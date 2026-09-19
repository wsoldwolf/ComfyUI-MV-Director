"""Strict line-oriented PromptTranslator backed by a loaded llama.cpp model."""

from __future__ import annotations

from collections.abc import Sequence
import json
import logging
import re
from typing import Any

from ..artifacts import canonical_json, normalize_newlines
from ..inference import (
    ContextBudgetError,
    LlamaCppLifecycle,
    LlamaRuntimeConfig,
    build_context_budget,
)
from ..protocols import parse_llm_records
from .errors import CompilerError


TRANSLATION_PROMPT_VERSION = "mvd-prompt-translation-ja-en-v11"
TRANSLATION_RECORD_TYPE = "TRANSLATION"
TRANSLATION_MAX_BATCH_UNITS = 7
TRANSLATION_RECOVERY_CHUNK_CHARS = 120
TRANSLATION_PROACTIVE_SPLIT_CHARS = 360
_JAPANESE_SCRIPT_RE = re.compile(r"[\u3040-\u30ff\u3400-\u9fff]")
_JAPANESE_SPAN_RE = re.compile(r"[\u3040-\u30ff\u3400-\u9fff]+")
_LOGGER = logging.getLogger("mv_director.compiler")


def _normalize_small_model_response(response: str) -> str:
    """Normalize observed Qwen3-4B separators without changing slot identity."""

    normalized = normalize_newlines(response)
    normalized = re.sub(r"<think>.*?</think>", "", normalized, flags=re.DOTALL)
    normalized = "\n".join(
        line
        for line in normalized.split("\n")
        if line.strip()
        not in {
            "TRANSLATION<TAB>SLOT<TAB>ENGLISH_TEXT",
            "TRANSLATION\tSLOT\tENGLISH_TEXT",
        }
    )
    labelled_slot_line = re.compile(
        r"^TRANSLATION\t(?:TAB\t)?slot\s+([0-9]+)\t(?:TAB\t)?(.+)$",
        flags=re.MULTILINE | re.IGNORECASE,
    )
    normalized = labelled_slot_line.sub(
        lambda match: f"{TRANSLATION_RECORD_TYPE}\t{match.group(1)}\t{match.group(2)}",
        normalized,
    )
    literal_tab_line = re.compile(
        r"^[^\n]*?<TAB>([0-9]+)<TAB>(.+)$",
        flags=re.MULTILINE,
    )
    normalized = literal_tab_line.sub(
        lambda match: f"{TRANSLATION_RECORD_TYPE}\t{match.group(1)}\t{match.group(2)}",
        normalized,
    )
    tab_label_line = re.compile(
        r"^[^\n\t]*\tTAB\t([0-9]+)\tTAB\t(.+)$",
        flags=re.MULTILINE,
    )
    normalized = tab_label_line.sub(
        lambda match: f"{TRANSLATION_RECORD_TYPE}\t{match.group(1)}\t{match.group(2)}",
        normalized,
    )
    normalized = re.sub(
        r"\tTRANSLATION\t([0-9]+)\t",
        r"\nTRANSLATION\t\1\t",
        normalized,
    )
    return normalized


def _recover_isolated_translation(response: str) -> str | None:
    """Recover one unambiguous translation from a one-slot retry.

    This adapter is intentionally unavailable to multi-slot batches. It
    removes only structural wrappers and returns the model's text AS IS.
    """

    normalized = normalize_newlines(response)
    normalized = re.sub(r"<think>.*?</think>", "", normalized, flags=re.DOTALL)
    stripped = normalized.strip()
    if not stripped:
        return None

    fenced = re.sub(r"^\x60\x60\x60(?:json|text)?\s*\n?", "", stripped, flags=re.IGNORECASE)
    fenced = re.sub(r"\n?\x60\x60\x60$", "", fenced).strip()
    try:
        value = json.loads(fenced)
    except (TypeError, ValueError):
        value = None
    if isinstance(value, dict):
        slot = value.get("slot", 1)
        if slot not in {1, "1"}:
            return None
        candidates = [
            value[key].strip()
            for key in ("translation", "english_text", "text")
            if isinstance(value.get(key), str) and value[key].strip()
        ]
        if len(candidates) == 1:
            return candidates[0]
        return None
    if isinstance(value, list) and len(value) == 1 and isinstance(value[0], str):
        return value[0].strip() or None

    lines = [
        line.strip()
        for line in fenced.split("\n")
        if line.strip()
        and line.strip().lower()
        not in {
            "translation:",
            "english translation:",
            "translation",
            "english translation",
        }
    ]
    if len(lines) != 1:
        return None
    text = re.sub(r"^[-*]\s+", "", lines[0], count=1).strip()
    explicit = re.fullmatch(
        r"TRANSLATION\s+(?:slot\s*)?1\s*(?::|[-–—])?\s+(.+)",
        text,
        flags=re.IGNORECASE,
    )
    if explicit:
        text = explicit.group(1).strip()
    else:
        labelled = re.fullmatch(
            r"(?:TRANSLATION|English translation)\s*:\s*(.+)",
            text,
            flags=re.IGNORECASE,
        )
        if labelled:
            text = labelled.group(1).strip()
    if (
        not text
        or text.startswith(("#", "{", "["))
        or re.match(r"^TRANSLATION(?:\s|\t|:|$)", text, flags=re.IGNORECASE)
    ):
        return None
    return text


