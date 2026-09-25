"""The local Scene experiment must not leak baseline Actions into LLM input."""
import json
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from tools.offline_scene_body_chain import model_input, parse_response


class OfflineSceneBodyChainTests(unittest.TestCase):
    def setUp(self):
        path = Path(__file__).resolve().parents[1] / (
            "tests/fixtures/research/scene-body-chain-2026-09-22/fixture.json"
        )
        self.scenes = json.loads(path.read_text(encoding="utf-8"))["scenes"]

    def test_original_actions_do_not_enter_request(self):
        for scene in self.scenes:
            request = model_input(scene)
            self.assertEqual(len(request["shot_slots"]), len(scene["shots"]))
            serialized = json.dumps(request, ensure_ascii=False)
            for shot in scene["shots"]:
                self.assertNotIn(shot["original_action"], serialized)
            self.assertNotIn("original_action", serialized)

    def test_camera_guided_request_preserves_fixed_slots_without_baseline_leakage(self):
        scaffold_path = Path(__file__).resolve().parents[1] / (
            "tests/fixtures/research/scene-body-chain-2026-09-22/camera-scaffold.json"
        )
        scaffold = json.loads(scaffold_path.read_text(encoding="utf-8"))
        for scene in self.scenes:
            request = model_input(
                scene, variant="camera_guided_shot_chain",
                camera_coverage=scaffold[str(scene["scene_number"])],
            )
            self.assertEqual(len(request["camera_coverage"]), len(scene["shots"]))
            self.assertEqual(len(request["shot_slots"]), len(scene["shots"]))
            self.assertNotIn("original_action", json.dumps(request, ensure_ascii=False))
        with self.assertRaisesRegex(ValueError, "fixed Shot count"):
            model_input(
                self.scenes[0], variant="camera_guided_shot_chain",
                camera_coverage=["only one Shot"],
            )
        brief_path = Path(__file__).resolve().parents[1] / (
            "tests/fixtures/research/scene-body-chain-2026-09-22/performance-brief.json"
        )
        briefs = json.loads(brief_path.read_text(encoding="utf-8"))
        for scene in self.scenes:
            request = model_input(
                scene, variant="brief_camera_guided",
                camera_coverage=scaffold[str(scene["scene_number"])],
                performance_brief=briefs[str(scene["scene_number"])],
            )
            self.assertIn("performance_brief", request)
            self.assertNotIn("original_action", json.dumps(request, ensure_ascii=False))

    def test_response_requires_matching_shot_count_without_repair(self):
        raw = json.dumps({"start_pose": "始点", "progression": ["移動", "着地"],
                          "end_pose": "終端", "shot_actions": ["第一", "第二"]})
        self.assertEqual(parse_response(raw, 2)["shot_actions"], ["第一", "第二"])
        self.assertEqual(parse_response("<think>\n\n</think>\n" + raw, 2)["end_pose"], "終端")
        with self.assertRaises(ValueError):
            parse_response(raw, 1)

    def test_unified_contract_has_one_end_state_per_shot(self):
        raw = json.dumps({"start_pose": "始点", "shots": [
            {"action": "第一動作", "end_pose": "中間"},
            {"action": "第二動作", "end_pose": "終端"},
        ]})
        self.assertEqual(parse_response(raw, 2, "unified_shot_chain")["shots"][-1]["end_pose"], "終端")
        with self.assertRaises(ValueError):
            parse_response(raw, 1, "unified_shot_chain")
        self.assertEqual(
            parse_response(raw, 2, "camera_guided_shot_chain")["shots"][-1]["end_pose"],
            "終端",
        )
        self.assertEqual(
            parse_response(raw, 2, "brief_camera_guided")["shots"][-1]["end_pose"],
            "終端",
        )


if __name__ == "__main__":
    unittest.main()
