"""Discovery contracts are structural tests, not a semantic-quality score."""

import copy
import json
import unittest

from core.artifacts import DirectionArtifact
from core.planner import plan_timeline
from core.planner.cue_constraints import (
    build_discovery_grammar, build_grounded_cue_grammar,
    parse_discovery, select_scene_cue,
)
from core.planner.engine import (
    _Entity, _parse_cue_card, _request_entities,
    _with_grounding_transfer_requirements,
)
from nodes.node_timeline_planner.node import _system_prompts
from test_timeline_planner import CONCEPT, TEMPLATE, FakePlannerBackend, runtime


class CueDiscoveryTests(unittest.TestCase):
    def test_discovery_grammar_is_source_bound_and_uses_three_columns(self):
        grammar = build_discovery_grammar([{"slot": 7, "text": "雪を見つめる"}])
        self.assertIn(r"DISCOVERY\t7\t", grammar)
        self.assertIn('"none|なし"', grammar)
        self.assertIn('"雪"', grammar)
        for target in ("苔", "花", "狐火", "御神木", "灯籠"):
            self.assertNotIn(target, grammar)
        for bad in ([], [{"slot": 0, "text": "雪"}], [{"slot": 1, "text": ""}],
                    [{"slot": 1, "text": "雪\n月"}]):
            with self.assertRaises(ValueError):
                build_discovery_grammar(bad)

    def test_discovery_preserves_llm_span_and_rejects_foreign_or_unknown_value(self):
        self.assertEqual(parse_discovery("motif|御神木", "御神木は"),
                         {"kind": "motif", "target": "御神木", "evidence": "御神木は"})
        self.assertIsNone(parse_discovery("none|なし", "想い出"))
        for bad in ("motif|灯籠", "other|御神木", "motif|", "none|御神木", "御神木"):
            with self.assertRaises(ValueError):
                parse_discovery(bad, "御神木は")

    def test_latest_source_cue_does_not_rank_fallible_kind_labels(self):
        sources = ["塔の前", "雪の中", "手を結ぶ"]
        found = {s: parse_discovery(t, s) for s, t in zip(sources,
                 ["motif|塔", "place|雪", "body|手"])}
        self.assertEqual(select_scene_cue(sources, found), [found["雪の中"]])
        self.assertEqual(select_scene_cue(["手を結ぶ"], found), [])
        self.assertEqual(select_scene_cue([], found), [])
        self.assertEqual(select_scene_cue(["塔の前"], found), [found["塔の前"]])

    def test_selected_target_and_evidence_share_one_branch(self):
        source = "雪へ還る"
        slot = {"slot": 2, "lyrics": [{"text": source}, {"text": "塔の前"}],
                "discovered_cues": [parse_discovery("motif|雪", source)]}
        grammar = build_grounded_cue_grammar([slot])
        self.assertIn("雪｜根拠=雪へ還る｜感情=", grammar)
        self.assertIn("｜配置=雪", grammar)
        self.assertNotIn("塔", grammar)
        self.assertNotIn('s2-l0-c0 ::=', grammar)
        slot["discovered_cues"] = [parse_discovery("motif|月", "月へ還る")]
        with self.assertRaises(ValueError):
            build_grounded_cue_grammar([slot])

    def test_discovered_effect_keeps_autonomous_noncontact_cue_type(self):
        source = "狐火へ問う"
        grammar = build_grounded_cue_grammar([{
            "slot": 1, "lyrics": [{"text": source}],
            "discovered_cues": [parse_discovery("effect|狐火", source)],
        }])
        self.assertIn('"｜接触=禁止"', grammar)
        self.assertIn('"｜現象=外部自律"', grammar)
        self.assertNotIn('"許可"', grammar)
        self.assertNotIn('"身体操作"', grammar)

    def test_scene_spine_keeps_autonomous_effect_development_in_event(self):
        cue = {
            "valid": True, "target": "狐火", "phenomenon": "外部自律",
            "spatial_anchor": "狐火が前景から奥へ漂う",
            "visible_development": "狐火が宙を舞い石畳へ光を落とす",
        }
        entities = [
            _Entity(1, (1, index), {
                "visual_beat_grounding": cue,
                "scene_spine_step": {"phase": phase},
                "performance_role": "expressive_hand_arm_performance",
            })
            for index, phase in ((1, "setup"), (2, "event"))
        ]
        transferred = _with_grounding_transfer_requirements(entities, automatic=True)
        self.assertEqual(transferred[0].value["required_spatial_anchor"], cue["spatial_anchor"])
        self.assertEqual(transferred[1].value["required_visible_development"], cue["visible_development"])

    def test_explicit_empty_discovery_does_not_reopen_arbitrary_source_targets(self):
        slot = {"slot": 1, "lyrics": [{"text": "思い出"}], "discovered_cues": []}
        grammar = build_grounded_cue_grammar([slot])
        self.assertNotIn("思", grammar)
        self.assertIn("なし｜根拠=なし", grammar)
        del slot["discovered_cues"]
        self.assertIn('"思"', build_grounded_cue_grammar([slot]))

    def test_target_first_and_legacy_order_have_identical_field_values(self):
        prefix = ["感情=憧れ", "根拠=雪へ還る", "対象=雪"]
        tail = ["接触=禁止", "現象=外部自律", "配置=雪が参道脇に積もる", "可視展開=雪が枝から落ちる",
                "身体主導=目線", "終端=枝が露わになる"]
        entity = _Entity(1, (1,), {"lyrics": [{"text": "雪へ還る"}]})
        legacy = _parse_cue_card(entity, "｜".join(prefix + tail))
        revised = _parse_cue_card(entity, "｜".join([prefix[2], prefix[1], prefix[0]] + tail))
        self.assertTrue(revised.valid)
        self.assertEqual(revised, legacy)

    def test_generation_omits_old_prose_without_mutating_audit_history_or_direction(self):
        backend = FakePlannerBackend()
        shared = {"planner_policy_contract": {"lyric_interpretation": "bounded"},
                  "direction": {"time_lighting": ["夜間"]}, "recent_action_history": ["old"],
                  "recent_visual_beat_history": ["old"], "forbidden_recent_outputs": ["old"]}
        entities = [_Entity(1, (1, 1), {"previous_batch_action": "old", "must_differ_from": ["old"],
                     "rejected_output": "current candidate", "shot_index": 1})]
        before = copy.deepcopy((shared, entities))
        for task, record in (("actions", "ACTION"), ("action-audit", "AUDIT")):
            _request_entities(backend, task=task, record_type=record, entities=entities,
                              shared=shared, system_prompt="test", runtime_config=runtime(), interrupt_callback=None)
        self.assertEqual((shared, entities), before)
        generated, audited = [call[1] for call in backend.calls]
        self.assertNotIn("recent_action_history", generated)
        self.assertNotIn("previous_batch_action", generated["slots"][0])
        self.assertEqual(generated["direction"], shared["direction"])
        self.assertEqual(generated["slots"][0]["rejected_output"], "current candidate")
        self.assertEqual(audited["recent_action_history"], ["old"])

    def test_builtin_bounded_pipeline_calls_discovery_and_forwards_selection(self):
        class Capture(FakePlannerBackend):
            def complete_planner(self, *, task, payload, config, **kwargs):
                if task == "lyric-cues":
                    self.discovery_max_tokens = config.max_tokens
                    value = json.loads(payload)
                    self.calls.append((task, value))
                    return "\n".join(f"DISCOVERY\t{i['slot']}\tplace|千年鳥居" for i in value["slots"])
                return super().complete_planner(task=task, payload=payload, config=config, **kwargs)
        backend = Capture()
        result = plan_timeline(backend, template_emd=TEMPLATE, concept_emd=CONCEPT,
                              direction=DirectionArtifact(camera_profile_id="anime_emotional_mv"),
                              lip_sync_mode="off", lip_sync_target="サブジェクト1", lip_sync_audio_slot=1,
                              scenes_per_batch=3, system_prompts=_system_prompts(), runtime_config=runtime())
        self.assertTrue(result.complete)
        discovery = [p for task, p in backend.calls if task == "lyric-cues"]
        self.assertEqual(len(discovery), 1)
        self.assertEqual(len(discovery[0]["slots"]), 1)
        self.assertLessEqual(backend.discovery_max_tokens, 768)
        beat = next(p for task, p in backend.calls if task == "visual-beats")
        self.assertEqual(beat["slots"][0]["discovered_cues"][0]["target"], "千年鳥居")

    def test_discovered_effect_type_retries_invalid_cue_and_reaches_action(self):
        class Capture(FakePlannerBackend):
            beat_calls = 0

            def complete_planner(self, *, task, payload, config, **kwargs):
                value = json.loads(payload)
                if task == "lyric-cues":
                    self.calls.append((task, value))
                    return "\n".join(
                        f"DISCOVERY\t{item['slot']}\teffect|千年鳥居"
                        for item in value["slots"]
                    )
                if task == "visual-beats":
                    self.calls.append((task, value))
                    self.beat_calls += 1
                    contact, phenomenon = (
                        ("許可", "身体操作") if self.beat_calls == 1
                        else ("禁止", "外部自律")
                    )
                    return "\n".join(
                        f"BEAT\t{item['slot']}\t感情=驚き｜根拠=千年鳥居｜対象=千年鳥居｜"
                        f"接触={contact}｜現象={phenomenon}｜配置=千年鳥居が奥に見える｜"
                        "可視展開=千年鳥居の周囲の光が奥へ進む｜身体主導=視線｜終端=見送る"
                        for item in value["slots"]
                    )
                return super().complete_planner(task=task, payload=payload, config=config, **kwargs)

        backend = Capture()
        plan_timeline(
            backend, template_emd=TEMPLATE, concept_emd=CONCEPT,
            direction=DirectionArtifact(camera_profile_id="anime_emotional_mv"),
            lip_sync_mode="off", lip_sync_target="サブジェクト1", lip_sync_audio_slot=1,
            scenes_per_batch=3, system_prompts=_system_prompts(), runtime_config=runtime(),
        )
        self.assertEqual(backend.beat_calls, 2)
        action = next(payload for task, payload in backend.calls if task == "actions")
        self.assertTrue(all(slot["discovered_cue_kind"] == "effect" for slot in action["slots"]))
        self.assertTrue(all(
            slot["priority_lyric_cues"][0]["kind"] == "external_effect"
            for slot in action["slots"]
        ))


if __name__ == "__main__":
    unittest.main()
