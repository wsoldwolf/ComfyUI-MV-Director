from __future__ import annotations

import json
import unittest

from core.artifacts import DirectionArtifact
from core.planner import build_scene_spine_grammar, plan_timeline
from core.planner.engine import (
    _CameraPlan,
    _Entity,
    _camera_plan_contract_violations,
    _fallback_camera_plan,
)
from core.planner.scene_spine import (
    parse_scene_spine_step,
    validate_contact_coverage,
    validate_scene_spine,
)
from test_timeline_planner import CONCEPT, TEMPLATE, FakePlannerBackend, prompts, runtime


class SceneSpineTests(unittest.TestCase):
    def test_spine_protocol_and_scene_order(self) -> None:
        first = parse_scene_spine_step(
            "PHASE=event｜FROM=手を下ろす｜ADVANCE=指先で苔に一度触れる"
            "｜TO=指を離す｜SHOW=lyric_target_hands"
        )
        second = parse_scene_spine_step(
            "PHASE=response｜FROM=指を離す｜ADVANCE=顔に安堵が広がる"
            "｜TO=苔を見つめる｜SHOW=face_eyes_mouth"
        )
        validate_scene_spine((first, second))
        self.assertEqual(first.required_coverage, "lyric_target_and_hands")
        with self.assertRaisesRegex(ValueError, "exactly one event"):
            validate_scene_spine((first, first))
        repeated = parse_scene_spine_step(
            "PHASE=response｜FROM=指を離す｜ADVANCE=指先で苔に一度触れる"
            "｜TO=苔を見つめる｜SHOW=face_eyes_mouth"
        )
        with self.assertRaisesRegex(ValueError, "identical Shot advance"):
            validate_scene_spine((first, repeated))
        with self.assertRaisesRegex(ValueError, "five fields"):
            parse_scene_spine_step("PHASE=event｜FROM=立つ")
        validate_contact_coverage((first, second), contact_allowed=True)
        premature = parse_scene_spine_step(
            "PHASE=setup｜FROM=離れて立つ｜ADVANCE=苔へ近づく"
            "｜TO=苔の前で止まる｜SHOW=lyric_target_hands"
        )
        with self.assertRaisesRegex(ValueError, "only in its event"):
            validate_contact_coverage((premature, first), contact_allowed=True)
        with self.assertRaisesRegex(ValueError, "non-contact"):
            validate_contact_coverage((first, second), contact_allowed=False)
        grammar = build_scene_spine_grammar([1, 2])
        self.assertIn('"SPINE\\t1\\tPHASE=event"', grammar)
        self.assertIn('"SPINE\\t1\\tPHASE=setup"', grammar)
        self.assertIn('"lyric_target_hands"', grammar)
        self.assertNotIn('"SPINE\\t2\\tPHASE=setup"', grammar)
        non_contact = build_scene_spine_grammar([1, 2], allow_target_hands=False)
        self.assertNotIn('"lyric_target_hands"', non_contact)
        with self.assertRaisesRegex(ValueError, "no valid event position"):
            build_scene_spine_grammar([
                {"slot": 1, "editorial_role": "face_performance_cut"},
                {"slot": 2, "editorial_role": "face_performance_cut"},
            ])

    def test_camera_requires_spine_focus_and_keeps_target_readable(self) -> None:
        entity = _Entity(1, (1, 1), {
            "shot_duration_ms": 5000,
            "required_spine_coverage": "lyric_target_and_hands",
            "arc_permission": "forbidden",
        })
        hidden = _CameraPlan(
            "Push In at fast speed", "wide", "face_closeup",
            "front", "front", "push_in", "face_eyes_mouth",
        )
        self.assertIn(
            "required_spine_coverage",
            _camera_plan_contract_violations(entity, hidden),
        )
        self.assertIn(
            "spine_target_occluded",
            _camera_plan_contract_violations(entity, hidden),
        )
        fallback = _fallback_camera_plan(entity, 0)
        self.assertEqual(fallback.coverage, "lyric_target_and_hands")
        self.assertNotIn(
            fallback.end_scale, {"head_and_shoulders", "face_closeup"}
        )

    def test_scene_task_is_one_call_for_two_shots_and_shared_with_camera(self) -> None:
        class Backend(FakePlannerBackend):
            def complete_planner(self, *, task, system_prompt, payload, config, interrupt_callback=None):
                if task == "scene-spine":
                    value = json.loads(payload)
                    self.calls.append((task, value))
                    return "\n".join(
                        f"SPINE\t{item['slot']}\t"
                        + (
                            "PHASE=event｜FROM=手を下ろす｜ADVANCE=鳥居へ手を伸ばす"
                            "｜TO=手を戻す｜SHOW=lyric_target"
                            if index == 0 else
                            "PHASE=response｜FROM=手を戻す｜ADVANCE=表情を緩める"
                            "｜TO=正面を見る｜SHOW=face_eyes_mouth"
                        )
                        for index, item in enumerate(value["slots"])
                    )
                return super().complete_planner(
                    task=task, system_prompt=system_prompt, payload=payload,
                    config=config, interrupt_callback=interrupt_callback,
                )

        backend = Backend()
        system_prompts = {**prompts(), "scene-spine": "scene-spine"}
        result = plan_timeline(
            backend, template_emd=TEMPLATE, concept_emd=CONCEPT,
            direction=DirectionArtifact(
                motion_profile_id="anime_emotional_mv",
                camera_profile_id="anime_emotional_mv",
            ),
            lip_sync_mode="off", lip_sync_target="サブジェクト1",
            lip_sync_audio_slot=1, scenes_per_batch=1,
            system_prompts=system_prompts, runtime_config=runtime(),
        )
        self.assertTrue(result.complete)
        spine_calls = [payload for task, payload in backend.calls if task == "scene-spine"]
        self.assertEqual(len(spine_calls), 1)
        self.assertEqual(len(spine_calls[0]["slots"]), 2)
        self.assertEqual(len(result.content.scene_spine_steps), 2)
        action_payload = next(payload for task, payload in backend.calls if task == "actions")
        self.assertEqual(
            action_payload["slots"][0]["scene_spine_step"]["advance"],
            "鳥居へ手を伸ばす",
        )
        camera_payload = next(payload for task, payload in backend.calls if task == "cameras")
        self.assertEqual(
            camera_payload["slots"][0]["required_spine_coverage"],
            "lyric_target",
        )


if __name__ == "__main__":
    unittest.main()
