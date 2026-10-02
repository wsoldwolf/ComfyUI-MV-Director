"""Compare Planner's line grammar cost with identical local GGUF requests.

This is a diagnostic only. It does not submit a ComfyUI prompt or edit any
workflow, and it never writes the generated response to disk.
"""

from __future__ import annotations

import argparse
import inspect
import json
import sys
from pathlib import Path
from time import perf_counter, process_time

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from core.planner.scene_author import build_scene_author_grammar  # noqa: E402
from core.protocols import parse_llm_records  # noqa: E402

TASKS = {
    "event": ("scene-author-event", "EVENT"),
    "performance": ("scene-author-performance", "PERFORMANCE"),
    "camera": ("scene-author-camera", "CAMERA"),
}


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--model", type=Path, required=True)
    parser.add_argument("--gpu-layers", type=int, default=31)
    parser.add_argument("--n-ctx", type=int, default=8192)
    parser.add_argument("--max-tokens", type=int, default=192)
    parser.add_argument("--task", choices=TASKS, default="event")
    args = parser.parse_args()

    from llama_cpp import GGML_TYPE_Q8_0, Llama, LlamaGrammar, llama_cpp

    slots = [
        {"slot": 1, "scene_number": 3, "scene": 3, "shot": 1,
         "position": "石段に積もる／名もなき季節"},
        {"slot": 2, "scene_number": 3, "scene": 3, "shot": 2,
         "position": "昨日の願いは／苔へと還る"},
    ]
    task, record_type = TASKS[args.task]
    payload = {
        "protocol": "MVD_LLM_RECORDS_V1",
        "task": task,
        "scene_environment": ["夜の神社境内", "参道", "大樹"],
        "original_lyrics": ["石段に積もる 名もなき季節", "昨日の願いは 苔へと還る"],
        "staging_candidates_optional": [
            "参道脇の大樹の根元にある苔を一度確立する。"
        ],
        "previous_scene_state": "人物は参道に立つ",
        "accepted_events_by_shot": {
            "1": "大樹の根元の苔が見える",
            "2": "苔に木漏れ日が移り、人物は手を離す",
        },
        "accepted_performances_by_shot": {
            "1": "人物は参道脇の大樹へ寄り、根元の苔を指先で撫でる。",
            "2": "人物は手を離し、苔を見つめて微笑む。",
        },
        "slots": slots,
    }
    system_prompt = (
        ROOT / "prompts" / f"timeline_planner_{task.replace('-', '_')}_system_prompt.txt"
    ).read_text(encoding="utf-8")
    messages = [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": "/no_think\n" + json.dumps(
            payload, ensure_ascii=False, separators=(",", ":"),
        )},
    ]
    grammar_text = build_scene_author_grammar(task, slots)
    print("loading model", flush=True)
    started = perf_counter()
    model = Llama(
        model_path=str(args.model.resolve(strict=True)),
        n_ctx=args.n_ctx,
        n_gpu_layers=args.gpu_layers,
        n_batch=256,
        flash_attn=True,
        type_k=GGML_TYPE_Q8_0,
        type_v=GGML_TYPE_Q8_0,
        offload_kqv=True,
        op_offload=True,
        swa_full=False,
        verbose=False,
    )
    print(f"model_ready_s={perf_counter() - started:.2f}", flush=True)
    # Alternate order and reset context to separate grammar cost from warmup
    # and prefix reuse. Native timings exclude Python and grammar sampling.
    for index, constrained in enumerate((False, True, True, False), 1):
        model.reset()
        grammar = LlamaGrammar.from_string(grammar_text, verbose=False) if constrained else None
        llama_cpp.llama_perf_context_reset(model._ctx.ctx)
        cpu_start = process_time()
        wall_start = perf_counter()
        first_content: float | None = None
        parts: list[str] = []
        call_kwargs = {
            "messages": messages,
            "max_tokens": args.max_tokens,
            "temperature": 0.2,
            "top_p": 0.9,
            "repeat_penalty": 1.05,
            "seed": 123456,
            "stream": True,
            "chat_template_kwargs": {"enable_thinking": False},
            "reasoning": False,
        }
        if grammar is not None:
            call_kwargs["grammar"] = grammar
        supported = inspect.signature(model.create_chat_completion).parameters
        stream = model.create_chat_completion(**{
            key: value for key, value in call_kwargs.items() if key in supported
        })
        for chunk in stream:
            for choice in chunk.get("choices", []):
                content = choice.get("delta", {}).get("content")
                if content:
                    if first_content is None:
                        first_content = perf_counter()
                    parts.append(content)
        wall = perf_counter() - wall_start
        cpu = process_time() - cpu_start
        perf = llama_cpp.llama_perf_context(model._ctx.ctx)
        text = "".join(parts)
        parsed = parse_llm_records(
            text,
            allowed_slots={record_type: frozenset({1, 2})},
            required=frozenset({(record_type, 1), (record_type, 2)}),
        )
        print(json.dumps({
            "task": args.task,
            "trial": index,
            "grammar": constrained,
            "wall_s": round(wall, 3),
            "first_content_s": round(first_content - wall_start, 3) if first_content else None,
            "cpu_core_seconds": round(cpu, 3),
            "prompt_eval_s": round(perf.t_p_eval_ms / 1000, 3),
            "decode_s": round(perf.t_eval_ms / 1000, 3),
            "prompt_eval_tokens": perf.n_p_eval,
            "decode_tokens": perf.n_eval,
            "response_chars": len(text),
            "starts_with_record": text.startswith(f"{record_type}\t1\t"),
            "valid_slots": sorted(record.slot for record in parsed.records),
            "missing_slots": sorted(slot for _, slot in parsed.missing),
            "issues": [issue.reason for issue in parsed.issues],
            "unaccounted_s": round(
                wall - (perf.t_p_eval_ms + perf.t_eval_ms) / 1000, 3,
            ),
        }, ensure_ascii=False), flush=True)
    model.close()


if __name__ == "__main__":
    main()
