"""Eight controlled performance-only calls: prompt x section context.

No event/camera inference, semantic repair, or H3 rendering. All variants share
an explicit event and effective seed. Persist complete prompts and raw outputs.
"""
from __future__ import annotations

import argparse
from dataclasses import asdict, replace
import hashlib
import json
from pathlib import Path
import subprocess
import sys
import time

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from core.artifacts import canonical_json
from core.inference import LlamaCppLifecycle, LlamaRuntimeConfig
from core.lyrics.plain import parse_plain_lyrics
from nodes.node_timeline_planner.node import _LlamaPlannerBackend

PROMPT = "prompts/timeline_planner_scene_author_performance_system_prompt.txt"


def reading_context(lyrics: str, payload: dict) -> list[dict]:
    """Locate unique local source sequence; reject ambiguous fixture matching."""
    segments = parse_plain_lyrics(lyrics)
    local = [(line["section"], line["text"]) for shot in payload["original_lyrics"] for line in shot["lyrics"]]
    all_lines = [(line.section, line.text) for line in segments]
    matches = [i for i in range(len(all_lines) - len(local) + 1) if all_lines[i:i + len(local)] == local]
    if not local or len(matches) != 1:
        raise ValueError("Fixture lyrics must match one unique contiguous source span")
    first = matches[0]
    focus = set(range(first, first + len(local)))
    groups = []
    counts = {}
    # Full original source headings are available in this offline experiment.
    heading_lines = [i for i, line in enumerate(lyrics.splitlines(), 1) if line.startswith("[")]
    previous_heading = None
    for index, segment in enumerate(segments):
        heading = max(i for i in heading_lines if i < segment.source_line)
        if heading != previous_heading:
            counts[segment.section] = counts.get(segment.section, 0) + 1
            groups.append({"section": segment.section, "occurrence": counts[segment.section],
                           "boundary_source": "original_heading", "coverage": "full_source_section", "lines": []})
            previous_heading = heading
        groups[-1]["lines"].append({"source_line": segment.source_line, "scene": 1 if index in focus else 0,
                                   "text": segment.text})
    return [g for g in groups if any(line["scene"] == 1 for line in g["lines"])]


class FixedSeedBackend(_LlamaPlannerBackend):
    @staticmethod
    def _call_seed(base_seed, task, call_number, payload):
        return base_seed


class RecordingLifecycle(LlamaCppLifecycle):
    last_config = None

    def complete_chat(self, messages, config, **kwargs):
        self.last_config = config
        return super().complete_chat(messages, config, **kwargs)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--model", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--baseline-ref", default="01cfc6c")
    parser.add_argument("--lyrics", type=Path, default=ROOT / "assets/bgm/bgm_millennium_torii_lyrics.txt")
    parser.add_argument("--seed", type=int, default=1)
    parser.add_argument("--variants", nargs="+", choices=list("ABCD"), default=list("ABCD"))
    args = parser.parse_args()
    if args.output.exists() and any(args.output.iterdir()):
        raise ValueError("Choose a fresh output directory; do not overwrite evidence")
    args.output.mkdir(parents=True, exist_ok=True)
    old_prompt = subprocess.check_output(["git", "show", f"{args.baseline_ref}:{PROMPT}"], cwd=ROOT).decode("utf-8")
    new_prompt = (ROOT / PROMPT).read_text(encoding="utf-8")
    lyrics = args.lyrics.read_text(encoding="utf-8")
    requests = []
    for scene in (5, 9):
        source = ROOT / f"docs/assets/research/scene-author-2026-09-23/scene{scene}-v5/summary.json"
        saved = json.loads(source.read_text(encoding="utf-8"))
        original = json.loads(next(row["payload"] for row in saved["trace"] if row["task"] == "scene-author-performance"))
        # Frozen common input isolates performance generation from event failures.
        original["accepted_event"] = "なし" if scene == 5 else "人物の周囲の空間に複数の狐火が現れる。"
        original["accepted_event_shot"] = 1 if scene == 5 else 2
        original["event_source"] = "author"
        original["staging_candidates_optional"] = []
        context = reading_context(lyrics, original)
        for variant in args.variants:
            request = {**original}
            if variant in "CD":
                request["section_lyric_context"] = context
            system = new_prompt if variant in "BD" else old_prompt
            requests.append((scene, variant, system, canonical_json(request)))
    config = LlamaRuntimeConfig(
        n_ctx=16384, max_tokens=1536, temperature=0.2, top_p=0.9,
        repetition_penalty=1.05, gpu_layers=-1, n_batch=512,
        keep_model_loaded=False, seed=args.seed,
    )
    lifecycle = RecordingLifecycle()
    backend = FixedSeedBackend(lifecycle)
    manifest = {"baseline_ref": args.baseline_ref, "model": str(args.model),
                "config": asdict(config), "lyrics_sha256": hashlib.sha256(lyrics.encode()).hexdigest(),
                "scope": "performance_only_frozen_event", "results": []}
    try:
        lifecycle.ensure_loaded(args.model, config)
        for scene, variant, system, payload in requests:
            started = time.perf_counter()
            count = lifecycle.count_serialized_prompt(system + "\n/no_think\n" + payload)
            response = backend.complete_planner(
                task="scene-author-performance", system_prompt=system, payload=payload, config=config,
            )
            result = {
                "scene": scene, "variant": variant, "system_prompt": system, "payload": json.loads(payload),
                "system_sha256": hashlib.sha256(system.encode()).hexdigest(),
                "payload_sha256": hashlib.sha256(payload.encode()).hexdigest(),
                "prompt_tokens": count.count, "tokens_estimated": count.estimated,
                "effective_config": asdict(lifecycle.last_config), "elapsed_seconds": time.perf_counter() - started,
                "response": response,
            }
            (args.output / f"scene{scene}-{variant}.json").write_text(
                json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8",
            )
            manifest["results"].append({k: result[k] for k in ("scene", "variant", "prompt_tokens", "elapsed_seconds")})
            print(f"scene={scene} variant={variant} tokens={count.count} elapsed={result['elapsed_seconds']:.2f}", flush=True)
    finally:
        lifecycle.clear()
        (args.output / "manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
