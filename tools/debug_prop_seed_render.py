"""Seed-only H3 diagnostic using an already compiled, rendered proposal.

No LLM inference, text modification, or production workflow update is performed.
The previous Scene checkpoint is retained and verified after rendering.
"""
from __future__ import annotations

import argparse
from copy import deepcopy
import hashlib
import json
from pathlib import Path
import re
import shutil
import subprocess


OUTPUT = Path(r'C:\Software\ComfyUI\output')
FFMPEG = r'C:\Software\ffmpeg\bin\ffmpeg.exe'
FFPROBE = r'C:\Software\ffmpeg\bin\ffprobe.exe'


def read(path):
    return json.loads(path.read_text(encoding='utf-8-sig'))


def save(path, value):
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding='utf-8')


def seed_plan(plan, scene, seed):
    if not 0 <= seed < 2**64 or not 1 <= scene <= len(plan['shots']):
        raise ValueError('Scene or seed out of range')
    if plan['shots'][scene - 1]['seed'] == seed:
        raise ValueError('Seed must differ from the baseline')
    result = deepcopy(plan)
    result['shots'][scene - 1]['seed'] = seed
    return result


def prepare(baseline, evidence, case, seed):
    manifest = read(baseline / 'manifest.json')
    scene = manifest['scene']
    original = read(baseline / 'candidate-plan.json')
    plan = seed_plan(original, scene, seed)
    graph = read(baseline / 'h3-candidate.json')
    before = deepcopy(graph)
    for node in ('24', '37', '48'):
        if json.loads(graph[node]['inputs']['plan_json']) != original:
            raise ValueError('Embedded Plan differs from baseline compiled Plan')
        graph[node]['inputs']['plan_json'] = json.dumps(plan, ensure_ascii=False)
    graph['24']['inputs']['run_name'] = case
    graph['21']['inputs']['filename'] = case
    # A structural proof of the only graph changes: Plan seed and output names.
    proof = deepcopy(graph)
    for node in ('24', '37', '48'):
        proof[node]['inputs']['plan_json'] = before[node]['inputs']['plan_json']
    proof['24']['inputs']['run_name'] = before['24']['inputs']['run_name']
    proof['21']['inputs']['filename'] = before['21']['inputs']['filename']
    if proof != before:
        raise AssertionError('Graph changed outside permitted fields')
    for node in ('7', '29'):
        if not graph[node]['inputs']['verify_resume_history']:
            raise ValueError('Predecessor verification must remain enabled')
    run = OUTPUT / 'h3_chains' / case
    if run.exists() or evidence.exists():
        raise FileExistsError('Use fresh evidence and run directories')
    source_run = Path(manifest['source_run'])
    sources = [source_run / 'checkpoints' / f'clip_{i:04d}.json' for i in range(1, scene)]
    if not all(p.is_file() for p in sources):
        raise FileNotFoundError('Original predecessor metadata missing')
    baseline_checkpoint = read(OUTPUT / 'h3_chains' / manifest['case'] / 'checkpoints' / f'clip_{scene:04d}.json')
    predecessor = read(sources[-1])
    if baseline_checkpoint['segment']['predecessor_checkpoint_sha256'] != predecessor['segment']['checkpoint_sha256']:
        raise ValueError('Baseline rendered with another predecessor')
    evidence.mkdir(parents=True)
    (run / 'checkpoints').mkdir(parents=True)
    copies = []
    for source in sources:
        dest = run / 'checkpoints' / source.name
        shutil.copy2(source, dest)
        if source.read_bytes() != dest.read_bytes():
            raise AssertionError('Predecessor metadata copy differs')
        copies.append({'source': str(source), 'copy': str(dest),
                       'sha256': hashlib.sha256(source.read_bytes()).hexdigest()})
    shutil.copy2(baseline / 'candidate.md', evidence / 'candidate.md')
    save(evidence / 'candidate-plan.json', plan)
    save(evidence / 'h3-candidate.json', graph)
    save(evidence / 'manifest.json', {
        'baseline_evidence': str(baseline), 'baseline_run': str(OUTPUT / 'h3_chains' / manifest['case']),
        'source_run': str(source_run), 'case': case, 'scene': scene,
        'old_seed': original['shots'][scene - 1]['seed'], 'seed': seed,
        'only_scene_seed_changed': True, 'prompt_reference_audio_and_predecessor_unchanged': True,
        'emd_sha256': hashlib.sha256((baseline / 'candidate.md').read_bytes()).hexdigest(),
        'predecessor_metadata': copies, 'gpu_job_not_submitted_at_preparation': True,
    })
    print(f'Prepared Scene {scene}: seed {original["shots"][scene - 1]["seed"]} -> {seed}', flush=True)


