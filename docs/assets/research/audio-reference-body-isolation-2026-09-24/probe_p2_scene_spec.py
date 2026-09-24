"""Research-only de-novo Scene/Shot specification probe on saved real lyrics.

Unlike P1, the model never sees the generated EMD Action or final H3 Plan.
No output is patched into production EMD or submitted to H3.
"""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import sys
import time

ROOT = Path(__file__).resolve().parents[4]
sys.path.insert(0, str(ROOT))

from core.emd.parser import parse_emd
from core.inference import LlamaCppLifecycle, LlamaRuntimeConfig


SYSTEMS = {
    "neutral": (
        "あなたはMVの映像監督です。与えられた歌詞とScene資料から、短い日本語の"
        "映像仕様を作ってください。Sceneの一文と各Shotの一文を返します。"
        "出力形式はSCENE|本文、次にSHOT|1|本文、必要ならSHOT|2|本文です。"
        "余分な説明やMarkdownは不要です。"
    ),
    "linked": (
        "あなたはMVの映像監督です。一つのSceneを連続する出来事として設計します。"
        "入力にaccepted_scene_eventがあれば、それを選択済みの可視的出来事として使用します。"
        "無ければ歌詞から出来事を選びます。"
        "歌詞から映す対象と場所を選び、対象の可視変化、人物の身体・表情の反応、"
        "その関係を見せるCameraを時間順に結び付けます。"
        "短い日本語でScene一文と各Shot一文を返してください。"
        "出力形式はSCENE|本文、次にSHOT|1|本文、必要ならSHOT|2|本文です。"
        "余分な説明やMarkdownは不要です。"
    ),
    "lyric_priority": (
        "あなたはMVの映像監督です。歌詞に明示された具体的な対象をSceneの主題に選び、"
        "環境資料はその対象の配置に使います。対象の可視変化、人物の身体・表情の反応、"
        "その関係を見せるCameraを短い時間進行として結び付けてください。"
        "短い日本語でScene一文と各Shot一文を返してください。"
        "出力形式はSCENE|本文、次にSHOT|1|本文、必要ならSHOT|2|本文です。"
        "余分な説明やMarkdownは不要です。"
    ),
    "body_camera": (
        "あなたはMVの映像監督です。accepted_scene_eventは選択済みの出来事です。"
        "その指定Shotで対象が変化し、他のShotはその準備または余韻を担います。"
        "各Shotは、人物の始点姿勢、重心・体幹・腕の具体的な変化、目線・表情、"
        "終点姿勢を一つの流れにし、Cameraが対象と人物の反応を同じ画面で捉える"
        "短い映像文にしてください。歩行や視線だけを身体演技の代用にしません。"
        "歌詞とScene資料を使い、短い日本語でScene一文と各Shot一文を返します。"
        "出力形式はSCENE|本文、次にSHOT|1|本文、必要ならSHOT|2|本文です。"
        "余分な説明やMarkdownは不要です。"
    ),
    "separate_roles": (
        "あなたはMVの映像監督です。accepted_scene_eventは選択済みの出来事です。"
        "指定Shotで対象が可視変化し、他のShotは準備または余韻を担います。"
        "まずSceneを一文で示します。各ShotのBODY行には人物の始点姿勢から"
        "重心・体幹・腕・目線・表情の具体的変化と終点を短く書きます。"
        "各ShotのCAMERA行にはその対象の変化と人物の身体反応を画面に収める"
        "動きと画角を短く書きます。同一Sceneで時間的につなげます。"
        "出力形式はSCENE|本文、BODY|1|本文、CAMERA|1|本文、"
        "Shot 2があればBODY|2|本文、CAMERA|2|本文です。"
        "余分な説明やMarkdownは不要です。"
    ),
    "performer_camera": (
        "あなたはMVの映像監督です。accepted_scene_eventは選択済みの出来事です。"
        "指定Shotで対象が可視変化し、他のShotは準備または余韻を担います。"
        "PERFORMER行の主語は必ず同じ人物です。人物の始点姿勢から重心・体幹・腕・"
        "目線・表情の変化と終点を短く記し、木・葉・狐火の動作を人物の身体動作として"
        "記しません。CAMERA行では対象の変化と人物の反応を同時に捉える動きと画角を"
        "短く記します。SceneとShotを時間的につなげます。"
        "出力形式はSCENE|本文、PERFORMER|1|本文、CAMERA|1|本文、"
        "Shot 2があればPERFORMER|2|本文、CAMERA|2|本文です。"
        "余分な説明やMarkdownは不要です。"
    ),
    "opaque_roles": (
        "あなたはMVの映像監督です。accepted_scene_eventは選択済みの出来事です。"
        "output_slotsの順序どおり、各不透明トークンを一字も変えずに一度だけ出力し、"
        "直後に|と短い日本語の映像文を続けます。見出し、説明、余分なShotは出しません。"
        "『場面』は一つの出来事、『人物』は同じ人物の姿勢・重心・腕・目線・表情の変化、"
        "『撮影』は対象の変化と人物の反応を同時に収めるCameraの動きです。"
        "選択済みの出来事は指定Shotで起こし、他のShotは準備または余韻にします。"
    ),
}

