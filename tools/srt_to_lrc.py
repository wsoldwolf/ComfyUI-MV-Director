"""Convert SRT (including ComfyUI's SRT-in-.txt output) to simple UTF-8 LRC.

Each cue becomes one line at its start time; end times are not represented in
simple LRC. Multiline cue text is joined with spaces. Default timestamps use
centiseconds truncated from milliseconds; --precision 3 retains milliseconds.
No third-party dependencies or GPU are required.
"""
from __future__ import annotations

import argparse
from pathlib import Path
import re


_TIMING = re.compile(
    r"^[ \t]*(\d+:\d{2}:\d{2}[,.]\d{3})[ \t]*-->[ \t]*"
    r"(\d+:\d{2}:\d{2}[,.]\d{3})(?:[ \t]+[^\r\n]+)?[ \t]*$"
)


def _milliseconds(timestamp: str) -> int:
    hours, minutes, seconds, milliseconds = map(int, re.split(r"[:,.]", timestamp))
    if minutes >= 60 or seconds >= 60:
        raise ValueError(f"invalid SRT timestamp: {timestamp}")
    return ((hours * 60 + minutes) * 60 + seconds) * 1000 + milliseconds


def convert_srt(text: str, *, precision: int = 2) -> str:
    """Validate all cues before emitting LRC, preserving cue order and text."""
    if precision not in (2, 3):
        raise ValueError("precision must be 2 or 3")
    text = text.lstrip("\ufeff").replace("\r\n", "\n").replace("\r", "\n").strip()
    if not text:
        raise ValueError("SRT input is empty")
    output = []
    for number, block in enumerate(re.split(r"\n(?:[ \t]*\n)+", text), 1):
        lines = block.splitlines()
        # Accept ordinary numbered SRT and timestamp-first exported cues.
        timing_index = 1 if lines[0].strip().isdigit() else 0
        match = _TIMING.fullmatch(lines[timing_index]) if len(lines) > timing_index else None
        if match is None:
            raise ValueError(f"cue {number}: missing or invalid SRT timing line")
        start, end = map(_milliseconds, match.groups())
        if end < start:
            raise ValueError(f"cue {number}: end time precedes start time")
        lyric = " ".join(line.strip() for line in lines[timing_index + 1:] if line.strip())
        if not lyric:
            raise ValueError(f"cue {number}: subtitle text is empty")
        minutes, remainder = divmod(start, 60000)
        seconds, milliseconds = divmod(remainder, 1000)
        fraction = milliseconds // 10 if precision == 2 else milliseconds
        output.append(f"[{minutes:02d}:{seconds:02d}.{fraction:0{precision}d}]{lyric}")
    return "\n".join(output) + "\n"


def convert_file(source: Path, destination: Path | None = None, *, precision: int = 2,
                 encoding: str = "utf-8-sig", force: bool = False) -> Path:
    source = Path(source)
    destination = Path(destination) if destination is not None else source.with_suffix(".lrc")
    if source.resolve() == destination.resolve() or (
        destination.exists() and source.exists() and source.samefile(destination)
    ):
        raise ValueError("output must not overwrite the source file")
    if destination.exists() and not force:
        raise FileExistsError(f"output already exists: {destination}; use --force to overwrite")
    lrc = convert_srt(source.read_text(encoding=encoding), precision=precision)
    # Exclusive creation prevents accidental overwrites, including a race.
    with destination.open("w" if force else "x", encoding="utf-8", newline="\n") as file:
        file.write(lrc)
    return destination


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("input", type=Path, help="SRT file, or .txt containing SRT")
    parser.add_argument("-o", "--output", type=Path, help="default: input filename with .lrc extension")
    parser.add_argument("--precision", type=int, choices=(2, 3), default=2,
                        help="timestamp decimal digits: 2 (centiseconds) or 3 (milliseconds)")
    parser.add_argument("--encoding", default="utf-8-sig", help="input encoding (default: UTF-8, BOM accepted)")
    parser.add_argument("--force", action="store_true", help="overwrite an existing output, never the input")
    args = parser.parse_args(argv)
    try:
        destination = convert_file(args.input, args.output, precision=args.precision,
                                   encoding=args.encoding, force=args.force)
    except (OSError, ValueError, LookupError) as exc:
        parser.exit(1, f"error: {exc}\n")
    print(destination.resolve())


if __name__ == "__main__":
    main()
