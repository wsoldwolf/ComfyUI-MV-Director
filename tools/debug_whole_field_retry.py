"""Explicit GPU probe of one saved Compiler field; never modifies EMD or Plan.

Results require a fresh directory outside the project. --check-repair injects
one duplicated marker into a valid draft to exercise the real repair call;
that injected response is synthetic, not a reproduction of a previous failure.
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

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from core.compiler.llama_translator import LlamaPromptTranslator
from core.compiler.protection import protect_unit
from core.compiler.whole_field import MaskedField, whole_field_prompt
from core.emd import parse_emd, shot_prose
from core.inference import LlamaCppLifecycle, LlamaRuntimeConfig
from nodes.common.gguf_discovery import resolve_comfy_gguf_model


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--emd', type=Path, required=True)
    parser.add_argument('--workflow', type=Path, required=True)
    parser.add_argument('--field', required=True, help='Zero-based scene.N.shot.N.body.N')
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--check-repair', action='store_true')
    args = parser.parse_args()
    match = re.fullmatch(r'scene\.(\d+)\.shot\.(\d+)\.body\.(\d+)', args.field)
    if match is None:
        raise ValueError('invalid field identifier')
    output = args.output.resolve()
    if output.is_relative_to(ROOT) or output.exists():
        raise ValueError('a fresh evidence directory outside the project is required')
    emd_bytes = args.emd.read_bytes()
    document = parse_emd(emd_bytes.decode('utf-8'))
    scene, shot, body = map(int, match.groups())
    source = shot_prose(document.scenes[scene].shots[shot].body[body])
    unit = protect_unit(source, document.subjects)
    field = MaskedField.from_unit(unit)
    if not field.markers:
        raise ValueError('the selected field has no protected occurrences')
    workflow = json.loads(args.workflow.read_text(encoding='utf-8'))
    compiler = next(n for n in workflow['nodes'] if n['type'] == 'MVDirectorEMDCompiler')
    settings = compiler['widgets_values_named']
    runtime = {key: settings[key] for key in LlamaRuntimeConfig.__dataclass_fields__}
    runtime['chat_format'] = '' if runtime['chat_format'] == 'auto' else runtime['chat_format']
    config = LlamaRuntimeConfig(**runtime)
    model = resolve_comfy_gguf_model(settings['model_name'], folder_paths_module=SimpleNamespace(
        models_dir='C:/Software/ComfyUI/models', folder_names_and_paths={}))
    output.mkdir(parents=True)
    lifecycle = LlamaCppLifecycle()
    results = {'field_id': args.field, 'source': source, 'runtime': config.to_dict(),
               'model': str(model.path), 'emd_sha256': hashlib.sha256(emd_bytes).hexdigest(),
               'whole_field_prompt_sha256': hashlib.sha256(whole_field_prompt().encode('utf-8')).hexdigest(),
               'planner_rerun': False, 'h3_generated': False, 'probes': []}

    def save():
        (output / 'results.json').write_text(json.dumps(results, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')

    def run(backend, label):
        translator = LlamaPromptTranslator(backend, system_prompt='Unused fragment route.', runtime_config=config)
        started = time.perf_counter()
        row = {'probe': label}
        results['probes'].append(row)
        try:
            restored = translator.translate_protected_unit(unit, field_id=args.field,
                source_sha256=hashlib.sha256(source.encode('utf-8')).hexdigest(), source=source)
            row['restored'] = restored
            return translator.translation_trace[-1]['attempts'][-1]['masked_translation']
        except Exception as exc:
            row['error'] = str(exc)
            raise
        finally:
            row.update(elapsed_s=time.perf_counter() - started, calls=translator.batch_count,
                       trace=translator.translation_trace)
            save()

    try:
        print('GPU: loading saved Compiler model for one field only', flush=True)
        lifecycle.ensure_loaded(model.path, config)
        draft = run(lifecycle, 'normal-production-translation')
        if args.check_repair:
            # Duplicate the Subject occurrence implicated in this incident when
            # present; otherwise select the first marker. Do not alter any source.
            marker = field.markers[min(2, len(field.markers) - 1)]
            invalid = draft.replace(marker, marker + ' ' + marker, 1)
            results['synthetic_draft'] = invalid

            class InjectedDraft:
                effective_n_ctx = lifecycle.effective_n_ctx
                injected = False
                count_serialized_prompt = lifecycle.count_serialized_prompt

                def complete_chat(self, *a, **kw):
                    if not self.injected:
                        self.injected = True
                        return 'TRANSLATION\t1\t' + invalid
                    return lifecycle.complete_chat(*a, **kw)

            run(InjectedDraft(), 'controlled-duplicate-then-real-repair')
        results['source_emd_unchanged'] = args.emd.read_bytes() == emd_bytes
        results['outcome'] = 'success'
        save()
        print(json.dumps({k: v for k, v in results.items() if k in ('field_id', 'source_emd_unchanged')}, ensure_ascii=False), flush=True)
        print('Evidence: ' + str(output / 'results.json'), flush=True)
    except Exception as exc:
        results['outcome'], results['error'] = 'failed', str(exc)
        raise
    finally:
        lifecycle.clear()
        results['source_emd_unchanged'] = args.emd.read_bytes() == emd_bytes
        save()


if __name__ == '__main__':
    main()
