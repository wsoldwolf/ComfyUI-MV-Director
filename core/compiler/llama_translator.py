"""Strict line-oriented PromptTranslator backed by a loaded llama.cpp model."""

from __future__ import annotations

from collections.abc import Sequence
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


TRANSLATION_PROMPT_VERSION = "mvd-prompt-translation-ja-en-v7"
TRANSLATION_RECORD_TYPE = "TRANSLATION"
TRANSLATION_MAX_BATCH_UNITS = 7
_JAPANESE_SCRIPT_RE = re.compile(r"[\u3040-\u30ff\u3400-\u9fff]")
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

    @staticmethod
    def _payload(units: Sequence[str]) -> str:
        return canonical_json(
            {
                "protocol": "MVD_LLM_RECORDS_V1",
                "task": "translation-ja-en",
                "instruction": (
                    "Translate each slots[].japanese_text value into English. "
                    "The output text field must be English, never the slot number "
                    "or the Japanese source."
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
                raise CompilerError(
                    "translation response is not English after isolated retry "
                    f"for slot {displayed_slots[retry_slot - 1]}"
                ) from exc
            by_slot[retry_slot] = retry_by_slot[1]

        if not retry_slots:
            self._english_text_by_slot(
                parsed,
                displayed_slots=displayed_slots,
            )

        return tuple(by_slot[slot] for slot in range(1, len(units) + 1))

    def translate(self, units: Sequence[str]) -> Sequence[str]:
        if not units:
            return ()
        if any(not isinstance(unit, str) or not unit.strip() for unit in units):
            raise CompilerError("translation units must be nonempty strings")
        result: list[str] = []
        position = 0
        while position < len(units):
            batch_size = self._largest_batch(units[position:])
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
