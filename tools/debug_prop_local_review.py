"""Opt-in bounded holding review, never a production author stage.

Builds one saved Scene 16 case and explicitly synthetic controls. Only automatic
Performance and END_STATE can change. No Compiler, Camera authoring, EMD patch,
workflow edit, H3 submission, or commit is performed.
"""
from __future__ import annotations

import argparse
from copy import deepcopy
from dataclasses import replace
import hashlib
import json
import logging
from pathlib import Path
import sys
import time

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from core.artifacts import canonical_json
from core.inference import LlamaCppLifecycle, LlamaRuntimeConfig
from core.inference.budget import build_context_budget
from core.planner.scene_author import _split_terminal_state

PROMPT = ROOT / 'prompts/experimental_prop_local_review_system_prompt.txt'
GRAMMAR = 'root ::= "HOLDING_REVIEW\\t1\\t" char+ "\\n"?\n' + r'char ::= [^\x00-\x1f]' + '\n'


def save(path, value):
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')


def eligible(case):
    return (case['ownership'] == 'automatic'
            and bool(case['input']['readonly']['prop_inventory'])
            and bool(case['input']['readonly']['holding_plan']))


def parse_review(response):
    lines = response.strip().splitlines()
    if len(lines) != 1:
        return None
    fields = lines[0].split('\t', 2)
    if len(fields) != 3 or fields[:2] != ['HOLDING_REVIEW', '1']:
        return None
    def unique(pairs):
        out = {}
        for k, v in pairs:
            if k in out:
                raise ValueError('duplicate field')
            out[k] = v
        return out
    try:
        value = json.loads(fields[2], object_pairs_hook=unique)
    except (ValueError, TypeError):
        return None
    if (not isinstance(value, dict)
            or set(value) != {'status', 'reason', 'performance', 'end_state'}
            or not all(isinstance(v, str) for v in value.values())
            or value['status'] not in {'KEEP', 'REVISE', 'UNRESOLVED'}
            or not value['reason'].strip()):
        return None
    changed = bool(value['performance'].strip()) and bool(value['end_state'].strip())
    if value['status'] == 'REVISE':
        if not changed:
            return None
    elif value['performance'] or value['end_state']:
        return None
    return value


def apply_review(case, verdict):
    """Enforce field ownership only; no semantic prose repair or quality gate."""
    result = deepcopy(case['input'])
    if eligible(case) and verdict and verdict['status'] == 'REVISE':
        result['target'] = {k: verdict[k] for k in ('performance', 'end_state')}
    if result['readonly'] != case['input']['readonly']:
        raise AssertionError('Readonly context changed')
    return result


def synthetic_case(name, props, plan, event, performance, state, *, lyrics=''):
    return {'name': name, 'provenance': 'synthetic_control', 'ownership': 'automatic',
            'input': {'target': {'performance': performance, 'end_state': state},
                      'readonly': {'prop_inventory': props, 'holding_plan': plan,
                                   'fixed_event': event, 'lyrics': lyrics,
                                   'camera': '人物の上半身と両腕を映す。',
                                   'mouth': '自由', 'duration_ms': 3000}}}


