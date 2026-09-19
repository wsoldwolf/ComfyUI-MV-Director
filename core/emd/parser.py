"""Strict line-oriented parser for MVD_EMD_V1."""

from __future__ import annotations

import re
from dataclasses import dataclass, replace

from ..artifacts.base import normalize_newlines
from ..h3_contract import DEFAULT_H3_TIMING_PROFILE, H3TimingProfile

from .ast import (
    AudioDirective,
    EMDDocument,
    LyricAnnotation,
    RetentionDirective,
    Scene,
    SceneSetting,
    Shot,
    Subject,
)
from .errors import EMDParseError
from .scene_fragment import SceneEMDFragmentError, parse_scene_emd_fragment


_TIME_RE = re.compile(r"([0-9]{2,}):([0-5][0-9])\.([0-9]{3})\Z")
_SUBJECT_MEDIA_RE = re.compile(r"`(画像([1-9])|動画([1-3])|音声([1-3]))`")
_SCENE_ANNOTATION_RE = re.compile(r"> `シーン` ([1-9][0-9]*)\Z")
_SCENE_RE = re.compile(
    r"# シーン ([0-9]{2,}:[0-5][0-9]\.[0-9]{3}) --> "
    r"([0-9]{2,}:[0-5][0-9]\.[0-9]{3})( 継続)?\Z"
)
_H3_LENGTH_RE = re.compile(r"\* `H3長` ([1-9][0-9]*)\Z")
_SHOT_RE = re.compile(r"## ショット ([0-9]{2,}:[0-5][0-9]\.[0-9]{3})\Z")
_ANNOTATION_RE = re.compile(
    r"> `(セクション|歌詞開始|歌詞終了|歌詞)`(?: (.*))?\Z"
)
_CONTEXT_LIP_RE = re.compile(
    r"\* `リップシンク` `Context Loop` `(サブジェクト[1-4])`\Z"
)
_AUDIO_LIP_RE = re.compile(
    r"\* `リップシンク` `Audio参照` "
    r"`(サブジェクト[1-4])` `音声([1-3])`\Z"
)
_LYRIC_LIP_RE = re.compile(
    r"\* `リップシンク` `歌詞` "
    r"`(サブジェクト[1-4])` 「(.+)」\Z"
)
_SIMPLE_AUDIO_RE = re.compile(r"\* `(明示台詞のみ|無音)`\Z")
_CONCEPT_TOKEN_RE = re.compile(r"`(サブジェクト[1-4])`")
_SHOT_CONCEPT_START_RE = re.compile(
    r"\* `サブジェクト[1-4]`(?:\s|\Z)"
)
_RETENTION_RE = re.compile(
    r"\* `(サブジェクト[1-4])`:\s*"
    r"`(fully_preserved|partially_preserved)`\s+(.+)\Z"
)
_RESERVED_LIST_RE = re.compile(r"\* `[^`]+`(?:\s|\Z)")
_D_TAG_RE = re.compile(r"</?d(?:\[[^\]\r\n]+\])?>")
_COMMON_SECTIONS = (
    "スタイル",
    "環境",
    "時間・照明",
    "モーション",
    "カメラ",
    "その他",
)


def parse_time_ms(value: str, *, line_number: int = 0) -> int:
    match = _TIME_RE.fullmatch(value)
    if match is None:
        raise EMDParseError(line_number, f"invalid EMD time: {value!r}")
    minutes, seconds, millis = (int(part) for part in match.groups())
    return (minutes * 60 + seconds) * 1000 + millis


def _validate_dialogue_markup(text: str, line_number: int) -> None:
    if text.count("「") != text.count("」"):
        raise EMDParseError(line_number, "unbalanced Japanese dialogue brackets")
    depth = 0
    for match in _D_TAG_RE.finditer(text):
        token = match.group(0)
        if token.startswith("</"):
            if depth != 1:
                raise EMDParseError(line_number, "unmatched </d> tag")
            depth = 0
        else:
            if depth:
                raise EMDParseError(line_number, "nested <d> tag")
            depth = 1
    if depth:
        raise EMDParseError(line_number, "unclosed <d> tag")
    cleaned = _D_TAG_RE.sub("", text)
    if "<d" in cleaned or "</d" in cleaned:
        raise EMDParseError(line_number, "malformed <d> tag")


@dataclass(frozen=True, slots=True)
class _Line:
    number: int
    text: str


