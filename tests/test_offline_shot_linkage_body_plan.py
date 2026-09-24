"""CPU safeguards for the isolated Scene 3-4/9 H3 treatment."""

import json
from pathlib import Path
import unittest

from tools.offline_shot_linkage_body_plan import checked_treatment, replace_plan


TREATMENT = Path("docs/assets/research/shot-linkage-body-2026-09-24/treatment.json")


class ShotLinkageBodyPlanTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.selected = checked_treatment(json.loads(TREATMENT.read_text(encoding="utf-8")))

    def test_reference_generation_does_not_preannounce_target(self):
        for scene, target in ((3, "moss"), (4, "flower"), (9, "foxfire")):
            self.assertNotIn(target, self.selected[scene][0]["action"].lower())
            self.assertIn(target, self.selected[scene][1]["action"].lower())
        self.assertIn("Continue from the prior Scene", self.selected[4][0]["action"])

    def test_only_target_scene_prompts_change(self):
        source = {"defaults": {"steps": 8}, "shots": []}
        for number in range(1, 10):
            source["shots"].append({
                "id": f"scene_{number:04d}", "length": 243,
                "prompt": ["summary:", "[reference generation] old", "detailed_description:",
                           "[Shot 1] old action old camera",
                           "[Shot 2] At 00:04.625, old action old camera"],
            })
        candidate = replace_plan(source, self.selected)
        for number in range(1, 10):
            before = source["shots"][number - 1]
            after = candidate["shots"][number - 1]
            if number in self.selected:
                self.assertNotEqual(before["prompt"], after["prompt"])
                self.assertEqual(before["length"], after["length"])
                self.assertEqual(after["prompt"][1],
                                 "[reference generation] " + self.selected[number][0]["action"])
            else:
                self.assertEqual(before, after)
        self.assertEqual(source["defaults"], candidate["defaults"])


if __name__ == "__main__":
    unittest.main()
