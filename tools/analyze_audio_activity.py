"""CPU-only P0 activity export; never loads Whisper, an LLM, or H3.

Use --timeline for a saved Timeline artifact/cache, or --template to reconstruct
source windows from saved lyric timestamps. Reconstruction must reproduce every
saved Scene/Shot frame, otherwise it is rejected rather than presented as exact.
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import html
import json
import math
from pathlib import Path
import subprocess
import sys
import time

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from core.artifacts import TimelineArtifact
from core.artifacts.base import canonical_json
from core.audio.pad_pair import AudioShape, SceneAudioWindow, align_audio_to_plan_scenes, scene_audio_placements
from core.h3_contract import DEFAULT_H3_TIMING_PROFILE
from core.lyrics import AlignedLyric, SourceLyricSegment, VoicedInterval, analyze_waveform, build_timeline, normalize_match_text, parse_plain_lyrics
from core.lyrics.activity import VAD_SETTINGS, build_activity_diagnostic
from core.planner.template import parse_template_emd


def decode_audio(path: Path, ffmpeg: str):
    """Decode original rate/channels on CPU; no resampling or channel averaging."""
    import numpy as np
    import torch
    probe = str(Path(ffmpeg).with_name("ffprobe.exe")) if Path(ffmpeg).is_file() else "ffprobe"
    info = json.loads(subprocess.check_output([
        probe, "-v", "error", "-select_streams", "a:0", "-show_entries",
        "stream=sample_rate,channels", "-of", "json", str(path),
    ]))["streams"][0]
    rate, channels = int(info["sample_rate"]), int(info["channels"])
    pcm = subprocess.check_output([
        ffmpeg, "-v", "error", "-threads", "1", "-i", str(path), "-map", "0:a:0",
        "-f", "f32le", "-acodec", "pcm_f32le", "pipe:1",
    ])
    values = np.frombuffer(pcm, dtype="<f4").reshape(-1, channels).T.copy()
    waveform = torch.from_numpy(values).unsqueeze(0)
    fingerprint = hashlib.sha256()
    fingerprint.update(str(tuple(waveform.shape)).encode("ascii"))
    fingerprint.update(str(rate).encode("ascii"))
    fingerprint.update(waveform.numpy().tobytes())
    return waveform, rate, fingerprint.hexdigest()


def timeline_from_template(path: Path, duration_ms: int, maximum_ms: int):
    template = parse_template_emd(path.read_text(encoding="utf-8-sig"))
    aligned = []
    for scene in template.scenes:
        for shot in scene.shots:
            for annotation in shot.lyric_annotations:
                if annotation.start_ms is None or annotation.end_ms is None:
                    raise ValueError("template must contain source-clock lyric timestamps")
                identifier = f"saved_{len(aligned) + 1:04d}"
                source = SourceLyricSegment(
                    identifier, annotation.text, annotation.section, len(aligned) + 1,
                    0, len(annotation.text), normalize_match_text(annotation.text),
                )
                aligned.append(AlignedLyric(source, annotation.start_ms, annotation.end_ms))
    timeline = build_timeline(tuple(aligned), (), source_audio_duration_ms=duration_ms,
                              max_scene_duration_ms=maximum_ms, timing_profile=DEFAULT_H3_TIMING_PROFILE)
    actual = [(s.start_ms, s.end_ms, s.raw_length, [t.start_ms for t in s.shots])
              for s in timeline.scenes]
    expected = [(s.start_ms, s.end_ms, s.h3_length, [t.start_ms for t in s.shots])
                for s in template.scenes]
    if actual != expected:
        raise ValueError("reconstructed source windows do not reproduce saved Scene/Shot frames; use --timeline")
    return timeline


def svg_summary(waveform, fullmix, diagnostic):
    """A static scientific timeline: original energy, detector, lyrics and gaps."""
    rate, samples = diagnostic["sample_rate"], diagnostic["source_samples"]
    duration = samples / rate
    width, left, plot = 1500, 155, 1300
    rows = [('Vocal energy', waveform, 90), ('Full mix energy', fullmix, 155)]
    elements = [f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="440" viewBox="0 0 {width} 440">',
                '<rect width="1500" height="440" fill="white"/>',
                '<g font-family="sans-serif" font-size="14" fill="#223047">',
                '<text x="20" y="26">P0 source-clock activity (seconds); candidates, not verified singing</text>']
    for label, audio, y in rows:
        elements.append(f'<text x="15" y="{y+18}">{label}</text>')
        if audio is None:
            continue
        points = []
        for index in range(plot):
            start, end = index * samples // plot, max(index * samples // plot + 1, (index + 1) * samples // plot)
            energy = float(audio[..., start:end].square().mean(dim=-1).sqrt().amax())
            db = 20 * math.log10(max(energy, 1e-12))
            level = max(0, min(1, (db + 70) / 70))
            points.append(f'{left+index},{y+48-48*level:.2f}')
        elements.append(f'<polyline points="{" ".join(points)}" fill="none" stroke="#517baa" stroke-width="1"/>')
        elements.append(f'<line x1="{left}" x2="{left+plot}" y1="{y+48-48*25/70:.2f}" y2="{y+48-48*25/70:.2f}" stroke="#aaa" stroke-dasharray="4 4"/>')
    colors = {"vocal_candidate": "#357a55", "unknown": "#e0872d", "no_vocal_candidate": "#adc1d6",
              "instrumental_candidate": "#689bda", "fullmix_silence_candidate": "#c0c0c0"}
    for label, items, y, color in [
        ("Activity", diagnostic["source_intervals"], 230, None),
        ("Lyric annotations", diagnostic["lyrics"], 280, "#8058b4"),
        ("Long VAD gaps", diagnostic["long_gaps"], 330, "#689bda"),
    ]:
        elements.append(f'<text x="15" y="{y+18}">{label}</text>')
        for item in items:
            x = left + item["start_sample"] / samples * plot
            w = (item["end_sample"] - item["start_sample"]) / samples * plot
            fill = color or colors[item["state"]]
            title = html.escape(str(item))
            elements.append(f'<rect x="{x:.3f}" y="{y}" width="{w:.3f}" height="24" fill="{fill}"><title>{title}</title></rect>')
    for seconds in range(0, math.ceil(duration), 10):
        x = left + seconds / duration * plot
        elements.append(f'<line x1="{x:.2f}" x2="{x:.2f}" y1="65" y2="363" stroke="#999" opacity="0.2"/>')
        elements.append(f'<text x="{x:.2f}" y="385">{seconds}</text>')
    elements.append('<text x="155" y="420">Green: vocal candidate | Blue: no-vocal/music candidate | Orange: lyric/VAD disagreement | Purple: lyrics</text>')
    elements.append('</g></svg>')
    return "\n".join(elements)


def png_summary(waveform, fullmix, diagnostic, destination):
    """Optional raster preview of the same scientific data, using only CPU."""
    try:
        import matplotlib
    except ImportError:
        return
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    import numpy as np
    colors = {"vocal_candidate": "#357a55", "unknown": "#e0872d", "no_vocal_candidate": "#adc1d6",
              "instrumental_candidate": "#689bda", "fullmix_silence_candidate": "#c0c0c0"}
    rate, samples = diagnostic["sample_rate"], diagnostic["source_samples"]
    edges = np.linspace(0, samples, 1301, dtype=int)
    x = edges[:-1] / rate
    figure, axes = plt.subplots(5, 1, figsize=(15, 5), sharex=True,
                               gridspec_kw={"height_ratios": [2, 2, 1, 1, 1]}, layout="constrained")
    for axis, audio, label in zip(axes[:2], [waveform, fullmix], ["Vocal dBFS", "Full mix dBFS"]):
        if audio is not None:
            rms = [float(audio[..., a:b].square().mean(dim=-1).sqrt().amax()) for a, b in zip(edges, edges[1:])]
            axis.plot(x, 20 * np.log10(np.maximum(rms, 1e-12)), linewidth=0.6)
            axis.axhline(-45, linestyle="--", color="gray", linewidth=0.6)
        axis.set_ylim(-75, 0)
        axis.set_ylabel(label)
    for axis, items, label, fixed in zip(axes[2:],
            [diagnostic["source_intervals"], diagnostic["lyrics"], diagnostic["long_gaps"]],
            ["Activity", "Lyrics", "Long gaps"], [None, "#8058b4", "#689bda"]):
        for item in items:
            axis.axvspan(item["start_sample"] / rate, item["end_sample"] / rate,
                         color=fixed or colors[item["state"]])
        axis.set_ylabel(label)
        axis.set_yticks([])
    axes[-1].set_xlim(0, samples / rate)
    axes[-1].set_xlabel("Source time (seconds) | green: vocal candidate; blue: no-vocal/music; orange: unknown")
    figure.suptitle("P0 source-clock activity | energy candidates, not verified singing")
    figure.savefig(destination, dpi=110)
    plt.close(figure)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--vocal", type=Path, required=True)
    parser.add_argument("--lyrics", type=Path, help="Record plain lyric provenance; does not invent timestamps")
    parser.add_argument("--fullmix", type=Path)
    parser.add_argument("--allow-one-sample-tail-difference", action="store_true",
                        help="Preserve a one-sample length difference; missing full mix tail is unknown")
    source = parser.add_mutually_exclusive_group()
    source.add_argument("--timeline", type=Path)
    source.add_argument("--template", type=Path)
    parser.add_argument("--max-scene-duration-ms", type=int, default=10000)
    parser.add_argument("--long-gap-ms", type=int, default=2000)
    parser.add_argument("--ffmpeg", default="ffmpeg")
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args()
    destination = args.output_dir.resolve()
    if destination.is_relative_to(ROOT):
        raise ValueError("Research outputs must be outside the project")
    if destination.exists() and any(destination.iterdir()):
        raise ValueError("Choose an empty output directory; do not overwrite research evidence")
    import torch
    torch.set_num_threads(4)
    started = time.monotonic()
    waveform, rate, digest = decode_audio(args.vocal, args.ffmpeg)
    samples = waveform.shape[-1]
    voiced = analyze_waveform(waveform, sample_rate=rate, total_samples=samples, **VAD_SETTINGS)
    timeline = None
    if args.timeline:
        value = json.loads(args.timeline.read_text(encoding="utf-8-sig"))
        timeline = TimelineArtifact.from_dict(value.get("payload", value).get("timeline", value))
    elif args.template:
        timeline = timeline_from_template(args.template, math.ceil(samples * 1000 / rate), args.max_scene_duration_ms)
    fullmix, mix_ranges, mix_samples = None, None, None
    mix_provenance = None
    if args.fullmix:
        fullmix, mix_rate, mix_digest = decode_audio(args.fullmix, args.ffmpeg)
        mix_samples = fullmix.shape[-1]
        difference = mix_samples - samples
        if mix_rate != rate or (difference and not (args.allow_one_sample_tail_difference and abs(difference) == 1)):
            raise ValueError("Full mix and stem must have the same sample clock and duration; no silent resampling")
        if difference:
            print(f"Explicit one-sample tail difference: fullmix minus vocal = {difference}; PCM unchanged", file=sys.stderr)
        mix_ranges = analyze_waveform(fullmix, sample_rate=rate, total_samples=mix_samples, **VAD_SETTINGS)
        mix_ranges = tuple(VoicedInterval(i.start_sample, min(i.end_sample, samples))
                           for i in mix_ranges if i.start_sample < samples)
        mix_provenance = {"file": str(args.fullmix.resolve()), "pcm_sha256": mix_digest,
                          "source_samples": mix_samples, "tail_difference_samples": difference,
                          "one_sample_tail_difference_allowed": args.allow_one_sample_tail_difference}
    diagnostic = build_activity_diagnostic(
        voiced, sample_rate=rate, total_samples=samples, audio_sha256=digest,
        timeline=timeline, fullmix_active=mix_ranges, long_gap_ms=args.long_gap_ms,
        fullmix_observed_samples=mix_samples,
    )
    diagnostic["provenance"] = {
        "vocal_file": str(args.vocal.resolve()), "fullmix": mix_provenance,
        "timeline_file": str(args.timeline.resolve()) if args.timeline else None,
        "template_file": str(args.template.resolve()) if args.template else None,
        "timeline_reconstructed": args.template is not None,
        "timeline_audio_identity": "duration/frame check only; saved timeline has no PCM fingerprint",
    }
    if args.lyrics:
        raw_lyrics = args.lyrics.read_bytes()
        lyrics = parse_plain_lyrics(raw_lyrics.decode("utf-8-sig"))
        diagnostic["provenance"]["plain_lyrics"] = {
            "file": str(args.lyrics.resolve()), "file_sha256": hashlib.sha256(raw_lyrics).hexdigest(),
            "atomic_segments": len(lyrics), "sections": list(dict.fromkeys(i.section for i in lyrics)),
            "timed": False,
        }
    mapping_checked = None
    if timeline:
        target = diagnostic["aligned_reference"]["target_samples"]
        windows = tuple(SceneAudioWindow(s.source_start_ms, s.source_end_ms, s.delivered_frames) for s in timeline.scenes)
        aligned, _ = align_audio_to_plan_scenes({"waveform": waveform, "sample_rate": rate}, windows, target_samples=target)
        positions = scene_audio_placements(AudioShape(rate, samples), windows, target_samples=target)
        for p in positions:
            if not torch.equal(waveform[..., p.source_start_sample:p.source_end_sample],
                               aligned["waveform"][..., p.destination_start_sample:p.destination_end_sample]):
                raise AssertionError("PCM changed during alignment")
        for gap in diagnostic["aligned_reference"]["padding"]:
            if torch.count_nonzero(aligned["waveform"][..., gap["start_sample"]:gap["end_sample"]]).item():
                raise AssertionError("Padding is not PCM zero")
        mapping_checked = True
    diagnostic["verification"] = {"aligned_pcm_sample_equality": mapping_checked, "gpu_used": False,
                                  "elapsed_seconds": time.monotonic() - started}
    destination.mkdir(parents=True, exist_ok=True)
    (destination / "activity.json").write_text(canonical_json(diagnostic), encoding="utf-8")
    if timeline:
        (destination / "timeline.json").write_text(timeline.to_json(), encoding="utf-8")
    with (destination / "intervals.csv").open("w", encoding="utf-8-sig", newline="") as stream:
        writer = csv.writer(stream)
        writer.writerow(["start_seconds", "end_seconds", "state", "lyric_ids", "clock"])
        for clock, items in [("source", diagnostic["source_intervals"]),
                             ("aligned_reference", diagnostic.get("aligned_reference", {}).get("intervals", [])),
                             ("aligned_reference", diagnostic.get("aligned_reference", {}).get("padding", []))]:
            for item in items:
                writer.writerow([item["start_sample"] / rate, item["end_sample"] / rate,
                                 item["state"], ",".join(item.get("lyric_ids", [])), clock])
    (destination / "overview.svg").write_text(svg_summary(waveform, fullmix, diagnostic), encoding="utf-8")
    png_summary(waveform, fullmix, diagnostic, destination / "overview.png")
    print(json.dumps({"output_dir": str(destination), "source_seconds": samples / rate,
                      "long_gaps": diagnostic["long_gaps"], "unknown_intervals": diagnostic["warning_count"],
                      **diagnostic["verification"]}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
