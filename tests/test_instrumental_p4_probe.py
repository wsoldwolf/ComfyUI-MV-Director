"""CPU contracts for the opt-in, single-performance research probe."""
import copy
import unittest
from tools.debug_instrumental_p4 import verify_body_only_plan


class InstrumentalProbeTests(unittest.TestCase):
    def setUp(self):
        self.saved = {"prompt_prefix": "global", "shots": [
            {"seed": 1, "prompt": ["prefix"]},
            {"seed": 2, "prompt": ["summary: old", "Shot 1 old camera", "Shot 2 singing"]},
        ]}
        self.candidate = copy.deepcopy(self.saved)
        self.candidate["shots"][1]["prompt"][:2] = ["summary: new", "Shot 1 new camera"]

    def test_body_only_and_candidate_not_mutated(self):
        snapshot = copy.deepcopy(self.candidate)
        verify_body_only_plan(self.saved, self.candidate, 2, "old", "new")
        self.assertEqual(self.candidate, snapshot)

    def test_protected_changes_rejected(self):
        for mutate in (
            lambda plan: plan.update(prompt_prefix="other"),
            lambda plan: plan["shots"][0].update(seed=9),
            lambda plan: plan["shots"][1].update(seed=9),
            lambda plan: plan["shots"][1]["prompt"].append("new Camera"),
            lambda plan: plan["shots"][1]["prompt"].__setitem__(2, "different singing"),
        ):
            with self.subTest(mutate=mutate):
                candidate = copy.deepcopy(self.candidate)
                mutate(candidate)
                with self.assertRaises(ValueError):
                    verify_body_only_plan(self.saved, candidate, 2, "old", "new")


if __name__ == "__main__":
    unittest.main()
