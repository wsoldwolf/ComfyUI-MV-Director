"""Transport/ownership tests, not semantic prop plausibility scoring."""
from copy import deepcopy
import json
import unittest

from core.inference import LlamaRuntimeConfig
from core.planner.prop_decision import (build_prop_decision_grammar, parse_prop_decisions,
                                        request_prop_decisions)
from tools.debug_prop_decision import (reopen_cameras, replace_selected_cameras, run_probe)
from tools.debug_prop_performance import prepare_inputs, replace_primary_performances
SOURCE = (
    "# サブジェクト\n* `画像1` 刀と盾を持つ歌手。\n"
    "> `シーン` 1\n# シーン 00:00.000 --> 00:10.125\n* `H3長` 243\n"
    "## ショット 00:00.000\n* `演技` 右手の刀を引き寄せる。\n* `カメラ` 正面。\n"
    "## ショット 00:05.000\n* `演出` 葉が舞う。\n* `演技` 遠くを見る。\n* `カメラ` 横から追う。\n"
    "> `シーン` 2\n# シーン 00:10.125 --> 00:11.833 継続\n* `H3長` 56\n"
    "## ショット 00:10.125\n* `演技` 右手を前に伸ばす。\n"
    "* `演技` 支持足から横へ一歩進む。\n* `カメラ` 上半身。\n"
)

DECISION = {"prop_locations": "刀は右手、盾は左手。",
            "right_hand": "刀を握る。", "left_hand": "盾を保持。",
            "transition": "なし", "performance_scope": "刀を握り肘を曲げる。",
            "end_state": "右手に刀、左手に盾。"}


def record(slot, decision=None):
    return f"PROP_DECISION\t{slot}\t" + json.dumps(decision or DECISION, ensure_ascii=False)


