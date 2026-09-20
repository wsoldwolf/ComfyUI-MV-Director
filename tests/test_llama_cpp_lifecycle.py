from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
import unittest

from core.inference import LlamaCppLifecycle, LlamaRuntimeConfig


class FakeLlama:
    instances = []

    def __init__(self, **kwargs):
        self.kwargs = kwargs
        self.close_count = 0
        self.__class__.instances.append(self)

    def close(self):
        self.close_count += 1

    def n_ctx(self):
        return self.kwargs["n_ctx"] or 4096

    def tokenize(self, value, add_bos):
        return list(value) + ([0] if add_bos else [])

    def create_chat_completion(self, **kwargs):
        self.completion_kwargs = kwargs
        return iter(
            [
                {"choices": [{"delta": {"content": "Hello"}}]},
                {"choices": [{"delta": {"content": " world"}}]},
                {"choices": [], "usage": {"total_tokens": 2}},
            ]
        )


FAKE_MODULE = SimpleNamespace(
    GGML_TYPE_Q8_0="Q8",
    GGML_TYPE_Q4_0="Q4",
    GGML_TYPE_F16="F16",
)


class LlamaCppLifecycleTests(unittest.TestCase):
    def setUp(self):
        FakeLlama.instances.clear()

    def test_load_reuse_reload_and_clear(self) -> None:
        with TemporaryDirectory() as temporary:
            path = Path(temporary) / "model.gguf"
            path.write_bytes(b"model")
            lifecycle = LlamaCppLifecycle(
                llama_module=FAKE_MODULE, llama_class=FakeLlama
            )
            config = LlamaRuntimeConfig(n_ctx=32_768, chat_format="qwen")
            first = lifecycle.ensure_loaded(path, config)
            self.assertIs(first, lifecycle.ensure_loaded(path, config))
            self.assertEqual(first.kwargs["type_k"], "Q8")
            self.assertEqual(first.kwargs["chat_format"], "qwen")
            second = lifecycle.ensure_loaded(
                path, LlamaRuntimeConfig(n_ctx=16_384, chat_format="qwen")
            )
            self.assertIsNot(first, second)
            self.assertEqual(first.close_count, 1)
            lifecycle.clear()
            lifecycle.clear()
            self.assertEqual(second.close_count, 1)

    def test_exact_token_count_marks_fallback_only_as_estimated(self) -> None:
        with TemporaryDirectory() as temporary:
            path = Path(temporary) / "model.gguf"
            path.write_bytes(b"model")
            lifecycle = LlamaCppLifecycle(
                llama_module=FAKE_MODULE, llama_class=FakeLlama
            )
            model = lifecycle.ensure_loaded(path, LlamaRuntimeConfig())
            count = lifecycle.count_serialized_prompt("abc")
            self.assertFalse(count.estimated)
            self.assertEqual(count.count, 4)
            model.tokenize = None
            fallback = lifecycle.count_serialized_prompt("abc")
            self.assertTrue(fallback.estimated)
            self.assertEqual(fallback.count, 1)

    def test_streaming_completion_disables_thinking_and_polls_interrupt(self) -> None:
        with TemporaryDirectory() as temporary:
            path = Path(temporary) / "model.gguf"
            path.write_bytes(b"model")
            lifecycle = LlamaCppLifecycle(
                llama_module=FAKE_MODULE, llama_class=FakeLlama
            )
            model = lifecycle.ensure_loaded(path, LlamaRuntimeConfig())
            checks = []
            text = lifecycle.complete_chat(
                [{"role": "user", "content": "translate"}],
                LlamaRuntimeConfig(),
                interrupt_callback=lambda: checks.append(True),
            )
            self.assertEqual(text, "Hello world")
            self.assertGreaterEqual(len(checks), 4)
            self.assertEqual(
                model.completion_kwargs["chat_template_kwargs"],
                {"enable_thinking": False},
            )
            self.assertIs(model.completion_kwargs["reasoning"], False)

    def test_optional_grammar_is_forwarded_and_missing_support_is_explicit(self):
        from core.inference import InferenceBackendError
        with TemporaryDirectory() as temporary:
            path = Path(temporary) / "model.gguf"
            path.write_bytes(b"model")
            parsed = []
            class Grammar:
                @staticmethod
                def from_string(text, *, verbose):
                    parsed.append((text, verbose))
                    return "compiled grammar"
            module = SimpleNamespace(**vars(FAKE_MODULE), LlamaGrammar=Grammar)
            lifecycle = LlamaCppLifecycle(llama_module=module, llama_class=FakeLlama)
            model = lifecycle.ensure_loaded(path, LlamaRuntimeConfig())
            lifecycle.complete_chat([], LlamaRuntimeConfig(), grammar='root ::= "x"')
            self.assertEqual(parsed, [('root ::= "x"', False)])
            self.assertEqual(model.completion_kwargs["grammar"], "compiled grammar")
            lifecycle.complete_chat([], LlamaRuntimeConfig())
            self.assertNotIn("grammar", model.completion_kwargs)
            del module.LlamaGrammar
            with self.assertRaisesRegex(InferenceBackendError, "LlamaGrammar"):
                lifecycle.complete_chat([], LlamaRuntimeConfig(), grammar='root ::= "x"')
            lifecycle.clear()

    def test_interrupt_exception_propagates_before_inference(self) -> None:
        class Cancelled(BaseException):
            pass

        with TemporaryDirectory() as temporary:
            path = Path(temporary) / "model.gguf"
            path.write_bytes(b"model")
            lifecycle = LlamaCppLifecycle(
                llama_module=FAKE_MODULE, llama_class=FakeLlama
            )
            model = lifecycle.ensure_loaded(path, LlamaRuntimeConfig())
            with self.assertRaises(Cancelled):
                lifecycle.complete_chat(
                    [],
                    LlamaRuntimeConfig(),
                    interrupt_callback=lambda: (_ for _ in ()).throw(Cancelled()),
                )
            self.assertFalse(hasattr(model, "completion_kwargs"))


if __name__ == "__main__":
    unittest.main()
