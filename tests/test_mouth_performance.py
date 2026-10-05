"""CPU tests of Planner-owned mouth intentions and literal compilation."""

from dataclasses import replace
import unittest

from core.artifacts import DirectionArtifact, EMDTextArtifact
from core.compiler import IdentityTranslator, compile_ref2va
from core.emd import MouthPerformance, Scene, Shot, ShotDirective, parse_emd
from core.emd.audio_activity import AudioActivity, ActivityRange, ReferenceCopy
from core.emd.errors import EMDParseError
from core.h3_contract import DEFAULT_H3_TIMING_PROFILE
from core.planner import PlannerContent, plan_timeline
from core.planner.errors import TimelinePlannerError
from core.planner.mouth_performance import plan_mouth_performances
from core.planner.template import PlannerTemplate, parse_template_emd
from nodes.node_timeline_planner.node import _system_prompts
from scene_author_fixtures import Backend, CONCEPT, _runtime


TEMPLATE = """> `シーン` 1
# シーン 00:00.000 --> 00:06.000
* `H3長` 158
## ショット 00:00.000
* 未計画
## ショット 00:03.500
* 未計画
"""
AUTHOR_TEMPLATE = TEMPLATE.replace("## ショット 00:00.000", """> `口元` `サブジェクト1` 00:00.000 --> 00:03.000 `閉口`
> `口元` `サブジェクト1` 00:03.000 --> 00:06.000 `歌唱`
## ショット 00:00.000""")


def activity(*ranges, copies=(), samples=6000):
    return AudioActivity(1000, samples, "a" * 64,
                         tuple(ActivityRange(*row) for row in ranges), copies)


def resolve(value, *, scenes=None, mode="context_loop", target="サブジェクト1", subjects=1):
    if scenes is None:
        scenes = parse_template_emd(TEMPLATE).scenes
    return plan_mouth_performances(PlannerTemplate(scenes, value),
        lip_sync_mode=mode, lip_sync_target=target, subject_count=subjects)


def rows(items):
    return [(i.target_concept_id, i.start_ms, i.end_ms, i.state) for i in items]


