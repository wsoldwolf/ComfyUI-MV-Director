"""CPU-only rhythm probe. No node registration, LLM calls, or production changes.

Run in an isolated librosa environment. Source-sample timestamps are authoritative;
the resampled analysis audio never replaces the original full mix.
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import importlib.metadata
import json
import math
from pathlib import Path
import time


def window_beats(times, start, end):
    """Half-open source-clock crop, including a beat exactly at its start."""
    if not (math.isfinite(start) and math.isfinite(end) and 0 <= start < end):
        raise ValueError("invalid source-clock window")
    result = []
    previous = -1.0
    for value in times:
        value = float(value)
        if not math.isfinite(value) or value < 0 or value <= previous:
            raise ValueError("beats must be finite, nonnegative, and strictly ordered")
        previous = value
        if start <= value < end:
            result.append(value)
    return result


def source_sample(seconds, rate, samples):
    if rate <= 0 or samples < 0 or not math.isfinite(seconds) or seconds < 0:
        raise ValueError("invalid audio clock")
    return min(samples, round(seconds * rate))


def pulse_summary(times):
    """Timing dispersion is a diagnostic, NOT detector confidence or correctness."""
    if len(times) < 2:
        return {"median_interval_s": None, "interval_cv": None}
    intervals = [b - a for a, b in zip(times, times[1:])]
    if any(not math.isfinite(x) or x <= 0 for x in intervals):
        raise ValueError("nonpositive beat interval")
    ordered = sorted(intervals)
    middle = len(ordered) // 2
    median = ordered[middle] if len(ordered) % 2 else (ordered[middle - 1] + ordered[middle]) / 2
    mean = sum(intervals) / len(intervals)
    variance = sum((x - mean) ** 2 for x in intervals) / len(intervals)
    return {"median_interval_s": median, "interval_cv": math.sqrt(variance) / mean}


def click_overlay(audio, rate, times, source_start=0.0, gain=0.15):
    """Render all clicks equally: no invented 4/4 meter or downbeat emphasis."""
    import numpy as np
    audio = np.asarray(audio, dtype=np.float32)
    if audio.ndim != 2 or rate <= 0 or not math.isfinite(gain) or gain < 0 or not np.isfinite(audio).all():
        raise ValueError("invalid PCM")
    out = audio.copy()
    n = max(1, round(0.025 * rate))
    phase = np.arange(n) / rate
    tick = np.sin(2 * np.pi * 1800 * phase) * np.exp(-phase / 0.006) * gain
    for beat in window_beats(times, source_start, source_start + len(out) / rate):
        position = source_sample(beat - source_start, rate, len(out))
        count = min(n, len(out) - position)
        out[position:position + count] += tick[:count, None]
    peak = float(np.max(np.abs(out))) if out.size else 0.0
    scale = min(1.0, 0.98 / peak) if peak else 1.0
    # One constant preview gain; no limiter or time stretching.
    return out * scale, scale


def save_json(path, value):
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False), encoding="utf-8")


def audible_previews(output):
    """Listening-only remix of already detected timestamps; never retrack beats."""
    import numpy as np
    import soundfile as sf
    result = json.loads((output / "rhythm.json").read_text(encoding="utf-8"))
    checks = []
    for window in result["windows"]:
        label = window["label"]
        original, rate = sf.read(output / f"{label}-original.wav", dtype="float32", always_2d=True)
        times = window["preview"]["global"]["source_seconds"]
        remix, scale = click_overlay(original * 0.25, rate, times, window["start_s"], gain=0.45)
        ticks, _ = click_overlay(np.zeros_like(original), rate, times, window["start_s"], gain=0.45)
        destinations = [output / f"{label}-global-click-audible.wav", output / f"{label}-click-only.wav"]
        if any(path.exists() for path in destinations):
            raise ValueError("Audible preview already exists; do not overwrite evidence")
        sf.write(destinations[0], remix, rate, subtype="FLOAT")
        sf.write(destinations[1], ticks, rate, subtype="FLOAT")
        checks.append({"window": label, "music_gain": 0.25, "click_gain": 0.45,
                       "constant_output_gain": scale, "beats_reused_without_changes": True,
                       "source_samples": len(original), "sample_rate": rate,
                       "preview": str(destinations[0]), "click_only": str(destinations[1])})
    save_json(output / "audible-preview-checks.json", checks)
    print(json.dumps(checks, indent=2), flush=True)


def tempo_candidate_previews(output, bpm):
    """Re-use spectral flux; explicit user tempo hypothesis, not a new estimate."""
    import numpy as np
    import soundfile as sf
    import librosa
    if not math.isfinite(bpm) or bpm <= 0:
        raise ValueError("BPM candidate must be positive and finite")
    result = json.loads((output / "rhythm.json").read_text(encoding="utf-8"))
    destination = output / f"candidate-{bpm:g}"
    if destination.exists():
        raise ValueError("Tempo candidate already exists; retain previous evidence")
    features = np.loadtxt(output / "features.csv", delimiter=",", skiprows=1)
    _, frames = librosa.beat.beat_track(onset_envelope=features[:, 1], bpm=bpm,
        sr=result["analysis_rate"], hop_length=result["hop_length"])
    times = window_beats(librosa.frames_to_time(frames, sr=result["analysis_rate"],
        hop_length=result["hop_length"]), 0, result["duration_s"])
    destination.mkdir()
    checks = {"schema": "MVD_RHYTHM_TEMPO_HYPOTHESIS_V1", "timebase": result["timebase"],
        "source_file_sha256": result["file_sha256"], "bpm_candidate": bpm,
        "bpm_origin": "user_hypothesis", "human_verified": False,
        "beat_source_seconds": times, "interval_diagnostic": pulse_summary(times), "windows": []}
    for window in result["windows"]:
        label = window["label"]
        crop, rate = sf.read(output / f"{label}-original.wav", dtype="float32", always_2d=True)
        beats = window_beats(times, window["start_s"], window["end_s"])
        preview, scale = click_overlay(crop * 0.25, rate, beats, window["start_s"], gain=0.45)
        path = destination / f"{label}-click-audible.wav"
        sf.write(path, preview, rate, subtype="FLOAT")
        checks["windows"].append({"label": label, "preview": str(path),
            "start_s": window["start_s"], "end_s": window["end_s"],
            "beat_source_seconds": beats, "crop_relative_seconds": [t - window["start_s"] for t in beats],
            "music_gain": 0.25, "click_gain": 0.45, "constant_output_gain": scale})
    save_json(destination / "hypothesis.json", checks)
    print(json.dumps({"bpm_candidate": bpm, "beat_count": len(times),
        "windows": [{"label": w["label"], "beats": len(w["beat_source_seconds"])}
                    for w in checks["windows"]]}, indent=2), flush=True)


def run(args):
    import numpy as np
    import soundfile as sf
    import librosa
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    source = args.fullmix.resolve(strict=True)
    output = args.output.resolve()
    if output.exists() and any(output.iterdir()):
        raise ValueError("Use a new empty research directory; previous evidence is not overwritten")
    output.mkdir(parents=True, exist_ok=True)
    started = time.perf_counter()
    known_times = np.arange(0.5, 12, 0.5)
    synthetic = librosa.clicks(times=known_times, sr=22050, length=12 * 22050)
    synthetic_tempo, synthetic_frames = librosa.beat.beat_track(y=synthetic, sr=22050, hop_length=256)
    detected = librosa.frames_to_time(synthetic_frames, sr=22050, hop_length=256)
    nearest_error = float(np.median([min(abs(t - known_times)) for t in detected])) if len(detected) else None
    silence_tempo, silence_frames = librosa.beat.beat_track(y=np.zeros(22050 * 3), sr=22050, hop_length=256)
    self_check = {"known_pulse_bpm": 120, "detected_bpm": float(np.asarray(synthetic_tempo).reshape(-1)[0]),
        "detected_beats": len(detected), "median_nearest_pulse_error_s": nearest_error,
        "silence_tempo": float(np.asarray(silence_tempo).reshape(-1)[0]), "silence_beats": len(silence_frames),
        "note": "Synthetic smoke check, not accuracy validation on music."}
    save_json(output / "detector-self-check.json", self_check)
    if not len(detected) or len(silence_frames):
        raise AssertionError("detector synthetic pulse/silence smoke check failed")
    audio, rate = sf.read(source, dtype="float32", always_2d=True)
    if not len(audio) or not np.isfinite(audio).all():
        raise ValueError("empty or nonfinite source audio")
    duration = len(audio) / rate
    source_hash = hashlib.sha256(source.read_bytes()).hexdigest()
    print(f"Source: {duration:.6f}s, {rate}Hz, {audio.shape[1]} channels; CPU only", flush=True)
    analysis_rate, hop = 22050, 256
    mono = audio.mean(axis=1)
    analysis = librosa.resample(mono, orig_sr=rate, target_sr=analysis_rate)
    print("Computing full-song spectral flux (no vocal stem, no lyrics)", flush=True)
    onset = librosa.onset.onset_strength(y=analysis, sr=analysis_rate, hop_length=hop, n_fft=2048)
    frame_times = librosa.frames_to_time(np.arange(len(onset)), sr=analysis_rate, hop_length=hop)
    rms = librosa.feature.rms(y=analysis, frame_length=2048, hop_length=hop)[0]
    print("Tracking full-song beats", flush=True)
    tempo, frames = librosa.beat.beat_track(onset_envelope=onset, sr=analysis_rate, hop_length=hop)
    global_times = librosa.frames_to_time(frames, sr=analysis_rate, hop_length=hop)
    global_times = window_beats(global_times, 0, duration)
    records = []
    for beat in global_times:
        index = round(beat * analysis_rate / hop)
        records.append({"source_seconds": beat, "source_sample": source_sample(beat, rate, len(audio)),
                        "onset_strength": float(onset[index])})
    with (output / "features.csv").open("w", newline="", encoding="utf-8") as stream:
        writer = csv.writer(stream)
        writer.writerow(["source_seconds", "spectral_flux", "analysis_rms"])
        writer.writerows((float(t), float(o), float(rms[min(i, len(rms) - 1)]))
                         for i, (t, o) in enumerate(zip(frame_times, onset)))

    windows = [("intro", 0.0, 20.0), ("interlude", 85.680, 106.0), ("return", 108.0, 123.0)]
    if duration < max(end for _, _, end in windows):
        raise ValueError("Momiji2 research windows exceed source duration")
    result = {"schema": "MVD_RHYTHM_PROBE_V1", "timebase": "original_fullmix_pcm",
              "source": str(source), "file_sha256": source_hash, "sample_rate": rate,
              "source_samples": len(audio), "duration_s": duration,
              "method": "librosa_dynamic_programming", "device": "cpu",
              "analysis_rate": analysis_rate, "hop_length": hop, "n_fft": 2048,
              "start_bpm_prior": 120.0, "tightness": 100.0, "trim": True,
              "global_tempo_bpm": float(np.asarray(tempo).reshape(-1)[0]),
              "beats": records, "global_interval_diagnostic": pulse_summary(global_times),
              "downbeats": None, "confidence": None, "human_verified": False,
              "note": "Onset strength and interval regularity are not calibrated confidence. No meter inferred.",
              "versions": {key: importlib.metadata.version(key) for key in
                           ["librosa", "numpy", "scipy", "soundfile", "numba", "soxr"]},
              "windows": []}
    fig, axes = plt.subplots(3, 1, figsize=(14, 8), constrained_layout=True)
    for axis, (label, start, end) in zip(axes, windows):
        begin_sample, end_sample = source_sample(start, rate, len(audio)), source_sample(end, rate, len(audio))
        start = begin_sample / rate
        crop = audio[begin_sample:end_sample]
        end = end_sample / rate
        begin_frame = math.ceil(start * analysis_rate / hop)
        end_frame = min(len(onset), math.ceil(end * analysis_rate / hop))
        local_tempo, local_frames = librosa.beat.beat_track(
            onset_envelope=onset[begin_frame:end_frame], sr=analysis_rate, hop_length=hop)
        # The envelope slice starts on an analysis frame, not the arbitrary crop start.
        local_times = librosa.frames_to_time(local_frames + begin_frame, sr=analysis_rate, hop_length=hop)
        local_times = window_beats(local_times, start, end)
        selected_global = window_beats(global_times, start, end)
        sf.write(output / f"{label}-original.wav", crop, rate, subtype="FLOAT")
        previews = {}
        for mode, times in [("global", selected_global), ("local", local_times)]:
            overlay, scale = click_overlay(crop, rate, times, start)
            destination = output / f"{label}-{mode}-click.wav"
            sf.write(destination, overlay, rate, subtype="FLOAT")
            previews[mode] = {"path": str(destination), "source_seconds": times,
                              "crop_relative_seconds": [t - start for t in times],
                              "preview_constant_gain": scale,
                              "interval_diagnostic": pulse_summary(times)}
        # Candidate accents: rank actual onset strength at detected beats and space them.
        # Not every fourth beat, not downbeats, and not a compulsory motion schedule.
        ranked = sorted(selected_global, key=lambda t: float(onset[round(t * analysis_rate / hop)]), reverse=True)
        landmarks = []
        for value in ranked:
            if all(abs(value - existing) >= 2.0 for existing in landmarks):
                landmarks.append(value)
            if len(landmarks) == 3:
                break
        landmarks.sort()
        result["windows"].append({"label": label, "start_s": start, "end_s": end,
            "start_sample": begin_sample, "end_sample": end_sample,
            "local_tempo_bpm": float(np.asarray(local_tempo).reshape(-1)[0]),
            "preview": previews,
            "unverified_accent_candidates_source_s": landmarks,
            "motion_generated": False})
        axis.plot(frame_times[begin_frame:end_frame], onset[begin_frame:end_frame], color="#506784", lw=1)
        axis.vlines(selected_global, 0, float(onset[begin_frame:end_frame].max(initial=1)),
                    color="#ca4b41", alpha=0.5, label="Full-song beats")
        axis.scatter(local_times, [-0.5] * len(local_times), marker="|", color="#25875d", label="Local beats")
        axis.set_title(f"{label}: source {start:.3f}..{end:.3f}s; local tempo {result['windows'][-1]['local_tempo_bpm']:.2f} BPM")
        axis.set_xlabel("Original full-mix seconds")
        axis.set_ylabel("Spectral flux (not confidence)")
        axis.legend(loc="upper right")
    fig.savefig(output / "rhythm-windows.png", dpi=130)
    plt.close(fig)
    preview, scale = click_overlay(audio, rate, global_times)
    sf.write(output / "fullmix-global-click.wav", preview, rate, subtype="FLOAT")
    result["full_preview_constant_gain"] = scale
    result["elapsed_s"] = time.perf_counter() - started
    # Confirm original-rate plain crops remain exact, without normalization/resampling.
    for window in result["windows"]:
        crop, crop_rate = sf.read(output / f"{window['label']}-original.wav", dtype="float32", always_2d=True)
        window["source_crop_exact"] = bool(crop_rate == rate and np.array_equal(
            crop, audio[window["start_sample"]:window["end_sample"]]))
        if not window["source_crop_exact"]:
            raise AssertionError("source crop differs from original PCM")
    save_json(output / "rhythm.json", result)
    print(json.dumps({"tempo": result["global_tempo_bpm"], "beats": len(records),
        "elapsed_s": result["elapsed_s"], "windows": [{"label": w["label"],
        "local_bpm": w["local_tempo_bpm"], "global_beats": len(w["preview"]["global"]["source_seconds"]),
        "local_beats": len(w["preview"]["local"]["source_seconds"])} for w in result["windows"]]}, indent=2), flush=True)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--fullmix", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    modes = parser.add_mutually_exclusive_group()
    modes.add_argument("--audible-preview", action="store_true")
    modes.add_argument("--bpm-candidate", type=float)
    args = parser.parse_args()
    if args.audible_preview:
        audible_previews(args.output.resolve(strict=True))
    elif args.bpm_candidate is not None:
        tempo_candidate_previews(args.output.resolve(strict=True), args.bpm_candidate)
    elif args.fullmix is None:
        parser.error("--fullmix is required for analysis")
    else:
        run(args)
