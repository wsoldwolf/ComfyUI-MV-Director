"""Evaluate 8B target/change semantic alignment on pre-labelled Scene pairs.

This is an offline audit study. It does not edit Planner output or production code.
"""

from __future__ import annotations

import argparse
from dataclasses import replace
import hashlib
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from core.inference import LlamaCppLifecycle, LlamaRuntimeConfig
from core.protocols.llm_records import parse_llm_records
from tools.offline_scene_event_performance_probe import _infer, _quote

CASES = ROOT / "docs/assets/research/scene-target-event-alignment-2026-09-22/cases.json"
BASELINE = ROOT / "docs/assets/research/choreography-full-run-v4-2026-09-22/evidence.json"
PROMPT = """あなたはアニメMVのScene計画の意味監査者。計画文を直さず、現在Sceneの原歌詞、TARGET、CHANGEだけを評価する。
SOURCE=yesはTARGETが原歌詞の現在Sceneに根拠を持つこと。背景や別Sceneだけにある対象ならno。
EVENT=yesはCHANGEがそのTARGETを画面上の出来事として実際に見せること。対象自身が現れる・動く・変化する、又は人物が対象を見つめる・触れる等の撮影可能な関係を作るならyes。TARGET名が別欄にあるだけ、対象が動かない単なる背景、足音や歩行など別物だけの出来事ならno。日本語の部分文字列だけで判断しない。
人物の手から狐火や光が生まれること自体は許される。狐火が手を離れて進む演出も、狐火を手元で光らせる演出も、TARGET=狐火の可視出来事になり得る。人物が腕を動かすだけで狐火が映らない場合はEVENT=no。起源・自律性・好みを理由にnoへしない。
QUOTEはEVENT=yesならCHANGE内に実際に存在する、対象が映る又は対象と関係する最短の連続文字列を引用する。EVENT=noならQUOTE=なし。QUOTEを創作せず、TARGET欄や歌詞欄から引用しない。
説明不要。実TAB区切り一行 ALIGN、1、SOURCE=yes|no｜EVENT=yes|no｜QUOTE=... だけを出す。"""
BINARY_PROMPT = PROMPT.split("QUOTEはEVENT=yesなら")[0] + (
    "説明不要。実TAB区切り一行 ALIGN、1、SOURCE=yes|no｜EVENT=yes|no だけを出す。"
)


def grammar() -> str:
    return (
        "root ::= " + _quote("ALIGN\t1\tSOURCE=") + " bit "
        + _quote("｜EVENT=") + " bit " + _quote("｜QUOTE=") + " cell "
        + '"\\n"?\nbit ::= "yes" | "no"\n'
        + r"cell ::= [^\x00-\x1f｜\\]{1,120}" + "\n"
    )


def binary_grammar() -> str:
    return (
        "root ::= " + _quote("ALIGN\t1\tSOURCE=") + " bit "
        + _quote("｜EVENT=") + " bit " + '"\\n"?\n'
        + 'bit ::= "yes" | "no"\n'
    )


def parse(raw: str, change: str) -> dict:
    result = parse_llm_records(
        raw, allowed_slots={"ALIGN": frozenset({1})},
        required=frozenset({("ALIGN", 1)}),
    )
    if result.issues or result.missing or len(result.records) != 1:
        return {"valid": False, "issues": [issue.reason for issue in result.issues]}
    parts = result.records[0].text.split("｜")
    if len(parts) != 3:
        return {"valid": False, "error": "field_count"}
    parsed: dict[str, str] = {}
    for name, item in zip(("SOURCE", "EVENT", "QUOTE"), parts):
        label, separator, value = item.partition("=")
        if not separator or label != name or not value:
            return {"valid": False, "error": f"invalid_{name}"}
        parsed[name] = value
    if parsed["SOURCE"] not in {"yes", "no"} or parsed["EVENT"] not in {"yes", "no"}:
        return {"valid": False, "error": "invalid_bit"}
    quote_valid = (
        parsed["QUOTE"] == "なし" if parsed["EVENT"] == "no"
        else parsed["QUOTE"] != "なし" and parsed["QUOTE"] in change
    )
    return {"valid": True, "fields": parsed, "quote_valid": quote_valid}


def parse_binary(raw: str) -> dict:
    result = parse_llm_records(
        raw, allowed_slots={"ALIGN": frozenset({1})},
        required=frozenset({("ALIGN", 1)}),
    )
    if result.issues or result.missing or len(result.records) != 1:
        return {"valid": False, "issues": [issue.reason for issue in result.issues]}
    parts = result.records[0].text.split("｜")
    if len(parts) != 2:
        return {"valid": False, "error": "field_count"}
    parsed: dict[str, str] = {}
    for name, item in zip(("SOURCE", "EVENT"), parts):
        label, separator, value = item.partition("=")
        if not separator or label != name or value not in {"yes", "no"}:
            return {"valid": False, "error": f"invalid_{name}"}
        parsed[name] = value
    return {"valid": True, "fields": parsed}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--cases", type=Path, default=CASES)
    parser.add_argument("--baseline", type=Path, default=BASELINE)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--seeds", type=int, nargs="+", default=[42, 43])
    parser.add_argument("--format", choices=("quote", "binary"), default="quote")
    args = parser.parse_args()
    case_bytes = args.cases.read_bytes()
    dataset = json.loads(case_bytes)
    case_ids = [case["id"] for case in dataset["cases"]]
    if len(case_ids) != len(set(case_ids)):
        raise ValueError("case IDs must be unique")
    baseline = json.loads(args.baseline.read_text(encoding="utf-8"))
    runtime = LlamaRuntimeConfig(**baseline["runtime"])
    evidence = {
        "cases_sha256": hashlib.sha256(case_bytes).hexdigest(),
        "cases_path": str(args.cases), "model": baseline["model"],
        "runtime": runtime.to_dict(), "prompt": PROMPT if args.format == "quote" else BINARY_PROMPT,
        "format": args.format,
        "seeds": args.seeds, "runs": [],
    }
    args.output.mkdir(parents=True, exist_ok=True)
    path = args.output / ("evidence.json" if args.format == "quote" else "evidence_binary.json")
    lifecycle = LlamaCppLifecycle()
    try:
        lifecycle.ensure_loaded(Path(baseline["model"]), runtime)
        for seed in args.seeds:
            for case in dataset["cases"]:
                payload = {"lyrics": case["lyrics"], "target": case["target"],
                           "change": case["change"]}
                raw, tokens, elapsed = _infer(
                    lifecycle, replace(runtime, seed=seed, max_tokens=128),
                    system=PROMPT if args.format == "quote" else BINARY_PROMPT,
                    payload=payload,
                    grammar=grammar() if args.format == "quote" else binary_grammar(),
                )
                parsed = parse(raw, case["change"]) if args.format == "quote" else parse_binary(raw)
                item = {"seed": seed, "case_id": case["id"],
                        "gold": {"source": case["source"], "event": case["event"]},
                        "payload": payload, "response": raw, "parsed": parsed,
                        "prompt_tokens": tokens, "elapsed_seconds": elapsed}
                evidence["runs"].append(item)
                path.write_text(json.dumps(evidence, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
                observed = parsed.get("fields", {})
                print(f"seed={seed} {case['id']} gold={case['source']}/{case['event']} "
                      f"got={observed.get('SOURCE')}/{observed.get('EVENT')} "
                      f"quote_valid={parsed.get('quote_valid')}", flush=True)
    finally:
        lifecycle.clear()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
