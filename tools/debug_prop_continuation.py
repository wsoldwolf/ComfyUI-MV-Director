"""Validate next-Scene authorship using the user-adopted prop repair state.

Production task handlers/prompts replay saved Scene 17 inputs; only Scene 17
primary Performance/Camera are replaced. This is not a whole-song Planner run.
No H3 job is submitted by this tool.
"""
from __future__ import annotations

import argparse
from copy import deepcopy
import hashlib
import json
import logging
from pathlib import Path
import re
import shutil
import subprocess
import sys
import time

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from core.compiler import LlamaPromptTranslator, compile_ref2va
from core.inference import LlamaCppLifecycle, LlamaRuntimeConfig
from core.planner.prop_decision import request_prop_decisions
from core.planner.requests import request_entities
from core.planner.scene_author import _split_terminal_state
from core.planner.types import PlannerEntity
from nodes.node_emd_compiler.node import _system_prompt as compiler_prompt
from nodes.node_timeline_planner.node import _LlamaPlannerBackend, _planner_transport_policy, _system_prompts
from tools.debug_prop_shot_repair import replace_fields

OUTPUT = Path(r'C:\Software\ComfyUI\output')


def read(path):
    return json.loads(path.read_text(encoding='utf-8-sig'))


def save(path, value):
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding='utf-8')


def build_inputs(calls, handoff):
    tasks = ('scene-author-prop-decision', 'scene-author-performance', 'scene-author-camera')
    selected = {}
    for task in tasks:
        rows = [c for c in calls if c['task'] == task and c['payload'].get('scene_number') == 17]
        if len(rows) != 1:
            raise ValueError('Expected one saved Scene 17 call per task')
        selected[task] = deepcopy(rows[0]['payload'])
    for task in tasks[:2]:
        selected[task]['previous_scene_state'] = handoff['performance_end_state']
    selected[tasks[0]]['previous_prop_state'] = deepcopy(handoff['accepted_prop_decision']['end_state'])
    # Keep the LLM's Camera prose verbatim. No Python inference of a camera pose.
    selected[tasks[2]]['previous_scene_state'] = handoff['camera_from_same_joint_proposal']
    return selected


def prepare(args):
    if args.out.exists():
        raise FileExistsError('Use a fresh evidence directory')
    handoff = read(args.repair / 'state-handoff.json')
    inputs = build_inputs(read(args.saved / 'calls.json'), handoff)
    previous_manifest = read(args.baseline / 'manifest.json')
    previous_run = OUTPUT / 'h3_chains' / previous_manifest['case']
    previous = read(previous_run / 'checkpoints/clip_0016.json')
    if previous['segment']['seed'] != previous_manifest['seed']:
        raise ValueError('Adopted seed does not match rendered Scene 16')
    args.out.mkdir(parents=True)
    save(args.out / 'inputs.json', inputs)
    shutil.copy2(args.baseline / 'candidate.md', args.out / 'source-emd.md')
    save(args.out / 'conditions.json', {
        'baseline': str(args.baseline), 'translation_source': str(args.translation_source),
        'previous_run': str(previous_run), 'model': str(args.model), 'case': args.case,
        'previous_scene': 16, 'new_scene': 17, 'source_calls': str(args.saved / 'calls.json'),
        'handoff_source': str(args.repair / 'state-handoff.json'),
        'handoff_is_planned_state_not_video_observation': True,
        'adopted_previous_seed': previous['segment']['seed'],
        'previous_checkpoint_sha256': previous['segment']['checkpoint_sha256'],
        'source_emd_sha256': hashlib.sha256((args.out / 'source-emd.md').read_bytes()).hexdigest(),
        'production_integrated': False, 'h3_not_submitted_at_preparation': True,
    })
    print('Prepared Scene 17 task replay with adopted Scene 16 state', flush=True)


