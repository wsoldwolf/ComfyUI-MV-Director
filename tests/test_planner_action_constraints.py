import json
import unittest

from core.artifacts import DirectionArtifact
from core.inference import LlamaRuntimeConfig
from core.planner import build_action_grammar, build_action_audit_grammar, plan_timeline
from nodes.node_timeline_planner.node import _LlamaPlannerBackend
from test_timeline_planner import CONCEPT, TEMPLATE, FakePlannerBackend, prompts, runtime


class ActionConstraintTests(unittest.TestCase):
    def test_action_slots_and_exact_fragments_are_escaped_not_rewritten(self):
        fragment = '大樹の根元の「苔」 "x" \\ y'
        grammar = build_action_grammar([
            {"slot": 2, "required_spatial_anchor": fragment},
            {"slot": 5, "required_spatial_anchor": "配置", "required_visible_development": "変化"},
            {"slot": 8},
        ])
        self.assertIn(json.dumps(fragment, ensure_ascii=False), grammar)
        self.assertIn(r'"ACTION\t2\t"', grammar)
        self.assertIn('"配置" bridge "変化" char*', grammar)
        self.assertIn(r'"ACTION\t8\t" char+', grammar)
        self.assertIn('bridge ::= char{0,32}', grammar)
        self.assertNotIn("狐火", grammar)
        self.assertNotIn("まぶた", grammar)
        self.assertEqual(build_action_grammar([{"slot": 1, "required_spatial_anchor": "同一",
                         "required_visible_development": "同一"}]).count('"同一"'), 1)

    def test_invalid_contracts_are_not_silently_repaired(self):
        for slots in ([], [{"slot": 0}], [{"slot": True}], [{"slot": 1}, {"slot": 1}],
                      [{"slot": 1, "required_spatial_anchor": "first\nsecond"}],
                      [{"slot": 1, "required_visible_development": None}]):
            with self.subTest(slots=slots), self.assertRaises(ValueError):
                build_action_grammar(slots)
        for slots, reasons in (([], ["CODE"]), ([0], ["CODE"]), ([1], []), ([1], ["not a code"])):
            with self.assertRaises(ValueError):
                build_action_audit_grammar(slots, reasons)

    def test_audit_grammar_allows_only_one_known_verdict_per_requested_slot(self):
        grammar = build_action_audit_grammar([1, 9], ["REFERENCE_POSE", "MISSING_GROUNDED_CUE"])
        self.assertIn(r'"AUDIT\t1\t" verdict', grammar)
        self.assertIn(r'"AUDIT\t9\t" verdict', grammar)
        self.assertIn('verdict ::= "PASS" | "REJECT:" reason', grammar)
        self.assertNotIn("char", grammar)
        self.assertNotIn("INVALID_AUDIT_VERDICT", grammar)

    def test_production_backend_constrains_initial_and_retry_actions_only_for_emotional(self):
        class Lifecycle:
            effective_n_ctx = 16384
            def __init__(self): self.calls = []
            def count_serialized_prompt(self, _):
                return type("Count", (), {"count": 10, "estimated": False})()
            def complete_chat(self, messages, config, **kwargs):
                self.calls.append(kwargs)
                return "ACTION\t1\t大樹の根元へ視線を向ける。"
        lifecycle = Lifecycle()
        backend = _LlamaPlannerBackend(lifecycle)
        for policy in ("anime_emotional_mv", "anime_story_mv"):
            for retry in ("no", "semantic_audit_rejected_slots", "isolated_missing_slot"):
                payload = {"planner_policy_contract": {"policy_id": policy}, "retry": retry,
                           "slots": [{"slot": 1, "required_spatial_anchor": "大樹の根元"}]}
                result = backend.complete_planner(task="actions", system_prompt="system",
                    payload=json.dumps(payload), config=LlamaRuntimeConfig())
                self.assertEqual(result, "ACTION\t1\t大樹の根元へ視線を向ける。")
        self.assertTrue(all("grammar" in c for c in lifecycle.calls[:3]))
        self.assertTrue(all("grammar" not in c for c in lifecycle.calls[3:]))

    def test_best_candidate_keeps_grounding_even_with_more_soft_quality_warnings(self):
        original = {}
        class Backend(FakePlannerBackend):
            def complete_planner(self, *, task, system_prompt, payload, config, interrupt_callback=None):
                request = json.loads(payload)
                if task == "actions":
                    response = super().complete_planner(task=task, system_prompt=system_prompt,
                        payload=payload, config=config, interrupt_callback=interrupt_callback)
                    rows = []
                    for slot, row in zip(request["slots"], response.splitlines()):
                        if slot.get("required_spatial_anchor"):
                            if request.get("retry") == "semantic_audit_rejected_slots":
                                row = f"ACTION\t{slot['slot']}\t視線を向ける。"
                            else:
                                text = slot["required_spatial_anchor"] + "の前で足袋を見て走る。"
                                original[(slot["scene_number"], slot["shot_index"])] = text
                                row = f"ACTION\t{slot['slot']}\t{text}"
                        rows.append(row)
                    return "\n".join(rows)
                return super().complete_planner(task=task, system_prompt=system_prompt,
                    payload=payload, config=config, interrupt_callback=interrupt_callback)
        backend = Backend()
        result = plan_timeline(backend, template_emd=TEMPLATE, concept_emd=CONCEPT,
            direction=DirectionArtifact(camera_profile_id="anime_emotional_mv"),
            lip_sync_mode="off", lip_sync_target="サブジェクト1", lip_sync_audio_slot=1,
            scenes_per_batch=3, system_prompts=prompts(), runtime_config=runtime())
        self.assertTrue(result.complete)
        actions = {(s, k): text for s, k, text in result.content.actions}
        for key, text in original.items():
            self.assertEqual(actions[key], text)
        repairs = [p for t, p in backend.calls if t == "actions"
                   and p.get("retry") == "semantic_audit_rejected_slots"]
        self.assertEqual(len(repairs), 1)


if __name__ == "__main__":
    unittest.main()
