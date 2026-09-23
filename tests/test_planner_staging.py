"""Scene-local staging transport and spatial grounding regression tests."""

import json
import unittest

from core.artifacts import DirectionArtifact
from core.planner import plan_timeline
from core.planner.cue_constraints import build_grounded_cue_grammar
from core.planner.engine import _Entity, _parse_cue_card
from core.planner.staging import (
    build_staging_selection_grammar,
    parse_staging_selection,
)
from test_timeline_planner import (
    CONCEPT, INSTRUMENTAL_TAIL, TEMPLATE, FakePlannerBackend, prompts, runtime,
)


class StagingSelectionTests(unittest.TestCase):
    def test_spatial_event_and_body_phrase_can_share_one_scene(self):
        class SelectTwo(FakePlannerBackend):
            def complete_planner(self, *, task, system_prompt, payload, config,
                                 interrupt_callback=None):
                if task == "staging-selection":
                    value = json.loads(payload)
                    self.calls.append((task, value))
                    return (
                        "STAGING\t1\tC2|なし"
                        if value["slots"][0].get("selection_role") == "body"
                        else "STAGING\t1\tC1|千年鳥居は参道奥に立つ"
                    )
                if task == "lyric-cues":
                    value = json.loads(payload)
                    self.calls.append((task, value))
                    return "\n".join(
                        f"DISCOVERY\t{item['slot']}\tmotif|千年鳥居"
                        for item in value["slots"]
                    )
                if task == "scene-spine":
                    value = json.loads(payload)
                    self.calls.append((task, value))
                    return "\n".join(
                        f"SPINE\t{item['slot']}\t" + (
                            "PHASE=event｜FROM=両足で立つ｜ADVANCE=千年鳥居へ視線を向ける"
                            "｜TO=鳥居を見る｜SHOW=whole_body" if index == 0 else
                            "PHASE=response｜FROM=鳥居を見る｜ADVANCE=胸郭と片腕を開く"
                            "｜TO=腕を緩める｜SHOW=face_eyes_mouth"
                        ) for index, item in enumerate(value["slots"])
                    )
                return super().complete_planner(
                    task=task, system_prompt=system_prompt, payload=payload,
                    config=config, interrupt_callback=interrupt_callback,
                )

        backend = SelectTwo()
        result = plan_timeline(
            backend, template_emd=TEMPLATE, concept_emd=CONCEPT,
            direction=DirectionArtifact(
                camera_profile_id="anime_emotional_mv",
                motion_profile_id="anime_emotional_mv",
                staging_candidates=(
                    "千年鳥居は参道奥に立ち、人物は手前で歌う",
                    "両足支持から胸郭と片腕を順に動かし、表情へつなぐ",
                ),
            ),
            lip_sync_mode="off", lip_sync_target="サブジェクト1",
            lip_sync_audio_slot=1, scenes_per_batch=3,
            system_prompts={**prompts(), "lyric-cues": "discover", "scene-spine": "spine"},
            runtime_config=runtime(),
        )
        self.assertTrue(result.complete)
        choices = [payload for task, payload in backend.calls if task == "staging-selection"]
        self.assertEqual(len(choices), 2)
        self.assertEqual(choices[1]["slots"][0]["selection_role"], "body")
        beat = next(payload for task, payload in backend.calls if task == "visual-beats")
        self.assertEqual(beat["slots"][0]["selected_staging_candidate"]["id"], "C1")
        spine = next(payload for task, payload in backend.calls if task == "scene-spine")
        self.assertEqual(spine["selected_body_staging_candidate"]["id"], "C2")
        action = next(payload for task, payload in backend.calls if task == "actions")
        self.assertTrue(all(
            slot["selected_body_staging_candidate"]["id"] == "C2"
            for slot in action["slots"]
        ))

    def test_selection_grammar_and_exact_id_validation(self):
        grammar = build_staging_selection_grammar(["C1", "C3"])
        self.assertIn('"C1|" anchor', grammar)
        self.assertIn('"C3|" anchor', grammar)
        self.assertNotIn('"C2|"', grammar)
        candidates = ("大樹の根元の苔を撫でる", "胸郭から腕へ動きを伝える")
        self.assertEqual(
            parse_staging_selection(
                "C1|苔は参道脇の大樹の根元に生える", candidates,
                current_target="苔",
            ),
            (1, "苔は参道脇の大樹の根元に生える"),
        )
        self.assertIsNone(parse_staging_selection("NONE|なし", candidates))
        with self.assertRaisesRegex(ValueError, "must itself name"):
            parse_staging_selection(
                "C2|苔は大樹の根元に生える", candidates,
                current_target="苔",
            )
        for invalid in ("C0|なし", "C3|なし", "C1|なし", "C1|木の根元", "C1|苔｜木", "C1|"):
            with self.subTest(invalid=invalid), self.assertRaises(ValueError):
                parse_staging_selection(invalid, candidates, current_target="苔")

    def test_selected_spatial_relation_is_cue_prefix_and_required_by_parser(self):
        selected = {"id": "C1", "text": "大樹の根元の苔を撫でる",
                    "anchor": "苔は参道脇の大樹の根元に生える"}
        slot = {"slot": 1, "lyrics": [{"text": "苔へと還る"}],
                "selected_staging_candidate": selected}
        grammar = build_grounded_cue_grammar([slot])
        self.assertIn("配置=対象位置:苔は参道脇の大樹の根元に生える", grammar)
        self.assertIn("人物位置:", grammar)
        entity = _Entity(1, (1,), slot)
        base = ("対象=苔｜根拠=苔へと還る｜感情=追憶｜接触=許可｜現象=身体操作｜"
                "配置={anchor}｜可視展開=人物が苔を撫でて手を離す｜身体主導=腕を伸ばす｜終端=静止")
        self.assertTrue(_parse_cue_card(entity, base.format(anchor=selected["anchor"])).valid)
        divided = _parse_cue_card(entity, base.format(
            anchor="対象位置:" + selected["anchor"] + "；人物位置:参道脇の地面で大樹の手前",
        ))
        self.assertTrue(divided.valid)
        self.assertEqual(
            divided.spatial_anchor,
            "対象位置:" + selected["anchor"] + "；人物位置:参道脇の地面で大樹の手前",
        )
        incomplete = _parse_cue_card(entity, base.format(
            anchor="対象位置:" + selected["anchor"],
        ))
        self.assertIn("spatial_roles_incomplete", incomplete.violations)
        wrong = _parse_cue_card(entity, base.format(anchor="苔は石段の上に生える"))
        self.assertIn("staging_anchor_missing", wrong.violations)

    def test_body_only_candidate_is_not_sent_as_visual_beat_location(self):
        class SelectBody(FakePlannerBackend):
            def complete_planner(self, *, task, system_prompt, payload, config,
                                 interrupt_callback=None):
                if task == "staging-selection":
                    self.calls.append((task, json.loads(payload)))
                    return "STAGING\t1\tC1|なし"
                return super().complete_planner(
                    task=task, system_prompt=system_prompt, payload=payload,
                    config=config, interrupt_callback=interrupt_callback,
                )

        backend = SelectBody()
        result = plan_timeline(
            backend, template_emd=TEMPLATE, concept_emd=CONCEPT,
            direction=DirectionArtifact(
                camera_profile_id="anime_emotional_mv",
                staging_candidates=("両足で立ち、胸郭から腕へ動きを伝える",),
            ),
            lip_sync_mode="off", lip_sync_target="サブジェクト1",
            lip_sync_audio_slot=1, scenes_per_batch=3,
            system_prompts=prompts(), runtime_config=runtime(),
        )
        self.assertTrue(result.complete)
        beat = next(payload for task, payload in backend.calls if task == "visual-beats")
        self.assertNotIn("selected_staging_candidate", beat["slots"][0])
        action = next(payload for task, payload in backend.calls if task == "actions")
        self.assertEqual(action["slots"][0]["selected_body_staging_candidate"]["id"], "C1")

    def test_spatial_candidate_is_used_in_one_scene_and_action_coverage(self):
        class SelectOnce(FakePlannerBackend):
            def complete_planner(self, *, task, system_prompt, payload, config,
                                 interrupt_callback=None):
                if task == "staging-selection":
                    value = json.loads(payload)
                    self.calls.append((task, value))
                    return "STAGING\t1\tC1|千年鳥居は参道奥に立つ"
                if task == "lyric-cues":
                    value = json.loads(payload)
                    self.calls.append((task, value))
                    return "\n".join(
                        f"DISCOVERY\t{item['slot']}\tmotif|千年鳥居"
                        for item in value["slots"]
                    )
                return super().complete_planner(
                    task=task, system_prompt=system_prompt, payload=payload,
                    config=config, interrupt_callback=interrupt_callback,
                )

        backend = SelectOnce()
        result = plan_timeline(
            backend, template_emd=TEMPLATE + INSTRUMENTAL_TAIL,
            concept_emd=CONCEPT,
            direction=DirectionArtifact(
                camera_profile_id="anime_emotional_mv",
                staging_candidates=("千年鳥居は参道奥に立ち、人物はその手前で歌う",),
            ),
            lip_sync_mode="off", lip_sync_target="サブジェクト1",
            lip_sync_audio_slot=1, scenes_per_batch=3,
            system_prompts={**prompts(), "lyric-cues": "discover"},
            runtime_config=runtime(),
        )
        self.assertTrue(result.complete)
        choices = [payload for task, payload in backend.calls if task == "staging-selection"]
        self.assertEqual(len(choices), 1)
        beats = [slot for task, payload in backend.calls if task == "visual-beats"
                 for slot in payload["slots"]]
        self.assertEqual(beats[0]["selected_staging_candidate"]["anchor"],
                         "千年鳥居は参道奥に立つ")
        self.assertNotIn("selected_staging_candidate", beats[1])
        actions = [slot for task, payload in backend.calls if task == "actions"
                   for slot in payload["slots"] if slot["scene_number"] == 1]
        self.assertEqual(len(actions), 2)
        self.assertTrue(all(
            slot["required_spatial_anchor"] == "千年鳥居は参道奥に立つ"
            for slot in actions
        ))

    def test_missing_selected_anchor_blocks_incomplete_emd_after_one_retry(self):
        class DropsAnchor(FakePlannerBackend):
            def complete_planner(self, *, task, system_prompt, payload, config,
                                 interrupt_callback=None):
                if task == "lyric-cues":
                    value = json.loads(payload)
                    self.calls.append((task, value))
                    return "\n".join(
                        f"DISCOVERY\t{item['slot']}\tmotif|千年鳥居"
                        for item in value["slots"]
                    )
                if task == "staging-selection":
                    self.calls.append((task, json.loads(payload)))
                    return "STAGING\t1\tC1|千年鳥居は参道奥に立つ"
                text = super().complete_planner(
                    task=task, system_prompt=system_prompt, payload=payload,
                    config=config, interrupt_callback=interrupt_callback,
                )
                return text.replace("千年鳥居は参道奥に立つ", "参道奥の鳥居") if task == "visual-beats" else text

        backend = DropsAnchor()
        result = plan_timeline(
            backend, template_emd=TEMPLATE, concept_emd=CONCEPT,
            direction=DirectionArtifact(
                camera_profile_id="anime_emotional_mv",
                staging_candidates=("千年鳥居は参道奥に立つ",),
            ),
            lip_sync_mode="off", lip_sync_target="サブジェクト1",
            lip_sync_audio_slot=1, scenes_per_batch=3,
            system_prompts={**prompts(), "lyric-cues": "discover"},
            runtime_config=runtime(),
        )
        self.assertFalse(result.complete)
        self.assertIn("STAGING_ANCHOR", str(result.missing))
        self.assertEqual(
            len([task for task, _ in backend.calls if task == "visual-beats"]), 2
        )


if __name__ == "__main__":
    unittest.main()
