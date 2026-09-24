"""GPU probe: compare one-phase and time-ordered long-Shot Action instructions."""

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

from core.direction.profile_loader import load_direction_profile
from core.inference import LlamaCppLifecycle, LlamaRuntimeConfig
from core.planner.action_constraints import build_action_grammar
from core.protocols.llm_records import parse_llm_records
from nodes.node_timeline_planner.node import _LlamaPlannerBackend


PROMPT_PATH = ROOT / "prompts/timeline_planner_actions_dance_phrase_system_prompt.txt"
OLD_RULE = "短尺へ無関係な動作を詰めない。"
NEW_RULE = (
    OLD_RULE +
    "4秒以上の通常Shotでは、一つの感情的意図の中で、予備動作から主動作、"
    "読める到達姿勢まで二つ以上の異なる身体段階を時間順に書く。"
    "支持と重心の変化は体幹と腕へ伝え、同じ手の上下を二段階として数えない。"
    "4秒未満又は顔Shotでは一つの決定的な変化と結果に絞り、見えない脚の動きを始めない。"
)
MINIMAL_PROMPT = (
    "あなたはアニメMVの人物振付家。入力slotは一つのSceneの既存Shot枠で、歌詞とCueだけを演技の根拠にする。"
    "各Shotは前Shotの到達姿勢から始め、違う動作を一度だけ進めて次へ渡す。"
    "感情の変化が読める重心、体幹、腕、視線の組合せを選ぶが、毎Shot同じ部位順にはしない。"
    "単なる歩行、左右を替えた腕上げ、前傾、手を腰へ戻す動きの反復は避ける。"
    "一人だけを描き、歌詞にない小道具や接触対象を作らない。"
    "外部現象は人物の手から発生させず、カメラ動作を人物の回転で代用しない。"
    "顔Shotは目と歌唱口を見せ、見えない脚を動かさない。"
    "各slotに一行だけ、ACTION、slot番号、自然な日本語の演技本文を実TAB区切りで出力する。"
    "本文に内部ラベル、台詞、歌詞引用、カメラ指示を入れない。説明やMarkdownを付けない。\n"
)
PER_PHASE_PROMPT = (
    "あなたはアニメMVの人物演技を作る。slotは時間順で、連続する二つのslotが同じShot内の"
    "前半と後半である。前半は身体の準備または方向付け、後半はその結果としての決定的な"
    "アクセントまたは収まりを書く。次Shotは前Shotの到達姿勢から始める。"
    "一行につき一つの撮影可能な身体変化を具体的に記す。"
    "左右を入れ替えた同じ動き、足を交互に上げる反復、単なる手の上下、前傾、歩行だけにしない。"
    "歌詞にない物、接触、人物を加えず、カメラを人物の回転で代用しない。"
    "各slotにACTION、slot番号、日本語の動作本文を実TABで区切った一行を出力する。"
    "説明、JSON、Markdown、台詞、カメラ指示を出さない。\n"
)


def prompts() -> dict[str, str]:
    baseline = PROMPT_PATH.read_text(encoding="utf-8").rstrip() + "\n"
    if baseline.count(OLD_RULE) != 1:
        raise ValueError("long-Shot baseline rule changed")
    return {
        "baseline": baseline,
        "multi_phase": baseline.replace(OLD_RULE, NEW_RULE),
        "minimal": MINIMAL_PROMPT,
        "per_phase": PER_PHASE_PROMPT,
    }


COMPACT_MOTION = (
    "歌詞の感情に従い、各Shotで意図のある異なる身体動作と到達姿勢を作る。"
    "前Shotの姿勢から始め、同じ手の上下、前傾、歩行を繰り返さない。"
    "カメラの回り込みを人物の全身回転で代用せず、足先の細部を主題にしない。"
)


