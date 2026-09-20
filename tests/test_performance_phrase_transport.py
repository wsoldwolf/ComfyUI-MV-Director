"""Transport/selection regressions, not assertions about generated video quality."""
import hashlib
from pathlib import Path
import tempfile
import unittest

from core.compiler import compile_ref2va
from core.direction.profile_loader import load_direction_profile, DirectionProfileError
from core.direction.profiles import MOTION_PROFILES, RENDER_PROMPTS, render_profile_direction, planner_profile_metadata
from types import SimpleNamespace
from core.planner.engine import _CameraPlan, _connect_camera_geometry
from core.planner.layout import build_layout_candidates


class PerformanceTransportTests(unittest.TestCase):
    def test_global_and_local_translation_sources_never_share_a_call(self):
        class Translator:
            def __init__(self):
                self.calls, self.trace = [], []
            def translate(self, units):
                self.calls.append(tuple(units))
                return ["A person." if "人物" in value else "Soft lighting." if "照明" in value
                        else "An arm follows a curved path." for value in units]
            def record_field_translation(self, **record):
                self.trace.append(record)
        translator = Translator()
        source = "# サブジェクト\n* 人物\n# 共通プロンプト\n## 時間・照明\n* 柔らかい照明\n> `シーン` 1\n# シーン 00:00.000 --> 00:01.000\n* `H3長` 22\n## ショット 00:00.000\n* 腕で弧を描く\n"
        result = compile_ref2va(source, translator)
        self.assertEqual(translator.calls, [("人物",), ("柔らかい照明",), ("腕で弧を描く",)])
        self.assertEqual([row["field_id"] for row in translator.trace],
                         ["subject.0.description", "common.時間・照明.0", "scene.0.shot.0.body.0"])
        for row in translator.trace:
            self.assertEqual(row["source_sha256"], hashlib.sha256(row["source"].encode()).hexdigest())
        prefix = " ".join(result.plan.get("prompt_prefix", []))
        self.assertNotIn("arm follows", prefix)

    def test_render_projection_leaves_author_and_modified_values_as_is(self):
        original = MOTION_PROFILES["anime_emotional_mv"]
        values = (original, "作者の追加演技", original + " 作者指定")
        result = render_profile_direction("motion", "anime_emotional_mv", values)
        self.assertEqual(result, (RENDER_PROMPTS["motion"]["anime_emotional_mv"], *values[1:]))
        self.assertEqual(render_profile_direction("motion", "passthrough", values), values)
        self.assertIn("render_prompts", planner_profile_metadata("anime_emotional_mv", "anime_emotional_mv"))

    def test_render_metadata_is_opt_in_and_kind_checked(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "custom.md"
            path.write_text("# プロファイル\n* `render_prompt` なめらかな演技\n# 共通プロンプト\n## モーション\n* 配分を決める\n", encoding="utf-8")
            definition = load_direction_profile(path, "motion")
            self.assertEqual(definition.text, "配分を決める")
            self.assertEqual(definition.render_prompt, "なめらかな演技")
            path.write_text(path.read_text(encoding="utf-8").replace("モーション", "スタイル"), encoding="utf-8")
            with self.assertRaises(DirectionProfileError):
                load_direction_profile(path, "style")

    def test_sustained_candidates_preserve_scene_and_allow_short_scene(self):
        for seconds in (3, 10, 15):
            scene = SimpleNamespace(start_ms=0, end_ms=seconds*1000, shots=(SimpleNamespace(start_ms=0),))
            candidates = build_layout_candidates(scene, min_duration_ms=4000)
            starts = [row.start_ms for row in candidates]
            self.assertEqual(starts[0], 0)
            if len(starts) > 1:
                self.assertTrue(all(right-left >= 4000 for left, right in zip(starts, starts[1:]+[scene.end_ms])))
            self.assertGreaterEqual(scene.end_ms, seconds*1000)

    def test_camera_handoff_preserves_scale_and_cannot_zoom_from_rear_to_face(self):
        previous = _CameraPlan("Arc Shot", "medium", "upper_body", "front", "rear_three_quarter", "arc_left_60_120_70_90", "upper_body_hands")
        target = _CameraPlan("Zoom In", "head_and_shoulders", "face_closeup", "front", "front", "zoom_in_35_55", "face_eyes_mouth")
        result = _connect_camera_geometry(target, previous, previous.path)
        self.assertEqual(result.start_scale, previous.end_scale)
        self.assertEqual(result.start_view, previous.end_view)
        self.assertEqual(result.path, previous.path)
        self.assertEqual(result.end_view, "front_three_quarter")
        self.assertTrue(result.motion.startswith("Arc Shot"))
        self.assertIs(_connect_camera_geometry(target, None), target)

    def test_static_handoff_never_changes_scale_or_view(self):
        previous = _CameraPlan("Zoom Out", "face_closeup", "upper_body", "front", "front", "zoom_out", "upper_body_hands")
        target = _CameraPlan("Static Shot", "wide", "wide", "side", "side", "stationary", "upper_body_hands")
        result = _connect_camera_geometry(target, previous)
        self.assertEqual((result.start_scale, result.end_scale), ("upper_body", "upper_body"))
        self.assertEqual((result.start_view, result.end_view), ("front", "front"))
