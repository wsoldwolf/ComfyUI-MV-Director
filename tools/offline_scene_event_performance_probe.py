"""Probe a dual-lane Scene plan and an independent semantic audit with saved inputs.

This is research-only: no production Planner, EMD, or workflow is changed.
"""

from __future__ import annotations

import argparse
from dataclasses import replace
import hashlib
import json
from pathlib import Path
import sys
import time

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from core.inference import LlamaCppLifecycle, LlamaRuntimeConfig
from core.inference.budget import build_context_budget
from core.protocols.llm_records import parse_llm_records
from tools.offline_motion_template_input_probe import parse_motion_templates
from tools.offline_motion_template_pre_cue_probe import _saved_requests

SOURCE = ROOT / "docs/assets/research/choreography-full-run-v4-2026-09-22/evidence.json"
TEMPLATES = ROOT / "docs/assets/research/motion-template-input-probe-2026-09-22/motion_templates.emd.md"
SCENES = (11, 14)
FIELDS = {
    "EVENT": ("EVIDENCE", "TARGET", "MODE", "ANCHOR", "CONTACT_POINT", "CHANGE", "RESULT"),
    "BODY": ("START", "PATH", "ACCENT", "END", "SYNC"),
}
MODES = frozenset({"none", "observe", "contact", "autonomous"})
AUDIT_CODES = (
    "TARGET_MISMATCH", "UNSUPPORTED_TARGET", "EFFECT_CAUSALITY",
    "EVENT_MISSING", "SYNC_CONFLICT", "CONTACT_POINT_MISSING",
)
PLAN_PROMPT = """あなたはアニメMVのScene演出家。現在Sceneの歌詞に対し、対象の出来事と人物の身体演技を別々の責務として同時に計画する。
EVENTは現在Sceneの原歌詞・作者指示のみを対象の出典にする。scene_contextは背景の配置参考であり新しい対象の出典ではない。MODEはnone/observe/contact/autonomous。歌詞が社を語るだけで社へ接触させない。接触を選ぶならCONTACT_POINTは必ずTARGETの実際の一部とし、CHANGEにその対象への一回の接触を書く。床や別の物へ触れない。autonomousの光や狐火は人物の手から出さず、自律した出現・空間経路・可視結果をCHANGEとRESULTに書く。対象のない歌詞ならTARGET等に「なし」を書ける。
BODYはDirection motionと候補を任意の着想にし、STARTからPATH、ACCENT、ENDまでを一続きに書く。候補の選択・融合・改変・不使用は自由。候補から場所や小道具や接触対象を輸入しない。SYNCにはEVENTが起こる瞬間と人物の視線・手・体幹の関係を明記する。人物が外部現象を操作するとは書かない。長い候補文の複写や、肩と腕の単純な上げ下げだけで済ませない。
各Sceneへ実TAB区切りの二行のみを出す。第一行は EVENT、Scene番号、EVIDENCE=...｜TARGET=...｜MODE=...｜ANCHOR=...｜CONTACT_POINT=...｜CHANGE=...｜RESULT=...。第二行は BODY、同じScene番号、START=...｜PATH=...｜ACCENT=...｜END=...｜SYNC=...。MODE以外の欄は日本語。接触しないときCONTACT_POINT=なし。説明、Markdown、JSON、追加行は出さない。"""
AUDIT_PROMPT = """あなたは独立したScene整合性監査者。創作せず、現在Sceneの原歌詞・作者指示とEVENT/BODYの二行を比較する。候補文や長いprofileは見ない。
次のうち最初に見つけた明白な違反だけを返す。TARGET_MISMATCH: 接触又は作用する実物がTARGETとは別。UNSUPPORTED_TARGET: 原歌詞・作者指示に対象の根拠がない。EFFECT_CAUSALITY: autonomousの現象を人物が発生・保持・操作する。EVENT_MISSING: CHANGEに対象自身の出来事がない。SYNC_CONFLICT: BODYの同期がEVENTと矛盾する。CONTACT_POINT_MISSING: contactなのに対象の一部への接触点がない。明白な違反がなければOK。社への接触そのものは必須ではない。候補を使わないことや身体表現の小ささは違反ではない。
実TAB区切りの一行だけ: AUDIT、1、OK または REJECT:理由コード。説明や追加行を出さない。"""


