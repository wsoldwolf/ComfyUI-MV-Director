"""Shared-vocal target transport, not proof of H3's visible mouth accuracy."""
from dataclasses import replace
import unittest

from core.artifacts import DirectionArtifact
from core.compiler import IdentityTranslator, compile_ref2va
from core.emd import MouthPerformance, parse_emd
from core.emd.errors import EMDParseError
from core.planner import plan_timeline, parse_lip_sync_targets, render_completed_emd
from core.planner.errors import TimelinePlannerError
from core.planner.mouth_performance import plan_mouth_performances
from core.planner.template import PlannerTemplate, parse_template_emd
from nodes.node_timeline_planner.node import _system_prompts
from scene_author_fixtures import Backend, _runtime
from test_mouth_performance import activity


CONCEPT = '# サブジェクト\n* `画像1` Singer A.\n* `画像3` Singer B.\n* `画像4` Dancer C.\n'
TEMPLATE = ('> `シーン` 1\n# シーン 00:00.000 --> 00:06.000\n* `H3長` 158\n'
            '> `歌詞開始` 00:03.000\n> `歌詞終了` 00:06.000\n> `歌詞` 同じ歌\n'
            '## ショット 00:00.000\n* 未計画\n')
TARGETS = 'サブジェクト1,サブジェクト2'


def rendered(target=TARGETS, mode='context_loop'):
    return render_completed_emd(concept_emd=CONCEPT, template=parse_template_emd(TEMPLATE),
        direction=DirectionArtifact(), actions={(1, 1): 'The performers sway.'},
        cameras={(1, 1): 'Static Shot.'}, lip_sync_mode=mode, lip_sync_target=target, lip_sync_audio_slot=1)