class MouthPlannerPolicyTests(unittest.TestCase):
    def test_pure_instrumental_closes_without_changing_shots(self):
        scene = parse_template_emd(TEMPLATE).scenes[0]
        result = resolve(activity((0, 6000, "instrumental_candidate")))
        self.assertEqual(rows(result[1]), [("サブジェクト1", 0, 6000, "閉口")])
        self.assertEqual([s.start_ms for s in scene.shots], [0, 3500])

    def test_mixed_interval_uses_pcm_not_shot_and_preserves_margin(self):
        result = resolve(activity((0, 3000, "no_vocal_candidate"), (3000, 6000, "vocal_candidate")))
        self.assertEqual(rows(result[1]), [
            ("サブジェクト1", 0, 2800, "閉口"), ("サブジェクト1", 3000, 6000, "歌唱")])

    def test_scene_split_does_not_reduce_long_gap_to_breath(self):
        scenes = tuple(Scene(i + 1, i * 1000, (i + 1) * 1000, 22, (),
                             (Shot(i * 1000, ("未計画",), (), (), 1),), (), 1)
                       for i in range(6))
        result = resolve(activity((0, 6000, "instrumental_candidate")), scenes=scenes)
        self.assertEqual(len(result), 6)
        self.assertTrue(all(i[0].state == "閉口" for i in result.values()))

    def test_short_gaps_unknown_and_tail_padding_are_not_closed(self):
        value = activity((0, 1000, "no_vocal_candidate"), (1000, 2000, "unknown"),
                         (2000, 4000, "vocal_candidate"), (4000, 5000, "no_vocal_candidate"), samples=5000)
        self.assertEqual(rows(resolve(value)[1]), [("サブジェクト1", 2000, 4000, "歌唱")])

    def test_no_activity_off_and_unmapped_keep_authored_only(self):
        value = activity((0, 6000, "no_vocal_candidate"))
        for candidate, mode in ((None, "context_loop"), (value, "off"), (value, "audio_reference")):
            self.assertEqual(resolve(candidate, mode=mode)[1], ())

    def test_reference_mapping_uses_destination_clock_and_skips_padding(self):
        value = activity((0, 3000, "no_vocal_candidate"), (3000, 6000, "vocal_candidate"),
                         copies=(ReferenceCopy(0, 3000, 0), ReferenceCopy(3000, 6000, 3200)))
        self.assertEqual(rows(resolve(value, mode="audio_reference")[1]), [
            ("サブジェクト1", 0, 3000, "閉口"), ("サブジェクト1", 3200, 6000, "歌唱")])

    def test_fixed_performance_and_plain_body_block_automatic_policy(self):
        scene = parse_template_emd(TEMPLATE).scenes[0]
        for first in (replace(scene.shots[0], body=("作者の呼吸。",)),
                      replace(scene.shots[0], body=("`演技` 作者の呼吸。",),
                              directives=(ShotDirective("演技", "作者の呼吸。", 1),))):
            with self.subTest(first=first):
                result = resolve(activity((0, 6000, "no_vocal_candidate")),
                                 scenes=(replace(scene, shots=(first, scene.shots[1])),))
                self.assertEqual(rows(result[1]), [("サブジェクト1", 3500, 6000, "閉口")])

    def test_fixed_camera_does_not_block_automatic_policy(self):
        scene = parse_template_emd(TEMPLATE).scenes[0]
        fixed = replace(scene.shots[0], body=("`カメラ` Arc Shot.",),
                        directives=(ShotDirective("カメラ", "Arc Shot.", 1),))
        result = resolve(activity((0, 6000, "no_vocal_candidate")),
                         scenes=(replace(scene, shots=(fixed, scene.shots[1])),))
        self.assertTrue(result[1])
        self.assertEqual(sum(i.end_ms-i.start_ms for i in result[1]), 6000)

    def test_author_free_overrides_automatic_closure_only_for_its_target(self):
        scene = parse_template_emd(TEMPLATE).scenes[0]
        author = MouthPerformance("サブジェクト1", 1000, 2000, "自由", 5)
        result = resolve(activity((0, 6000, "no_vocal_candidate")),
                         scenes=(replace(scene, mouth_performances=(author,)),))
        self.assertEqual(rows(result[1]), [
            ("サブジェクト1", 0, 1000, "閉口"), ("サブジェクト1", 1000, 2000, "自由"),
            ("サブジェクト1", 2000, 6000, "閉口")])

    def test_targets_bind_to_actual_concept_not_template_placeholders(self):
        scene = parse_template_emd(AUTHOR_TEMPLATE.replace("サブジェクト1", "サブジェクト2")).scenes[0]
        with self.assertRaises(TimelinePlannerError):
            resolve(None, scenes=(scene,))
        self.assertEqual(len(resolve(None, scenes=(scene,), subjects=2)[1]), 2)
        result = resolve(activity((0, 6000, "no_vocal_candidate")), target="サブジェクト2", subjects=2)
        self.assertEqual(result[1][0].target_concept_id, "サブジェクト2")


