"""Explicit GPU probe of fragment versus intact protected-field translation.

Saved EMD is never regenerated. --recompile uses the public Compiler node only.
All evidence must be written to a fresh directory outside the repository.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import re
import sys
import time
from types import SimpleNamespace
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from core.compiler.llama_translator import LlamaPromptTranslator
from core.compiler.protection import protect_unit
from core.compiler.whole_field import WholeFieldTranslator
from core.emd import parse_emd, shot_prose
from core.inference import LlamaCppLifecycle, LlamaRuntimeConfig
from core.artifacts import canonical_json
from nodes.common.gguf_discovery import resolve_comfy_gguf_model
from nodes.node_emd_compiler import node as compiler_module
from tools.debug_multi_subject_pipeline import implementation_manifest, save


def verify_recompile(saved, destination):
    original = json.loads((saved / 'plan.json').read_text(encoding='utf-8'))
    plan_text = (destination / 'plan.json').read_text(encoding='utf-8')
    current = json.loads(plan_text)
    trace = json.loads((destination / 'translation-trace.json').read_text(encoding='utf-8'))
    results = json.loads((destination / 'results.json').read_text(encoding='utf-8'))
    previous = json.loads((saved / 'results.json').read_text(encoding='utf-8'))
    def mechanics(value):
        if isinstance(value, dict):
            return {key: mechanics(item) for key, item in value.items()
                    if key not in {'prompt', 'prompt_prefix'}}
        if isinstance(value, list):
            return [mechanics(item) for item in value]
        return value
    # All timing, continuity, singer and source-audio fields must be identical.
    checks = {'non_prompt_plan_identical': mechanics(original) == mechanics(current),
        'required_references_identical': results['references'] == previous['compiler']['required_references'],
        'no_reserved_marker_in_plan': '__MVD_KEEP_' not in plan_text,
        'strict_json_trace': bool(canonical_json({'trace': trace})),
        'source_emd_unmodified': (saved / 'planner-emd.md').read_text(encoding='utf-8') ==
            (destination / 'source-emd.md').read_text(encoding='utf-8')}
    save(destination / 'checks.json', checks)
    if not all(checks.values()):
        raise AssertionError('Recompile changed a protected structural contract')
    lines = ['# Compiler source EMD and adopted English fields', '',
        'Saved EMD only; no Planner rerun and no H3 generation.', '']
    for field in trace:
        lines += [f"## {field['field_id']}", '',
            'Strategy: ' + field.get('strategy', 'protected_fragments'), '',
            '```text', field['source'], '```', '',
            '```text', field['restored'], '```', '']
    (destination / 'english-fields.md').write_text('\n'.join(lines), encoding='utf-8')
    return checks


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--saved', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--infer', action='store_true')
    parser.add_argument('--recompile', action='store_true')
    parser.add_argument('--verify-only', action='store_true')
    parser.add_argument('--single-subject-only', action='store_true',
        help='Compare only saved clauses containing one distinct Subject reference')
    args = parser.parse_args()
    destination = args.output.resolve()
    if destination.is_relative_to(ROOT):
        raise ValueError('Evidence must be outside the repository')
    if args.verify_only:
        if args.infer or args.recompile:
            raise ValueError('--verify-only must not run inference')
        print(verify_recompile(args.saved, destination))
        return
    if destination.exists():
        raise ValueError('Evidence requires a fresh external directory')
    destination.mkdir(parents=True)
    emd_path = args.saved / 'planner-emd.md'
    emd = emd_path.read_text(encoding='utf-8')
    prepared = json.loads((args.saved / 'prepared.json').read_text(encoding='utf-8'))
    arguments = prepared['compiler']
    doc = parse_emd(emd)
    cfg = LlamaRuntimeConfig(**{
        'chat_format': '' if arguments['chat_format'] == 'auto' else arguments['chat_format'],
        **{key: arguments[key] for key in ('max_tokens', 'temperature', 'top_p',
            'repetition_penalty', 'gpu_layers', 'n_batch', 'n_ctx', 'flash_attn',
            'kv_cache_type', 'op_offload', 'keep_model_loaded', 'seed')}})
    resolve = lambda name: resolve_comfy_gguf_model(name, folder_paths_module=SimpleNamespace(
        models_dir='C:/Software/ComfyUI/models', folder_names_and_paths={}))
    model = resolve(arguments['model_name'])
    if args.single_subject_only:
        cases = []
        for scene_index, scene in enumerate(doc.scenes):
            for shot_index, shot in enumerate(scene.shots):
                for body_index, body in enumerate(shot.body):
                    source = shot_prose(body)
                    unit = protect_unit(source, doc.subjects)
                    references = {value for value in unit.values
                                  if re.fullmatch(r'<Subject [1-4]>', value)}
                    if len(references) == 1:
                        cases.append((f'saved.{scene_index}.{shot_index}.{body_index}', source))
    else:
        cases = [(f'saved.1.1.{i}', shot_prose(body))
                 for i, body in enumerate(doc.scenes[0].shots[0].body)]
        cases += [
            ('handoff', '`サブジェクト1`が左手の花を`サブジェクト2`の右手へ渡す。'),
            ('tree', '`サブジェクト1`が`サブジェクト3`の幹の根元に生えた苔に右手で触れる。'),
            ('reverse_target', '`サブジェクト1`へ`サブジェクト2`が視線を向ける。'),
            ('dialogue', '`サブジェクト1`が「待って」と言い、Arc Shot at fast speed で`サブジェクト2`を追う。'),
            ('single_control', '`サブジェクト1`が足袋と下駄を履いてゆっくり歩く。')]
    save(destination / 'sources.json', {'emd_path': str(emd_path),
        'emd_sha256': hashlib.sha256(emd.encode()).hexdigest(),
        'runtime': cfg.to_dict(), 'model': str(model.path),
        'implementation': implementation_manifest(), 'cases': cases,
        'probe_sha256': hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
        'planner_rerun': False, 'h3_generated': False})
    if not args.infer:
        return
    lifecycle = LlamaCppLifecycle()
    calls, results = [], []
    original = lifecycle.complete_chat
    def record(messages, config, **kwargs):
        entry = {'messages': messages}
        calls.append(entry)
        started = time.perf_counter()
        try:
            entry['response'] = original(messages, config, **kwargs)
            return entry['response']
        except BaseException as exc:
            entry['error'] = repr(exc)
            raise
        finally:
            entry['elapsed_s'] = time.perf_counter() - started
            save(destination / 'calls.json', calls)
    lifecycle.complete_chat = record
    try:
        print('GPU: loading Gemma4 31B for Compiler only', flush=True)
        lifecycle.ensure_loaded(model.path, cfg)
        if args.recompile:
            instance = compiler_module.MVDirectorEMDCompiler()
            instance._lifecycle.clear()
            instance._lifecycle = lifecycle
            captured = []
            class TracedTranslator(LlamaPromptTranslator):
                def __init__(self, *a, **kw):
                    super().__init__(*a, **kw)
                    captured.append(self)
            started = time.perf_counter()
            with patch.object(compiler_module, 'resolve_comfy_gguf_model', resolve), \
                 patch.object(compiler_module, '_cache', return_value=None), \
                 patch.object(compiler_module, 'LlamaPromptTranslator', TracedTranslator):
                plan, refs, status = instance.compile_emd(**arguments, emd_text=emd)
            (destination / 'plan.json').write_text(plan, encoding='utf-8')
            (destination / 'source-emd.md').write_text(emd, encoding='utf-8')
            save(destination / 'translation-trace.json', captured[0].translation_trace)
            save(destination / 'results.json', {'status': status,
                'elapsed_s': time.perf_counter() - started, 'references': refs.to_dict()})
            verify_recompile(args.saved, destination)
            print(status, flush=True)
            return
        for name, source in cases:
            row = {'case': name, 'source': source}
            results.append(row)
            unit = protect_unit(source, doc.subjects)
            for strategy in ('fragments', 'whole_field'):
                start, before = time.perf_counter(), len(calls)
                try:
                    if strategy == 'fragments':
                        translator = LlamaPromptTranslator(lifecycle,
                            system_prompt=compiler_module._system_prompt(), runtime_config=cfg)
                        indices = [i for i, fragment in enumerate(unit.fragments)
                                   if re.search(r'[\u3040-\u30ff\u3400-\u9fff]', fragment)]
                        translated = translator.translate(tuple(unit.fragments[i] for i in indices))
                        text = unit.restore(dict(zip(indices, translated)))
                    else:
                        translator = WholeFieldTranslator(lifecycle, runtime_config=cfg)
                        text = translator.translate_unit(unit)
                    row[strategy] = {'text': text, 'elapsed_s': time.perf_counter() - start,
                        'calls': len(calls) - before}
                except Exception as exc:
                    row[strategy] = {'error': repr(exc), 'elapsed_s': time.perf_counter() - start,
                        'calls': len(calls) - before}
                save(destination / 'results.json', results)
                print(name, strategy, row[strategy], flush=True)
    except BaseException as exc:
        save(destination / 'failure.json', {'error': repr(exc), 'calls': len(calls)})
        raise
    finally:
        lifecycle.clear()
        print('GPU model unloaded; no Planner/H3 execution', flush=True)


if __name__ == '__main__':
    main()
