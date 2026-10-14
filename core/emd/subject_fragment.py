"""Lossless, structural merging of up to four Subject EMD inputs.

Subject numbering follows input and row order. Media slots are independent:
this module never rewrites descriptions, guesses identity, or renumbers media.
"""

from __future__ import annotations

from dataclasses import dataclass

from ..artifacts.base import normalize_newlines
from ..h3_contract import DEFAULT_H3_TIMING_PROFILE, H3TimingProfile
from .parser import parse_emd
from .errors import EMDParseError


SUBJECT_INPUT_NAMES = ("concept_emd", "concept_emd_2", "concept_emd_3", "concept_emd_4")
_PROBE_SCENE = """
> `シーン` 1
# シーン 00:00.000 --> 00:00.208
* `H3長` 5
## ショット 00:00.000
* 未計画
"""


class SubjectEMDFragmentError(ValueError):
    pass


@dataclass(frozen=True, slots=True)
class SubjectInputBinding:
    input_name: str
    input_subject_index: int
    concept_id: str

    def to_dict(self) -> dict[str, object]:
        return {
            "input_name": self.input_name,
            "input_subject_index": self.input_subject_index,
            "concept_id": self.concept_id,
        }


@dataclass(frozen=True, slots=True)
class MergedSubjectEMD:
    text: str
    bindings: tuple[SubjectInputBinding, ...]

    @property
    def status(self) -> str:
        mapping = ",".join(
            f"{item.input_name}[{item.input_subject_index}]={item.concept_id}"
            for item in self.bindings
        )
        return f"subjects={len(self.bindings)}; subject_map={mapping or 'none'}"


def merge_subject_emd(
    concept_emd: str = "",
    concept_emd_2: str = "",
    concept_emd_3: str = "",
    concept_emd_4: str = "",
    *,
    timing_profile: H3TimingProfile = DEFAULT_H3_TIMING_PROFILE,
) -> MergedSubjectEMD:
    """Validate each fragment and merge without a model or a default Subject.

    Empty ports are ignored; the caller owns any all-empty fallback. A single
    supplied fragment keeps its normalized text, including internal whitespace.
    The four-port limit does not expand the EMD limit of four Subject rows.
    """
    fragments: list[str] = []
    bindings: list[SubjectInputBinding] = []
    for name, raw in zip(SUBJECT_INPUT_NAMES, (
        concept_emd, concept_emd_2, concept_emd_3, concept_emd_4,
    )):
        if not isinstance(raw, str):
            raise SubjectEMDFragmentError(f"{name} must be a string")
        if "\x00" in raw:
            raise SubjectEMDFragmentError(f"{name} contains NUL")
        text = normalize_newlines(raw).strip()
        if not text:
            continue
        headings = [line for line in text.split("\n") if line.startswith("# ")]
        if headings != ["# サブジェクト"]:
            raise SubjectEMDFragmentError(f"{name} must be one # サブジェクト fragment")
        try:
            document = parse_emd(text + "\n" + _PROBE_SCENE, timing_profile=timing_profile)
        except EMDParseError as exc:
            raise SubjectEMDFragmentError(f"invalid {name}: {exc}") from exc
        if len(bindings) + len(document.subjects) > 4:
            raise SubjectEMDFragmentError(
                f"merged # サブジェクト supports at most 4 lines; exceeded at {name}"
            )
        fragments.append(text)
        for index, _subject in enumerate(document.subjects, 1):
            bindings.append(SubjectInputBinding(name, index, f"サブジェクト{len(bindings) + 1}"))
    if not fragments:
        return MergedSubjectEMD("", ())
    text = fragments[0]
    for fragment in fragments[1:]:
        text += "\n" + fragment.split("\n", 1)[1]
    return MergedSubjectEMD(text + "\n", tuple(bindings))
