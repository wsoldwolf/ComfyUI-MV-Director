import unittest

from tools.offline_prototype_blueprint import scene_payload, summarize


class PrototypeBlueprintProbeTests(unittest.TestCase):
    def test_payload_keeps_lyrics_but_excludes_old_action(self):
        payload = scene_payload({
            "scene_id": 3, "duration_ms": 9208,
            "lyrics": ["苔へと還る"],
            "original_action": "これはモデルに渡さない",
        })
        self.assertEqual(payload["scenes"][0]["lyric_lines"][0]["text"], "苔へと還る")
        self.assertNotIn("これはモデルに渡さない", str(payload))

    def test_summary_counts_action_lines(self):
        result = summarize("ACTION\t1\t接近\nACTION\t2\t触れる\nVISIBLE_RESULT\t変化")
        self.assertEqual(result["actions"], [(1, "接近"), (2, "触れる")])
        self.assertFalse(result["has_required_records"])


if __name__ == "__main__":
    unittest.main()
