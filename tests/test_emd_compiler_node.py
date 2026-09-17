from __future__ import annotations

import json
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from core.compiler import CompilerError, LlamaPromptTranslator
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
    ) -> None:
        self.effective_n_ctx = 1120
        self.invalid_response = invalid_response
        self.small_model_format = small_model_format
        self.japanese_response = japanese_response
        self.japanese_response_once = japanese_response_once
        self.invalid_last_slot_once = invalid_last_slot_once
        self.invalid_last_slot_always = invalid_last_slot_always
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
        if self.japanese_response or (
            self.japanese_response_once and len(self.chat_calls) == 1
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
        return "\n".join(rows)

    def ensure_loaded(self, model_path, config):
        self.ensure_calls += 1

    def clear(self):
        self.clear_calls += 1


class LlamaPromptTranslatorTests(unittest.TestCase):
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

    def test_invalid_translation_line_stops_without_retry(self) -> None:
        lifecycle = FakeLifecycle(invalid_response=True)
        translator = LlamaPromptTranslator(
            lifecycle,
            system_prompt="translate",
            runtime_config=LlamaRuntimeConfig(max_tokens=32, n_ctx=1100),
        )
        with self.assertRaisesRegex(CompilerError, "line protocol"):
            translator.translate(("一",))
        self.assertEqual(len(lifecycle.chat_calls), 1)

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
        self.assertEqual(inputs["required"]["n_ctx"][1]["default"], 32768)
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
        self.assertIn("English 2", prompt)
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
