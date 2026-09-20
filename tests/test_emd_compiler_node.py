from __future__ import annotations

import json
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from core.compiler import CompilerError, LlamaPromptTranslator
from core.compiler.llama_translator import (
    _isolated_english_candidates,
    _recover_isolated_translation,
)
from core.emd import EMDParseError
from core.inference import LlamaRuntimeConfig, SuccessCache, TokenCount
from nodes import NODE_CLASS_MAPPINGS, NODE_DISPLAY_NAME_MAPPINGS


ENGLISH_EMD = """# サブジェクト
* A person wearing a white coat.
> `シーン` 1
# シーン 00:00.000 --> 00:01.000
* `H3長` 22
## ショット 00:00.000
* The person walks forward.
"""


class FakeLifecycle:
    def __init__(
        self,
        *,
        invalid_response: bool = False,
        small_model_format: bool = False,
        japanese_response: bool = False,
        japanese_response_once: bool = False,
        invalid_last_slot_once: bool = False,
        invalid_last_slot_always: bool = False,
        unknown_type_response: bool = False,
        duplicate_response: bool = False,
        conflicting_duplicate_once: bool = False,
        conflicting_duplicate_always: bool = False,
        unknown_slot_response: bool = False,
        bare_isolated_response: bool = False,
        ambiguous_isolated_response: bool = False,
        japanese_min_chars: int | None = None,
        mixed_japanese_response: bool = False,
    ) -> None:
        self.effective_n_ctx = 1120
        self.invalid_response = invalid_response
        self.small_model_format = small_model_format
        self.japanese_response = japanese_response
        self.japanese_response_once = japanese_response_once
        self.invalid_last_slot_once = invalid_last_slot_once
        self.invalid_last_slot_always = invalid_last_slot_always
        self.unknown_type_response = unknown_type_response
        self.duplicate_response = duplicate_response
        self.conflicting_duplicate_once = conflicting_duplicate_once
        self.conflicting_duplicate_always = conflicting_duplicate_always
        self.unknown_slot_response = unknown_slot_response
        self.bare_isolated_response = bare_isolated_response
        self.ambiguous_isolated_response = ambiguous_isolated_response
        self.japanese_min_chars = japanese_min_chars
        self.mixed_japanese_response = mixed_japanese_response
        self.invalid_last_slot_used = False
        self.chat_calls: list[dict[str, object]] = []
        self.ensure_calls = 0
        self.clear_calls = 0

    def count_serialized_prompt(self, prompt: str) -> TokenCount:
        return TokenCount(10 + prompt.count('"slot":') * 20, False)

    def complete_chat(self, messages, config, interrupt_callback=None):
        content = messages[-1]["content"]
        if not content.startswith("/no_think\n"):
            raise AssertionError("translation request must disable thinking")
        payload = json.loads(content.removeprefix("/no_think\n"))
        self.chat_calls.append(payload)
        if len(self.chat_calls) > 1 and len(payload["slots"]) == 1:
            if self.bare_isolated_response:
                return "Recovered English translation"
            if self.ambiguous_isolated_response:
                return "First possible translation\nSecond possible translation"
        if self.small_model_format:
            rows = [
                f"source<TAB>{item['slot']}<TAB>English {item['slot']}"
                for item in payload["slots"]
            ]
            return (
                "<think>translate every slot</think>\n"
                "TRANSLATION<TAB>SLOT<TAB>ENGLISH_TEXT\n"
                + "\n".join(rows)
            )
        if self.mixed_japanese_response:
            return "\n".join(
                f"TRANSLATION\t{item['slot']}\t"
                + (
                    "screen"
                    if item["japanese_text"] == "画面"
                    else "Draw the 画面 as a continuous composition"
                )
                for item in payload["slots"]
            )
        if self.japanese_response or (
            self.japanese_response_once and len(self.chat_calls) == 1
        ) or (
            self.japanese_min_chars is not None
            and any(
                len(item["japanese_text"]) >= self.japanese_min_chars
                for item in payload["slots"]
            )
        ):
            return "\n".join(
                f"TRANSLATION\t{item['slot']}\t{item['japanese_text']}"
                for item in payload["slots"]
            )
        rows = []
        for item in reversed(payload["slots"]):
            protected = (
                " ⟪MVD_PROTECTED_0000⟫"
                if "⟪MVD_PROTECTED_0000⟫" in item["japanese_text"]
                else ""
            )
            rows.append(
                f"TRANSLATION\t{item['slot']}\tEnglish {item['slot']}{protected}"
            )
        should_corrupt = self.invalid_last_slot_always or (
            self.invalid_last_slot_once and not self.invalid_last_slot_used
        )
        if should_corrupt:
            self.invalid_last_slot_used = True
            last_slot = payload["slots"][-1]["slot"]
            rows = [
                row
                for row in rows
                if not row.startswith(f"TRANSLATION\t{last_slot}\t")
            ]
            rows.append("TRANSLATION\tseven\tbroken")
        if self.invalid_response:
            rows.append("extra commentary")
        if self.unknown_type_response:
            rows.append("NOTE\t1\ttranslation complete")
        if self.duplicate_response:
            rows.extend(list(rows))
        if self.conflicting_duplicate_once and len(self.chat_calls) == 1:
            rows.append("TRANSLATION\t1\tDifferent English translation")
        if self.conflicting_duplicate_always:
            rows.append("TRANSLATION\t1\tDifferent English translation")
        if self.unknown_slot_response:
            rows.append("TRANSLATION\t99\tUnknown slot")
        return "\n".join(rows)

    def ensure_loaded(self, model_path, config):
        self.ensure_calls += 1

    def clear(self):
        self.clear_calls += 1


