"""One bounded LLM-authored repair of failed dual-lane Scene plans (offline only)."""

from __future__ import annotations

import argparse
from dataclasses import replace
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from core.inference import LlamaCppLifecycle, LlamaRuntimeConfig
from tools.offline_scene_event_performance_probe import (
    PLAN_PROMPT, _infer, parse_plan, plan_grammar,
)
from tools.offline_scene_semantic_audit_probe import PROMPT as MATRIX_PROMPT, grammar as matrix_grammar, parse as parse_matrix

SOURCE = ROOT / "docs/assets/research/scene-event-performance-dual-probe-2026-09-22/evidence.json"
MATRIX = ROOT / "docs/assets/research/scene-event-performance-audit-matrix-2026-09-22/evidence.json"
REPAIR_RULE = """これは同じSceneの一回だけの再要求。前のEVENT/BODY二行は採用されなかった。監査でFAILとなった項目を直し、歌詞の出来事と身体経路を両立させた完全な二行を新たに書く。
TARGET_ACTION=FAILならTARGET以外の足音・石畳等を出来事の主役にしない。CONTACT_POINT=FAILなら接触点がTARGETの実際の部位であることを確認する。歌詞に接触が必要でない社のSceneではMODE=observeにしてCONTACT_POINT=なしを選べる。
EXTERNAL_EFFECT=FAILなら狐火はMODE=autonomous、CONTACT_POINT=なしで、狐火自身の出現・空間経路・環境への結果をEVENTに書く。人物はそれを見て反応し、発生・保持・操作しない。
SYNC=FAILならBODYのアクセントをEVENTの同じ瞬間へ結び付ける。候補の動きを繰り返すだけで対象を失わない。出力は元のEVENT/BODY二行だけ。"""


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, default=SOURCE)
    parser.add_argument("--matrix", type=Path, default=MATRIX)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    source = json.loads(args.source.read_text(encoding="utf-8"))
    matrix = json.loads(args.matrix.read_text(encoding="utf-8"))
    matrix_by_name = {item["name"]: item["parsed"] for item in matrix["runs"]}
    runtime = LlamaRuntimeConfig(**source["runtime"])
    evidence = {"source": str(args.source), "matrix": str(args.matrix),
                "model": source["model"], "runtime": runtime.to_dict(),
                "repair_rule": REPAIR_RULE, "runs": []}
    args.output.mkdir(parents=True, exist_ok=True)
    path = args.output / "evidence.json"
    lifecycle = LlamaCppLifecycle()
    try:
        lifecycle.ensure_loaded(Path(source["model"]), runtime)
        for item in source["runs"]:
            if item["task"] != "dual-plan":
                continue
            seed, scene = item["seed"], item["scene"]
            name = f"generated_scene{scene}_seed{seed}"
            flags = matrix_by_name[name]["flags"]
            failures = [key for key, value in flags.items() if value == "FAIL"]
            if not failures:
                continue
            payload = {**item["payload"], "previous_rejected_plan": item["response"],
                       "audit_failures": failures}
            raw, tokens, elapsed = _infer(
                lifecycle, replace(runtime, seed=seed, max_tokens=768),
                system=PLAN_PROMPT + "\n" + REPAIR_RULE,
                payload=payload, grammar=plan_grammar(scene),
            )
            lyrics = [lyric["text"] for lyric in item["payload"]["lyrics"]]
            parsed = parse_plan(raw, scene, lyrics)
            result = {"seed": seed, "scene": scene, "failures": failures,
                      "payload": payload, "response": raw, "parsed": parsed,
                      "prompt_tokens": tokens, "elapsed_seconds": elapsed}
            if parsed["valid"]:
                audit_payload = {"scene_number": scene, "lyrics": lyrics, "plan": raw}
                audit_raw, audit_tokens, audit_elapsed = _infer(
                    lifecycle, replace(runtime, seed=seed, max_tokens=128),
                    system=MATRIX_PROMPT, payload=audit_payload, grammar=matrix_grammar(),
                )
                result["matrix_audit"] = {"response": audit_raw, "parsed": parse_matrix(audit_raw),
                                          "prompt_tokens": audit_tokens,
                                          "elapsed_seconds": audit_elapsed}
            evidence["runs"].append(result)
            path.write_text(json.dumps(evidence, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
            print(f"seed={seed} scene={scene} repair_valid={parsed['valid']} "
                  f"matrix={result.get('matrix_audit', {}).get('parsed')}", flush=True)
    finally:
        lifecycle.clear()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
