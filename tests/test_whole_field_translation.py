from dataclasses import replace
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from core.compiler.errors import CompilerError
from core.compiler import compile_ref2va, IdentityTranslator
from core.compiler.llama_translator import LlamaPromptTranslator
from core.artifacts import canonical_json
from core.compiler.protection import protect_unit
from core.compiler.whole_field import MaskedField, WholeFieldTranslator, needs_relation_translation
from core.emd import parse_emd
from core.inference import ContextBudgetError, LlamaRuntimeConfig


EMD = '# サブジェクト\n* A.\n* B.\n* 木。\n> `シーン` 1\n# シーン 00:00.000 --> 00:01.000\n* `H3長` 22\n## ショット 00:00.000\n* 待つ。\n'
SUBJECTS = parse_emd(EMD).subjects


class Lifecycle:
    effective_n_ctx = 16384
    def __init__(self, replies):
        self.replies, self.calls = iter(replies), []
    def count_serialized_prompt(self, text):
        return SimpleNamespace(count=100, estimated=False)
    def complete_chat(self, messages, config, **kwargs):
        self.calls.append(messages)
        return next(self.replies)


class WholeFieldTests(unittest.TestCase):
    def test_relation_selector_is_structural_not_person_or_noun_heuristic(self):
        self.assertTrue(needs_relation_translation(protect_unit('`サブジェクト1`が`サブジェクト3`の幹に触る。', SUBJECTS)))
        self.assertTrue(needs_relation_translation(protect_unit('`サブジェクト1`が振り向き、`サブジェクト1`が歌う。', SUBJECTS)))
        self.assertTrue(needs_relation_translation(protect_unit('`サブジェクト3`の枝から紅葉が舞う。', SUBJECTS)))
        self.assertFalse(needs_relation_translation(protect_unit('二人が向き合う。', SUBJECTS)))
        self.assertFalse(needs_relation_translation(protect_unit('`画像1`を参照してArc Shotで回る。', SUBJECTS)))

    def test_whole_field_retains_particle_context_and_restores_reordered_references(self):
        field = MaskedField.from_unit(protect_unit('`サブジェクト1`へ`サブジェクト2`が視線を向ける。', SUBJECTS))
        self.assertEqual(field.text, '__MVD_KEEP_0001__へ__MVD_KEEP_0002__が視線を向ける。')
        self.assertEqual(field.restore('__MVD_KEEP_0002__ looks toward __MVD_KEEP_0001__.'), '<Subject 2> looks toward <Subject 1>.')

    def test_repeat_occurrences_remain_separate(self):
        field = MaskedField.from_unit(protect_unit('`サブジェクト1`が`サブジェクト2`を見て、`サブジェクト1`が歌う。', SUBJECTS))
        self.assertEqual(len(field.markers), 3)
        self.assertEqual(field.restore('__MVD_KEEP_0001__ looks toward __MVD_KEEP_0002__; __MVD_KEEP_0003__ sings.').count('<Subject 1>'), 2)

    def test_dialogue_camera_and_footwear_are_exact_and_dialogue_is_not_sent(self):
        unit = protect_unit('`サブジェクト1`が「待って」と言い、Arc Shot at fast speed で足袋と下駄を見せる。', SUBJECTS)
        field = MaskedField.from_unit(unit)
        self.assertNotIn('待って', field.payload())
        translated = 'Actor ' + ' then '.join(field.markers) + '.'
        restored = field.restore(translated)
        for value in ('<Subject 1>', '<d>[Japanese]待って</d>', 'Arc Shot', 'at fast speed', 'tabi', 'geta'):
            self.assertIn(value, restored)

    def test_missing_duplicate_unknown_raw_reference_and_untranslated_output_fail(self):
        field = MaskedField.from_unit(protect_unit('`サブジェクト1`が歌う。', SUBJECTS))
        for value in ('Sings.', '__MVD_KEEP_0001__ __MVD_KEEP_0001__ sings.',
                      '__MVD_KEEP_0002__ sings.', '__MVD_KEEP_0001__ <Subject 2> sings.',
                      '__MVD_KEEP_0001__ <Subject 99> sings.', '__MVD_KEEP_0001__ 歌う。',
                      '__MVD_KEEP_0001__ __MVD_KEEP_bad__ sings.'):
            with self.subTest(value=value), self.assertRaises(CompilerError):
                field.restore(value)

    def test_protected_literal_cannot_be_printed_as_well_as_marker(self):
        field = MaskedField.from_unit(protect_unit('Arc Shot で回る。', SUBJECTS))
        with self.assertRaisesRegex(CompilerError, 'duplicated'):
            field.restore('__MVD_KEEP_0001__ Arc Shot circles.')

    def test_literal_duplicate_check_does_not_reject_unrelated_words(self):
        field = MaskedField.from_unit(protect_unit('下駄を履いて野菜を運ぶ。', SUBJECTS))
        self.assertEqual(field.restore('Wears __MVD_KEEP_0001__ and carries vegetables.'),
            'Wears geta and carries vegetables.')

    def test_source_marker_collision_is_rejected(self):
        with self.assertRaisesRegex(CompilerError, 'collides'):
            MaskedField.from_unit(protect_unit('__MVD_KEEP_0001__ を記述する。', SUBJECTS))

    def test_retries_only_twice_never_falls_back_to_fragments(self):
        lifecycle = Lifecycle(['TRANSLATION\t1\tNo marker.'] * 2)
        translator = WholeFieldTranslator(lifecycle, runtime_config=LlamaRuntimeConfig())
        with self.assertRaisesRegex(CompilerError, 'after 2'):
            translator.translate_unit(protect_unit('`サブジェクト1`が歌う。', SUBJECTS))
        self.assertEqual(len(lifecycle.calls), 2)
        self.assertIn('retry_reason', lifecycle.calls[-1][1]['content'])

    def test_successful_retry_restores_reference_without_rewriting(self):
        lifecycle = Lifecycle(['TRANSLATION\t1\tNo marker.', 'TRANSLATION\t1\t__MVD_KEEP_0001__ sings.'])
        translator = WholeFieldTranslator(lifecycle, runtime_config=LlamaRuntimeConfig())
        self.assertEqual(translator.translate_unit(protect_unit('`サブジェクト1`が歌う。', SUBJECTS)), '<Subject 1> sings.')
        self.assertEqual(translator.batch_count, 2)

    def test_wrong_slot_extra_lines_and_empty_output_do_not_pass(self):
        for response in ('TRANSLATION\t2\tSings.', 'NOTE\t1\tSings.', '',
                         'TRANSLATION\t1\tSings.\nTRANSLATION\t1\tSings.'):
            lifecycle = Lifecycle([response] * 2)
            with self.subTest(response=response), self.assertRaises(CompilerError):
                WholeFieldTranslator(lifecycle, runtime_config=LlamaRuntimeConfig()).translate_unit(protect_unit('歌う。', SUBJECTS))

    def test_parser_control_character_error_is_bounded(self):
        lifecycle = Lifecycle(['TRANSLATION\t1\t\x00Bad.'] * 2)
        with self.assertRaisesRegex(CompilerError, 'after 2'):
            WholeFieldTranslator(lifecycle, runtime_config=LlamaRuntimeConfig()).translate_unit(protect_unit('歌う。', SUBJECTS))
        self.assertEqual(len(lifecycle.calls), 2)

    def test_context_overflow_never_drops_required_context(self):
        lifecycle = Lifecycle([])
        lifecycle.effective_n_ctx = 128
        with self.assertRaises(ContextBudgetError):
            WholeFieldTranslator(lifecycle, runtime_config=replace(LlamaRuntimeConfig(), max_tokens=100)).translate_unit(protect_unit('`サブジェクト1`が歌う。', SUBJECTS))
        self.assertEqual(lifecycle.calls, [])

    def test_retry_identifies_duplicate_and_missing_occurrences(self):
        unit = protect_unit('`サブジェクト1`が`サブジェクト2`を見る。', SUBJECTS)
        lifecycle = Lifecycle(['TRANSLATION\t1\t__MVD_KEEP_0001__ sees __MVD_KEEP_0001__.',
            'TRANSLATION\t1\t__MVD_KEEP_0001__ sees __MVD_KEEP_0002__.'])
        WholeFieldTranslator(lifecycle, runtime_config=LlamaRuntimeConfig()).translate_unit(unit)
        payload = lifecycle.calls[1][1]['content']
        self.assertIn('__MVD_KEEP_0001__: expected=1, got=2', payload)
        self.assertIn('__MVD_KEEP_0002__: expected=1, got=0', payload)


