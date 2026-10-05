from dataclasses import replace
import unittest

from core.emd import parse_emd
from core.emd.audio_activity import AudioActivity, ActivityRange, ReferenceCopy
from core.lyrics import build_timeline, render_template_emd
from core.h3_contract import DEFAULT_H3_TIMING_PROFILE
from core.artifacts import DirectionArtifact
from core.planner import plan_timeline
from core.compiler import compile_ref2va
from nodes.node_timeline_planner.node import _system_prompts
from scene_author_fixtures import Backend, CONCEPT, TEMPLATE, _runtime


def activity():
    return AudioActivity(1000, 6000, "a" * 64, (
        ActivityRange(0, 2500, "no_vocal_candidate"),
        ActivityRange(2500, 4000, "vocal_candidate"),
        ActivityRange(4000, 6000, "no_vocal_candidate"),
    ), (ReferenceCopy(0, 3000, 0), ReferenceCopy(3000, 6000, 3200)))


class EMDAudioActivityTests(unittest.TestCase):
    def test_sample_metadata_roundtrip_without_frame_changes(self):
        timeline = build_timeline((), (), source_audio_duration_ms=6000,
                                  max_scene_duration_ms=10000, timing_profile=DEFAULT_H3_TIMING_PROFILE)
        old = render_template_emd(timeline)
        new = render_template_emd(timeline, audio_activity=activity())
        self.assertEqual(old.schema, "MVD_EMD_TEMPLATE_V1")
        self.assertEqual(new.schema, "MVD_EMD_TEMPLATE_V2")
        document = parse_emd(CONCEPT + new.text)
        self.assertEqual(new.text.split("> `シーン`", 1)[1], old.text.split("> `シーン`", 1)[1])
        self.assertEqual(document.audio_activity, activity())

    def test_reference_clock_splits_voice_and_does_not_shift_by_scene(self):
        payload = activity().scene_payload(start_ms=2800, end_ms=4500, audio_mode="audio_reference")
        self.assertEqual(payload["timebase"], "aligned_reference_pcm")
        self.assertEqual([(i["local_start_ms"], i["local_end_ms"], i["state"])
                          for i in payload["intervals"]], [
            (0, 200, "vocal_candidate"), (200, 400, "padding"),
            (400, 1400, "vocal_candidate"), (1400, 1700, "no_vocal_candidate")])
        payload = activity().scene_payload(start_ms=0, end_ms=2000, audio_mode="context_loop")
        self.assertEqual(payload["song_position"], "intro")
        self.assertEqual(payload["next_vocal_start_ms"], 2500)

    def test_padding_unknown_and_unmapped_are_not_automatic_scene_commands(self):
        no_map = replace(activity(), reference_copies=())
        self.assertEqual(no_map.scene_payload(start_ms=0, end_ms=1000,
                                              audio_mode="audio_reference")["intervals"], [])
        payload = activity().scene_payload(start_ms=5500, end_ms=6500, audio_mode="context_loop")
        self.assertEqual([i["state"] for i in payload["intervals"]], ["no_vocal_candidate", "padding"])
        self.assertEqual(payload["previous_vocal_end_ms"], 4000)

    def test_invalid_source_or_mapping_rejected(self):
        for value in (replace(activity(), intervals=(ActivityRange(1, 6000, "unknown"),)),
                      replace(activity(), reference_copies=(ReferenceCopy(0, 6001, 0),)),
                      replace(activity(), reference_copies=(ReferenceCopy(0, 3000, 0), ReferenceCopy(3000, 6000, 2000)))):
            with self.assertRaises(ValueError):
                value.validate()

    def test_advisory_reaches_all_stages_fixed_fields_preserved(self):
        template = "\n".join(activity().render_lines()) + "\n\n" + TEMPLATE
        backend = Backend()
        result = plan_timeline(backend, template_emd=template, concept_emd=CONCEPT,
            direction=DirectionArtifact(motion_profile_id="anime_scene_author_mv"),
            lip_sync_mode="context_loop", lip_sync_target="サブジェクト1", lip_sync_audio_slot=1,
            system_prompts=_system_prompts(), runtime_config=_runtime())
        self.assertTrue(result.complete)
        self.assertEqual(result.emd.schema, "MVD_EMD_V3")
        for _, payload in backend.calls:
            self.assertTrue(payload["audio_activity"]["advisory"])
            self.assertNotIn("audio_sha256", payload["audio_activity"])
        document = parse_emd(result.emd.text)
        self.assertEqual(document.audio_activity, activity())
        self.assertIn("`演技` 人物が片手を胸元に置く。", result.emd.text)

    def test_compiler_preserves_diagnostics_without_prompt_or_audio_changes(self):
        class Translator:
            def __init__(self):
                self.units = []
            def translate(self, units):
                self.units.extend(units)
                return tuple("EN:" + unit for unit in units)
        source = CONCEPT + TEMPLATE.replace("未計画", "人物が歌う。")
        augmented = source.replace("> `シーン` 1", "\n".join(activity().render_lines()) + "\n> `シーン` 1")
        translator = Translator()
        plain = compile_ref2va(source, Translator())
        added = compile_ref2va(augmented, translator)
        self.assertEqual(added.plan["shots"], plain.plan["shots"])
        self.assertEqual(added.plan["mv_director_audio_activity"], activity().to_dict())
        self.assertNotIn("vocal_candidate", " ".join(translator.units))

    def test_silent_scene_reads_small_neighbor_excerpt_not_invented_lyrics(self):
        from core.planner.section_context import section_context_by_scene
        from core.planner.template import PlannerTemplate
        from core.emd.ast import LyricAnnotation, Scene, Shot
        scenes = (
            Scene(1, 0, 1000, 22, (), (Shot(0, (), (), (), 1),), (), 1),
            Scene(2, 1000, 2000, 22, (), (Shot(1000, (), tuple(
                LyricAnnotation(str(i), "VERSE", 1000+i, 1001+i, i+1) for i in range(9)), (), 1),), (), 1),
        )
        context = section_context_by_scene(PlannerTemplate(scenes, activity()))[1]
        self.assertEqual(len(context[0]["lines"]), 4)
        self.assertEqual(context[0]["role"], "following_lyrics")
        self.assertTrue(context[0]["reading_only"])
        self.assertEqual(scenes[0].shots[0].lyric_annotations, ())
        self.assertEqual(section_context_by_scene(PlannerTemplate(scenes))[1], [])


if __name__ == "__main__":
    unittest.main()
