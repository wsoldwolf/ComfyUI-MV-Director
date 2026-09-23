"""Probe separate event/body Shot advances for the valid foxfire Scene (offline)."""

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
from tools.offline_scene_event_performance_probe import _infer, _quote

SOURCE = ROOT / "docs/assets/research/scene-event-performance-two-stage-2026-09-22/evidence.json"
TRACE = ROOT / "docs/assets/research/choreography-full-run-v4-2026-09-22/evidence.json"
PROMPT = """あなたは一つのSceneの二Shotを同時に計画する。EVENTとBODYは既に別々のLLMによって決定された原文であり、対象や意味を変更しない。
Shot1は対象の出来事を一度だけ映すevent。EVENT_STEPにはEVENT.CHANGEからRESULTへ至る狐火自身の可視変化を具体的に記す。BODY_STEPには人物の身体経路の最初の段階と同時反応を書く。狐火を人物の手から発生・保持・操作させない。
Shot2は顔と歌唱口のresponse。EVENT_STEP=なしで、狐火の出現を繰り返さず、BODY_STEPに前Shotで進んだ身体の落ち着きと視線・目・口の結果を書く。Shot2のFROMはShot1のTOから自然に続ける。新しい出来事、対象、Camera動作を書かない。
FROMとTOの主語は必ず人物とし、支持・体幹・腕・視線など人物の姿勢又は位置だけを記す。夜空、狐火、背景、光の結果をFROM/TOに書かない。Shot1のFROMはBODY.STARTの人物姿勢、Shot1のTOはアクセント時の人物姿勢、Shot2のFROMはその姿勢の続き、Shot2のTOはBODY.ENDの人物姿勢とする。対象の変化はEVENT_STEPだけで表す。
各Shotにつき実TAB区切り一行 STEP、slot番号、PHASE=...｜FROM=...｜EVENT_STEP=...｜BODY_STEP=...｜TO=...｜SHOW=...。指定された二行のみ。"""
FIELDS = ("PHASE", "FROM", "EVENT_STEP", "BODY_STEP", "TO", "SHOW")


def grammar() -> str:
    rows: list[str] = []
    for slot, phase, show in ((1, "event", "lyric_target"), (2, "response", "face_eyes_mouth")):
        parts = [_quote(f"STEP\t{slot}\tPHASE={phase}")]
        for field in FIELDS[1:-1]:
            parts.append(_quote("｜" + field + "="))
            parts.append(_quote("なし") if slot == 2 and field == "EVENT_STEP" else "cell")
        parts.append(_quote("｜SHOW=" + show))
        rows.append(" ".join(parts))
    return (
        "root ::= " + ' "\\n" '.join(rows) + ' "\\n"?\n'
        + r"cell ::= [^\x00-\x1f｜\\]{1,140}" + "\n"
    )


def parse(raw: str) -> dict:
    parsed = parse_llm_records(
        raw, allowed_slots={"STEP": frozenset({1, 2})},
        required=frozenset({("STEP", 1), ("STEP", 2)}),
    )
    result = {"valid": False, "issues": [issue.reason for issue in parsed.issues],
              "missing": [list(item) for item in parsed.missing]}
    if result["issues"] or result["missing"]:
        return result
    rows: dict[str, dict[str, str]] = {}
    for record in parsed.records:
        parts = record.text.split("｜")
        if len(parts) != len(FIELDS):
            result["error"] = "field count"
            return result
        row: dict[str, str] = {}
        for field, part in zip(FIELDS, parts):
            label, sep, value = part.partition("=")
            if label != field or not sep or not value:
                result["error"] = f"invalid {field}"
                return result
            row[field] = value
        rows[str(record.slot)] = row
    result.update({"valid": True, "rows": rows})
    return result


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, default=SOURCE)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    source = json.loads(args.source.read_text(encoding="utf-8"))
    trace = json.loads(TRACE.read_text(encoding="utf-8"))
    saved = next(json.loads(entry["payload"]) for entry in trace["trace"]
                 if entry["task"] == "scene-spine"
                 and json.loads(entry["payload"]).get("scene_number") == 14)
    runtime = LlamaRuntimeConfig(**source["runtime"])
    evidence = {"source": str(args.source), "model": source["model"],
                "runtime": runtime.to_dict(), "prompt": PROMPT, "runs": []}
    args.output.mkdir(parents=True, exist_ok=True)
    path = args.output / "evidence.json"
    lifecycle = LlamaCppLifecycle()
    try:
        lifecycle.ensure_loaded(Path(source["model"]), runtime)
        for run in source["runs"]:
            if run["scene"] != 14 or not run.get("combined_parsed", {}).get("valid"):
                continue
            payload = {"scene_number": 14, "lyric_lines": saved["lyric_lines"],
                       "event": run["event_response"], "body": run["body_response"],
                       "shot_slots": saved["slots"]}
            raw, tokens, elapsed = _infer(
                lifecycle, replace(runtime, seed=run["seed"], max_tokens=512),
                system=PROMPT, payload=payload, grammar=grammar(),
            )
            item = {"seed": run["seed"], "payload": payload, "response": raw,
                    "parsed": parse(raw), "prompt_tokens": tokens,
                    "elapsed_seconds": elapsed}
            evidence["runs"].append(item)
            path.write_text(json.dumps(evidence, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
            print(f"seed={run['seed']} valid={item['parsed']['valid']} elapsed={elapsed}s", flush=True)
    finally:
        lifecycle.clear()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
