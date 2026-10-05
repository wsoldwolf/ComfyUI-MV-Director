import unittest
from copy import deepcopy
from tools.debug_simple_dance import replace_body, ENGLISH, EXPANSIVE_ENGLISH, TORSO_ENGLISH, PIVOT_ENGLISH, GRACEFUL_ENGLISH, CONCRETE_ENGLISH, CONTINUOUS_ENGLISH, TURNING_ENGLISH, HALF_TURN_ENGLISH, MOMENTUM_ENGLISH


class SimpleDanceProbeTests(unittest.TestCase):
    def test_only_body_changes(self):
        before = {"shots": [{"prompt": ["Subject hakama", "Event old body Camera"], "seed": 9}], "prefix": "fixed"}
        saved = deepcopy(before)
        after = replace_body(before, "old body", ENGLISH)
        self.assertEqual(before, saved)
        self.assertEqual(after["shots"][0]["prompt"], ["Subject hakama", f"Event {ENGLISH} Camera"])
        self.assertEqual(after["shots"][0]["seed"], 9)
        self.assertEqual(after["prefix"], "fixed")

    def test_missing_or_duplicate_body_rejected(self):
        for prompt in (["missing"], ["body body"], ["body", "body"]):
            with self.assertRaises(ValueError):
                replace_body({"shots": [{"prompt": prompt}]}, "body", ENGLISH)

    def test_full_song_not_rendered_by_accident(self):
        with self.assertRaises(ValueError):
            replace_body({"shots": [{"prompt": ["body"]}, {"prompt": ["body"]}]}, "body", ENGLISH)

    def test_expansive_variant_preserves_event_camera_and_identity(self):
        original = {"shots": [{"prompt": ["Subject hakama", f"Event {ENGLISH} Camera"], "seed": 20261014}]}
        updated = replace_body(original, ENGLISH, EXPANSIVE_ENGLISH)
        self.assertEqual(updated["shots"][0]["prompt"], ["Subject hakama", f"Event {EXPANSIVE_ENGLISH} Camera"])
        self.assertEqual(updated["shots"][0]["seed"], 20261014)

    def test_torso_variant_changes_only_expansive_performance(self):
        original = {"shots": [{"prompt": ["Subject hakama", f"Event {EXPANSIVE_ENGLISH} Camera"], "seed": 20261014}]}
        saved = deepcopy(original)
        updated = replace_body(original, EXPANSIVE_ENGLISH, TORSO_ENGLISH)
        self.assertEqual(original, saved)
        self.assertEqual(updated["shots"][0]["prompt"], ["Subject hakama", f"Event {TORSO_ENGLISH} Camera"])
        self.assertEqual(updated["shots"][0]["seed"], 20261014)

    def test_pivot_variant_preserves_torso_baseline_settings(self):
        original = {"shots": [{"prompt": ["Subject hakama", f"Event {TORSO_ENGLISH} Camera"], "seed": 20261014}]}
        saved = deepcopy(original)
        updated = replace_body(original, TORSO_ENGLISH, PIVOT_ENGLISH)
        self.assertEqual(original, saved)
        self.assertEqual(updated["shots"][0]["prompt"], ["Subject hakama", f"Event {PIVOT_ENGLISH} Camera"])
        self.assertEqual(updated["shots"][0]["seed"], 20261014)

    def test_graceful_variant_preserves_pivot_baseline_settings(self):
        original = {"shots": [{"prompt": ["Subject hakama", f"Event {PIVOT_ENGLISH} Camera"], "seed": 20261014}]}
        saved = deepcopy(original)
        updated = replace_body(original, PIVOT_ENGLISH, GRACEFUL_ENGLISH)
        self.assertEqual(original, saved)
        self.assertEqual(updated["shots"][0]["prompt"], ["Subject hakama", f"Event {GRACEFUL_ENGLISH} Camera"])
        self.assertEqual(updated["shots"][0]["seed"], 20261014)

    def test_concrete_turn_changes_only_graceful_performance(self):
        original = {"shots": [{"prompt": ["Subject hakama", f"Event {GRACEFUL_ENGLISH} Camera"], "seed": 20261014}]}
        saved = deepcopy(original)
        updated = replace_body(original, GRACEFUL_ENGLISH, CONCRETE_ENGLISH)
        self.assertEqual(original, saved)
        self.assertEqual(updated["shots"][0]["prompt"], ["Subject hakama", f"Event {CONCRETE_ENGLISH} Camera"])
        self.assertEqual(updated["shots"][0]["seed"], 20261014)


    def test_continuous_variant_preserves_concrete_baseline_settings(self):
        original = {"shots": [{"prompt": ["Subject hakama", f"Event {CONCRETE_ENGLISH} Camera"], "seed": 20261014}]}
        saved = deepcopy(original)
        updated = replace_body(original, CONCRETE_ENGLISH, CONTINUOUS_ENGLISH)
        self.assertEqual(original, saved)
        self.assertEqual(updated["shots"][0]["prompt"], ["Subject hakama", f"Event {CONTINUOUS_ENGLISH} Camera"])
        self.assertEqual(updated["shots"][0]["seed"], 20261014)


    def test_turning_variant_preserves_continuous_baseline_settings(self):
        original = {"shots": [{"prompt": ["Subject hakama", f"Event {CONTINUOUS_ENGLISH} Camera"], "seed": 20261014}]}
        saved = deepcopy(original)
        updated = replace_body(original, CONTINUOUS_ENGLISH, TURNING_ENGLISH)
        self.assertEqual(original, saved)
        self.assertEqual(updated["shots"][0]["prompt"], ["Subject hakama", f"Event {TURNING_ENGLISH} Camera"])
        self.assertEqual(updated["shots"][0]["seed"], 20261014)


    def test_half_turn_variant_preserves_continuous_baseline_settings(self):
        original = {"shots": [{"prompt": ["Subject hakama", f"Event {CONTINUOUS_ENGLISH} Camera"], "seed": 20261014}]}
        saved = deepcopy(original)
        updated = replace_body(original, CONTINUOUS_ENGLISH, HALF_TURN_ENGLISH)
        self.assertEqual(original, saved)
        self.assertEqual(updated["shots"][0]["prompt"], ["Subject hakama", f"Event {HALF_TURN_ENGLISH} Camera"])
        self.assertEqual(updated["shots"][0]["seed"], 20261014)


    def test_momentum_variant_preserves_half_turn_baseline_settings(self):
        original = {"shots": [{"prompt": ["Subject hakama", f"Event {HALF_TURN_ENGLISH} Camera"], "seed": 20261014}]}
        saved = deepcopy(original)
        updated = replace_body(original, HALF_TURN_ENGLISH, MOMENTUM_ENGLISH)
        self.assertEqual(original, saved)
        self.assertEqual(updated["shots"][0]["prompt"], ["Subject hakama", f"Event {MOMENTUM_ENGLISH} Camera"])
        self.assertEqual(updated["shots"][0]["seed"], 20261014)


if __name__ == "__main__":
    unittest.main()
