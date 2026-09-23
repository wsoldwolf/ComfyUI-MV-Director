"""Separate event grounding from body planning, then audit both (offline only)."""

from __future__ import annotations

import argparse
from dataclasses import replace
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from core.inference import LlamaCppLifecycle, LlamaRuntimeConfig
from core.protocols.llm_records import parse_llm_records
from tools.offline_scene_event_performance_probe import (
    FIELDS, MODES, _fields, _infer, _quote, parse_plan,
)
from tools.offline_scene_semantic_audit_probe import PROMPT as AUDIT_PROMPT, grammar as audit_grammar, parse as parse_audit
from tools.offline_motion_template_input_probe import parse_motion_templates
from tools.offline_motion_template_pre_cue_probe import _saved_requests

SOURCE = ROOT / "docs/assets/research/choreography-full-run-v4-2026-09-22/evidence.json"
TEMPLATES = ROOT / "docs/assets/research/motion-template-input-probe-2026-09-22/motion_templates.emd.md"
SCENES = (11, 14)
EVENT_PROMPT = """あなたはアニメMVのSceneで起こる出来事だけを決める。身体振付候補や共通motion文は与えない。現在Sceneの原歌詞・作者指示だけを対象の根拠にし、背景scene_contextは配置の参考に限る。discovered_cuesのtargetは現在Sceneに選ばれた対象である。
MODEはnone/observe/contact/autonomous。歌詞に物への接触動詞がない場合は、対象を見せるobserveをまず検討し、接触を演出する必然がある時だけcontactを選ぶ。contactならCONTACT_POINTをTARGETの実際の部位として書き、CHANGEでもその部位へ人物が到達して触れる。床や別物へ作用して対象名だけ書くことは禁止。effectの発光体や狐火は人物の手から出さずautonomousで自律した出現・空間経路・結果を作る。TARGET以外の足音や歩行だけをCHANGEの主役にしない。
実TABで一行 EVENT、Scene番号、EVIDENCE=...｜TARGET=...｜MODE=...｜ANCHOR=...｜CONTACT_POINT=...｜CHANGE=...｜RESULT=...。根拠は現在の歌詞の連続引用。非contactならCONTACT_POINT=なし。説明やBODY行は書かない。"""
BODY_PROMPT = """あなたは既に確定したSceneのEVENTを変えず、人物の連続した身体演技だけを計画する。候補は任意の着想であり、選択・融合・改変・不使用ができる。身体の支持・骨盤・胸郭・左右の腕・視線を必要な範囲でSTART→PATH→ACCENT→ENDへ進める。毎Scene同じ候補全文を複写しない。対象、小道具、場所、接触の有無を候補から増やさない。SYNCにEVENT.CHANGEの一回の瞬間と人物の反応の関係を書く。外部自律の光は人物が発生・保持・操作せず、視線や身体で反応する。
実TABで一行 BODY、Scene番号、START=...｜PATH=...｜ACCENT=...｜END=...｜SYNC=...。各欄は短い具体文。EVENT行、説明、Markdownは出さない。"""


def _row_grammar(kind: str, scene: int) -> str:
    parts = [_quote(f"{kind}\t{scene}\t")]
    for index, field in enumerate(FIELDS[kind]):
        parts.append(_quote(("" if index == 0 else "｜") + field + "="))
        parts.append("mode" if field == "MODE" else "cell")
    return (
        "root ::= " + " ".join(parts) + ' "\\n"?\n'
        + "mode ::= " + " | ".join(_quote(item) for item in sorted(MODES)) + "\n"
        + r"cell ::= [^\x00-\x1f｜\\]{1,140}" + "\n"
    )


