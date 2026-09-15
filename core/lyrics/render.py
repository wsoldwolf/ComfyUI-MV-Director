"""Render Template EMD and SRT from the canonical timeline."""

from __future__ import annotations

from ..artifacts import EMDTextArtifact, TimelineArtifact


def format_emd_time(value_ms: int) -> str:
    minutes, remainder = divmod(value_ms, 60_000)
    seconds, millis = divmod(remainder, 1000)
    return f"{minutes:02d}:{seconds:02d}.{millis:03d}"


def format_srt_time(value_ms: int) -> str:
    hours, remainder = divmod(value_ms, 3_600_000)
    minutes, remainder = divmod(remainder, 60_000)
    seconds, millis = divmod(remainder, 1000)
    return f"{hours:02d}:{minutes:02d}:{seconds:02d},{millis:03d}"


def render_template_emd(timeline: TimelineArtifact) -> EMDTextArtifact:
    timeline.validate()
    lyrics_by_shot: dict[tuple[int, int], list[object]] = {}
    for lyric in timeline.lyrics:
        lyrics_by_shot.setdefault((lyric.scene_number, lyric.shot_index), []).append(lyric)
    lines: list[str] = []
    for scene in timeline.scenes:
        if lines:
            lines.append("")
        lines.extend(
            [
                f"> `シーン` {scene.scene_number}",
                f"# シーン {format_emd_time(scene.start_ms)} --> {format_emd_time(scene.end_ms)}",
                f"* `H3長` {scene.raw_length}",
            ]
        )
        for shot_index, shot in enumerate(scene.shots, 1):
            for lyric in lyrics_by_shot.get((scene.scene_number, shot_index), []):
                lines.extend(
                    [
                        f"> `セクション` {lyric.section}",
                        f"> `歌詞開始` {format_emd_time(lyric.start_ms)}",
                        f"> `歌詞終了` {format_emd_time(lyric.end_ms)}",
                        f"> `歌詞` {lyric.text}",
                    ]
                )
            lines.extend(
                [
                    f"## ショット {format_emd_time(shot.start_ms)}",
                    "* 未計画",
                ]
            )
    return EMDTextArtifact.create("MVD_EMD_TEMPLATE_V1", "\n".join(lines) + "\n")


def render_srt(timeline: TimelineArtifact, *, offset_ms: int = 0) -> str:
    timeline.validate()
    blocks: list[str] = []
    for index, lyric in enumerate(timeline.lyrics, 1):
        start = max(0, lyric.start_ms + offset_ms)
        end = max(start + 1, lyric.end_ms + offset_ms)
        blocks.append(
            f"{index}\n{format_srt_time(start)} --> {format_srt_time(end)}\n{lyric.text}"
        )
    return "\n\n".join(blocks) + ("\n" if blocks else "")
