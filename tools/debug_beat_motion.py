"""Research B1: paired Scene 11 performance calls with/without rhythm hints.

CPU --prepare-only produces evidence contracts; --infer uses the prepared files.
No EMD grammar, node, production prompt, compiler, or H3 changes are made.
"""
from __future__ import annotations

import argparse
from copy import deepcopy
import hashlib
import json
import logging
from pathlib import Path
import sys
import time

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

CANDIDATE = (
    "歌詞のない間奏で、人物は閉眼と呼吸に感情を溜め、短い荷重の移動から"
    "胸郭、左右の腕へ一続きの身体フレーズを展開する。右手は剣の柄を握り続け、"
    "右腕と剣を一体として動かす。左腕は異なる高さで釣り合いを取り、"
    "左手の指先をほどく瞬間をアクセントにして、体幹と肘を緩め、"
    "始点とは異なる姿勢へ静かに収める。"
)
CAMERA = "正面のミディアムショットからゆっくり後方へ引き、人物の体幹、左右の腕、左手の指先の進行を一続きに捉える。"
SYSTEM_APPEND = (
    "\n今回の研究入力にmusic_rhythm_optionalがある場合、その局所的な脈動と時刻を"
    "身体フレーズの溜め・展開・アクセント・解放の参考にしてよい。"
    "全拍に新しい動作を割り当てる必要はなく、複数拍にまたがる連続した演技として扱う。"
    "optional_accent_candidatesは小節頭でも必須の出来事でもない。"
    "時刻はscene_elapsed_sで読み、参考にした節目は自然な本文の中に必要な範囲だけ示す。"
    "解析フィールド名、数表、BPMの説明や拍を数える解説を映像本文へ複写しない。"
    "この情報がない場合は既存の演出候補と身体フレーズを通常どおり扱う。\n"
)
TIMED_APPEND = (
    "\nこの追加比較ではmusic_rhythm_optionalのoptional_accent_candidatesから、"
    "身体フレーズに合う節目を一つ又は二つ選び、そこへ向かう溜めと展開、"
    "その後の解放を一続きの動作として本文にする。"
    "選んだ節目は『開始から約○秒で』のようなScene内の時間の目安を自然な本文に示す。"
    "全ての候補を使ったり、毎拍で別動作を始めたりする必要はない。"
    "時刻の説明だけにせず、重心・体幹・腕のどの動きがその瞬間へ至るかを描く。"
    "本文は通常どおりPERFORMANCEの日本語本文であり、新しいフィールドや行は増やさない。\n"
)


def read(path):
    return json.loads(path.read_text(encoding="utf-8"))


def save(path, value):
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False), encoding="utf-8")


def rhythm_packet(hypothesis, start_sample, end_sample, rate, *, every=6, first=3):
    """Thin pulses without asserting meter, downbeats, or compulsory body actions."""
    if not 0 <= start_sample < end_sample or rate <= 0 or every < 1 or first < 0:
        raise ValueError("invalid packet bounds or thinning")
    times = hypothesis["beat_source_seconds"]
    if any(a >= b for a, b in zip(times, times[1:])):
        raise ValueError("hypothesis beats are not strictly ordered")
    samples = [round(t * rate) for t in times if start_sample <= round(t * rate) < end_sample]
    local = [round((sample - start_sample) / rate, 3) for sample in samples]
    return {"schema": "MVD_SCENE_RHYTHM_RESEARCH_V1", "advisory": True,
        "bpm_hint": hypothesis["bpm_candidate"], "bpm_origin": "author_listening_selection",
        "timebase": "scene_elapsed_s", "source_timebase": "original_fullmix_pcm",
        "source_start_sample": start_sample, "source_end_sample": end_sample, "sample_rate": rate,
        "scene_duration_s": (end_sample - start_sample) / rate,
        "pulse_period_hint_s": round(60 / hypothesis["bpm_candidate"], 3),
        "detected_pulse_count": len(local),
        "optional_accent_candidates": [{"scene_elapsed_s": local[i], "detected_pulse_index": i}
                                       for i in range(first, len(local), every)],
        "thinning": {"every_detected_pulses": every, "first_index": first,
                     "meaning": "sparse optional body accents; not meter or downbeats"},
        "downbeats": None, "calibrated_confidence": None,
        "use": "溜めから展開・解放へ数拍かけて進む身体フレーズの目安。節目の候補は選択又は省略できる。"}


