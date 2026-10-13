"""Replay WF lyrics against a local stem and preserve every Whisper decode."""
from __future__ import annotations

import argparse
import base64
from dataclasses import asdict
import hashlib
import json
import logging
import math
from pathlib import Path
import sys
import time

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from core.lyrics import (WhisperLifecycle, align_lyrics, analyze_waveform,
    build_timeline, extract_whisper_words, parse_plain_lyrics,
    prepare_whisper_audio, recover_unplaced_lyrics, render_srt,
    render_template_emd)
from core.lyrics.activity import VAD_SETTINGS
from core.h3_contract import DEFAULT_H3_TIMING_PROFILE


def save(path, value):
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding="utf-8")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("workflow", "audio", "model", "output"):
        parser.add_argument("--" + name, type=Path, required=True)
    parser.add_argument("--replay", type=Path, help="Replay saved decodes without GPU")
    args = parser.parse_args()
    output = args.output.resolve()
    output.mkdir(parents=True, exist_ok=True)
    if any(output.iterdir()):
        raise ValueError("Use an empty output directory")
    logging.basicConfig(level=logging.INFO, handlers=[logging.StreamHandler(),
        logging.FileHandler(output / "debug.log", encoding="utf-8")])
    import soundfile as sf
    import torch
    wf = json.loads(args.workflow.read_text(encoding="utf-8-sig"))
    node = next(n for n in wf["nodes"] if n["type"] == "MVDirectorLoadTextFile")
    lyrics_text = base64.b64decode(node["widgets_values"][0]).decode("utf-8-sig")
    lyrics = parse_plain_lyrics(lyrics_text)
    (output / "lyrics.txt").write_text(lyrics_text, encoding="utf-8")
    samples, rate = sf.read(str(args.audio), dtype="float32", always_2d=True)
    waveform = torch.from_numpy(samples.T.copy()).unsqueeze(0)
    duration_ms = math.ceil(len(samples) * 1000 / rate)
    voiced = analyze_waveform(waveform, sample_rate=rate,
        total_samples=len(samples), **VAD_SETTINGS)
    audio = prepare_whisper_audio(waveform, sample_rate=rate,
        total_samples=len(samples))
    save(output / "source.json", {"workflow": str(args.workflow),
        "audio": str(args.audio), "model": str(args.model),
        "audio_sha256": hashlib.sha256(samples.tobytes()).hexdigest(),
        "lyrics_sha256": hashlib.sha256(lyrics_text.encode()).hexdigest(),
        "sample_rate": rate, "duration_ms": duration_ms,
        "lyrics": [asdict(l) for l in lyrics], "voiced": [asdict(v) for v in voiced]})
    lifecycle = WhisperLifecycle()
    device = "cpu" if args.replay else lifecycle.resolve_device()
    class TraceTranscriber:
        calls = 0
        def transcribe(self, pcm, **kwargs):
            self.calls += 1
            offset = (pcm.data_ptr() - audio.data_ptr()) // audio.element_size()
            request = {"offset_samples": offset, "samples": len(pcm), **kwargs}
            path = output / f"decode-{self.calls:03}.json"
            start = time.perf_counter()
            if args.replay:
                stored = json.loads((args.replay / path.name).read_text(encoding="utf-8"))
                old = stored["request"]
                if any(old[k] != request[k] for k in request if k != "device"):
                    raise ValueError(f"Replay request changed: {path.name}: {request}")
                result = stored["result"]
            else:
                result = lifecycle.transcribe(pcm, **kwargs)
            save(path, {"request": request, "result": result,
                "elapsed_s": time.perf_counter()-start})
            text = str(result.get("text", ""))
            print(f"decode {self.calls}: offset={offset/16000:.3f}s "
                f"length={len(pcm)/16000:.3f}s text_chars={len(text)} "
                f"preview={text[:160]}", flush=True)
            return result
    transcriber = TraceTranscriber()
    try:
        if not args.replay:
            lifecycle.ensure_loaded(args.model, device=device)
        result = transcriber.transcribe(audio, language="ja", device=device,
            initial_prompt="", condition_on_previous_text=False)
        words = extract_whisper_words(result, audio_duration_ms=duration_ms)
        save(output / "words.json", [asdict(w) for w in words])
        resolved, unplaced = align_lyrics(lyrics, words, voiced_intervals=voiced,
            sample_rate=rate, audio_duration_ms=duration_ms)
        save(output / "initial.json", {"resolved": [asdict(l) for l in resolved],
            "unplaced": [asdict(l) for l in unplaced]})
        print("initial unplaced:", [(l.segment_id, l.text) for l in unplaced], flush=True)
        if unplaced:
            resolved, unplaced, stats = recover_unplaced_lyrics(lyrics, resolved,
                audio, transcriber, language="ja", device=device,
                voiced_intervals=voiced, sample_rate=rate, audio_duration_ms=duration_ms)
            print("retry:", stats, flush=True)
        save(output / "final.json", {"resolved": [asdict(l) for l in resolved],
            "unplaced": [asdict(l) for l in unplaced]})
        timeline = build_timeline(resolved, unplaced,
            source_audio_duration_ms=duration_ms, max_scene_duration_ms=10000,
            timing_profile=DEFAULT_H3_TIMING_PROFILE)
        save(output / "timeline.json", timeline.to_dict())
        if not unplaced:
            (output / "alignment.srt").write_text(render_srt(timeline), encoding="utf-8")
            (output / "template.md").write_text(render_template_emd(timeline).text, encoding="utf-8")
        print("final unplaced:", [(l.segment_id, l.text) for l in unplaced], flush=True)
    finally:
        lifecycle.clear()


if __name__ == "__main__":
    main()
