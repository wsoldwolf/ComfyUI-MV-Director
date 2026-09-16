"""Strict line-oriented PromptTranslator backed by a loaded llama.cpp model."""

from __future__ import annotations

from collections.abc import Sequence
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


TRANSLATION_PROMPT_VERSION = "mvd-prompt-translation-ja-en-v2"
TRANSLATION_RECORD_TYPE = "TRANSLATION"


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
    """Translate ordered units without repair, semantic review, or retry."""

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
                "slots": [
                    {"slot": index, "text": text}
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
        for size in range(1, len(remaining) + 1):
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

    def _translate_batch(self, units: Sequence[str]) -> tuple[str, ...]:
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
        slots = frozenset(range(1, len(units) + 1))
        parsed = parse_llm_records(
            _normalize_small_model_response(response),
            allowed_slots={TRANSLATION_RECORD_TYPE: slots},
            required=frozenset((TRANSLATION_RECORD_TYPE, slot) for slot in slots),
        )
        if parsed.issues or parsed.missing:
            reasons = ",".join(issue.reason for issue in parsed.issues) or "none"
            missing = ",".join(str(slot) for _, slot in parsed.missing) or "none"
            raise CompilerError(
                "translation response does not match the line protocol: "
                f"issues={reasons}; missing_slots={missing}"
            )
        by_slot = {record.slot: record.text for record in parsed.records}
        self.batch_count += 1
        if count.estimated:
            self.estimated_token_batches += 1
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
            result.extend(self._translate_batch(units[position : position + batch_size]))
            position += batch_size
        return tuple(result)