def _quote(value: str) -> str:
    return json.dumps(value, ensure_ascii=False)


def plan_grammar(scene: int) -> str:
    if type(scene) is not int or scene < 1:
        raise ValueError("scene must be positive")
    rows: list[str] = []
    for kind in ("EVENT", "BODY"):
        parts = [_quote(f"{kind}\t{scene}\t")]
        for index, field in enumerate(FIELDS[kind]):
            parts.append(_quote(("" if index == 0 else "｜") + field + "="))
            parts.append("mode" if field == "MODE" else "cell")
        rows.append(" ".join(parts))
    return (
        "root ::= " + ' "\\n" '.join(rows) + ' "\\n"?\n'
        + "mode ::= " + " | ".join(_quote(mode) for mode in sorted(MODES)) + "\n"
        + r"cell ::= [^\x00-\x1f｜]+" + "\n"
    )


def audit_grammar() -> str:
    outcomes = ("OK", *(f"REJECT:{reason}" for reason in AUDIT_CODES))
    return (
        "root ::= " + _quote("AUDIT\t1\t") + " outcome " + ' "\\n"?\n'
        + "outcome ::= " + " | ".join(_quote(value) for value in outcomes) + "\n"
    )


def _fields(text: str, names: tuple[str, ...]) -> dict[str, str]:
    parts = text.split("｜")
    if len(parts) != len(names):
        raise ValueError(f"expected {len(names)} fields")
    result: dict[str, str] = {}
    for expected, part in zip(names, parts):
        label, separator, value = part.partition("=")
        if not separator or label != expected or not value.strip():
            raise ValueError(f"invalid {expected} field")
        result[label] = value.strip()
    return result


def parse_plan(raw: str, scene: int, lyrics: list[str]) -> dict:
    parsed = parse_llm_records(
        raw,
        allowed_slots={"EVENT": frozenset({scene}), "BODY": frozenset({scene})},
        required=frozenset({("EVENT", scene), ("BODY", scene)}),
    )
    result: dict = {
        "valid": False,
        "issues": [issue.reason for issue in parsed.issues],
        "missing": [list(item) for item in parsed.missing],
    }
    if result["issues"] or result["missing"]:
        return result
    try:
        rows = {record.record_type: record.text for record in parsed.records}
        event = _fields(rows["EVENT"], FIELDS["EVENT"])
        body = _fields(rows["BODY"], FIELDS["BODY"])
        if event["MODE"] not in MODES:
            raise ValueError("unknown mode")
        if event["EVIDENCE"] != "なし" and not any(
            event["EVIDENCE"] in lyric for lyric in lyrics
        ):
            raise ValueError("evidence is not a current lyric")
        if event["TARGET"] != "なし" and event["TARGET"] not in event["EVIDENCE"]:
            raise ValueError("target is not in evidence")
        if event["MODE"] == "contact" and event["CONTACT_POINT"] == "なし":
            raise ValueError("contact point missing")
        if event["MODE"] != "contact" and event["CONTACT_POINT"] != "なし":
            raise ValueError("unexpected contact point")
        result.update({"valid": True, "event": event, "body": body})
    except (KeyError, ValueError) as exc:
        result["validation_error"] = str(exc)
    return result


def parse_audit(raw: str) -> dict:
    parsed = parse_llm_records(
        raw, allowed_slots={"AUDIT": frozenset({1})},
        required=frozenset({("AUDIT", 1)}),
    )
    values = [record.text for record in parsed.records]
    allowed = {"OK", *(f"REJECT:{code}" for code in AUDIT_CODES)}
    valid = not parsed.issues and not parsed.missing and len(values) == 1 and values[0] in allowed
    return {"valid": valid, "verdict": values[0] if valid else "", "issues": [issue.reason for issue in parsed.issues]}


