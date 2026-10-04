"""P1 real Whisper alignment and paired Scene Author inference, never H3.

Outputs belong outside the repository. Explicit GPU authorization is required
before invoking either subcommand. Alignment caches are preserved for review.
"""
from __future__ import annotations
import argparse
import hashlib
import json
import logging
from pathlib import Path
import sys
import time
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from tools.analyze_audio_activity import decode_audio
from core.artifacts import DirectionArtifact, TimelineArtifact
from core.inference import LlamaCppLifecycle, LlamaRuntimeConfig, SuccessCache
from core.emd.audio_activity import AudioActivity
from core.lyrics import analyze_waveform, render_template_emd
from core.lyrics.activity import VAD_SETTINGS, build_activity_diagnostic
from core.audio.pad_pair import SceneAudioWindow, align_audio_to_plan_scenes
from core.planner.api import generate_planner_content
from core.planner.template import PlannerTemplate, parse_template_emd
from core.planner.section_context import section_context_by_scene
from nodes.common.whisper_discovery import WhisperModel
from nodes.node_lyric_segmentation import node as lyric_node
from nodes.node_timeline_planner.node import _LlamaPlannerBackend, _system_prompts, _planner_transport_policy


def save(path, value):
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding="utf-8")


def prepare(args):
    """Remove only the explicitly identified, non-sung arrangement annotation."""
    from core.lyrics.plain import parse_plain_lyrics
    source = args.lyrics.resolve(strict=True)
    original = source.read_text(encoding="utf-8-sig")
    annotation = "[Instrumental: cascading piano, bright lead, rushing waterfall]"
    lines = original.splitlines()
    removed = [{"line": i, "text": line} for i, line in enumerate(lines, 1)
               if line == annotation]
    prepared = "\n".join(line for line in lines if line != annotation) + "\n"
    segments = parse_plain_lyrics(prepared)
    output = args.output.resolve()
    if output.exists() and any(output.iterdir()):
        raise ValueError("input preparation directory must be empty")
    output.mkdir(parents=True, exist_ok=True)
    (output / "lyrics-alignment.txt").write_text(prepared, encoding="utf-8")
    save(output / "provenance.json", {"original": str(source),
        "original_sha256": hashlib.sha256(source.read_bytes()).hexdigest(),
        "prepared_sha256": hashlib.sha256(prepared.encode()).hexdigest(),
        "excluded_non_sung_annotation": removed,
        "lyric_segments": len(segments), "authored_lyric_text_preserved": True})
    print(f"Prepared {len(segments)} lyric segments; excluded annotations={len(removed)}", flush=True)


def align(args):
    output = args.output.resolve()
    if output.exists() and any(output.iterdir()):
        raise ValueError("alignment output directory must be empty")
    output.mkdir(parents=True, exist_ok=True)
    wave, rate, digest = decode_audio(args.vocal.resolve(strict=True), args.ffmpeg)
    model_path = args.whisper.resolve(strict=True)
    stat = model_path.stat()
    model = WhisperModel(model_path.name, model_path, stat.st_size, stat.st_mtime_ns)
    node = lyric_node.MVDirectorLyricSegmentation()
    transcribe = node._whisper.transcribe
    calls = []
    def traced(*a, **kw):
        start = time.perf_counter()
        value = transcribe(*a, **kw)
        calls.append({"elapsed_s": time.perf_counter() - start, "result": value})
        save(output / "whisper-trace.json", calls)
        return value
    start = time.perf_counter()
    with patch.object(lyric_node, "_cache", return_value=SuccessCache(output / "cache")), \
         patch.object(lyric_node, "resolve_comfy_whisper_model", return_value=model), \
         patch.object(node._whisper, "transcribe", side_effect=traced):
        result = node.segment(vocal_audio={"waveform": wave, "sample_rate": rate},
            lyrics_text=args.lyrics.read_text(encoding="utf-8-sig"), whisper_model=model_path.name,
            language="ja", max_scene_duration_ms=10000, srt_time_offset_ms=0,
            cache_mode="refresh", keep_whisper_loaded=False)
    if not isinstance(result, tuple):
        raise RuntimeError("lyric alignment was blocked; inspect saved Whisper trace")
    template, srt, timeline, status = result
    fullmix, mix_rate, mix_digest = decode_audio(args.fullmix.resolve(strict=True), args.ffmpeg)
    if mix_rate != rate or abs(fullmix.shape[-1] - wave.shape[-1]) > 1:
        raise ValueError("fullmix differs by more than the approved one-sample tail")
    voices = analyze_waveform(wave, sample_rate=rate, total_samples=wave.shape[-1], **VAD_SETTINGS)
    music = analyze_waveform(fullmix, sample_rate=rate, total_samples=fullmix.shape[-1], **VAD_SETTINGS)
    diagnostic = build_activity_diagnostic(voices, sample_rate=rate, total_samples=wave.shape[-1],
        audio_sha256=digest, timeline=timeline, fullmix_active=music,
        fullmix_observed_samples=min(fullmix.shape[-1], wave.shape[-1]))
    metadata = AudioActivity.from_diagnostic(diagnostic)
    template = render_template_emd(timeline, audio_activity=metadata).text
    (output / "template.md").write_text(template, encoding="utf-8")
    (output / "lyrics.srt").write_text(srt, encoding="utf-8")
    save(output / "timeline.json", timeline.to_dict())
    save(output / "activity.json", diagnostic)
    save(output / "alignment-summary.json", {"status": status, "elapsed_s": time.perf_counter()-start,
         "vocal": str(args.vocal), "fullmix": str(args.fullmix), "lyrics": str(args.lyrics),
         "whisper": str(model_path), "vocal_sha256": digest, "fullmix_sha256": mix_digest,
         "whisper_calls": len(calls), "long_gaps": diagnostic["long_gaps"]})
    print(status, flush=True)