def infer(evidence):
    if (evidence / 'calls.json').exists():
        raise FileExistsError('Inference already attempted; inspect saved calls')
    conditions, inputs = read(evidence / 'conditions.json'), read(evidence / 'inputs.json')
    config = LlamaRuntimeConfig(n_ctx=16384, n_batch=256, max_tokens=1536, temperature=0.2, seed=20261007)
    model = Path(conditions['model'])
    prompts = _system_prompts(prop_holding=True)
    logging.basicConfig(level=logging.INFO, format='%(asctime)s %(message)s',
        handlers=[logging.StreamHandler(sys.stdout), logging.FileHandler(evidence / 'inference.log', encoding='utf-8')])
    lifecycle = LlamaCppLifecycle()

    class RecordingBackend(_LlamaPlannerBackend):
        def __init__(self):
            super().__init__(lifecycle)
            self.calls = []

        def complete_planner(self, **kwargs):
            row = {'task': kwargs['task'], 'payload': json.loads(kwargs['payload']), 'system_prompt': kwargs['system_prompt']}
            self.calls.append(row)
            started = time.perf_counter()
            try:
                row['response'] = super().complete_planner(**kwargs)
                return row['response']
            finally:
                row['elapsed_s'] = time.perf_counter() - started
                save(evidence / 'calls.json', self.calls)

    backend = RecordingBackend()
    backend.transport_policy = _planner_transport_policy(model.name)
    started = time.perf_counter()
    try:
        logging.info('GPU model loading starts for Scene 17 continuation')
        lifecycle.ensure_loaded(model, config)
        decision = request_prop_decisions(backend, shared=inputs['scene-author-prop-decision'],
            system_prompt=prompts['scene-author-prop-decision'], runtime_config=config)
        if not decision.decisions:
            raise RuntimeError('No holding proposal; diagnostic stopped without modifying EMD')
        values, states = {}, {}
        for task, record, key in (('scene-author-performance', 'PERFORMANCE', 'performance'),
                                  ('scene-author-camera', 'CAMERA', 'camera')):
            payload = deepcopy(inputs[task])
            payload['accepted_prop_decisions'] = {str(k): v for k, v in decision.decisions.items()}
            if key == 'camera':
                payload['accepted_performances'] = {'1': values['performance']}
            for field in ('slots', 'task', 'protocol'):
                payload.pop(field, None)
            result, issues, retries, missing, recovered = request_entities(backend,
                task=task, record_type=record,
                entities=[PlannerEntity(17, (1,), {'scene': 17, 'scene_number': 17, 'shot': 1,
                                                  'position': payload['shot_positions'][0]})],
                shared=payload, system_prompt=prompts[task] + ('\n' + prompts['prop-performance-addendum'] if key == 'performance' else ''),
                runtime_config=config, interrupt_callback=None)
            if missing:
                raise RuntimeError(f'{task} incomplete; saved response retained')
            values[key], states[key] = _split_terminal_state(result[(1,)])
        candidate = replace_fields((evidence / 'source-emd.md').read_text(encoding='utf-8'),
            {'status': 'REVISE', **values}, scene_number=17, shot_number=1)
        (evidence / 'candidate-emd.md').write_text(candidate, encoding='utf-8')
        save(evidence / 'result.json', {'values': values, 'terminal_states': states,
            'holding_plan': decision.decisions[1], 'elapsed_s': time.perf_counter() - started,
            'outside_shots_fixed_event_mouth_timing_preserved': True,
            'existing_secondary_performance_preserved': True, 'runtime': config.to_dict()})
        print(json.dumps(values, ensure_ascii=False), flush=True)
    finally:
        lifecycle.clear()
        logging.info('Owned 31B model unloaded')