def prepare(calls):
    c = next(c for c in calls if c['task'] == 'scene-author-performance'
             and c['payload']['scene_number'] == 16)
    p = c['payload']
    performances = {}
    for line in c['response'].splitlines():
        kind, slot, text = line.split('\t', 2)
        if kind != 'PERFORMANCE':
            raise ValueError('Unexpected saved response')
        body, state = _split_terminal_state(text)
        performances[slot] = {'performance': body, 'end_state': state}
    camera_call = next(c for c in calls if c['task'] == 'scene-author-camera'
                       and c['payload']['scene_number'] == 16)
    actual = {'name': 'scene16_shot3_saved', 'provenance': 'saved_P5_actual_31B',
              'ownership': 'automatic', 'input': {
                  'target': deepcopy(performances['3']),
                  'readonly': {'prop_inventory': p['prop_inventory'],
                               'holding_plan': p['accepted_prop_decisions']['3'],
                               'fixed_event': p['accepted_events_by_shot']['3'],
                               'event_source': p['event_sources_by_shot']['3'],
                               'original_lyrics': p['original_lyrics'],
                               'section_lyric_context': p['section_lyric_context'],
                               'previous_performances': {k: v for k, v in performances.items() if k != '3'},
                               'camera_response': camera_call['response'],
                               'mouth_performance': p['mouth_performance'],
                               'shot_position': p['shot_positions'][2],
                               'scene_environment': p['scene_environment']}}}
    umbrella = [{'id': 'P1', 'label': '傘', 'initial_state': '右手で保持'}]
    cup = [{'id': 'P1', 'label': 'マグカップ', 'initial_state': '右手で保持'}]
    flowers = [{'id': 'P1', 'label': '花束', 'initial_state': '左手で保持'}]
    cases = [actual,
             synthetic_case('free_left_hand', umbrella,
                            {'right_hand': '傘を握り続ける', 'left_hand': '自由', 'transition': 'なし'},
                            '人物が左の掌を差し出す。',
                            '傘を右手で保持したまま、左手を開いて前へ差し出し、穏やかに微笑む。',
                            '右手傘保持・左掌前方・穏やかな表情'),
             synthetic_case('compatible_cup', cup,
                            {'right_hand': 'カップを握り続ける', 'left_hand': '自由', 'transition': 'なし'},
                            '人物がカップを胸元へ引き寄せる。',
                            '右手でカップを握ったまま胸元へ運び、肩を緩めて一息つく。',
                            '右手カップ保持・肩の力を抜く'),
             synthetic_case('conflicting_bouquet', flowers,
                            {'right_hand': '自由', 'left_hand': '花束を握り続ける', 'transition': 'なし'},
                            '人物が胸に手を添えて想いを伝える。',
                            '花束を左手に握ったまま、同じ左手の指を広げ、空の掌を胸に当てて微笑む。右腕は体側へ下ろす。',
                            '左手花束保持・左掌胸元・右腕体側・微笑む'),
             synthetic_case('unknown_hand', [{'id': 'P1', 'label': '扇子', 'initial_state': '未確定'}],
                            {'right_hand': '未確定', 'left_hand': '未確定', 'transition': '未確定'},
                            '人物が片手を差し出す。',
                            '片手を開いて差し出し、もう片方の手に扇子を持ちながら相手を見る。',
                            '片手前方・反対の手に扇子・視線相手')]
    fixed = deepcopy(actual)
    fixed.update(name='author_fixed_performance', ownership='author',
                 provenance='synthetic_ownership_control_on_saved_text')
    empty = synthetic_case('no_props', [], {}, '人物が両手を開く。',
                           '両手を開き、胸を張って晴れやかに微笑む。', '両手開き・胸を張る')
    blocked = synthetic_case('fixed_event_conflict', cup,
        {'right_hand': 'カップを握り続ける', 'left_hand': '自由', 'transition': 'なし'},
        '人物が右手の指をすべて開き、物を持たない右の掌を見せる。',
        'カップを右手で握ったまま、同じ右手の指をすべて開き、空の右掌を見せて微笑む。',
        '右手カップ保持・右掌空で開く・微笑む')
    cases.extend([fixed, empty, blocked])
    return cases


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--saved', type=Path, required=True)
    parser.add_argument('--model', type=Path, required=True)
    parser.add_argument('--out', type=Path, required=True)
    parser.add_argument('--infer', action='store_true', help='Explicit GPU opt-in')
    parser.add_argument('--case', action='append', dest='selected_cases',
                        help='Run only explicitly named cases; repeat for a subset')
    args = parser.parse_args()
    if args.out.exists():
        raise FileExistsError('Use a fresh evidence directory')
    calls_path = args.saved / 'calls.json'
    cases = prepare(json.loads(calls_path.read_text(encoding='utf-8')))
    if args.selected_cases:
        selected = set(args.selected_cases)
        if selected - {c['name'] for c in cases}:
            raise ValueError('Unknown case name')
        cases = [c for c in cases if c['name'] in selected]
    prompt = PROMPT.read_text(encoding='utf-8')
    args.out.mkdir(parents=True)
    config = LlamaRuntimeConfig(n_ctx=16384, n_batch=256, max_tokens=768,
                               temperature=0.2, seed=20261007)
    save(args.out / 'conditions.json', {'source': str(calls_path),
         'source_sha256': hashlib.sha256(calls_path.read_bytes()).hexdigest(),
         'model': str(args.model), 'runtime': config.to_dict(), 'gpu_authorized': args.infer,
         'production_integrated': False, 'h3_generated': False,
         'seed_policy': 'stable_case_payload_sha256', 'transport_attempts_max': 2})
    save(args.out / 'cases.json', cases)
    (args.out / 'system-prompt.txt').write_text(prompt, encoding='utf-8')
    if not args.infer:
        return
    logging.basicConfig(level=logging.INFO, format='%(asctime)s %(message)s',
        handlers=[logging.StreamHandler(sys.stdout),
                  logging.FileHandler(args.out / 'inference.log', encoding='utf-8')])
    lifecycle = LlamaCppLifecycle()
    results = []
    try:
        started = time.perf_counter()
        logging.info('GPU model loading starts')
        lifecycle.ensure_loaded(args.model, config)
        save(args.out / 'load.json', {'load_s': time.perf_counter() - started})
        for case in cases:
            started = time.perf_counter()
            entry = {'name': case['name'], 'provenance': case['provenance'], 'calls': []}
            verdict = None
            if eligible(case):
                payload = canonical_json(case['input'])
                messages = [{'role': 'system', 'content': prompt},
                            {'role': 'user', 'content': '/no_think\n' + payload}]
                count = lifecycle.count_serialized_prompt(prompt + '\n/no_think\n' + payload)
                budget = build_context_budget(count.count, config.max_tokens,
                    lifecycle.effective_n_ctx or config.n_ctx, estimated=count.estimated)
                entry['input_tokens'] = count.count
                entry['required_tokens'] = budget.required_tokens
                for attempt in range(2):
                    seed = int.from_bytes(hashlib.sha256((payload + str(attempt)).encode()).digest()[:4], 'big') & 0x7fffffff
                    logging.info('Review starts; case=%s; attempt=%d; tokens=%d', case['name'], attempt + 1, count.count)
                    try:
                        response = lifecycle.complete_chat(messages, replace(config, seed=seed), grammar=GRAMMAR)
                        entry['calls'].append({'seed': seed, 'response': response})
                        verdict = parse_review(response)
                    except Exception as exc:
                        entry['calls'].append({'seed': seed, 'error': repr(exc)})
                    if verdict is not None:
                        break
                entry['status'] = verdict['status'] if verdict else 'invalid_transport_retained'
            else:
                entry['status'] = 'skip_author' if case['ownership'] == 'author' else 'skip_no_props'
            entry['verdict'] = verdict
            entry['output'] = apply_review(case, verdict)
            entry['target_changed'] = entry['output']['target'] != case['input']['target']
            entry['readonly_preserved'] = entry['output']['readonly'] == case['input']['readonly']
            entry['elapsed_s'] = time.perf_counter() - started
            results.append(entry)
            save(args.out / 'results.json', results)
            logging.info('Review done; case=%s; status=%s; changed=%s; elapsed=%.3f',
                         case['name'], entry['status'], entry['target_changed'], entry['elapsed_s'])
    finally:
        lifecycle.clear()
        logging.info('Owned GPU model unloaded')


if __name__ == '__main__':
    main()