def paired_shared(request, packet):
    baseline = deepcopy(request)
    baseline.pop("protocol", None)
    baseline.pop("task", None)
    slots = baseline.pop("slots")
    if len(slots) != 1 or baseline["scene_number"] != 11:
        raise ValueError("Expected one saved Scene 11 Performance slot")
    if baseline["original_lyrics"][0]["lyrics"]:
        raise ValueError("Experiment requires an instrumental Shot")
    baseline["staging_candidates_optional"] = [CANDIDATE]
    baseline["scene_other"] = [*baseline.get("scene_other", []),
        "この比較では右手に剣の柄を保持する。指先を開く身体表現は自由な左手で行う。"]
    baseline["continuation"] = False
    baseline["previous_scene_state"] = ""
    for position in baseline["shot_positions"]:
        position["fixed_camera"] = CAMERA
    entity = deepcopy(slots[0])
    entity.pop("slot", None)
    entity["position"] = deepcopy(baseline["shot_positions"][0])
    with_rhythm = deepcopy(baseline)
    with_rhythm["music_rhythm_optional"] = packet
    verify_pair(baseline, with_rhythm)
    return baseline, with_rhythm, entity


def verify_pair(baseline, candidate):
    if "music_rhythm_optional" in baseline:
        raise ValueError("Baseline contains rhythm information")
    normalized = deepcopy(candidate)
    if normalized.pop("music_rhythm_optional", None) is None or normalized != baseline:
        raise ValueError("Inputs differ outside the rhythm packet")


def prepare(args):
    from nodes.node_timeline_planner.node import _system_prompts
    output = args.output.resolve()
    if output.exists() and any(output.iterdir()):
        raise ValueError("Use a new empty output directory")
    previous = args.previous.resolve(strict=True)
    rhythm = args.rhythm.resolve(strict=True)
    old = read(previous / "activity-inference.json")
    row = next(row for row in old["trace"] if row["task"] == "scene-author-performance")
    request = json.loads(row["payload"]) if isinstance(row["payload"], str) else row["payload"]
    hypothesis = read(rhythm / "candidate-167" / "hypothesis.json")
    selected = read(rhythm / "listening-decision.json")
    detection = read(rhythm / "rhythm.json")
    if selected["user_selected_bpm_candidate"] != hypothesis["bpm_candidate"]:
        raise ValueError("Tempo candidate is not the author's selected listening condition")
    if not selected["source_file_sha256"] == hypothesis["source_file_sha256"] == detection["file_sha256"]:
        raise ValueError("Source full-mix lineage mismatch")
    # Match actual P5 PCM, not segmentation source boundaries or rounded Plan ms.
    manifest = read(previous / "h3-manifest.json")
    fps, rate = 24, manifest["sample_rate"]
    start = manifest["start_sample"] + manifest["actual_source_preroll_frames"] * rate // fps
    end = manifest["end_sample"]
    if abs(start / rate * 1000 - request["scene_start_ms"]) > 1:
        raise ValueError("Actual PCM start differs from saved Scene by more than rounding")
    packet = rhythm_packet(hypothesis, start, end, rate)
    baseline, candidate, entity = paired_shared(request, packet)
    system_prompt = _system_prompts()["scene-author-performance"] + SYSTEM_APPEND
    output.mkdir(parents=True)
    save(output / "input-contract.json", {"baseline_shared": baseline, "rhythm_shared": candidate,
        "entity": entity, "rhythm_packet": packet, "candidate": CANDIDATE, "camera": CAMERA,
        "common_changes_from_p5": ["hand-held sword consistency", "same researcher Camera for both",
            "one shared body candidate", "fresh isolated state", "same optional rhythm instruction in both system prompts"],
        "comparison_variable": "music_rhythm_optional only", "python_prose_repair": False})
    (output / "system-prompt.txt").write_text(system_prompt, encoding="utf-8")
    conditions = read(previous / "conditions.json")
    save(output / "conditions.json", {"model": conditions["model"], "runtime": conditions["runtime"],
        "previous": str(previous), "rhythm_source": str(rhythm), "scene": 11,
        "performance_seed": 85264133, "planned_calls": 2,
        "system_prompt_sha256": hashlib.sha256(system_prompt.encode()).hexdigest(),
        "scope": "inference only; no compiler or H3", "source_pcm_window_samples": [start, end],
        "sample_rate": rate, "camera_authorship": "researcher; identical in both conditions"})
    print(json.dumps({"prepared": True, "pulse_count": packet["detected_pulse_count"],
        "accent_candidates": packet["optional_accent_candidates"], "duration_s": packet["scene_duration_s"]}), flush=True)


