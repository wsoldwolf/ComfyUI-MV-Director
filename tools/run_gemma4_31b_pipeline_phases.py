"""Reproduce bounded Gemma 4 31B pipeline comparisons from saved full-song calls.

P0 uses only saved data. P1-P3 use the same local GGUF and llama.cpp settings
as the full-song experiment. Results are isolated under docs/assets/research.
No production workflow, prompt, profile, or saved baseline is changed.
"""

from __future__ import annotations

import argparse
from collections import Counter
import copy
import hashlib
import json
from pathlib import Path
import re
import sys
import time

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from core.inference import LlamaCppLifecycle, LlamaRuntimeConfig
from core.planner.scene_author import _split_terminal_state


SOURCE = ROOT / "docs/assets/research/gemma4-31b-full-2026-09-25"
SUCCESS = ROOT / "docs/assets/research/gemma4-31b-scene5-2026-09-25"
DEST = ROOT / "docs/assets/research/gemma4-31b-pipeline-phases-2026-09-25"
MODEL = Path(r"C:\Users\owner\.lmstudio\models\unsloth\gemma-4-31B-it-GGUF\gemma-4-31B-it-Q4_K_S.gguf")
STAGES = ("event", "performance", "camera")


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def write_json(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def original_calls() -> dict[tuple[int, str], dict]:
    found: dict[tuple[int, str], dict] = {}
    for path in (SOURCE / "llm_calls").glob("scene-author-*.json"):
        item = json.loads(path.read_text(encoding="utf-8"))
        if item["request"].get("backend") != "direct":
            continue
        payload = json.loads(item["request"]["messages"][1]["content"])
        key = (payload["scene_number"], payload["task"].removeprefix("scene-author-"))
        if key in found:
            raise ValueError(f"duplicate direct call {key}")
        found[key] = {"file": path, "item": item, "payload": payload}
    if len(found) != 48 or any((scene, stage) not in found
                                for scene in range(1, 17) for stage in STAGES):
        raise ValueError("expected one direct call per stage per Scene")
    return found


def response_fields(response: str, kind: str, count: int) -> tuple[dict[str, str], dict[str, str]]:
    rows = response.strip().splitlines()
    if len(rows) != count:
        raise ValueError(f"{kind} has {len(rows)} lines, expected {count}")
    prose: dict[str, str] = {}
    states: dict[str, str] = {}
    for expected, row in enumerate(rows, 1):
        prefix = f"{kind}\t{expected}\t"
        if not row.startswith(prefix):
            raise ValueError(f"{kind} line {expected} is malformed: {row[:100]!r}")
        text, state = _split_terminal_state(row[len(prefix):])
        prose[str(expected)] = text
        states[str(expected)] = state
    return prose, states


def event_field(response: str, shot_count: int) -> tuple[int, str, str]:
    prose, states = response_fields(response, "EVENT", 1)
    match = re.fullmatch(r"SHOT=([1-9][0-9]*)｜(.+)", prose["1"])
    if not match or int(match.group(1)) > shot_count:
        raise ValueError(f"Event assignment invalid: {prose['1']!r}")
    return int(match.group(1)), match.group(2), states["1"]


def revised_event_system(system: str) -> str:
    source = "人物の演技、画角、Zoom、Arc、カメラ動作はこの担当の本文へ書かない。"
    target = ("手足の細かな振付、画角、Zoom、Arc、カメラ動作はこの担当の本文へ書かない。"
              "対象と人物の位置関係、必要な接近や接触とその可視の結果は出来事として書いてよい。")
    if system.count(source) != 1:
        raise ValueError("Event system prompt changed from frozen baseline")
    system = system.replace(source, target)
    anchor = "今回のoriginal_lyricsを優先する。"
    addition = ("前後のSceneにまたがって歌詞が一文になるとき、section_lyric_contextから"
                "今回の句に係る主語又は述語を読み、CUTでもその文法的な関係を保つ。"
                "比喩は歌詞に沿う象徴的な映像の対象として表してよい。"
                "現在Sceneの歌詞に直接対応する作者の候補は、一般的な背景要素より先に検討する。"
                "採用しない場合も新しい対象を背景の設備で代用しない。")
    if system.count(anchor) != 1:
        raise ValueError("Event state anchor changed from frozen baseline")
    return system.replace(anchor, anchor + addition)


def p0() -> None:
    calls = original_calls()
    old = calls[(5, "performance")]
    success_user = json.loads((SUCCESS / "scene5-gemma-user.txt").read_text(encoding="utf-8"))
    success_system = (SUCCESS / "system-performance.txt").read_text(encoding="utf-8")
    baseline_system = old["item"]["request"]["messages"][0]["content"]
    difference = {
        key: {"full": old["payload"].get(key), "successful_short": success_user.get(key)}
        for key in sorted(old["payload"].keys() | success_user.keys())
        if old["payload"].get(key) != success_user.get(key)
    }
    saved = json.loads((SOURCE / "planner-summary.json").read_text(encoding="utf-8"))["content"]
    summary = {
        "source_model_sha256": digest(MODEL),
        "source_plan_sha256": digest(SOURCE / "plan.json"),
        "source_template_sha256": digest(SOURCE / "template.md"),
        "source_direction_sha256": json.loads(
            (SOURCE / "input-manifest.json").read_text(encoding="utf-8"))["direction_sha256"],
        "direct_stage_calls": Counter(stage for scene, stage in calls),
        "adopted_events": len(saved["events"]),
        "adopted_performances": len(saved["actions"]),
        "adopted_cameras": len(saved["cameras"]),
        "motion_compositions": len(saved["motion_compositions"]),
        "successful_scene5_system_matches_full": success_system.strip() == baseline_system.strip(),
        "successful_scene5_differing_input_fields": difference,
        "scene5_full_performance_call": str(old["file"].relative_to(ROOT)).replace("\\", "/"),
        "scene5_success_response": str((SUCCESS / "scene5-gemma-performance.json").relative_to(ROOT)).replace("\\", "/"),
    }
    write_json(DEST / "p0-manifest.json", summary)
    print(f"P0 complete: 48 direct calls, 14 compositions, {len(difference)} changed Scene 5 input fields", flush=True)
    print("P0 changed fields: " + ", ".join(difference), flush=True)


class DirectGemma:
    def __init__(self) -> None:
        self.model_sha256 = digest(MODEL)
        self.lifecycle = LlamaCppLifecycle()
        self.config = LlamaRuntimeConfig(
            n_ctx=24576, max_tokens=2048, temperature=0.2,
            top_p=0.9, repetition_penalty=1.05, gpu_layers=-1,
            n_batch=512, keep_model_loaded=False, seed=2,
        )
        self.lifecycle.ensure_loaded(MODEL, self.config)

    def close(self) -> None:
        self.lifecycle.clear()

    def run(self, name: str, system: str, payload: dict, max_tokens: int) -> str:
        path = DEST / "calls" / f"{name}.json"
        user = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        request = {"system": system, "user": user, "max_tokens": max_tokens,
                   "temperature": 0.2, "top_p": 0.9, "repeat_penalty": 1.05,
                   "seed": 2, "n_ctx": 24576, "model_sha256": self.model_sha256}
        request_hash = hashlib.sha256(json.dumps(request, ensure_ascii=False,
                                      sort_keys=True).encode("utf-8")).hexdigest()
        if path.exists():
            existing = json.loads(path.read_text(encoding="utf-8"))
            if existing["request_hash"] != request_hash:
                raise ValueError(f"saved request changed: {path}")
            print(f"{name}: cache hit", flush=True)
            return existing["response"]
        print(f"{name}: inference started ({len(user)} input chars)", flush=True)
        started = time.monotonic()
        response = self.lifecycle.complete_chat(
            [{"role": "system", "content": system}, {"role": "user", "content": user}],
            LlamaRuntimeConfig(
                n_ctx=24576, max_tokens=max_tokens, temperature=0.2,
                top_p=0.9, repetition_penalty=1.05, gpu_layers=-1,
                n_batch=512, keep_model_loaded=False, seed=2,
            ),
        )
        if not response.strip():
            raise RuntimeError(f"{name} returned no visible response")
        write_json(path, {"request": request, "request_hash": request_hash,
                          "response": response, "elapsed_seconds": round(time.monotonic()-started, 3)})
        print(f"{name}: completed in {time.monotonic()-started:.1f}s", flush=True)
        return response


def p1(model: DirectGemma) -> None:
    calls = original_calls()
    for scene in (5, 6):
        source = calls[(scene, "performance")]
        payload = copy.deepcopy(source["payload"])
        original_composition = payload.pop("scheduled_motion_composition")
        system = source["item"]["request"]["messages"][0]["content"]
        response = model.run(f"p1-scene{scene}-performance-no-composition", system, payload, 2048)
        prose, states = response_fields(response, "PERFORMANCE", len(payload["slots"]))
        camera = calls[(scene, "camera")]
        camera_payload = copy.deepcopy(camera["payload"])
        camera_payload.pop("scheduled_motion_composition", None)
        camera_payload["accepted_performances"] = prose
        camera_system = camera["item"]["request"]["messages"][0]["content"]
        camera_response = model.run(f"p1-scene{scene}-camera-no-composition",
                                    camera_system, camera_payload, 1536)
        camera_prose, _ = response_fields(camera_response, "CAMERA", len(camera_payload["slots"]))
        write_json(DEST / f"p1-scene{scene}-summary.json", {
            "baseline_composition": original_composition,
            "baseline_performance": calls[(scene, "performance")]["item"]["response"],
            "without_composition_performance": prose,
            "without_composition_terminal": states,
            "baseline_camera": camera["item"]["response"],
            "without_composition_camera": camera_prose,
            "event_is_frozen": payload["accepted_event"] == source["payload"]["accepted_event"],
        })
    p1b_source = calls[(5, "performance")]
    p1b_system = (SUCCESS / "system-performance.txt").read_text(encoding="utf-8")
    p1b_payload = json.loads((SUCCESS / "scene5-gemma-user.txt").read_text(encoding="utf-8"))
    p1b_response = model.run("p1-scene5-success-contract-direct", p1b_system, p1b_payload, 2048)
    p1b_prose, _ = response_fields(p1b_response, "PERFORMANCE", len(p1b_payload["slots"]))
    write_json(DEST / "p1-scene5-success-contract-summary.json", {
        "same_model_as_full": True,
        "baseline_full_performance": p1b_source["item"]["response"],
        "earlier_api_success_performance": json.loads(
            (SUCCESS / "scene5-gemma-performance.json").read_text(encoding="utf-8"))["response"],
        "success_contract_direct_performance": p1b_prose,
    })
    print("P1 complete: 2 composition-off Performance+Camera pairs and 1 successful-contract Performance", flush=True)


def p2(model: DirectGemma) -> None:
    calls = original_calls()
    changed_states = {}
    for scene in (3, 4, 6, 7):
        original = calls[(scene, "event")]
        payload = copy.deepcopy(original["payload"])
        if scene in (4, 7) and payload["continuation"]:
            payload["previous_scene_state"] = changed_states[scene - 1]
        system = revised_event_system(original["item"]["request"]["messages"][0]["content"])
        response = model.run(f"p2-scene{scene}-event-relation", system, payload, 1024)
        shot, event, state = event_field(response, len(payload["shot_positions"]))
        changed_states[scene] = state
        write_json(DEST / f"p2-scene{scene}-event-summary.json", {
            "baseline": original["item"]["response"],
            "variant": response,
            "selected_shot": shot,
            "selected_event": event,
            "terminal_state": state,
            "continuation": payload["continuation"],
            "previous_scene_state": payload["previous_scene_state"],
            "system_prompt_sha256": hashlib.sha256(system.encode("utf-8")).hexdigest(),
        })
    print("P2 Event comparison complete for Scenes 3, 4, 6, 7", flush=True)


def p2b(model: DirectGemma) -> None:
    """One Scene call: each Shot may own one visible event and one performance."""
    calls = original_calls()
    system = (
        "あなたは歌唱MVの一つのScene全体を、時間順の映像として設計する。"
        "original_lyricsのShot位置とsection_lyric_contextの前後関係を読み、"
        "各Shotで必要な可視の出来事と、人物の身体演技を同じ応答で決める。"
        "EVENTはそのShotで初めて確立する場所、対象、変化と人物との関係を短く書く。"
        "別Shotの出来事を早く出さない。外部の可視変化が無ければ「なし」と書く。"
        "比喩に応じた象徴的な情景も使ってよい。"
        "前後のSceneにまたがる歌詞の主語と述語は、CUTを挟んでも歌詞としてつなげて読む。"
        "staging_candidates_optionalは現在の歌詞に合うものを優先して検討するが、"
        "作者固定の演出と違って採用は任意である。背景一覧の一般的な設備で歌詞固有の対象を代用しない。"
        "PERFORMANCEはEVENTと歌詞へ人物がどう反応し、支持・体幹・腕・視線・表情がどう変わるかを"
        "Sceneを通す一つの身体フレーズとして書く。"
        "対象を扱うだけの説明に縮めず、理由のない全身移動、突然の切り返しを要求しない。"
        "EventとPerformanceの本文にCamera指示を入れない。"
        "出力はShot数分の EVENT<TAB>番号<TAB>本文 を番号順に、その次にShot数分の"
        " PERFORMANCE<TAB>番号<TAB>本文 を番号順に出す。"
        "余分な行、説明、見出し、Markdown、END_STATEを出さない。"
    )
    for scene in (3, 4, 6, 7):
        event = calls[(scene, "event")]
        performance = calls[(scene, "performance")]
        payload = copy.deepcopy(event["payload"])
        payload["task"] = "scene-author-event-performance"
        payload["scene_motion"] = performance["payload"]["scene_motion"]
        payload["previous_performance_state"] = performance["payload"]["previous_scene_state"]
        payload["slots"] = [
            {"slot": item["shot"], "position": item}
            for item in payload["shot_positions"]
        ]
        payload.pop("event_position_retry", None)
        count = len(payload["slots"])
        response = model.run(f"p2b-scene{scene}-joint-by-shot", system, payload, 3072)
        lines = [line for line in response.splitlines() if line.strip()]
        if len(lines) != 2 * count:
            raise ValueError(f"Scene {scene}: joint result has {len(lines)} lines, expected {2 * count}")
        fields: dict[tuple[str, int], str] = {}
        for row in lines:
            match = re.fullmatch(r"(EVENT|PERFORMANCE)\t([1-9][0-9]*)\t(.+)", row)
            if not match:
                raise ValueError(f"Scene {scene}: malformed joint line {row[:100]!r}")
            key = (match.group(1), int(match.group(2)))
            if key in fields or not 1 <= key[1] <= count:
                raise ValueError(f"Scene {scene}: duplicate or out-of-range {key}")
            fields[key] = match.group(3)
        if any((kind, index) not in fields
               for kind in ("EVENT", "PERFORMANCE") for index in range(1, count + 1)):
            raise ValueError(f"Scene {scene}: missing joint field")
        write_json(DEST / f"p2b-scene{scene}-summary.json", {
            "original_event": event["item"]["response"],
            "original_performances": performance["item"]["response"],
            "joint_events": [fields["EVENT", index] for index in range(1, count + 1)],
            "joint_performances": [fields["PERFORMANCE", index] for index in range(1, count + 1)],
            "no_fixed_motion_composition": True,
            "system_prompt_sha256": hashlib.sha256(system.encode("utf-8")).hexdigest(),
        })
    print("P2b joint Event/Performance comparison complete", flush=True)


def p3(model: DirectGemma) -> None:
    sample = {
        "subject": (
            "人物は白い足袋と赤い鼻緒の黒い木下駄を着用する。",
            "The subject wears white tabi socks and black wooden geta with red straps."
        ),
        "camera": (
            "顔と両手を見せるため、Arc Shotで側面へ回り込み、Zoom Inする。",
            "Arc Shot and Zoom In"
        ),
        "lyric": (
            "歌詞「苔へと還る」に合わせ、参道脇の大樹の根元の苔を指先で撫でる。",
            "moss at the base of a large tree beside the path"
        ),
    }
    system = (
        "Translate the entire Japanese field into one concise natural English sentence for an MV video prompt. "
        "Use the full sentence context, preserve the action, temporal order, all spatial relationships, "
        "and the exact camera instruction names. Keep quoted song lyrics inside the existing <d>[Japanese]..."
        "</d> markers without adding any placeholder. Return only JSON with a key translations containing "
        "one English string. No explanations."
    )
    for name, (source, expectation) in sample.items():
        wrapped = re.sub(r"「([^「」]*)」", r"<d>[Japanese]\1</d>", source)
        response = model.run(f"p3-translation-full-field-{name}", system, {"texts": [wrapped]}, 1024)
        protocol_violations = []
        body = response.strip()
        if body.startswith("```json\n") and body.endswith("\n```"):
            protocol_violations.append("markdown_fence")
            body = body[len("```json\n"):-len("\n```")]
        try:
            translated = json.loads(body)["translations"]
        except (json.JSONDecodeError, KeyError, TypeError) as exc:
            raise ValueError(f"translation protocol failure for {name}: {response!r}") from exc
        if isinstance(translated, str):
            protocol_violations.append("scalar_instead_of_array")
            translated = [translated]
        if len(translated) != 1 or not isinstance(translated[0], str):
            raise ValueError(f"translation cardinality failure for {name}")
        write_json(DEST / f"p3-translation-{name}-summary.json", {
            "source": source, "provided_to_model": wrapped, "translation": translated[0],
            "expected_semantics": expectation,
            "has_placeholder": "[placeholder]" in translated[0],
            "has_japanese_lyric": "<d>[Japanese]" in translated[0],
            "protocol_violations": protocol_violations,
        })
    print("P3 full-field translation probe complete", flush=True)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("phase", choices=("p0", "p1", "p2", "p2b", "p3"))
    args = parser.parse_args()
    if args.phase == "p0":
        p0()
        return
    model = DirectGemma()
    try:
        {"p1": p1, "p2": p2, "p2b": p2b, "p3": p3}[args.phase](model)
    finally:
        model.close()


if __name__ == "__main__":
    main()
