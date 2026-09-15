from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from core.inference import (
    ContextBudgetError,
    LlamaRuntimeConfig,
    ModelSelectionError,
    SuccessCache,
    build_cache_key,
    build_context_budget,
    discover_gguf_models,
    resolve_model_selection,
)


class InferenceFoundationTests(unittest.TestCase):
    def test_discovers_gguf_recursively_and_excludes_mmproj(self) -> None:
        with TemporaryDirectory() as temporary:
            base = Path(temporary)
            first = base / "first"
            second = base / "second"
            (first / "nested").mkdir(parents=True)
            second.mkdir()
            (first / "nested" / "model.gguf").write_bytes(b"one")
            (second / "model.gguf").write_bytes(b"two")
            (second / "vision-mmproj.gguf").write_bytes(b"three")
            models = discover_gguf_models({"primary": first, "extra": second})
            self.assertEqual(len(models), 2)
            self.assertEqual(
                {model.selection_id for model in models},
                {"nested/model.gguf", "model.gguf"},
            )
            self.assertEqual(
                resolve_model_selection("nested/model.gguf", {"primary": first}).size,
                3,
            )

    def test_duplicate_relative_paths_are_root_qualified(self) -> None:
        with TemporaryDirectory() as temporary:
            base = Path(temporary)
            roots = {"a": base / "a", "b": base / "b"}
            for path in roots.values():
                path.mkdir()
                (path / "same.gguf").write_bytes(b"model")
            selections = {
                model.selection_id for model in discover_gguf_models(roots)
            }
            self.assertEqual(selections, {"a::same.gguf", "b::same.gguf"})
            with self.assertRaises(ModelSelectionError):
                resolve_model_selection("same.gguf", roots)

    def test_absolute_model_selection_is_rejected(self) -> None:
        with self.assertRaisesRegex(ModelSelectionError, "absolute"):
            resolve_model_selection(str(Path.cwd().resolve() / "model.gguf"), {})

    def test_context_budget_distinguishes_exact_fit_and_one_over(self) -> None:
        exact = build_context_budget(14_049, 1_024, 16_384)
        self.assertEqual(exact.required_tokens, 16_384)
        self.assertEqual(exact.remaining_tokens, 0)
        with self.assertRaisesRegex(ContextBudgetError, "required=16385"):
            build_context_budget(14_050, 1_024, 16_384)

    def test_runtime_config_preserves_32k_trial_values(self) -> None:
        config = LlamaRuntimeConfig(n_ctx=32_768, kv_cache_type="q8_0")
        self.assertEqual(config.to_dict()["n_ctx"], 32_768)
        with self.assertRaises(ValueError):
            LlamaRuntimeConfig(n_ctx=131_073).validate()

    def test_success_cache_round_trip_and_key_sensitivity(self) -> None:
        key = build_cache_key(
            task="compiler.translate",
            algorithm_version="1",
            inputs={"model_fingerprint": "abc", "seed": 1},
        )
        changed = build_cache_key(
            task="compiler.translate",
            algorithm_version="1",
            inputs={"model_fingerprint": "abc", "seed": 2},
        )
        self.assertNotEqual(key, changed)
        with TemporaryDirectory() as temporary:
            cache = SuccessCache(temporary)
            self.assertIsNone(cache.get(key))
            cache.put_success(key, {"units": ["hello"]})
            self.assertEqual(cache.get(key), {"units": ["hello"]})


if __name__ == "__main__":
    unittest.main()
