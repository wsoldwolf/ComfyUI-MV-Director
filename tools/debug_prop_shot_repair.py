"""Scene/Shot-local LLM proposal driven by saved human render feedback.

Diagnostic only. A joint automatic holding/Performance/Camera proposal is kept
with its END_STATE; author Event, previous Shots, lyrics and mouth are immutable.
No H3 job or production integration is performed by this script.
"""
from __future__ import annotations

import argparse
from copy import deepcopy
from dataclasses import replace
import hashlib
import json
import logging
from pathlib import Path
import re
import sys
import time

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from core.artifacts import canonical_json
from core.emd import parse_emd
from core.inference import LlamaCppLifecycle, LlamaRuntimeConfig
from core.inference.budget import build_context_budget
from core.planner.prop_decision import parse_prop_decisions
from tools.debug_prop_local_review import prepare as prepare_review, save

PROMPT = ROOT / 'prompts/experimental_prop_shot_repair_system_prompt.txt'
GRAMMAR = 'root ::= "SHOT_REPAIR\\t1\\t" char+ "\\n"?\n' + r'char ::= [^\x00-\x1f]' + '\n'


def primary_fields(shot):
    return {kind: next(d.text for d in shot.directives if d.kind == kind)
            for kind in ('演技', 'カメラ')}


def prepare(saved, rendered_text, adopted_text):
    item = prepare_review(saved)[0]
    candidate, reference = parse_emd(rendered_text), parse_emd(adopted_text)
    scene = next(s for s in candidate.scenes if s.scene_number == 16)
    ref_scene = next(s for s in reference.scenes if s.scene_number == 16)
    fields = primary_fields(scene.shots[2])
    if fields['演技'] != item['input']['target']['performance']:
        raise ValueError('Rendered Performance differs from saved reviewed case')
    payload = deepcopy(item['input'])
    readonly = payload['readonly']
    plan = readonly.pop('holding_plan')
    readonly.pop('camera_response')
    payload.pop('target')
    payload['editable'] = {'performance': fields['演技'], 'camera': fields['カメラ'],
        'end_state': item['input']['target']['end_state'], 'holding_plan': plan}
    readonly['previous_shots_in_rendered_emd'] = [primary_fields(s) for s in scene.shots[:2]]
    payload['render_feedback'] = {
        'source': 'user_observation_of_actual_H3_clip',
        'text': 'アカンですね手が開いているのに剣が伸びている様に見える',
        'approximate_local_time_s': [6, 7],
        'video': 'C:/Software/ComfyUI/output/h3_chains/prop-local-review-h3-s16-20261007/segments/clip_0016.a38560a4d06f4405a4f6840290145ab4.mp4'}
    payload['successful_reference'] = {
        'source': 'same_asset_user_accepted_local_probe',
        'performance': primary_fields(ref_scene.shots[2])['演技'],
        'camera': primary_fields(ref_scene.shots[2])['カメラ'],
        'fixed_event': ' '.join(d.text for d in ref_scene.shots[2].directives if d.kind == '演出'),
        'not_a_global_template': True}
    return payload


def parse_proposal(response, prop_ids):
    lines = response.strip().splitlines()
    if len(lines) != 1:
        return None
    f = lines[0].split('\t', 2)
    if len(f) != 3 or f[:2] != ['SHOT_REPAIR', '1']:
        return None
    def unique(pairs):
        out = {}
        for k, v in pairs:
            if k in out:
                raise ValueError('Duplicate field')
            out[k] = v
        return out
    try:
        v = json.loads(f[2], object_pairs_hook=unique)
    except (ValueError, TypeError):
        return None
    if (not isinstance(v, dict) or set(v) != {'status', 'reason', 'performance', 'camera', 'end_state', 'holding_plan'}
            or v['status'] not in {'REVISE', 'UNRESOLVED'}
            or not all(isinstance(v[k], str) for k in ('reason', 'performance', 'camera', 'end_state'))
            or not v['reason'].strip()):
        return None
    if v['status'] == 'UNRESOLVED':
        return v if not any(v[k] for k in ('performance', 'camera', 'end_state', 'holding_plan')) else None
    if not all(v[k].strip() and not any(ord(c) < 32 for c in v[k])
               for k in ('performance', 'camera', 'end_state')):
        return None
    plan = parse_prop_decisions('PROP_DECISION\t1\t' + json.dumps(v['holding_plan'], ensure_ascii=False),
                               (3,), prop_ids=frozenset(prop_ids))
    return v if plan is not None else None