def _translation_recovery_chunks(text: str) -> tuple[str, ...]:
    """Split one long failed unit at existing Japanese prose boundaries.

    The splitter neither rewrites nor drops source text. It is used only after
    the intact unit and its isolated retry both returned non-English text.
    """

    if len(text) <= TRANSLATION_RECOVERY_CHUNK_CHARS:
        return (text,)

    def split_after(pattern: str, value: str) -> list[str]:
        pieces: list[str] = []
        cursor = 0
        for match in re.finditer(pattern, value):
            pieces.append(value[cursor : match.end()])
            cursor = match.end()
        if cursor < len(value):
            pieces.append(value[cursor:])
        return [piece for piece in pieces if piece]

    sentence_pieces = split_after(r"[。！？]+", text)
    atomic: list[str] = []
    for piece in sentence_pieces:
        if len(piece) <= TRANSLATION_RECOVERY_CHUNK_CHARS:
            atomic.append(piece)
            continue
        clause_pieces = split_after(r"[、，,；;]+", piece)
        atomic.extend(clause_pieces if len(clause_pieces) > 1 else (piece,))

    chunks: list[str] = []
    current = ""
    for piece in atomic:
        if current and len(current) + len(piece) > TRANSLATION_RECOVERY_CHUNK_CHARS:
            chunks.append(current)
            current = ""
        current += piece
    if current:
        chunks.append(current)
    if len(chunks) <= 1 or "".join(chunks) != text:
        return (text,)
    return tuple(chunks)


def _is_mostly_english_with_residual_japanese(text: str) -> bool:
    japanese_count = len(_JAPANESE_SCRIPT_RE.findall(text))
    latin_count = len(re.findall(r"[A-Za-z]", text))
    return japanese_count > 0 and latin_count >= max(12, japanese_count * 2)


