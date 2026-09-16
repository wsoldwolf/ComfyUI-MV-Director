from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from core.inference import LlamaRuntimeConfig
from core.protocols import VisionProtocolError
from core.vision import (
    LlamaCppVisionLifecycle,
    PreparedVisionImage,
    VisionObservationRequest,
    compose_image_to_subject,
    discover_vision_model_pairs,
    observe_image,
    pixel_fingerprint,
    prepare_comfy_image,
    resolve_picture_binding,
    resolve_vision_model_pair,
)
from core.vision.image_to_subject import build_vision_request
from nodes import NODE_CLASS_MAPPINGS
from nodes.common import (
    NO_VISION_MODELS,
    resolve_comfy_vision_model,
    vision_model_choices,
)


FIXTURE = Path(__file__).parent / "fixtures" / "protocol" / "vision_observation_valid.txt"


def _gguf(path: Path, payload: bytes = b"data") -> None:
    path.write_bytes(b"GGUF" + payload)


class FakeObserver:
    def __init__(self, response: str) -> None:
        self.response = response
        self.calls = []

    def complete_observation(self, **kwargs):
        self.calls.append(kwargs)
        return self.response


class SequenceObserver:
    def __init__(self, *responses: str) -> None:
        self.responses = list(responses)
        self.calls = []

    def complete_observation(self, **kwargs):
        self.calls.append(kwargs)
        return self.responses.pop(0)


class FakeHandler:
    instances = []

    def __init__(self, **kwargs):
        self.kwargs = kwargs
        self.closed = False
        self.__class__.instances.append(self)

    def close(self):
        self.closed = True


class FakeVisionModel:
    instances = []

    def __init__(self, **kwargs):
        self.kwargs = kwargs
        self.closed = False
        self.reset_count = 0
        self.__class__.instances.append(self)

    def reset(self):
        self.reset_count += 1

    def create_chat_completion(self, **kwargs):
        self.completion_kwargs = kwargs
        return iter(
            [
                {"choices": [{"delta": {"content": "MVD_"}}]},
                {"choices": []},
                {"choices": [{"delta": {"content": "RESULT"}}]},
            ]
        )

    def close(self):
        self.closed = True


class FakeLlamaModule:
    GGML_TYPE_Q8_0 = 8
    GGML_TYPE_Q4_0 = 4
    GGML_TYPE_F16 = 16