class MultiLipSyncTests(unittest.TestCase):
    def test_ui_list_parsing_preserves_order_and_single_target(self):
        self.assertEqual(parse_lip_sync_targets('サブジェクト1'), ('サブジェクト1',))
        for value in (' サブジェクト2, サブジェクト1 ', 'サブジェクト2，サブジェクト1', 'サブジェクト2、サブジェクト1'):
            with self.subTest(value=value):
                self.assertEqual(parse_lip_sync_targets(value, subject_count=2), ('サブジェクト2', 'サブジェクト1'))
        self.assertEqual(len(parse_lip_sync_targets(','.join(f'サブジェクト{i}' for i in range(1, 5)), subject_count=4)), 4)

    def test_invalid_duplicate_and_undefined_targets_fail(self):
        for value in ('', 'サブジェクト1,', ',サブジェクト1', 'サブジェクト1,,サブジェクト2',
                      'サブジェクト1,サブジェクト1', 'サブジェクト5', 'サブジェクト1,2', None):
            with self.subTest(value=value), self.assertRaises(TimelinePlannerError):
                parse_lip_sync_targets(value)
        with self.assertRaisesRegex(TimelinePlannerError, 'undefined'):
            parse_lip_sync_targets(TARGETS, subject_count=1)

    def test_individual_directives_roundtrip_in_both_audio_modes(self):
        for mode in ('context_loop', 'audio_reference'):
            source = rendered(mode=mode).text
            document = parse_emd(source)
            directives = document.scenes[0].audio_directives
            self.assertEqual([d.target_concept_id for d in directives], ['サブジェクト1', 'サブジェクト2'])
            self.assertEqual({d.mode for d in directives}, {mode})
            self.assertNotIn('`サブジェクト1,サブジェクト2`', source)

    def test_audio_modes_still_exclusive_duplicate_and_distinct_stems_fail(self):
        base = rendered().text
        for extra in ('* `リップシンク` `Context Loop` `サブジェクト1`\n',
                      '* `リップシンク` `Audio参照` `サブジェクト3` `音声1`\n', '* `無音`\n'):
            with self.subTest(extra=extra), self.assertRaises(EMDParseError):
                parse_emd(base + extra)
        with self.assertRaisesRegex(EMDParseError, 'multiple lip-sync audio slots'):
            parse_emd(rendered(mode='audio_reference').text.replace('`サブジェクト2` `音声1`', '`サブジェクト2` `音声2`'))

    def test_compiler_binds_both_targets_to_one_locked_audio_without_touching_actions(self):
        one = compile_ref2va(rendered('サブジェクト1').text, IdentityTranslator())
        two = compile_ref2va(rendered().text, IdentityTranslator())
        original, scene = one.plan['shots'][0], two.plan['shots'][0]
        text = '\n'.join(scene['prompt'])
        self.assertIn('<Subject 1> visibly sings', text)
        self.assertIn('<Subject 2> visibly sings', text)
        self.assertNotIn('<Subject 3> visibly sings', text)
        self.assertEqual(scene['source_audio_target'], 'locked')
        self.assertEqual({k: v for k, v in scene.items() if k != 'prompt'},
                         {k: v for k, v in original.items() if k != 'prompt'})
        self.assertEqual([line for line in scene['prompt'] if line.startswith('[Shot')],
                         [line for line in original['prompt'] if line.startswith('[Shot')])
        self.assertEqual(one.required_references, two.required_references)

    def test_shared_audio_reference_retains_each_subject_binding(self):
        result = compile_ref2va(rendered(mode='audio_reference').text, IdentityTranslator())
        refs = [r for r in result.required_references.references if r.purpose == 'lip_sync_audio_reference']
        self.assertEqual({r.concept_id for r in refs}, {'サブジェクト1', 'サブジェクト2'})
        self.assertEqual({r.required_input for r in refs}, {'ref_audios.ref_audio_0'})
        text = '\n'.join(result.plan['shots'][0]['prompt'])
        for i in (1, 2):
            self.assertIn(f'<Subject {i}> performs visible lip movements synchronized to <Audio 1>.', text)

    def test_same_lyrics_are_emitted_for_selected_subjects_only(self):
        source = rendered(mode='lyrics').text
        shot = parse_emd(source).scenes[0].shots[0]
        self.assertEqual(shot.lyric_lip_sync, (('サブジェクト1', '同じ歌'), ('サブジェクト2', '同じ歌')))
        text = '\n'.join(compile_ref2va(source, IdentityTranslator()).plan['shots'][0]['prompt'])
        self.assertEqual(text.count('performs visible lip movements to <d>[Japanese]同じ歌</d>.'), 2)

    def test_auto_mouth_plan_is_per_target_and_preserves_author_override(self):
        template = parse_template_emd(TEMPLATE)
        free = MouthPerformance('サブジェクト1', 1000, 2000, '自由')
        scene = replace(template.scenes[0], mouth_performances=(free,))
        value = activity((0, 3000, 'no_vocal_candidate'), (3000, 6000, 'vocal_candidate'))
        mouths = plan_mouth_performances(PlannerTemplate((scene,), value), lip_sync_mode='context_loop',
            lip_sync_target=TARGETS, subject_count=3)[1]
        self.assertIn(free, mouths)
        self.assertEqual([(m.start_ms, m.end_ms) for m in mouths if m.target_concept_id == 'サブジェクト1' and m.state == '閉口'],
                         [(0, 1000), (2000, 2800)])
        self.assertEqual([(m.start_ms, m.end_ms) for m in mouths if m.target_concept_id == 'サブジェクト2' and m.state == '閉口'],
                         [(0, 2800)])
        self.assertEqual({m.target_concept_id for m in mouths if m.state == '歌唱'}, {'サブジェクト1', 'サブジェクト2'})
        self.assertNotIn('サブジェクト3', {m.target_concept_id for m in mouths})

    def test_zero_post_margin_closes_each_selected_target_at_vocal_end(self):
        template = parse_template_emd(TEMPLATE)
        value = activity((0, 3000, 'vocal_candidate'), (3000, 6000, 'no_vocal_candidate'))
        mouths = plan_mouth_performances(PlannerTemplate(template.scenes, value),
            lip_sync_mode='context_loop', lip_sync_target=TARGETS, subject_count=3)[1]
        self.assertEqual([(m.target_concept_id, m.start_ms, m.end_ms)
                          for m in mouths if m.state == '閉口'], [
            ('サブジェクト1', 3000, 6000), ('サブジェクト2', 3000, 6000)])
        self.assertNotIn('サブジェクト3', {m.target_concept_id for m in mouths})

    def test_one_closed_target_does_not_suppress_other_singer(self):
        source = rendered().text.replace('> `歌詞開始`',
            '> `口元` `サブジェクト1` 00:00.000 --> 00:06.000 `閉口`\n> `歌詞開始`', 1)
        text = '\n'.join(compile_ref2va(source, IdentityTranslator()).plan['shots'][0]['prompt'])
        self.assertIn('<Subject 1> keeps the lips', text)
        self.assertNotIn('<Subject 1> visibly sings', text)
        self.assertIn('<Subject 2> visibly sings', text)

    def test_singer_ids_reach_performance_and_camera_even_without_activity(self):
        backend = Backend()
        result = plan_timeline(backend, template_emd=TEMPLATE, concept_emd=CONCEPT, direction=DirectionArtifact(),
            lip_sync_mode='context_loop', lip_sync_target=TARGETS, lip_sync_audio_slot=1,
            system_prompts=_system_prompts(), runtime_config=_runtime())
        self.assertTrue(result.complete)
        for task, payload in backend.calls:
            if task in ('scene-author-performance', 'scene-author-camera'):
                self.assertEqual(payload['lip_sync_targets'], ['サブジェクト1', 'サブジェクト2'])
            elif task == 'scene-author-event':
                self.assertNotIn('lip_sync_targets', payload)
        self.assertEqual(len(parse_emd(result.emd.text).scenes[0].audio_directives), 2)

    def test_bad_target_is_rejected_before_any_inference_without_activity(self):
        backend = Backend()
        with self.assertRaisesRegex(TimelinePlannerError, 'undefined'):
            plan_timeline(backend, template_emd=TEMPLATE, concept_emd=CONCEPT, direction=DirectionArtifact(),
                lip_sync_mode='context_loop', lip_sync_target='サブジェクト4', lip_sync_audio_slot=1,
                system_prompts=_system_prompts(), runtime_config=_runtime())
        self.assertEqual(backend.calls, [])

    def test_four_target_activity_survives_normal_pipeline_and_compilation(self):
        value = activity((0, 3000, 'instrumental_candidate'), (3000, 6000, 'vocal_candidate'))
        targets = ','.join(f'サブジェクト{i}' for i in range(1, 5))
        concept = CONCEPT + '* Singer D.\n'
        backend = Backend()
        result = plan_timeline(backend,
            template_emd='\n'.join(value.render_lines()) + '\n' + TEMPLATE,
            concept_emd=concept, direction=DirectionArtifact(),
            lip_sync_mode='context_loop', lip_sync_target=targets, lip_sync_audio_slot=1,
            system_prompts=_system_prompts(), runtime_config=_runtime())
        self.assertTrue(result.complete)
        self.assertEqual(len(backend.calls), 3)
        scene = parse_emd(result.emd.text).scenes[0]
        self.assertEqual(len(scene.audio_directives), 4)
        self.assertEqual(len(scene.mouth_performances), 8)
        compiled = compile_ref2va(result.emd.text, IdentityTranslator()).plan['shots'][0]
        self.assertEqual(compiled['source_audio_target'], 'locked')
        text = '\n'.join(compiled['prompt'])
        for i in range(1, 5):
            self.assertIn(f'From 00:00.000 to 00:02.800 in the generated clip, <Subject {i}> keeps the lips', text)
            self.assertIn(f'From 00:03.000 to 00:06.000 in the generated clip, <Subject {i}> visibly sings', text)

    def test_off_never_emits_singing_and_single_target_remains_identical(self):
        self.assertEqual(rendered(' サブジェクト1 ').text, rendered('サブジェクト1').text)
        self.assertNotIn('`リップシンク`', rendered(mode='off').text)


if __name__ == '__main__':
    unittest.main()
