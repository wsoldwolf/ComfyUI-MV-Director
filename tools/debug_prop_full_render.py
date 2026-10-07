"""Render the adopted full Plan without replanning or importing checkpoints.

This diagnostic owns its server, records the single submission, and survives
the calling terminal. It never interrupts unrelated processes or queued jobs.
"""
from __future__ import annotations

import argparse
from copy import deepcopy
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import re
import shutil
import subprocess
import time
from urllib.request import Request, urlopen

COMFY = Path(r'C:\Software\ComfyUI')
PYTHON = COMFY / 'venv/Scripts/python.exe'
FFPROBE = r'C:\Software\ffmpeg\bin\ffprobe.exe'


def read(path):
    return json.loads(path.read_text(encoding='utf-8-sig'))


def save(path, value):
    # A temporary sibling prevents a reader from seeing half a status document.
    temporary = path.with_suffix(path.suffix + '.tmp')
    temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding='utf-8')
    temporary.replace(path)


def stamp():
    return datetime.now(timezone.utc).isoformat()


def digest(path):
    with path.open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def full_graph(source, plan, case):
    if not re.fullmatch(r'[a-z0-9_-]+', case):
        raise ValueError('Unsafe case name')
    graph = deepcopy(source)
    for node in ('24', '37', '48'):
        if json.loads(graph[node]['inputs']['plan_json']) != plan:
            raise ValueError(f'Node {node} does not contain the adopted Plan')
    graph['24']['inputs'].update(run_name=case, default_steps=20)
    graph['21']['inputs']['filename'] = case
    for node in ('7', '29'):
        graph[node]['inputs'].update(start_clip=1, scene_range='', verify_resume_history=True)
    if graph['48']['inputs']['enable']:
        raise ValueError('Debug splitter must already be disabled')
    if graph['47']['inputs']['megapixels'] != 0.9:
        raise ValueError('Adopted graph must already be 0.9 MP')
    if graph['28']['inputs']['enabled'] or graph['40']['inputs']['voice'] != ['48', 1]:
        raise ValueError('Review or standard lip-sync configuration differs')
    if any('spectrum' in n['class_type'].lower() for n in graph.values()):
        raise ValueError('Spectrum must remain bypassed')
    if any('lora' in n['class_type'].lower() for n in graph.values()):
        raise ValueError('Turbo LoRA must remain bypassed')
    if any(s.get('steps', 20) != 20 for s in plan['shots']):
        raise ValueError('Per-Scene steps override the full-test setting')
    return graph


def prepare(source, evidence, case):
    if evidence.exists() or (COMFY / 'output/h3_chains' / case).exists():
        raise FileExistsError('Use a fresh full-test case; no outputs overwritten')
    plan = read(source / 'candidate-plan.json')
    graph = full_graph(read(source / 'h3-candidate.json'), plan, case)
    assets = []
    for node, field in (('26', 'image'), ('45', 'image'), ('32', 'audio'), ('33', 'audio')):
        path = (COMFY / 'input' / graph[node]['inputs'][field]).resolve(strict=True)
        if not path.is_relative_to((COMFY / 'input').resolve()):
            raise ValueError('Source asset escapes the input directory')
        assets.append({'node': node, 'path': str(path), 'sha256': digest(path), 'bytes': path.stat().st_size})
    evidence.mkdir(parents=True)
    for name in ('candidate-plan.json', 'candidate-emd.md', 'translation.json'):
        shutil.copy2(source / name, evidence / name)
    save(evidence / 'h3-candidate.json', graph)
    save(evidence / 'conditions.json', {
        'case': case, 'source_evidence': str(source), 'source_plan_sha256': digest(source / 'candidate-plan.json'),
        'scope': 'full H3 render of adopted Plan; no new Planner or Compiler inference',
        'scenes': len(plan['shots']), 'expected_frames': sum(s['length']-s.get('context_length', 0) for s in plan['shots']),
        'fps': 24, 'width': 1280, 'height': 736, 'megapixels': 0.9, 'steps': 20,
        'fresh_from_scene1': True, 'imported_checkpoints': [], 'standard_context_loop_lip_sync': True,
        'spectrum': False, 'turbo_lora': False, 'review_gate': False,
        'adopted_scene16_seed': plan['shots'][15]['seed'], 'assets': assets, 'prepared_at': stamp(),
        'server_flags': ['--listen', '127.0.0.1', '--port', '8191', '--disable-auto-launch', '--enable-manager'],
        'human_visual_verdict_pending': True,
    })
    print(f'Prepared {len(plan["shots"])} Scenes without changing prompts/seeds', flush=True)


def api(url, suffix, data=None):
    request = Request(url + suffix, data=None if data is None else json.dumps(data).encode(),
                      headers={'Content-Type': 'application/json'})
    with urlopen(request, timeout=45) as response:
        return json.load(response)


