"""Bind Cue evidence to its own source without a noun dictionary."""

import json
from collections.abc import Mapping, Sequence

from .action_constraints import _slots


def build_discovery_grammar(slots: Sequence[Mapping[str, object]]) -> str:
    _slots([s["slot"] for s in slots])
    quote = lambda text: json.dumps(text, ensure_ascii=False)
    rows, rules = [], []
    for slot in slots:
        text = slot["text"]
        if not isinstance(text, str) or not text or any(ord(c) < 32 for c in text):
            raise ValueError("Discovery requires nonempty single-line source text")
        prefix = f"l{slot['slot']}"
        for offset, char in enumerate(text):
            tail = f" {prefix}-c{offset+1}?" if offset+1 < len(text) else ""
            rules.append(f"{prefix}-c{offset} ::= {quote(char)}{tail}")
        rules.append(f"{prefix}-target ::= " + " | ".join(f"{prefix}-c{k}" for k in range(len(text))))
        rows.append(quote(f"DISCOVERY\t{slot['slot']}\t") +
                    f' ("none|なし" | ("motif|" | "effect|" | "place|" | "body|") {prefix}-target)')
    return "root ::= " + ' "\\n" '.join(rows) + ' "\\n"?\n' + "\n".join(rules) + "\n"


def parse_discovery(text: str, source: str) -> dict[str, str] | None:
    kind, separator, target = text.partition("|")
    if kind == "none" and target == "なし":
        return None
    if not separator or kind not in {"motif", "effect", "place", "body"} or not target or target not in source:
        raise ValueError("Discovery target must be an exact span of its source")
    return {"kind": kind, "target": target, "evidence": source}


def select_scene_cue(sources: Sequence[str], discoveries: Mapping[str, dict[str, str] | None]) -> list[dict[str, str]]:
    """Prefer the latest material cue reached by the lyrics, not an opening setting.

    Classification/target strings are LLM-authored. Python only assigns source
    order; it neither creates a noun nor composes the resulting event.
    """
    candidates = [discoveries[s] for s in sources if discoveries.get(s)
                  and discoveries[s]["kind"] in {"motif", "effect", "place"}]
    return [dict(candidates[-1])] if candidates else []


def build_grounded_cue_grammar(slots: Sequence[Mapping[str, object]]) -> str:
    """Nine unchanged fields; evidence and target share a source branch.

    Suffix rules encode all nonempty contiguous substrings in linear rule
    count, instead of enumerating a quadratic vocabulary of guessed nouns.
    This is lexical provenance only, not a semantic classifier.
    """
    _slots([s["slot"] for s in slots])
    quote = lambda text: json.dumps(text, ensure_ascii=False)
    rules = [r"cell ::= [^\x00-\x1f｜]+"]
    rows = []
    tail = ('"｜接触=" ("禁止" | "許可") "｜現象=" '
            '("なし" | "外部自律" | "身体操作") "｜配置=" cell '
            '"｜可視展開=" cell "｜身体主導=" cell "｜終端=" cell')
    none = quote("なし｜根拠=なし｜感情=") + ' cell ' + quote("｜接触=禁止｜現象=なし｜配置=なし｜可視展開=なし｜身体主導=") + ' cell "｜終端=" cell'
    for slot in slots:
        number = slot["slot"]
        sources = [str(item.get("text", "")).strip() for item in slot.get("lyrics", [])
                   if isinstance(item, Mapping)]
        sources += [str(item).strip() for item in slot.get("author_body", [])]
        sources = list(dict.fromkeys(s for s in sources if s))
        candidates = slot.get("discovered_cues")
        alternatives = [] if candidates else [none]
        for index, source in enumerate(sources):
            if "｜" in source or any(ord(c) < 32 for c in source):
                raise ValueError("Cue sources must be single-line text without the field separator")
            prefix = f"s{number}-l{index}"
            if candidates is not None:
                for candidate in candidates:
                    target = candidate["target"]
                    if candidate["evidence"] == source and target and target in source:
                        # Keep the identity in the transferable spatial clause;
                        # the LLM still supplies the location and event verb.
                        anchored_tail = tail.replace('"｜配置=" cell', quote("｜配置=" + target) + ' cell')
                        alternatives.append(quote(target + "｜根拠=" + source + "｜感情=") + " cell " + anchored_tail)
                continue
            for offset, char in enumerate(source):
                continuation = f" {prefix}-c{offset + 1}?" if offset + 1 < len(source) else ""
                rules.append(f"{prefix}-c{offset} ::= {quote(char)}{continuation}")
            rules.append(f"{prefix}-target ::= " + " | ".join(f"{prefix}-c{k}" for k in range(len(source))))
            alternatives.append(f"{prefix}-target " + quote("｜根拠=" + source + "｜感情=") + " cell " + tail)
        if not alternatives:
            raise ValueError("Discovered Cue candidates must belong to the current source")
        rules.append(f"s{number}-grounding ::= " + " | ".join(alternatives))
        rows.append(quote(f"BEAT\t{number}\t対象=") + f" s{number}-grounding")
    return "root ::= " + ' "\\n" '.join(rows) + ' "\\n"?\n' + "\n".join(rules) + "\n"
