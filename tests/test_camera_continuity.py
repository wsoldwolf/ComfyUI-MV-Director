"""Regressions for loop-10 orbit reversal and impossible optical moves."""

import unittest
from core.planner.engine import (
    _Entity, _CameraPlan, _camera_plan_contract_violations,
    _fallback_camera_plan, _select_continuous_camera_plan,
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


if __name__ == "__main__":
    unittest.main()