def model_request(
    fixture: dict, *, motion_mode: str = "full",
    slot_layout: str = "shot",
) -> dict:
    """Use fixed lyric/Cue inputs; exclude the original Action from every slot."""
    if motion_mode not in {"full", "compact"}:
        raise ValueError("motion_mode must be full or compact")
    if slot_layout not in {"shot", "phase"}:
        raise ValueError("slot_layout must be shot or phase")
    scene = fixture["scenes"][0]
    motion = load_direction_profile(
        ROOT / "profiles/motion/anime_emotional_mv.md", "motion"
    )
    slots = []
    for index, shot in enumerate(scene["shots"], 1):
        phases = (("prepare", "accent") if index == 1
                  else ("continue", "resolve"))
        for phase_index in range(2 if slot_layout == "phase" else 1):
            slot_number = len(slots) + 1
            slots.append({
            "slot": slot_number,
            "scene_number": scene["scene_number"],
            "shot_index": index,
            "phase_in_shot": (
                phases[phase_index] if slot_layout == "phase" else ""
            ),
            "shot_duration_ms": 2479 if slot_layout == "phase" else 4959,
            "lyrics": [{"text": value} for value in scene["lyrics"]],
            "author_body": [],
            "visual_beat": scene["cue"],
            "visual_beat_grounding": {
                "valid": False, "target": "なし", "body_driver": scene["cue"],
                "final_state": "",
            },
            "priority_lyric_cues": [],
            "performance_mode": "dance_phrase",
            "performance_role": (
                "body_phrase_accent" if index == 1 and phase_index == 0
                else "expressive_resolution"
            ),
            "performance_phase": (
                "prepare_and_accent" if index == 1
                else "release_and_reaction"
            ),
            "phrase_position": f"{index}/{len(scene['shots'])}",
            "previous_shot": (
                None if slot_number == 1
                else {"scene_number": scene["scene_number"], "slot": slot_number - 1}
            ),
            })
    return {
        "protocol": "MVD_LLM_RECORDS_V1",
        "task": "actions",
        "subject_roster": ["サブジェクト1"],
        "direction": {
            "style": "手描きセルアニメ",
            "time_lighting": "夜",
            "motion": motion.text if motion_mode == "full" else COMPACT_MOTION,
            "other": "",
        },
        "planner_policy_contract": {
            "policy_id": "anime_emotional_mv",
            "performance_mode": "dance_phrase",
            "lyric_interpretation": "bounded",
        },
        "primary_action_concept": "サブジェクト1",
        "subject_instance_policy": "single_subject_exactly_one_visible_instance",
        "action_batch_contract": {
            "slow_or_gentle_action_maximum": 1,
            "generic_hand_raise_or_lower_maximum": 0,
            "unrequested_lower_body_primary_action_maximum": 0,
            "unrequested_running_maximum": 0,
        },
        "recent_action_history": [],
        "slots": slots,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--fixture", type=Path, default=ROOT /
                        "docs/assets/research/scene-body-chain-2026-09-22/fixture.json")
    parser.add_argument("--model", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--seeds", nargs="+", type=int, default=[1, 2, 3])
    parser.add_argument("--motion-mode", choices=("full", "compact"), default="full")
    parser.add_argument("--variants", nargs="+", choices=("baseline", "multi_phase", "minimal", "per_phase"),
                        default=["baseline", "multi_phase"])
    parser.add_argument("--slot-layout", choices=("shot", "phase"), default="shot")
    args = parser.parse_args()
    fixture_bytes = args.fixture.read_bytes()
    request = model_request(
        json.loads(fixture_bytes), motion_mode=args.motion_mode,
        slot_layout=args.slot_layout,
    )
    payload = json.dumps(request, ensure_ascii=False, separators=(",", ":"))
    prompt_by_variant = prompts()
    grammar = build_action_grammar(request["slots"])
    config = LlamaRuntimeConfig(
        n_ctx=16384, max_tokens=1024, temperature=0.2, top_p=0.9,
        repetition_penalty=1.05, gpu_layers=-1, n_batch=512,
        keep_model_loaded=False,
    )
    args.output.mkdir(parents=True, exist_ok=True)
    evidence = {
        "fixture_sha256": hashlib.sha256(fixture_bytes).hexdigest(),
        "model": str(args.model.resolve()),
        "model_size": args.model.stat().st_size,
        "runtime": config.to_dict(),
        "motion_mode": args.motion_mode,
        "slot_layout": args.slot_layout,
        "payload": request,
        "prompt_sha256": {
            key: hashlib.sha256(value.encode("utf-8")).hexdigest()
            for key, value in prompt_by_variant.items()
        },
        "grammar_sha256": hashlib.sha256(grammar.encode("utf-8")).hexdigest(),
        "runs": [],
    }
    lifecycle = LlamaCppLifecycle()
    try:
        lifecycle.ensure_loaded(args.model, config)
        for seed in args.seeds:
            for variant in args.variants:
                prompt = prompt_by_variant[variant]
                started = time.perf_counter()
                backend = _LlamaPlannerBackend(lifecycle)
                print(f"seed={seed} variant={variant} started", flush=True)
                raw = backend.complete_planner(
                    task="actions", system_prompt=prompt,
                    payload=payload, config=replace(config, seed=seed),
                )
                ids = frozenset(slot["slot"] for slot in request["slots"])
                parsed = parse_llm_records(
                    raw, allowed_slots={"ACTION": ids},
                    required=frozenset(("ACTION", slot) for slot in ids),
                ).to_dict()
                evidence["runs"].append({
                    "seed": seed, "variant": variant, "raw": raw,
                    "elapsed_seconds": round(time.perf_counter() - started, 3),
                    "parsed": parsed,
                })
                (args.output / "evidence.json").write_text(
                    json.dumps(evidence, ensure_ascii=False, indent=2) + "\n",
                    encoding="utf-8",
                )
                print(
                    f"seed={seed} variant={variant} "
                    f"missing={parsed['missing']} issues={len(parsed['issues'])}",
                    flush=True,
                )
    finally:
        lifecycle.clear()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