def finalize(evidence):
    manifest = read(evidence / 'manifest.json')
    scene = manifest['scene']
    run = OUTPUT / 'h3_chains' / manifest['case']
    history = read(evidence / 'render-candidate.json')
    if history['history']['status']['status_str'] != 'success':
        raise ValueError('Render failed')
    old = read(Path(manifest['baseline_run']) / 'checkpoints' / f'clip_{scene:04d}.json')
    new = read(run / 'checkpoints' / f'clip_{scene:04d}.json')
    for key in ('raw_frames', 'delivered_frames', 'steps', 'context_length',
                'audio_context_length', 'predecessor_checkpoint_sha256'):
        if old['segment'][key] != new['segment'][key]:
            raise ValueError(f'Render changed {key}')
    if old['segment']['seed'] != manifest['old_seed'] or new['segment']['seed'] != manifest['seed']:
        raise ValueError('Runtime seed does not match requested seed-only comparison')
    videos = [OUTPUT / row['segment']['segment'] for row in (old, new)]
    probes = []
    for video in videos:
        probe = json.loads(subprocess.check_output([FFPROBE, '-v', 'error', '-show_entries',
            'stream=codec_type,width,height,r_frame_rate,nb_frames,duration', '-of', 'json', str(video)], encoding='utf-8'))
        stream = next(s for s in probe['streams'] if s['codec_type'] == 'video')
        if (stream['width'], stream['height'], stream['r_frame_rate'], int(stream['nb_frames'])) != (1280, 736, '24/1', 238):
            raise ValueError('Unexpected media format')
        probes.append(probe)
    comparison = evidence / 'comparison-seeds.mp4'
    subprocess.run([FFMPEG, '-n', '-v', 'error', '-i', str(videos[0]), '-i', str(videos[1]),
        '-filter_complex',
        '[0:v]drawtext=fontfile=arial.ttf:text=Previous Seed:x=16:y=12:fontsize=32:fontcolor=white:box=1:boxcolor=black@0.7[t];'
        '[1:v]drawtext=fontfile=arial.ttf:text=New Seed:x=16:y=12:fontsize=32:fontcolor=white:box=1:boxcolor=black@0.7[b];[t][b]vstack[v]',
        '-map', '[v]', '-an', '-c:v', 'libx264', '-crf', '18', '-preset', 'fast', '-movflags', '+faststart', str(comparison)],
        cwd=r'C:\Windows\Fonts', check=True)
    wav = run / 'generated_audio' / (videos[1].stem + '.wav')
    preview = evidence / 'scene16-with-audio.mp4'
    subprocess.run([FFMPEG, '-n', '-v', 'error', '-i', str(videos[1]), '-i', str(wav),
        '-map', '0:v:0', '-map', '1:a:0', '-c:v', 'copy', '-c:a', 'aac', '-b:a', '192k',
        '-movflags', '+faststart', str(preview)], check=True)
    subprocess.run([FFMPEG, '-n', '-v', 'error', '-ss', '4.5', '-i', str(videos[1]), '-vf',
        'fps=2,scale=640:368,tile=3x2', '-frames:v', '1', str(evidence / 'candidate-4p5-7p5.png')], check=True)
    save(evidence / 'media-checks.json', {
        'videos': list(map(str, videos)), 'preview': str(preview), 'comparison': str(comparison),
        'streams': probes, 'same_predecessor_steps_dimensions_timing': True,
        'runtime_seed_verified': True, 'elapsed_s': history['elapsed_s'],
        'human_visual_verdict_pending': True,
    })
    print(json.dumps({'preview': str(preview), 'comparison': str(comparison)}, ensure_ascii=False), flush=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--baseline', type=Path)
    parser.add_argument('--evidence', type=Path, required=True)
    parser.add_argument('--case')
    parser.add_argument('--seed', type=int)
    parser.add_argument('--finalize-only', action='store_true')
    args = parser.parse_args()
    if args.finalize_only:
        finalize(args.evidence)
    else:
        if not args.baseline or args.seed is None or not args.case or not re.fullmatch(r'[a-z0-9_-]+', args.case):
            parser.error('Preparation requires baseline, uint64 seed, and safe case name')
        prepare(args.baseline, args.evidence, args.case, args.seed)


if __name__ == '__main__':
    main()
