from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
import unittest

from core.inference import ModelSelectionError
from nodes.common import (
    NO_GGUF_MODELS,
    collect_comfy_gguf_roots,
    discover_comfy_gguf_models,
    gguf_model_choices,
    resolve_comfy_gguf_model,
)


class FakeFolderPaths:
    def __init__(self, models_dir: Path, llm_roots):
        self.models_dir = str(models_dir)
        self.folder_names_and_paths = {"LLM": ([], {".gguf"})}
        self._llm_roots = [str(path) for path in llm_roots]

    def get_folder_paths(self, category):
        if category != "LLM":
            raise AssertionError(category)
        return list(self._llm_roots)


class ComfyGGUFDiscoveryTests(unittest.TestCase):
    def test_collects_default_and_registered_llm_roots(self) -> None:
        with TemporaryDirectory() as temporary:
            base = Path(temporary)
            models_dir = base / "models"
            default_gguf = models_dir / "LLM" / "GGUF"
            external = base / "external_llm"
            external_gguf = external / "GGUF"
            default_gguf.mkdir(parents=True)
            external_gguf.mkdir(parents=True)
            (default_gguf / "default.gguf").write_bytes(b"default")
            (models_dir / "LLM" / "direct.gguf").write_bytes(b"direct")
            (external_gguf / "external.gguf").write_bytes(b"external")
            (external_gguf / "vision-mmproj.gguf").write_bytes(b"projector")

            folder_paths = FakeFolderPaths(
                models_dir, [models_dir / "LLM", external]
            )
            roots = collect_comfy_gguf_roots(folder_paths)
            self.assertEqual(
                list(roots),
                ["models", "LLM1", "LLM2-GGUF", "LLM2"],
            )
            models = discover_comfy_gguf_models(folder_paths)
            self.assertEqual(
                {model.path.name for model in models},
                {"default.gguf", "direct.gguf", "external.gguf"},
            )
            self.assertNotIn("vision-mmproj.gguf", gguf_model_choices(folder_paths))
            selected = next(
                model.selection_id
                for model in models
                if model.path.name == "external.gguf"
            )
            self.assertEqual(
                resolve_comfy_gguf_model(selected, folder_paths).path.name,
                "external.gguf",
            )

    def test_duplicate_relative_names_are_root_qualified(self) -> None:
        with TemporaryDirectory() as temporary:
            base = Path(temporary)
            models_dir = base / "models"
            default = models_dir / "LLM" / "GGUF"
            external = base / "external"
            default.mkdir(parents=True)
            (external / "GGUF").mkdir(parents=True)
            (default / "same.gguf").write_bytes(b"a")
            (external / "GGUF" / "same.gguf").write_bytes(b"b")
            folder_paths = FakeFolderPaths(models_dir, [external])
            choices = gguf_model_choices(folder_paths)
            self.assertEqual(
                set(choices),
                {"models::same.gguf", "LLM1-GGUF::same.gguf"},
            )

    def test_missing_folder_paths_or_models_returns_placeholder(self) -> None:
        self.assertEqual(gguf_model_choices(None), [NO_GGUF_MODELS])
        empty = SimpleNamespace(
            models_dir="Z:/path/that/does/not/exist",
            folder_names_and_paths={},
        )
        self.assertEqual(gguf_model_choices(empty), [NO_GGUF_MODELS])
        with self.assertRaisesRegex(ModelSelectionError, "no GGUF models"):
            resolve_comfy_gguf_model(NO_GGUF_MODELS, empty)

    def test_stale_or_absolute_selection_is_rejected(self) -> None:
        empty = SimpleNamespace(models_dir="", folder_names_and_paths={})
        with self.assertRaises(ModelSelectionError):
            resolve_comfy_gguf_model("stale.gguf", empty)
        with self.assertRaisesRegex(ModelSelectionError, "absolute"):
            resolve_comfy_gguf_model(str(Path.cwd() / "model.gguf"), empty)


if __name__ == "__main__":
    unittest.main()