class LlamaPromptTranslatorTests(unittest.TestCase):
    def test_translation_prompt_preserves_unusual_local_geometry(self) -> None:
        prompt = (
            Path(__file__).parents[1]
            / "prompts"
            / "prompt_translation_ja_en_system_prompt.txt"
        ).read_text(encoding="utf-8")
        self.assertIn("identity-specific visual geometry literally", prompt)
        self.assertIn("shape, count, placement, scale, color, material", prompt)
        self.assertIn("compact circular or oval mark", prompt)
        self.assertIn("not merely as \"round\" or \"rounded\"", prompt)

    def test_translation_payload_requires_literal_local_geometry(self) -> None:
        payload = json.loads(LlamaPromptTranslator._payload(("丸い眉毛",)))
        self.assertIn("Preserve concrete local visual geometry", payload["instruction"])
        self.assertIn("conventional default", payload["instruction"])
        self.assertIn("never translate tabi as geta", payload["instruction"])

    def test_isolated_translation_wrapper_recovery_is_unambiguous(self) -> None:
        cases = (
            ("Bare English translation", "Bare English translation"),
            (
                "TRANSLATION 1: Explicit English translation",
                "Explicit English translation",
            ),
            (
                '{"slot":1,"translation":"JSON English translation"}',
                "JSON English translation",
            ),
            (
                "```text\nFenced English translation\n```",
                "Fenced English translation",
            ),
            ("First candidate\nSecond candidate", None),
            ('{"slot":2,"translation":"Wrong slot"}', None),
            ('{"translation":"One","text":"Two"}', None),
        )
        for response, expected in cases:
            with self.subTest(response=response):
                self.assertEqual(
                    _recover_isolated_translation(response),
                    expected,
                )

    def test_isolated_duplicate_candidates_skip_echoes_and_keep_response_order(
        self,
    ) -> None:
        response = (
            "TRANSLATION\t1\t日本語のまま\n"
            "TRANSLATION\t1\tFirst English candidate\n"
            "TRANSLATION\t1\tFirst English candidate\n"
            "TRANSLATION\t1\tSecond English candidate"
        )

        self.assertEqual(
            _isolated_english_candidates(response),
            ("First English candidate", "Second English candidate"),
        )

    def test_japanese_echo_is_rejected_after_one_isolated_retry(self) -> None:
        lifecycle = FakeLifecycle(japanese_response=True)
        translator = LlamaPromptTranslator(
            lifecycle,
            system_prompt="translate",
            runtime_config=LlamaRuntimeConfig(max_tokens=32, n_ctx=1100),
        )
        with self.assertRaisesRegex(CompilerError, "not English"):
            translator.translate(("少女",))
        self.assertEqual(len(lifecycle.chat_calls), 2)

    def test_japanese_echo_is_recovered_by_one_isolated_retry(self) -> None:
        lifecycle = FakeLifecycle(japanese_response_once=True)
        translator = LlamaPromptTranslator(
            lifecycle,
            system_prompt="translate",
            runtime_config=LlamaRuntimeConfig(max_tokens=32, n_ctx=1100),
        )
        translated = translator.translate(("一", "二"))
        self.assertEqual(translated, ("English 1", "English 1"))
        self.assertEqual([len(call["slots"]) for call in lifecycle.chat_calls], [2, 1, 1])

    def test_long_japanese_echo_uses_logged_segmented_recovery(self) -> None:
        lifecycle = FakeLifecycle(japanese_min_chars=180)
        translator = LlamaPromptTranslator(
            lifecycle,
            system_prompt="translate",
            runtime_config=LlamaRuntimeConfig(max_tokens=32, n_ctx=1100),
        )
        source = "".join(f"第{index}の場面を描写する。" for index in range(25))

        with self.assertLogs("mv_director.compiler", level="INFO") as captured:
            translated = translator.translate((source,))

        self.assertEqual(len(translated), 1)
        self.assertNotRegex(translated[0], r"[\u3040-\u30ff\u3400-\u9fff]")
        self.assertEqual(translator.segmented_recovered_count, 1)
        log = "\n".join(captured.output)
        self.assertIn("isolated translation retry started", log)
        self.assertIn("segmented translation recovery started", log)
        self.assertIn("segmented translation recovery completed", log)
        self.assertGreaterEqual(len(lifecycle.chat_calls), 3)

    def test_very_long_unit_is_segmented_before_first_model_call(self) -> None:
        lifecycle = FakeLifecycle(japanese_min_chars=180)
        translator = LlamaPromptTranslator(
            lifecycle,
            system_prompt="translate",
            runtime_config=LlamaRuntimeConfig(max_tokens=32, n_ctx=1100),
        )
        source = "".join(f"第{index}の場面を描写する。" for index in range(80))

        with self.assertLogs("mv_director.compiler", level="INFO") as captured:
            translated = translator.translate((source,))

        self.assertEqual(len(translated), 1)
        self.assertEqual(translator.segmented_recovered_count, 1)
        self.assertTrue(lifecycle.chat_calls)
        self.assertTrue(
            all(
                len(item["japanese_text"]) < 300
                for call in lifecycle.chat_calls
                for item in call["slots"]
            )
        )
        self.assertIn("trigger=proactive_long_unit", "\n".join(captured.output))

    def test_mostly_english_candidate_uses_logged_residual_cleanup(self) -> None:
        lifecycle = FakeLifecycle(mixed_japanese_response=True)
        translator = LlamaPromptTranslator(
            lifecycle,
            system_prompt="translate",
            runtime_config=LlamaRuntimeConfig(max_tokens=32, n_ctx=1100),
        )

        with self.assertLogs("mv_director.compiler", level="INFO") as captured:
            translated = translator.translate(("画面を連続した構図として描く。",))

        self.assertEqual(translated, ("Draw the screen as a continuous composition",))
        self.assertEqual(translator.cleanup_recovered_count, 1)
        self.assertEqual(len(lifecycle.chat_calls), 2)
        self.assertEqual(
            lifecycle.chat_calls[1]["slots"][0]["japanese_text"],
            "画面",
        )
        log = "\n".join(captured.output)
        self.assertIn("residual-Japanese cleanup started", log)
        self.assertIn("residual-Japanese cleanup completed", log)

    def test_residual_cleanup_translates_unique_spans_not_whole_candidate(self) -> None:
        class ResidualSpanLifecycle(FakeLifecycle):
            def complete_chat(self, messages, config, interrupt_callback=None):
                content = messages[-1]["content"]
                payload = json.loads(content.removeprefix("/no_think\n"))
                self.chat_calls.append(payload)
                if len(self.chat_calls) == 1:
                    return (
                        "TRANSLATION\t1\tA detailed cinematic portrait shows "
                        "狐巫女 wearing 黒い木下駄. The 狐巫女 smiles softly "
                        "at the camera."
                    )
                translations = {
                    "狐巫女": "fox shrine maiden",
                    "黒い木下駄": "black wooden geta",
                }
                return "\n".join(
                    f"TRANSLATION\t{item['slot']}\t"
                    f"{translations[item['japanese_text']]}"
                    for item in payload["slots"]
                )

        lifecycle = ResidualSpanLifecycle()
        translator = LlamaPromptTranslator(
            lifecycle,
            system_prompt="translate",
            runtime_config=LlamaRuntimeConfig(max_tokens=32, n_ctx=1100),
        )

        with self.assertLogs("mv_director.compiler", level="INFO") as captured:
            translated = translator.translate(("人物を描く。",))

        self.assertEqual(
            translated,
            (
                "A detailed cinematic portrait shows fox shrine maiden wearing "
                "black wooden geta. The fox shrine maiden smiles softly at the "
                "camera.",
            ),
        )
        self.assertEqual(len(lifecycle.chat_calls), 2)
        self.assertEqual(
            [
                item["japanese_text"]
                for item in lifecycle.chat_calls[1]["slots"]
            ],
            ["狐巫女", "黒い木下駄"],
        )
        self.assertIn("spans=2", "\n".join(captured.output))

    def test_proactive_segments_recover_one_mixed_english_chunk_by_span(self) -> None:
        class SegmentedResidualLifecycle(FakeLifecycle):
            def __init__(self) -> None:
                super().__init__()
                self.effective_n_ctx = 32_768

            def complete_chat(self, messages, config, interrupt_callback=None):
                content = messages[-1]["content"]
                payload = json.loads(content.removeprefix("/no_think\n"))
                self.chat_calls.append(payload)
                rows = []
                for item in payload["slots"]:
                    source = item["japanese_text"]
                    if source == "狐巫女":
                        translated = "fox shrine maiden"
                    elif "残留" in source:
                        translated = (
                            "An otherwise complete cinematic English description "
                            "with 狐巫女 clearly visible"
                        )
                    else:
                        translated = f"English chunk {item['slot']}"
                    rows.append(
                        f"TRANSLATION\t{item['slot']}\t{translated}"
                    )
                return "\n".join(rows)

        lifecycle = SegmentedResidualLifecycle()
        translator = LlamaPromptTranslator(
            lifecycle,
            system_prompt="translate",
            runtime_config=LlamaRuntimeConfig(max_tokens=512, n_ctx=32_768),
        )
        source = "".join(
            (
                f"第{index}の場面では人物と背景を詳細に描写し、"
                f"時間方向の連続性を明確に保つ{'残留' if index == 4 else ''}。"
            )
            for index in range(12)
        )

        with self.assertLogs("mv_director.compiler", level="INFO") as captured:
            translated = translator.translate((source,))

        self.assertEqual(len(translated), 1)
        self.assertNotRegex(translated[0], r"[\u3040-\u30ff\u3400-\u9fff]")
        self.assertIn("fox shrine maiden", translated[0])
        self.assertEqual(translator.segmented_recovered_count, 1)
        self.assertEqual(translator.cleanup_recovered_count, 1)
        self.assertTrue(
            any(
                [item["japanese_text"] for item in call["slots"]] == ["狐巫女"]
                for call in lifecycle.chat_calls
            )
        )
        log = "\n".join(captured.output)
        self.assertIn("trigger=proactive_long_unit", log)
        self.assertIn("residual-Japanese cleanup completed", log)
        self.assertIn("segmented translation recovery completed", log)

    def test_qwen4b_thinking_header_and_literal_tabs_are_normalized(self) -> None:
        lifecycle = FakeLifecycle(small_model_format=True)
        translator = LlamaPromptTranslator(
            lifecycle,
            system_prompt="translate",
            runtime_config=LlamaRuntimeConfig(max_tokens=32, n_ctx=1100),
        )
        translated = translator.translate(("一", "二"))
        self.assertEqual(translated, ("English 1", "English 2"))
        self.assertEqual(translator.batch_count, 1)

    def test_finite_batches_preserve_original_unit_order(self) -> None:
        lifecycle = FakeLifecycle()
        translator = LlamaPromptTranslator(
            lifecycle,
            system_prompt="translate",
            runtime_config=LlamaRuntimeConfig(max_tokens=32, n_ctx=1100),
        )
        translated = translator.translate(("一 ⟪MVD_PROTECTED_0000⟫", "二", "三"))
        self.assertEqual(
            translated,
            ("English 1 ⟪MVD_PROTECTED_0000⟫", "English 2", "English 1"),
        )
        self.assertEqual(translator.batch_count, 2)
        self.assertEqual(len(lifecycle.chat_calls), 2)

    def test_complete_translation_ignores_nonrecord_commentary(self) -> None:
        lifecycle = FakeLifecycle(invalid_response=True)
        translator = LlamaPromptTranslator(
            lifecycle,
            system_prompt="translate",
            runtime_config=LlamaRuntimeConfig(max_tokens=32, n_ctx=1100),
        )
        with self.assertLogs("mv_director.compiler", level="INFO"):
            translated = translator.translate(("一",))
        self.assertEqual(translated, ("English 1",))
        self.assertEqual(len(lifecycle.chat_calls), 1)

    def test_complete_translation_ignores_only_unknown_record_types(self) -> None:
        lifecycle = FakeLifecycle(unknown_type_response=True)
        translator = LlamaPromptTranslator(
            lifecycle,
            system_prompt="translate",
            runtime_config=LlamaRuntimeConfig(max_tokens=32, n_ctx=1100),
        )
        with self.assertLogs("mv_director.compiler", level="INFO") as captured:
            translated = translator.translate(("一", "二"))
        self.assertEqual(translated, ("English 1", "English 2"))
        self.assertEqual(len(lifecycle.chat_calls), 1)
        self.assertIn(
            "unknown_type=1",
            "\n".join(captured.output),
        )

    def test_identical_duplicate_translations_are_ignored(self) -> None:
        lifecycle = FakeLifecycle(duplicate_response=True)
        translator = LlamaPromptTranslator(
            lifecycle,
            system_prompt="translate",
            runtime_config=LlamaRuntimeConfig(max_tokens=32, n_ctx=1100),
        )
        with self.assertLogs("mv_director.compiler", level="INFO") as captured:
            translated = translator.translate(("一", "二"))
        self.assertEqual(translated, ("English 1", "English 2"))
        self.assertEqual(len(lifecycle.chat_calls), 1)
        self.assertIn("duplicate=2", "\n".join(captured.output))

    def test_conflicting_duplicate_translation_is_retried_in_isolation(self) -> None:
        lifecycle = FakeLifecycle(conflicting_duplicate_once=True)
        translator = LlamaPromptTranslator(
            lifecycle,
            system_prompt="translate",
            runtime_config=LlamaRuntimeConfig(max_tokens=32, n_ctx=1100),
        )
        with self.assertLogs("mv_director.compiler", level="INFO") as captured:
            translated = translator.translate(("一", "二"))
        self.assertEqual(translated, ("English 1", "English 2"))
        self.assertEqual([len(call["slots"]) for call in lifecycle.chat_calls], [2, 1])
        self.assertIn(
            "retrying conflicting duplicate translation slots in isolation: 1",
            "\n".join(captured.output),
        )

    def test_conflicting_duplicate_on_isolated_retry_selects_first_english(self) -> None:
        lifecycle = FakeLifecycle(conflicting_duplicate_always=True)
        translator = LlamaPromptTranslator(
            lifecycle,
            system_prompt="translate",
            runtime_config=LlamaRuntimeConfig(max_tokens=32, n_ctx=1100),
        )

        with self.assertLogs("mv_director.compiler", level="INFO") as captured:
            translated = translator.translate(("一", "二"))

        self.assertEqual(translated, ("English 1", "English 2"))
        self.assertEqual([len(call["slots"]) for call in lifecycle.chat_calls], [2, 1])
        self.assertEqual(translator.protocol_recovered_count, 1)
        log = "\n".join(captured.output)
        self.assertIn(
            "recovered conflicting duplicate isolated translation; slot=1; "
            "candidates=2; selected=first_valid_english",
            log,
        )

    def test_segmented_long_unit_recovers_duplicate_on_isolated_chunk_retry(
        self,
    ) -> None:
        lifecycle = FakeLifecycle(conflicting_duplicate_always=True)
        lifecycle.effective_n_ctx = 32_768
        translator = LlamaPromptTranslator(
            lifecycle,
            system_prompt="translate",
            runtime_config=LlamaRuntimeConfig(max_tokens=512, n_ctx=32_768),
        )
        source = "".join(f"第{index}の場面を詳しく描写する。" for index in range(40))

        with self.assertLogs("mv_director.compiler", level="INFO") as captured:
            translated = translator.translate((source,))

        self.assertEqual(len(translated), 1)
        self.assertNotRegex(translated[0], r"[\u3040-\u30ff\u3400-\u9fff]")
        self.assertEqual(translator.segmented_recovered_count, 1)
        self.assertGreaterEqual(translator.protocol_recovered_count, 1)
        log = "\n".join(captured.output)
        self.assertIn("trigger=proactive_long_unit", log)
        self.assertIn("recovered conflicting duplicate isolated translation", log)

    def test_complete_translation_ignores_extra_unknown_slot(self) -> None:
        lifecycle = FakeLifecycle(unknown_slot_response=True)
        translator = LlamaPromptTranslator(
            lifecycle,
            system_prompt="translate",
            runtime_config=LlamaRuntimeConfig(max_tokens=32, n_ctx=1100),
        )
        with self.assertLogs("mv_director.compiler", level="INFO") as captured:
            translated = translator.translate(("一",))
        self.assertEqual(translated, ("English 1",))
        self.assertEqual(len(lifecycle.chat_calls), 1)
        self.assertIn("unknown_slot=1", "\n".join(captured.output))

    def test_unknown_slot_without_required_translation_remains_fatal(self) -> None:
        class OnlyUnknownSlotLifecycle(FakeLifecycle):
            def complete_chat(self, messages, config, interrupt_callback=None):
                content = messages[-1]["content"]
                payload = json.loads(content.removeprefix("/no_think\n"))
                self.chat_calls.append(payload)
                return "TRANSLATION\t99\tUnknown slot"

        lifecycle = OnlyUnknownSlotLifecycle()
        translator = LlamaPromptTranslator(
            lifecycle,
            system_prompt="translate",
            runtime_config=LlamaRuntimeConfig(max_tokens=32, n_ctx=1100),
        )
        with self.assertRaisesRegex(CompilerError, "unknown_slot"):
            translator.translate(("一",))
        self.assertEqual(len(lifecycle.chat_calls), 2)

    def test_isolated_retry_keeps_required_slot_and_discards_extra_unknown_slot(
        self,
    ) -> None:
        lifecycle = FakeLifecycle(
            invalid_last_slot_once=True,
            unknown_slot_response=True,
        )
        lifecycle.effective_n_ctx = 32768
        translator = LlamaPromptTranslator(
            lifecycle,
            system_prompt="translate",
            runtime_config=LlamaRuntimeConfig(max_tokens=4096, n_ctx=32768),
        )

        with self.assertLogs("mv_director.compiler", level="INFO") as captured:
            translated = translator.translate(
                ("一", "二", "三", "四", "五", "六", "七")
            )

        self.assertEqual(translated[:6], tuple(f"English {index}" for index in range(1, 7)))
        self.assertEqual(translated[6], "English 1")
        self.assertEqual([len(call["slots"]) for call in lifecycle.chat_calls], [7, 1])
        self.assertIn("unknown_slot=1", "\n".join(captured.output))

    def test_missing_slot_is_retried_once_as_an_isolated_unit(self) -> None:
        lifecycle = FakeLifecycle(invalid_last_slot_once=True)
        lifecycle.effective_n_ctx = 32768
        translator = LlamaPromptTranslator(
            lifecycle,
            system_prompt="translate",
            runtime_config=LlamaRuntimeConfig(max_tokens=4096, n_ctx=32768),
        )
        translated = translator.translate(("一", "二", "三", "四", "五", "六", "七"))
        self.assertEqual(translated[:6], tuple(f"English {index}" for index in range(1, 7)))
        self.assertEqual(translated[6], "English 1")
        self.assertEqual([len(call["slots"]) for call in lifecycle.chat_calls], [7, 1])
        self.assertEqual(lifecycle.chat_calls[1]["slots"][0]["japanese_text"], "七")
        self.assertEqual(translator.batch_count, 2)

    def test_bare_text_from_isolated_retry_is_recovered_one_to_one(self) -> None:
        lifecycle = FakeLifecycle(
            invalid_last_slot_once=True,
            bare_isolated_response=True,
        )
        lifecycle.effective_n_ctx = 32768
        translator = LlamaPromptTranslator(
            lifecycle,
            system_prompt="translate",
            runtime_config=LlamaRuntimeConfig(max_tokens=4096, n_ctx=32768),
        )

        translated = translator.translate(
            ("一", "二", "三", "四", "五", "六", "七")
        )

        self.assertEqual(translated[-1], "Recovered English translation")
        self.assertEqual(translator.protocol_recovered_count, 1)
        self.assertEqual(
            [len(call["slots"]) for call in lifecycle.chat_calls],
            [7, 1],
        )

    def test_ambiguous_multiline_isolated_retry_still_stops(self) -> None:
        lifecycle = FakeLifecycle(
            invalid_last_slot_once=True,
            ambiguous_isolated_response=True,
        )
        lifecycle.effective_n_ctx = 32768
        translator = LlamaPromptTranslator(
            lifecycle,
            system_prompt="translate",
            runtime_config=LlamaRuntimeConfig(max_tokens=4096, n_ctx=32768),
        )

        with self.assertRaisesRegex(CompilerError, "isolated retry for slot 7"):
            translator.translate(("一", "二", "三", "四", "五", "六", "七"))
        self.assertEqual(translator.protocol_recovered_count, 0)

    def test_isolated_retry_failure_still_stops(self) -> None:
        lifecycle = FakeLifecycle(invalid_last_slot_always=True)
        translator = LlamaPromptTranslator(
            lifecycle,
            system_prompt="translate",
            runtime_config=LlamaRuntimeConfig(max_tokens=32, n_ctx=1100),
        )
        with self.assertRaisesRegex(CompilerError, "isolated retry for slot 1"):
            translator.translate(("一",))
        self.assertEqual(len(lifecycle.chat_calls), 2)

    def test_protocol_batches_are_capped_at_seven_units(self) -> None:
        lifecycle = FakeLifecycle()
        lifecycle.effective_n_ctx = 32768
        translator = LlamaPromptTranslator(
            lifecycle,
            system_prompt="translate",
            runtime_config=LlamaRuntimeConfig(max_tokens=4096, n_ctx=32768),
        )
        translated = translator.translate(tuple(f"項目{i}" for i in range(15)))
        self.assertEqual(len(translated), 15)
        self.assertEqual(
            [len(call["slots"]) for call in lifecycle.chat_calls],
            [7, 7, 1],
        )


