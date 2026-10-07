"""CPU-only preparation of a production Planner replay; no model is loaded.

Completed EMD has no explicit absent-Event marker. Selected absent Events get
`演出` なし transport markers, recorded separately for removal before H3.
This tool reopens explicitly named diagnostic fields, never guesses ownership.
"""
import argparse
import base64
from dataclasses import asdict
import hashlib
import json
from pathlib import Path
import re
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from core.artifacts import DirectionArtifact
from core.emd import parse_emd
from core.inference import LlamaRuntimeConfig
from core.planner import plan_timeline
from core.planner.template import parse_template_emd
from nodes.node_timeline_planner.node import _system_prompts


def semantic(value):
    if hasattr(value, '__dataclass_fields__'):
        value = asdict(value)
    if isinstance(value, dict):
        return {k: semantic(v) for k, v in value.items() if k != 'line_number'}
    if isinstance(value, (tuple, list)):
        return [semantic(v) for v in value]
    return value


def prepare(text, selected=(15, 16, 17)):
    doc = parse_emd(text)
    if not selected or not set(selected).issubset(s.scene_number for s in doc.scenes):
        raise ValueError('all selected Scenes must exist')
    boundary = (selected[0], 1)
    match = re.search(r'(?m)^> `シーン` \d+', text)
    if not match:
        raise ValueError('no Scene section')
    prefix = text[:match.start()]
    concept = re.split(r'(?m)^# (?!サブジェクト)', prefix, maxsplit=1)[0].strip() + '\n'
    setting = re.search(r'(?ms)^# シーン設定\n.*?(?=^# |\Z)', prefix)
    scene_emd = setting.group().strip() + '\n' if setting else ''
    activity = re.search(r'(?ms)^# 音声活動\n.*?(?=^# |\Z)', prefix)
    lines = activity.group().rstrip().splitlines() if activity else []
    events = {(s.scene_number, i): any(d.kind == '演出' for d in sh.directives)
              for s in doc.scenes for i, sh in enumerate(s.shots, 1)}
    markers, reopened, removed = [], [], []
    scene = shot = 0
    audio = False
    for line in text[match.start():].splitlines():
        sm = re.fullmatch(r'> `シーン` (\d+)', line)
        if sm:
            scene, shot, audio = int(sm.group(1)), 0, False
        if line.startswith('## 音響'):
            audio = True
            continue
        if audio:
            continue
        if line.startswith('## ショット '):
            shot += 1
            lines.append(line)
            key = (scene, shot)
            if scene in selected and key != boundary:
                reopened.append(key)
                if not events[key]:
                    lines.append('* `演出` なし')
                    markers.append(key)
            continue
        if line.startswith('> `モーション補完`'):
            removed.append({'scene': scene, 'shot': shot, 'line': line})
            continue
        if scene in selected and (scene, shot) != boundary and (
            line.startswith('* `演技` ') or line.startswith('* `カメラ` ')
        ):
            removed.append({'scene': scene, 'shot': shot, 'line': line})
            continue
        lines.append(line)
    template = '\n'.join(lines).strip() + '\n'
    parsed = parse_template_emd(template)
    common = doc.common_prompt_dict()
    # Prose can be recovered, original Enhancer provenance cannot. Policy below
    # is explicitly selected for this replay, not claimed as original evidence.
    direction = DirectionArtifact(
        style_direction=common.get('スタイル', ()),
        environment_direction=common.get('環境', ()),
        time_lighting_direction=common.get('時間・照明', ()),
        motion_direction=common.get('モーション', ()),
        camera_direction=common.get('カメラ', ()),
        other_direction=common.get('その他', ()),
        motion_profile_id='anime_scene_composed_mv', camera_profile_id='anime_emotional_mv',
        staging_candidates=(),
    )
    direction.validate()
    originals = {s.scene_number: s for s in doc.scenes}
    for s in parsed.scenes:
        old = originals[s.scene_number]
        assert (s.start_ms, s.end_ms, s.h3_length, s.continuation) == (
            old.start_ms, old.end_ms, old.h3_length, old.continuation)
        assert semantic(s.mouth_performances) == semantic(old.mouth_performances)
        for i, sh in enumerate(s.shots, 1):
            original = old.shots[i - 1]
            assert semantic(sh.lyric_annotations) == semantic(original.lyric_annotations)
            if (s.scene_number, i) not in reopened:
                assert sh.body == original.body
            else:
                assert not any(d.kind in {'演技', 'カメラ'} for d in sh.directives)
    assert semantic(parsed.audio_activity) == semantic(doc.audio_activity)
    return dict(concept_emd=concept, scene_emd=scene_emd, template_emd=template,
                direction=direction.to_dict(), selected_scenes=list(selected),
                boundary=list(boundary), reopened_shots=[list(k) for k in reopened],
                no_event_transport_markers=[list(k) for k in markers], removed_lines=removed,
                original_direction_provenance_recovered=False, staging_candidates_replayed=False,
                composition_timing='post_author', full_song_context_retained=True)