def compile_graph(evidence):
    if (evidence / 'h3-candidate.json').exists():
        raise FileExistsError('Graph already prepared')
    conditions = read(evidence / 'conditions.json')
    baseline = Path(conditions['baseline'])
    before_plan = read(baseline / 'candidate-plan.json')
    trace_source = Path(conditions['translation_source'])
    cache = {tuple(r['fragments']): tuple(r['translated']) for r in read(trace_source / 'translation.json')}
    model = Path(conditions['model'])
    config = LlamaRuntimeConfig(n_ctx=16384, n_batch=256, max_tokens=4096, temperature=0.0, seed=20261007)
    lifecycle, trace = LlamaCppLifecycle(), []
    translator = LlamaPromptTranslator(lifecycle, system_prompt=compiler_prompt(), runtime_config=config)
    class Cached:
        def translate(self, units):
            key = tuple(units)
            self.reused = key in cache
            if not self.reused:
                lifecycle.ensure_loaded(model, config)
                cache[key] = tuple(translator.translate(units))
            return cache[key]
        def record_field_translation(self, **kwargs):
            trace.append({**kwargs, 'reused_saved_translation': self.reused})
    class Saved:
        def translate(self, units):
            return cache[tuple(units)]
    def restore_seeds(plan):
        for shot, old in zip(plan['shots'], before_plan['shots']):
            shot['seed'] = old['seed']
        return plan
    if restore_seeds(compile_ref2va((evidence / 'source-emd.md').read_text(encoding='utf-8'), Saved()).plan) != before_plan:
        raise ValueError('Compiler no longer reproduces adopted Plan')
    try:
        plan = restore_seeds(compile_ref2va((evidence / 'candidate-emd.md').read_text(encoding='utf-8'), Cached()).plan)
    finally:
        lifecycle.clear()
        save(evidence / 'translation.json', trace)
    proof = deepcopy(plan)
    proof['shots'][16]['prompt'] = before_plan['shots'][16]['prompt']
    if proof != before_plan:
        raise ValueError('Plan changed outside Scene 17 prompt')
    graph = read(baseline / 'h3-candidate.json')
    for node in ('24', '37', '48'):
        graph[node]['inputs']['plan_json'] = json.dumps(plan, ensure_ascii=False)
    graph['24']['inputs']['run_name'] = conditions['case']
    graph['21']['inputs']['filename'] = conditions['case']
    for node in ('7', '29'):
        graph[node]['inputs'].update(start_clip=17, scene_range='17', verify_resume_history=True)
    run = OUTPUT / 'h3_chains' / conditions['case']
    if run.exists():
        raise FileExistsError('Run already exists')
    (run / 'checkpoints').mkdir(parents=True)
    for scene in range(1, 17):
        shutil.copy2(Path(conditions['previous_run']) / 'checkpoints' / f'clip_{scene:04d}.json',
                     run / 'checkpoints' / f'clip_{scene:04d}.json')
    save(evidence / 'candidate-plan.json', plan)
    save(evidence / 'h3-candidate.json', graph)
    save(evidence / 'compile-checks.json', {'only_scene17_prompt_changed': True,
        'adopted_scene16_seed_preserved': plan['shots'][15]['seed'],
        'new_translation_fields': [r['field_id'] for r in trace if not r['reused_saved_translation']]})
    print('Scene 17 graph prepared; adopted Scene 16 retained as predecessor', flush=True)