def replace_fields(text, proposal, *, scene_number=16, shot_number=3):
    """Assign generated fields verbatim, never rewrite their meaning in Python."""
    if proposal['status'] != 'REVISE':
        return text
    scene = shot = 0
    found = set()
    lines = []
    for line in text.splitlines(keepends=True):
        m = re.match(r'> `シーン` (\d+)\s*$', line)
        if m:
            scene, shot = int(m[1]), 0
        if line.startswith('## ショット '):
            shot += 1
        if (scene, shot) == (scene_number, shot_number):
            for kind, key in (('演技', 'performance'), ('カメラ', 'camera')):
                if line.startswith('* `' + kind + '` ') and kind not in found:
                    line = '* `' + kind + '` ' + proposal[key] + '\n'
                    found.add(kind)
                    break
        lines.append(line)
    if found != {'演技', 'カメラ'}:
        raise ValueError('Target primary fields absent')
    result = ''.join(lines)
    before, after = parse_emd(text), parse_emd(result)
    if replace(before, scenes=after.scenes) != after:
        raise AssertionError('Document fields changed')
    if len(before.scenes) != len(after.scenes):
        raise AssertionError('Scene count changed')
    for a, b in zip(before.scenes, after.scenes):
        if replace(a, shots=b.shots) != b or len(a.shots) != len(b.shots):
            raise AssertionError('Scene metadata changed')
        for i, (old, new) in enumerate(zip(a.shots, b.shots), 1):
            if (a.scene_number, i) != (scene_number, shot_number):
                if old != new:
                    raise AssertionError('Other Shot changed')
            elif replace_fields_noneditable(old) != replace_fields_noneditable(new):
                raise AssertionError('Target fixed fields changed')
    return result


def replace_fields_noneditable(shot):
    return replace(shot,
        body=tuple(t for t in shot.body if not t.startswith(('`演技` ', '`カメラ` '))),
        directives=tuple(d for d in shot.directives if d.kind not in ('演技', 'カメラ')))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--saved', type=Path, required=True)
    parser.add_argument('--rendered-emd', type=Path, required=True)
    parser.add_argument('--adopted-emd', type=Path, required=True)
    parser.add_argument('--model', type=Path, required=True)
    parser.add_argument('--out', type=Path, required=True)
    parser.add_argument('--infer', action='store_true')
    args = parser.parse_args()
    if args.out.exists():
        raise FileExistsError('Use a fresh evidence directory')
    text = args.rendered_emd.read_text(encoding='utf-8-sig')
    payload = prepare(json.loads((args.saved / 'calls.json').read_text(encoding='utf-8')),
                      text, args.adopted_emd.read_text(encoding='utf-8-sig'))
    prompt = PROMPT.read_text(encoding='utf-8')
    config = LlamaRuntimeConfig(n_ctx=16384, n_batch=256, max_tokens=1536,
                               temperature=0.2, seed=20261007)
    args.out.mkdir(parents=True)
    save(args.out / 'input.json', payload)
    save(args.out / 'conditions.json', {'model': str(args.model), 'runtime': config.to_dict(),
        'source_emd': str(args.rendered_emd), 'source_sha256': hashlib.sha256(text.encode()).hexdigest(),
        'reference_emd': str(args.adopted_emd), 'gpu_authorized': args.infer,
        'production_integrated': False, 'video_seen_by_llm': False, 'only_editable_shot': [16, 3]})
    (args.out / 'system-prompt.txt').write_text(prompt, encoding='utf-8')
    if not args.infer:
        return
    logging.basicConfig(level=logging.INFO, format='%(asctime)s %(message)s',
        handlers=[logging.StreamHandler(sys.stdout),
                  logging.FileHandler(args.out / 'inference.log', encoding='utf-8')])
    lifecycle = LlamaCppLifecycle()
    attempts = []
    proposal = None
    try:
        started = time.perf_counter()
        logging.info('GPU loading starts')
        lifecycle.ensure_loaded(args.model, config)
        load_s = time.perf_counter() - started
        data = canonical_json(payload)
        count = lifecycle.count_serialized_prompt(prompt + '\n/no_think\n' + data)
        budget = build_context_budget(count.count, config.max_tokens,
            lifecycle.effective_n_ctx or config.n_ctx, estimated=count.estimated)
        started = time.perf_counter()
        for attempt in range(2):
            seed = int.from_bytes(hashlib.sha256((data + str(attempt)).encode()).digest()[:4], 'big') & 0x7fffffff
            logging.info('Repair starts; attempt=%d; input_tokens=%d', attempt + 1, count.count)
            response = lifecycle.complete_chat([{'role': 'system', 'content': prompt},
                {'role': 'user', 'content': '/no_think\n' + data}], replace(config, seed=seed), grammar=GRAMMAR)
            attempts.append({'seed': seed, 'response': response})
            save(args.out / 'calls.json', attempts)
            proposal = parse_proposal(response, {p['id'] for p in payload['readonly']['prop_inventory']})
            if proposal is not None:
                break
        save(args.out / 'result.json', {'proposal': proposal, 'load_s': load_s,
            'inference_s': time.perf_counter() - started, 'input_tokens': count.count,
            'required_tokens': budget.required_tokens})
        if proposal is None:
            logging.warning('Invalid response retained; no EMD generated')
            return
        if proposal['status'] == 'UNRESOLVED':
            logging.warning('Fixed Event unresolved; no EMD generated')
            return
        candidate = replace_fields(text, proposal)
        (args.out / 'candidate-emd.md').write_text(candidate, encoding='utf-8')
        save(args.out / 'state-handoff.json', {'scene': 16, 'shot': 3,
            'accepted_prop_decision': proposal['holding_plan'],
            'performance_end_state': proposal['end_state'],
            'camera_from_same_joint_proposal': proposal['camera'],
            'next_scene_generation_not_performed': True})
        logging.info('Joint proposal saved; only Scene 16 Shot 3 primary Performance/Camera changed')
    finally:
        lifecycle.clear()
        logging.info('Owned GPU model unloaded')


if __name__ == '__main__':
    main()
