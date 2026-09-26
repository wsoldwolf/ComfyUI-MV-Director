"""Offline Gemma 4 31B composition-choice probe on frozen P6 Scene outputs.

This does not alter an EMD or any production workflow. It tests whether one
bounded judgement can replace scene-number cycling without changing prose.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
import re
import sys

from core.direction.profiles import MOTION_TEMPLATES
from core.emd import parse_emd
from tools import run_gemma4_31b_full as base


RESEARCH = Path(r"E:\ComfyUI\projects\ComfyUI-MV-Director-research\docs\assets\research")
SOURCE = RESEARCH / "gemma4-31b-post-author-full-2026-09-25"
DEST = RESEARCH / "gemma4-31b-composition-audit-probe-2026-09-25"
SCENES = (6, 8, 9, 15)
PROFILE = "anime_scene_composed_mv"
GRAMMAR = 'root ::= "CHOICE\\t1\\t" [0-3] "\\n"?\n'
SYSTEM = (
    "あなたは歌唱MVの任意モーション補完を選ぶ監査担当である。"
    "各Shotの原歌詞、確定Event、人物Performance、Cameraを一つのSceneの時間順に読む。"
    "target_shotの既存Performance文は変更・削除できず、候補文は同じShotに後から独立した文として追加される。"
    "候補0は追加なし、候補1〜3は提示された文そのものを表す。"
    "既存の動きと物理的に両立し、歌詞と撮影の中で意味があり、前後Shotの位置と身体状態がつながる候補を一つ選ぶ。"
    "時間順に成立する短い反動や重心の戻りは矛盾と決めつけない。"
    "Cameraが脚を接写しなくても体幹と表情に現れる動きは採用できる。"
    "逆に明示された移動を同時に打ち消す候補や、Shotの長さで収まらない候補は選ばない。"
    "全候補が適合しなければ0を選ぶ。候補を採用すること自体を目的にしない。"
    "人物の演技やCameraの新しい文章は生成しない。"
    "出力はCHOICE<TAB>1<TAB>番号の一行のみ。番号は0、1、2、3のいずれか。"
)
COMPATIBILITY_GRAMMAR = (
    'root ::= "AUDIT\\t1\\t" ("PASS" | "REJECT") "｜理由=" char+ "\\n"?\n'
    'char ::= [^\\x00-\\x1f]\n'
)
COMPATIBILITY_SYSTEM = (
    "あなたは歌唱MVの後段モーション補完について、明確な物理矛盾だけを監査する。"
    "候補は確定済みPerformanceの文を置き換えず、そのShotへ追加される。"
    "同じShotの時間順に、準備、主動作、反動又は着地として併存できればPASSとする。"
    "既存の演技が上半身や表情だけでも、短い支持移動は独立した身体アクセントとして成立し得る。"
    "Cameraが脚を接写しないことだけで棄却しない。"
    "同じ時間に反対方向へ進むなど、明示された移動を打ち消し、尺内で前後にも配置できない場合だけREJECTとする。"
    "候補が好みか、劇的か、必要不可欠かは判定しない。確定済み文を修正しない。"
    "出力はAUDIT<TAB>1<TAB>PASS又はREJECT｜理由=短い日本語の一行のみ。"
)
RETRY_GRAMMAR = (
    'root ::= "RETRY\\t1\\t" char+ "\\n"?\n'
    'char ::= [^\\x00-\\x1f]\n'
)
RETRY_SYSTEM = (
    "あなたは歌唱MVの人物演技を再推論する振付家である。"
    "今回変更できるのはtarget_shotのLLM生成Performance本文だけである。"
    "作者が直接書いた確定指示、Event、Camera、歌詞、他ShotのPerformanceは変更しない。"
    "提示されたoptional_compositionは任意の身体補完であり、作者の確定指示ではない。"
    "まず同じShotの動作を時間順に組み立て、補完と矛盾しない一続きの人物演技を再生成する。"
    "Sceneの前後Shotの身体状態、対象との位置、Cameraの画角も保つ。"
    "補完文をそのまま複写せず、人物の感情、視線、腕と体幹の反応を歌詞に合わせて書く。"
    "物理的に両立しない場合でも元のPerformanceを無理に守ろうとせず、"
    "変更可能な本文を新たに書き直す。ただし確定指示は改変しない。"
    "撮影指示、解説、Markdown、END_STATE、改行を含めない。"
    "出力はRETRY<TAB>1<TAB>日本語本文の一行のみ。"
)
CHOICE_RETRY_SYSTEM = (
    "あなたは歌唱MVの任意モーション補完だけを選び直す。"
    "元のPerformance、Event、Camera、作者の確定指示は一字も変更できない。"
    "現在の候補は動作が衝突する疑いがあるため、別候補を一度だけ検討する。"
    "各候補はtarget_shotのPerformanceの後に追加される独立した文である。"
    "既存の移動方向、対象への接近・通過、前後Shotとの接続、Cameraの画角を保つ。"
    "候補を成立させるために既存Performanceの意味を変えて解釈しない。"
    "候補0は補完なし、1〜3は提示された原文である。"
    "少なくとも一つ自然に共存できる候補があればその番号を選び、"
    "どれも無理な場合だけ0を選ぶ。現在の候補は再選択しない。"
    "出力はCHOICE<TAB>1<TAB>番号の一行のみ。"
)
UTILITY_SYSTEM = (
    "あなたは歌唱MVの任意モーション補完の編集者である。"
    "Sceneの歌詞、Event、既存Performance、Cameraと前後Shotを時間順に読む。"
    "元のPerformanceとCameraは完成済みであり、そのままでも成立する。"
    "候補0は補完なし。候補1〜3はtarget_shotに追加する原文である。"
    "動作が物理的に両立するだけでは採用理由にならない。"
    "既存の動きが単調で、候補により画面上で異なる身体アクセントが明瞭に増し、"
    "歌詞・Event・Cameraの流れを改善する時だけ候補を一つ選ぶ。"
    "既存Performanceが十分なら0を選ぶ。補完による歩行の重複、不要な反転、"
    "Cameraだけの旋回を人物の自転へ変えることは避ける。"
    "静かなSceneに有効な動きまで一律に棄却せず、候補なしも一律に優先しない。"
    "確定済み本文の意味を候補のために読み替えない。"
    "出力はCHOICE<TAB>1<TAB>番号の一行のみ。"
)
GUARDED_RESELECTION_SYSTEM = (
    "あなたは歌唱MVの任意モーション補完を最小限だけ見直す編集者である。"
    "original_lyrics、Event、既存Performance、CameraをSceneの時間順に読む。"
    "現在の補完は仮採用済みで、原則としてそのまま維持する。"
    "補完は既存Performanceの後に追加される独立した一文であり、"
    "元のPerformance、Event、Camera、作者確定指示は変更しない。"
    "現在の補完が既存の移動方向、対象への接近・通過、Shot間の支持・位置、"
    "撮影される身体動作と明確に噛み合わない時だけ、別候補へ一度選び直す。"
    "例えば前方の対象へ進むSceneに、後退や方向転換を強調する補完を足すと、"
    "理論上は順序付け可能でもSceneの主動作がぼやけることがある。"
    "単なる好み、理想的な自然さ、動作量の多寡だけでは変更しない。"
    "別候補が明確に改善するならその番号を選ぶ。どれも噛み合わない時だけ0を選ぶ。"
    "現在の候補が十分成立するなら、その番号を維持する。"
    "出力はCHOICE<TAB>1<TAB>番号の一行のみ。"
)
NO_DROP_GRAMMAR = 'root ::= "CHOICE\\t1\\t" [1-3] "\\n"?\n'
NO_DROP_SYSTEM = (
    "あなたは歌唱MVの任意モーション補完を最小限だけ選び直す。"
    "現在の補完は採用済みで、基本は維持する。補完なしという選択肢は今回ない。"
    "原歌詞、Event、既存Performance、Cameraと前後Shotを時間順に読む。"
    "候補文は元のPerformanceへ別文として追加される。元の文は変更できない。"
    "H3は短い荷重・切り返しから接近や躍動を描くことがあり、"
    "文章上の見かけの逆方向だけで現在の補完を棄却しない。"
    "別候補が元のSceneの対象、身体アクセント、Cameraとの連動を"
    "明瞭に良くすると判断できる場合だけ、その別候補に変更する。"
    "判断できなければ現在の番号を維持する。"
    "作者の確定指示と既存Performance・Event・Cameraは変更しない。"
    "出力はCHOICE<TAB>1<TAB>番号の一行のみ。"
)


def _digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _lookup(rows: list[list[object]]) -> dict[tuple[int, int], str]:
    return {(int(scene), int(shot)): str(text) for scene, shot, text in rows}


def main() -> None:
    DEST.mkdir(parents=True, exist_ok=True)
    base.DEST = DEST
    path = SOURCE / "planned.md"
    summary_path = SOURCE / "planner-summary.json"
    document = parse_emd(path.read_text(encoding="utf-8"))
    content = json.loads(summary_path.read_text(encoding="utf-8"))["content"]
    actions = _lookup(content["actions"])
    cameras = _lookup(content["cameras"])
    events = _lookup(content["events"])
    compositions = {int(row[0]): row for row in content["motion_compositions"]}
    templates = MOTION_TEMPLATES[PROFILE]
    if len(templates) != 3:
        raise ValueError("The frozen probe expects three profile templates")
    base.write_json(DEST / "source-manifest.json", {
        "source_emd": str(path), "source_emd_sha256": _digest(path),
        "planner_summary": str(summary_path),
        "planner_summary_sha256": _digest(summary_path),
        "profile": PROFILE, "scenes": list(SCENES),
        "model": str(base.MODEL_PATH), "seed": 2,
        "system_prompt_sha256": hashlib.sha256(SYSTEM.encode("utf-8")).hexdigest(),
    })
    requests = []
    for number in SCENES:
        scene = next(scene for scene in document.scenes if scene.scene_number == number)
        composition = compositions[number]
        target = int(composition[1])
        shots = []
        for index, shot in enumerate(scene.shots, 1):
            end_ms = scene.shots[index].start_ms if index < len(scene.shots) else scene.end_ms
            shots.append({
                "shot": index,
                "duration_ms": end_ms - shot.start_ms,
                "lyrics": [lyric.text for lyric in shot.lyric_annotations],
                "event": events.get((number, index), "なし"),
                "performance": actions[(number, index)],
                "camera": cameras[(number, index)],
            })
        requests.append({
            "scene": number,
            "target_shot": target,
            "shots": shots,
            "candidates": {str(index): text for index, text in enumerate(templates, 1)},
            "old_cyclic_choice": int(composition[3]),
        })
    base.write_json(DEST / "audit-inputs.json", requests)
    chat = base.CachedChat()
    decisions = []
    compatibility = []
    try:
        for request in requests:
            answer = chat.complete(
                kind=f"composition-audit-scene{request['scene']}",
                system=SYSTEM,
                user=json.dumps(request, ensure_ascii=False, separators=(",", ":")),
                max_tokens=32,
                temperature=0.1,
                grammar=GRAMMAR,
            ).strip()
            match = re.fullmatch(r"CHOICE\t1\t([0-3])", answer)
            if match is None:
                raise ValueError(f"Invalid audit response for Scene {request['scene']}: {answer!r}")
            selected = int(match.group(1))
            decisions.append({
                "scene": request["scene"],
                "target_shot": request["target_shot"],
                "cyclic_choice": request["old_cyclic_choice"],
                "audited_choice": selected,
                "changed": selected != request["old_cyclic_choice"],
                "response": answer,
            })
            print(f"Scene {request['scene']}: cyclic={request['old_cyclic_choice']} "
                  f"audited={selected}", flush=True)
        for request in requests:
            current = request["old_cyclic_choice"]
            compatibility_request = {
                "scene": request["scene"],
                "target_shot": request["target_shot"],
                "shots": request["shots"],
                "proposed_composition": request["candidates"][str(current)],
            }
            answer = chat.complete(
                kind=f"composition-compatibility-scene{request['scene']}",
                system=COMPATIBILITY_SYSTEM,
                user=json.dumps(compatibility_request, ensure_ascii=False,
                                separators=(",", ":")),
                max_tokens=128,
                temperature=0.1,
                grammar=COMPATIBILITY_GRAMMAR,
            ).strip()
            match = re.fullmatch(r"AUDIT\t1\t(PASS|REJECT)｜理由=([^\n]+)", answer)
            if match is None:
                raise ValueError(f"Invalid compatibility response for Scene {request['scene']}: {answer!r}")
            compatibility.append({
                "scene": request["scene"],
                "target_shot": request["target_shot"],
                "cyclic_choice": current,
                "verdict": match.group(1),
                "reason": match.group(2),
                "response": answer,
            })
            print(f"Scene {request['scene']}: compatibility={match.group(1)} "
                  f"reason={match.group(2)}", flush=True)
    finally:
        chat.close()
    base.write_json(DEST / "decisions.json", decisions)
    base.write_json(DEST / "compatibility-decisions.json", compatibility)


def retry_scene15() -> None:
    """Retry only generated Performance; leave all fixed instructions intact."""
    DEST.mkdir(parents=True, exist_ok=True)
    base.DEST = DEST
    requests = json.loads((DEST / "audit-inputs.json").read_text(encoding="utf-8"))
    request = next(item for item in requests if item["scene"] == 15)
    target = request["target_shot"]
    payload = {
        "scene": 15,
        "target_shot": target,
        "shots": request["shots"],
        "optional_composition": request["candidates"][str(request["old_cyclic_choice"])],
        "retry_reason": (
            "元のPerformanceは鳥居を前進してくぐるが、補完は後足へ退いて"
            "方向を切り返す。確定EventとCameraを保ったまま両者が一続きの"
            "動作として成立するよう、未固定Performanceを再推論する。"
        ),
        "fixed_user_performance": False,
        "fixed_user_event_or_camera_may_be_changed": False,
    }
    chat = base.CachedChat()
    try:
        answer = chat.complete(
            kind="composition-retry-scene15",
            system=RETRY_SYSTEM,
            user=json.dumps(payload, ensure_ascii=False, separators=(",", ":")),
            max_tokens=768,
            temperature=0.2,
            grammar=RETRY_GRAMMAR,
        ).strip()
        match = re.fullmatch(r"RETRY\t1\t([^\n]+)", answer)
        if match is None:
            raise ValueError(f"Invalid retry response: {answer!r}")
        revised = match.group(1).strip()
        if not revised or revised == request["shots"][target - 1]["performance"]:
            raise ValueError("Retry did not produce a new Performance")
        after = json.loads(json.dumps(request, ensure_ascii=False))
        after["shots"][target - 1]["performance"] = revised
        audit_payload = {
            "scene": 15,
            "target_shot": target,
            "shots": after["shots"],
            "proposed_composition": payload["optional_composition"],
        }
        audit_answer = chat.complete(
            kind="composition-retry-audit-scene15",
            system=COMPATIBILITY_SYSTEM,
            user=json.dumps(audit_payload, ensure_ascii=False, separators=(",", ":")),
            max_tokens=128,
            temperature=0.1,
            grammar=COMPATIBILITY_GRAMMAR,
        ).strip()
        audit = re.fullmatch(r"AUDIT\t1\t(PASS|REJECT)｜理由=([^\n]+)", audit_answer)
        if audit is None:
            raise ValueError(f"Invalid post-retry audit response: {audit_answer!r}")
        result = {
            "source_scene": 15, "target_shot": target,
            "original_performance": request["shots"][target - 1]["performance"],
            "revised_performance": revised,
            "optional_composition": payload["optional_composition"],
            "unchanged_event": request["shots"][target - 1]["event"],
            "unchanged_camera": request["shots"][target - 1]["camera"],
            "post_retry_audit": {"verdict": audit.group(1), "reason": audit.group(2)},
        }
        base.write_json(DEST / "scene15-retry.json", result)
        print(json.dumps(result, ensure_ascii=False, indent=2), flush=True)
    finally:
        chat.close()


def retry_scene15_choice() -> None:
    """Prefer a different optional template over rewriting LLM performance."""
    DEST.mkdir(parents=True, exist_ok=True)
    base.DEST = DEST
    requests = json.loads((DEST / "audit-inputs.json").read_text(encoding="utf-8"))
    request = next(item for item in requests if item["scene"] == 15)
    payload = {
        "scene": 15,
        "target_shot": request["target_shot"],
        "shots": request["shots"],
        "current_conflicting_choice": request["old_cyclic_choice"],
        "alternative_candidates": {
            key: value for key, value in request["candidates"].items()
            if int(key) != request["old_cyclic_choice"]
        },
        "reason": "鳥居を前進してくぐる演技と後退・方向転換が衝突する疑い",
    }
    chat = base.CachedChat()
    try:
        answer = chat.complete(
            kind="composition-choice-retry-scene15",
            system=CHOICE_RETRY_SYSTEM,
            user=json.dumps(payload, ensure_ascii=False, separators=(",", ":")),
            max_tokens=32,
            temperature=0.2,
            grammar=GRAMMAR,
        ).strip()
        match = re.fullmatch(r"CHOICE\t1\t([0-3])", answer)
        if match is None:
            raise ValueError(f"Invalid choice retry response: {answer!r}")
        choice = int(match.group(1))
        if choice == request["old_cyclic_choice"]:
            raise ValueError("Choice retry selected the original conflicting candidate")
        result = {
            "source_scene": 15,
            "target_shot": request["target_shot"],
            "old_choice": request["old_cyclic_choice"],
            "retry_choice": choice,
            "retry_composition": request["candidates"].get(str(choice)),
            "original_performance_unchanged": request["shots"][request["target_shot"] - 1]["performance"],
        }
        base.write_json(DEST / "scene15-choice-retry.json", result)
        print(json.dumps(result, ensure_ascii=False, indent=2), flush=True)
    finally:
        chat.close()


def probe_utility() -> None:
    """Test whether 31B distinguishes added value from mere compatibility."""
    DEST.mkdir(parents=True, exist_ok=True)
    base.DEST = DEST
    requests = json.loads((DEST / "audit-inputs.json").read_text(encoding="utf-8"))
    decisions = []
    chat = base.CachedChat()
    try:
        for request in requests:
            answer = chat.complete(
                kind=f"composition-utility-scene{request['scene']}",
                system=UTILITY_SYSTEM,
                user=json.dumps(request, ensure_ascii=False, separators=(",", ":")),
                max_tokens=32,
                temperature=0.1,
                grammar=GRAMMAR,
            ).strip()
            match = re.fullmatch(r"CHOICE\t1\t([0-3])", answer)
            if match is None:
                raise ValueError(f"Invalid utility decision: {answer!r}")
            choice = int(match.group(1))
            decisions.append({
                "scene": request["scene"],
                "target_shot": request["target_shot"],
                "cyclic_choice": request["old_cyclic_choice"],
                "utility_choice": choice,
                "response": answer,
            })
            print(f"Scene {request['scene']}: old={request['old_cyclic_choice']} "
                  f"utility={choice}", flush=True)
    finally:
        chat.close()
    base.write_json(DEST / "utility-decisions.json", decisions)


def probe_guarded_reselection() -> None:
    """One 31B choice per scheduled Scene, preserving the current default."""
    DEST.mkdir(parents=True, exist_ok=True)
    base.DEST = DEST
    path = SOURCE / "planned.md"
    summary_path = SOURCE / "planner-summary.json"
    document = parse_emd(path.read_text(encoding="utf-8"))
    content = json.loads(summary_path.read_text(encoding="utf-8"))["content"]
    actions = _lookup(content["actions"])
    cameras = _lookup(content["cameras"])
    events = _lookup(content["events"])
    templates = MOTION_TEMPLATES[PROFILE]
    compositions = sorted(content["motion_compositions"], key=lambda row: int(row[0]))
    requests = []
    for composition in compositions:
        number, target, _source, index, _motion = composition
        number, target, index = int(number), int(target), int(index)
        scene = next(item for item in document.scenes if item.scene_number == number)
        shots = []
        for shot_index, shot in enumerate(scene.shots, 1):
            end_ms = (scene.shots[shot_index].start_ms
                      if shot_index < len(scene.shots) else scene.end_ms)
            shots.append({
                "shot": shot_index,
                "duration_ms": end_ms - shot.start_ms,
                "lyrics": [lyric.text for lyric in shot.lyric_annotations],
                "event": events.get((number, shot_index), "なし"),
                "performance": actions[(number, shot_index)],
                "camera": cameras[(number, shot_index)],
            })
        requests.append({
            "scene": number, "target_shot": target, "shots": shots,
            "current_choice": index,
            "candidates": {str(i): text for i, text in enumerate(templates, 1)},
        })
    base.write_json(DEST / "guarded-reselection-inputs.json", requests)
    decisions = []
    chat = base.CachedChat()
    try:
        for request in requests:
            answer = chat.complete(
                kind=f"composition-guarded-reselection-scene{request['scene']}",
                system=GUARDED_RESELECTION_SYSTEM,
                user=json.dumps(request, ensure_ascii=False, separators=(",", ":")),
                max_tokens=32,
                temperature=0.1,
                grammar=GRAMMAR,
            ).strip()
            match = re.fullmatch(r"CHOICE\t1\t([0-3])", answer)
            if match is None:
                raise ValueError(f"Invalid guarded re-selection: {answer!r}")
            choice = int(match.group(1))
            decisions.append({
                "scene": request["scene"],
                "target_shot": request["target_shot"],
                "current_choice": request["current_choice"],
                "new_choice": choice,
                "changed": choice != request["current_choice"],
            })
            print(f"Scene {request['scene']}: {request['current_choice']} -> {choice}",
                  flush=True)
    finally:
        chat.close()
    base.write_json(DEST / "guarded-reselection-decisions.json", decisions)


def probe_no_drop() -> None:
    """Probe minimum re-selection while disallowing automatic deletion."""
    DEST.mkdir(parents=True, exist_ok=True)
    base.DEST = DEST
    requests = json.loads((DEST / "guarded-reselection-inputs.json").read_text(
        encoding="utf-8"))
    decisions = []
    chat = base.CachedChat()
    try:
        for request in requests:
            answer = chat.complete(
                kind=f"composition-no-drop-scene{request['scene']}",
                system=NO_DROP_SYSTEM,
                user=json.dumps(request, ensure_ascii=False, separators=(",", ":")),
                max_tokens=32,
                temperature=0.1,
                grammar=NO_DROP_GRAMMAR,
            ).strip()
            match = re.fullmatch(r"CHOICE\t1\t([1-3])", answer)
            if match is None:
                raise ValueError(f"Invalid no-drop decision: {answer!r}")
            choice = int(match.group(1))
            decisions.append({
                "scene": request["scene"],
                "current_choice": request["current_choice"],
                "new_choice": choice,
                "changed": choice != request["current_choice"],
            })
            print(f"Scene {request['scene']}: {request['current_choice']} -> {choice}",
                  flush=True)
    finally:
        chat.close()
    base.write_json(DEST / "no-drop-decisions.json", decisions)


if __name__ == "__main__":
    if sys.argv[1:] == ["retry-scene15"]:
        retry_scene15()
    elif sys.argv[1:] == ["retry-scene15-choice"]:
        retry_scene15_choice()
    elif sys.argv[1:] == ["probe-utility"]:
        probe_utility()
    elif sys.argv[1:] == ["probe-guarded-reselection"]:
        probe_guarded_reselection()
    elif sys.argv[1:] == ["probe-no-drop"]:
        probe_no_drop()
    else:
        main()