class LlamaPromptTranslator:
    """Translate ordered units with one isolated retry for missing slots."""

    def __init__(
        self,
        lifecycle: LlamaCppLifecycle,
        *,
        system_prompt: str,
        runtime_config: LlamaRuntimeConfig,
        interrupt_callback: Any = None,
    ) -> None:
        if not isinstance(system_prompt, str) or not system_prompt.strip():
            raise CompilerError("translation system prompt must not be empty")
        runtime_config.validate()
        self.lifecycle = lifecycle
        self.system_prompt = system_prompt.rstrip() + "\n"
        self.runtime_config = runtime_config
        self.interrupt_callback = interrupt_callback
        self.batch_count = 0
        self.estimated_token_batches = 0
        self.protocol_recovered_count = 0
        self.segmented_recovered_count = 0
        self.cleanup_recovered_count = 0

    @staticmethod
    def _payload(units: Sequence[str]) -> str:
        return canonical_json(
            {
                "protocol": "MVD_LLM_RECORDS_V1",
                "task": "translation-ja-en",
                "instruction": (
                    "Translate each slots[].japanese_text value into English. "
                    "The output text field must be English, never the slot number "
                    "or the Japanese source. Preserve concrete local visual "
                    "geometry, including shape, count, placement, scale, color, "
                    "material, and exclusions; never generalize an unusual "
                    "identity feature into a conventional default."
                ),
                "slots": [
                    {"slot": index, "japanese_text": text}
                    for index, text in enumerate(units, 1)
                ],
            }
        )

    def _check_budget(self, units: Sequence[str]) -> bool:
        payload = f"/no_think\n{self._payload(units)}"
        count = self.lifecycle.count_serialized_prompt(
            self.system_prompt + "\n" + payload
        )
        try:
            build_context_budget(
                count.count,
                self.runtime_config.max_tokens,
                self.lifecycle.effective_n_ctx or self.runtime_config.n_ctx,
                estimated=count.estimated,
            )
        except ContextBudgetError:
            return False
        return True

    def _largest_batch(self, remaining: Sequence[str]) -> int:
        accepted = 0
        for size in range(1, min(len(remaining), TRANSLATION_MAX_BATCH_UNITS) + 1):
            if not self._check_budget(remaining[:size]):
                break
            accepted = size
        if accepted:
            return accepted

        payload = f"/no_think\n{self._payload(remaining[:1])}"
        count = self.lifecycle.count_serialized_prompt(
            self.system_prompt + "\n" + payload
        )
        build_context_budget(
            count.count,
            self.runtime_config.max_tokens,
            self.lifecycle.effective_n_ctx or self.runtime_config.n_ctx,
            estimated=count.estimated,
        )
        raise AssertionError("unreachable context budget state")

    def _complete_units(self, units: Sequence[str]) -> str:
        payload = f"/no_think\n{self._payload(units)}"
        count = self.lifecycle.count_serialized_prompt(
            self.system_prompt + "\n" + payload
        )
        build_context_budget(
            count.count,
            self.runtime_config.max_tokens,
            self.lifecycle.effective_n_ctx or self.runtime_config.n_ctx,
            estimated=count.estimated,
        )
        response = self.lifecycle.complete_chat(
            [
                {"role": "system", "content": self.system_prompt},
                {"role": "user", "content": payload},
            ],
            self.runtime_config,
            interrupt_callback=self.interrupt_callback,
        )
        self.batch_count += 1
        if count.estimated:
            self.estimated_token_batches += 1
        return response

    @staticmethod
    def _english_text_by_slot(
        parsed: Any,
        *,
        displayed_slots: Sequence[int],
    ) -> dict[int, str]:
        by_slot = {record.slot: record.text for record in parsed.records}
        non_english = [
            slot
            for slot, text in by_slot.items()
            if _JAPANESE_SCRIPT_RE.search(text) or text.strip() == str(slot)
        ]
        if non_english:
            labels = ",".join(
                str(displayed_slots[slot - 1]) for slot in sorted(non_english)
            )
            raise CompilerError(
                "translation response is not English for slots: " + labels
            )
        return by_slot

    @staticmethod
    def _non_english_slots(parsed: Any) -> tuple[int, ...]:
        return tuple(
            sorted(
                record.slot
                for record in parsed.records
                if _JAPANESE_SCRIPT_RE.search(record.text)
                or record.text.strip() == str(record.slot)
            )
        )

    @staticmethod
    def _protocol_error(parsed: Any) -> CompilerError:
        reasons = ",".join(issue.reason for issue in parsed.issues) or "none"
        missing = ",".join(str(slot) for _, slot in parsed.missing) or "none"
        return CompilerError(
            "translation response does not match the line protocol: "
            f"issues={reasons}; missing_slots={missing}"
        )

    @staticmethod
    def _duplicate_conflict_slots(
        normalized_response: str,
        allowed_slots: frozenset[int],
    ) -> tuple[int, ...]:
        texts: dict[int, list[str]] = {}
        for raw_line in normalized_response.split("\n"):
            fields = raw_line.split("\t", 2)
            if len(fields) != 3 or fields[0] != TRANSLATION_RECORD_TYPE:
                continue
            slot_text, text = fields[1], fields[2].replace("\t", " ").strip()
            if not slot_text.isascii() or not slot_text.isdecimal() or not text:
                continue
            slot = int(slot_text)
            if slot not in allowed_slots:
                continue
            texts.setdefault(slot, []).append(text)
        return tuple(
            sorted(
                slot
                for slot, values in texts.items()
                if len(values) > 1 and len(set(values)) > 1
            )
        )

    @classmethod
    def _validate_protocol_issues(
        cls,
        parsed: Any,
        *,
        duplicate_conflict_slots: Sequence[int] = (),
        allow_conflicting_duplicates: bool = True,
    ) -> None:
        if not parsed.issues:
            return
        harmless_reasons = {"field_count", "unknown_type", "duplicate"}
        reasons = {issue.reason for issue in parsed.issues}
        if (
            not parsed.missing
            and reasons <= harmless_reasons
            and (allow_conflicting_duplicates or not duplicate_conflict_slots)
        ):
            counts = ",".join(
                f"{reason}={sum(issue.reason == reason for issue in parsed.issues)}"
                for reason in sorted(reasons)
            )
            _LOGGER.warning(
                "[MV Director - EMD Compiler (Ref2VA)] recovered complete "
                "translation records with extra output; issues=%s; "
                "conflicting_duplicate_slots=%s",
                counts,
                ",".join(str(slot) for slot in duplicate_conflict_slots) or "none",
            )
            return
        if not parsed.missing:
            raise cls._protocol_error(parsed)

    def _translate_batch(
        self,
        units: Sequence[str],
        *,
        displayed_slots: Sequence[int],
        allow_segmented_recovery: bool = True,
        allow_cleanup: bool = True,
    ) -> tuple[str, ...]:
        response = self._complete_units(units)
        slots = frozenset(range(1, len(units) + 1))
        normalized_response = _normalize_small_model_response(response)
        parsed = parse_llm_records(
            normalized_response,
            allowed_slots={TRANSLATION_RECORD_TYPE: slots},
            required=frozenset((TRANSLATION_RECORD_TYPE, slot) for slot in slots),
        )
        duplicate_conflict_slots = set(
            self._duplicate_conflict_slots(normalized_response, slots)
        )
        self._validate_protocol_issues(
            parsed,
            duplicate_conflict_slots=tuple(sorted(duplicate_conflict_slots)),
        )

        by_slot = {record.slot: record.text for record in parsed.records}
        missing_slots = {slot for _, slot in parsed.missing}
        non_english_slots = set(self._non_english_slots(parsed))
        retry_slots = sorted(
            missing_slots | non_english_slots | duplicate_conflict_slots
        )
        if non_english_slots:
            labels = ",".join(
                str(displayed_slots[slot - 1])
                for slot in sorted(non_english_slots)
            )
            _LOGGER.info(
                "[MV Director - EMD Compiler (Ref2VA)] retrying non-English "
                "translation slots in isolation: %s",
                labels,
            )
        if duplicate_conflict_slots:
            labels = ",".join(
                str(displayed_slots[slot - 1])
                for slot in sorted(duplicate_conflict_slots)
            )
            _LOGGER.info(
                "[MV Director - EMD Compiler (Ref2VA)] retrying conflicting "
                "duplicate translation slots in isolation: %s",
                labels,
            )

        for retry_slot in retry_slots:
            displayed_slot = displayed_slots[retry_slot - 1]
            source_unit = units[retry_slot - 1]
            first_candidate = by_slot.get(retry_slot, "")
            if allow_cleanup and _is_mostly_english_with_residual_japanese(
                first_candidate
            ):
                cleaned = self._cleanup_mixed_translation(
                    first_candidate,
                    displayed_slot=displayed_slot,
                )
                if cleaned is not None:
                    by_slot[retry_slot] = cleaned
                    continue
            _LOGGER.info(
                "[MV Director - EMD Compiler (Ref2VA)] isolated translation "
                "retry started; slot=%d; source_chars=%d; reason=%s",
                displayed_slot,
                len(source_unit),
                "non_english"
                if retry_slot in non_english_slots
                else "duplicate_conflict"
                if retry_slot in duplicate_conflict_slots
                else "missing",
            )
            retry_response = self._complete_units((units[retry_slot - 1],))
            normalized_retry = _normalize_small_model_response(retry_response)
            retry = parse_llm_records(
                normalized_retry,
                allowed_slots={TRANSLATION_RECORD_TYPE: frozenset({1})},
                required=frozenset({(TRANSLATION_RECORD_TYPE, 1)}),
            )
            retry_duplicate_conflicts = self._duplicate_conflict_slots(
                normalized_retry,
                frozenset({1}),
            )
            retry_reasons = {issue.reason for issue in retry.issues}
            recovered_text = (
                _recover_isolated_translation(retry_response)
                if retry.missing and retry_reasons <= {"field_count"}
                else None
            )
            if recovered_text is not None:
                if (
                    _JAPANESE_SCRIPT_RE.search(recovered_text)
                    or recovered_text.strip() == "1"
                ):
                    cleaned = self._cleanup_mixed_translation(
                        recovered_text,
                        displayed_slot=displayed_slot,
                    ) if allow_cleanup else None
                    if cleaned is not None:
                        by_slot[retry_slot] = cleaned
                        continue
                    segmented = self._recover_segmented_unit(
                        source_unit,
                        displayed_slot=displayed_slot,
                        allow=allow_segmented_recovery,
                        trigger="after_isolated_retry",
                    )
                    if segmented is None:
                        raise CompilerError(
                            "translation response is not English after isolated "
                            f"retry for slot {displayed_slot}"
                        )
                    by_slot[retry_slot] = segmented
                    continue
                by_slot[retry_slot] = recovered_text
                self.protocol_recovered_count += 1
                _LOGGER.warning(
                    "[MV Director - EMD Compiler (Ref2VA)] recovered bare "
                    "one-to-one translation after isolated retry for slot %d",
                    displayed_slots[retry_slot - 1],
                )
                continue
            try:
                self._validate_protocol_issues(
                    retry,
                    duplicate_conflict_slots=retry_duplicate_conflicts,
                    allow_conflicting_duplicates=False,
                )
            except CompilerError as exc:
                raise CompilerError(
                    "translation response does not match the line protocol after "
                    "isolated retry for slot "
                    f"{displayed_slots[retry_slot - 1]}: "
                    f"{exc}"
                ) from exc
            if retry.missing:
                raise CompilerError(
                    "translation response does not match the line protocol after "
                    "isolated retry for slot "
                    f"{displayed_slots[retry_slot - 1]}: "
                    f"{self._protocol_error(retry)}"
                )
            try:
                retry_by_slot = self._english_text_by_slot(
                    retry,
                    displayed_slots=(displayed_slots[retry_slot - 1],),
                )
            except CompilerError as exc:
                retry_candidate = {
                    record.slot: record.text for record in retry.records
                }.get(1, "")
                cleaned = self._cleanup_mixed_translation(
                    retry_candidate,
                    displayed_slot=displayed_slot,
                ) if allow_cleanup else None
                if cleaned is not None:
                    by_slot[retry_slot] = cleaned
                    continue
                segmented = self._recover_segmented_unit(
                    source_unit,
                    displayed_slot=displayed_slot,
                    allow=allow_segmented_recovery,
                    trigger="after_isolated_retry",
                )
                if segmented is None:
                    raise CompilerError(
                        "translation response is not English after isolated retry "
                        f"for slot {displayed_slot}"
                    ) from exc
                by_slot[retry_slot] = segmented
                continue
            by_slot[retry_slot] = retry_by_slot[1]

        if not retry_slots:
            self._english_text_by_slot(
                parsed,
                displayed_slots=displayed_slots,
            )

        return tuple(by_slot[slot] for slot in range(1, len(units) + 1))

    def _cleanup_mixed_translation(
        self,
        candidate: str,
        *,
        displayed_slot: int,
    ) -> str | None:
        if not _is_mostly_english_with_residual_japanese(candidate):
            return None
        residual_count = len(_JAPANESE_SCRIPT_RE.findall(candidate))
        residual_spans = tuple(dict.fromkeys(_JAPANESE_SPAN_RE.findall(candidate)))
        _LOGGER.info(
            "[MV Director - EMD Compiler (Ref2VA)] residual-Japanese cleanup "
            "started; slot=%d; candidate_chars=%d; residual_chars=%d; spans=%d",
            displayed_slot,
            len(candidate),
            residual_count,
            len(residual_spans),
        )
        if not residual_spans:
            return None
        try:
            translated_spans = self._translate_batch(
                residual_spans,
                displayed_slots=(displayed_slot,) * len(residual_spans),
                allow_segmented_recovery=False,
                allow_cleanup=False,
            )
        except CompilerError:
            _LOGGER.info(
                "[MV Director - EMD Compiler (Ref2VA)] residual-Japanese cleanup "
                "failed; slot=%d",
                displayed_slot,
            )
            return None
        replacements = dict(zip(residual_spans, translated_spans))

        def replace_span(match: re.Match[str]) -> str:
            replacement = replacements[match.group(0)].strip()
            if not replacement:
                return match.group(0)
            if (
                match.start() > 0
                and candidate[match.start() - 1].isascii()
                and candidate[match.start() - 1].isalnum()
                and replacement[0].isascii()
                and replacement[0].isalnum()
            ):
                replacement = " " + replacement
            if (
                match.end() < len(candidate)
                and candidate[match.end()].isascii()
                and candidate[match.end()].isalnum()
                and replacement[-1].isascii()
                and replacement[-1].isalnum()
            ):
                replacement += " "
            return replacement

        translated = _JAPANESE_SPAN_RE.sub(replace_span, candidate).strip()
        if _JAPANESE_SCRIPT_RE.search(translated):
            _LOGGER.info(
                "[MV Director - EMD Compiler (Ref2VA)] residual-Japanese cleanup "
                "failed; slot=%d; reason=non_english_output",
                displayed_slot,
            )
            return None
        self.cleanup_recovered_count += 1
        _LOGGER.info(
            "[MV Director - EMD Compiler (Ref2VA)] residual-Japanese cleanup "
            "completed; slot=%d; output_chars=%d",
            displayed_slot,
            len(translated),
        )
        return translated

    def _recover_segmented_unit(
        self,
        source: str,
        *,
        displayed_slot: int,
        allow: bool,
        trigger: str,
    ) -> str | None:
        if not allow:
            return None
        chunks = _translation_recovery_chunks(source)
        if len(chunks) <= 1:
            _LOGGER.info(
                "[MV Director - EMD Compiler (Ref2VA)] segmented translation "
                "recovery unavailable; slot=%d; source_chars=%d; reason=no_safe_boundaries",
                displayed_slot,
                len(source),
            )
            return None
        _LOGGER.info(
            "[MV Director - EMD Compiler (Ref2VA)] segmented translation "
            "recovery started; slot=%d; trigger=%s; source_chars=%d; chunks=%d; "
            "chunk_chars=%s",
            displayed_slot,
            trigger,
            len(source),
            len(chunks),
            ",".join(str(len(chunk)) for chunk in chunks),
        )
        translated_chunks: list[str] = []
        position = 0
        try:
            while position < len(chunks):
                batch_size = self._largest_batch(chunks[position:])
                _LOGGER.info(
                    "[MV Director - EMD Compiler (Ref2VA)] segmented translation "
                    "batch; slot=%d; chunks=%d..%d/%d",
                    displayed_slot,
                    position + 1,
                    position + batch_size,
                    len(chunks),
                )
                translated_chunks.extend(
                    self._translate_batch(
                        chunks[position : position + batch_size],
                        displayed_slots=(displayed_slot,) * batch_size,
                        allow_segmented_recovery=False,
                    )
                )
                position += batch_size
        except CompilerError:
            _LOGGER.info(
                "[MV Director - EMD Compiler (Ref2VA)] segmented translation "
                "recovery failed; slot=%d; completed_chunks=%d/%d",
                displayed_slot,
                position,
                len(chunks),
            )
            raise
        translated = " ".join(chunk.strip() for chunk in translated_chunks if chunk.strip())
        if not translated or _JAPANESE_SCRIPT_RE.search(translated):
            _LOGGER.info(
                "[MV Director - EMD Compiler (Ref2VA)] segmented translation "
                "recovery failed; slot=%d; reason=non_english_output",
                displayed_slot,
            )
            return None
        self.segmented_recovered_count += 1
        _LOGGER.info(
            "[MV Director - EMD Compiler (Ref2VA)] segmented translation "
            "recovery completed; slot=%d; chunks=%d; output_chars=%d",
            displayed_slot,
            len(chunks),
            len(translated),
        )
        return translated

    def translate(self, units: Sequence[str]) -> Sequence[str]:
        if not units:
            return ()
        if any(not isinstance(unit, str) or not unit.strip() for unit in units):
            raise CompilerError("translation units must be nonempty strings")
        result: list[str] = []
        position = 0
        while position < len(units):
            unit = units[position]
            proactive_chunks = (
                _translation_recovery_chunks(unit)
                if len(unit) > TRANSLATION_PROACTIVE_SPLIT_CHARS
                else (unit,)
            )
            if len(proactive_chunks) > 1:
                translated = self._recover_segmented_unit(
                    unit,
                    displayed_slot=position + 1,
                    allow=True,
                    trigger="proactive_long_unit",
                )
                if translated is None:
                    raise CompilerError(
                        "long translation unit could not be segmented safely for "
                        f"slot {position + 1}"
                    )
                result.append(translated)
                position += 1
                continue

            run_end = position + 1
            while run_end < len(units):
                candidate = units[run_end]
                if (
                    len(candidate) > TRANSLATION_PROACTIVE_SPLIT_CHARS
                    and len(_translation_recovery_chunks(candidate)) > 1
                ):
                    break
                run_end += 1
            batch_size = self._largest_batch(units[position:run_end])
            result.extend(
                self._translate_batch(
                    units[position : position + batch_size],
                    displayed_slots=tuple(
                        range(position + 1, position + batch_size + 1)
                    ),
                )
            )
            position += batch_size
        return tuple(result)