LABEL_CONTROL_SYSTEM = (
    "あなたはMVの映像監督です。accepted_scene_eventは選択済みの出来事です。"
    "output_slotsの順序どおり、各tokenを一字も変えずに一度だけ出力し、"
    "直後に|と短い日本語の映像文を続けます。見出し、説明、余分なShotは出しません。"
    "『場面』は一つの出来事、『人物』は同じ人物の姿勢・重心・腕・目線・表情の変化、"
    "『撮影』は対象の変化と人物の反応を同時に収めるCameraの動きです。"
    "『人物』の本文では人物を主語とし、木・葉・狐火を人物の代わりにしません。"
    "選択済みの出来事は指定Shotで起こし、他のShotは準備または余韻にします。"
)
SYSTEMS["natural_label_control"] = LABEL_CONTROL_SYSTEM
SYSTEMS["opaque_label_control"] = LABEL_CONTROL_SYSTEM
SYSTEMS["explicit_label_control"] = LABEL_CONTROL_SYSTEM
SYSTEMS["phase_label_control"] = LABEL_CONTROL_SYSTEM


def payload_for_scene(document, scene_number: int) -> dict[str, object]:
    scene = next(
        item for item in document.scenes if item.scene_number == scene_number
    )
    shots: list[dict[str, object]] = []
    for index, shot in enumerate(scene.shots, start=1):
        shots.append({
            "shot": index,
            "start_ms": shot.start_ms,
            "end_ms": (
                scene.shots[index].start_ms
                if index < len(scene.shots) else scene.end_ms
            ),
            "lyrics": [
                {"text": lyric.text, "section": lyric.section}
                for lyric in shot.lyric_annotations
            ],
        })
    setting = document.scene_setting
    return {
        "scene_number": scene_number,
        "scene_start_ms": scene.start_ms,
        "scene_end_ms": scene.end_ms,
        "continuation": scene.continuation,
        "environment": list(setting.environment) if setting else [],
        "time_lighting": list(setting.time_lighting) if setting else [],
        "shots": shots,
    }


def output_slots(
    scene_number: int, count: int, *, label_style: str = "opaque",
) -> list[dict[str, object]]:
    meanings = [("場面", 0)]
    for shot in range(1, count + 1):
        meanings.extend((("人物", shot), ("撮影", shot)))
    return [
        {
            "token": {
                "opaque": f"MVD{scene_number:02d}T{index:02d}X",
                "natural": (
                    "SCENE" if meaning == "場面" else
                    f"PERFORMER_{shot}" if meaning == "人物" else
                    f"CAMERA_{shot}"
                ),
                "explicit": (
                    "SCENE_EVENT" if meaning == "場面" else
                    f"PERFORMER_BODY_ACTION_{shot}" if meaning == "人物" else
                    f"CAMERA_MOTION_COVERAGE_{shot}"
                ),
                "phase": (
                    "SCENE_VISIBLE_EVENT" if meaning == "場面" else
                    f"PERFORMER_POSE_CHANGE_{shot}" if meaning == "人物" else
                    f"CAMERA_SHOWS_EVENT_AND_PERFORMER_{shot}"
                ),
            }[label_style],
            "meaning": meaning,
            "shot": shot,
        }
        for index, (meaning, shot) in enumerate(meanings)
    ]