class MouthEMDAndCompilerTests(unittest.TestCase):
    def test_roundtrip_and_v3_artifact(self):
        document = parse_emd(CONCEPT + AUTHOR_TEMPLATE)
        self.assertEqual(rows(document.scenes[0].mouth_performances), [
            ("サブジェクト1", 0, 3000, "閉口"), ("サブジェクト1", 3000, 6000, "歌唱")])
        self.assertEqual(EMDTextArtifact.create("MVD_EMD_V3", CONCEPT + AUTHOR_TEMPLATE).schema,
                         "MVD_EMD_V3")

    def test_invalid_author_intervals_are_rejected_with_line_number(self):
        for annotation in (
            "> `口元` `サブジェクト1` 00:00.000 --> 00:00.000 `閉口`",
            "> `口元` `サブジェクト1` 00:00.000 --> 00:06.001 `閉口`",
            "> `口元` `サブジェクト2` 00:00.000 --> 00:02.000 `閉口`",
            "> `口元` `サブジェクト1` 00:00.000 --> 00:02.000 `不明`",
            "> `口元` `サブジェクト1` 00:00.000 --> 00:02.000 `閉口`\n"
            "> `口元` `サブジェクト1` 00:01.000 --> 00:03.000 `歌唱`",
        ):
            source = CONCEPT + TEMPLATE.replace("## ショット 00:00.000", annotation + "\n## ショット 00:00.000")
            with self.subTest(annotation=annotation), self.assertRaises(EMDParseError) as caught:
                parse_emd(source)
            self.assertGreater(caught.exception.line_number, 0)

    def test_free_has_no_new_visual_prompt(self):
        source = CONCEPT + TEMPLATE
        annotated = source.replace("## ショット 00:00.000",
            "> `口元` `サブジェクト1` 00:00.000 --> 00:06.000 `自由`\n## ショット 00:00.000")
        self.assertEqual(compile_ref2va(source, IdentityTranslator()).plan,
                         compile_ref2va(annotated, IdentityTranslator()).plan)

    def test_closed_scene_keeps_audio_lock_and_authored_fields(self):
        base = (CONCEPT + TEMPLATE.replace("未計画", "`演技` 身体を回転させる。")
                + "## 音響\n* `リップシンク` `Context Loop` `サブジェクト1`\n")
        closed = base.replace("## ショット 00:00.000",
            "> `口元` `サブジェクト1` 00:00.000 --> 00:06.000 `閉口`\n## ショット 00:00.000")
        original = compile_ref2va(base, IdentityTranslator()).plan["shots"][0]
        updated = compile_ref2va(closed, IdentityTranslator()).plan["shots"][0]
        text = "\n".join(updated["prompt"])
        self.assertIn("keeps the lips gently together", text)
        self.assertNotIn("visibly sings", text)
        self.assertEqual({k:v for k,v in original.items() if k != "prompt"},
                         {k:v for k,v in updated.items() if k != "prompt"})
        self.assertEqual(updated["source_audio_target"], "locked")
        self.assertEqual([l for l in original["prompt"] if l.startswith("[Shot")],
                         [l for l in updated["prompt"] if l.startswith("[Shot")])

    def test_compiler_uses_author_state_not_activity_detection(self):
        value = activity((0, 6000, "vocal_candidate"))
        source = CONCEPT + "\n".join(value.render_lines()) + "\n" + TEMPLATE.replace(
            "## ショット 00:00.000",
            "> `口元` `サブジェクト1` 00:00.000 --> 00:06.000 `閉口`\n## ショット 00:00.000")
        text = "\n".join(compile_ref2va(source, IdentityTranslator()).plan["shots"][0]["prompt"])
        self.assertIn("keeps the lips gently together", text)
        self.assertNotIn("vocal_candidate", text)
        self.assertNotIn("閉口", text)

    def test_mixed_scene_has_exact_pcm_time_independent_of_shot(self):
        source = CONCEPT + AUTHOR_TEMPLATE
        text = "\n".join(compile_ref2va(source, IdentityTranslator()).plan["shots"][0]["prompt"])
        self.assertIn("From 00:00.000 to 00:03.000", text)
        self.assertIn("From 00:03.000 to 00:06.000", text)
        self.assertIn("[Shot 2] At 00:03.500", text)

    def test_continuation_prefix_uses_timing_profile_without_adding_shots(self):
        second = AUTHOR_TEMPLATE.replace("シーン` 1", "シーン` 2").replace(
            "# シーン 00:00.000 --> 00:06.000", "# シーン 00:06.000 --> 00:12.000 継続")
        # Shift the annotation and Shot times without changing durations.
        second = second.replace("`サブジェクト1` 00:00.000 --> 00:03.000",
                                "`サブジェクト1` 00:06.000 --> 00:09.000")
        second = second.replace("`サブジェクト1` 00:03.000 --> 00:06.000",
                                "`サブジェクト1` 00:09.000 --> 00:12.000")
        second = second.replace("## ショット 00:00.000", "## ショット 00:06.000")
        second = second.replace("## ショット 00:03.500", "## ショット 00:09.500")
        source = CONCEPT + TEMPLATE + second
        for frames, prefix in ((22, "00:00.917"), (39, "00:01.625"), (0, "00:00.000")):
            profile = replace(DEFAULT_H3_TIMING_PROFILE, continuation_context_length=frames)
            scenes = compile_ref2va(source, IdentityTranslator(), timing_profile=profile).plan["shots"]
            self.assertEqual(len(scenes), 2)
            self.assertIn("From " + prefix, "\n".join(scenes[1]["prompt"]))
            self.assertEqual(scenes[1]["context_length"], frames)

    def test_author_targets_and_audio_reference_are_preserved(self):
        source = (CONCEPT + "* 二人目。\n" + AUTHOR_TEMPLATE.replace("サブジェクト1", "サブジェクト2")
                  + "## 音響\n* `リップシンク` `Audio参照` `サブジェクト2` `音声1`\n")
        result = compile_ref2va(source, IdentityTranslator())
        text = "\n".join(result.plan["shots"][0]["prompt"])
        self.assertIn("<Subject 2> keeps the lips", text)
        self.assertNotIn("<Subject 1> keeps the lips", text)
        self.assertTrue(any(i.purpose == "lip_sync_audio_reference" for i in result.required_references.references))

    def test_pure_closed_audio_reference_removes_global_singing_only(self):
        source = (CONCEPT + TEMPLATE.replace("## ショット 00:00.000",
            "> `口元` `サブジェクト1` 00:00.000 --> 00:06.000 `閉口`\n## ショット 00:00.000")
            + "## 音響\n* `リップシンク` `Audio参照` `サブジェクト1` `音声1`\n")
        result = compile_ref2va(source, IdentityTranslator())
        text = "\n".join(result.plan["shots"][0]["prompt"])
        self.assertIn("keeps the lips gently together", text)
        self.assertIn("<Audio 1> supplies the scene audio", text)
        self.assertNotIn("performs visible lip movements", text)
        self.assertTrue(any(i.purpose == "lip_sync_audio_reference" for i in result.required_references.references))


