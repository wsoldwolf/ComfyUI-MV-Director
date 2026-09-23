"""Transport/contract tests, not evidence of real-model creative quality."""

import json
from pathlib import Path
import unittest
from unittest.mock import patch

from core.artifacts import DirectionArtifact
from core.direction.profiles import CAMERA_LYRIC_INTERPRETATIONS, planner_profile_metadata
from core.planner import plan_timeline
from core.planner.engine import (
    _CUE_CARD_FIELDS,
    _Entity,
    _lyric_reading_contexts,
    _parse_cue_card,
    _action_budget_violations,
    build_cue_card_grammar,
)
from test_timeline_planner import (
    CONCEPT, TEMPLATE, INSTRUMENTAL_TAIL, FakePlannerBackend, prompts, runtime,
)


class BoundedInterpretationTests(unittest.TestCase):
    def test_user_staging_candidates_reach_only_scene_interpretation(self):
        candidate = "苔のある大木へ近づき、根元を指先で撫でる。"
        backend = FakePlannerBackend()
        result = plan_timeline(
            backend, template_emd=TEMPLATE, concept_emd=CONCEPT,
            direction=DirectionArtifact(
                camera_profile_id="anime_emotional_mv",
                staging_candidates=(candidate,),
            ),
            lip_sync_mode="off", lip_sync_target="サブジェクト1",
            lip_sync_audio_slot=1, scenes_per_batch=3,
            system_prompts=prompts(), runtime_config=runtime(),
        )
        self.assertTrue(result.complete)
        selection_payloads = [payload for task, payload in backend.calls if task == "staging-selection"]
        self.assertTrue(selection_payloads)
        self.assertTrue(all(
            slot["candidates"][0]["text"] == candidate
            for payload in selection_payloads for slot in payload["slots"]
        ))
        beat_payloads = [payload for task, payload in backend.calls if task == "visual-beats"]
        self.assertTrue(beat_payloads)
        self.assertTrue(all(
            "selected_staging_candidate" not in slot
            for payload in beat_payloads for slot in payload["slots"]
        ))
        action_payloads = [payload for task, payload in backend.calls if task == "actions"]
        self.assertTrue(any(
            slot.get("selected_body_staging_candidate", {}).get("text") == candidate
            for payload in action_payloads for slot in payload["slots"]
        ))
        self.assertTrue(all(
            "selected_staging_candidate" not in slot
            for task, payload in backend.calls if task not in {"visual-beats", "staging-selection"}
            for slot in payload.get("slots", [])
        ))
        self.assertNotIn(candidate, result.emd.text)

    def test_profile_metadata_changes_cache_identity_without_changing_prose(self):
        from core.inference import build_cache_key
        keys = []
        for mode in ("literal", "bounded"):
            with patch.dict(CAMERA_LYRIC_INTERPRETATIONS, {"anime_emotional_mv": mode}):
                keys.append(build_cache_key(
                    task="timeline-planner", algorithm_version="test",
                    inputs={"planner_profile": planner_profile_metadata("anime_emotional_mv")},
                ))
        self.assertNotEqual(*keys)

    def test_grammar_uses_only_existing_schema_and_requested_slots(self):
        grammar = build_cue_card_grammar([2, 7])
        self.assertIn(r"BEAT\t2\t", grammar)
        self.assertIn(r"BEAT\t7\t", grammar)
        for field in _CUE_CARD_FIELDS:
            self.assertEqual(grammar.count(field + "="), 2)
        self.assertNotIn("苔", grammar)
        self.assertNotIn("花", grammar)
        self.assertNotIn("狐火", grammar)
        for bad in ([], [0], [True], [1, 1], ["2"]):
            with self.assertRaises(ValueError):
                build_cue_card_grammar(bad)

    def test_backend_constrains_bounded_beats_and_finite_audit(self):
        from core.inference import LlamaRuntimeConfig
        from nodes.node_timeline_planner.node import _LlamaPlannerBackend
        class Lifecycle:
            effective_n_ctx = 16384
            calls = []
            def count_serialized_prompt(self, _):
                return type("Count", (), {"count": 10, "estimated": False})()
            def complete_chat(self, messages, config, **kwargs):
                self.calls.append(kwargs)
                return "response"
        lifecycle = Lifecycle()
        backend = _LlamaPlannerBackend(lifecycle)
        for task, mode in (("visual-beats", "bounded"), ("visual-beats", "literal"),
                           ("actions", "bounded"), ("action-audit", "bounded")):
            backend.complete_planner(
                task=task, system_prompt="system", config=LlamaRuntimeConfig(),
                payload=json.dumps({"slots": [{"slot": 1}],
                    "planner_policy_contract": {"lyric_interpretation": mode},
                    "audit_contract": {"verdicts": ["PASS", "REJECT:REFERENCE_POSE"]}}))
        self.assertIn("grammar", lifecycle.calls[0])
        self.assertTrue(all("grammar" not in c for c in lifecycle.calls[1:3]))
        self.assertIn("grammar", lifecycle.calls[3])

    def test_compact_variants_are_selected_only_when_supplied_and_bounded(self):
        from nodes.node_timeline_planner.node import _system_prompts
        loaded = _system_prompts()
        self.assertLess(len(loaded["visual-beats-bounded"]), len(loaded["visual-beats"]))
        self.assertNotIn("actions-bounded", loaded)
        for mode in ("bounded", "literal"):
            seen = {}
            class Capture(FakePlannerBackend):
                def complete_planner(self, *, task, system_prompt, **kwargs):
                    seen[task] = system_prompt
                    return super().complete_planner(task=task, system_prompt=system_prompt, **kwargs)
            with patch.dict(CAMERA_LYRIC_INTERPRETATIONS, {"anime_emotional_mv": mode}):
                result = plan_timeline(
                    Capture(), template_emd=TEMPLATE, concept_emd=CONCEPT,
                    direction=DirectionArtifact(camera_profile_id="anime_emotional_mv"),
                    lip_sync_mode="off", lip_sync_target="サブジェクト1", lip_sync_audio_slot=1,
                    scenes_per_batch=3, system_prompts=loaded, runtime_config=runtime())
            self.assertTrue(result.complete)
            for task in ("visual-beats", "actions"):
                variant = task + "-bounded"
                self.assertEqual(seen[task], loaded[variant if mode == "bounded" and variant in loaded else task])

    def test_adjacent_context_respects_order_limits_and_empty_scenes(self):
        lyrics = {
            2: [{"text": "前の行"}, {"text": "御神木は"}],
            5: [{"text": "ただ葉を鳴らすだけ"}],
            8: [],
            12: [{"text": "狐火"}],
        }
        context = _lyric_reading_contexts([2, 5, 8, 12], lyrics)
        self.assertEqual(context[5]["before"], ["前の行", "御神木は"])
        self.assertEqual(context[2]["after"], ["ただ葉を鳴らすだけ"])
        self.assertEqual(context[5]["after"], [])
        self.assertEqual(context[12]["before"], [])
        self.assertEqual(context[2]["before"], [])
        self.assertEqual(context[12]["after"], [])
        long_lines = {1: [{"text": "a" * 300}, {"text": "b" * 300}],
                      2: [], 3: [{"text": "c" * 300}, {"text": "d" * 300}]}
        middle = _lyric_reading_contexts([1, 2, 3], long_lines)[2]
        self.assertEqual(middle["before"], ["b" * 256])
        self.assertEqual(middle["after"], ["c" * 256])

    def test_reading_context_is_never_quote_or_target_authority(self):
        entity = _Entity(2, (2,), {
            "lyrics": [{"text": "ただ葉を鳴らすだけ"}],
            "lyric_reading_context": {"before": ["御神木は"], "after": ["狐火"]},
        })
        for target in ("御神木", "狐火", "灯籠"):
            with self.subTest(target=target):
                card = _parse_cue_card(entity,
                    f"感情=驚き｜根拠={target}｜対象={target}｜接触=許可｜"
                    f"現象=身体操作｜配置=道沿いの{target}｜可視展開={target}へ触れる｜"
                    "身体主導=手｜終端=静止")
                self.assertFalse(card.valid)
                self.assertIn("evidence_not_in_scene_source", card.violations)

    def test_nine_field_schema_accepts_event_led_card_without_body_checklist(self):
        self.assertEqual(len(_CUE_CARD_FIELDS), 9)
        card = _parse_cue_card(_Entity(1, (1,), {"lyrics": [{"text": "雪解け"}]}),
            "感情=希望｜根拠=雪解け｜対象=雪解け｜接触=禁止｜現象=外部自律｜"
            "配置=斜面の雪解け｜可視展開=雪解けの水が斜面から小川へ流れる｜"
            "身体主導=水の流れ、人物は静止｜終端=流れが奥へ抜ける")
        self.assertTrue(card.valid)
        invalid = _parse_cue_card(
            _Entity(1, (1,), {"lyrics": [{"text": "雪解け"}]}),
            "感情=希望｜根拠=雪解け｜対象=雪解け｜接触=自由｜現象=新分類｜"
            "配置=斜面｜可視展開=水が流れる｜身体主導=水｜終端=奥")
        self.assertFalse(invalid.valid)
        self.assertIn("contact_enum", invalid.violations)

    def test_external_event_keeps_grounding_and_face_safety_checks(self):
        event = "狐火が樹間を巡って奥へ抜け、道に光の跡を落とす。"
        base = {"grounded_cue_required": True,
                "visual_beat_grounding": {"valid": True, "target": "狐火"},
                "required_visible_development": event,
                "lyrics": [{"text": "狐火"}]}
        entity = _Entity(1, (1, 1), base)
        self.assertEqual(_action_budget_violations([entity], {(1, 1): event}), {})
        face = _Entity(1, (1, 1), {**base, "performance_role": "face_and_upper_body_accent"})
        self.assertIn("face_performance_missing",
                      _action_budget_violations([face], {(1, 1): event})[(1, 1)])

    def test_policy_and_context_are_forwarded_without_a_new_inference_stage(self):
        results = {}
        for mode in ("literal", "bounded"):
            backend = FakePlannerBackend()
            with patch.dict(CAMERA_LYRIC_INTERPRETATIONS, {"anime_emotional_mv": mode}):
                result = plan_timeline(
                    backend, template_emd=TEMPLATE + INSTRUMENTAL_TAIL,
                    concept_emd=CONCEPT,
                    direction=DirectionArtifact(camera_profile_id="anime_emotional_mv"),
                    lip_sync_mode="off", lip_sync_target="サブジェクト1",
                    lip_sync_audio_slot=1, scenes_per_batch=3,
                    system_prompts=prompts(), runtime_config=runtime())
            self.assertTrue(result.complete)
            results[mode] = backend.calls
            for task, payload in backend.calls:
                if task in ("visual-beats", "actions", "action-audit"):
                    self.assertEqual(payload["planner_policy_contract"]["lyric_interpretation"], mode)
                if task == "visual-beats":
                    for slot in payload["slots"]:
                        self.assertEqual("lyric_reading_context" in slot, mode == "bounded")
                if task == "actions":
                    self.assertTrue(all("lyric_reading_context" not in s for s in payload["slots"]))
        self.assertEqual([t for t, _ in results["literal"]],
                         [t for t, _ in results["bounded"]])

    def test_bounded_contact_and_external_text_remain_as_is(self):
        cases = [
            ("苔", "許可", "身体操作", "大樹の根元の苔",
             "指先で苔の表面を一度撫でて離す。"),
            ("花", "禁止", "外部自律", "参道脇の花",
             "花が風に揺れ、一枚の花弁が奥へ流れる。"),
            ("狐火", "禁止", "外部自律", "樹間を浮遊する狐火",
             "狐火が前景から頭上を回り奥へ抜け、道に光を落とす。"),
        ]
        for target, contact, phenomenon, anchor, development in cases:
            with self.subTest(target=target):
                class EventBackend(FakePlannerBackend):
                    def complete_planner(self, *, task, system_prompt, payload, config,
                                         interrupt_callback=None):
                        value = json.loads(payload)
                        if task == "visual-beats":
                            self.calls.append((task, value))
                            card = (f"感情=懐旧｜根拠={target}｜対象={target}｜接触={contact}｜"
                                    f"現象={phenomenon}｜配置={anchor}｜可視展開={development}｜"
                                    "身体主導=出来事の進行｜終端=余韻")
                            return "\n".join(f"BEAT\t{s['slot']}\t{card}" for s in value["slots"])
                        if task == "actions":
                            self.calls.append((task, value))
                            return "\n".join(
                                f"ACTION\t{s['slot']}\t" +
                                (anchor + "を前に立ち止まる。" if s["shot_index"] == 1 else development)
                                for s in value["slots"])
                        return super().complete_planner(
                            task=task, system_prompt=system_prompt, payload=payload,
                            config=config, interrupt_callback=interrupt_callback)
                backend = EventBackend()
                result = plan_timeline(
                    backend, template_emd=TEMPLATE.replace("千年鳥居をくぐるそなたよ", target),
                    concept_emd=CONCEPT,
                    direction=DirectionArtifact(camera_profile_id="anime_emotional_mv"),
                    lip_sync_mode="off", lip_sync_target="サブジェクト1", lip_sync_audio_slot=1,
                    scenes_per_batch=3, system_prompts=prompts(), runtime_config=runtime())
                self.assertTrue(result.complete)
                self.assertEqual([text for _, _, text in result.content.actions],
                                 [anchor + "を前に立ち止まる。", development])
                self.assertEqual(sum(t == "visual-beats" for t, _ in backend.calls), 1)
                self.assertEqual(sum(t == "actions" for t, _ in backend.calls), 1)

    def test_prompts_share_contact_and_event_contract_without_new_output_fields(self):
        root = Path(__file__).resolve().parents[1] / "prompts"
        beat = (root / "timeline_planner_visual_beats_system_prompt.txt").read_text(encoding="utf-8")
        action = (root / "timeline_planner_actions_system_prompt.txt").read_text(encoding="utf-8")
        audit = (root / "timeline_planner_action_audit_system_prompt.txt").read_text(encoding="utf-8")
        self.assertIn("Keep the existing nine fields", beat)
        self.assertIn("never quote it as 根拠", beat)
        self.assertIn("non-destructive", beat)
        self.assertIn("non-destructive", action)
        self.assertIn("non-destructive", audit)
        self.assertIn("reaction and release slots need not repeat the noun", action)
        self.assertIn("grounded_cue_phase takes precedence", action)
        self.assertIn("grounded_cue_phase takes precedence", audit)
        self.assertNotIn("naming a noun alone always yields", beat)


if __name__ == "__main__":
    unittest.main()
