"""Section reading scope and context recovery do not rewrite authored material."""
import json
import unittest

from core.emd.ast import LyricAnnotation, Scene, Shot
from core.planner.template import PlannerTemplate
from core.planner.section_context import section_context_by_scene, reduce_section_context
from core.planner.request_budget import complete_with_context_recovery
from core.inference import ContextBudgetError, LlamaRuntimeConfig


def template(rows):
    scenes = []
    number = 0
    for scene_id, lyrics in enumerate(rows, 1):
        annotations = []
        for label, text in lyrics:
            number += 1
            annotations.append(LyricAnnotation(text, label, number * 10, number * 10 + 9, number))
        scenes.append(Scene(scene_id, (scene_id - 1) * 1000, scene_id * 1000, 22,
                            (), (Shot((scene_id - 1) * 1000, (), tuple(annotations), (), 1),), (), 1))
    return PlannerTemplate(tuple(scenes))


class SectionContextTests(unittest.TestCase):
    def test_section_full_text_across_scenes_and_two_sections_in_one_scene(self):
        source = template([
            [("VERSE", "それでも永遠を")],
            [("VERSE", "口にする"), ("PRE", "命とは")],
            [("PRE", "長さなのか")],
        ])
        contexts = section_context_by_scene(source)
        self.assertEqual([[line["text"] for line in group["lines"]] for group in contexts[2]],
                         [["それでも永遠を", "口にする"], ["命とは", "長さなのか"]])
        self.assertEqual(source.scenes[1].shots[0].lyric_annotations[0].text, "口にする")

    def test_repeated_choruses_and_identical_lines_are_not_merged(self):
        source = template([
            [("CHORUS", "繰り返す"), ("CHORUS", "繰り返す")],
            [("BRIDGE", "変化")],
            [("CHORUS", "繰り返す")],
        ])
        contexts = section_context_by_scene(source)
        self.assertEqual(len(contexts[1][0]["lines"]), 2)
        self.assertEqual(contexts[3][0]["occurrence"], 2)
        self.assertEqual(len(contexts[3][0]["lines"]), 1)

    def test_missing_labels_do_not_invent_whole_song_section(self):
        contexts = section_context_by_scene(template([[(None, "前")], [], [(None, "後")]]))
        self.assertEqual(contexts[2], [])
        self.assertEqual([r["text"] for r in contexts[1][0]["lines"]], ["前"])

    def test_reduction_preserves_current_lyrics_candidates_and_fixed_fields(self):
        source = template([[("VERSE", str(i))] for i in range(9)])
        context = section_context_by_scene(source)[5]
        original = {"scene_number": 5, "section_lyric_context": context,
                    "original_lyrics": [{"text": "4"}], "slots": [{"slot": 1}, {"slot": 2}],
                    "staging_candidates_optional": ["作者候補"], "fixed_performances": {"1": "固定演技"}}
        snapshot = json.dumps(original)
        reduced = reduce_section_context(original)
        self.assertLess(len(reduced["section_lyric_context"][0]["lines"]), 9)
        self.assertIn("4", [r["text"] for r in reduced["section_lyric_context"][0]["lines"]])
        self.assertEqual(json.dumps(original), snapshot)
        while (next_request := reduce_section_context(reduced)) is not None:
            reduced = next_request
        self.assertEqual([r["text"] for r in reduced["section_lyric_context"][0]["lines"]], ["4"])
        self.assertEqual(reduced["staging_candidates_optional"], ["作者候補"])
        self.assertEqual(reduced["fixed_performances"], {"1": "固定演技"})
        self.assertEqual(reduced["original_lyrics"], original["original_lyrics"])

    def test_budget_shrinks_reading_context_before_splitting_scene(self):
        class Backend:
            calls = []
            def complete_planner(self, *, payload, **kwargs):
                request = json.loads(payload)
                self.calls.append(request)
                if len(request["section_lyric_context"][0]["lines"]) > 1:
                    raise ContextBudgetError("test overflow")
                return "PERFORMANCE\t1\t原文一\nPERFORMANCE\t2\t原文二"
        source = template([[("VERSE", "前")], [("VERSE", "今")], [("VERSE", "後")]])
        backend = Backend()
        result = complete_with_context_recovery(
            backend, task="scene-author-performance", system_prompt="",
            payload=json.dumps({"scene_number": 2, "section_lyric_context": section_context_by_scene(source)[2],
                                "slots": [{"slot": 1}, {"slot": 2}]}),
            config=LlamaRuntimeConfig(),
        )
        self.assertEqual(result, "PERFORMANCE\t1\t原文一\nPERFORMANCE\t2\t原文二")
        self.assertTrue(all(len(call["slots"]) == 2 for call in backend.calls))