class ContractBackend:
    """Synthetic transport only, not LLM output or semantic certification."""
    def __init__(self):
        self.calls = []

    def complete_planner(self, *, task, payload, system_prompt, **kwargs):
        p = json.loads(payload)
        self.calls.append(dict(task=task, payload=p, system_prompt=system_prompt))
        if task == 'subject-prop-inventory':
            props = [dict(id='P1', subject='サブジェクト1', label='白い盾',
                          evidence='赤い楓葉が描かれた白い盾', initial_state='左手'),
                     dict(id='P2', subject='サブジェクト1', label='日本刀',
                          evidence='日本刀', initial_state='右手')]
            return 'PROP_INVENTORY\t1\t' + json.dumps({'props': props}, ensure_ascii=False)
        if task == 'scene-author-prop-decision':
            decision = dict(prop_locations={'P1': '左手', 'P2': '右手'}, right_hand='刀を握る',
                            left_hand='盾を保持する', transition='保持を継続する',
                            performance_scope='体幹と腕を動かす', end_state={'P1': '左手', 'P2': '右手'})
            return '\n'.join('PROP_DECISION\t' + str(s['slot']) + '\t' +
                             json.dumps(decision, ensure_ascii=False) for s in p['slots'])
        if task == 'scene-author-composition-choice':
            return 'CHOICE\t1\t' + str(p['current_choice'])
        if task == 'scene-author-event':
            raise AssertionError('Fixed Event replay must not infer Events')
        kind, prose, end = {
            'scene-author-performance': ('PERFORMANCE', '刀と盾を保持して体幹を起こす。', '刀は右手、盾は左手。'),
            'scene-author-camera': ('CAMERA', '時計回りのArc Shotで上半身を捉える。', '時計回り、斜め正面。'),
        }[task]
        return '\n'.join(f"{kind}\t{s['slot']}\t{prose}｜END_STATE={end}" for s in p['slots'])


def contract_run(inputs):
    backend = ContractBackend()
    result = plan_timeline(backend, template_emd=inputs['template_emd'],
        concept_emd=inputs['concept_emd'], scene_emd=inputs['scene_emd'],
        direction=DirectionArtifact.from_dict(inputs['direction']), lip_sync_mode='context_loop',
        lip_sync_target='サブジェクト1', lip_sync_audio_slot=1,
        system_prompts=_system_prompts(prop_holding=True),
        runtime_config=LlamaRuntimeConfig(max_tokens=1536, n_ctx=16384, n_batch=256, seed=20261007))
    assert result.complete
    assert sum(c['task'] == 'subject-prop-inventory' for c in backend.calls) == 1
    for c in backend.calls:
        if c['task'] != 'subject-prop-inventory':
            assert c['payload'].get('scene_number', c['payload'].get('scene')) in inputs['selected_scenes']
        if c['task'] in {'scene-author-performance', 'scene-author-camera'}:
            assert len(c['payload']['prop_inventory']) == 2
            assert 'accepted_prop_decisions' in c['payload']
            assert 'scheduled_motion_composition' not in c['payload']
    return result, backend.calls


def remove_transport_markers(text, markers):
    """Remove only recorded absent-Event markers, not author-owned prose."""
    expected = {tuple(k) for k in markers}
    seen = set()
    lines = []
    scene = shot = 0
    for line in text.splitlines(keepends=True):
        sm = re.fullmatch(r'> `シーン` (\d+)\s*', line)
        if sm:
            scene, shot = int(sm.group(1)), 0
        if line.startswith('## ショット '):
            shot += 1
        if (scene, shot) in expected and line.rstrip('\r\n') == '* `演出` なし':
            if (scene, shot) in seen:
                raise ValueError('duplicate transport marker')
            seen.add((scene, shot))
            continue
        lines.append(line)
    if seen != expected:
        raise ValueError('recorded transport markers missing')
    result = ''.join(lines)
    parse_emd(result)
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for key in ('source-emd', 'source-run', 'out'):
        parser.add_argument('--' + key, type=Path, required=True)
    args = parser.parse_args()
    if args.out.exists():
        raise FileExistsError('Use a new evidence directory; do not overwrite old results')
    text = args.source_emd.read_text(encoding='utf-8-sig')
    inputs = prepare(text)
    result, calls = contract_run(inputs)
    graph_path = args.source_run / 'api_prompt.json'
    graph = json.loads(graph_path.read_text(encoding='utf-8-sig'))
    plan_bytes = base64.b64decode(graph['39']['inputs']['file_data_base64'], validate=True)
    plan = json.loads(plan_bytes.decode('utf-8-sig'))
    checkpoint = args.source_run / 'checkpoints' / 'clip_0015.json'
    sha = lambda p: hashlib.sha256(p.read_bytes()).hexdigest()
    manifest = dict(stage='P4_CPU_ONLY', gpu_used=False, model_loaded=False,
        contract_output_is_synthetic=True, source_emd=str(args.source_emd), source_emd_sha256=sha(args.source_emd),
        source_api_prompt=str(graph_path), source_api_prompt_sha256=sha(graph_path),
        source_plan_sha256=hashlib.sha256(plan_bytes).hexdigest(), source_plan_scenes=len(plan['shots']),
        scene15_checkpoint=str(checkpoint), scene15_checkpoint_sha256=sha(checkpoint),
        tasks=[c['task'] for c in calls],
        comparison_h3=dict(width=1280, height=736, steps=20, scene16_seed=17507335375349101561))
    args.out.mkdir(parents=True)
    for name, data in {'inputs.json': inputs, 'manifest.json': manifest, 'synthetic-contract-calls.json': calls}.items():
        (args.out / name).write_text(json.dumps(data, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    for name, data in {'source-emd.md': text, 'template-emd.md': inputs['template_emd'],
                       'synthetic-contract-output.md': result.emd.text}.items():
        (args.out / name).write_text(data, encoding='utf-8')
    (args.out / 'source-plan.txt').write_bytes(plan_bytes)
    for key, value in _system_prompts(prop_holding=True).items():
        (args.out / (key + '-system.txt')).write_text(value, encoding='utf-8')
    print(json.dumps(manifest, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()