def _parse_row(raw: str, kind: str, scene: int) -> dict:
    parsed = parse_llm_records(raw, allowed_slots={kind: frozenset({scene})},
                               required=frozenset({(kind, scene)}))
    if parsed.issues or parsed.missing or len(parsed.records) != 1:
        return {"valid": False, "issues": [issue.reason for issue in parsed.issues],
                "missing": [list(item) for item in parsed.missing]}
    try:
        fields = _fields(parsed.records[0].text, FIELDS[kind])
    except ValueError as exc:
        return {"valid": False, "error": str(exc)}
    return {"valid": True, "fields": fields}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, default=SOURCE)
    parser.add_argument("--templates", type=Path, default=TEMPLATES)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--seeds", type=int, nargs="+", default=[42, 43])
    parser.add_argument("--retry-target-missing", action="store_true")
    args = parser.parse_args()
    source = json.loads(args.source.read_text(encoding="utf-8"))
    templates = parse_motion_templates(args.templates.read_text(encoding="utf-8"))
    saved = _saved_requests(source["trace"], "visual-beats")
    runtime = LlamaRuntimeConfig(**source["runtime"])
    evidence = {"source": str(args.source), "model": source["model"],
                "runtime": runtime.to_dict(), "event_prompt": EVENT_PROMPT,
                "body_prompt": BODY_PROMPT, "scenes": list(SCENES),
                "seeds": args.seeds, "runs": []}
    args.output.mkdir(parents=True, exist_ok=True)
    path = args.output / "evidence.json"
    lifecycle = LlamaCppLifecycle()
    try:
        lifecycle.ensure_loaded(Path(source["model"]), runtime)
        for seed in args.seeds:
            for scene in SCENES:
                original = json.loads(saved[scene]["payload"])
                slot = next(slot for slot in original["slots"] if slot["scene_number"] == scene)
                lyrics = [item["text"] for item in slot["lyrics"]]
                event_payload = {"scene_number": scene, "lyrics": slot["lyrics"],
                                 "author_body": slot.get("author_body", []),
                                 "discovered_cues": slot.get("discovered_cues", []),
                                 "scene_context": original.get("scene_context", {})}
                raw, tokens, elapsed = _infer(
                    lifecycle, replace(runtime, seed=seed, max_tokens=512),
                    system=EVENT_PROMPT, payload=event_payload,
                    grammar=_row_grammar("EVENT", scene),
                )
                event = _parse_row(raw, "EVENT", scene)
                item = {"seed": seed, "scene": scene, "event_input": event_payload,
                        "event_response": raw, "event": event,
                        "event_prompt_tokens": tokens, "event_elapsed_seconds": elapsed}
                if (args.retry_target_missing and event["valid"]
                        and event["fields"]["TARGET"] != "なし"
                        and event["fields"]["TARGET"] not in event["fields"]["CHANGE"]):
                    retry_payload = {**event_payload, "previous_rejected_event": raw,
                                     "repair_reason": "CHANGE must name TARGET and show the target itself or a person's visible relation to it; background sound or footsteps alone are insufficient"}
                    retry_prompt = EVENT_PROMPT + (
                        "\n前のEVENTは対象以外の出来事だけをCHANGEへ書いたので不採用。"
                        "CHANGEにはTARGETの原文の名詞句を含め、対象自体の見える変化又は人物と"
                        "対象の撮影できる関係を書く。足音や背景だけで済ませない。完全なEVENT一行を書き直す。"
                    )
                    retry_raw, retry_tokens, retry_elapsed = _infer(
                        lifecycle, replace(runtime, seed=seed, max_tokens=512),
                        system=retry_prompt, payload=retry_payload,
                        grammar=_row_grammar("EVENT", scene),
                    )
                    item["event_retry"] = {"payload": retry_payload, "response": retry_raw,
                                           "parsed": _parse_row(retry_raw, "EVENT", scene),
                                           "prompt_tokens": retry_tokens,
                                           "elapsed_seconds": retry_elapsed}
                    raw = retry_raw
                    event = item["event_retry"]["parsed"]
                item["event_final_response"] = raw
                item["event_final"] = event
                evidence["runs"].append(item)
                path.write_text(json.dumps(evidence, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
                print(f"seed={seed} scene={scene} event_valid={event['valid']} elapsed={elapsed}s", flush=True)
                if not event["valid"]:
                    continue
                item["target_named_in_change"] = (
                    event["fields"]["TARGET"] == "なし"
                    or event["fields"]["TARGET"] in event["fields"]["CHANGE"]
                )
                if args.retry_target_missing and not item["target_named_in_change"]:
                    path.write_text(json.dumps(evidence, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
                    print(f"seed={seed} scene={scene} target still missing in CHANGE", flush=True)
                    continue
                body_payload = {"scene_number": scene, "lyrics": lyrics,
                                "fixed_event": raw, "direction_motion": original["direction"]["motion"],
                                "motion_templates": list(templates)}
                body_raw, body_tokens, body_elapsed = _infer(
                    lifecycle, replace(runtime, seed=seed, max_tokens=512),
                    system=BODY_PROMPT, payload=body_payload,
                    grammar=_row_grammar("BODY", scene),
                )
                item.update({"body_input": body_payload, "body_response": body_raw,
                             "body": _parse_row(body_raw, "BODY", scene),
                             "body_prompt_tokens": body_tokens,
                             "body_elapsed_seconds": body_elapsed})
                if item["body"]["valid"]:
                    combined = raw.rstrip("\n") + "\n" + body_raw.rstrip("\n") + "\n"
                    item["combined_plan"] = combined
                    item["combined_parsed"] = parse_plan(combined, scene, lyrics)
                    audit_payload = {"scene_number": scene, "lyrics": lyrics,
                                     "plan": combined}
                    audit_raw, audit_tokens, audit_elapsed = _infer(
                        lifecycle, replace(runtime, seed=seed, max_tokens=128),
                        system=AUDIT_PROMPT, payload=audit_payload, grammar=audit_grammar(),
                    )
                    item["matrix_audit"] = {"response": audit_raw, "parsed": parse_audit(audit_raw),
                                            "prompt_tokens": audit_tokens,
                                            "elapsed_seconds": audit_elapsed}
                path.write_text(json.dumps(evidence, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
                print(f"seed={seed} scene={scene} body_valid={item['body']['valid']} "
                      f"matrix={item.get('matrix_audit', {}).get('parsed')}", flush=True)
    finally:
        lifecycle.clear()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
