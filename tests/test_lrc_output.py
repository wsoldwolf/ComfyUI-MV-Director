import copy
from dataclasses import replace
import json
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from core.h3_contract import DEFAULT_H3_TIMING_PROFILE
from core.lyrics import AlignedLyric, build_timeline, parse_plain_lyrics, render_lrc, render_srt, render_template_emd
from nodes.node_lyric_segmentation import node
from tools.generate_workflows import sync_lyric_outputs, validate_workflow, write_workflows
from tools.srt_to_lrc import convert_srt


ROOT = Path(__file__).resolve().parents[1]


def timeline():
    lyrics = parse_plain_lyrics('[VERSE]\n朝霧を裂いて\n')
    return build_timeline((AlignedLyric(lyrics[0], 2123, 3500),), (),
        source_audio_duration_ms=6000, max_scene_duration_ms=10000,
        timing_profile=DEFAULT_H3_TIMING_PROFILE)


class LrcOutputTests(unittest.TestCase):
    def test_lrc_matches_script_from_same_srt_and_does_not_change_timeline(self):
        source = timeline()
        before = source.to_dict()
        for offset in (0, 1000, -2500):
            with self.subTest(offset=offset):
                self.assertEqual(render_lrc(source, offset_ms=offset),
                                 convert_srt(render_srt(source, offset_ms=offset)))
        self.assertEqual(render_lrc(source), '[00:02.12]朝霧を裂いて\n')
        self.assertEqual(source.to_dict(), before)

    def test_multiline_text_is_joined(self):
        source = timeline()
        source = replace(source, lyrics=(replace(source.lyrics[0], text='最初\n次の行'),))
        self.assertEqual(render_lrc(source), '[00:02.12]最初 次の行\n')

    def test_no_lyrics_returns_empty_lrc(self):
        self.assertEqual(render_lrc(replace(timeline(), lyrics=())), '')

    def test_cache_hit_appends_lrc_with_offset_without_whisper_or_vad(self):
        import torch
        source = timeline()
        cached = {'timeline': source.to_dict(), 'template_emd': render_template_emd(source).text}
        model = SimpleNamespace(selection_id='test', size=1, mtime_ns=1)
        instance = node.MVDirectorLyricSegmentation()
        with patch.object(node, '_cache', return_value=SimpleNamespace(get=lambda key: cached)), \
             patch.object(node, 'resolve_comfy_whisper_model', return_value=model), \
             patch.object(node, '_activity_diagnostic', return_value=None), \
             patch.object(instance._whisper, 'ensure_loaded', side_effect=AssertionError('no inference')):
            result = instance.segment(vocal_audio={'waveform': torch.zeros((1, 1, 6000)), 'sample_rate': 1000},
                lyrics_text='[VERSE]\n朝霧を裂いて\n', whisper_model='test', language='ja',
                max_scene_duration_ms=10000, srt_time_offset_ms=-500, cache_mode='reuse', keep_whisper_loaded=False)
        self.assertEqual(result[:3], (cached['template_emd'], render_srt(source, offset_ms=-500), source))
        self.assertIn('cache=hit', result[3])
        self.assertEqual(result[4], '[00:01.62]朝霧を裂いて\n')

    def test_cache_miss_also_appends_lrc(self):
        import torch
        source = parse_plain_lyrics('[VERSE]\n朝霧を裂いて\n')[0]
        instance = node.MVDirectorLyricSegmentation()
        model = SimpleNamespace(path=Path('unused.pt'), selection_id='test', size=1, mtime_ns=1)
        with patch.object(node, '_cache', return_value=None), \
             patch.object(node, 'resolve_comfy_whisper_model', return_value=model), \
             patch.object(node, 'analyze_waveform', return_value=()), \
             patch.object(node, '_activity_diagnostic', return_value=None), \
             patch.object(node, 'prepare_whisper_audio', return_value=torch.zeros(96000)), \
             patch.object(node, 'align_lyrics', return_value=((AlignedLyric(source, 2123, 3500),), ())), \
             patch.object(instance._whisper, 'resolve_device', return_value='cpu'), \
             patch.object(instance._whisper, 'ensure_loaded'), \
             patch.object(instance._whisper, 'transcribe', return_value={'segments': []}):
            result = instance.segment(vocal_audio={'waveform': torch.zeros((1, 1, 6000)), 'sample_rate': 1000},
                lyrics_text='[VERSE]\n朝霧を裂いて\n', whisper_model='test', language='ja',
                max_scene_duration_ms=10000, srt_time_offset_ms=1000, cache_mode='disabled', keep_whisper_loaded=False)
        self.assertIn('cache=miss', result[3])
        self.assertEqual(result[4], '[00:03.12]朝霧を裂いて\n')
        self.assertEqual(result[4], convert_srt(result[1]))

    def test_workflow_migration_only_appends_output_and_is_idempotent(self):
        for path in (ROOT / 'workflows').glob('*.json'):
            workflow = json.loads(path.read_text(encoding='utf-8'))
            for item in workflow['nodes']:
                if item['type'] == 'MVDirectorLyricSegmentation':
                    item['outputs'] = item['outputs'][:4]
            before = copy.deepcopy(workflow)
            sync_lyric_outputs(workflow)
            validate_workflow(workflow)
            for original, item in zip(before['nodes'], workflow['nodes']):
                expected = copy.deepcopy(original)
                if item['type'] == 'MVDirectorLyricSegmentation':
                    expected['outputs'].append({'name': 'lrc_text', 'type': 'STRING', 'links': None})
                self.assertEqual(item, expected)
            self.assertEqual(workflow['links'], before['links'])
            first = copy.deepcopy(workflow)
            sync_lyric_outputs(workflow)
            self.assertEqual(workflow, first)

    def test_sync_command_does_not_create_deleted_workflows(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            path = root / '01_plan_compiler_context_loop_4subject.json'
            workflow = json.loads((ROOT / 'workflows' / path.name).read_text(encoding='utf-8'))
            for item in workflow['nodes']:
                if item['type'] == 'MVDirectorLyricSegmentation':
                    item['outputs'] = item['outputs'][:4]
            path.write_text(json.dumps(workflow, ensure_ascii=False), encoding='utf-8')
            write_workflows(Path('unused'), root, lyric_outputs_only=True)
            self.assertEqual([p.name for p in root.iterdir()], [path.name])
            first = path.read_bytes()
            write_workflows(Path('unused'), root, lyric_outputs_only=True)
            self.assertEqual(path.read_bytes(), first)


if __name__ == '__main__':
    unittest.main()
