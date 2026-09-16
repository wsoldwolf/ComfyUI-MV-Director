from pathlib import Path
import json
import unittest

from core.direction import (
    CAMERA_PROFILES,
    DIRECTION_PRESETS,
    MOTION_PROFILES,
    STYLE_PROFILES,
    DirectionEnhancerError,
    DirectionEnhancerInput,
    build_direction_payload,
    enhance_direction,
)
from core.inference import LlamaRuntimeConfig
from nodes import NODE_CLASS_MAPPINGS


class FakeDirectionBackend:
    def __init__(self, *responses: str) -> None:
        self.responses = list(responses)
        self.calls = []

    def complete_direction(self, **kwargs):
        self.calls.append(kwargs)
        if not self.responses:
            raise AssertionError("unexpected inference call")
        return self.responses.pop(0)


VALID = "\n".join(
    (
        "STYLE\t1\t実写映画として自然な材質と奥行きで描く。",
        "MOTION\t1\t重心と接地が読める連続動作にする。",
        "CAMERA\t1\t緩やかに接近しながら安定した構図を保つ。",
        "OTHER\t1\t夜間の静かな緊張感を保つ。",
    )
)


class DirectionEnhancerTests(unittest.TestCase):
    def test_empty_user_and_concept_use_profiles(self) -> None:
        backend = FakeDirectionBackend(VALID)
        value = DirectionEnhancerInput()
        result = enhance_direction(
            backend,
            value=value,
            system_prompt="fixed",
            runtime_config=LlamaRuntimeConfig(),
        )
        self.assertEqual(len(backend.calls), 1)
        self.assertEqual(result.direction.style_direction[0], "実写映画として自然な材質と奥行きで描く。")
        self.assertIn("## スタイル", result.direction_emd_preview)
        self.assertIn("## その他", result.direction_emd_preview)
        input_records = [
            item for item in result.direction.provenance if item.record_kind == "input"
        ]
        self.assertEqual(len(input_records), 3)
        self.assertTrue(all(item.source == "profile" for item in input_records))

    def test_normalizes_observed_qwen4b_record_formatting(self) -> None:
        backend = FakeDirectionBackend(
            "<think>\n</think>\n"
            "STYLE\t1\t画風。\tMOTION\t2\t動作。\tCAMERA\t3\tカメラ。"
        )
        result = enhance_direction(
            backend,
            value=DirectionEnhancerInput(),
            system_prompt="fixed",
            runtime_config=LlamaRuntimeConfig(),
        )
        self.assertEqual(len(backend.calls), 1)
        self.assertEqual(result.direction.style_direction, ("画風。",))
        self.assertEqual(result.direction.motion_direction, ("動作。",))
        self.assertEqual(result.direction.camera_direction, ("カメラ。",))
        self.assertFalse(result.issues)
        self.assertFalse(result.retried_missing)

    def test_payload_keeps_authority_order_and_read_only_concept(self) -> None:
        concept = "# サブジェクト\n* 金色の眉。\n"
        value = DirectionEnhancerInput(
            concept_emd=concept,
            user_request="夜間にする。",
            style_profile="reference_cinematic",
            motion_profile="expressive_mv",
            camera_profile="cinematic_depth",
        )
        payload = json.loads(build_direction_payload(value))
        self.assertEqual(
            payload["authority_order"],
            ["user", "vision_concept", "profile", "generated"],
        )
        self.assertEqual(payload["user_request"], "夜間にする。")
        self.assertEqual(payload["concept_emd"], concept.strip())
        self.assertIn("実写映画", payload["profiles"]["style"]["text"])

    def test_missing_required_slot_gets_one_local_retry(self) -> None:
        backend = FakeDirectionBackend(
            "STYLE\t1\t画風。\nCAMERA\t1\tカメラ。",
            "STYLE\t1\t再掲しない。\nMOTION\t1\t動作。",
        )
        result = enhance_direction(
            backend,
            value=DirectionEnhancerInput(),
            system_prompt="fixed",
            runtime_config=LlamaRuntimeConfig(),
        )
        self.assertEqual(len(backend.calls), 2)
        retry = json.loads(backend.calls[1]["payload"])
        self.assertEqual(retry["retry"], "missing_slots_only")
        self.assertEqual(retry["missing"], [["MOTION", 1]])
        self.assertEqual(result.retried_missing, (("MOTION", 1),))
        self.assertEqual(result.direction.motion_direction, ("動作。",))
        self.assertEqual(len(result.issues), 1)
        self.assertEqual(result.issues[0].reason, "unknown_type")
        self.assertNotIn("再掲しない", result.direction_emd_preview)

    def test_missing_after_retry_stops(self) -> None:
        backend = FakeDirectionBackend("STYLE\t1\t画風。", "CAMERA\t1\tカメラ。")
        with self.assertRaisesRegex(DirectionEnhancerError, "MOTION:1"):
            enhance_direction(
                backend,
                value=DirectionEnhancerInput(),
                system_prompt="fixed",
                runtime_config=LlamaRuntimeConfig(),
            )
        self.assertEqual(len(backend.calls), 2)

    def test_invalid_lines_are_discard_provenance_without_retry(self) -> None:
        backend = FakeDirectionBackend("preamble\n" + VALID + "\nSTYLE\t1\t別案")
        result = enhance_direction(
            backend,
            value=DirectionEnhancerInput(user_request="夜間"),
            system_prompt="fixed",
            runtime_config=LlamaRuntimeConfig(),
        )
        self.assertEqual(len(backend.calls), 1)
        discarded = [
            item
            for item in result.direction.provenance
            if item.record_kind == "discard"
        ]
        self.assertEqual(len(discarded), 2)
        self.assertTrue(all(item.reason == "invalid_line_record" for item in discarded))
        self.assertNotIn("preamble", result.direction_emd_preview)
        self.assertNotIn("別案", result.direction_emd_preview)

    def test_concept_adapter_rejects_complete_emd(self) -> None:
        value = DirectionEnhancerInput(
            concept_emd="# サブジェクト\n* 主人公。\n# シーン 00:00.000 --> 00:01.000"
        )
        with self.assertRaisesRegex(DirectionEnhancerError, "one # サブジェクト"):
            value.validate()

    def test_profile_surface_is_fixed(self) -> None:
        self.assertEqual(
            set(STYLE_PROFILES),
            {"reference_anime", "reference_cinematic", "reference_painterly"},
        )
        self.assertEqual(
            set(MOTION_PROFILES),
            {"natural_performance", "expressive_mv", "limited_animation"},
        )
        self.assertEqual(
            set(CAMERA_PROFILES),
            {"readable_depth", "cinematic_depth", "rhythmic_mv"},
        )
        self.assertEqual(len(DIRECTION_PRESETS), 3)

    def test_public_node_mapping_and_socket_surface(self) -> None:
        self.assertIn("MVDirectorDirectionEnhancer", NODE_CLASS_MAPPINGS)
        inputs = NODE_CLASS_MAPPINGS["MVDirectorDirectionEnhancer"].INPUT_TYPES()
        self.assertIn("style_profile", inputs["required"])
        self.assertIn("n_ctx", inputs["required"])
        self.assertEqual(
            inputs["required"]["seed"][1]["control_after_generate"],
            "randomize",
        )
        self.assertIn("concept_emd", inputs["optional"])
        self.assertIn("observations_json", inputs["optional"])


if __name__ == "__main__":
    unittest.main()