def content_records(
    response: str, count: int, *, role_type: str | None,
    opaque_tokens: list[str] | None = None,
) -> dict[str, object]:
    lines = [line.strip() for line in response.splitlines() if line.strip()]
    if opaque_tokens is not None:
        expected = opaque_tokens
    else:
        expected = ["SCENE"]
        for index in range(1, count + 1):
            if role_type:
                expected.extend((f"{role_type}|{index}", f"CAMERA|{index}"))
            else:
                expected.append(f"SHOT|{index}")
    return {
        "protocol_ok": (
            len(lines) == len(expected)
            and all(line.startswith(prefix + "|") for line, prefix in zip(
                lines, expected, strict=True
            ))
        ),
        "record_count": len(lines),
        "lines": lines,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--emd", type=Path, required=True)
    parser.add_argument("--model", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--event-fixture", type=Path)
    parser.add_argument("--seeds", type=int, nargs="+", default=[1, 2])
    parser.add_argument("--temperature", type=float, default=0.2)
    parser.add_argument("--top-p", type=float, default=0.9)
    parser.add_argument(
        "--variants", nargs="+", choices=tuple(SYSTEMS),
        default=["neutral", "linked", "lyric_priority"],
    )
    args = parser.parse_args()
    source = args.emd.read_bytes()
    document = parse_emd(source.decode("utf-8"))
    event_fixture_bytes = (
        args.event_fixture.read_bytes() if args.event_fixture else None
    )
    events = (
        json.loads(event_fixture_bytes)["events"]
        if event_fixture_bytes else {}
    )
    config = LlamaRuntimeConfig(
        n_ctx=8192, max_tokens=512, temperature=args.temperature,
        top_p=args.top_p,
        n_batch=512, gpu_layers=-1, keep_model_loaded=False,
    )
    runs: list[dict[str, object]] = []
    evidence = {
        "scope": "research_only_no_generated_action_or_camera_in_input",
        "emd_sha256": hashlib.sha256(source).hexdigest(),
        "event_fixture_sha256": (
            hashlib.sha256(event_fixture_bytes).hexdigest()
            if event_fixture_bytes else None
        ),
        "model_path": str(args.model),
        "model_size": args.model.stat().st_size,
        "runtime": config.to_dict(),
        "system_prompts": {name: SYSTEMS[name] for name in args.variants},
        "runs": runs,
    }
    lifecycle = LlamaCppLifecycle()
    try:
        lifecycle.ensure_loaded(args.model, config)
        for scene_number in (6, 9):
            payload = payload_for_scene(document, scene_number)
            if events:
                payload["accepted_scene_event"] = events[str(scene_number)]
            for seed in args.seeds:
                for variant in args.variants:
                    system = SYSTEMS[variant]
                    request_payload = dict(payload)
                    slots = (
                        output_slots(
                            scene_number, len(payload["shots"]),
                            label_style=(
                                "natural" if variant == "natural_label_control"
                                else "explicit" if variant == "explicit_label_control"
                                else "phase" if variant == "phase_label_control"
                                else "opaque"
                            ),
                        )
                        if variant in (
                            "opaque_roles", "natural_label_control",
                            "opaque_label_control", "explicit_label_control",
                            "phase_label_control",
                        ) else None
                    )
                    if slots is not None:
                        request_payload["output_slots"] = slots
                    user_content = "/no_think\n" + json.dumps(
                        request_payload, ensure_ascii=False,
                        separators=(",", ":"),
                    )
                    active = LlamaRuntimeConfig(
                        **{**config.to_dict(), "seed": seed}
                    )
                    started = time.perf_counter()
                    print(
                        f"scene={scene_number} seed={seed} "
                        f"variant={variant} started", flush=True,
                    )
                    response = lifecycle.complete_chat(
                        [{"role": "system", "content": system},
                         {"role": "user", "content": user_content}],
                        active,
                    )
                    parsed = content_records(
                        response, len(payload["shots"]),
                        role_type=(
                            "BODY" if variant == "separate_roles" else
                            "PERFORMER" if variant == "performer_camera" else None
                        ),
                        opaque_tokens=(
                            [str(slot["token"]) for slot in slots]
                            if slots is not None else None
                        ),
                    )
                    runs.append({
                        "scene": scene_number,
                        "seed": seed,
                        "variant": variant,
                        "payload": request_payload,
                        "response_after_lifecycle": response,
                        "parsed": parsed,
                        "elapsed_seconds": round(
                            time.perf_counter() - started, 3
                        ),
                    })
                    args.output.parent.mkdir(parents=True, exist_ok=True)
                    args.output.write_text(
                        json.dumps(
                            evidence, ensure_ascii=False, indent=2
                        ) + "\n",
                        encoding="utf-8",
                    )
                    print(
                        f"scene={scene_number} seed={seed} "
                        f"variant={variant} protocol_ok="
                        f"{parsed['protocol_ok']}", flush=True,
                    )
    finally:
        lifecycle.clear()


if __name__ == "__main__":
    main()
