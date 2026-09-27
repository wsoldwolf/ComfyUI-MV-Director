"""Arc continuity detection and bounded Camera-only repair, no GPU."""

import unittest

from core.artifacts import DirectionArtifact
from core.planner import plan_timeline
from core.planner.camera_continuity import arc_directions, inspect_arc_sequence
from nodes.node_timeline_planner.node import _system_prompts
from scene_author_fixtures import Backend, CONCEPT, _runtime


TEMPLATE = (
    "> `シーン` 1\n# シーン 00:00.000 --> 00:12.250\n* `H3長` 294\n"
    "## ショット 00:00.000\n* `演出` なし\n* `演技` 人物が歌う。\n"
    "## ショット 00:04.000\n* `演出` なし\n* `演技` 人物が歌う。\n"
    "## ショット 00:08.000\n* `演出` なし\n* `演技` 人物が歌う。\n"
)


class CameraBackend(Backend):
    def __init__(self, repair=True):
        super().__init__()
        self.repair = repair

    def complete_planner(self, **kwargs):
        import json
        request = json.loads(kwargs["payload"])
        self.calls.append((kwargs["task"], request))
        texts = {1: "Arc Shot 時計回りで顔へ寄る。",
                 2: "Pull Outで上半身へ引く。",
                 3: "Arc Shot 反時計回りで全身へ引く。"}
        if request.get("retry") == "arc_direction_only" and self.repair:
            texts[3] = "Arc Shot 時計回りで全身へ引く。Roll Counterclockwiseで傾ける。"
        return "\n".join(f"CAMERA\t{s['slot']}\t{texts[s['shot']]}"
                         for s in request["slots"])


class CameraContinuityTests(unittest.TestCase):
    def test_directions_and_roll_are_distinct(self):
        for text, expected in (
            ("Arc Shot rotate clockwise.", {"clockwise"}),
            ("Arc Shot swivels counter-clockwise.", {"counterclockwise"}),
            ("Arc Shot anticlockwise.", {"counterclockwise"}),
            ("Arc Shot 反時計回り。", {"counterclockwise"}),
            ("Arc Shot 右回り。Roll Counterclockwiseで戻す。", {"clockwise"}),
            ("Arc Shot clockwise with Roll Counterclockwise.", {"clockwise"}),
            ("Arc Shot with Roll Clockwise.", set()),
            ("Roll Clockwise。", set()),
            ("Arc Shot 人物の右側から寄る。", set()),
            ("人物が反時計回りに回転する。Static Shot。", set()),
        ):
            with self.subTest(text=text):
                self.assertEqual(arc_directions(text), expected)

    def test_non_arc_does_not_reset_direction(self):
        cameras = {1: "Arc Shot clockwise.", 2: "Pull Out.",
                   3: "Arc Shot counterclockwise."}
        self.assertEqual(inspect_arc_sequence(cameras, {}, None),
                         ({3: "clockwise"}, "clockwise"))
        self.assertEqual(inspect_arc_sequence({1: "Static Shot."}, {}, "clockwise"),
                         ({}, "clockwise"))

    def test_authored_direction_overrides_and_cut_resets(self):
        cameras = {1: "Arc Shot counterclockwise.", 2: "Arc Shot counterclockwise."}
        self.assertEqual(inspect_arc_sequence(cameras, {1: cameras[1]}, "clockwise"),
                         ({}, "counterclockwise"))
        self.assertEqual(inspect_arc_sequence(cameras, {}, None), ({}, "counterclockwise"))
        self.assertEqual(inspect_arc_sequence({1: "Static Shot."}, {1: "Static Shot."}, "clockwise"),
                         ({}, "clockwise"))

    def test_mixed_directions_in_one_shot(self):
        self.assertEqual(inspect_arc_sequence(
            {1: "Arc Shot counter-clockwise then clockwise."}, {}, None),
            ({1: "counterclockwise"}, "counterclockwise"))

    def test_only_conflicting_camera_is_regenerated(self):
        backend = CameraBackend()
        result = plan_timeline(
            backend, template_emd=TEMPLATE, concept_emd=CONCEPT,
            direction=DirectionArtifact(), lip_sync_mode="off",
            lip_sync_target="サブジェクト1", lip_sync_audio_slot=1,
            system_prompts=_system_prompts(), runtime_config=_runtime(),
        )
        self.assertTrue(result.complete)
        self.assertEqual(len(backend.calls), 2)
        retry = backend.calls[1][1]
        self.assertEqual(retry["retry"], "arc_direction_only")
        self.assertEqual([s["shot"] for s in retry["slots"]], [3])
        self.assertEqual(retry["slots"][0]["required_arc_direction"], "clockwise")
        self.assertEqual(result.content.cameras[0][2], "Arc Shot 時計回りで顔へ寄る。")
        self.assertIn("Roll Counterclockwise", result.content.cameras[2][2])

    def test_failed_repair_warns_without_blocking(self):
        backend = CameraBackend(repair=False)
        with self.assertLogs("mv_director.nodes", level="WARNING") as logs:
            result = plan_timeline(
                backend, template_emd=TEMPLATE, concept_emd=CONCEPT,
                direction=DirectionArtifact(), lip_sync_mode="off",
                lip_sync_target="サブジェクト1", lip_sync_audio_slot=1,
                system_prompts=_system_prompts(), runtime_config=_runtime(),
            )
        self.assertTrue(result.complete)
        self.assertEqual(len(backend.calls), 2)
        self.assertIn("反時計回り", result.content.cameras[2][2])
        self.assertIn("retained original Camera AS IS", "\n".join(logs.output))

    def test_scene_handoff_survives_static_without_end_state_and_resets_at_cut(self):
        source = (
            "> `シーン` 1\n# シーン 00:00.000 --> 00:01.000\n* `H3長` 22\n"
            "## ショット 00:00.000\n* `演出` なし\n* `演技` 歌う。\n"
            "* `カメラ` Arc Shot 時計回り。Roll Counterclockwise。\n"
            "## ショット 00:00.500\n* `演出` なし\n* `演技` 歌う。\n"
            "> `シーン` 2\n# シーン 00:01.000 --> 00:02.708{continuation}\n* `H3長` 56\n"
            "## ショット 00:01.000\n* `演出` なし\n* `演技` 歌う。\n"
        )

        class HandoffBackend(Backend):
            def complete_planner(self, **kwargs):
                import json
                payload = json.loads(kwargs["payload"])
                self.calls.append((kwargs["task"], payload))
                if payload["scene_number"] == 1:
                    text = "Static Shotで表情を捉える。"
                elif payload.get("retry"):
                    text = "Arc Shot 時計回り。"
                else:
                    text = "Arc Shot 反時計回り。"
                return f"CAMERA\t1\t{text}"

        for continuation, expected in ((" 継続", "clockwise"), ("", None)):
            with self.subTest(continuation=continuation):
                backend = HandoffBackend()
                result = plan_timeline(
                    backend, template_emd=source.format(continuation=continuation),
                    concept_emd=CONCEPT, direction=DirectionArtifact(),
                    lip_sync_mode="off", lip_sync_target="サブジェクト1", lip_sync_audio_slot=1,
                    system_prompts=_system_prompts(), runtime_config=_runtime(),
                )
                self.assertTrue(result.complete)
                second = [p for _, p in backend.calls if p["scene_number"] == 2]
                self.assertEqual(second[0]["arc_continuity"]["inherited_direction"], expected)
                self.assertEqual(len(second), 2 if continuation else 1)
                self.assertIn("Roll Counterclockwise", result.emd.text)


if __name__ == "__main__":
    unittest.main()