def compare(args):
    output = args.output.resolve()
    if output.exists() and any(output.iterdir()):
        raise ValueError("comparison output directory must be empty")
    output.mkdir(parents=True, exist_ok=True)
    template = parse_template_emd((args.alignment / "template.md").read_text(encoding="utf-8"))
    diagnostic = json.loads((args.alignment / "activity.json").read_text(encoding="utf-8"))
    gaps = diagnostic["long_gaps"]
    intro = next(g for g in gaps if g["position"] == "intro")
    middle = next(g for g in gaps if g["position"] == "internal")
    rate = diagnostic["sample_rate"]
    windows = {"intro": (intro["start_sample"]+intro["end_sample"])/2*1000/rate,
               "interlude": (middle["start_sample"]+middle["end_sample"])/2*1000/rate,
               "vocal-return": middle["end_sample"]*1000/rate+1000}
    scenes = {name: next(s for s in template.scenes if s.start_ms <= t < s.end_ms)
              for name, t in windows.items()}
    # Neutral candidates: no song-specific props are hardcoded into the pipeline.
    direction = DirectionArtifact(motion_profile_id="anime_scene_author_mv", motion_templates=(),
        environment_direction=("秋の山稜と谷、岩場や滝がある自然の空間。",),
        motion_direction=("伴奏と歌詞の感情に呼応した明瞭な身体フレーズを選ぶ。",),
        staging_candidates=(
            "伴奏が続く場面で、人物は短く荷重を移し、胸郭から腕へ弧を渡す。一拍のアクセント後に手をほどき、異なる姿勢で余韻を残す。",
            "歌唱へ戻る場面で、流れていた手を胸前で受け止め、顔を上げて視線を結び、呼吸から歌へ自然につなぐ。"))
    config = LlamaRuntimeConfig(n_ctx=16384, max_tokens=2048, gpu_layers=-1,
        n_batch=512, temperature=0.2, top_p=0.9, repetition_penalty=1.05, seed=20261003)
    lifecycle = LlamaCppLifecycle()
    save(output / "conditions.json", {"model": str(args.model), "runtime": config.to_dict(),
        "direction": direction.to_dict(), "scenes": {k: s.scene_number for k,s in scenes.items()},
        "comparison": "same prompts/candidates/Scene/role seed; only audio_activity differs",
        "prior_context": "single Scene probe; no preceding generated terminal state",
        "video_generated": False})
    prompts = _system_prompts()
    contexts = section_context_by_scene(template)
    class ContextBackend(_LlamaPlannerBackend):
        @staticmethod
        def _call_seed(base_seed, task, call_number, payload):
            request = json.loads(payload.split("\0", 1)[0])
            material = f"{base_seed}/{request['scene_number']}/{task}/{call_number}"
            return int.from_bytes(hashlib.sha256(material.encode()).digest()[:8], "big") % 2147483647 + 1
        def complete_planner(self, *, payload, **kwargs):
            request = json.loads(payload)
            request["section_lyric_context"] = contexts[request["scene_number"]]
            return super().complete_planner(payload=json.dumps(request, ensure_ascii=False), **kwargs)
    try:
        lifecycle.ensure_loaded(args.model, config)
        for name, scene in scenes.items():
            for enabled in (False, True):
                label = f"{name}-{'activity' if enabled else 'baseline'}"
                backend = ContextBackend(lifecycle)
                backend.transport_policy = _planner_transport_policy(str(args.model))
                start = time.perf_counter()
                content, missing = generate_planner_content(backend,
                    template=PlannerTemplate((scene,), template.audio_activity if enabled else None),
                    concept_emd="# サブジェクト\n* 一人の歌手。\n", direction=direction,
                    lip_sync_mode="context_loop", lip_sync_target="サブジェクト1",
                    system_prompts=prompts, runtime_config=config)
                save(output / f"{label}.json", {"elapsed_s": time.perf_counter()-start,
                    "scene": scene.scene_number, "trace": backend.trace,
                    "missing": missing, "content": None if content is None else content.to_dict()})
                lines = [f"# {label}", f"Scene {scene.scene_number}: {scene.start_ms}..{scene.end_ms} ms", ""]
                if content:
                    for heading, rows in (("演出", content.events), ("演技", content.actions), ("カメラ", content.cameras)):
                        lines += [f"## {heading}", ""] + [f"* Shot {r[1]}: {r[2]}" for r in rows] + [""]
                else:
                    lines.append(f"Incomplete: {missing}")
                (output / f"{label}.md").write_text("\n".join(lines), encoding="utf-8")
                print(f"{label}: elapsed={time.perf_counter()-start:.1f}s missing={missing}", flush=True)
    finally:
        lifecycle.clear()