class MouthPipelineTests(unittest.TestCase):
    def test_normal_pipeline_passes_policy_only_to_performance_and_camera(self):
        value = activity((0, 3000, "instrumental_candidate"), (3000, 6000, "vocal_candidate"))
        backend = Backend()
        result = plan_timeline(backend,
            template_emd="\n".join(value.render_lines()) + "\n" + TEMPLATE,
            concept_emd=CONCEPT, direction=DirectionArtifact(motion_profile_id="anime_scene_author_mv"),
            lip_sync_mode="context_loop", lip_sync_target="サブジェクト1", lip_sync_audio_slot=1,
            system_prompts=_system_prompts(), runtime_config=_runtime())
        self.assertTrue(result.complete)
        self.assertEqual(result.emd.schema, "MVD_EMD_V3")
        self.assertEqual(len(backend.calls), 3)
        for task, payload in backend.calls:
            if task == "scene-author-event":
                self.assertNotIn("mouth_performance", payload)
            else:
                self.assertEqual(payload["mouth_performance"]["intervals"][1]["start_ms"], 3000)
        self.assertEqual(PlannerContent.from_dict(result.content.to_dict()), result.content)
        doc = parse_emd(result.emd.text)
        self.assertEqual(rows(doc.scenes[0].mouth_performances), [
            ("サブジェクト1", 0, 2800, "閉口"), ("サブジェクト1", 3000, 6000, "歌唱")])
        compiled = compile_ref2va(result.emd.text, IdentityTranslator())
        self.assertEqual(compiled.plan["shots"][0]["source_audio_target"], "locked")

    def test_explicit_mouth_input_without_activity_reaches_pipeline(self):
        result = plan_timeline(Backend(), template_emd=AUTHOR_TEMPLATE,
            concept_emd=CONCEPT, direction=DirectionArtifact(),
            lip_sync_mode="off", lip_sync_target="サブジェクト1", lip_sync_audio_slot=1,
            system_prompts=_system_prompts(), runtime_config=_runtime())
        self.assertEqual(rows(parse_emd(result.emd.text).scenes[0].mouth_performances),
                         rows(parse_emd(CONCEPT + AUTHOR_TEMPLATE).scenes[0].mouth_performances))


if __name__ == "__main__":
    unittest.main()
