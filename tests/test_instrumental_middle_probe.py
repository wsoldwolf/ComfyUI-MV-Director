import json
import unittest
from copy import deepcopy

from tools.debug_instrumental_middle import rehydrate_payload, verify_plan


class InstrumentalMiddleProbeTests(unittest.TestCase):
    def test_only_saved_state_and_candidate_can_differ(self):
        baseline = {"scene_number": 12, "continuation": True,
                    "previous_scene_state": "元の終端状態", "staging_candidates_optional": ["旧候補"],
                    "slots": [{"slot": 1}], "audio_activity": {"start": 99375}}
        request = deepcopy(baseline)
        request.update(previous_scene_state="", staging_candidates_optional=["新候補"])
        actual = json.loads(rehydrate_payload(json.dumps(request), baseline, ["新候補"]))
        expected = deepcopy(baseline)
        expected["staging_candidates_optional"] = ["新候補"]
        self.assertEqual(actual, expected)
        self.assertEqual(baseline["staging_candidates_optional"], ["旧候補"])
        for field, value in (("slots", []), ("audio_activity", {}),
                             ("previous_scene_state", "改変した状態"), ("continuation", False)):
            wrong = {**request, field: value}
            with self.assertRaises(ValueError):
                rehydrate_payload(json.dumps(wrong), baseline, ["新候補"])

    def test_plan_only_middle_performance_changes(self):
        baseline = {"shots": [{"prompt": ["序盤"], "seed": 1},
                              {"prompt": ["Event Camera OLD"], "seed": 2},
                              {"prompt": ["終盤"], "seed": 3}], "setting": 20}
        changed = deepcopy(baseline)
        changed["shots"][1]["prompt"] = ["Event Camera NEW"]
        verify_plan(baseline, changed, "OLD", "NEW", index=1)
        for bad in ({**changed, "setting": 8},
                    {**changed, "shots": [changed["shots"][0], {**changed["shots"][1], "seed": 9}, changed["shots"][2]]}):
            with self.assertRaises(ValueError):
                verify_plan(baseline, bad, "OLD", "NEW", index=1)
        with self.assertRaises(ValueError):
            verify_plan(baseline, changed, "OLD", "", index=1)


if __name__ == "__main__":
    unittest.main()