class _Parser:
    def __init__(self, source: str, timing_profile: H3TimingProfile) -> None:
        normalized = normalize_newlines(source)
        if "\x00" in normalized:
            raise EMDParseError(0, "NUL is not allowed")
        self.lines = tuple(
            _Line(number, text)
            for number, text in enumerate(normalized.split("\n"), 1)
            if text != ""
        )
        self.index = 0
        self.timing_profile = timing_profile

    def current(self) -> _Line | None:
        return self.lines[self.index] if self.index < len(self.lines) else None

    def take(self) -> _Line:
        line = self.current()
        if line is None:
            raise EMDParseError(0, "unexpected end of document")
        self.index += 1
        return line

    def expect(self, text: str) -> _Line:
        line = self.take()
        if line.text != text:
            raise EMDParseError(line.number, f"expected {text!r}")
        return line

    def parse(self) -> EMDDocument:
        if not self.lines:
            raise EMDParseError(0, "empty EMD is not compiler-ready")
        self.expect("# サブジェクト")
        subjects = self.parse_subjects()
        scene_setting: SceneSetting | None = None
        retention: tuple[RetentionDirective, ...] = ()
        common: tuple[tuple[str, tuple[str, ...]], ...] = ()
        line = self.current()
        if line and line.text == "# シーン設定":
            scene_setting = self.parse_scene_setting()
        line = self.current()
        if line and line.text == "# 保持分析":
            retention = self.parse_retention(subjects)
        line = self.current()
        if line and line.text == "# 共通プロンプト":
            common = self.parse_common_prompt()
        scenes = self.parse_scenes()
        self.validate_concept_references(subjects, scenes)
        if self.current() is not None:
            line = self.current()
            raise EMDParseError(line.number, "unexpected trailing content")
        return EMDDocument(subjects, retention, common, scenes, scene_setting)

    def parse_scene_setting(self) -> SceneSetting:
        start = self.current()
        assert start is not None
        fragment_lines: list[str] = [self.take().text]
        while (line := self.current()) is not None:
            if line.text in {"# 保持分析", "# 共通プロンプト"}:
                break
            if line.text.startswith("> `シーン`"):
                break
            fragment_lines.append(self.take().text)
        try:
            setting = parse_scene_emd_fragment("\n".join(fragment_lines) + "\n")
        except SceneEMDFragmentError as exc:
            raise EMDParseError(start.number, f"invalid # シーン設定: {exc}") from exc
        return replace(setting, line_number=start.number)

    @staticmethod
    def validate_concept_references(
        subjects: tuple[Subject, ...], scenes: tuple[Scene, ...]
    ) -> None:
        defined = {subject.concept_id for subject in subjects}
        for scene in scenes:
            for shot in scene.shots:
                for text in shot.body:
                    for match in _CONCEPT_TOKEN_RE.finditer(text):
                        if match.group(1) not in defined:
                            raise EMDParseError(
                                shot.line_number,
                                f"Shot references undefined concept ID {match.group(1)}",
                            )
                for concept_id, _ in shot.lyric_lip_sync:
                    if concept_id not in defined:
                        raise EMDParseError(
                            shot.line_number,
                            f"lip-sync references undefined concept ID {concept_id}",
                        )
            for directive in scene.audio_directives:
                if (
                    directive.target_concept_id is not None
                    and directive.target_concept_id not in defined
                ):
                    raise EMDParseError(
                        directive.line_number,
                        "audio directive references undefined concept ID",
                    )

    def parse_subjects(self) -> tuple[Subject, ...]:
        subjects: list[Subject] = []
        while (line := self.current()) is not None:
            if not line.text.startswith("* "):
                break
            if len(subjects) >= 4:
                raise EMDParseError(line.number, "# サブジェクト supports at most 4 lines")
            start = self.take()
            content = start.text[2:].strip()
            references: list[str] = []
            position = 0
            while True:
                match = _SUBJECT_MEDIA_RE.match(content, position)
                if match is None or match.start() != position:
                    break
                token = match.group(1)
                if token.startswith("画像"):
                    reference = f"<Picture {match.group(2)}>"
                elif token.startswith("動画"):
                    reference = f"<Video {match.group(3)}>"
                else:
                    reference = f"<Audio {match.group(4)}>"
                if reference in references:
                    raise EMDParseError(start.number, "duplicate Subject media reference")
                references.append(reference)
                position = match.end()
                while position < len(content) and content[position] == " ":
                    position += 1
            description = content[position:].strip()
            if "`" in description:
                raise EMDParseError(start.number, "unknown Subject reserved token")
            if not description:
                raise EMDParseError(start.number, "Subject line requires a description")
            index = len(subjects) + 1
            subjects.append(
                Subject(
                    concept_id=f"サブジェクト{index}",
                    subject_ref=f"<Subject {index}>",
                    description=description,
                    references=tuple(references),
                    line_number=start.number,
                )
            )
        if not subjects:
            line = self.current()
            raise EMDParseError(
                line.number if line else 0, "# サブジェクト requires a Subject record"
            )
        return tuple(subjects)

    def parse_list_section(self, heading: str) -> tuple[str, ...]:
        self.expect(heading)
        values: list[str] = []
        while (line := self.current()) is not None and line.text.startswith("* "):
            if line.text.startswith("* `"):
                raise EMDParseError(line.number, f"reserved line is invalid in {heading}")
            values.append(line.text[2:])
            self.take()
        if not values:
            line = self.current()
            raise EMDParseError(
                line.number if line else 0, f"{heading} must not be empty"
            )
        return tuple(values)

    def parse_retention(
        self, subjects: tuple[Subject, ...]
    ) -> tuple[RetentionDirective, ...]:
        self.expect("# 保持分析")
        defined = {subject.concept_id for subject in subjects}
        values: list[RetentionDirective] = []
        while (line := self.current()) is not None and line.text.startswith("* "):
            match = _RETENTION_RE.fullmatch(line.text)
            if match is None:
                raise EMDParseError(
                    line.number,
                    "retention line must use a defined concept ID, fixed mode, and description",
                )
            if match.group(1) not in defined:
                raise EMDParseError(line.number, "retention references undefined concept ID")
            values.append(
                RetentionDirective(
                    concept_id=match.group(1),
                    mode=match.group(2),
                    description=match.group(3),
                    line_number=line.number,
                )
            )
            self.take()
        if not values:
            line = self.current()
            raise EMDParseError(
                line.number if line else 0, "# 保持分析 must not be empty"
            )
        return tuple(values)

    def parse_common_prompt(self) -> tuple[tuple[str, tuple[str, ...]], ...]:
        self.expect("# 共通プロンプト")
        sections: list[tuple[str, tuple[str, ...]]] = []
        expected_index = 0
        while (line := self.current()) is not None and line.text.startswith("## "):
            name = line.text[3:]
            if name not in _COMMON_SECTIONS:
                raise EMDParseError(line.number, "unknown common prompt subsection")
            actual_index = _COMMON_SECTIONS.index(name)
            if actual_index < expected_index:
                raise EMDParseError(line.number, "common prompt subsection order is invalid")
            expected_index = actual_index + 1
            self.take()
            values: list[str] = []
            while (
                (line := self.current()) is not None
                and line.text.startswith("* ")
                and not line.text.startswith("* `")
            ):
                values.append(line.text[2:])
                self.take()
            if not values:
                raise EMDParseError(
                    line.number if line else 0, f"## {name} must not be empty"
                )
            sections.append((name, tuple(values)))
        if not sections:
            line = self.current()
            raise EMDParseError(
                line.number if line else 0, "# 共通プロンプト must not be empty"
            )
        return tuple(sections)

    def parse_scenes(self) -> tuple[Scene, ...]:
        scenes: list[Scene] = []
        previous_end = 0
        while (line := self.current()) is not None:
            annotation = _SCENE_ANNOTATION_RE.fullmatch(line.text)
            if annotation is None:
                raise EMDParseError(line.number, "Scene annotation is required")
            annotation_line = self.take()
            scene_number = int(annotation.group(1))
            if scene_number != len(scenes) + 1:
                raise EMDParseError(
                    annotation_line.number,
                    f"Scene number must be {len(scenes) + 1}",
                )
            heading_line = self.take()
            if heading_line.number != annotation_line.number + 1:
                raise EMDParseError(
                    heading_line.number,
                    "Scene heading must be on the physical line after annotation",
                )
            heading = _SCENE_RE.fullmatch(heading_line.text)
            if heading is None:
                raise EMDParseError(
                    heading_line.number, "Scene heading must follow annotation"
                )
            start_ms = parse_time_ms(heading.group(1), line_number=heading_line.number)
            end_ms = parse_time_ms(heading.group(2), line_number=heading_line.number)
            continuation = heading.group(3) is not None
            if not scenes and continuation:
                raise EMDParseError(
                    heading_line.number, "first Scene cannot use 継続"
                )
            if start_ms != previous_end or end_ms <= start_ms:
                raise EMDParseError(
                    heading_line.number, "Scenes must be positive and contiguous"
                )
            if end_ms - start_ms > 60_000:
                raise EMDParseError(
                    heading_line.number, "Scene duration must be at most 60000 ms"
                )
            length_line = self.take()
            length_match = _H3_LENGTH_RE.fullmatch(length_line.text)
            if length_match is None:
                raise EMDParseError(
                    length_line.number, "H3長 must be the first Scene line"
                )
            h3_length = int(length_match.group(1))
            try:
                self.timing_profile.validate_raw_length(h3_length)
            except ValueError as exc:
                raise EMDParseError(
                    length_line.number, str(exc)
                ) from exc
            descriptions: list[str] = []
            while (line := self.current()) is not None:
                if line.text.startswith("> `") or line.text.startswith("## ショット "):
                    break
                if line.text.startswith("* ") and not line.text.startswith("* `"):
                    descriptions.append(line.text[2:])
                    self.take()
                    continue
                break
            pending_annotations: list[LyricAnnotation] = []
            shots: list[Shot] = []
            while (line := self.current()) is not None:
                if line.text.startswith("> `") and not _SCENE_ANNOTATION_RE.fullmatch(
                    line.text
                ):
                    pending_annotations.append(self.parse_lyric_annotation())
                    continue
                shot_match = _SHOT_RE.fullmatch(line.text)
                if shot_match is None:
                    break
                shot_line = self.take()
                shot_start = parse_time_ms(
                    shot_match.group(1), line_number=shot_line.number
                )
                body: list[str] = []
                lyric_sync: list[tuple[str, str]] = []
                while (body_line := self.current()) is not None:
                    lyric_match = _LYRIC_LIP_RE.fullmatch(body_line.text)
                    if lyric_match:
                        lyric_sync.append((lyric_match.group(1), lyric_match.group(2)))
                        self.take()
                        continue
                    if body_line.text.startswith("* "):
                        if (
                            _RESERVED_LIST_RE.match(body_line.text)
                            and not _SHOT_CONCEPT_START_RE.match(body_line.text)
                        ):
                            raise EMDParseError(
                                body_line.number, "unknown Shot reserved directive"
                            )
                        text = body_line.text[2:]
                        _validate_dialogue_markup(text, body_line.number)
                        body.append(text)
                        self.take()
                        continue
                    break
                if not body:
                    raise EMDParseError(shot_line.number, "Shot requires body text")
                shots.append(
                    Shot(
                        start_ms=shot_start,
                        body=tuple(body),
                        lyric_annotations=tuple(pending_annotations),
                        lyric_lip_sync=tuple(lyric_sync),
                        line_number=shot_line.number,
                    )
                )
                pending_annotations = []
            if pending_annotations:
                raise EMDParseError(
                    pending_annotations[0].line_number,
                    "lyric annotation must be followed by a Shot",
                )
            if not shots:
                raise EMDParseError(heading_line.number, "Scene requires at least one Shot")
            if shots[0].start_ms != start_ms:
                raise EMDParseError(
                    shots[0].line_number, "first Shot must start at Scene start"
                )
            for index, shot in enumerate(shots):
                if shot.start_ms < start_ms or shot.start_ms >= end_ms:
                    raise EMDParseError(shot.line_number, "Shot is outside Scene")
                if index and shot.start_ms <= shots[index - 1].start_ms:
                    raise EMDParseError(
                        shot.line_number, "Shot times must be strictly increasing"
                    )

            audio: list[AudioDirective] = []
            line = self.current()
            if line and line.text == "## 音響":
                self.take()
                while (directive_line := self.current()) is not None:
                    parsed = self.parse_audio_directive(directive_line)
                    if parsed is None:
                        break
                    audio.append(parsed)
                    self.take()
                if not audio:
                    raise EMDParseError(line.number, "## 音響 must not be empty")
            self.validate_audio_modes(shots, audio)
            scenes.append(
                Scene(
                    scene_number=scene_number,
                    start_ms=start_ms,
                    end_ms=end_ms,
                    h3_length=h3_length,
                    descriptions=tuple(descriptions),
                    shots=tuple(shots),
                    audio_directives=tuple(audio),
                    line_number=heading_line.number,
                    continuation=continuation,
                )
            )
            previous_end = end_ms
        if not scenes:
            raise EMDParseError(0, "at least one Scene is required")
        return tuple(scenes)

    def parse_lyric_annotation(self) -> LyricAnnotation:
        values: dict[str, tuple[str, int]] = {}
        order = {"セクション": 0, "歌詞開始": 1, "歌詞終了": 2, "歌詞": 3}
        previous = -1
        first_line = self.current()
        while (line := self.current()) is not None:
            match = _ANNOTATION_RE.fullmatch(line.text)
            if match is None:
                break
            label, value = match.groups()
            position = order[label]
            if position <= previous or label in values:
                raise EMDParseError(line.number, "lyric annotation order is invalid")
            if value is None or value == "":
                raise EMDParseError(line.number, f"{label} must not be empty")
            previous = position
            values[label] = (value, line.number)
            self.take()
            if label == "歌詞":
                break
        if "歌詞" not in values:
            raise EMDParseError(
                first_line.number if first_line else 0, "歌詞 annotation is required"
            )
        has_start = "歌詞開始" in values
        has_end = "歌詞終了" in values
        if has_start != has_end:
            raise EMDParseError(
                first_line.number if first_line else 0,
                "歌詞開始 and 歌詞終了 must appear together",
            )
        start_ms = (
            parse_time_ms(values["歌詞開始"][0], line_number=values["歌詞開始"][1])
            if has_start
            else None
        )
        end_ms = (
            parse_time_ms(values["歌詞終了"][0], line_number=values["歌詞終了"][1])
            if has_end
            else None
        )
        if start_ms is not None and end_ms is not None and end_ms <= start_ms:
            raise EMDParseError(values["歌詞終了"][1], "歌詞終了 must be after 歌詞開始")
        return LyricAnnotation(
            text=values["歌詞"][0],
            section=values.get("セクション", (None, 0))[0],
            start_ms=start_ms,
            end_ms=end_ms,
            line_number=values["歌詞"][1],
        )

    @staticmethod
    def parse_audio_directive(line: _Line) -> AudioDirective | None:
        if match := _CONTEXT_LIP_RE.fullmatch(line.text):
            return AudioDirective("context_loop", match.group(1), None, line.number)
        if match := _AUDIO_LIP_RE.fullmatch(line.text):
            return AudioDirective(
                "audio_reference", match.group(1), int(match.group(2)), line.number
            )
        if match := _SIMPLE_AUDIO_RE.fullmatch(line.text):
            mode = "explicit_dialogue_only" if match.group(1) == "明示台詞のみ" else "silence"
            return AudioDirective(mode, None, None, line.number)
        if line.text.startswith("* "):
            raise EMDParseError(line.number, "unknown audio directive")
        return None

    @staticmethod
    def validate_audio_modes(
        shots: list[Shot], directives: list[AudioDirective]
    ) -> None:
        lyric_mode = any(shot.lyric_lip_sync for shot in shots)
        lip_modes = [
            directive for directive in directives if directive.mode in {"context_loop", "audio_reference"}
        ]
        if len(lip_modes) > 1:
            raise EMDParseError(lip_modes[1].line_number, "lip-sync modes are exclusive")
        if lyric_mode and lip_modes:
            raise EMDParseError(
                lip_modes[0].line_number, "lip-sync modes are exclusive"
            )
        silence = next((item for item in directives if item.mode == "silence"), None)
        if silence and (len(directives) > 1 or lyric_mode):
            raise EMDParseError(
                silence.line_number, "silence cannot be combined with audio directives"
            )
        seen: set[str] = set()
        for directive in directives:
            if directive.mode in seen:
                raise EMDParseError(
                    directive.line_number, "duplicate audio directive"
                )
            seen.add(directive.mode)


def parse_emd(
    source: str,
    *,
    timing_profile: H3TimingProfile = DEFAULT_H3_TIMING_PROFILE,
) -> EMDDocument:
    if not isinstance(source, str):
        raise EMDParseError(0, "EMD source must be a string")
    timing_profile.validate()
    return _Parser(source, timing_profile).parse()