def validate_media(evidence):
    conditions, plan = read(evidence / 'conditions.json'), read(evidence / 'candidate-plan.json')
    run = COMFY / 'output/h3_chains' / conditions['case']
    previous_hash, total_frames, rows = None, 0, []
    for scene, shot in enumerate(plan['shots'], 1):
        metadata = read(run / 'checkpoints' / f'clip_{scene:04d}.json')
        segment, compatibility = metadata['segment'], metadata['compatibility']
        if metadata['run_name'] != conditions['case']:
            raise ValueError('A checkpoint from another run was imported')
        if segment['steps'] != 20 or segment['seed'] != shot['seed']:
            raise ValueError(f'Scene {scene}: runtime steps/seed differs')
        if (compatibility['width'], compatibility['height'], compatibility['fps']) != (1280, 736, 24):
            raise ValueError(f'Scene {scene}: resolution/fps differs')
        if (shot.get('context_length', 0) or shot.get('audio_context_length', 0)) and scene > 1:
            if segment.get('predecessor_checkpoint_sha256') != previous_hash:
                raise ValueError(f'Scene {scene}: fresh predecessor lineage differs')
        previous_hash = segment['checkpoint_sha256']
        total_frames += segment['delivered_frames']
        rows.append({'scene': scene, 'delivered_frames': segment['delivered_frames'], 'seed': segment['seed'],
                     'segment': segment['segment'], 'checkpoint_sha256': previous_hash})
    final = run / 'final' / (conditions['case'] + '.mp4')
    probe = json.loads(subprocess.check_output([FFPROBE, '-v', 'error', '-show_streams', '-show_format',
                                                '-of', 'json', str(final)], encoding='utf-8'))
    video = next(s for s in probe['streams'] if s['codec_type'] == 'video')
    audio = [s for s in probe['streams'] if s['codec_type'] == 'audio']
    if (video['width'], video['height'], video['r_frame_rate']) != (1280, 736, '24/1') or not audio:
        raise ValueError('Final format/audio differs')
    if total_frames != conditions['expected_frames'] or int(video['nb_frames']) != total_frames:
        raise ValueError('Final delivered frame count differs')
    save(evidence / 'media-checks.json', {'final': str(final), 'probe': probe, 'scenes': rows,
        'expected_frames': total_frames, 'all_fresh_checkpoints_verified': True, 'human_visual_verdict_pending': True})
    return str(final)


def run(evidence):
    conditions = read(evidence / 'conditions.json')
    url = 'http://127.0.0.1:8191'
    if (evidence / 'submission-candidate.json').exists():
        raise FileExistsError('Submission already exists; never duplicate an uncertain job')
    try:
        api(url, '/queue')
    except OSError:
        pass
    else:
        raise RuntimeError('Port 8191 already serves a process; left untouched')
    for asset in conditions['assets']:
        if digest(Path(asset['path'])) != asset['sha256']:
            raise ValueError('Reference/audio changed since preparation')
    start = time.monotonic()
    state = {'status': 'starting_server', 'started_at': stamp(), 'case': conditions['case'], 'completed_scenes': []}
    server = None
    with (evidence / 'server-stdout.log').open('w', encoding='utf-8') as stdout, \
         (evidence / 'server-stderr.log').open('w', encoding='utf-8') as stderr:
        try:
            server = subprocess.Popen([str(PYTHON), '-s', 'main.py', *conditions['server_flags']],
                cwd=COMFY, stdout=stdout, stderr=stderr, creationflags=subprocess.CREATE_NO_WINDOW)
            state['owned_server_pid'] = server.pid
            save(evidence / 'status.json', state)
            for _ in range(180):
                if server.poll() is not None:
                    raise RuntimeError('Owned server exited during startup')
                try:
                    queue = api(url, '/queue')
                    break
                except OSError:
                    time.sleep(2)
            else:
                raise TimeoutError('Server startup timeout; see logs')
            if queue['queue_running'] or queue['queue_pending']:
                raise RuntimeError('Server has an existing job; left untouched')
            submission = api(url, '/prompt', {'prompt': read(evidence / 'h3-candidate.json')})
            save(evidence / 'submission-candidate.json', submission)
            state.update(status='rendering', prompt_id=submission['prompt_id'])
            run_dir = COMFY / 'output/h3_chains' / conditions['case']
            while time.monotonic() - start < 36 * 3600:
                state.update(updated_at=stamp(), elapsed_s=round(time.monotonic() - start, 1),
                    completed_scenes=[s for s in range(1, conditions['scenes'] + 1)
                        if (run_dir / 'checkpoints' / f'clip_{s:04d}.json').exists()])
                save(evidence / 'status.json', state)
                history = api(url, '/history/' + submission['prompt_id'])
                if submission['prompt_id'] in history:
                    item = history[submission['prompt_id']]
                    save(evidence / 'render-candidate.json', {'history': item, 'elapsed_s': state['elapsed_s']})
                    if item['status']['status_str'] != 'success':
                        raise RuntimeError('Full render failed; inspect saved history')
                    state.update(status='success', final=validate_media(evidence), completed_at=stamp())
                    break
                if server.poll() is not None:
                    raise RuntimeError('Owned server exited before history completion')
                time.sleep(20)
            else:
                raise TimeoutError('Observation limit; server/job left intact')
        except Exception as error:
            state.update(status='error', error=f'{type(error).__name__}: {error}', updated_at=stamp())
            raise
        finally:
            # Only our exact child process may be stopped, and only after a
            # finished job or a startup failure with an explicitly empty queue.
            if server is not None and server.poll() is None:
                try:
                    queue = api(url, '/queue')
                    if not queue['queue_running'] and not queue['queue_pending']:
                        server.terminate()
                        server.wait(timeout=30)
                        state['owned_server_released'] = True
                except (OSError, subprocess.TimeoutExpired):
                    state['owned_server_released'] = False
            state['elapsed_s'] = round(time.monotonic() - start, 1)
            save(evidence / 'status.json', state)
            print(json.dumps(state, ensure_ascii=False), flush=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--mode', choices=('prepare', 'run'), required=True)
    parser.add_argument('--source', type=Path)
    parser.add_argument('--evidence', type=Path, required=True)
    parser.add_argument('--case')
    args = parser.parse_args()
    if args.mode == 'prepare':
        if not args.source or not args.case:
            parser.error('prepare requires source and case')
        prepare(args.source, args.evidence, args.case)
    else:
        run(args.evidence)


if __name__ == '__main__':
    main()