def verify(args):
    import torch
    timeline = TimelineArtifact.from_dict(json.loads((args.alignment / "timeline.json").read_text(encoding="utf-8")))
    diagnostic = json.loads((args.alignment / "activity.json").read_text(encoding="utf-8"))
    wave, rate, digest = decode_audio(args.vocal.resolve(strict=True), args.ffmpeg)
    if rate != diagnostic["sample_rate"] or digest != diagnostic["audio_sha256"]:
        raise ValueError("activity source fingerprint mismatch")
    windows = tuple(SceneAudioWindow(s.source_start_ms, s.source_end_ms, s.delivered_frames) for s in timeline.scenes)
    output, _ = align_audio_to_plan_scenes({"waveform": wave, "sample_rate": rate}, windows,
        target_samples=diagnostic["aligned_reference"]["target_samples"])
    equal = all(torch.equal(wave[..., p["source_start_sample"]:p["source_end_sample"]],
        output["waveform"][..., p["destination_start_sample"]:p["destination_end_sample"]])
        for p in diagnostic["aligned_reference"]["placements"])
    silent = all(torch.count_nonzero(output["waveform"][..., p["start_sample"]:p["end_sample"]]).item() == 0
        for p in diagnostic["aligned_reference"]["padding"])
    if not equal or not silent:
        raise ValueError("PCM alignment verification failed")
    path = args.alignment / "pcm-verification.json"
    if path.exists():
        raise ValueError("verification output already exists")
    save(path, {"source_samples": wave.shape[-1], "target_samples": output["waveform"].shape[-1],
        "sample_rate": rate, "source_sha256": digest,
        "all_source_samples_equal": equal, "padding_zero": silent,
        "scene_frames": [s.raw_length for s in timeline.scenes]})
    print(f"PCM verification: copied={equal}; padding_zero={silent}", flush=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    subs = parser.add_subparsers(dest="task", required=True)
    p = subs.add_parser("prepare")
    p.add_argument("--lyrics", type=Path, required=True)
    p.add_argument("--output", type=Path, required=True)
    a = subs.add_parser("align")
    for name in ("vocal", "fullmix", "lyrics", "whisper", "output"):
        a.add_argument("--"+name, type=Path, required=True)
    a.add_argument("--ffmpeg", default="ffmpeg")
    c = subs.add_parser("compare")
    for name in ("alignment", "model", "output"):
        c.add_argument("--"+name, type=Path, required=True)
    v = subs.add_parser("verify")
    for name in ("alignment", "vocal"):
        v.add_argument("--"+name, type=Path, required=True)
    v.add_argument("--ffmpeg", default="ffmpeg")
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s", stream=sys.stdout)
    {"prepare": prepare, "align": align, "compare": compare, "verify": verify}[args.task](args)


if __name__ == "__main__":
    main()
