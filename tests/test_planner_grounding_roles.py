"""Face coverage must not accidentally consume the Scene event contract."""

import json
import unittest

from core.artifacts import DirectionArtifact
from core.planner import plan_timeline
from core.planner.engine import (
    _Entity, _action_budget_violations, _with_grounding_transfer_requirements,
)
from test_timeline_planner import CONCEPT, FakePlannerBackend, prompts, runtime


FACE = "face_and_upper_body_accent"
GROUNDING = {
    "valid": True, "target": "苔", "spatial_anchor": "大樹の根元",
    "visible_development": "苔が湿った樹皮を覆う",
}


def entities(roles, *, scene=12, priority=False):
    return [
        _Entity(scene, (scene, index), {
            "performance_role": role, "visual_beat_grounding": dict(GROUNDING),
            "grounded_cue_required": True,
            "priority_lyric_cues": [{"token": "苔", "kind": "object"}] if priority else [],
            "grounded_cue_phase": "old_phase", "priority_cue_phase": "old_phase",
        })
        for index, role in enumerate(roles, 1)
    ]


class GroundingRoleTests(unittest.TestCase):
    def test_face_first_keeps_face_expression_and_moves_event_to_coverage(self):
        original = entities([FACE, "expressive_hand_arm_performance",
                             "environment_interaction_or_body_turn", "expressive_resolution"])
        revised = _with_grounding_transfer_requirements(original, automatic=True)
        self.assertNotIn("required_spatial_anchor", revised[0].value)
        self.assertNotIn("required_visible_development", revised[0].value)
        self.assertEqual(revised[0].value["grounded_cue_phase"], "")
        self.assertEqual(revised[1].value["required_spatial_anchor"], GROUNDING["spatial_anchor"])
        self.assertEqual(revised[2].value["required_visible_development"], GROUNDING["visible_development"])
        self.assertEqual([e.value["grounded_cue_phase"] for e in revised[1:]],
                         ["establish_and_relation", "event_and_reaction", "release"])
        self.assertEqual(original[0].value["grounded_cue_phase"], "old_phase")
        self.assertTrue(all("required_spatial_anchor" not in e.value for e in original))
        actions = {
            (12, 1): "まぶたを半ば伏せ、歌う口元に微笑みを残す。",
            (12, 2): "大樹の根元へ視線を向ける。",
            (12, 3): "苔が湿った樹皮を覆う様子を見つめる。",
            (12, 4): "奥へ向き直り静止する。",
        }
        self.assertEqual(_action_budget_violations(revised, actions), {})
        invalid = _action_budget_violations(revised, {**actions, (12, 2): "視線を向ける。"})
        self.assertIn("missing_spatial_anchor", invalid[(12, 2)])
        invalid = _action_budget_violations(revised, {**actions, (12, 1): "人物が静止する。"})
        self.assertIn("face_performance_missing", invalid[(12, 1)])

    def test_middle_and_multiple_face_slots_are_not_event_slots(self):
        for roles in (["coverage", FACE, "coverage"], [FACE, "coverage", FACE, "coverage"]):
            for priority in (False, True):
                with self.subTest(roles=roles, priority=priority):
                    result = _with_grounding_transfer_requirements(
                        entities(roles, priority=priority), automatic=not priority)
                    coverage = [e for e in result if e.value["performance_role"] != FACE]
                    self.assertIn("required_spatial_anchor", coverage[0].value)
                    self.assertIn("required_visible_development", coverage[1].value)
                    for e in result:
                        if e.value["performance_role"] == FACE:
                            self.assertNotIn("required_spatial_anchor", e.value)
                            self.assertNotIn("required_visible_development", e.value)
                            self.assertEqual(e.value["grounded_cue_phase"], "")
                        self.assertEqual(e.value["priority_cue_phase"],
                                         e.value["grounded_cue_phase"] if priority else "")

    def test_one_coverage_slot_gets_both_fragments_without_losing_event(self):
        result = _with_grounding_transfer_requirements(entities([FACE, "coverage"]), automatic=True)
        self.assertEqual(result[1].value["required_spatial_anchor"], GROUNDING["spatial_anchor"])
        self.assertEqual(result[1].value["required_visible_development"], GROUNDING["visible_development"])
        self.assertEqual(result[1].value["grounded_cue_phase"], "establish_relation_reaction_release")

    def test_face_only_layout_does_not_silently_drop_grounding(self):
        for roles in ([FACE], [FACE, FACE]):
            result = _with_grounding_transfer_requirements(entities(roles), automatic=True)
            self.assertIn("required_spatial_anchor", result[0].value)
            self.assertIn("required_visible_development", result[-1].value)

    def test_disabled_invalid_and_multiple_scene_scopes(self):
        source = entities([FACE, "coverage"])
        self.assertEqual(_with_grounding_transfer_requirements(source), source)
        invalid = [_Entity(e.scene_number, e.key, {**e.value,
                    "visual_beat_grounding": {"valid": False}}) for e in source]
        self.assertEqual(_with_grounding_transfer_requirements(invalid, automatic=True), invalid)
        source += entities(["coverage", FACE, "coverage"], scene=13)
        # Output order must follow the input even when it is not chronological.
        source.reverse()
        result = _with_grounding_transfer_requirements(source, automatic=True)
        self.assertEqual([e.key for e in result], [e.key for e in source])
        by_key = {e.key: e.value for e in result}
        self.assertIn("required_spatial_anchor", by_key[(12, 2)])
        self.assertIn("required_visible_development", by_key[(12, 2)])
        self.assertIn("required_spatial_anchor", by_key[(13, 1)])
        self.assertIn("required_visible_development", by_key[(13, 3)])

    def test_lip_sync_planner_completes_with_face_and_event_text_as_is(self):
        template = (
            "> `シーン` 1\n# シーン 00:00.000 --> 00:10.125\n* `H3長` 243\n"
            "> `セクション` CHORUS\n> `歌詞開始` 00:00.000\n"
            "> `歌詞終了` 00:09.000\n> `歌詞` 苔\n"
            "## ショット 00:00.000\n* 未計画\n## ショット 00:02.500\n* 未計画\n"
            "## ショット 00:05.000\n* 未計画\n## ショット 00:07.500\n* 未計画\n"
        )
        generated = {}
        class Backend(FakePlannerBackend):
            def complete_planner(self, *, task, system_prompt, payload, config,
                                 interrupt_callback=None):
                value = json.loads(payload)
                if task in ("visual-beats", "actions"):
                    self.calls.append((task, value))
                    rows = []
                    for slot in value["slots"]:
                        if task == "visual-beats":
                            text = ("感情=懐旧｜根拠=苔｜対象=苔｜接触=禁止｜現象=なし｜"
                                    "配置=大樹の根元｜可視展開=苔が湿った樹皮を覆う｜身体主導=視線｜終端=静止")
                        else:
                            text = {
                                1: "まぶたを半ば伏せ、歌う口元に微笑みを残す。",
                                2: "大樹の根元へ視線を向ける。",
                                3: "苔が湿った樹皮を覆う様子を見つめる。",
                                4: "奥へ向き直り静止する。",
                            }[slot["shot_index"]]
                            generated[(slot["scene_number"], slot["shot_index"])] = text
                        rows.append(f"{'BEAT' if task == 'visual-beats' else 'ACTION'}\t{slot['slot']}\t{text}")
                    return "\n".join(rows)
                return super().complete_planner(task=task, system_prompt=system_prompt,
                    payload=payload, config=config, interrupt_callback=interrupt_callback)
        backend = Backend()
        result = plan_timeline(backend, template_emd=template, concept_emd=CONCEPT,
            direction=DirectionArtifact(camera_profile_id="anime_emotional_mv"),
            lip_sync_mode="lyrics", lip_sync_target="サブジェクト1", lip_sync_audio_slot=1,
            scenes_per_batch=3, system_prompts=prompts(), runtime_config=runtime())
        self.assertTrue(result.complete)
        self.assertEqual({(s, k): text for s, k, text in result.content.actions}, generated)
        calls = [p for task, p in backend.calls if task == "actions"]
        self.assertEqual(len(calls), 1)
        self.assertEqual(calls[0]["slots"][0]["performance_role"], FACE)
        self.assertNotIn("required_spatial_anchor", calls[0]["slots"][0])
        self.assertIn("required_spatial_anchor", calls[0]["slots"][1])


if __name__ == "__main__":
    unittest.main()