class PropDecisionTests(unittest.TestCase):
    def test_slot_mapping_and_strings_are_preserved(self):
        result = parse_prop_decisions(record(1) + "\n" + record(2), (3, 7))
        self.assertEqual(result, {3: DECISION, 7: DECISION})

    def test_partial_duplicates_and_invalid_schema_are_rejected(self):
        for response in (record(1), record(1) + "\n" + record(1),
                         record(1, {**DECISION, "extra": "なし"}) + "\n" + record(2),
                         record(1, {**DECISION, "transition": None}) + "\n" + record(2),
                         record(1, {**DECISION, "transition": "\n"}) + "\n" + record(2),
                         'PROP_DECISION\t1\t{"right_hand":"刀","right_hand":"なし"}'):
            with self.subTest(response=response):
                self.assertIsNone(parse_prop_decisions(response, (3, 7)))

    def test_semantic_text_is_not_repaired_or_certified(self):
        contradictory = {**DECISION, "performance_scope": "握った刀を持ったまま掌を開く。"}
        self.assertEqual(parse_prop_decisions(record(1, contradictory), (1,))[1], contradictory)

    def test_structured_inventory_is_preserved_without_flattening(self):
        props = {"日本刀": "右手", "白い盾": "不明"}
        structured = {**DECISION, "prop_locations": props, "end_state": props}
        self.assertEqual(parse_prop_decisions(record(1, structured), (1,)), {1: structured})
        omitted = {**structured, "end_state": {"日本刀": "右手"}}
        self.assertIsNone(parse_prop_decisions(record(1, omitted), (1,)))
        nested = {**structured, "prop_locations": {"日本刀": {"state": "右手"}}}
        self.assertIsNone(parse_prop_decisions(record(1, nested), (1,)))

    def test_bounded_retry_preserves_inputs_and_returns_no_partial_authority(self):
        shared = {"scene_number": 1, "shot_positions": [{"shot": 1}],
                  "fixed_performances": {"1": "刀を保持し続ける。"}}
        before = deepcopy(shared)
        class Backend:
            calls = []
            def complete_planner(self, **kwargs):
                self.calls.append(json.loads(kwargs["payload"]))
                return "invalid"
        backend = Backend()
        result = request_prop_decisions(backend, shared=shared, system_prompt="test",
                                        runtime_config=LlamaRuntimeConfig())
        self.assertEqual(result.status, "invalid_transport")
        self.assertEqual(result.decisions, {})
        self.assertEqual(result.attempts, 2)
        self.assertEqual(len(backend.calls), 2)
        self.assertEqual(shared, before)
        self.assertEqual(backend.calls[1]["fixed_performances"], shared["fixed_performances"])

    def test_valid_second_attempt_and_interrupt(self):
        calls, interruptions = [], []
        class Backend:
            def complete_planner(self, **kwargs):
                calls.append(kwargs)
                return "invalid" if len(calls) == 1 else record(1)
        result = request_prop_decisions(Backend(), shared={"scene_number": 1,
            "shot_positions": [{"shot": 9}]}, system_prompt="test",
            runtime_config=LlamaRuntimeConfig(), interrupt_callback=lambda: interruptions.append(1))
        self.assertEqual(result.decisions, {9: DECISION})
        self.assertEqual(len(interruptions), 2)

    def test_grammar_has_only_requested_slots(self):
        grammar = build_prop_decision_grammar([{"slot": 2}, {"slot": 4}])
        self.assertIn('PROP_DECISION\\t2\\t', grammar)
        self.assertIn('PROP_DECISION\\t4\\t', grammar)
        for slots in ([], [{"slot": True}], [{"slot": 1}, {"slot": 1}]):
            with self.assertRaises(ValueError):
                build_prop_decision_grammar(slots)

    def test_only_selected_cameras_reopen_and_emd_assignments_preserve_rest(self):
        requests = prepare_inputs(SOURCE, [1, 2])
        original = deepcopy(requests[0]["shared"])
        reopened = reopen_cameras(original, {2})
        self.assertEqual(reopened["shot_positions"][0]["fixed_camera"], "正面。")
        self.assertEqual(reopened["shot_positions"][1]["fixed_camera"], "")
        self.assertEqual(requests[0]["shared"], original)
        emd = replace_primary_performances(SOURCE, {(1, 2): "刀を握り胸を開く。"})
        updated = replace_selected_cameras(emd, {(1, 2): "握る手と胸郭を追う。"})
        self.assertIn("* `演技` 右手の刀を引き寄せる。", updated)
        self.assertIn("* `カメラ` 正面。", updated)
        self.assertIn("* `演技` 支持足から横へ一歩進む。", updated)
        self.assertIn("* `カメラ` 上半身。", updated)
        with self.assertRaises(ValueError):
            replace_selected_cameras(emd, {(3, 1): "正面。"})

    def test_decision_performance_camera_sequence_and_state_reset(self):
        requests = prepare_inputs(SOURCE, [1, 2])
        original = deepcopy(requests)
        class Backend:
            def __init__(self):
                self.calls = []
            def complete_planner(self, *, task, payload, **kwargs):
                p = json.loads(payload)
                self.calls.append((task, p))
                if task == "scene-author-prop-decision":
                    return "\n".join(record(s["slot"]) for s in p["slots"])
                kind = "PERFORMANCE" if task == "scene-author-performance" else "CAMERA"
                return "\n".join(f"{kind}\t{s['slot']}\t決定に沿う。｜END_STATE=右手に刀、左手に盾。"
                                 for s in p["slots"])
        backend = Backend()
        rows, actions, cameras = run_probe(backend, requests,
            {"decision": "d", "performance": "p", "camera": "c"}, LlamaRuntimeConfig(),
            camera_policy="reopen_selected")
        self.assertEqual(len(backend.calls), 6)
        self.assertEqual([t for t, _ in backend.calls[:3]],
                         ["scene-author-prop-decision", "scene-author-performance", "scene-author-camera"])
        self.assertEqual(backend.calls[3][1]["previous_prop_state"], DECISION["end_state"])
        self.assertEqual(backend.calls[1][1]["accepted_prop_decisions"]["2"], DECISION)
        for task, request in backend.calls:
            if task in {"scene-author-performance", "scene-author-camera"}:
                self.assertTrue(all(slot["position"]["fixed_camera"] == ""
                                    for slot in request["slots"]))
                for slot in request["slots"]:
                    position = next(p for p in request["shot_positions"] if p["shot"] == slot["shot"])
                    self.assertEqual(slot["position"], position)
        self.assertIn("支持足から横へ一歩進む。", backend.calls[5][1]["accepted_performances"]["1"])
        self.assertEqual(set(actions), {(1, 2), (2, 1)})
        self.assertEqual(set(cameras), set(actions))
        self.assertEqual(requests, original)
        requests[1]["shared"]["continuation"] = False
        backend = Backend()
        run_probe(backend, requests, {"decision": "d", "performance": "p", "camera": "c"},
                  LlamaRuntimeConfig(), camera_policy="fixed")
        self.assertEqual(len(backend.calls), 4)
        self.assertEqual(backend.calls[2][1]["previous_prop_state"], "")
        self.assertEqual(backend.calls[2][1]["previous_scene_state"], "")

    def test_invalid_decision_does_not_stall_performance_or_fabricate_state(self):
        requests = prepare_inputs(SOURCE, [1])
        class Backend:
            def __init__(self):
                self.calls = []
            def complete_planner(self, *, task, payload, **kwargs):
                p = json.loads(payload)
                self.calls.append((task, p))
                if task == "scene-author-prop-decision":
                    return "invalid"
                return "\n".join(f"PERFORMANCE\t{s['slot']}\t元の演技。｜END_STATE=右手に刀。"
                                 for s in p["slots"])
        backend = Backend()
        rows, actions, cameras = run_probe(backend, requests,
            {"decision": "d", "performance": "p", "camera": "c"}, LlamaRuntimeConfig(),
            camera_policy="fixed")
        self.assertEqual(len(backend.calls), 3)
        self.assertEqual(rows[0]["decision_status"], "invalid_transport")
        self.assertEqual(rows[0]["decisions"], {})
        self.assertEqual(backend.calls[-1][1]["accepted_prop_decisions"], {})
        self.assertEqual(actions, {(1, 2): "元の演技。"})
        self.assertEqual(cameras, {})


if __name__ == "__main__":
    unittest.main()