class EMDCompilerNodeTests(unittest.TestCase):
    def test_public_mapping_and_socket_surface(self) -> None:
        cls = NODE_CLASS_MAPPINGS["MVDirectorEMDCompiler"]
        self.assertEqual(
            NODE_DISPLAY_NAME_MAPPINGS["MVDirectorEMDCompiler"],
            "MV Director - EMD Compiler (Ref2VA)",
        )
        self.assertEqual(
            cls.RETURN_TYPES,
            ("STRING", "MV_DIRECTOR_REQUIRED_REFERENCES", "STRING"),
        )
        inputs = cls.INPUT_TYPES()
        self.assertTrue(inputs["required"]["emd_text"][1]["forceInput"])
        self.assertEqual(inputs["required"]["translation_mode"][1]["default"], "ja_to_en")
        self.assertEqual(inputs["required"]["n_ctx"][1]["default"], 16384)
        self.assertEqual(
            inputs["required"]["seed"][1]["control_after_generate"],
            "randomize",
        )
        self.assertIn("h3_timing_profile", inputs["optional"])
        self.assertEqual(inputs["required"]["cache_mode"][1]["default"], "reuse")

    def test_already_english_does_not_resolve_or_load_a_model(self) -> None:
        cls = NODE_CLASS_MAPPINGS["MVDirectorEMDCompiler"]
        node = cls()
        lifecycle = FakeLifecycle()
        node._lifecycle = lifecycle
        plan_json, references, status = node.compile_emd(
            ENGLISH_EMD,
            "already_english",
            "(no GGUF models found)",
            "auto",
            20,
            64,
            0.1,
            0.9,
            1.05,
            -1,
            256,
            32768,
            True,
            "q8_0",
            True,
            False,
            1,
        )
        self.assertEqual(json.loads(plan_json)["shots"][0]["length"], 22)
        self.assertEqual(references.references, ())
        self.assertIn("model=not_loaded", status)
        self.assertEqual(lifecycle.ensure_calls, 0)
        self.assertEqual(lifecycle.clear_calls, 1)

    def test_success_cache_round_trips_plan_and_references(self) -> None:
        cls = NODE_CLASS_MAPPINGS["MVDirectorEMDCompiler"]
        node = cls()
        lifecycle = FakeLifecycle()
        node._lifecycle = lifecycle
        with TemporaryDirectory() as temporary, patch(
            "nodes.node_emd_compiler.node._cache",
            return_value=SuccessCache(Path(temporary)),
        ):
            first = node.compile_emd(
                ENGLISH_EMD,
                "already_english",
                "(no GGUF models found)",
                "auto",
                20,
                64,
                0.1,
                0.9,
                1.05,
                -1,
                256,
                32768,
                True,
                "q8_0",
                True,
                False,
                1,
                "reuse",
            )
            second = node.compile_emd(
                ENGLISH_EMD,
                "already_english",
                "(no GGUF models found)",
                "auto",
                20,
                64,
                0.1,
                0.9,
                1.05,
                -1,
                256,
                32768,
                True,
                "q8_0",
                True,
                False,
                1,
                "reuse",
            )
        self.assertEqual(first[:2], second[:2])
        self.assertIn("cache=miss", first[2])
        self.assertIn("cache=hit", second[2])
        self.assertEqual(lifecycle.ensure_calls, 0)

    def test_ja_to_en_uses_selected_model_and_internal_translator(self) -> None:
        source = ENGLISH_EMD.replace(
            "A person wearing a white coat.", "白いコートを着た人物。"
        ).replace("The person walks forward.", "前へ歩く。")
        cls = NODE_CLASS_MAPPINGS["MVDirectorEMDCompiler"]
        node = cls()
        lifecycle = FakeLifecycle()
        node._lifecycle = lifecycle
        model = SimpleNamespace(
            path=Path("selected.gguf"),
            selection_id="selected.gguf",
            fingerprint="f" * 64,
            size=123,
            mtime_ns=456,
        )
        with patch(
            "nodes.node_emd_compiler.node.resolve_comfy_gguf_model",
            return_value=model,
        ):
            plan_json, references, status = node.compile_emd(
                source,
                "ja_to_en",
                "selected.gguf",
                "auto",
                20,
                32,
                0.0,
                0.9,
                1.05,
                -1,
                256,
                1100,
                True,
                "q8_0",
                True,
                False,
                1,
            )
        prompt = "\n".join(json.loads(plan_json)["shots"][0]["prompt"])
        self.assertIn("English 1", prompt)
        self.assertEqual(len(lifecycle.chat_calls), 2)
        self.assertTrue(all(len(call["slots"]) == 1 for call in lifecycle.chat_calls))
        self.assertEqual(references.references, ())
        self.assertIn("mode=ja_to_en", status)
        self.assertEqual(lifecycle.ensure_calls, 1)
        self.assertEqual(lifecycle.clear_calls, 1)

    def test_grammar_error_stops_before_model_resolution(self) -> None:
        cls = NODE_CLASS_MAPPINGS["MVDirectorEMDCompiler"]
        node = cls()
        lifecycle = FakeLifecycle()
        node._lifecycle = lifecycle
        with self.assertRaisesRegex(EMDParseError, "Scene annotation"):
            node.compile_emd(
                ENGLISH_EMD.replace("> `シーン` 1\n", ""),
                "ja_to_en",
                "missing.gguf",
                "auto",
                20,
                32,
                0.0,
                0.9,
                1.05,
                -1,
                256,
                1100,
                True,
                "q8_0",
                True,
                False,
                1,
            )
        self.assertEqual(lifecycle.ensure_calls, 0)


if __name__ == "__main__":
    unittest.main()