def infer(output, *, timed_followup=False):
    from core.inference import LlamaCppLifecycle, LlamaRuntimeConfig
    from core.planner.requests import request_entities
    from core.planner.scene_author import _split_terminal_state
    from core.planner.types import PlannerEntity
    from nodes.node_timeline_planner.node import _LlamaPlannerBackend, _planner_transport_policy
    conditions = read(output / "conditions.json")
    contract = read(output / "input-contract.json")
    verify_pair(contract["baseline_shared"], contract["rhythm_shared"])
    if timed_followup:
        if not (output / "results.json").exists() or (output / "timed-inference.json").exists():
            raise ValueError("Follow-up requires completed pair and no previous timed inference")
    elif (output / "results.json").exists() or any(output.glob("*-inference.json")):
        raise ValueError("Inference evidence already exists; no silent rerun")
    config = LlamaRuntimeConfig(**conditions["runtime"])
    system_prompt = (output / "system-prompt.txt").read_text(encoding="utf-8")
    if hashlib.sha256(system_prompt.encode()).hexdigest() != conditions["system_prompt_sha256"]:
        raise ValueError("Prepared system prompt changed")
    if timed_followup:
        system_prompt += TIMED_APPEND
        (output / "timed-system-prompt.txt").write_text(system_prompt, encoding="utf-8")
    lifecycle = LlamaCppLifecycle()
    class Backend(_LlamaPlannerBackend):
        @staticmethod
        def _call_seed(base_seed, task, call_number, payload):
            return conditions["performance_seed"]
    results = []
    try:
        load_started = time.perf_counter()
        lifecycle.ensure_loaded(Path(conditions["model"]), config)
        load_elapsed = time.perf_counter() - load_started
        calls = [("timed", contract["rhythm_shared"])] if timed_followup else [
            ("baseline", contract["baseline_shared"]), ("rhythm", contract["rhythm_shared"])]
        for label, shared in calls:
            backend = Backend(lifecycle)
            backend.transport_policy = _planner_transport_policy(conditions["model"])
            backend._task_calls["scene-author-performance"] = 1
            backend._primary_calls["scene-author-performance"] = 1
            started = time.perf_counter()
            values, issues, retries, missing, recovered = request_entities(backend,
                task="scene-author-performance", record_type="PERFORMANCE",
                entities=[PlannerEntity(11, (1,), contract["entity"])], shared=shared,
                system_prompt=system_prompt, runtime_config=config, interrupt_callback=None)
            artifact = {"label": label, "trace": backend.trace, "issues": [str(i) for i in issues],
                "retried_scenes": retries, "missing": missing, "recovered": recovered,
                "elapsed_s": time.perf_counter() - started}
            save(output / f"{label}-inference.json", artifact)
            if missing:
                raise RuntimeError(f"Incomplete performance in {label}: {missing}")
            prose, terminal = _split_terminal_state(values[(1,)])
            results.append({"label": label, "prose": prose, "terminal_state": terminal,
                "elapsed_s": artifact["elapsed_s"], "issues": len(issues), "retry_scenes": list(retries)})
            # Output preserves Japanese UTF-8, independent of Windows console code page.
            (output / f"{label}-excerpt.md").write_text(
                f"# Scene 11\n\n* `演技` {prose}\n* `カメラ` {CAMERA}\n", encoding="utf-8")
            print(json.dumps({"label": label, "output_chars": len(prose),
                "elapsed_s": artifact["elapsed_s"], "issues": len(issues)}), flush=True)
        save(output / ("timed-results.json" if timed_followup else "results.json"), {"model_load_s": load_elapsed, "results": results,
            "inference_only": True, "video_generated": False, "prose_postprocessed": False})
    finally:
        lifecycle.clear()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--previous", type=Path)
    parser.add_argument("--rhythm", type=Path)
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--prepare-only", action="store_true")
    mode.add_argument("--infer", action="store_true")
    mode.add_argument("--timed-followup", action="store_true")
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s", stream=sys.stdout)
    if args.infer or args.timed_followup:
        infer(args.output.resolve(strict=True), timed_followup=args.timed_followup)
    elif args.previous is None or args.rhythm is None:
        parser.error("preparation requires --previous and --rhythm")
    else:
        prepare(args)
