"""Regressions for loop-10 orbit reversal and impossible optical moves."""

import unittest
from pathlib import Path
from core.direction.profile_loader import DirectionProfileError, load_direction_profile
from core.direction.profiles import CAMERA_ARC_ROLL_POLICIES, planner_profile_metadata
from core.planner.engine import (
    _Entity, _CameraPlan, _camera_plan_contract_violations,
    _connect_camera_geometry, _fallback_camera_plan, _parse_camera_plan, _render_camera_plan,
    _select_continuous_camera_plan, _select_arc_roll,
    build_camera_plan_grammar,
)


def record(path, motion="Arc Shot with large amplitude at fast speed"):
    return (
        f"MOTION={motion}｜START_SCALE=medium｜END_SCALE=upper_body｜"
        f"START_VIEW=side｜END_VIEW=front_three_quarter｜PATH={path}｜"
        "COVERAGE=upper_body_hands"
    )


def entity(scene, group, slot=1, **extra):
    return _Entity(scene, (scene, slot), {
        "camera_continuity_group": group, "shot_duration_ms": 3500,
        "arc_permission": "required", **extra,
    })


class CameraContinuityTests(unittest.TestCase):
    def test_arc_roll_profile_is_explicit_and_baseline_stays_off(self):
        root = Path(__file__).resolve().parents[1]
        emotional = load_direction_profile(root / "profiles/camera/anime_emotional_mv.md", "camera")
        story = load_direction_profile(root / "profiles/camera/anime_story_mv.md", "camera")
        self.assertEqual(emotional.arc_roll_policy, "selective_arc")
        self.assertEqual(story.arc_roll_policy, "off")
        self.assertEqual(emotional.camera_render_style, "detailed")
        self.assertEqual(story.camera_render_style, "detailed")
        self.assertEqual(CAMERA_ARC_ROLL_POLICIES["anime_emotional_mv"], "selective_arc")
        self.assertEqual(planner_profile_metadata("anime_emotional_mv")["arc_roll_policy"], "selective_arc")
        self.assertEqual(planner_profile_metadata("anime_emotional_mv")["camera_render_style"], "detailed")
        bad = root / "profiles/camera/anime_emotional_mv.md"
        with self.assertRaisesRegex(DirectionProfileError, "arc_roll_policy"):
            from unittest.mock import patch
            with patch("pathlib.Path.read_text", return_value=bad.read_text(encoding="utf-8").replace(
                "selective_arc", "every_shot", 1
            )):
                load_direction_profile(bad, "camera")
        with self.assertRaisesRegex(DirectionProfileError, "requires anime_emotional_mv"):
            with patch("pathlib.Path.read_text", return_value=bad.read_text(encoding="utf-8").replace(
                "`planner_policy` anime_emotional_mv", "`planner_policy` anime_story_mv", 1
            )):
                load_direction_profile(bad, "camera")
        with self.assertRaisesRegex(DirectionProfileError, "arc_tilt_policy is retired"):
            with patch("pathlib.Path.read_text", return_value=bad.read_text(encoding="utf-8").replace(
                "`arc_roll_policy` selective_arc", "`arc_tilt_policy` selective_full_body", 1
            )):
                load_direction_profile(bad, "camera")
        with self.assertRaisesRegex(DirectionProfileError, "camera_render_style"):
            with patch("pathlib.Path.read_text", return_value=bad.read_text(encoding="utf-8").replace(
                "`arc_roll_policy` selective_arc",
                "`arc_roll_policy` selective_arc\n* `camera_render_style` unknown", 1
            )):
                load_direction_profile(bad, "camera")

    def test_arc_roll_preserves_spine_coverage_and_orbit_direction(self):
        chosen = entity(1, 1, shot_duration_ms=4500, arc_roll_emphasis=True,
                        required_spine_coverage="upper_body_hands")
        blocked = entity(2, 2, shot_duration_ms=4500,
                         required_spine_coverage="face_eyes_mouth")
        selected = _select_arc_roll(
            [blocked, chosen], {blocked.key, chosen.key}, {}
        )
        self.assertEqual(selected, chosen.key)
        self.assertIsNone(_select_arc_roll(
            [chosen], {chosen.key}, {chosen.key: "arc_into_next_face_cut"}
        ))
        target = entity(3, 3, shot_duration_ms=4500,
                        required_spine_coverage="lyric_target_and_hands")
        self.assertEqual(_select_arc_roll([target], {target.key}, {}), target.key)
        # The policy is sparse per batch, not a one-time allowance for a song.
        later = entity(7, 7, shot_duration_ms=4200,
                       required_spine_coverage="lyric_target")
        self.assertEqual(_select_arc_roll([later], {later.key}, {}), later.key)
        target_roll = entity(3, 3, shot_duration_ms=4500,
                             required_spine_coverage="lyric_target_and_hands",
                             arc_roll_emphasis=True)
        target_fallback = _fallback_camera_plan(target_roll, 0)
        self.assertEqual(target_fallback.coverage, "lyric_target_and_hands")
        self.assertEqual(_camera_plan_contract_violations(target_roll, target_fallback), ())
        slot = {**chosen.value, "slot": 1, "camera_protocol": "finite_v1",
                "previous_arc_path": "arc_right_60_120_70_90"}
        grammar = build_camera_plan_grammar([slot])
        self.assertIn('camera-path-1 ::= "arc_right_60_120_70_90_roll_clockwise"', grammar)
        self.assertNotIn('"face_closeup"', grammar.split("camera-start-scale-1 ::=", 1)[1].split("\n", 1)[0])
        self.assertIn('camera-coverage-1 ::= "upper_body_hands"', grammar)
        line = (
            "MOTION=Arc Shot with large amplitude at fast speed｜"
            "START_SCALE=medium_wide｜END_SCALE=medium｜"
            "START_VIEW=low_front_three_quarter｜END_VIEW=side｜"
            "PATH=arc_right_60_120_70_90_roll_clockwise｜COVERAGE=upper_body_hands"
        )
        plan, errors = _parse_camera_plan(line)
        self.assertEqual(errors, ())
        self.assertEqual(_camera_plan_contract_violations(chosen, plan), ())
        rendered = _render_camera_plan(plan)
        self.assertTrue(rendered.startswith("Arc Shot with large amplitude at fast speed."))
        self.assertIn("Roll Clockwise with small amplitude", rendered)
        self.assertIn("return the horizon to level", rendered)
        compact = _render_camera_plan(plan, style="compact")
        self.assertTrue(compact.startswith("Arc Shot with large amplitude at fast speed."))
        self.assertIn("Move right around the subject", compact)
        self.assertIn("Roll Clockwise with small amplitude", compact)
        self.assertIn("Show the face, shoulders, arms, and hands together", compact)
        self.assertLess(len(compact), len(rendered))
        self.assertNotIn("60-to-120-degree", compact)
        wrong_scale = _CameraPlan(
            plan.motion, "face_closeup", plan.end_scale, plan.start_view,
            plan.end_view, plan.path, plan.coverage,
        )
        self.assertIn("arc_roll_requires_room_for_horizon", _camera_plan_contract_violations(chosen, wrong_scale))
        self.assertIn("unassigned_arc_roll", _camera_plan_contract_violations(
            entity(1, 1), plan,
        ))
        arc_paths = {}
        _, errors = _select_continuous_camera_plan(chosen, line, 0, set(), arc_paths)
        self.assertEqual(errors, ())
        self.assertEqual(arc_paths[1], "arc_right_60_120_70_90")
        next_plan, errors = _select_continuous_camera_plan(
            entity(2, 1, previous_arc_path="arc_right_60_120_70_90"),
            record("arc_right_60_120_70_90"), 0, set(), arc_paths,
        )
        self.assertEqual(errors, ())
        self.assertEqual(next_plan.path, "arc_right_60_120_70_90")
        fallback = _fallback_camera_plan(entity(3, 1, arc_roll_emphasis=True,
            previous_arc_path="arc_right_60_120_70_90"), 0)
        self.assertEqual(fallback.path, "arc_right_60_120_70_90_roll_clockwise")
        self.assertEqual(_camera_plan_contract_violations(entity(3, 1,
            arc_roll_emphasis=True, previous_arc_path="arc_right_60_120_70_90"), fallback), ())

    def test_face_closeup_to_full_body_arc_can_roll_and_return_level(self):
        face_out = entity(
            1, 1, slot=2, shot_duration_ms=4700,
            face_arc_transition="arc_out_of_previous_face_cut",
            previous_camera_in_batch={"scene_number": 1, "shot_index": 1},
            editorial_role="upper_body_performance_coverage",
            required_spine_coverage="upper_body_hands",
            arc_roll_emphasis=True,
        )
        self.assertEqual(
            _select_arc_roll([face_out], set(), {}), face_out.key
        )
        pre_assignment = entity(
            1, 1, slot=2, shot_duration_ms=4700,
            previous_camera_in_batch={"scene_number": 1, "shot_index": 1},
            editorial_role="upper_body_performance_coverage",
            required_spine_coverage="upper_body_hands",
        )
        self.assertEqual(
            _select_arc_roll(
                [pre_assignment], set(),
                {pre_assignment.key: "arc_out_of_previous_face_cut"},
            ), pre_assignment.key
        )
        slot = {**face_out.value, "slot": 2, "camera_protocol": "finite_v1"}
        grammar = build_camera_plan_grammar([slot])
        self.assertIn('camera-start-scale-2 ::= "face_closeup" | "head_and_shoulders"', grammar)
        self.assertIn('camera-end-scale-2 ::= "full_body"', grammar)
        self.assertIn('camera-coverage-2 ::= "whole_body_hands"', grammar)
        line = (
            "MOTION=Arc Shot with large amplitude at fast speed｜"
            "START_SCALE=face_closeup｜END_SCALE=full_body｜"
            "START_VIEW=front｜END_VIEW=side｜"
            "PATH=arc_right_60_120_70_90_roll_clockwise｜COVERAGE=whole_body_hands"
        )
        plan, errors = _parse_camera_plan(line)
        self.assertEqual(errors, ())
        self.assertEqual(_camera_plan_contract_violations(face_out, plan), ())
        previous = _CameraPlan(
            "Zoom In with large amplitude at fast speed", "head_and_shoulders",
            "face_closeup", "front", "front", "zoom_in_35_55", "face_eyes_mouth",
        )
        connected = _connect_camera_geometry(plan, previous)
        self.assertEqual(_camera_plan_contract_violations(face_out, connected), ())
        self.assertIn("Roll Clockwise", _render_camera_plan(connected))
        self.assertIn("arms, and hands", _render_camera_plan(connected))
        fallback = _fallback_camera_plan(face_out, 0)
        self.assertEqual(_camera_plan_contract_violations(face_out, fallback), ())

        face_in = entity(
            2, 1, face_arc_transition="arc_into_next_face_cut",
            arc_roll_emphasis=True,
        )
        self.assertIsNone(_select_arc_roll([face_in], {face_in.key}, {}))

    def test_finite_camera_grammar_keeps_slot_order_and_arc_assignment(self):
        grammar = build_camera_plan_grammar([
            {"slot": 1, "camera_protocol": "finite_v1",
             "arc_permission": "required", "previous_arc_path": "arc_right_60_120_70_90"},
            {"slot": 2, "camera_protocol": "finite_v1",
             "arc_permission": "forbidden"},
        ])
        self.assertIn(r"CAMERA\t1\tMOTION=", grammar)
        self.assertIn(r"CAMERA\t2\tMOTION=", grammar)
        self.assertIn("camera-path-1 ::= \"arc_right_60_120_70_90\"", grammar)
        self.assertIn("camera-motion-1 ::= \"Arc Shot with large amplitude at fast speed\"", grammar)
        self.assertNotIn("Arc Shot", grammar.split("camera-motion-2 ::=", 1)[1])
        self.assertIn(r'"\n"', grammar)
        for slots in ([], [{"slot": 0, "camera_protocol": "finite_v1"}],
                      [{"slot": 1, "camera_protocol": "free_text_v1"}],
                      [{"slot": 1, "camera_protocol": "finite_v1"}] * 2):
            with self.assertRaises(ValueError):
                build_camera_plan_grammar(slots)

    def test_arc_direction_survives_other_motion_and_batch_boundary(self):
        states = {}
        left = "arc_left_60_120_70_90"
        right = "arc_right_60_120_70_90"
        first, errors = _select_continuous_camera_plan(entity(1, 1), record(left), 0, set(), states)
        self.assertEqual(errors, ())
        self.assertEqual(first.path, left)
        zoom = record("zoom_out", "Zoom Out").replace("START_VIEW=side", "START_VIEW=front_three_quarter")
        _, errors = _select_continuous_camera_plan(entity(1, 1, 2, arc_permission="forbidden"), zoom, 1, set(), states)
        self.assertEqual(errors, ())
        next_plan, errors = _select_continuous_camera_plan(entity(2, 1), record(right), 0, set(), states)
        self.assertIn("camera_plan_arc_direction_reversal", errors)
        self.assertEqual(next_plan.path, left)
        cut, errors = _select_continuous_camera_plan(entity(3, 3), record(right), 1, set(), states)
        self.assertEqual(errors, ())
        self.assertEqual(cut.path, right)

    def test_fallback_and_repetition_cannot_reverse_an_existing_orbit(self):
        for path in ("arc_left_60_120_70_90", "arc_right_60_120_70_90"):
            for relation in ("", "arc_into_next_face_cut", "arc_out_of_previous_face_cut"):
                e = entity(2, 1, previous_arc_path=path, face_arc_transition=relation)
                for ordinal in range(8):
                    plan = _fallback_camera_plan(e, ordinal)
                    self.assertEqual(plan.path, path)
                    self.assertEqual(_camera_plan_contract_violations(e, plan), ())
                plan, errors = _select_continuous_camera_plan(e, record(path), 0, set(), {1: path}, ("camera_plan_repetition",))
                self.assertEqual(plan.path, path)

    def test_zoom_and_linear_dolly_cannot_change_subject_viewpoint(self):
        for motion, path in (("Zoom Out", "zoom_out"), ("Zoom In", "zoom_in_35_55"), ("Push In", "push_in"), ("Pull Out", "pull_out")):
            e = entity(1, 1, arc_permission="forbidden")
            plan = _CameraPlan(motion, "medium", "wide", "front", "rear_three_quarter", path, "environment_relation")
            self.assertIn("camera_plan_unmotivated_view_change", _camera_plan_contract_violations(e, plan))
        static = _CameraPlan("Static Shot", "medium", "wide", "front", "front", "stationary", "environment_relation")
        self.assertIn("camera_plan_static_scale_change", _camera_plan_contract_violations(e, static))

    def test_arc_must_change_composition_and_closeup_cannot_claim_hand_coverage(self):
        e = entity(1, 1)
        unchanged = _CameraPlan("Arc Shot with large amplitude at fast speed",
            "face_closeup", "face_closeup", "front", "front",
            "arc_right_60_120_70_90", "face_eyes_mouth")
        self.assertIn("camera_plan_arc_no_composition_change",
            _camera_plan_contract_violations(e, unchanged))
        hidden_hands = _CameraPlan("Arc Shot with large amplitude at fast speed",
            "upper_body", "face_closeup", "side", "front",
            "arc_right_60_120_70_90", "upper_body_hands")
        self.assertIn("camera_plan_coverage_scale_conflict",
            _camera_plan_contract_violations(e, hidden_hands))

    def test_fallback_keeps_assigned_upper_body_coverage(self):
        e = entity(1, 1, editorial_role="upper_body_performance_coverage")
        for ordinal in range(8):
            plan = _fallback_camera_plan(e, ordinal)
            self.assertEqual(plan.coverage, "upper_body_hands")
            self.assertEqual(plan.end_scale, "upper_body")
            self.assertEqual(_camera_plan_contract_violations(e, plan), ())

    def test_whole_body_spine_overrides_upper_body_editorial_fallback(self):
        e = entity(
            1, 1,
            editorial_role="upper_body_performance_coverage",
            required_spine_coverage="whole_body_emotion",
        )
        for ordinal in range(8):
            plan = _fallback_camera_plan(e, ordinal)
            self.assertEqual(plan.coverage, "whole_body_emotion")
            self.assertTrue(
                {plan.start_scale, plan.end_scale}
                & {"wide", "medium_wide", "full_body"}
            )
            self.assertEqual(_camera_plan_contract_violations(e, plan), ())


if __name__ == "__main__":
    unittest.main()
