"""Inventory transport/coverage tests, not semantic object recognition gates."""
from copy import deepcopy
import json
import unittest

from core.inference import LlamaRuntimeConfig
from core.planner.prop_inventory import (parse_prop_inventory, request_prop_inventory,
                                         build_prop_inventory_grammar)
from core.planner.prop_decision import parse_prop_decisions, request_prop_decisions
from tools.debug_prop_decision import run_probe
from tools.debug_prop_performance import prepare_inputs


PROPS = [
    {"id": "P1", "subject": "人物1", "label": "道具A", "evidence": "道具A",
     "initial_state": "右手で保持"},
    {"id": "P2", "subject": "人物1", "label": "道具B", "evidence": "道具B",
     "initial_state": "所在未確定"},
]
DECISION = {"prop_locations": {"P1": "右手の道具A", "P2": "左手の道具B"},
            "right_hand": "道具Aを握る", "left_hand": "道具Bを握る", "transition": "なし",
            "performance_scope": "体幹を向ける", "end_state": {"P1": "右手の道具A", "P2": "左手の道具B"}}


def inventory_record(props):
    return "PROP_INVENTORY\t1\t" + json.dumps({"props": props}, ensure_ascii=False)


def decision_record(value):
    return "PROP_DECISION\t1\t" + json.dumps(value, ensure_ascii=False)


class PropInventoryTests(unittest.TestCase):
    def test_valid_inventory_and_empty_inventory_are_distinct_from_failure(self):
        self.assertEqual(parse_prop_inventory(inventory_record(PROPS)), tuple(PROPS))
        self.assertEqual(parse_prop_inventory(inventory_record([])), ())
        self.assertIsNone(parse_prop_inventory("invalid"))

    def test_malformed_duplicate_and_unknown_fields_rejected(self):
        values = [PROPS + [PROPS[0]], [{**PROPS[0], "extra": "new"}],
                  [{**PROPS[0], "id": "generic_word"}], [{**PROPS[0], "initial_state": None}],
                  [{**PROPS[0], "evidence": ""}], [{**PROPS[0], "label": "A\nB"}]]
        for props in values:
            self.assertIsNone(parse_prop_inventory(inventory_record(props)))
        self.assertIsNone(parse_prop_inventory(inventory_record(PROPS) + "\n" + inventory_record(PROPS)))
        self.assertIsNone(parse_prop_inventory('PROP_INVENTORY\t1\t{"props":[],"props":[]}'))

    def test_no_semantic_truth_or_noun_dictionary_is_inferred(self):
        props = [{**PROPS[0], "label": "未知の器具", "initial_state": "空中に浮く"}]
        self.assertEqual(parse_prop_inventory(inventory_record(props)), tuple(props))

    def test_inventory_retry_is_bounded_and_boundary_is_preserved(self):
        boundary = {"1": "右手で道具Aを保持する。"}
        before = deepcopy(boundary)
        calls = []
        class Backend:
            def complete_planner(self, **kwargs):
                calls.append(json.loads(kwargs["payload"]))
                return "invalid"
        result = request_prop_inventory(Backend(), subject_emd="道具Aと道具B", fixed_boundary=boundary,
            scene_number=15, system_prompt="test", runtime_config=LlamaRuntimeConfig())
        self.assertEqual((result.status, result.attempts, result.props), ("invalid_transport", 2, ()))
        self.assertEqual(boundary, before)
        self.assertEqual(calls[1]["fixed_boundary_performances"], boundary)
        self.assertIn("PROP_INVENTORY\\t1\\t", build_prop_inventory_grammar())

    def test_valid_second_inventory_attempt_preserves_all_fields(self):
        calls = []
        class Backend:
            def complete_planner(self, **kwargs):
                calls.append(kwargs)
                return "invalid" if len(calls) == 1 else inventory_record(PROPS)
        result = request_prop_inventory(Backend(), subject_emd="道具Aと道具B", fixed_boundary={},
            scene_number=15, system_prompt="test", runtime_config=LlamaRuntimeConfig())
        self.assertEqual(result.props, tuple(PROPS))
        self.assertEqual((result.status, result.attempts), ("transport_valid", 2))

    def test_each_shot_requires_exact_inventory_ids_in_both_maps(self):
        ids = frozenset({"P1", "P2"})
        self.assertEqual(parse_prop_decisions(decision_record(DECISION), (3,), prop_ids=ids), {3: DECISION})
        for field in ("prop_locations", "end_state"):
            for mapping in ({"P1": "right"}, {**DECISION[field], "P3": "new"}, "A and B"):
                self.assertIsNone(parse_prop_decisions(decision_record({**DECISION, field: mapping}), (3,), prop_ids=ids))

    def test_omitted_prop_retries_without_silent_reconstruction(self):
        incomplete = {**DECISION, "prop_locations": {"P1": "right"}, "end_state": {"P1": "right"}}
        calls = []
        class Backend:
            def complete_planner(self, **kwargs):
                calls.append(json.loads(kwargs["payload"]))
                return decision_record(incomplete if len(calls) == 1 else DECISION)
        shared = {"scene_number": 1, "shot_positions": [{"shot": 3}], "prop_inventory": PROPS}
        before = deepcopy(shared)
        result = request_prop_decisions(Backend(), shared=shared, system_prompt="test", runtime_config=LlamaRuntimeConfig())
        self.assertEqual(result.decisions, {3: DECISION})
        self.assertEqual(result.attempts, 2)
        self.assertEqual(calls[1]["required_prop_ids_in_each_shot"], ["P1", "P2"])
        self.assertEqual(shared, before)

    def test_same_inventory_reaches_decision_performance_camera(self):
        source = ("# サブジェクト\n* `画像1` 道具Aと道具Bを持つ人物。\n"
                  "> `シーン` 1\n# シーン 00:00.000 --> 00:10.125\n* `H3長` 243\n"
                  "## ショット 00:00.000\n* `演技` 道具Aを握る。\n* `カメラ` 正面。\n"
                  "## ショット 00:05.000\n* `演技` 胸を向ける。\n* `カメラ` 横から追う。\n")
        calls = []
        class Backend:
            def complete_planner(self, *, task, payload, **kwargs):
                req = json.loads(payload)
                calls.append(req)
                if task == "scene-author-prop-decision":
                    return "\n".join(f"PROP_DECISION\t{s['slot']}\t{json.dumps(DECISION)}" for s in req["slots"])
                kind = "PERFORMANCE" if task == "scene-author-performance" else "CAMERA"
                return f"{kind}\t1\t道具Aと道具Bを保持して胸を向ける。｜END_STATE=両方を保持。"
        before = deepcopy(PROPS)
        run_probe(Backend(), prepare_inputs(source, [1]), {"decision": "d", "performance": "p", "camera": "c"},
                  LlamaRuntimeConfig(), camera_policy="reopen_selected", inventory=PROPS)
        self.assertEqual(len(calls), 3)
        self.assertTrue(all(c["prop_inventory"] == PROPS for c in calls))
        self.assertEqual(PROPS, before)


if __name__ == "__main__":
    unittest.main()