def finalize(evidence):
    conditions, plan = read(evidence / 'conditions.json'), read(evidence / 'candidate-plan.json')
    history = read(evidence / 'render-candidate.json')
    if history['history']['status']['status_str'] != 'success':
        raise ValueError('Render did not succeed')
    run = OUTPUT / 'h3_chains' / conditions['case']
    metadata = [read(run / 'checkpoints' / f'clip_{scene:04d}.json') for scene in (15, 16, 17)]
    target = metadata[2]
    if target['segment']['predecessor_checkpoint_sha256'] != conditions['previous_checkpoint_sha256']:
        raise ValueError('Scene 17 did not consume adopted Scene 16 checkpoint')
    if target['segment']['seed'] != plan['shots'][16]['seed'] or target['segment']['steps'] != 20:
        raise ValueError('Scene 17 runtime seed or steps changed')
    ffmpeg, ffprobe = r'C:\Software\ffmpeg\bin\ffmpeg.exe', r'C:\Software\ffmpeg\bin\ffprobe.exe'
    clips, waves, probes = [], [], []
    for item in metadata:
        video, wav = OUTPUT / item['segment']['segment'], OUTPUT / item['segment']['generated_audio']
        probe = json.loads(subprocess.check_output([ffprobe, '-v', 'error', '-select_streams', 'v:0',
            '-show_entries', 'stream=width,height,r_frame_rate,nb_frames,duration', '-of', 'json', str(video)], encoding='utf-8'))
        stream = probe['streams'][0]
        if (stream['width'], stream['height'], stream['r_frame_rate'], int(stream['nb_frames'])) != (
                1280, 736, '24/1', item['segment']['delivered_frames']):
            raise ValueError('Media format differs from checkpoint')
        clips.append(video)
        waves.append(wav)
        probes.append(probe)
    preview = evidence / 'scene17-with-audio.mp4'
    subprocess.run([ffmpeg, '-n', '-v', 'error', '-i', str(clips[2]), '-i', str(waves[2]),
        '-map', '0:v:0', '-map', '1:a:0', '-c:v', 'copy', '-c:a', 'aac', '-b:a', '192k',
        '-movflags', '+faststart', str(preview)], check=True)
    joined = evidence / 'scenes15-17-with-audio.mp4'
    command = [ffmpeg, '-n', '-v', 'error']
    for video, wav in zip(clips, waves):
        command += ['-i', str(video), '-i', str(wav)]
    command += ['-filter_complex', '[0:v][1:a][2:v][3:a][4:v][5:a]concat=n=3:v=1:a=1[v][a]',
        '-map', '[v]', '-map', '[a]', '-c:v', 'libx264', '-crf', '18', '-preset', 'fast',
        '-c:a', 'aac', '-b:a', '192k', '-movflags', '+faststart', str(joined)]
    subprocess.run(command, check=True)
    expected_frames = sum(m['segment']['delivered_frames'] for m in metadata)
    joined_probe = json.loads(subprocess.check_output([ffprobe, '-v', 'error', '-select_streams', 'v:0',
        '-show_entries', 'stream=nb_frames,duration', '-of', 'json', str(joined)], encoding='utf-8'))
    if int(joined_probe['streams'][0]['nb_frames']) != expected_frames:
        raise ValueError('Joined preview changed delivered frame count')
    subprocess.run([ffmpeg, '-n', '-v', 'error', '-i', str(clips[2]), '-vf',
        'fps=1,scale=640:368,tile=3x3', '-frames:v', '1', str(evidence / 'scene17-contact-sheet.png')], check=True)
    save(evidence / 'media-checks.json', {
        'clips': list(map(str, clips)), 'waves': list(map(str, waves)), 'probes': probes,
        'preview': str(preview), 'continuity_preview': str(joined), 'joined_probe': joined_probe,
        'same_adopted_scene16_checkpoint': True, 'newly_rendered_scenes': [17],
        'reused_scenes': [15, 16], 'h3_elapsed_s': history['elapsed_s'],
        'human_visual_verdict_pending': True,
    })
    print(json.dumps({'preview': str(preview), 'continuity': str(joined)}, ensure_ascii=False), flush=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--out', type=Path, required=True)
    parser.add_argument('--baseline', type=Path)
    parser.add_argument('--translation-source', type=Path)
    parser.add_argument('--repair', type=Path)
    parser.add_argument('--saved', type=Path)
    parser.add_argument('--model', type=Path)
    parser.add_argument('--case')
    parser.add_argument('--mode', choices=('prepare', 'infer', 'compile', 'finalize'), required=True)
    args = parser.parse_args()
    if args.mode == 'prepare':
        if not all((args.baseline, args.translation_source, args.repair, args.saved, args.model, args.case)):
            parser.error('Preparation requires baseline, translation-source, repair, saved, model, case')
        if not re.fullmatch(r'[a-z0-9_-]+', args.case):
            parser.error('Unsafe case')
        prepare(args)
    elif args.mode == 'infer':
        infer(args.out)
    elif args.mode == 'compile':
        compile_graph(args.out)
    else:
        finalize(args.out)


if __name__ == '__main__':
    main()
