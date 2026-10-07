"""Inference evidence preservation checks are CPU-only."""
import unittest

from tools.debug_prop_pipeline import prepare, contract_run, remove_transport_markers
from tools.debug_prop_pipeline_infer import check_preservation
from test_prop_pipeline_prepare import SOURCE


def source_with_audio():
    audio = '## 音響\n* `リップシンク` `Context Loop` `サブジェクト1`\n'
    return SOURCE.replace('> `シーン` 3', audio + '> `シーン` 3').replace(
        '> `シーン` 4', audio + '> `シーン` 4') + audio


class PropPipelineInferenceTests(unittest.TestCase):
    def setUp(self):
        self.source = source_with_audio()
        self.inputs = prepare(self.source, (2, 3, 4))
        result, _ = contract_run(self.inputs)
        self.candidate = remove_transport_markers(result.emd.text,
                                                 self.inputs['no_event_transport_markers'])

    def test_replay_preserves_fixed_fields_and_timing(self):
        checks = check_preservation(self.source, self.candidate, self.inputs)
        self.assertTrue(checks['fixed_shots_preserved'])
        self.assertTrue(checks['events_preserved'])

    def test_fixed_event_change_is_detected(self):
        changed = self.candidate.replace('葉が舞う。', '雨が降る。')
        with self.assertRaisesRegex(AssertionError, 'Fixed Event changed'):
            check_preservation(self.source, changed, self.inputs)

    def test_outside_field_change_is_detected(self):
        changed = self.candidate.replace('外側の固定演技。', '別の演技。')
        with self.assertRaisesRegex(AssertionError, 'Fixed or outside Shot changed'):
            check_preservation(self.source, changed, self.inputs)


if __name__ == '__main__':
    unittest.main()