class CompilerWholeFieldIntegrationTests(unittest.TestCase):
    def document(self, body):
        return ('# サブジェクト\n* Actor A.\n* Actor B.\n* A tree.\n'
            '> `シーン` 1\n# シーン 00:00.000 --> 00:01.000\n'
            '* `H3長` 22\n## ショット 00:00.000\n* ' + body + '\n')

    def translator(self, responses):
        return LlamaPromptTranslator(Lifecycle(responses), system_prompt='Translate fragments.',
            runtime_config=LlamaRuntimeConfig())

    def test_production_compiler_routes_relations_intact_and_progress_once(self):
        translator = self.translator(['TRANSLATION\t1\t__MVD_KEEP_0002__ looks toward __MVD_KEEP_0001__.'])
        progress = []
        result = compile_ref2va(self.document('`サブジェクト1`へ`サブジェクト2`が視線を向ける。'),
            translator, progress_callback=lambda done, total: progress.append((done, total)))
        self.assertIn('<Subject 2> looks toward <Subject 1>.', result.plan_json())
        self.assertNotIn('__MVD_KEEP_', result.plan_json())
        self.assertEqual(translator.whole_field_count, 1)
        self.assertEqual(translator.batch_count, 1)
        self.assertEqual(progress, [(0, 1), (1, 1)])
        trace = translator.translation_trace[0]
        self.assertEqual(trace['strategy'], 'whole_protected_field')
        self.assertEqual(trace['source'], '`サブジェクト1`へ`サブジェクト2`が視線を向ける。')
        canonical_json({'trace': translator.translation_trace})

    def test_single_subject_uses_intact_clause(self):
        translator = self.translator(['TRANSLATION\t1\t__MVD_KEEP_0001__ sings.'])
        result = compile_ref2va(self.document('`サブジェクト1`が歌う。'), translator)
        self.assertIn('<Subject 1> sings.', result.plan_json())
        self.assertEqual(translator.whole_field_count, 1)
        self.assertEqual(translator.translation_trace[0]['strategy'], 'whole_protected_field')

    def test_single_nonperson_owner_moves_after_its_owned_object(self):
        translator = self.translator(['TRANSLATION\t1\tAutumn leaves rise from the branches of __MVD_KEEP_0001__.'])
        result = compile_ref2va(self.document('`サブジェクト3`の枝から紅葉が舞い上がる。'), translator)
        self.assertIn('Autumn leaves rise from the branches of <Subject 3>.', result.plan_json())

    def test_repeated_single_subject_uses_distinct_occurrence_markers(self):
        translator = self.translator(['TRANSLATION\t1\t__MVD_KEEP_0001__ turns and __MVD_KEEP_0002__ sings.'])
        result = compile_ref2va(self.document('`サブジェクト1`が振り向き、`サブジェクト1`が歌う。'), translator)
        self.assertIn('<Subject 1> turns and <Subject 1> sings.', result.plan_json())
        self.assertEqual(translator.whole_field_count, 1)

    def test_subjectless_camera_literal_keeps_fragment_route(self):
        translator = self.translator(['TRANSLATION\t1\tcircles gently.'])
        result = compile_ref2va(self.document('Arc Shotで緩やかに回る。'), translator)
        self.assertIn('Arc Shot circles gently.', result.plan_json())
        self.assertEqual(translator.whole_field_count, 0)

    def test_one_subject_document_also_uses_intact_clause(self):
        translator = self.translator(['TRANSLATION\t1\tThe sleeves of __MVD_KEEP_0001__ flutter.'])
        emd = self.document('`サブジェクト1`の袖がなびく。').replace('* Actor B.\n* A tree.\n', '')
        result = compile_ref2va(emd, translator)
        self.assertIn('The sleeves of <Subject 1> flutter.', result.plan_json())
        self.assertEqual(translator.whole_field_count, 1)

    def test_invalid_relation_never_downgrades_to_context_free_route(self):
        translator = self.translator(['TRANSLATION\t1\tThey sing.'] * 2)
        with self.assertRaisesRegex(CompilerError, 'after 2'):
            compile_ref2va(self.document('`サブジェクト1`が`サブジェクト2`を見る。'), translator)
        self.assertEqual(translator.batch_count, 2)
        self.assertEqual(translator.whole_field_count, 0)
        self.assertTrue(all('translation-whole-protected-ja-en' in msg[1]['content']
            for msg in translator.lifecycle.calls))

    def test_whole_field_retry_is_counted_in_normal_status_statistics(self):
        translator = self.translator(['TRANSLATION\t1\tBad.',
            'TRANSLATION\t1\t__MVD_KEEP_0001__ watches __MVD_KEEP_0002__.'])
        compile_ref2va(self.document('`サブジェクト1`が`サブジェクト2`を見る。'), translator)
        self.assertEqual(translator.batch_count, 2)
        self.assertEqual(translator.protocol_recovered_count, 1)
        self.assertEqual(len(translator.translation_trace[0]['attempts']), 2)

    def test_already_english_does_not_call_whole_field_llm(self):
        class NoInference(IdentityTranslator):
            def translate_protected_unit(self, *a, **kw):
                raise AssertionError('English pass-through must not run LLM')
        result = compile_ref2va(self.document('<Subject 1> looks toward <Subject 2>.'), NoInference())
        self.assertIn('<Subject 1> looks toward <Subject 2>.', result.plan_json())

    def test_nonperson_subject_is_not_rewritten_as_actor(self):
        translator = self.translator(['TRANSLATION\t1\t__MVD_KEEP_0001__ touches the trunk of __MVD_KEEP_0002__.'])
        result = compile_ref2va(self.document('`サブジェクト1`が`サブジェクト3`の幹に触る。'), translator)
        self.assertIn('<Subject 1> touches the trunk of <Subject 3>.', result.plan_json())

    def test_cache_invalidated_when_whole_field_prompt_changes(self):
        from nodes.node_emd_compiler import node as module
        class MemoryCache:
            values = None
            def __init__(self):
                self.values = {}
            def get(self, key):
                return self.values.get(key)
            def put_success(self, key, payload):
                canonical_json(payload)
                self.values[key] = payload
        cache = MemoryCache()
        lifecycle = Lifecycle(['TRANSLATION\t1\t__MVD_KEEP_0001__ sees __MVD_KEEP_0002__.'] * 2)
        lifecycle.ensure_loaded = lambda *a: None
        lifecycle.clear = lambda: None
        instance = module.MVDirectorEMDCompiler()
        instance._lifecycle = lifecycle
        model = SimpleNamespace(path='model.gguf', selection_id='model', fingerprint='hash', size=10, mtime_ns=1)
        kwargs = dict(emd_text=self.document('`サブジェクト1`が`サブジェクト2`を見る。'),
            translation_mode='ja_to_en', model_name='model', chat_format='auto',
            max_tokens=256, temperature=0.0, top_p=0.9, repetition_penalty=1.05,
            gpu_layers=-1, n_batch=256, n_ctx=16384, flash_attn=True,
            kv_cache_type='q8_0', op_offload=True, keep_model_loaded=False, seed=1)
        with patch.object(module, '_cache', return_value=cache), \
             patch.object(module, 'resolve_comfy_gguf_model', return_value=model):
            with patch.object(module, 'whole_field_prompt', return_value='prompt A'):
                instance.compile_emd(**kwargs)
                instance.compile_emd(**kwargs)
                self.assertEqual(len(lifecycle.calls), 1)
            with patch.object(module, 'whole_field_prompt', return_value='prompt B'):
                instance.compile_emd(**kwargs)
        self.assertEqual(len(lifecycle.calls), 2)
        self.assertEqual(len(cache.values), 2)


if __name__ == '__main__':
    unittest.main()