class VisionPhase3Tests(unittest.TestCase):
    def setUp(self) -> None:
        FakeHandler.instances.clear()
        FakeVisionModel.instances.clear()

    def test_pixel_fingerprint_includes_shape_and_pixels(self) -> None:
        first = pixel_fingerprint(b"\x00\x01\x02", width=1, height=1, channels=3)
        self.assertEqual(
            first,
            pixel_fingerprint(b"\x00\x01\x02", width=1, height=1, channels=3),
        )
        self.assertNotEqual(
            first,
            pixel_fingerprint(b"\x00\x01\x03", width=1, height=1, channels=3),
        )
        with self.assertRaises(ValueError):
            pixel_fingerprint(b"\x00", width=1, height=1, channels=3)

    def test_reference_view_request_consolidates_one_identity(self) -> None:
        request = build_vision_request(
            VisionObservationRequest(), reference_view_count=3
        )
        self.assertIn("3 reference views", request)
        self.assertIn("one unique PRIMARY_SUBJECT", request)
        prompt = (
            Path(__file__).resolve().parents[1]
            / "prompts"
            / "vision_observation_system_prompt.txt"
        ).read_text(encoding="utf-8")
        self.assertIn("character sheet", prompt)
        self.assertIn("rear views as one unique PRIMARY_SUBJECT", prompt)

    def test_image_batch_is_composed_as_one_reference_sheet(self) -> None:
        try:
            import torch
        except ImportError:
            self.skipTest("torch is unavailable")
        first = torch.zeros((2, 16, 12, 3), dtype=torch.float32)
        first[1, :, :, 0] = 1.0
        prepared = prepare_comfy_image(first, 256)
        self.assertEqual(prepared.batch_size, 2)
        self.assertGreater(prepared.analysis_width, prepared.source_width)
        self.assertGreater(prepared.analysis_height, prepared.source_height)
        self.assertIn("one character reference sheet", prepared.warnings[0])
        second = first.clone()
        second[1, 0, 0, 1] = 1.0
        self.assertNotEqual(
            prepared.image_sha256,
            prepare_comfy_image(second, 256).image_sha256,
        )

    def test_discovers_model_and_best_same_directory_projector(self) -> None:
        with TemporaryDirectory() as temporary:
            root = Path(temporary)
            model = root / "vision-Q5_K_M.gguf"
            preferred = root / "mmproj-vision-f16.gguf"
            _gguf(model)
            _gguf(preferred)
            _gguf(root / "mmproj-other-q4.gguf")
            pairs = discover_vision_model_pairs({"models": root})
            self.assertEqual(len(pairs), 1)
            self.assertEqual(pairs[0].model_path, model.resolve())
            self.assertEqual(pairs[0].projector_path, preferred.resolve())
            self.assertEqual(
                resolve_vision_model_pair(pairs[0].selection_id, {"models": root}),
                pairs[0],
            )

    def test_comfy_adapter_placeholder_without_folder_paths(self) -> None:
        self.assertEqual(vision_model_choices(None), [NO_VISION_MODELS])
        with self.assertRaisesRegex(ValueError, "no Vision GGUF pair"):
            resolve_comfy_vision_model(NO_VISION_MODELS, None)

    def test_observation_provenance_and_binding_are_python_owned(self) -> None:
        backend = FakeObserver(FIXTURE.read_text(encoding="utf-8"))
        prepared = PreparedVisionImage(
            data_uri="data:image/png;base64,AAAA",
            image_sha256="a" * 64,
            source_width=640,
            source_height=480,
            analysis_width=640,
            analysis_height=480,
            channels=3,
            batch_size=1,
        )
        request = VisionObservationRequest(
            subject_hint="subject_hint: 狐の尾は一本です。\r\n",
            additional_instruction="眉を詳しく見る。",
            hint_mode="lock_identity",
        )
        observations, warnings = observe_image(
            backend,
            prepared=prepared,
            request=request,
            model_identity={"selection_id": "vision.gguf"},
            system_prompt="fixed prompt\n",
            runtime_config=LlamaRuntimeConfig(),
        )
        self.assertEqual(warnings, ())
        self.assertIn("subject_hint: 狐の尾は一本です。", backend.calls[0]["request"])
        provenance = {item["kind"]: item for item in observations.provenance}
        self.assertEqual(provenance["subject_hint"]["role"], "user_authority")
        self.assertEqual(
            provenance["additional_instruction"]["role"], "observation_focus"
        )
        binding = resolve_picture_binding(
            "auto_h3",
            picture_index=1,
            prompt={
                "42": {
                    "class_type": "MiniMaxH3ReferenceToVideo",
                    "inputs": {"ref_image_2": ["10", 2]},
                }
            },
            unique_id="10",
        )
        result = compose_image_to_subject(
            observations,
            prepared=prepared,
            request=request,
            binding=binding,
            concept_type="person",
        )
        self.assertEqual(result.resolved_picture_reference, "<Picture 3>")
        self.assertIn("`画像3`", result.emd.emd_fragment)
        self.assertNotIn("<Picture 3>", result.emd.emd_fragment)
        self.assertIn("subject_hint: 狐の尾は一本です。", result.emd.emd_fragment)
        stored = result.reference_bindings.bindings[0]
        self.assertEqual(stored.image_sha256, "a" * 64)
        self.assertEqual(stored.target_node_id, "42")

    def test_invalid_compact_response_gets_one_format_only_retry(self) -> None:
        backend = SequenceObserver(
            "MVD_VISION_OBSERVATION_LINES_V2\t人物\tnot_used",
            FIXTURE.read_text(encoding="utf-8"),
        )
        prepared = PreparedVisionImage(
            "data:image/png;base64,AAAA", "c" * 64, 1, 1, 1, 1, 3, 1
        )
        observations, warnings = observe_image(
            backend,
            prepared=prepared,
            request=VisionObservationRequest(subject_hint="眉は金色です。"),
            model_identity={},
            system_prompt="fixed prompt",
            runtime_config=LlamaRuntimeConfig(),
        )
        self.assertEqual(observations.primary_subject, "長い黒髪の人物")
        self.assertEqual(len(backend.calls), 2)
        self.assertIn("FORMAT RETRY", backend.calls[1]["request"])
        self.assertTrue(any("format-only retry" in item for item in warnings))

    def test_format_retry_stops_after_second_invalid_response(self) -> None:
        backend = SequenceObserver("broken", "still broken")
        prepared = PreparedVisionImage(
            "data:image/png;base64,AAAA", "d" * 64, 1, 1, 1, 1, 3, 1
        )
        with self.assertRaisesRegex(VisionProtocolError, "format retry failed"):
            observe_image(
                backend,
                prepared=prepared,
                request=VisionObservationRequest(),
                model_identity={},
                system_prompt="fixed prompt",
                runtime_config=LlamaRuntimeConfig(),
            )
        self.assertEqual(len(backend.calls), 2)

    def test_observe_only_does_not_send_or_render_hint(self) -> None:
        response = FIXTURE.read_text(encoding="utf-8").replace(
            "HINT_STATUS\tconsistent",
            "HINT_STATUS\tnot_used",
        ).replace(
            "HINT_REASON\t短く丸い淡い金色の眉が部分的に確認できる。",
            "HINT_REASON\t",
        )
        backend = FakeObserver(response)
        prepared = PreparedVisionImage(
            "data:image/png;base64,AAAA", "b" * 64, 1, 1, 1, 1, 3, 1
        )
        request = VisionObservationRequest(
            subject_hint="画像外の設定", hint_mode="observe_only"
        )
        observations, _ = observe_image(
            backend,
            prepared=prepared,
            request=request,
            model_identity={},
            system_prompt="fixed prompt",
            runtime_config=LlamaRuntimeConfig(),
        )
        self.assertNotIn("画像外の設定", backend.calls[0]["request"])
        result = compose_image_to_subject(
            observations,
            prepared=prepared,
            request=request,
            binding=resolve_picture_binding(
                "none", picture_index=1, prompt=None, unique_id=None
            ),
            concept_type="person",
        )
        self.assertNotIn("画像外の設定", result.emd.emd_fragment)

    def test_mtmd_lifecycle_loads_reuses_streams_and_closes(self) -> None:
        with TemporaryDirectory() as temporary:
            root = Path(temporary)
            model = root / "vision.gguf"
            projector = root / "mmproj-vision.gguf"
            _gguf(model)
            _gguf(projector)
            pair = discover_vision_model_pairs({"models": root})[0]
            lifecycle = LlamaCppVisionLifecycle(
                llama_module=FakeLlamaModule,
                llama_class=FakeVisionModel,
                handler_class=FakeHandler,
            )
            config = LlamaRuntimeConfig()
            first = lifecycle.ensure_loaded(pair, config)
            self.assertIs(lifecycle.ensure_loaded(pair, config), first)
            self.assertEqual(len(FakeVisionModel.instances), 1)
            interrupts = []
            output = lifecycle.complete_observation(
                system_prompt="system",
                request="request",
                image_data_uri="data:image/png;base64,AAAA",
                config=config,
                interrupt_callback=lambda: interrupts.append(True),
            )
            self.assertEqual(output, "MVD_RESULT")
            user_content = first.completion_kwargs["messages"][1]["content"]
            self.assertEqual(user_content[0]["text"], "/no_think\nrequest")
            self.assertGreaterEqual(len(interrupts), 3)
            self.assertEqual(first.reset_count, 1)
            lifecycle.clear()
            self.assertTrue(first.closed)
            self.assertTrue(FakeHandler.instances[0].closed)

    def test_public_mapping_contains_image_node(self) -> None:
        self.assertIn("MVDirectorImageToSubjectEMD", NODE_CLASS_MAPPINGS)
        inputs = NODE_CLASS_MAPPINGS["MVDirectorImageToSubjectEMD"].INPUT_TYPES()
        self.assertIn("model_name", inputs["required"])
        self.assertEqual(
            inputs["required"]["seed"][1]["control_after_generate"],
            "randomize",
        )
        self.assertNotIn("concept_index", inputs["required"])
        self.assertNotIn("subject_index", inputs["required"])
        self.assertEqual(inputs["hidden"], {"prompt": "PROMPT", "unique_id": "UNIQUE_ID"})


if __name__ == "__main__":
    unittest.main()
