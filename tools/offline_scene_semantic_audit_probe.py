"""Test whether an itemized 8B auditor catches semantic Scene contradictions.

Research-only; reads the dual-lane probe output and leaves production code untouched.
"""

from __future__ import annotations

import argparse
from dataclasses import replace
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from core.inference import LlamaCppLifecycle, LlamaRuntimeConfig
from core.protocols.llm_records import parse_llm_records
from tools.offline_scene_event_performance_probe import _audit_controls, _infer, _quote

SOURCE = ROOT / "docs/assets/research/scene-event-performance-dual-probe-2026-09-22/evidence.json"
FIELDS = ("TARGET_ACTION", "CONTACT_POINT", "EXTERNAL_EFFECT", "SYNC")
PROMPT = """あなたはMVの計画文を独立に検査する。EVENTとBODYを修正・創作しない。各質問を別々に評価してPASS又はFAILを記す。
TARGET_ACTION: EVENT.CHANGEで動くもの・作用されるものはEVENT.TARGETか。TARGET=社なのに足音や石畳だけが変化するならFAIL。
CONTACT_POINT: MODE=contactならCONTACT_POINTはTARGETの一部分か。TARGET=社で石畳ならFAIL。contact以外でCONTACT_POINT=なしならPASS。
EXTERNAL_EFFECT: TARGETが狐火など独立した現象ならMODE=autonomousで人物の手から発生・操作しないか。狐火をcontact扱いするならFAIL。独立現象でなければPASS。
SYNC: BODY.SYNCはEVENT.CHANGEの同じ瞬間へ反応し、別の出来事へ置き換えていないか。
例: TARGET=社、CONTACT_POINT=石畳、CHANGE=石畳に触れる → TARGET_ACTION=FAIL、CONTACT_POINT=FAIL。
例: TARGET=狐火、MODE=contact、CONTACT_POINT=神社の建物、CHANGE=狐火が建物に触れる → CONTACT_POINT=FAIL、EXTERNAL_EFFECT=FAIL。
例: TARGET=狐火、MODE=autonomous、CHANGE=狐火が自ら空中を巡る → EXTERNAL_EFFECT=PASS。
EVENT/BODYを読んで実TAB区切り一行 CHECK、1、TARGET_ACTION=...｜CONTACT_POINT=...｜EXTERNAL_EFFECT=...｜SYNC=... のみ出力する。説明を出さない。"""


def grammar() -> str:
    row = [_quote("CHECK\t1\t")]
    for index, field in enumerate(FIELDS):
        row.append(_quote(("" if index == 0 else "｜") + field + "="))
        row.append("verdict")
    return "root ::= " + " ".join(row) + ' "\\n"?\n' + 'verdict ::= "PASS" | "FAIL"\n'


def parse(raw: str) -> dict:
    result = parse_llm_records(
        raw, allowed_slots={"CHECK": frozenset({1})},
        required=frozenset({("CHECK", 1)}),
    )
    if result.issues or result.missing or len(result.records) != 1:
        return {"valid": False, "issues": [issue.reason for issue in result.issues]}
    parts = result.records[0].text.split("｜")
    flags: dict[str, str] = {}
    for name, part in zip(FIELDS, parts):
        label, equals, value = part.partition("=")
        if not equals or label != name or value not in {"PASS", "FAIL"}:
            return {"valid": False, "error": "field mismatch"}
        flags[name] = value
    return {"valid": len(parts) == len(FIELDS), "flags": flags}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, default=SOURCE)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    source = json.loads(args.source.read_text(encoding="utf-8"))
    runtime = LlamaRuntimeConfig(**source["runtime"])
    records: list[dict] = []
    for case in _audit_controls():
        records.append({"name": case["name"], "scene": case["scene"],
                        "lyrics": case["lyrics"], "plan": case["plan"],
                        "expected": case["expect"]})
    for run in source["runs"]:
        if run["task"] != "dual-plan":
            continue
        records.append({"name": f"generated_scene{run['scene']}_seed{run['seed']}",
                        "scene": run["scene"],
                        "lyrics": [item["text"] for item in run["payload"]["lyrics"]],
                        "plan": run["response"]})
    evidence = {"source": str(args.source), "model": source["model"],
                "runtime": runtime.to_dict(), "prompt": PROMPT, "runs": []}
    args.output.mkdir(parents=True, exist_ok=True)
    path = args.output / "evidence.json"
    lifecycle = LlamaCppLifecycle()
    try:
        lifecycle.ensure_loaded(Path(source["model"]), runtime)
        for record in records:
            payload = {"scene_number": record["scene"], "lyrics": record["lyrics"],
                       "plan": record["plan"]}
            raw, tokens, elapsed = _infer(
                lifecycle, replace(runtime, seed=42, max_tokens=128),
                system=PROMPT, payload=payload, grammar=grammar(),
            )
            item = {"name": record["name"], "expected": record.get("expected"),
                    "payload": payload, "response": raw, "parsed": parse(raw),
                    "prompt_tokens": tokens, "elapsed_seconds": elapsed}
            evidence["runs"].append(item)
            path.write_text(json.dumps(evidence, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
            print(f"{record['name']}: {item['parsed']}", flush=True)
    finally:
        lifecycle.clear()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
