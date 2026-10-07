"""Explicit GPU inference of the prepared P4 inputs through production code.

No experimental task handler or seed override; the subclass records evidence
only. No compiler, H3 job, server start, workflow edit or commit is performed.
"""
import argparse
import hashlib
import json
import logging
from pathlib import Path
import sys
import time

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from core.artifacts import DirectionArtifact
from core.emd import parse_emd
from core.inference import LlamaCppLifecycle, LlamaRuntimeConfig
from core.planner import plan_timeline
from nodes.node_timeline_planner.node import _LlamaPlannerBackend, _planner_transport_policy, _system_prompts
from tools.debug_prop_pipeline import remove_transport_markers, semantic


def save(path, value):
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')


def check_preservation(source, candidate, inputs):
    before, after = parse_emd(source), parse_emd(candidate)
    if len(before.scenes) != len(after.scenes):
        raise AssertionError('Scene count changed')
    reopened = {tuple(k) for k in inputs['reopened_shots']}
    for old, new in zip(before.scenes, after.scenes):
        for attr in ('scene_number', 'start_ms', 'end_ms', 'h3_length', 'continuation',
                     'descriptions', 'mouth_performances', 'audio_directives'):
            if semantic(getattr(old, attr)) != semantic(getattr(new, attr)):
                raise AssertionError(f'Scene {old.scene_number}: {attr} changed')
        if len(old.shots) != len(new.shots):
            raise AssertionError('Shot count changed')
        for index, (o, n) in enumerate(zip(old.shots, new.shots), 1):
            if o.start_ms != n.start_ms or semantic(o.lyric_annotations) != semantic(n.lyric_annotations):
                raise AssertionError('Shot or lyric timing changed')
            if [d.text for d in o.directives if d.kind == '演出'] != [
                    d.text for d in n.directives if d.kind == '演出']:
                raise AssertionError('Fixed Event changed')
            if (old.scene_number, index) not in reopened and o.body != n.body:
                raise AssertionError('Fixed or outside Shot changed')
    if semantic(before.audio_activity) != semantic(after.audio_activity):
        raise AssertionError('Audio activity changed')
    return {'scene_count': len(after.scenes), 'fixed_shots_preserved': True,
            'events_preserved': True, 'mouth_lyric_timing_preserved': True,
            'audio_activity_preserved': True,
            'common_prompt_equal': semantic(before.common_prompt) == semantic(after.common_prompt)}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--prepared', type=Path, required=True)
    parser.add_argument('--model', type=Path, required=True)
    parser.add_argument('--out', type=Path, required=True)
    parser.add_argument('--performance-addendum', type=Path,
                        help='Explicit one-prompt comparison; all production stages and seeds stay unchanged')
    args = parser.parse_args()
    if args.out.exists():
        raise FileExistsError('Use a fresh inference evidence directory')
    inputs_path = args.prepared / 'inputs.json'
    inputs = json.loads(inputs_path.read_text(encoding='utf-8'))
    source = (args.prepared / 'source-emd.md').read_text(encoding='utf-8')
    prompts = _system_prompts(prop_holding=True)
    for key, value in prompts.items():
        if (args.prepared / (key + '-system.txt')).read_text(encoding='utf-8') != value:
            raise ValueError('Production prompt differs from P4 snapshot: ' + key)
    prompt_comparison = None
    if args.performance_addendum:
        before = prompts['prop-performance-addendum']
        candidate = args.performance_addendum.read_text(encoding='utf-8').strip()
        if not candidate or candidate == before:
            raise ValueError('Comparison prompt must be nonempty and different')
        prompts['prop-performance-addendum'] = candidate
        prompt_comparison = {'key': 'prop-performance-addendum',
                             'source': str(args.performance_addendum),
                             'baseline_sha256': hashlib.sha256(before.encode()).hexdigest(),
                             'candidate_sha256': hashlib.sha256(candidate.encode()).hexdigest()}
    config = LlamaRuntimeConfig(max_tokens=1536, n_ctx=16384, n_batch=256,
                               temperature=0.2, seed=20261007)
    args.out.mkdir(parents=True)
    logging.basicConfig(level=logging.INFO, format='%(asctime)s %(message)s',
                        handlers=[logging.StreamHandler(sys.stdout),
                                  logging.FileHandler(args.out / 'inference.log', encoding='utf-8')])
    lifecycle = LlamaCppLifecycle()

    class RecordingBackend(_LlamaPlannerBackend):
        def __init__(self):
            super().__init__(lifecycle)
            self.calls = []

        def complete_planner(self, **kwargs):
            started = time.perf_counter()
            entry = {'task': kwargs['task'], 'payload': json.loads(kwargs['payload']),
                     'system_prompt': kwargs['system_prompt']}
            self.calls.append(entry)
            try:
                response = super().complete_planner(**kwargs)
                entry['response'] = response
                return response
            except BaseException as exc:
                entry['error'] = repr(exc)
                raise
            finally:
                entry['elapsed_s'] = time.perf_counter() - started
                save(args.out / 'calls.json', self.calls)
                save(args.out / 'trace.json', self.trace)

    backend = RecordingBackend()
    backend.transport_policy = _planner_transport_policy(args.model.name)
    conditions = {'stage': 'P5_PRODUCTION_INFERENCE', 'gpu_authorized': True,
                  'prepared': str(args.prepared),
                  'inputs_sha256': hashlib.sha256(inputs_path.read_bytes()).hexdigest(),
                  'model': str(args.model), 'model_bytes': args.model.stat().st_size,
                  'runtime': config.to_dict(), 'transport_policy': backend.transport_policy,
                  'backend_seed_policy': 'production_payload_hash',
                  'source_direction_provenance_recovered': False, 'h3_generated': False,
                  'compiler_run': False, 'system_prompts_match_p4': True}
    conditions['prompt_comparison'] = prompt_comparison
    if prompt_comparison:
        conditions['system_prompts_match_p4'] = False
    for key, value in prompts.items():
        (args.out / (key + '-system.txt')).write_text(value, encoding='utf-8')
    save(args.out / 'conditions.json', conditions)
    started = time.perf_counter()
    try:
        logging.info('GPU model loading starts; model=%s; n_ctx=%d', args.model.name, config.n_ctx)
        lifecycle.ensure_loaded(args.model, config)
        load_s = time.perf_counter() - started
        logging.info('GPU model ready; elapsed=%.3fs; context=%s', load_s, lifecycle.effective_n_ctx)
        inference_started = time.perf_counter()
        result = plan_timeline(backend, template_emd=inputs['template_emd'],
            concept_emd=inputs['concept_emd'], scene_emd=inputs['scene_emd'],
            direction=DirectionArtifact.from_dict(inputs['direction']),
            lip_sync_mode='context_loop', lip_sync_target='サブジェクト1', lip_sync_audio_slot=1,
            system_prompts=prompts, runtime_config=config)
        elapsed = time.perf_counter() - inference_started
        save(args.out / 'result.json', {'complete': result.complete, 'missing': result.missing,
             'load_s': load_s, 'inference_s': elapsed,
             'content': result.content.to_dict() if result.content else None})
        if not result.complete:
            raise RuntimeError('Normal Planner did not produce complete output')
        (args.out / 'planner-output-with-markers.md').write_text(result.emd.text, encoding='utf-8')
        cleaned = remove_transport_markers(result.emd.text, inputs['no_event_transport_markers'])
        preservation = check_preservation(source, cleaned, inputs)
        save(args.out / 'preservation.json', preservation)
        (args.out / 'candidate-emd.md').write_text(cleaned, encoding='utf-8')
        logging.info('P5 completed; inference=%.3fs; calls=%d; preservation=%s',
                     elapsed, len(backend.calls), preservation)
    except BaseException as exc:
        save(args.out / 'failure.json', {'error': repr(exc), 'elapsed_s': time.perf_counter() - started})
        raise
    finally:
        lifecycle.clear()
        logging.info('Owned model unloaded; GPU inference finished')


if __name__ == '__main__':
    main()