def _infer(lifecycle: LlamaCppLifecycle, config: LlamaRuntimeConfig, *,
           system: str, payload: dict, grammar: str) -> tuple[str, int, float]:
    user = "/no_think\n" + json.dumps(payload, ensure_ascii=False, separators=(",", ":"))
    count = lifecycle.count_serialized_prompt(system + "\n" + user)
    build_context_budget(count.count, config.max_tokens, lifecycle.effective_n_ctx or config.n_ctx,
                         estimated=count.estimated)
    started = time.perf_counter()
    raw = lifecycle.complete_chat(
        [{"role": "system", "content": system}, {"role": "user", "content": user}],
        config, grammar=grammar,
    )
    return raw, count.count, round(time.perf_counter() - started, 3)


def _audit_controls() -> list[dict]:
    return [
        {"name": "shrine_valid_observe", "scene": 11, "lyrics": ["またこの社へ続くなら"],
         "plan": "EVENT\t11\tEVIDENCE=またこの社へ続くなら｜TARGET=社｜MODE=observe｜ANCHOR=参道の先の社｜CONTACT_POINT=なし｜CHANGE=人物が社を見上げ、屋根の輪郭が月明かりに現れる｜RESULT=社の姿を見届ける\nBODY\t11\tSTART=両足支持で腕を低く置く｜PATH=胸郭を起こし、視線に遅れて片腕を斜めへ通す｜ACCENT=社を見上げて一拍止める｜END=腕を静かに戻す｜SYNC=社の輪郭を認めた瞬間に視線を上げる", "expect": "OK"},
        {"name": "shrine_bad_other_object", "scene": 11, "lyrics": ["またこの社へ続くなら"],
         "plan": "EVENT\t11\tEVIDENCE=またこの社へ続くなら｜TARGET=社｜MODE=contact｜ANCHOR=社の前｜CONTACT_POINT=石畳｜CHANGE=右手で石畳に触れる｜RESULT=石畳から手を離す\nBODY\t11\tSTART=両足支持｜PATH=右手を下へ伸ばす｜ACCENT=石畳に触れる｜END=手を戻す｜SYNC=石畳に触れた瞬間に身体を傾ける", "expect": "REJECT:TARGET_MISMATCH"},
        {"name": "foxfire_valid_autonomous", "scene": 14, "lyrics": ["狐火は祈り"],
         "plan": "EVENT\t14\tEVIDENCE=狐火は祈り｜TARGET=狐火｜MODE=autonomous｜ANCHOR=人物の周囲の空間｜CONTACT_POINT=なし｜CHANGE=狐火が人物の周囲を自ら巡り、木々へ光を落とす｜RESULT=光の輪が遠ざかる\nBODY\t14\tSTART=両足支持で視線を伏せる｜PATH=胸郭を起こし、左右の腕を異なる高さへ開く｜ACCENT=狐火を追って目を見開く｜END=腕を緩めて息を落とす｜SYNC=狐火が巡り始める瞬間に視線を上げる", "expect": "OK"},
        {"name": "foxfire_bad_hand_generated", "scene": 14, "lyrics": ["狐火は祈り"],
         "plan": "EVENT\t14\tEVIDENCE=狐火は祈り｜TARGET=狐火｜MODE=autonomous｜ANCHOR=人物の手の中｜CONTACT_POINT=なし｜CHANGE=人物が手から狐火を発生させて空へ放つ｜RESULT=狐火が手元から上がる\nBODY\t14\tSTART=腕を下げる｜PATH=右手を前へ伸ばす｜ACCENT=手から狐火を放つ｜END=手を戻す｜SYNC=右手を伸ばすことで狐火を発生させる", "expect": "REJECT:EFFECT_CAUSALITY"},
    ]


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--source", type=Path, default=SOURCE)
    parser.add_argument("--templates", type=Path, default=TEMPLATES)
    parser.add_argument("--seeds", type=int, nargs="+", default=[42, 43])
    args = parser.parse_args()
    source_bytes = args.source.read_bytes()
    template_bytes = args.templates.read_bytes()
    source = json.loads(source_bytes)
    templates = parse_motion_templates(template_bytes.decode("utf-8"))
    requests = _saved_requests(source["trace"], "visual-beats")
    runtime = LlamaRuntimeConfig(**source["runtime"])
    evidence = {
        "source_sha256": hashlib.sha256(source_bytes).hexdigest(),
        "templates_sha256": hashlib.sha256(template_bytes).hexdigest(),
        "model": source["model"], "runtime": runtime.to_dict(),
        "scenes": list(SCENES), "seeds": args.seeds,
        "plan_prompt": PLAN_PROMPT, "audit_prompt": AUDIT_PROMPT,
        "runs": [], "audit_controls": [],
    }
    args.output.mkdir(parents=True, exist_ok=True)
    path = args.output / "evidence.json"
    lifecycle = LlamaCppLifecycle()
    try:
        lifecycle.ensure_loaded(Path(source["model"]), runtime)
        for seed in args.seeds:
            for scene in SCENES:
                saved = json.loads(requests[scene]["payload"])
                slot = next(slot for slot in saved["slots"] if slot["scene_number"] == scene)
                lyrics = [item["text"] for item in slot["lyrics"]]
                input_payload = {
                    "scene_number": scene, "lyrics": slot["lyrics"],
                    "author_body": slot.get("author_body", []),
                    "discovered_cues": slot.get("discovered_cues", []),
                    "scene_context": saved.get("scene_context", {}),
                    "direction_motion": saved["direction"]["motion"],
                    "motion_templates": list(templates),
                }
                config = replace(runtime, seed=seed, max_tokens=min(runtime.max_tokens, 768))
                raw, tokens, elapsed = _infer(
                    lifecycle, config, system=PLAN_PROMPT, payload=input_payload,
                    grammar=plan_grammar(scene),
                )
                parsed = parse_plan(raw, scene, lyrics)
                item = {"seed": seed, "scene": scene, "task": "dual-plan", "payload": input_payload,
                        "response": raw, "parsed": parsed, "prompt_tokens": tokens, "elapsed_seconds": elapsed}
                evidence["runs"].append(item)
                path.write_text(json.dumps(evidence, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
                print(f"seed={seed} scene={scene} dual-plan valid={parsed['valid']} elapsed={elapsed}s", flush=True)
                if not parsed["valid"]:
                    continue
                audit_payload = {"scene_number": scene, "lyrics": lyrics,
                                 "author_body": slot.get("author_body", []), "plan": raw}
                audit_raw, audit_tokens, audit_elapsed = _infer(
                    lifecycle, replace(runtime, seed=seed, max_tokens=96),
                    system=AUDIT_PROMPT, payload=audit_payload,
                    grammar=audit_grammar(),
                )
                audit_item = {"seed": seed, "scene": scene, "task": "semantic-audit",
                              "payload": audit_payload, "response": audit_raw,
                              "parsed": parse_audit(audit_raw), "prompt_tokens": audit_tokens,
                              "elapsed_seconds": audit_elapsed}
                evidence["runs"].append(audit_item)
                path.write_text(json.dumps(evidence, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
                print(f"seed={seed} scene={scene} audit={audit_item['parsed']['verdict']} elapsed={audit_elapsed}s", flush=True)
        for case in _audit_controls():
            payload = {"scene_number": case["scene"], "lyrics": case["lyrics"],
                       "author_body": [], "plan": case["plan"]}
            raw, tokens, elapsed = _infer(
                lifecycle, replace(runtime, seed=42, max_tokens=96),
                system=AUDIT_PROMPT, payload=payload, grammar=audit_grammar(),
            )
            item = {"name": case["name"], "expected": case["expect"], "payload": payload,
                    "response": raw, "parsed": parse_audit(raw), "prompt_tokens": tokens,
                    "elapsed_seconds": elapsed}
            evidence["audit_controls"].append(item)
            path.write_text(json.dumps(evidence, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
            print(f"control={case['name']} expected={case['expect']} got={item['parsed']['verdict']}", flush=True)
    finally:
        lifecycle.clear()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
