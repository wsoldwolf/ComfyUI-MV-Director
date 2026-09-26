"""Finite multi-task Timeline Planner orchestration."""

from __future__ import annotations

from dataclasses import dataclass, replace
from difflib import SequenceMatcher
import json
import logging
import re
from typing import Any, Mapping, Protocol

from ..artifacts import DirectionArtifact, EMDTextArtifact, canonical_json, normalize_newlines
from ..direction.profiles import (
    CAMERA_ARC_ROLL_POLICIES,
    CAMERA_RENDER_STYLES,
    CAMERA_LYRIC_CUE_MODES,
    CAMERA_LYRIC_INTERPRETATIONS,
    CAMERA_PLANNER_POLICIES,
    CAMERA_PRIORITY_LYRIC_CUES,
    MOTION_BODY_ACCENT_POLICIES,
    MOTION_CHOREOGRAPHY_PHRASES,
    MOTION_CHOREOGRAPHY_POLICIES,
    MOTION_PERFORMANCE_MODES,
)
from ..emd import parse_scene_emd_fragment
from ..emd.ast import Scene
from ..h3_contract import (
    ANIME_EMOTIONAL_FACE_PERFORMANCE_CUT_CAMERA,
    FACE_PERFORMANCE_CUT_ACTION,
    FACE_PERFORMANCE_CUT_CAMERA,
)
from ..inference import LlamaRuntimeConfig
from ..protocols import LLMRecordIssue, parse_llm_records
from .dialogue import DialogueFilter, DialogueProtector
from .choreography import accept_choreography_choice
from .errors import TimelinePlannerError
from .layout import (
    apply_scene_continuations,
    apply_shot_layouts,
    build_layout_candidates,
    parse_scene_layout_selection,
    repair_scene_layout_selection,
)
from .renderer import render_completed_emd
from .request_budget import complete_with_context_recovery
from .scene_spine import (
    SceneSpineStep, parse_scene_spine_step, validate_contact_coverage,
    validate_scene_spine,
)
from .staging import parse_staging_selection
from .text_normalization import strip_generated_line_continuation
from .template import (
    PlannerTemplate,
    normalize_concept_emd,
    normalize_scene_emd,
    parse_template_emd,
)


PLANNER_ALGORITHM_VERSION = "mvd-timeline-planner-v85-compact-camera-render"
_ACTION_AUDIT_REPAIR_ATTEMPTS = 1
_LOGGER = logging.getLogger("mv_director.nodes")
TASKS = (
    "staging-selection",
    "visual-beats",
    "song-direction",
    "shot-layout",
    "actions",
    "action-audit",
    "cameras",
)
_CAMERA_MOTION_TYPES = (
    "Roll Counterclockwise",
    "Roll Clockwise",
    "Shake Slightly",
    "Shake Strongly",
    "Pedestal Down",
    "Pedestal Up",
    "Tracking Shot",
    "Static Shot",
    "Arc Shot",
    "Truck Right",
    "Truck Left",
    "Push In",
    "Pull Out",
    "Zoom In",
    "Zoom Out",
    "Pan Left",
    "Pan Right",
    "Tilt Up",
    "Tilt Down",
    "POV",
)
_LOWER_BODY_DETAIL_RE = re.compile(
    r"足元|足先|左足|右足|両足|足袋|履物|下駄|草履|toe|foot|feet|footwear",
    re.IGNORECASE,
)
_SLOW_CAMERA_RE = re.compile(r"at slow speed|ゆっくり|緩やか", re.IGNORECASE)
_LARGE_FAST_ARC_RE = re.compile(
    r"^Arc Shot\s+with large amplitude\s+at fast speed\b",
    re.IGNORECASE,
)
_SLOW_ACTION_RE = re.compile(
    r"ゆっくり|緩やか|そっと|静かに|徐々に|slowly|gently|gradually",
    re.IGNORECASE,
)
_GENERIC_HAND_ACTION_RE = re.compile(
    r"(?:右|左|両|片)?(?:手|腕)(?:を|が)?"
    r"[^。！？\n]{0,32}?"
    r"(?:上げ(?:る|た|て|ている)?|下げ(?:る|た|て|ている)?|"
    r"上下(?:させる|する|している)?)",
    re.IGNORECASE,
)
_FACE_PERFORMANCE_RE = re.compile(
    r"目|眼|まぶた|瞼|瞬き|閉眼|開眼|伏し目|見開|細め|"
    r"視線|眼差し|眉|口|唇|表情|顔",
    re.IGNORECASE,
)
_RUNNING_ACTION_RE = re.compile(
    r"走(?:る|り|った|って)|駆け(?:る|出す|抜ける|寄る)?|疾走|全力疾走|"
    r"\brun(?:ning|s)?\b|\bsprint(?:ing|s)?\b",
    re.IGNORECASE,
)
_INTERNAL_ACTION_LABEL_RE = re.compile(
    r"\b(?:ACTION|BEAT|CAMERA|AUDIT)\s+[0-9]+\b",
    re.IGNORECASE,
)
_ACTION_PROTOCOL_PREFIX_RE = re.compile(
    r"^\s*(?:(?:ACTION|BEAT|CAMERA|AUDIT)(?:\s+[0-9]+)+|"
    r"[0-9]+\s+|(?:TAB|タブ|<TAB>|\\t)[\s　]+)",
    re.IGNORECASE,
)
_ACTION_AUDIT_REASONS = frozenset(
    {
        "SEMANTIC_REPETITION",
        "PROFILE_CONFLICT",
        "INCIDENTAL_FIXTURE",
        "UNREQUESTED_LOWER_BODY",
        "UNREQUESTED_CONTACT",
        "REFERENCE_POSE",
        "MISSING_GROUNDED_CUE",
        "FACE_PERFORMANCE_MISSING",
        "BODY_TEMPLATE_REPETITION",
        "BODY_ACCENT_MISSING",
        "INTERNAL_PROTOCOL_LABEL",
    }
)

class TimelinePlannerBackend(Protocol):
    def complete_planner(
        self,
        *,
        task: str,
        system_prompt: str,
        payload: str,
        config: LlamaRuntimeConfig,
        interrupt_callback: Any = None,
    ) -> str:
        ...


@dataclass(frozen=True, slots=True)
class PlannerContent:
    visual_beats: tuple[tuple[int, str], ...]
    song_direction: str
    shot_layouts: tuple[tuple[int, tuple[int, ...]], ...]
    actions: tuple[tuple[int, int, str], ...]
    cameras: tuple[tuple[int, int, str], ...]
    issue_count: int
    retried_scenes: tuple[int, ...]
    removed_generated_dialogue_count: int
    unused_protected_dialogue_ids: tuple[str, ...]
    scene_continuations: tuple[tuple[int, bool], ...] = ()
    layout_repaired_scenes: tuple[int, ...] = ()
    layout_fallback_scenes: tuple[int, ...] = ()
    layout_mix_retry: bool = False
    protocol_recovered_count: int = 0
    repetition_warning_count: int = 0
    beat_repetition_warning_count: int = 0
    action_repetition_warning_count: int = 0
    camera_repetition_warning_count: int = 0
    song_direction_fallback: bool = False
    scene_spine_steps: tuple[tuple[int, int, str], ...] = ()
    scene_spine_skipped_scenes: tuple[int, ...] = ()
    events: tuple[tuple[int, int, str], ...] = ()
    typed_output: bool = False
    motion_compositions: tuple[tuple[int, int, str, int, str], ...] = ()
    terminal_states: tuple[tuple[int, str, str, str], ...] = ()

    def to_dict(self) -> dict[str, object]:
        return {
            "visual_beats": [list(value) for value in self.visual_beats],
            "song_direction": self.song_direction,
            "shot_layouts": [
                [scene, list(starts)] for scene, starts in self.shot_layouts
            ],
            "scene_continuations": [
                [scene, continuation]
                for scene, continuation in self.scene_continuations
            ],
            "actions": [list(value) for value in self.actions],
            "cameras": [list(value) for value in self.cameras],
            "issue_count": self.issue_count,
            "retried_scenes": list(self.retried_scenes),
            "removed_generated_dialogue_count": self.removed_generated_dialogue_count,
            "unused_protected_dialogue_ids": list(self.unused_protected_dialogue_ids),
            "layout_repaired_scenes": list(self.layout_repaired_scenes),
            "layout_fallback_scenes": list(self.layout_fallback_scenes),
            "layout_mix_retry": self.layout_mix_retry,
            "protocol_recovered_count": self.protocol_recovered_count,
            "repetition_warning_count": self.repetition_warning_count,
            "beat_repetition_warning_count": self.beat_repetition_warning_count,
            "action_repetition_warning_count": self.action_repetition_warning_count,
            "camera_repetition_warning_count": self.camera_repetition_warning_count,
            "song_direction_fallback": self.song_direction_fallback,
            "scene_spine_steps": [list(value) for value in self.scene_spine_steps],
            "scene_spine_skipped_scenes": list(self.scene_spine_skipped_scenes),
            "events": [list(value) for value in self.events],
            "typed_output": self.typed_output,
            "motion_compositions": [list(value) for value in self.motion_compositions],
            "terminal_states": [list(value) for value in self.terminal_states],
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "PlannerContent":
        return cls(
            visual_beats=tuple(
                (int(row[0]), str(row[1])) for row in value["visual_beats"]
            ),
            song_direction=str(value["song_direction"]),
            shot_layouts=tuple(
                (int(row[0]), tuple(int(item) for item in row[1]))
                for row in value["shot_layouts"]
            ),
            scene_continuations=tuple(
                (int(row[0]), bool(row[1]))
                for row in value.get("scene_continuations", ())
            ),
            actions=tuple((int(row[0]), int(row[1]), str(row[2])) for row in value["actions"]),
            cameras=tuple((int(row[0]), int(row[1]), str(row[2])) for row in value["cameras"]),
            issue_count=int(value["issue_count"]),
            retried_scenes=tuple(int(item) for item in value["retried_scenes"]),
            removed_generated_dialogue_count=int(value["removed_generated_dialogue_count"]),
            unused_protected_dialogue_ids=tuple(str(item) for item in value["unused_protected_dialogue_ids"]),
            layout_repaired_scenes=tuple(
                int(item) for item in value.get("layout_repaired_scenes", ())
            ),
            layout_fallback_scenes=tuple(
                int(item) for item in value["layout_fallback_scenes"]
            ),
            layout_mix_retry=bool(value.get("layout_mix_retry", False)),
            protocol_recovered_count=int(
                value.get("protocol_recovered_count", 0)
            ),
            repetition_warning_count=int(
                value.get("repetition_warning_count", 0)
            ),
            beat_repetition_warning_count=int(
                value.get("beat_repetition_warning_count", 0)
            ),
            action_repetition_warning_count=int(
                value.get("action_repetition_warning_count", 0)
            ),
            camera_repetition_warning_count=int(
                value.get("camera_repetition_warning_count", 0)
            ),
            song_direction_fallback=bool(
                value.get("song_direction_fallback", False)
            ),
            scene_spine_steps=tuple(
                (int(row[0]), int(row[1]), str(row[2]))
                for row in value.get("scene_spine_steps", ())
            ),
            scene_spine_skipped_scenes=tuple(
                int(scene) for scene in value.get("scene_spine_skipped_scenes", ())
            ),
            events=tuple(
                (int(row[0]), int(row[1]), str(row[2]))
                for row in value.get("events", ())
            ),
            typed_output=bool(value.get("typed_output", False)),
            motion_compositions=tuple(
                (int(r[0]), int(r[1]), str(r[2]), int(r[3]), str(r[4]))
                for r in value.get("motion_compositions", ())),
            terminal_states=tuple(
                (int(r[0]), str(r[1]), str(r[2]), str(r[3]))
                for r in value.get("terminal_states", ())),
        )


@dataclass(frozen=True, slots=True)
class TimelinePlannerResult:
    emd: EMDTextArtifact
    content: PlannerContent | None
    complete: bool
    missing: tuple[tuple[str, int, int], ...]


@dataclass(frozen=True, slots=True)
class _Entity:
    scene_number: int
    key: tuple[int, ...]
    value: dict[str, object]


_CUE_CARD_FIELDS = (
    "感情",
    "根拠",
    "対象",
    "接触",
    "現象",
    "配置",
    "可視展開",
    "身体主導",
    "終端",
)
_CUE_NONE_VALUES = frozenset({"", "なし", "無し", "none", "NONE"})


def build_cue_card_grammar(slots: list[int]) -> str:
    """Constrain the existing transport/field schema, never creative text."""
    if not slots or any(type(slot) is not int or slot < 1 for slot in slots):
        raise ValueError("Cue grammar requires positive integer slots")
    if len(set(slots)) != len(slots):
        raise ValueError("Cue grammar slots must be unique")
    quote = lambda value: json.dumps(value, ensure_ascii=False)
    rows: list[str] = []
    for slot in slots:
        fields = [quote(f"BEAT\t{slot}\t")]
        for index, name in enumerate(_CUE_CARD_FIELDS):
            fields.append(quote(("" if index == 0 else "｜") + name + "="))
            if name == "接触":
                fields.append('("禁止" | "許可")')
            elif name == "現象":
                fields.append('("なし" | "外部自律" | "身体操作")')
            else:
                fields.append("cell")
        rows.append(" ".join(fields))
    return (
        "root ::= " + ' "\\n" '.join(rows) + ' "\\n"?\n'
        + r"cell ::= [^\x00-\x1f｜]+" + "\n"
    )


_CAMERA_PLAN_FIELDS = (
    "MOTION",
    "START_SCALE",
    "END_SCALE",
    "START_VIEW",
    "END_VIEW",
    "PATH",
    "COVERAGE",
)
_CAMERA_PLAN_SCALES = frozenset(
    {
        "wide",
        "full_body",
        "medium_wide",
        "medium",
        "upper_body",
        "head_and_shoulders",
        "face_closeup",
    }
)
_CAMERA_PLAN_VIEWS = frozenset(
    {
        "front",
        "front_three_quarter",
        "side",
        "rear_three_quarter",
        "over_shoulder",
        "high_front",
        "low_front_three_quarter",
    }
)
_CAMERA_PLAN_PATHS = frozenset(
    {
        "stationary",
        "zoom_in_35_55",
        "zoom_out",
        "push_in",
        "pull_out",
        "pan_left",
        "pan_right",
        "truck_left",
        "truck_right",
        "tilt_up",
        "tilt_down",
        "pedestal_up",
        "pedestal_down",
        "arc_left_60_120_70_90",
        "arc_right_60_120_70_90",
        "arc_left_60_120_70_90_roll_counterclockwise",
        "arc_right_60_120_70_90_roll_clockwise",
        "tracking_forward",
        "tracking_lateral",
        "shake",
        "roll_clockwise",
        "roll_counterclockwise",
    }
)
_ARC_BASE_PATHS = frozenset({"arc_left_60_120_70_90", "arc_right_60_120_70_90"})
_ARC_ROLL_PATHS = frozenset({
    "arc_left_60_120_70_90_roll_counterclockwise",
    "arc_right_60_120_70_90_roll_clockwise",
})


def _arc_base_path(path: str) -> str:
    return path.split("_roll_", 1)[0] if path in _ARC_ROLL_PATHS else path
_CAMERA_PLAN_COVERAGE = frozenset(
    {
        "environment_relation",
        "lyric_target",
        "lyric_target_and_hands",
        "lyric_target_and_body",
        "whole_body_emotion",
        "whole_body_hands",
        "upper_body_hands",
        "face_eyes_mouth",
        "expressive_result",
    }
)


def build_camera_plan_grammar(slots: list[Mapping[str, object]]) -> str:
    """Constrain finite Camera transport without choosing its framing for the LLM."""

    numbers = [slot.get("slot") for slot in slots]
    if (
        not numbers
        or any(type(number) is not int or number < 1 for number in numbers)
        or len(set(numbers)) != len(numbers)
        or any(slot.get("camera_protocol") != "finite_v1" for slot in slots)
    ):
        raise ValueError("Camera grammar requires unique finite_v1 slots")
    quote = lambda value: json.dumps(value, ensure_ascii=False)
    rows: list[str] = []
    rules = [
        "camera-view ::= " + " | ".join(map(quote, sorted(_CAMERA_PLAN_VIEWS))),
    ]
    for slot in slots:
        number = slot["slot"]
        paths = set(_CAMERA_PATH_MOTIONS)
        if slot.get("face_zoom_emphasis"):
            paths = {"zoom_in_35_55"}
        elif slot.get("arc_roll_emphasis"):
            paths = set(_ARC_ROLL_PATHS)
        elif slot.get("arc_permission") == "required" or slot.get("face_arc_transition"):
            paths = set(_ARC_BASE_PATHS)
        elif slot.get("arc_permission") == "forbidden":
            paths.difference_update(_ARC_BASE_PATHS | _ARC_ROLL_PATHS)
        previous_arc = slot.get("previous_arc_path")
        if previous_arc and paths <= _ARC_BASE_PATHS | _ARC_ROLL_PATHS:
            paths = {path for path in paths if _arc_base_path(path) == previous_arc}
        if not paths:
            raise ValueError("Camera grammar has no permitted path")
        motions = {
            (
                "Arc Shot with large amplitude at fast speed"
                if motion == "Arc Shot" else
                "Zoom In with large amplitude at fast speed"
                if motion == "Zoom In" else
                "Zoom Out with large amplitude at fast speed"
                if motion == "Zoom Out" else
                motion if motion == "Static Shot" else
                f"{motion} at fast speed"
            )
            for path in paths
            for motion in _CAMERA_PATH_MOTIONS[path]
        }
        rules.append(
            f"camera-motion-{number} ::= "
            + " | ".join(map(quote, sorted(motions)))
        )
        face_out_roll = (
            slot.get("arc_roll_emphasis")
            and slot.get("face_arc_transition") == "arc_out_of_previous_face_cut"
        )
        start_scales = (
            {"face_closeup", "head_and_shoulders"} if face_out_roll else
            _CAMERA_PLAN_SCALES - {"face_closeup", "head_and_shoulders"}
            if slot.get("arc_roll_emphasis") else
            _CAMERA_PLAN_SCALES
        )
        end_scales = (
            {"full_body"} if face_out_roll else
            _CAMERA_PLAN_SCALES - {"face_closeup", "head_and_shoulders"}
            if slot.get("arc_roll_emphasis") else
            _CAMERA_PLAN_SCALES
        )
        if slot.get("body_phrase_accent"):
            body_scales = {"wide", "medium_wide", "full_body"}
            if slot.get("face_arc_transition") == "arc_into_next_face_cut":
                start_scales &= body_scales
            else:
                end_scales &= body_scales
        rules.append(
            f"camera-start-scale-{number} ::= "
            + " | ".join(map(quote, sorted(start_scales)))
        )
        rules.append(
            f"camera-end-scale-{number} ::= "
            + " | ".join(map(quote, sorted(end_scales)))
        )
        rules.append(
            f"camera-path-{number} ::= "
            + " | ".join(map(quote, sorted(paths)))
        )
        required_coverage = (
            "whole_body_hands" if face_out_roll
            and slot.get("required_spine_coverage") == "upper_body_hands"
            else "whole_body_emotion" if face_out_roll
            else slot.get("required_spine_coverage")
        )
        coverages = (
            {str(required_coverage)} if required_coverage in _CAMERA_PLAN_COVERAGE
            else _CAMERA_PLAN_COVERAGE
        )
        rules.append(
            f"camera-coverage-{number} ::= "
            + " | ".join(map(quote, sorted(coverages)))
        )
        rows.append(
            quote(f"CAMERA\t{number}\tMOTION=")
            + f" camera-motion-{number} "
            + quote("｜START_SCALE=") + f" camera-start-scale-{number} "
            + quote("｜END_SCALE=") + f" camera-end-scale-{number} "
            + quote("｜START_VIEW=") + " camera-view "
            + quote("｜END_VIEW=") + " camera-view "
            + quote("｜PATH=") + f" camera-path-{number} "
            + quote("｜COVERAGE=") + f" camera-coverage-{number}"
        )
    return "root ::= " + ' "\\n" '.join(rows) + ' "\\n"?\n' + "\n".join(rules) + "\n"


@dataclass(frozen=True, slots=True)
class _CueCard:
    emotion: str = ""
    evidence: str = ""
    target: str = ""
    contact: str = "禁止"
    phenomenon: str = "なし"
    spatial_anchor: str = "なし"
    visible_development: str = "なし"
    body_driver: str = ""
    final_state: str = ""
    valid: bool = False
    violations: tuple[str, ...] = ()

    def to_dict(self) -> dict[str, object]:
        return {
            "valid": self.valid,
            "emotion": self.emotion,
            "evidence": self.evidence,
            "target": self.target,
            "contact": self.contact,
            "phenomenon": self.phenomenon,
            "spatial_anchor": self.spatial_anchor,
            "visible_development": self.visible_development,
            "body_driver": self.body_driver,
            "final_state": self.final_state,
            "violations": list(self.violations),
        }


def _continuation_body_state(
    previous_scene_number: int | None,
    *,
    continuation: bool,
    last_shot_by_scene: Mapping[int, int],
    cue_cards: Mapping[tuple[int, ...], _CueCard],
    scene_spine_steps: Mapping[tuple[int, int], SceneSpineStep],
) -> str:
    """Pass through the previous LLM-authored end state, without rewriting it."""

    if not continuation or previous_scene_number is None:
        return ""
    last_shot = last_shot_by_scene.get(previous_scene_number)
    previous_spine = scene_spine_steps.get((previous_scene_number, last_shot))
    if previous_spine is not None:
        return previous_spine.to_state
    previous_card = cue_cards.get((previous_scene_number,))
    return previous_card.final_state if previous_card is not None else ""


def _continuation_effect_state(
    previous_scene_number: int | None,
    *,
    continuation: bool,
    last_shot_by_scene: Mapping[int, int],
    scene_spine_steps: Mapping[tuple[int, int], SceneSpineStep],
) -> str:
    """Carry only an LLM-authored external-effect endpoint across CONTINUE."""

    if not continuation or previous_scene_number is None:
        return ""
    last_shot = last_shot_by_scene.get(previous_scene_number)
    previous_spine = scene_spine_steps.get((previous_scene_number, last_shot))
    return previous_spine.effect_to if previous_spine is not None else ""


@dataclass(frozen=True, slots=True)
class _CameraPlan:
    motion: str
    start_scale: str
    end_scale: str
    start_view: str
    end_view: str
    path: str
    coverage: str


def _parse_camera_plan(text: str) -> tuple[_CameraPlan | None, tuple[str, ...]]:
    """Parse the finite Camera choice protocol without inferring missing fields."""

    parts = [part.strip() for part in text.split("｜")]
    parsed: dict[str, str] = {}
    violations: list[str] = []
    if len(parts) != len(_CAMERA_PLAN_FIELDS):
        violations.append("camera_plan_field_count")
    for index, part in enumerate(parts):
        if "=" not in part:
            violations.append("camera_plan_field_syntax")
            continue
        name, value = (item.strip() for item in part.split("=", 1))
        if index >= len(_CAMERA_PLAN_FIELDS) or name != _CAMERA_PLAN_FIELDS[index]:
            violations.append("camera_plan_field_order")
        if name in parsed:
            violations.append("camera_plan_duplicate_field")
        parsed[name] = value
    if set(parsed) != set(_CAMERA_PLAN_FIELDS):
        violations.append("camera_plan_field_set")

    motion = parsed.get("MOTION", "")
    base_motion = _camera_motion_type(motion)
    if not base_motion or len(_camera_motion_occurrences(motion)) != 1:
        violations.append("camera_plan_motion")
    elif not re.fullmatch(
        rf"{re.escape(base_motion)}(?: with (?:small|large) amplitude)?"
        r"(?: at (?:slow|fast) speed)?",
        motion,
    ):
        violations.append("camera_plan_motion_modifier")
    if parsed.get("START_SCALE") not in _CAMERA_PLAN_SCALES:
        violations.append("camera_plan_start_scale")
    if parsed.get("END_SCALE") not in _CAMERA_PLAN_SCALES:
        violations.append("camera_plan_end_scale")
    if parsed.get("START_VIEW") not in _CAMERA_PLAN_VIEWS:
        violations.append("camera_plan_start_view")
    if parsed.get("END_VIEW") not in _CAMERA_PLAN_VIEWS:
        violations.append("camera_plan_end_view")
    if parsed.get("PATH") not in _CAMERA_PLAN_PATHS:
        violations.append("camera_plan_path")
    if parsed.get("COVERAGE") not in _CAMERA_PLAN_COVERAGE:
        violations.append("camera_plan_coverage")
    unique = tuple(dict.fromkeys(violations))
    if unique:
        return None, unique
    return (
        _CameraPlan(
            motion=motion,
            start_scale=parsed["START_SCALE"],
            end_scale=parsed["END_SCALE"],
            start_view=parsed["START_VIEW"],
            end_view=parsed["END_VIEW"],
            path=parsed["PATH"],
            coverage=parsed["COVERAGE"],
        ),
        (),
    )


_CAMERA_PATH_MOTIONS = {
    "stationary": frozenset({"Static Shot"}),
    "zoom_in_35_55": frozenset({"Zoom In"}),
    "zoom_out": frozenset({"Zoom Out"}),
    "push_in": frozenset({"Push In"}),
    "pull_out": frozenset({"Pull Out"}),
    "pan_left": frozenset({"Pan Left"}),
    "pan_right": frozenset({"Pan Right"}),
    "truck_left": frozenset({"Truck Left"}),
    "truck_right": frozenset({"Truck Right"}),
    "tilt_up": frozenset({"Tilt Up"}),
    "tilt_down": frozenset({"Tilt Down"}),
    "pedestal_up": frozenset({"Pedestal Up"}),
    "pedestal_down": frozenset({"Pedestal Down"}),
    "arc_left_60_120_70_90": frozenset({"Arc Shot"}),
    "arc_right_60_120_70_90": frozenset({"Arc Shot"}),
    "arc_left_60_120_70_90_roll_counterclockwise": frozenset({"Arc Shot"}),
    "arc_right_60_120_70_90_roll_clockwise": frozenset({"Arc Shot"}),
    "tracking_forward": frozenset({"Tracking Shot"}),
    "tracking_lateral": frozenset({"Tracking Shot"}),
    "shake": frozenset({"Shake Slightly", "Shake Strongly"}),
    "roll_clockwise": frozenset({"Roll Clockwise"}),
    "roll_counterclockwise": frozenset({"Roll Counterclockwise"}),
}


def _camera_plan_contract_violations(
    entity: _Entity,
    plan: _CameraPlan,
) -> tuple[str, ...]:
    violations: list[str] = []
    motion = _camera_motion_type(plan.motion)
    if motion not in _CAMERA_PATH_MOTIONS.get(plan.path, frozenset()):
        violations.append("camera_plan_motion_path_mismatch")
    if motion in {"Zoom In", "Zoom Out", "Push In", "Pull Out", "Static Shot"}:
        if plan.start_view != plan.end_view:
            violations.append("camera_plan_unmotivated_view_change")
    if motion == "Static Shot" and plan.start_scale != plan.end_scale:
        violations.append("camera_plan_static_scale_change")
    if motion == "Arc Shot":
        if (
            plan.start_scale == plan.end_scale
            and plan.start_view == plan.end_view
        ):
            violations.append("camera_plan_arc_no_composition_change")
        if int(entity.value.get("shot_duration_ms", 0)) < 2500:
            violations.append("camera_plan_short_arc")
        if entity.value.get("arc_permission") == "forbidden":
            violations.append("unassigned_arc")
        if not _LARGE_FAST_ARC_RE.search(plan.motion):
            violations.append("required_long_arc_energy")
        previous_path = entity.value.get("previous_arc_path")
        if previous_path and _arc_base_path(plan.path) != previous_path:
            violations.append("camera_plan_arc_direction_reversal")
    if plan.path in _ARC_ROLL_PATHS:
        if not entity.value.get("arc_roll_emphasis"):
            violations.append("unassigned_arc_roll")
        face_out_roll = (
            entity.value.get("face_arc_transition")
            == "arc_out_of_previous_face_cut"
        )
        if face_out_roll and (
            plan.start_scale not in {"face_closeup", "head_and_shoulders"}
            or plan.end_scale != "full_body"
            or plan.coverage != (
                "whole_body_hands"
                if entity.value.get("required_spine_coverage") == "upper_body_hands"
                else "whole_body_emotion"
            )
        ):
            violations.append("arc_roll_face_handoff")
        if not face_out_roll and (
            {plan.start_scale, plan.end_scale}
            & {"face_closeup", "head_and_shoulders"}
        ):
            violations.append("arc_roll_requires_room_for_horizon")
        if entity.value.get("face_arc_transition") not in {
            "", None, "arc_out_of_previous_face_cut"
        } or entity.value.get("required_spine_coverage") == "face_eyes_mouth":
            violations.append("arc_roll_conflicts_with_face_coverage")
    elif entity.value.get("arc_roll_emphasis"):
        violations.append("required_arc_roll")
    if (
        plan.end_scale == "face_closeup"
        and plan.coverage in {
            "environment_relation", "whole_body_emotion", "upper_body_hands"
        }
    ):
        violations.append("camera_plan_coverage_scale_conflict")
    required_spine_coverage = entity.value.get("required_spine_coverage")
    if (
        required_spine_coverage
        and plan.coverage != required_spine_coverage
        and not (
            plan.path in _ARC_ROLL_PATHS
            and entity.value.get("face_arc_transition")
            == "arc_out_of_previous_face_cut"
            and required_spine_coverage == "upper_body_hands"
            and plan.coverage == "whole_body_hands"
        )
    ):
        violations.append("required_spine_coverage")
    if required_spine_coverage in {
        "lyric_target", "lyric_target_and_hands", "lyric_target_and_body"
    }:
        if {plan.start_scale, plan.end_scale} & {"face_closeup", "head_and_shoulders"}:
            violations.append("spine_target_occluded")
    if required_spine_coverage == "lyric_target_and_body" and not {
        plan.start_scale, plan.end_scale
    } & {"wide", "medium_wide", "full_body", "medium"}:
        violations.append("spine_body_accent_not_visible")
    if entity.value.get("body_phrase_accent"):
        body_scales = {"wide", "medium_wide", "full_body"}
        scale = (
            plan.start_scale
            if entity.value.get("face_arc_transition") == "arc_into_next_face_cut"
            else plan.end_scale
        )
        if scale not in body_scales:
            violations.append("body_phrase_accent_not_visible")
    if entity.value.get("single_prechorus_body_accent") and not {
        plan.start_scale, plan.end_scale
    } & {"wide", "medium_wide", "full_body"}:
        violations.append("prechorus_body_accent_not_visible")
    if required_spine_coverage in {"whole_body_emotion", "whole_body_hands"}:
        if not {plan.start_scale, plan.end_scale} & {
            "wide", "medium_wide", "full_body"
        }:
            violations.append("spine_whole_body_not_visible")
    if required_spine_coverage == "face_eyes_mouth" and plan.end_view not in {
        "front", "front_three_quarter", "high_front", "low_front_three_quarter"
    }:
        violations.append("spine_face_not_readable")
    if required_spine_coverage == "face_eyes_mouth" and plan.end_scale in {
        "wide", "medium_wide", "full_body"
    }:
        violations.append("spine_face_too_distant")
    if entity.value.get("arc_permission") == "required" and motion != "Arc Shot":
        violations.append("required_long_arc_emphasis")
    if entity.value.get("face_zoom_emphasis"):
        if motion != "Zoom In" or plan.path != "zoom_in_35_55":
            violations.append("required_face_zoom_emphasis")
        if plan.end_scale != "face_closeup" or plan.coverage != "face_eyes_mouth":
            violations.append("required_face_visibility")
    if entity.value.get("face_arc_transition"):
        if motion != "Arc Shot":
            violations.append("required_face_arc_transition")
        relation = str(entity.value.get("face_arc_transition"))
        if relation == "arc_into_next_face_cut" and plan.end_scale not in {
            "head_and_shoulders",
            "face_closeup",
        }:
            violations.append("required_face_handoff_scale")
        if relation == "arc_out_of_previous_face_cut" and plan.start_scale not in {
            "head_and_shoulders",
            "face_closeup",
        }:
            violations.append("required_face_handoff_scale")
    return tuple(dict.fromkeys(violations))


_CAMERA_SCALE_TEXT = {
    "wide": "a wide shot",
    "full_body": "a full-body shot",
    "medium_wide": "a medium-wide shot",
    "medium": "a medium shot",
    "upper_body": "an upper-body shot",
    "head_and_shoulders": "a head-and-shoulders shot",
    "face_closeup": "a readable face close-up",
}
_CAMERA_VIEW_TEXT = {
    "front": "a frontal viewpoint",
    "front_three_quarter": "a front three-quarter viewpoint",
    "side": "a side viewpoint",
    "rear_three_quarter": "a rear three-quarter viewpoint",
    "over_shoulder": "an over-shoulder viewpoint",
    "high_front": "a high frontal viewpoint",
    "low_front_three_quarter": "a low front three-quarter viewpoint",
}
_CAMERA_PATH_TEXT = {
    "stationary": "Keep camera position, orientation, and focal length fixed",
    "zoom_in_35_55": "Complete the focal-length approach in 35-to-55 percent of the shot",
    "zoom_out": "Widen the focal length continuously through the shot",
    "push_in": "Move the camera physically forward on a direct path",
    "pull_out": "Move the camera physically backward on a direct path",
    "pan_left": "Rotate the lens left from a fixed camera position",
    "pan_right": "Rotate the lens right from a fixed camera position",
    "truck_left": "Translate the entire camera laterally to the left",
    "truck_right": "Translate the entire camera laterally to the right",
    "tilt_up": "Rotate the lens upward from a fixed camera position",
    "tilt_down": "Rotate the lens downward from a fixed camera position",
    "pedestal_up": "Move the entire camera vertically upward",
    "pedestal_down": "Move the entire camera vertically downward",
    "arc_left_60_120_70_90": "Travel on a 60-to-120-degree left arc for 70-to-90 percent of the shot with strong parallax",
    "arc_right_60_120_70_90": "Travel on a 60-to-120-degree right arc for 70-to-90 percent of the shot with strong parallax",
    "arc_left_60_120_70_90_roll_counterclockwise": "Travel on a 60-to-120-degree left arc for 70-to-90 percent of the shot with strong parallax; during the middle third, blend in Roll Counterclockwise with small amplitude around the lens axis, visibly cant the frame by about 10 degrees, then smoothly return the horizon to level before the shot ends while the leftward orbit continues",
    "arc_right_60_120_70_90_roll_clockwise": "Travel on a 60-to-120-degree right arc for 70-to-90 percent of the shot with strong parallax; during the middle third, blend in Roll Clockwise with small amplitude around the lens axis, visibly cant the frame by about 10 degrees, then smoothly return the horizon to level before the shot ends while the rightward orbit continues",
    "tracking_forward": "Follow the existing subject displacement forward through depth",
    "tracking_lateral": "Follow the existing subject displacement laterally",
    "shake": "Apply the named camera shake without changing the framing purpose",
    "roll_clockwise": "Roll clockwise around the lens axis",
    "roll_counterclockwise": "Roll counterclockwise around the lens axis",
}
_CAMERA_COVERAGE_TEXT = {
    "environment_relation": "Keep the subject-to-environment spatial relationship readable",
    "lyric_target": "Keep the lyric-selected target or external phenomenon visible in its spatial setting",
    "lyric_target_and_hands": "Keep the lyric-selected target and the interacting hands visible together",
    "lyric_target_and_body": "Keep the lyric-selected target or external phenomenon visible in its stated location or path while the performer's face, weight shift, torso, and both arms remain readable together",
    "whole_body_emotion": "Keep the complete whole-body emotional silhouette readable without isolating the feet",
    "whole_body_hands": "Finish with the complete whole-body silhouette while keeping the face, arms, and hands readable together; do not isolate the feet",
    "upper_body_hands": "Keep the face, shoulders, arms, and hands readable together",
    "face_eyes_mouth": "Keep both eyes, both eyebrows, the nose, the complete singing mouth, and the facial contour visible",
    "expressive_result": "Keep the changed expression and final silhouette readable",
}
_COMPACT_CAMERA_SCALE_TEXT = {
    "wide": "wide",
    "full_body": "full-body",
    "medium_wide": "medium-wide",
    "medium": "medium",
    "upper_body": "upper-body",
    "head_and_shoulders": "head-and-shoulders",
    "face_closeup": "face close-up",
}
_COMPACT_CAMERA_VIEW_TEXT = {
    "front": "front",
    "front_three_quarter": "front three-quarter",
    "side": "side",
    "rear_three_quarter": "rear three-quarter",
    "over_shoulder": "over-shoulder",
    "high_front": "high front",
    "low_front_three_quarter": "low front three-quarter",
}
_COMPACT_CAMERA_PATH_TEXT = {
    "stationary": "Hold the camera and lens still",
    "zoom_in_35_55": "Zoom in during the first half, then hold the expression",
    "zoom_out": "Widen the lens through the shot",
    "push_in": "Move the camera forward",
    "pull_out": "Move the camera backward",
    "pan_left": "Pivot the camera left in place",
    "pan_right": "Pivot the camera right in place",
    "truck_left": "Move the camera left",
    "truck_right": "Move the camera right",
    "tilt_up": "Pivot the camera upward in place",
    "tilt_down": "Pivot the camera downward in place",
    "pedestal_up": "Raise the camera",
    "pedestal_down": "Lower the camera",
    "arc_left_60_120_70_90": "Move left around the subject",
    "arc_right_60_120_70_90": "Move right around the subject",
    "arc_left_60_120_70_90_roll_counterclockwise": (
        "Move left around the subject; blend in Roll Counterclockwise "
        "with small amplitude, then level the horizon"
    ),
    "arc_right_60_120_70_90_roll_clockwise": (
        "Move right around the subject; blend in Roll Clockwise "
        "with small amplitude, then level the horizon"
    ),
    "tracking_forward": "Follow the subject's forward travel",
    "tracking_lateral": "Follow the subject's lateral travel",
    "shake": "Apply the selected shake without changing the framing",
    "roll_clockwise": "Rotate the frame clockwise",
    "roll_counterclockwise": "Rotate the frame counterclockwise",
}
_COMPACT_CAMERA_COVERAGE_TEXT = {
    "environment_relation": "Show the subject and surrounding space together",
    "lyric_target": "Keep the lyric target visible in its setting",
    "lyric_target_and_hands": "Show the lyric target and interacting hands together",
    "lyric_target_and_body": "Show the lyric target, face, torso, and both arms together",
    "whole_body_emotion": "Show the full-body silhouette and facial expression",
    "whole_body_hands": "Show the full-body silhouette, face, arms, and hands together",
    "upper_body_hands": "Show the face, shoulders, arms, and hands together",
    "face_eyes_mouth": "Show both eyes, eyebrows, nose, and complete singing mouth",
    "expressive_result": "Show the changed expression and final silhouette",
}


def _render_camera_plan(plan: _CameraPlan, *, style: str = "detailed") -> str:
    """Serialize finite LLM selections; never add a target or character action."""

    if style == "compact":
        return (
            f"{plan.motion}. From "
            f"{_COMPACT_CAMERA_VIEW_TEXT[plan.start_view]} "
            f"{_COMPACT_CAMERA_SCALE_TEXT[plan.start_scale]} to "
            f"{_COMPACT_CAMERA_VIEW_TEXT[plan.end_view]} "
            f"{_COMPACT_CAMERA_SCALE_TEXT[plan.end_scale]}. "
            f"{_COMPACT_CAMERA_PATH_TEXT[plan.path]}. "
            f"{_COMPACT_CAMERA_COVERAGE_TEXT[plan.coverage]}."
        )
    if style != "detailed":
        raise ValueError(f"unknown camera render style: {style}")
    return (
        f"{plan.motion}. Start with {_CAMERA_SCALE_TEXT[plan.start_scale]} from "
        f"{_CAMERA_VIEW_TEXT[plan.start_view]}; end with "
        f"{_CAMERA_SCALE_TEXT[plan.end_scale]} from "
        f"{_CAMERA_VIEW_TEXT[plan.end_view]}. {_CAMERA_PATH_TEXT[plan.path]}. "
        f"{_CAMERA_COVERAGE_TEXT[plan.coverage]}."
    )


def _fallback_choice_index(entity: _Entity, ordinal: int, size: int) -> int:
    shot_number = int(entity.key[-1]) if entity.key else 0
    return (entity.scene_number * 2 + shot_number * 5 + ordinal) % size


def _connect_camera_geometry(plan: _CameraPlan, previous: _CameraPlan | None,
                             arc_path: str = "") -> _CameraPlan:
    """Connect Python-owned finite geometry; never change generated Action prose."""
    if previous is None:
        return plan
    plan = replace(plan, start_scale=previous.end_scale, start_view=previous.end_view)
    motion = _camera_motion_type(plan.motion)
    if motion in {"Zoom In", "Zoom Out", "Push In", "Pull Out", "Static Shot"}:
        if plan.coverage == "face_eyes_mouth" and previous.end_view not in {
            "front", "front_three_quarter", "high_front", "low_front_three_quarter"
        }:
            # A rear/side view cannot become a readable frontal face by zoom.
            # The sustained camera contract permits an orbit into that framing.
            return replace(plan, motion="Arc Shot with large amplitude at fast speed",
                           end_view="front_three_quarter",
                           path=arc_path or "arc_right_60_120_70_90")
        plan = replace(plan, end_view=previous.end_view)
        if motion == "Static Shot":
            plan = replace(plan, end_scale=previous.end_scale)
    return plan


def _choose_fallback_camera_option(
    entity: _Entity, ordinal: int, options: tuple[_CameraPlan, ...]
) -> _CameraPlan:
    # Retain an already selected orbit through the entire CUT/CONTINUE group.
    # Diversity cannot override optical geometry or change the direction.
    required_coverage = entity.value.get("required_spine_coverage")
    if required_coverage and not (
        entity.value.get("arc_roll_emphasis")
        and entity.value.get("face_arc_transition")
        == "arc_out_of_previous_face_cut"
    ):
        options = tuple(replace(option, coverage=str(required_coverage)) for option in options)
    allowed = tuple(
        option for option in options
        if not _camera_plan_contract_violations(entity, option)
    )
    if not allowed:
        reasons = (
            ",".join(_camera_plan_contract_violations(entity, options[0]))
            if options else "no_options"
        )
        raise ValueError(
            "no camera fallback satisfies the structural contract: " + reasons
        )
    return allowed[_fallback_choice_index(entity, ordinal, len(allowed))]


def _select_continuous_camera_plan(
    entity: _Entity,
    text: str,
    ordinal: int,
    used: set[str],
    arc_paths: dict[int, str],
    reasons: tuple[str, ...] = (),
) -> tuple[_CameraPlan, tuple[str, ...]]:
    """Select valid finite camera geometry; Action prose is never touched."""
    group = int(entity.value.get("camera_continuity_group", entity.scene_number))
    entity = _Entity(entity.scene_number, entity.key, {
        **entity.value,
        "previous_arc_path": arc_paths.get(group, entity.value.get("previous_arc_path", "")),
    })
    plan, errors = _parse_camera_plan(text)
    violations = tuple(dict.fromkeys((
        *errors, *reasons,
        *(_camera_plan_contract_violations(entity, plan) if plan else ()),
    )))
    if plan is None or violations:
        for variation in range(8):
            candidate = _fallback_camera_plan(entity, ordinal + variation)
            if _render_camera_plan(candidate) not in used or variation == 7:
                plan = candidate
                break
    assert plan is not None
    if _camera_motion_type(plan.motion) == "Arc Shot":
        arc_paths[group] = _arc_base_path(plan.path)
    return plan, violations


def _fallback_camera_plan(entity: _Entity, ordinal: int) -> _CameraPlan:
    """Choose a varied finite structural fallback for an invalid 8B response."""

    required_coverage = entity.value.get("required_spine_coverage")
    if entity.value.get("arc_roll_emphasis"):
        previous_state = entity.value.get("previous_camera_state") or {}
        face_out_roll = (
            entity.value.get("face_arc_transition")
            == "arc_out_of_previous_face_cut"
        )
        generic_scales = (
            ("full_body", "full_body")
            if required_coverage == "whole_body_emotion"
            or entity.value.get("body_phrase_accent") else
            ("wide", "medium_wide")
            if required_coverage == "environment_relation" else
            ("medium", "upper_body")
            if required_coverage == "upper_body_hands" else
            ("medium_wide", "medium")
        )
        start_view = str(previous_state.get("end_view") or (
            "front" if face_out_roll else "low_front_three_quarter"
        ))
        end_view = "side" if start_view != "side" else "front_three_quarter"
        options = tuple(
            _CameraPlan(
                "Arc Shot with large amplitude at fast speed",
                "face_closeup" if face_out_roll else generic_scales[0],
                "full_body" if face_out_roll else generic_scales[1],
                start_view, end_view,
                path, (
                    "whole_body_hands" if face_out_roll
                    and required_coverage == "upper_body_hands"
                    else "whole_body_emotion" if face_out_roll
                    else str(required_coverage or "environment_relation")
                ),
            )
            for path in sorted(_ARC_ROLL_PATHS)
        )
        return _choose_fallback_camera_option(entity, ordinal, options)
    if required_coverage in {
        "lyric_target", "lyric_target_and_hands", "lyric_target_and_body"
    }:
        body_accent = bool(entity.value.get("body_phrase_accent"))
        if entity.value.get("arc_permission") == "required":
            options = tuple(
                _CameraPlan(
                    "Arc Shot with large amplitude at fast speed",
                    "medium_wide", "full_body" if body_accent else "medium",
                    "low_front_three_quarter", "side",
                    path, str(required_coverage),
                )
                for path in ("arc_left_60_120_70_90", "arc_right_60_120_70_90")
            )
        else:
            options = (
                _CameraPlan("Push In at fast speed", "wide", "medium_wide" if body_accent else "medium", "front_three_quarter", "front_three_quarter", "push_in", str(required_coverage)),
                _CameraPlan("Truck Right at fast speed", "medium_wide", "full_body" if body_accent else "medium", "front_three_quarter", "side", "truck_right", str(required_coverage)),
            )
        return _choose_fallback_camera_option(entity, ordinal, options)
    if required_coverage == "face_eyes_mouth":
        if entity.value.get("arc_permission") == "required":
            options = tuple(
                _CameraPlan(
                    "Arc Shot with large amplitude at fast speed",
                    "medium", "head_and_shoulders", "side", "front_three_quarter",
                    path, "face_eyes_mouth",
                )
                for path in ("arc_left_60_120_70_90", "arc_right_60_120_70_90")
            )
        elif entity.value.get("face_zoom_emphasis"):
            options = (
                _CameraPlan("Zoom In with large amplitude at fast speed", "head_and_shoulders", "face_closeup", "front_three_quarter", "front_three_quarter", "zoom_in_35_55", "face_eyes_mouth"),
            )
        else:
            options = (
                _CameraPlan("Push In at fast speed", "upper_body", "head_and_shoulders", "front_three_quarter", "front_three_quarter", "push_in", "face_eyes_mouth"),
            )
        return _choose_fallback_camera_option(entity, ordinal, options)

    relation = str(entity.value.get("face_arc_transition", ""))
    if relation == "arc_into_next_face_cut":
        coverage = (
            str(required_coverage)
            if entity.value.get("body_phrase_accent")
            and required_coverage in {"whole_body_emotion", "whole_body_hands"}
            else "face_eyes_mouth"
        )
        options = (
            _CameraPlan("Arc Shot with large amplitude at fast speed", "full_body", "head_and_shoulders", "low_front_three_quarter", "front_three_quarter", "arc_left_60_120_70_90", coverage),
            _CameraPlan("Arc Shot with large amplitude at fast speed", "medium_wide", "head_and_shoulders" if entity.value.get("body_phrase_accent") else "face_closeup", "rear_three_quarter", "front", "arc_right_60_120_70_90", coverage),
            _CameraPlan("Arc Shot with large amplitude at fast speed", "full_body", "head_and_shoulders", "side", "front_three_quarter", "arc_right_60_120_70_90", coverage),
        )
        return _choose_fallback_camera_option(entity, ordinal, options)
    if relation == "arc_out_of_previous_face_cut":
        options = (
            _CameraPlan("Arc Shot with large amplitude at fast speed", "head_and_shoulders", "full_body", "front_three_quarter", "side", "arc_right_60_120_70_90", "whole_body_emotion"),
            _CameraPlan("Arc Shot with large amplitude at fast speed", "face_closeup", "medium_wide", "front", "rear_three_quarter", "arc_left_60_120_70_90", "whole_body_emotion"),
            _CameraPlan("Arc Shot with large amplitude at fast speed", "head_and_shoulders", "wide", "side", "front_three_quarter", "arc_left_60_120_70_90", "environment_relation"),
        )
        return _choose_fallback_camera_option(entity, ordinal, options)
    if entity.value.get("body_phrase_accent"):
        if entity.value.get("arc_permission") == "required":
            options = tuple(
                _CameraPlan(
                    "Arc Shot with large amplitude at fast speed",
                    "medium_wide", "full_body", "low_front_three_quarter",
                    "side", path, "whole_body_emotion",
                )
                for path in ("arc_left_60_120_70_90", "arc_right_60_120_70_90")
            )
        else:
            options = (
                _CameraPlan("Truck Right at fast speed", "medium_wide", "medium_wide", "side", "side", "truck_right", "whole_body_emotion"),
                _CameraPlan("Pull Out at fast speed", "medium", "medium_wide", "front_three_quarter", "front_three_quarter", "pull_out", "whole_body_emotion"),
            )
        return _choose_fallback_camera_option(entity, ordinal, options)
    if entity.value.get("arc_permission") == "required":
        if (
            entity.value.get("editorial_role") == "upper_body_performance_coverage"
            and required_coverage not in {"whole_body_emotion", "whole_body_hands"}
        ):
            options = tuple(
                _CameraPlan("Arc Shot with large amplitude at fast speed",
                    "medium", "upper_body", "side", "front_three_quarter",
                    path, "upper_body_hands")
                for path in ("arc_left_60_120_70_90", "arc_right_60_120_70_90")
            )
            return _choose_fallback_camera_option(entity, ordinal, options)
        options = (
            _CameraPlan("Arc Shot with large amplitude at fast speed", "full_body", "medium", "low_front_three_quarter", "side", "arc_left_60_120_70_90", "whole_body_emotion"),
            _CameraPlan("Arc Shot with large amplitude at fast speed", "full_body", "upper_body", "rear_three_quarter", "front_three_quarter", "arc_right_60_120_70_90", "expressive_result"),
            _CameraPlan("Arc Shot with large amplitude at fast speed", "medium_wide", "full_body", "side", "rear_three_quarter", "arc_left_60_120_70_90", "whole_body_emotion"),
            _CameraPlan("Arc Shot with large amplitude at fast speed", "wide", "medium", "rear_three_quarter", "front_three_quarter", "arc_right_60_120_70_90", "environment_relation"),
        )
        return _choose_fallback_camera_option(entity, ordinal, options)
    if entity.value.get("face_zoom_emphasis"):
        options = (
            _CameraPlan("Zoom In with large amplitude at fast speed", "head_and_shoulders", "face_closeup", "front_three_quarter", "front_three_quarter", "zoom_in_35_55", "face_eyes_mouth"),
            _CameraPlan("Zoom In with large amplitude at fast speed", "head_and_shoulders", "face_closeup", "front", "front", "zoom_in_35_55", "face_eyes_mouth"),
            _CameraPlan("Zoom In with large amplitude at fast speed", "upper_body", "face_closeup", "front_three_quarter", "front_three_quarter", "zoom_in_35_55", "face_eyes_mouth"),
        )
        return _choose_fallback_camera_option(entity, ordinal, options)
    options = (
        _CameraPlan("Push In at fast speed", "wide", "medium", "front_three_quarter", "front_three_quarter", "push_in", "environment_relation"),
        _CameraPlan("Truck Right at fast speed", "upper_body", "upper_body", "front_three_quarter", "side", "truck_right", "upper_body_hands"),
        _CameraPlan("Pull Out at fast speed", "medium", "wide", "front_three_quarter", "front_three_quarter", "pull_out", "expressive_result"),
        _CameraPlan("Pedestal Up at fast speed", "medium_wide", "medium", "low_front_three_quarter", "front_three_quarter", "pedestal_up", "whole_body_emotion"),
        _CameraPlan("Static Shot", "upper_body", "upper_body", "front_three_quarter", "front_three_quarter", "stationary", "upper_body_hands"),
        _CameraPlan("Zoom Out at fast speed", "head_and_shoulders", "medium_wide", "front", "front", "zoom_out", "environment_relation"),
        _CameraPlan("Pan Right at fast speed", "medium_wide", "medium_wide", "over_shoulder", "rear_three_quarter", "pan_right", "environment_relation"),
        _CameraPlan("Truck Left at fast speed", "medium", "medium", "side", "front_three_quarter", "truck_left", "upper_body_hands"),
    )
    return _choose_fallback_camera_option(entity, ordinal, options)


def _cue_source_texts(entity: _Entity) -> tuple[str, ...]:
    lyrics = entity.value.get("lyrics", [])
    lyric_texts = [
        str(item.get("text", "")).strip()
        for item in lyrics
        if isinstance(item, Mapping) and str(item.get("text", "")).strip()
    ]
    author_body = [
        str(item).strip()
        for item in entity.value.get("author_body", [])
        if str(item).strip()
    ]
    return tuple(lyric_texts + author_body)


def _lyric_reading_contexts(
    scene_numbers: list[int],
    lyrics_by_scene: Mapping[int, list[object]],
) -> dict[int, dict[str, list[str]]]:
    """Bounded adjacent text for reading, never a source of cue authority.

    Do not cross an empty/instrumental Scene. Limit each side to two lines
    and 256 characters in total; no extra inference or inferred lyrics.
    """

    def adjacent(number: int, *, before: bool) -> list[str]:
        texts = [
            str(item.get("text", "")).strip()
            for item in lyrics_by_scene.get(number, [])
            if isinstance(item, Mapping) and str(item.get("text", "")).strip()
        ]
        selected = texts[-2:] if before else texts[:2]
        if before:
            selected.reverse()
        result: list[str] = []
        remaining = 256
        for text in selected:
            if not remaining:
                break
            fragment = text[-remaining:] if before else text[:remaining]
            result.append(fragment)
            remaining -= len(fragment)
        return list(reversed(result)) if before else result

    return {
        number: {
            "before": adjacent(scene_numbers[index - 1], before=True) if index else [],
            "after": adjacent(scene_numbers[index + 1], before=False)
            if index + 1 < len(scene_numbers) else [],
        }
        for index, number in enumerate(scene_numbers)
    }


def _priority_lyric_cues_from_sources(
    lyrics: list[object],
    author_body: list[object],
    configured_cues: tuple[tuple[str, str], ...],
) -> tuple[dict[str, str], ...]:
    """Select configured profile cues only when the current Scene names them."""

    source_texts = [
        str(item.get("text", "")).strip()
        for item in lyrics
        if isinstance(item, Mapping) and str(item.get("text", "")).strip()
    ]
    source_texts.extend(
        str(item).strip() for item in author_body if str(item).strip()
    )
    configured = dict(configured_cues)
    selected: list[dict[str, str]] = []
    seen: set[str] = set()
    for source in source_texts:
        matches = sorted(
            (
                (source.find(token), token, configured[token])
                for token in configured
                if token in source and token not in seen
            ),
            key=lambda item: (item[0], item[1]),
        )
        for _position, token, kind in matches:
            seen.add(token)
            selected.append(
                {"token": token, "kind": kind, "evidence": source}
            )
    return tuple(selected)


def _priority_cue_phase(shot_index: int, shot_count: int) -> str:
    """Assign a finite Scene-development phase without composing Action prose."""

    if shot_count <= 1:
        return "establish_relation_reaction_release"
    if shot_count == 2:
        return (
            "establish_and_relation"
            if shot_index == 1
            else "reaction_and_release"
        )
    if shot_count == 3:
        return (
            "establish_and_relation"
            if shot_index == 1
            else "event_and_reaction"
            if shot_index == 2
            else "release"
        )
    return (
        "establish"
        if shot_index == 1
        else "relation"
        if shot_index == 2
        else "reaction"
        if shot_index == 3
        else "release"
    )


def _with_grounding_transfer_requirements(
    entities: list[_Entity],
    *,
    automatic: bool = False,
) -> list[_Entity]:
    """Assign exact Cue Card fragments to eligible Action slots.

    The fragments remain LLM-authored Visual Beat text. Python selects which
    slot must preserve each fragment, but never composes or edits Action prose.
    """

    by_scene: dict[int, list[_Entity]] = {}
    for entity in entities:
        by_scene.setdefault(entity.scene_number, []).append(entity)

    rewritten: dict[tuple[int, ...], _Entity] = {}
    for scene_entities in by_scene.values():
        ordered = sorted(scene_entities, key=lambda entity: entity.key)
        if (
            not automatic
            and not ordered[0].value.get("priority_lyric_cues")
        ):
            continue
        grounding = ordered[0].value.get("visual_beat_grounding")
        if not isinstance(grounding, Mapping) or not grounding.get("valid"):
            continue
        target = str(grounding.get("target", "")).strip()
        spatial_anchor = str(grounding.get("spatial_anchor", "")).strip()
        visible_development = str(
            grounding.get("visible_development", "")
        ).strip()
        if target in _CUE_NONE_VALUES:
            continue
        if (
            spatial_anchor in _CUE_NONE_VALUES
            or visible_development in _CUE_NONE_VALUES
        ):
            continue

        # Emotional face Actions are LLM-generated too. Do not give their
        # close-up slots the spatial/event obligations of the Scene coverage.
        coverage = [
            entity for entity in ordered
            if entity.value.get("performance_role") != "face_and_upper_body_accent"
        ]
        if coverage and len(coverage) != len(ordered):
            phases = {
                entity.key: (
                    str(entity.value.get("grounded_cue_phase"))
                    if entity.value.get("scene_spine_step")
                    else _priority_cue_phase(index, len(coverage))
                )
                for index, entity in enumerate(coverage, 1)
            }
            for entity in ordered:
                phase = phases.get(entity.key, "")
                rewritten[entity.key] = _Entity(
                    entity.scene_number,
                    entity.key,
                    {
                        **entity.value,
                        "grounded_cue_phase": phase,
                        "priority_cue_phase": (
                            phase if entity.value.get("priority_lyric_cues") else ""
                        ),
                    },
                )
        # A face-only layout has no alternative coverage. Preserve the hard
        # grounding contract rather than silently discarding the selected event.
        eligible = coverage or ordered
        development_entity = next(
            (
                entity for entity in eligible
                if isinstance(entity.value.get("scene_spine_step"), Mapping)
                and entity.value["scene_spine_step"].get("phase") == "event"
            ),
            eligible[0] if len(eligible) == 1 else eligible[1],
        )
        autonomous_effect = grounding.get("phenomenon") == "外部自律"
        anchor_entity = eligible[0]
        requirements = [(anchor_entity, "required_spatial_anchor", spatial_anchor)]
        selected_anchor = ordered[0].value.get("selected_staging_anchor")
        if selected_anchor and selected_anchor != "なし" and development_entity != anchor_entity:
            requirements.append((development_entity, "required_spatial_anchor", spatial_anchor))
        # The LLM-authored Scene step already names the one-time change. The
        # older exact Cue development otherwise duplicates contact in a Shot.
        # An external effect has no contact to duplicate: preserve its actual
        # visible path so H3 receives more than the Subject's reaction.
        if autonomous_effect or not development_entity.value.get("scene_spine_step"):
            requirements.append((
                development_entity, "required_visible_development", visible_development,
            ))
        for entity, field, value in requirements:
            current = rewritten.get(entity.key, entity)
            rewritten[entity.key] = _Entity(
                current.scene_number,
                current.key,
                {**current.value, field: value},
            )

    return [rewritten.get(entity.key, entity) for entity in entities]


def _strip_cue_quote(value: str) -> str:
    return value.strip().strip(" \t\"'「」『』【】[]")


def _parse_cue_card(entity: _Entity, text: str) -> _CueCard:
    """Validate lyric grounding without rewriting the LLM's Cue Card text."""

    parts = [part.strip() for part in text.split("｜")]
    # Explicit target-first wire order; do not change any field value.
    target_first_order = ("対象", "根拠", "感情", *_CUE_CARD_FIELDS[3:])
    if tuple(part.split("=", 1)[0] for part in parts) == target_first_order:
        parts = [parts[2], parts[1], parts[0], *parts[3:]]
    parsed: dict[str, str] = {}
    violations: list[str] = []
    if len(parts) != len(_CUE_CARD_FIELDS):
        violations.append("field_count")
    for index, part in enumerate(parts):
        if "=" not in part:
            violations.append("field_syntax")
            continue
        name, value = (item.strip() for item in part.split("=", 1))
        if index >= len(_CUE_CARD_FIELDS) or name != _CUE_CARD_FIELDS[index]:
            violations.append("field_order")
        if name in parsed:
            violations.append("duplicate_field")
        parsed[name] = value
    if set(parsed) != set(_CUE_CARD_FIELDS):
        violations.append("field_set")

    evidence = _strip_cue_quote(parsed.get("根拠", ""))
    target = _strip_cue_quote(parsed.get("対象", ""))
    contact = parsed.get("接触", "").strip()
    phenomenon = parsed.get("現象", "").strip()
    spatial_anchor = _strip_cue_quote(parsed.get("配置", ""))
    target_location = spatial_anchor
    if spatial_anchor.startswith("対象位置:"):
        target_location, separator, actor_location = spatial_anchor.partition("；人物位置:")
        target_location = target_location.removeprefix("対象位置:").strip()
        if not separator or not target_location or actor_location.strip() in _CUE_NONE_VALUES:
            violations.append("spatial_roles_incomplete")
    visible_development = _strip_cue_quote(parsed.get("可視展開", ""))
    spatial_anchor_is_none = spatial_anchor in _CUE_NONE_VALUES
    visible_development_is_none = visible_development in _CUE_NONE_VALUES
    sources = _cue_source_texts(entity)
    evidence_is_none = evidence in _CUE_NONE_VALUES
    target_is_none = target in _CUE_NONE_VALUES
    if evidence_is_none:
        if sources and (not target_is_none or contact != "禁止" or phenomenon != "なし"):
            violations.append("missing_evidence")
    elif not any(evidence in source for source in sources):
        violations.append("evidence_not_in_scene_source")
    if contact not in {"禁止", "許可"}:
        violations.append("contact_enum")
    if phenomenon not in {"なし", "外部自律", "身体操作"}:
        violations.append("phenomenon_enum")
    if target_is_none:
        if contact == "許可":
            violations.append("contact_without_target")
        if phenomenon != "なし":
            violations.append("phenomenon_without_target")
        if not spatial_anchor_is_none:
            violations.append("spatial_anchor_without_target")
        if not visible_development_is_none:
            violations.append("visible_development_without_target")
    elif evidence_is_none or target not in evidence:
        violations.append("target_not_in_evidence")
    else:
        if spatial_anchor_is_none:
            violations.append("missing_spatial_anchor")
        elif spatial_anchor.startswith("対象位置:") and not target_location.startswith(target):
            violations.append("spatial_target_mismatch")
        if visible_development_is_none:
            violations.append("missing_visible_development")
    selected_staging = entity.value.get("selected_staging_candidate")
    if isinstance(selected_staging, Mapping):
        required_anchor = str(selected_staging.get("anchor", "")).strip()
        if required_anchor and required_anchor != "なし":
            if target_location != required_anchor:
                violations.append("staging_anchor_missing")
            if target not in _CUE_NONE_VALUES and not required_anchor.startswith(target):
                violations.append("staging_target_mismatch")

    unique_violations = tuple(dict.fromkeys(violations))
    return _CueCard(
        emotion=parsed.get("感情", "").strip(),
        evidence=evidence,
        target="なし" if target_is_none else target,
        contact=contact or "禁止",
        phenomenon=phenomenon or "なし",
        spatial_anchor="なし" if spatial_anchor_is_none else spatial_anchor,
        visible_development="なし" if visible_development_is_none else visible_development,
        body_driver=parsed.get("身体主導", "").strip(),
        final_state=parsed.get("終端", "").strip(),
        valid=not unique_violations,
        violations=unique_violations,
    )


def _priority_cue_card_violations(
    card: _CueCard,
    cue: Mapping[str, str],
) -> tuple[str, ...]:
    """Validate one profile-priority cue without interpreting free prose."""

    violations: list[str] = []
    token = str(cue.get("token", "")).strip()
    kind = str(cue.get("kind", "")).strip()
    if not card.valid:
        violations.append("invalid_cue_card")
        violations.extend(card.violations)
    if not token or card.target != token:
        violations.append("priority_target_not_selected")
    if kind == "external_effect":
        if card.phenomenon not in {"外部自律", "身体操作"}:
            violations.append("priority_effect_missing_phenomenon")
        if card.contact != "禁止":
            violations.append("priority_effect_contact_not_forbidden")
    return tuple(dict.fromkeys(violations))


def _chunks(values: list[Any], size: int):
    for index in range(0, len(values), size):
        yield values[index : index + size]


def _scene_batches_with_isolated_priority_cues(
    scenes: list[Any],
    scene_priority_cues: Mapping[int, tuple[dict[str, str], ...]],
    batch_size: int,
):
    """Keep cue-bearing Scenes out of multi-Scene LLM requests.

    Small models can copy a token from a neighbouring slot even when every
    entity carries a correct local scope. Isolation is therefore an input
    routing rule, not a rewrite of accepted LLM text.
    """

    pending: list[Any] = []
    for scene in scenes:
        if scene_priority_cues.get(scene.scene_number):
            if pending:
                yield pending
                pending = []
            yield [scene]
            continue
        pending.append(scene)
        if len(pending) == batch_size:
            yield pending
            pending = []
    if pending:
        yield pending


def _unexpected_priority_cues(
    text: str,
    allowed_cues: tuple[dict[str, str], ...] | list[dict[str, str]],
    configured_cues: tuple[tuple[str, str], ...],
) -> tuple[str, ...]:
    """Return configured Cue tokens that escaped their current Scene scope."""

    allowed_tokens = {
        str(cue.get("token", "")).strip()
        for cue in allowed_cues
        if isinstance(cue, Mapping)
    }
    return tuple(
        token
        for token, _kind in configured_cues
        if token and token in text and token not in allowed_tokens
    )


def _normalize_small_model_response(response: str, record_type: str) -> str:
    """Normalize observed Qwen3-4B protocol spelling without changing slots."""

    normalized = normalize_newlines(response)
    normalized = re.sub(r"<think>.*?</think>", "", normalized, flags=re.DOTALL)
    labelled_slot_line = re.compile(
        rf"^{re.escape(record_type)}\t(?:TAB\t)?slot\s*([0-9]+)\t(?:TAB\t)?(.+)$",
        flags=re.MULTILINE | re.IGNORECASE,
    )
    normalized = labelled_slot_line.sub(
        lambda match: f"{record_type}\t{match.group(1)}\t{match.group(2)}",
        normalized,
    )
    labelled_tab_line = re.compile(
        r"^[^\n\t]*\tTAB\t([0-9]+)\tTAB\t(.+)$",
        flags=re.MULTILINE,
    )
    normalized = labelled_tab_line.sub(
        lambda match: f"{record_type}\t{match.group(1)}\t{match.group(2)}",
        normalized,
    )
    literal_marker = re.compile(
        rf"(^|<TAB>){re.escape(record_type)}<TAB>([0-9]+)<TAB>",
        flags=re.MULTILINE,
    )
    normalized = literal_marker.sub(
        lambda match: (
            ("" if match.group(1) == "" else "\n")
            + f"{record_type}\t{match.group(2)}\t"
        ),
        normalized,
    )
    normalized = re.sub(
        rf"\t{re.escape(record_type)}\t([0-9]+)\t",
        rf"\n{record_type}\t\1\t",
        normalized,
    )
    return normalized


def _strip_redundant_record_envelope(
    text: str,
    record_type: str,
    slot: int,
) -> tuple[str, bool]:
    """Remove only a duplicated transport wrapper from parsed TEXT.

    The outer TSV record already proves the record type and slot. Small models
    sometimes repeat that wrapper inside the third field. Removing this
    transport-only prefix preserves the semantic text AS IS.
    """

    value = text.strip()
    changed = False
    wrappers = (
        re.compile(
            rf"^{re.escape(record_type)}(?:\s+[0-9]+){{1,3}}(?:\s+|[:：]\s*)",
            flags=re.IGNORECASE,
        ),
        re.compile(rf"^{slot}(?:\s+|[:：.)-]\s*)"),
        re.compile(r"^(?:TAB|タブ|<TAB>|\\t)(?:\s+|[:：]\s*)", re.IGNORECASE),
    )
    for _ in range(3):
        for wrapper in wrappers:
            match = wrapper.match(value)
            if match and match.end() < len(value):
                value = value[match.end() :].lstrip()
                changed = True
                break
        else:
            break
    return value, changed


def _recover_unframed_records(
    response: str,
    record_type: str,
    expected_slots: list[int],
    *,
    allow_single_positional: bool = False,
) -> dict[int, str]:
    """Recover only unambiguous line wrappers while preserving TEXT AS IS."""

    if not expected_slots:
        return {}
    normalized = normalize_newlines(response)
    normalized = re.sub(r"<think>.*?</think>", "", normalized, flags=re.DOTALL)
    lines = [
        line.strip()
        for line in normalized.split("\n")
        if line.strip() and not line.strip().startswith("```")
    ]
    expected = set(expected_slots)
    labelled = re.compile(
        rf"^(?:[-*]\s*)?(?:{re.escape(record_type)}\s*)?"
        r"(?:slot\s*)?([0-9]+)\s*(?:\t+|[:：.)]\s*|[-–—]\s+|\s+)"
        r"(.+)$",
        flags=re.IGNORECASE,
    )
    recovered: dict[int, str] = {}
    for line in lines:
        match = labelled.fullmatch(line)
        if not match:
            continue
        slot = int(match.group(1))
        text = match.group(2).strip()
        if slot in expected and slot not in recovered and text:
            recovered[slot] = text
    if recovered:
        return recovered
    # Numbered output for another slot is not an unlabelled positional answer.
    # This matters when a split response omits slots but retains valid siblings.
    if any(labelled.fullmatch(line) for line in lines):
        return {}

    # Isolated retries have a unique side-table mapping.  Small models often
    # wrap that single record in JSON, a Markdown table, or slot/text labels
    # even when instructed to emit TSV.  Accept only wrappers that identify
    # one unambiguous text value; never synthesize or rewrite the value.
    if allow_single_positional and len(expected_slots) == 1:
        expected_slot = expected_slots[0]

        json_candidates: list[str] = []
        json_text = normalized.strip()
        if json_text.startswith("```") and json_text.endswith("```"):
            json_text = re.sub(r"^```(?:json)?\s*", "", json_text)
            json_text = re.sub(r"\s*```$", "", json_text)
        try:
            decoded = json.loads(json_text)
        except (json.JSONDecodeError, TypeError):
            decoded = None
        objects = decoded if isinstance(decoded, list) else [decoded]
        for item in objects:
            if not isinstance(item, dict):
                continue
            item_type = item.get("record_type", item.get("type", record_type))
            item_slot = item.get("slot", expected_slot)
            item_text = item.get("text")
            if (
                str(item_type).upper() == record_type.upper()
                and str(item_slot).isascii()
                and str(item_slot).isdecimal()
                and int(item_slot) == expected_slot
                and isinstance(item_text, str)
                and item_text.strip()
            ):
                json_candidates.append(item_text.strip())
        if len(json_candidates) == 1:
            return {expected_slot: json_candidates[0]}

        pipe_candidates: list[str] = []
        pipe_line = re.compile(
            rf"^\|?\s*{re.escape(record_type)}\s*\|\s*"
            rf"{expected_slot}\s*\|\s*(.+?)\s*\|?$",
            flags=re.IGNORECASE,
        )
        for line in lines:
            match = pipe_line.fullmatch(line)
            if match and match.group(1).strip():
                pipe_candidates.append(match.group(1).strip())
        if len(pipe_candidates) == 1:
            return {expected_slot: pipe_candidates[0]}

        labelled_texts: list[str] = []
        labelled_slots: list[int] = []
        labelled_types: list[str] = []
        for line in lines:
            field = re.fullmatch(
                r"(?:[-*]\s*)?(record_type|type|slot|text)\s*[:：]\s*(.+)",
                line,
                flags=re.IGNORECASE,
            )
            if not field:
                continue
            name, value = field.group(1).lower(), field.group(2).strip()
            if name in {"record_type", "type"}:
                labelled_types.append(value)
            elif name == "slot" and value.isascii() and value.isdecimal():
                labelled_slots.append(int(value))
            elif name == "text" and value:
                labelled_texts.append(value)
        type_matches = not labelled_types or all(
            value.upper() == record_type.upper() for value in labelled_types
        )
        slot_matches = not labelled_slots or all(
            value == expected_slot for value in labelled_slots
        )
        if type_matches and slot_matches and len(labelled_texts) == 1:
            return {expected_slot: labelled_texts[0]}

        # The isolated request itself is the slot side table.  If the model
        # answers with several plain prose lines, preserve every line in order
        # and only normalize the forbidden physical newlines to spaces.  This
        # is deliberately unavailable to normal or multi-slot batches.
        wrapper_line = re.compile(
            rf"^(?:{re.escape(record_type)}|MVD_LLM_RECORDS_V1|"
            rf"slot\s*[:：]?\s*{expected_slot}|{expected_slot})$",
            flags=re.IGNORECASE,
        )
        prose_lines = [line for line in lines if not wrapper_line.fullmatch(line)]
        if type_matches and slot_matches and len(prose_lines) > 1 and not any(
            line.startswith(("#", "{", "[", "|")) for line in prose_lines
        ):
            text = " ".join(
                re.sub(r"^[-*]\s+", "", line, count=1).strip()
                for line in prose_lines
            ).strip()
            if text:
                return {expected_slot: text}

    # With multiple requested slots, an exact line count gives a deterministic
    # side-table mapping. Only Markdown bullet syntax is removed; TEXT is kept.
    if (
        len(expected_slots) < 2
        and not (allow_single_positional and len(expected_slots) == 1)
    ) or len(lines) != len(expected_slots):
        return {}
    positional: dict[int, str] = {}
    for slot, line in zip(expected_slots, lines):
        text = re.sub(r"^[-*]\s+", "", line, count=1).strip()
        if not text or text.startswith(("#", "{", "[")):
            return {}
        positional[slot] = text
    return positional


def _request_entities(
    backend: TimelinePlannerBackend,
    *,
    task: str,
    record_type: str,
    entities: list[_Entity],
    shared: Mapping[str, object],
    system_prompt: str,
    runtime_config: LlamaRuntimeConfig,
    interrupt_callback: Any,
) -> tuple[
    dict[tuple[int, ...], str],
    list[LLMRecordIssue],
    tuple[int, ...],
    tuple[tuple[str, int, int], ...],
    int,
]:
    # Generation must not imitate earlier prose. Audit and repetition checks
    # retain the original history; explicit Direction and retry reasons remain.
    if task in {"visual-beats", "actions"} and shared.get("planner_policy_contract", {}).get("lyric_interpretation") == "bounded":
        shared = {key: value for key, value in shared.items()
                  if key not in {"recent_visual_beat_history", "recent_action_history", "forbidden_recent_outputs"}}
        entities = [replace(entity, value={key: value for key, value in entity.value.items()
                    if key not in {"previous_batch_beat", "previous_batch_action", "must_differ_from"}})
                    for entity in entities]
    slot_entities = {index: entity for index, entity in enumerate(entities, 1)}
    slots = [dict(entity.value, slot=slot) for slot, entity in slot_entities.items()]
    payload = canonical_json(
        {"protocol": "MVD_LLM_RECORDS_V1", "task": task, **dict(shared), "slots": slots}
    )
    response = complete_with_context_recovery(
        backend,
        task=task,
        system_prompt=system_prompt,
        payload=payload,
        config=runtime_config,
        interrupt_callback=interrupt_callback,
    )
    allowed = {record_type: frozenset(slot_entities)}
    required = frozenset((record_type, slot) for slot in slot_entities)
    parsed = parse_llm_records(
        _normalize_small_model_response(response, record_type),
        allowed_slots=allowed,
        required=required,
    )
    records = {record.slot: record.text for record in parsed.records}
    issues = list(parsed.issues)
    retried_scenes: list[int] = []
    recovered_count = 0

    first_missing = [slot for slot in slot_entities if slot not in records]
    recovered = _recover_unframed_records(
        response, record_type, first_missing
    )
    records.update(recovered)
    recovered_count += len(recovered)

    missing_slots = [slot for slot in slot_entities if slot not in records]
    for scene_number in sorted({slot_entities[slot].scene_number for slot in missing_slots}):
        scene_slots = [
            slot for slot in missing_slots if slot_entities[slot].scene_number == scene_number
        ]
        retry_payload = canonical_json(
            {
                "protocol": "MVD_LLM_RECORDS_V1",
                "task": task,
                **dict(shared),
                "retry": "missing_slots_only",
                "slots": [dict(slot_entities[slot].value, slot=slot) for slot in scene_slots],
            }
        )
        retry_response = complete_with_context_recovery(
            backend,
            task=task,
            system_prompt=system_prompt,
            payload=retry_payload,
            config=runtime_config,
            interrupt_callback=interrupt_callback,
        )
        retry_allowed = {record_type: frozenset(scene_slots)}
        retry_required = frozenset((record_type, slot) for slot in scene_slots)
        retry = parse_llm_records(
            _normalize_small_model_response(retry_response, record_type),
            allowed_slots=retry_allowed,
            required=retry_required,
        )
        issues.extend(retry.issues)
        retry_records = {record.slot: record.text for record in retry.records}
        records.update(retry_records)
        retry_missing = [
            slot for slot in scene_slots if slot not in retry_records
        ]
        recovered = _recover_unframed_records(
            retry_response, record_type, retry_missing
        )
        records.update(recovered)
        recovered_count += len(recovered)
        retried_scenes.append(scene_number)

    # A small model can still omit one of several records in the scene-local
    # retry. Isolate each remaining slot so its side-table mapping is unique.
    # No natural-language content is synthesized or rewritten here.
    isolated_missing = [slot for slot in slot_entities if slot not in records]
    for slot in isolated_missing:
        entity = slot_entities[slot]
        isolated_payload = canonical_json(
            {
                "protocol": "MVD_LLM_RECORDS_V1",
                "task": task,
                **dict(shared),
                "retry": "isolated_missing_slot",
                "slots": [dict(entity.value, slot=slot)],
            }
        )
        isolated_response = complete_with_context_recovery(
            backend,
            task=task,
            system_prompt=system_prompt,
            payload=isolated_payload,
            config=runtime_config,
            interrupt_callback=interrupt_callback,
        )
        isolated_allowed = {record_type: frozenset({slot})}
        isolated_required = frozenset({(record_type, slot)})
        isolated = parse_llm_records(
            _normalize_small_model_response(isolated_response, record_type),
            allowed_slots=isolated_allowed,
            required=isolated_required,
        )
        issues.extend(isolated.issues)
        isolated_records = {
            record.slot: record.text for record in isolated.records
        }
        records.update(isolated_records)
        if slot not in isolated_records:
            recovered = _recover_unframed_records(
                isolated_response,
                record_type,
                [slot],
                allow_single_positional=True,
            )
            records.update(recovered)
            recovered_count += len(recovered)
        retried_scenes.append(entity.scene_number)

    normalized_slots: list[int] = []
    for slot, text in tuple(records.items()):
        normalized_text, changed = _strip_redundant_record_envelope(
            text,
            record_type,
            slot,
        )
        if changed and normalized_text:
            records[slot] = normalized_text
            normalized_slots.append(slot)
    if normalized_slots:
        recovered_count += len(normalized_slots)
        _LOGGER.info(
            "[MV Director - Timeline Planner] normalized duplicated transport "
            "wrapper; task=%s; slots=%s",
            task,
            ",".join(str(slot) for slot in normalized_slots),
        )

    if record_type in {"ACTION", "CAMERA"}:
        cleaned_slots = []
        for slot, text in tuple(records.items()):
            cleaned = strip_generated_line_continuation(text)
            if cleaned != text:
                records[slot] = cleaned
                cleaned_slots.append(slot)
        if cleaned_slots:
            _LOGGER.info(
                "[MV Director - Timeline Planner] removed standalone trailing backslash; task=%s; slots=%s",
                task, ",".join(str(slot) for slot in cleaned_slots),
            )

    unresolved = tuple(
        (record_type, slot_entities[slot].scene_number, slot)
        for slot in slot_entities
        if slot not in records
    )
    values = {entity.key: records[slot] for slot, entity in slot_entities.items() if slot in records}
    return (
        values,
        issues,
        tuple(sorted(set(retried_scenes))),
        unresolved,
        recovered_count,
    )


def _request_entity_batches(
    backend: TimelinePlannerBackend,
    *,
    task: str,
    record_type: str,
    entities: list[_Entity],
    batch_size: int,
    shared: Mapping[str, object],
    system_prompt: str,
    runtime_config: LlamaRuntimeConfig,
    interrupt_callback: Any,
) -> tuple[
    dict[tuple[int, ...], str],
    list[LLMRecordIssue],
    tuple[int, ...],
    tuple[tuple[str, int, int], ...],
    int,
]:
    """Request a long entity list without duplicating the whole timeline.

    Each entity already carries its immediately preceding lyric and visual-beat
    context.  Keeping the batch boundary identical to the other Planner tasks
    therefore preserves the editorial context while bounding prompt growth.
    """

    values: dict[tuple[int, ...], str] = {}
    issues: list[LLMRecordIssue] = []
    retried_scenes: set[int] = set()
    missing: list[tuple[str, int, int]] = []
    recovered_count = 0
    for entity_batch in _chunks(entities, batch_size):
        (
            batch_values,
            batch_issues,
            batch_retries,
            batch_missing,
            batch_recovered,
        ) = _request_entities(
            backend,
            task=task,
            record_type=record_type,
            entities=entity_batch,
            shared=shared,
            system_prompt=system_prompt,
            runtime_config=runtime_config,
            interrupt_callback=interrupt_callback,
        )
        values.update(batch_values)
        issues.extend(batch_issues)
        retried_scenes.update(batch_retries)
        missing.extend(batch_missing)
        recovered_count += batch_recovered
    return (
        values,
        issues,
        tuple(sorted(retried_scenes)),
        tuple(missing),
        recovered_count,
    )


def _comparison_text(value: str) -> str:
    """Return a language-neutral surface form for repetition validation."""

    if "__MVD_LOCKED_DIALOGUE_" in value:
        return ""
    return re.sub(r"[^\w]+", "", value.casefold(), flags=re.UNICODE)


def _is_near_duplicate(left: str, right: str) -> bool:
    left_key = _comparison_text(left)
    right_key = _comparison_text(right)
    # Short protocol-test fragments and dialogue-only remnants do not contain
    # enough semantic surface to support a quality decision.
    if min(len(left_key), len(right_key)) < 16:
        return False
    if left_key == right_key:
        return True
    if min(len(left_key), len(right_key)) < 48:
        return False
    return (
        SequenceMatcher(None, left_key, right_key, autojunk=False).ratio()
        >= 0.92
    )


def _repeated_entities(
    entities: list[_Entity],
    values: Mapping[tuple[int, ...], str],
    history: list[str],
) -> tuple[list[_Entity], dict[tuple[int, ...], str]]:
    """Find later repeated records without modifying any accepted LLM text."""

    accepted = [text for text in history if text.strip()]
    repeated: list[_Entity] = []
    matched: dict[tuple[int, ...], str] = {}
    for entity in entities:
        text = values.get(entity.key, "").strip()
        if not text:
            continue
        prior = next(
            (
                candidate
                for candidate in reversed(accepted)
                if _is_near_duplicate(text, candidate)
            ),
            "",
        )
        if prior:
            repeated.append(entity)
            matched[entity.key] = prior
        else:
            accepted.append(text)
    return repeated, matched


def _request_distinct_entities(
    backend: TimelinePlannerBackend,
    *,
    task: str,
    record_type: str,
    entities: list[_Entity],
    shared: Mapping[str, object],
    history: list[str],
    system_prompt: str,
    runtime_config: LlamaRuntimeConfig,
    interrupt_callback: Any,
) -> tuple[
    dict[tuple[int, ...], str],
    list[LLMRecordIssue],
    tuple[int, ...],
    tuple[tuple[str, int, int], ...],
    int,
    int,
]:
    """Request records and retry only repeated TEXT while keeping output AS IS."""

    values, issues, retries, missing, recovered = _request_entities(
        backend,
        task=task,
        record_type=record_type,
        entities=entities,
        shared=shared,
        system_prompt=system_prompt,
        runtime_config=runtime_config,
        interrupt_callback=interrupt_callback,
    )
    if missing:
        return values, issues, retries, missing, recovered, 0
    merged = dict(values)
    retry_scenes_all: set[int] = set(retries)
    for diversity_attempt in range(1, 3):
        repeated, matched = _repeated_entities(entities, merged, history)
        if not repeated:
            return (
                merged,
                issues,
                tuple(sorted(retry_scenes_all)),
                (),
                recovered,
                0,
            )
        forbidden_outputs: list[str] = []
        for candidate in [
            *history,
            *(merged[entity.key] for entity in entities if entity.key in merged),
        ]:
            candidate = candidate.strip()
            if candidate and candidate not in forbidden_outputs:
                forbidden_outputs.append(candidate)
        retry_missing_all: list[tuple[str, int, int]] = []
        retry_scene_numbers = sorted(
            {entity.scene_number for entity in repeated}
        )
        for scene_number in retry_scene_numbers:
            retry_entities = [
                _Entity(
                    entity.scene_number,
                    entity.key,
                    {
                        **entity.value,
                        "rejected_output": merged[entity.key],
                        "must_differ_from": matched[entity.key],
                    },
                )
                for entity in repeated
                if entity.scene_number == scene_number
            ]
            (
                retry_values,
                retry_issues,
                retry_scenes,
                retry_missing,
                retry_recovered,
            ) = _request_entities(
                backend,
                task=task,
                record_type=record_type,
                entities=retry_entities,
                shared={
                    **dict(shared),
                    "retry": "repeated_slots_only",
                    "diversity_retry_attempt": diversity_attempt,
                    "diversity_retry": (
                        "Replace every rejected output with a genuinely different "
                        "creative choice. Do not merely change left/right, word "
                        "order, or synonyms."
                    ),
                    "forbidden_recent_outputs": forbidden_outputs[-12:],
                },
                system_prompt=system_prompt,
                runtime_config=runtime_config,
                interrupt_callback=interrupt_callback,
            )
            issues.extend(retry_issues)
            retry_scenes_all.update(retry_scenes)
            retry_scenes_all.add(scene_number)
            retry_missing_all.extend(retry_missing)
            recovered += retry_recovered
            merged.update(retry_values)
        if retry_missing_all:
            return (
                merged,
                issues,
                tuple(sorted(retry_scenes_all)),
                tuple(retry_missing_all),
                recovered,
                0,
            )

    repeated_after_retry, _ = _repeated_entities(entities, merged, history)
    return (
        merged,
        issues,
        tuple(sorted(retry_scenes_all)),
        (),
        recovered,
        len(repeated_after_retry),
    )


def _camera_motion_type(text: str) -> str:
    return next(
        (
            motion
            for motion in _CAMERA_MOTION_TYPES
            if re.match(rf"^{re.escape(motion)}(?:\s|$)", text)
        ),
        "",
    )


def _camera_motion_occurrences(text: str) -> tuple[str, ...]:
    return tuple(
        motion
        for motion in _CAMERA_MOTION_TYPES
        if re.search(
            rf"(?<![A-Za-z]){re.escape(motion)}(?![A-Za-z])",
            text,
        )
    )


def _camera_budget_violations(
    entities: list[_Entity],
    values: Mapping[tuple[int, ...], str],
    *,
    arc_maximum: int,
    recent_history: tuple[str, ...] | list[str] = (),
) -> dict[tuple[int, ...], tuple[str, ...]]:
    """Select Camera slots that need an LLM quality retry without rewriting TEXT."""

    motion_counts: dict[str, int] = {}
    seen_finite_plans = set(recent_history)
    arc_paths: dict[int, str] = {}
    slow_count = 0
    slow_maximum = max(1, len(entities) // 4)
    violations: dict[tuple[int, ...], list[str]] = {}
    for entity in entities:
        text = values.get(entity.key, "").strip()
        if not text:
            continue
        finite_protocol = entity.value.get("camera_protocol") == "finite_v1"
        plan: _CameraPlan | None = None
        if finite_protocol:
            plan, plan_violations = _parse_camera_plan(text)
            if plan_violations:
                violations.setdefault(entity.key, []).extend(plan_violations)
                continue
            assert plan is not None
            group = int(entity.value.get("camera_continuity_group", entity.scene_number))
            continuity_entity = _Entity(entity.scene_number, entity.key, {
                **entity.value,
                "previous_arc_path": arc_paths.get(group, entity.value.get("previous_arc_path", "")),
            })
            contract_violations = _camera_plan_contract_violations(continuity_entity, plan)
            if _camera_motion_type(plan.motion) == "Arc Shot" and not contract_violations:
                arc_paths[group] = _arc_base_path(plan.path)
            if contract_violations:
                violations.setdefault(entity.key, []).extend(contract_violations)
            rendered_plan = _render_camera_plan(plan)
            if rendered_plan in seen_finite_plans:
                violations.setdefault(entity.key, []).append(
                    "camera_plan_repetition"
                )
            else:
                seen_finite_plans.add(rendered_plan)
            camera_text = plan.motion
        else:
            camera_text = text
        motion = _camera_motion_type(camera_text)
        if not motion:
            violations.setdefault(entity.key, []).append(
                "required_h3_motion_type"
            )
        else:
            motion_counts[motion] = motion_counts.get(motion, 0) + 1
            maximum = (
                1
                if motion == "Tracking Shot"
                else arc_maximum
                if motion == "Arc Shot"
                else 2
            )
            if motion_counts[motion] > maximum:
                violations.setdefault(entity.key, []).append(
                    f"motion_budget:{motion}"
                )
        if len(_camera_motion_occurrences(camera_text)) != 1:
            violations.setdefault(entity.key, []).append(
                "exactly_one_h3_motion_type"
            )
        if (
            entity.value.get("face_arc_transition")
            and motion != "Arc Shot"
        ):
            violations.setdefault(entity.key, []).append(
                "required_face_arc_transition"
            )
        if entity.value.get("long_arc_emphasis"):
            if motion != "Arc Shot":
                violations.setdefault(entity.key, []).append(
                    "required_long_arc_emphasis"
                )
            elif not _LARGE_FAST_ARC_RE.search(camera_text):
                violations.setdefault(entity.key, []).append(
                    "required_long_arc_energy"
                )
        if entity.value.get("face_zoom_emphasis") and motion != "Zoom In":
            violations.setdefault(entity.key, []).append(
                "required_face_zoom_emphasis"
            )
        if entity.value.get("arc_permission") == "forbidden" and motion == "Arc Shot":
            violations.setdefault(entity.key, []).append("unassigned_arc")
        if _SLOW_CAMERA_RE.search(camera_text):
            slow_count += 1
            if slow_count > slow_maximum:
                violations.setdefault(entity.key, []).append("slow_speed_budget")
        if "at fast speed" in camera_text and re.search(
            r"ゆっくり|緩やか|at slow speed", camera_text, re.IGNORECASE
        ):
            violations.setdefault(entity.key, []).append(
                "conflicting_camera_speed"
            )
        source_text = canonical_json(
            {
                "lyrics": entity.value.get("lyrics", []),
                "author_body": entity.value.get("author_body", []),
            }
        )
        if (
            not finite_protocol
            and _LOWER_BODY_DETAIL_RE.search(text)
            and not _LOWER_BODY_DETAIL_RE.search(source_text)
        ):
            violations.setdefault(entity.key, []).append(
                "unrequested_lower_body_detail"
            )
    return {
        key: tuple(dict.fromkeys(value))
        for key, value in violations.items()
        if value
    }


def _anime_story_mv_long_arc_keys(entities: list[_Entity]) -> set[tuple[int, ...]]:
    """Choose a sparse, deterministic set of long Arc slots for anime_story_mv."""

    if not entities:
        return set()
    target = max(1, (len(entities) + 2) // 3)
    selected_indices = {
        index
        for index, entity in enumerate(entities)
        if entity.value.get("face_arc_transition")
    }
    role_priority = {
        "spatial_reveal_or_interaction_coverage": 0,
        "continuity_bridge": 1,
        "new_scene_establishing_edit": 2,
        "upper_body_performance_coverage": 3,
        "expressive_result_coverage": 4,
    }
    candidates = sorted(
        range(len(entities)),
        key=lambda index: (
            -int(entities[index].value.get("shot_duration_ms", 0)),
            role_priority.get(str(entities[index].value.get("editorial_role")), 9),
            index,
        ),
    )
    for index in candidates:
        if len(selected_indices) >= target:
            break
        if index in selected_indices:
            continue
        if any(abs(index - selected) == 1 for selected in selected_indices):
            continue
        selected_indices.add(index)
    if len(selected_indices) < target:
        for index in candidates:
            if len(selected_indices) >= target:
                break
            if index not in selected_indices:
                selected_indices.add(index)
    return {entities[index].key for index in selected_indices}


def _anime_story_mv_face_zoom_key(
    entities: list[_Entity],
    long_arc_keys: set[tuple[int, ...]],
) -> tuple[int, ...] | None:
    """Select one non-Arc performance slot for a readable face Zoom In."""

    role_priority = {
        "expressive_result_coverage": 0,
        "upper_body_performance_coverage": 1,
        "continuity_bridge": 2,
        "new_scene_establishing_edit": 3,
    }
    candidates = [
        entity
        for entity in entities
        if entity.key not in long_arc_keys
        and str(entity.value.get("editorial_role")) in role_priority
    ]
    if not candidates:
        return None
    selected = min(
        candidates,
        key=lambda entity: (
            role_priority[str(entity.value.get("editorial_role"))],
            -int(entity.value.get("shot_duration_ms", 0)),
            entity.key,
        ),
    )
    return selected.key


def _select_arc_roll(
    entities: list[_Entity],
    long_arc_keys: set[tuple[int, ...]],
    face_transitions: Mapping[tuple[int, ...], str],
) -> tuple[int, ...] | None:
    """Select one established Arc per batch for a brief, level-returning roll."""

    candidates: list[tuple[int, int, int, tuple[int, ...]]] = []
    coverage_priority = {
        "whole_body_emotion": 0,
        "upper_body_hands": 1,
        "environment_relation": 2,
        "expressive_result": 3,
        "lyric_target": 4,
        "lyric_target_and_hands": 5,
        "lyric_target_and_body": 1,
    }
    for entity in entities:
        value = entity.value
        transition = face_transitions.get(entity.key) or value.get(
            "face_arc_transition"
        )
        face_out = transition == "arc_out_of_previous_face_cut"
        required_coverage = str(value.get("required_spine_coverage") or "")
        if (
            (entity.key not in long_arc_keys and not face_out)
            or int(value.get("shot_duration_ms", 0)) < 3500
            or (transition and not face_out)
            or required_coverage == "face_eyes_mouth"
            or (face_out and required_coverage in {
                "lyric_target", "lyric_target_and_hands", "lyric_target_and_body"
            })
        ):
            continue
        previous_state = value.get("previous_camera_state") or {}
        if (
            not face_out
            and previous_state.get("end_scale") in {
                "face_closeup", "head_and_shoulders"
            }
        ):
            continue
        candidates.append((
            0 if face_out else 1,
            coverage_priority.get(required_coverage, 2),
            -int(value.get("shot_duration_ms", 0)),
            entity.key,
        ))
    return min(candidates)[-1] if candidates else None


def _anime_emotional_mv_camera_emphasis(
    entities: list[_Entity],
    *,
    face_target: int | None = None,
) -> tuple[
    set[tuple[int, ...]],
    set[tuple[int, ...]],
    dict[tuple[int, ...], str],
]:
    """Select long Arcs and a sparse face phrase without Camera prose."""

    if not entities:
        return set(), set(), {}
    role_priority = {
        "expressive_result_coverage": 0,
        "upper_body_performance_coverage": 1,
        "continuity_bridge": 2,
        "spatial_reveal_or_interaction_coverage": 3,
        "new_scene_establishing_edit": 4,
    }
    if face_target is None:
        face_target = max(1, (len(entities) + 11) // 12)
    face_eligible = {
        index for index, entity in enumerate(entities)
        if entity.value.get("required_spine_coverage")
        not in {"lyric_target", "lyric_target_and_hands", "lyric_target_and_body"}
        and not entity.value.get("single_prechorus_body_accent")
        and not entity.value.get("body_phrase_accent")
    }
    face_target = max(0, min(face_target, len(face_eligible)))
    face_indices: list[int] = []
    face_scenes: set[int] = set()
    ordered_face_candidates = sorted(
        face_eligible,
        key=lambda value: (
            0 if (
                (
                    entities[value].value.get("grounded_cue_phase") == "release"
                    or (
                        entities[value].value.get("grounded_cue_phase")
                        == "reaction_and_release"
                        and (
                            entities[value].value.get("visual_beat_grounding") or {}
                        ).get("contact") != "許可"
                    )
                )
                and entities[value].value.get("performance_phase")
                == "release_and_reaction"
            ) else 1,
            role_priority.get(
                str(entities[value].value.get("editorial_role")), 9
            ),
            value,
        ),
    )
    for index in ordered_face_candidates if face_target else ():
        scene_number = entities[index].scene_number
        if scene_number in face_scenes:
            continue
        if any(abs(index - selected) < 3 for selected in face_indices):
            continue
        face_indices.append(index)
        face_scenes.add(scene_number)
        if len(face_indices) >= face_target:
            break
    if 0 < len(face_indices) < face_target:
        for index in sorted(face_eligible):
            if index not in face_indices:
                face_indices.append(index)
                if len(face_indices) >= face_target:
                    break

    arc_indices: set[int] = set()
    transitions: dict[tuple[int, ...], str] = {}
    for face_index in sorted(face_indices):
        neighbours = (
            (face_index - 1, "arc_into_next_face_cut"),
            (face_index + 1, "arc_out_of_previous_face_cut"),
        )
        for candidate, relation in neighbours:
            if not 0 <= candidate < len(entities):
                continue
            if entities[candidate].scene_number != entities[face_index].scene_number:
                continue
            if int(entities[candidate].value.get("shot_duration_ms", 0)) < 2500:
                continue
            if candidate in face_indices or candidate in arc_indices:
                continue
            if entities[candidate].value.get("required_spine_coverage") in {
                "lyric_target", "lyric_target_and_hands", "lyric_target_and_body"
            }:
                continue
            arc_indices.add(candidate)
            transitions[entities[candidate].key] = relation
            break

    # Dense Arc coverage remains a defining trait of this profile, but it must
    # leave enough non-Arc coverage for a readable rhythm. Only Shots long
    # enough to carry a 70-90% path are eligible for an optional long Arc.
    eligible_arc_indices = {
        index
        for index, entity in enumerate(entities)
        if index not in face_indices
        and int(entity.value.get("shot_duration_ms", 0)) >= 2500
    }
    arc_target = max(
        len(arc_indices),
        (len(eligible_arc_indices) + 1) // 2,
    )
    arc_target = min(arc_target, len(eligible_arc_indices))
    candidates = sorted(
        (
            index for index in eligible_arc_indices if index not in arc_indices
        ),
        key=lambda index: (
            -int(entities[index].value.get("shot_duration_ms", 0)),
            role_priority.get(
                str(entities[index].value.get("editorial_role")), 9
            ),
            index,
        ),
    )
    for index in candidates:
        if len(arc_indices) >= arc_target:
            break
        if any(abs(index - selected) == 1 for selected in arc_indices):
            continue
        arc_indices.add(index)

    # Fill the target only after the spaced pass. This keeps the target stable
    # for short batches without making adjacent Arcs the default cadence.
    if len(arc_indices) < arc_target:
        for index in candidates:
            if len(arc_indices) >= arc_target:
                break
            arc_indices.add(index)

    return (
        {entities[index].key for index in arc_indices},
        {entities[index].key for index in face_indices},
        transitions,
    )


def _grounded_cue_targets(entity: _Entity) -> tuple[str, ...]:
    """Return exact current-Scene tokens that Action must preserve."""

    if not entity.value.get("grounded_cue_required"):
        return ()
    targets: list[str] = []
    grounding = entity.value.get("visual_beat_grounding")
    if isinstance(grounding, Mapping) and grounding.get("valid"):
        target = str(grounding.get("target", "")).strip()
        if target not in _CUE_NONE_VALUES:
            targets.append(target)
    priority_cues = entity.value.get("priority_lyric_cues", [])
    if isinstance(priority_cues, list):
        for cue in priority_cues:
            if not isinstance(cue, Mapping):
                continue
            token = str(cue.get("token", "")).strip()
            if token and token not in targets:
                targets.append(token)
    return tuple(targets)


def _action_budget_violations(
    entities: list[_Entity],
    values: Mapping[tuple[int, ...], str],
    *,
    configured_priority_cues: tuple[tuple[str, str], ...] = (),
) -> dict[tuple[int, ...], tuple[str, ...]]:
    """Select Action slots for one semantic retry without rewriting their TEXT."""

    slow_count = 0
    slow_maximum = max(1, len(entities) // 4)
    violations: dict[tuple[int, ...], list[str]] = {}
    for entity in entities:
        text = values.get(entity.key, "").strip()
        if not text:
            continue
        if (
            _INTERNAL_ACTION_LABEL_RE.search(text)
            or _ACTION_PROTOCOL_PREFIX_RE.search(text)
        ):
            violations.setdefault(entity.key, []).append(
                "internal_protocol_label"
            )
        required_anchor = str(
            entity.value.get("required_spatial_anchor", "")
        ).strip()
        if required_anchor and required_anchor not in text:
            violations.setdefault(entity.key, []).append(
                "missing_spatial_anchor"
            )
        required_development = str(
            entity.value.get("required_visible_development", "")
        ).strip()
        if required_development and required_development not in text:
            violations.setdefault(entity.key, []).append(
                "missing_visible_development"
            )
        if _SLOW_ACTION_RE.search(text):
            slow_count += 1
            if slow_count > slow_maximum:
                violations.setdefault(entity.key, []).append("slow_action_budget")
        if _GENERIC_HAND_ACTION_RE.search(text):
            violations.setdefault(entity.key, []).append("generic_hand_raise_or_lower")

        escaped_cues = _unexpected_priority_cues(
            text,
            entity.value.get("priority_lyric_cues", []),
            configured_priority_cues,
        )
        if escaped_cues:
            violations.setdefault(entity.key, []).append(
                "unexpected_priority_cue"
            )

        if (
            entity.value.get("performance_role") == "face_and_upper_body_accent"
            and not _FACE_PERFORMANCE_RE.search(text)
        ):
            violations.setdefault(entity.key, []).append(
                "face_performance_missing"
            )
        source_text = canonical_json(
            {
                "lyrics": entity.value.get("lyrics", []),
                "author_body": entity.value.get("author_body", []),
            }
        )
        if (
            _LOWER_BODY_DETAIL_RE.search(text)
            and not _LOWER_BODY_DETAIL_RE.search(source_text)
            # Body-side words also occur in legitimate dance support/steps.
            # The existing semantic audit judges detail versus whole-body
            # performance in this opt-in mode; do not infer it from words.
            and entity.value.get("performance_mode") != "dance_phrase"
        ):
            violations.setdefault(entity.key, []).append(
                "unrequested_lower_body_primary_action"
            )
        if (
            _RUNNING_ACTION_RE.search(text)
            and not _RUNNING_ACTION_RE.search(source_text)
        ):
            violations.setdefault(entity.key, []).append(
                "unrequested_running"
            )
    grounded_scenes: dict[int, tuple[list[str], list[_Entity]]] = {}
    for entity in entities:
        targets = _grounded_cue_targets(entity)
        if not targets:
            continue
        if entity.scene_number not in grounded_scenes:
            grounded_scenes[entity.scene_number] = ([], [])
        for target in targets:
            if target not in grounded_scenes[entity.scene_number][0]:
                grounded_scenes[entity.scene_number][0].append(target)
        grounded_scenes[entity.scene_number][1].append(entity)
    preferred_roles = {
        "environment_interaction_or_body_turn": 0,
        "expressive_hand_arm_performance": 1,
        "new_scene_physical_hook": 2,
        "lyric_driven_full_body_performance": 3,
    }
    for targets, scene_entities in grounded_scenes.values():
        ranked_entities = sorted(
            scene_entities,
            key=lambda entity: (
                preferred_roles.get(
                    str(entity.value.get("performance_role", "")), 9
                ),
                entity.key,
            ),
        )
        for target_index, target in enumerate(targets):
            if any(
                target in values.get(entity.key, "")
                for entity in scene_entities
            ):
                continue
            selected = ranked_entities[target_index % len(ranked_entities)]
            violations.setdefault(selected.key, []).append(
                "missing_grounded_cue_target"
            )
    return {
        key: tuple(dict.fromkeys(value))
        for key, value in violations.items()
    }


def _action_audit_failures(
    entities: list[_Entity],
    verdicts: Mapping[tuple[int, ...], str],
) -> dict[tuple[int, ...], tuple[str, ...]]:
    """Parse finite audit verdicts without changing candidate Action text."""

    failures: dict[tuple[int, ...], tuple[str, ...]] = {}
    for entity in entities:
        verdict = verdicts.get(entity.key, "").strip()
        if verdict == "PASS":
            continue
        match = re.fullmatch(
            r"REJECT:([A-Z_]+(?:,[A-Z_]+)*)",
            verdict,
        )
        if match:
            reasons = tuple(dict.fromkeys(match.group(1).split(",")))
            if reasons and all(reason in _ACTION_AUDIT_REASONS for reason in reasons):
                if entity.value.get("performance_role") != "body_phrase_accent":
                    reasons = tuple(
                        reason for reason in reasons
                        if reason != "BODY_ACCENT_MISSING"
                    )
                if not reasons:
                    continue
                failures[entity.key] = reasons
                continue
        failures[entity.key] = ("INVALID_AUDIT_VERDICT",)
    return failures


def _request_action_audit(
    backend: TimelinePlannerBackend,
    *,
    entities: list[_Entity],
    values: Mapping[tuple[int, ...], str],
    shared: Mapping[str, object],
    system_prompt: str,
    runtime_config: LlamaRuntimeConfig,
    interrupt_callback: Any,
) -> tuple[
    dict[tuple[int, ...], tuple[str, ...]],
    list[LLMRecordIssue],
    tuple[int, ...],
    tuple[tuple[str, int, int], ...],
    int,
]:
    """Ask the same LLM to judge bounded Action contracts, never to rewrite."""

    audit_entities = [
        _Entity(
            entity.scene_number,
            entity.key,
            {
                **entity.value,
                "candidate_action": values.get(entity.key, ""),
            },
        )
        for entity in entities
    ]
    audit_config = replace(
        runtime_config,
        max_tokens=min(
            runtime_config.max_tokens,
            max(256, min(1024, len(audit_entities) * 24)),
        ),
    )
    verdicts, issues, retries, missing, recovered = _request_entities(
        backend,
        task="action-audit",
        record_type="AUDIT",
        entities=audit_entities,
        shared=shared,
        system_prompt=system_prompt,
        runtime_config=audit_config,
        interrupt_callback=interrupt_callback,
    )
    if missing:
        return {}, issues, retries, missing, recovered
    return (
        _action_audit_failures(audit_entities, verdicts),
        issues,
        retries,
        (),
        recovered,
    )


def _shot_context(
    template: PlannerTemplate,
    protector: DialogueProtector,
) -> dict[tuple[int, int], dict[str, object]]:
    shots: dict[tuple[int, int], dict[str, object]] = {}
    seen_sections: set[str] = set()
    for scene in template.scenes:
        for shot_index, shot in enumerate(scene.shots, 1):
            shot_sections = {
                lyric.section
                for lyric in shot.lyric_annotations
                if lyric.section
            }
            section_entry = bool(shot_sections - seen_sections)
            seen_sections.update(shot_sections)
            shot_end_ms = (
                scene.shots[shot_index].start_ms
                if shot_index < len(scene.shots)
                else scene.end_ms
            )
            lyrics = [
                {
                    "section": lyric.section or "",
                    "text": protector.protect(
                        lyric.text,
                        source_ref=f"scene:{scene.scene_number}:shot:{shot_index}:lyric",
                    ),
                    "start_ms": lyric.start_ms,
                    "end_ms": lyric.end_ms,
                }
                for lyric in shot.lyric_annotations
            ]
            author_body = [
                protector.protect(
                    text,
                    source_ref=f"scene:{scene.scene_number}:shot:{shot_index}:body",
                )
                for text in shot.body
                if text != "未計画"
            ]
            shots[(scene.scene_number, shot_index)] = {
                "scene_number": scene.scene_number,
                "shot_index": shot_index,
                "scene_continuation": scene.continuation,
                "section_entry": section_entry,
                "scene_shot_count": len(scene.shots),
                "shot_start_ms": shot.start_ms,
                "shot_end_ms": shot_end_ms,
                "shot_duration_ms": shot_end_ms - shot.start_ms,
                "lyrics": lyrics,
                "author_body": author_body,
            }
    return shots


def _performance_role(
    context: Mapping[str, object],
    *,
    lip_sync_active: bool,
) -> str:
    """Assign a structural performance purpose without writing action prose."""

    shot_index = int(context["shot_index"])
    shot_count = int(context["scene_shot_count"])
    continuation = bool(context["scene_continuation"])
    if (
        lip_sync_active
        and not continuation
        and bool(context.get("section_entry"))
    ):
        return "face_and_upper_body_accent"
    if shot_count == 1:
        return "lyric_driven_full_body_performance"
    if shot_index == 1:
        if continuation:
            return "continuity_transformation"
        return "new_scene_physical_hook"
    if shot_index == 2:
        return "expressive_hand_arm_performance"
    if shot_index == 3:
        return "environment_interaction_or_body_turn"
    return "expressive_resolution"


def _sparse_body_accent_keys(
    shot_context: Mapping[tuple[int, int], Mapping[str, object]],
    scene_spine_steps: Mapping[tuple[int, int], SceneSpineStep],
    *,
    lip_sync_active: bool,
    cue_cards: Mapping[tuple[int, ...], _CueCard] | None = None,
    include_prechorus_single: bool = False,
    include_verse_contact: bool = False,
    include_all_scenes: bool = False,
) -> set[tuple[int, int]]:
    """Reserve one eligible accent per selected Scene, never rewrite Action."""

    by_scene: dict[int, list[tuple[int, int]]] = {}
    for key in sorted(shot_context):
        by_scene.setdefault(key[0], []).append(key)
    selected: set[tuple[int, int]] = set()
    for keys in by_scene.values():
        sections = {
            str(lyric.get("section", "")).upper()
            for key in keys
            for lyric in shot_context[key].get("lyrics", [])
            if isinstance(lyric, Mapping)
        }
        effect_card = (cue_cards or {}).get((keys[0][0],))
        prechorus_single = (
            include_prechorus_single
            and _is_prechorus_scene(keys, shot_context)
            and len(keys) == 1
            and int(shot_context[keys[0]].get("shot_duration_ms", 0)) >= 6000
            and not (
                effect_card and effect_card.valid
                and effect_card.contact == "許可"
                and keys[0] not in scene_spine_steps
            )
        )
        verse_contact = (
            include_verse_contact
            and len(keys) > 1
            and _verse_contact_cue(sections, effect_card)
            and all(key in scene_spine_steps for key in keys)
        )
        if not sections.intersection({"CHORUS", "FINAL_CHORUS"}) and not prechorus_single and not verse_contact and not include_all_scenes:
            continue
        if include_all_scenes and not (effect_card and effect_card.valid):
            # The opt-in policy needs an accepted Scene cue before reserving
            # a body phrase; otherwise keep the existing Action role.
            continue
        contact_scene = bool(
            effect_card and effect_card.valid and effect_card.contact == "許可"
        )
        body_only_scene = bool(
            include_all_scenes and effect_card and effect_card.valid
            and effect_card.target in _CUE_NONE_VALUES
        )
        if body_only_scene and not all(key in scene_spine_steps for key in keys):
            # Without an accepted Scene progression the body-only policy has
            # no authored phrase to expose; retain the legacy Action roles.
            continue
        if include_all_scenes and contact_scene and (
            len(keys) == 1 or not all(key in scene_spine_steps for key in keys)
        ):
            # A contact needs its own visible event; do not invent a second
            # body event if the LLM did not supply a complete Scene progression.
            continue
        external_effect = bool(
            effect_card and effect_card.valid
            and effect_card.phenomenon in {"外部自律", "身体操作"}
        )
        # The phenomenon's one event, not its setup or repeated response, is
        # the first eligible place for the sparse physical accent.
        effect_events = [
            key for key in keys
            if external_effect
            and (spine := scene_spine_steps.get(key)) is not None
            and spine.phase == "event"
            and spine.show in {"lyric_target_body", "lyric_target"}
        ]
        body_events = [
            key for key in keys
            if body_only_scene
            and not contact_scene
            and not external_effect
            and (spine := scene_spine_steps.get(key)) is not None
            and spine.phase == "event"
            and spine.show == "whole_body"
        ]
        priority_events = effect_events + body_events
        candidates = priority_events + [
            key for key in keys if key not in priority_events
        ]
        for key in candidates:
            if _performance_role(
                shot_context[key], lip_sync_active=lip_sync_active
            ) == "face_and_upper_body_accent":
                continue
            spine = scene_spine_steps.get(key)
            if (verse_contact or include_all_scenes and contact_scene) and (
                spine is None or spine.phase == "event"
            ):
                continue
            if spine is not None and spine.show not in {
                "whole_body", "upper_body_hands", "lyric_target_body"
            }:
                if not (
                    prechorus_single and spine.show == "lyric_target_hands"
                    or (external_effect or prechorus_single)
                    and spine.show == "lyric_target"
                    or verse_contact and spine.show == "lyric_target"
                ):
                    continue
            selected.add(key)
            break
    return selected


def _verse_contact_cue(sections: set[str], card: _CueCard | None) -> bool:
    """Identify a lyric-grounded Verse contact without naming any object."""

    return bool(
        sections and all(section.startswith("VERSE") for section in sections)
        and card is not None and card.valid and card.contact == "許可"
        and card.target not in _CUE_NONE_VALUES
    )


def _layout_min_duration_ms(
    scene: Scene, *, performance_mode: str, body_accent_policy: str,
    cue_card: _CueCard | None,
) -> int:
    if performance_mode != "dance_phrase":
        return 1500
    sections = {
        annotation.section.upper()
        for shot in scene.shots
        for annotation in shot.lyric_annotations
        if annotation.section
    }
    if (
        body_accent_policy in {
            "sparse_chorus_prechorus_verse_contact", "scene_phrase"
        }
        and _verse_contact_cue(sections, cue_card)
    ):
        return 3000
    return 4000


def _is_prechorus_scene(
    keys: Sequence[tuple[int, int]],
    shot_context: Mapping[tuple[int, int], Mapping[str, object]],
) -> bool:
    return {
        str(lyric.get("section", "")).upper()
        for key in keys
        for lyric in shot_context[key].get("lyrics", [])
        if isinstance(lyric, Mapping)
    } == {"PRE-CHORUS"}


def _camera_editorial_role(
    context: Mapping[str, object],
    *,
    lip_sync_active: bool,
) -> str:
    """Assign edit coverage while leaving the final camera sentence to the LLM."""

    shot_index = int(context["shot_index"])
    continuation = bool(context["scene_continuation"])
    if (
        lip_sync_active
        and not continuation
        and bool(context.get("section_entry"))
    ):
        return "face_performance_cut"
    if shot_index == 1:
        if continuation:
            return "continuity_bridge"
        return "new_scene_establishing_edit"
    if shot_index == 2:
        return "upper_body_performance_coverage"
    if shot_index == 3:
        return "spatial_reveal_or_interaction_coverage"
    return "expressive_result_coverage"


def _face_arc_transitions(
    shot_keys: list[tuple[int, int]],
    face_cut_keys: set[tuple[int, int]],
    shot_durations: Mapping[tuple[int, int], int] | None = None,
) -> dict[tuple[int, int], str]:
    """Pair each structural face insert with one same-Scene Arc coverage Shot."""

    transitions: dict[tuple[int, int], str] = {}
    for index, face_key in enumerate(shot_keys):
        if face_key not in face_cut_keys:
            continue
        candidates: list[tuple[tuple[int, int], str]] = []
        if index + 1 < len(shot_keys):
            next_key = shot_keys[index + 1]
            if next_key[0] == face_key[0] and next_key not in face_cut_keys:
                candidates.append((next_key, "arc_out_of_previous_face_cut"))
        if index > 0:
            previous_key = shot_keys[index - 1]
            if previous_key[0] == face_key[0] and previous_key not in face_cut_keys:
                candidates.append((previous_key, "arc_into_next_face_cut"))
        if face_key[1] > 1:
            candidates.reverse()
        for candidate, relation in candidates:
            if (
                shot_durations is not None
                and int(shot_durations.get(candidate, 0)) < 2500
            ):
                continue
            if candidate not in transitions:
                transitions[candidate] = relation
                break
    return transitions


def _protected_context(
    template: PlannerTemplate,
    concept_emd: str,
    scene_emd: str,
    direction: DirectionArtifact,
) -> tuple[
    DialogueProtector,
    str,
    dict[str, object],
    dict[tuple[int, int], dict[str, object]],
    dict[str, list[str]],
]:
    protector = DialogueProtector()
    protected_concept = protector.protect(concept_emd, source_ref="concept_emd")
    scene_setting = (
        parse_scene_emd_fragment(scene_emd) if scene_emd.strip() else None
    )
    scene_context: dict[str, object] = {}
    if scene_setting is not None:
        scene_context = {
            "environment": [
                protector.protect(value, source_ref="scene_emd:environment")
                for value in scene_setting.environment
            ],
            "time_lighting": [
                protector.protect(value, source_ref="scene_emd:time_lighting")
                for value in scene_setting.time_lighting
            ],
            "background_picture": scene_setting.picture_ref or "",
            "authority": (
                "Observed baseline only. Explicit Direction and user instructions "
                "override time, lighting, weather, season, and staging. The Picture "
                "is environment evidence, never a performer or composition template."
            ),
        }
    shots = _shot_context(template, protector)
    directions = {
        "style": [protector.protect(value, source_ref="direction:style") for value in direction.style_direction],
        "environment": [
            protector.protect(value, source_ref="direction:environment")
            for value in direction.environment_direction
        ],
        "time_lighting": [
            protector.protect(value, source_ref="direction:time_lighting")
            for value in direction.time_lighting_direction
        ],
        "motion": [protector.protect(value, source_ref="direction:motion") for value in direction.motion_direction],
        "camera": [protector.protect(value, source_ref="direction:camera") for value in direction.camera_direction],
        "other": [protector.protect(value, source_ref="direction:other") for value in direction.other_direction],
    }
    return protector, protected_concept, scene_context, shots, directions


def _decode_layout_texts(
    template: PlannerTemplate,
    candidate_map: Mapping[int, tuple[Any, ...]],
    layout_texts: Mapping[tuple[int, ...], str],
) -> tuple[
    dict[int, tuple[int, ...]],
    dict[int, bool],
    list[int],
    list[int],
]:
    layouts: dict[int, tuple[int, ...]] = {}
    continuations: dict[int, bool] = {}
    repaired: list[int] = []
    fallback: list[int] = []
    for scene in template.scenes:
        try:
            continuation, starts = parse_scene_layout_selection(
                layout_texts[(scene.scene_number,)],
                candidate_map[scene.scene_number],
                scene_end_ms=scene.end_ms,
                first_scene=scene.scene_number == 1,
            )
        except TimelinePlannerError:
            try:
                continuation, starts = repair_scene_layout_selection(
                    layout_texts[(scene.scene_number,)],
                    candidate_map[scene.scene_number],
                    scene_end_ms=scene.end_ms,
                    first_scene=scene.scene_number == 1,
                )
                repaired.append(scene.scene_number)
            except TimelinePlannerError:
                continuation = False
                starts = (scene.start_ms,)
                fallback.append(scene.scene_number)
        continuations[scene.scene_number] = continuation
        layouts[scene.scene_number] = starts
    return layouts, continuations, repaired, fallback


def _satisfies_boundary_contract(
    template: PlannerTemplate,
    continuations: Mapping[int, bool],
    *,
    planner_policy: str = "",
) -> bool:
    """Validate the structural boundary contract sent on the mix retry."""

    if not template.scenes:
        return False
    first_scene = template.scenes[0]
    if continuations.get(first_scene.scene_number, True):
        return False
    later = [
        continuations[scene.scene_number]
        for scene in template.scenes[1:]
    ]
    if not later:
        return True
    if planner_policy == "anime_emotional_mv":
        minimum_continuations = (len(later) * 3 + 3) // 4
        return later.count(True) >= minimum_continuations
    minimum_cuts = max(1, len(later) // 4)
    minimum_continuations = max(1, (len(later) + 1) // 2)
    later_cut_capacity = len(later) - minimum_continuations
    section_cut_scenes = set(
        [
            number
            for number in _section_entry_scene_numbers(template)
            if number != first_scene.scene_number
        ][:later_cut_capacity]
    )
    if any(continuations.get(scene_number, True) for scene_number in section_cut_scenes):
        return False
    if later.count(False) < minimum_cuts:
        return False
    if later.count(True) < minimum_continuations:
        return False
    maximum_transitions = max(2, (len(later) * 2 + 2) // 3)
    transition_count = sum(
        current != previous for previous, current in zip(later, later[1:])
    )
    if transition_count > maximum_transitions:
        return False
    run_length = 1
    for previous, current in zip(later, later[1:]):
        run_length = run_length + 1 if current == previous else 1
        if run_length > 3:
            return False
    return True


def _repair_boundary_contract(
    template: PlannerTemplate,
    continuations: Mapping[int, bool],
    *,
    planner_policy: str = "",
) -> tuple[dict[int, bool], tuple[int, ...]]:
    """Minimally repair only the structural CUT/CONTINUE sequence."""

    scene_numbers = [scene.scene_number for scene in template.scenes]
    if not scene_numbers:
        return {}, ()
    original = [bool(continuations.get(number, False)) for number in scene_numbers]
    later_original = original[1:]
    later_count = len(later_original)
    if later_count == 0:
        repaired = {scene_numbers[0]: False}
        changed = () if not original[0] else (scene_numbers[0],)
        return repaired, changed

    if planner_policy == "anime_emotional_mv":
        repaired_values = [False, *later_original]
        minimum_continuations = (later_count * 3 + 3) // 4
        needed = minimum_continuations - later_original.count(True)
        section_entries = set(_section_entry_scene_numbers(template))
        candidates = [
            index
            for index, value in enumerate(later_original, 1)
            if not value and scene_numbers[index] not in section_entries
        ]
        candidates.extend(
            index
            for index, value in enumerate(later_original, 1)
            if not value
            and scene_numbers[index] in section_entries
            and index not in candidates
        )
        for index in candidates[:max(0, needed)]:
            repaired_values[index] = True
        repaired = dict(zip(scene_numbers, repaired_values))
        changed = tuple(
            number
            for number, before, after in zip(
                scene_numbers, original, repaired_values
            )
            if before != after
        )
        return repaired, changed

    minimum_cuts = max(1, later_count // 4)
    minimum_continuations = max(1, (later_count + 1) // 2)
    maximum_transitions = max(2, (later_count * 2 + 2) // 3)
    later_cut_capacity = later_count - minimum_continuations
    section_cut_scenes = set(
        [
            number
            for number in _section_entry_scene_numbers(template)
            if number != scene_numbers[0]
        ][:later_cut_capacity]
    )
    # state -> (edit cost, transition count, sequence)
    states: dict[
        tuple[int, int, bool, int],
        tuple[int, int, tuple[bool, ...]],
    ] = {}
    for position, expected in enumerate(later_original):
        next_states: dict[
            tuple[int, int, bool, int],
            tuple[int, int, tuple[bool, ...]],
        ] = {}
        if position == 0:
            prior_items = [(None, (0, 0, ()))]
        else:
            prior_items = list(states.items())
        for state, (cost, transitions, sequence) in prior_items:
            scene_number = scene_numbers[position + 1]
            choices = (
                (False,)
                if scene_number in section_cut_scenes
                else (expected, not expected)
            )
            for choice in choices:
                if state is None:
                    cuts = int(not choice)
                    continues = int(choice)
                    run_length = 1
                else:
                    cuts, continues, previous, previous_run = state
                    run_length = previous_run + 1 if choice == previous else 1
                    if run_length > 3:
                        continue
                    cuts += int(not choice)
                    continues += int(choice)
                next_state = (cuts, continues, choice, run_length)
                candidate = (
                    cost + int(choice != expected),
                    transitions
                    + int(bool(sequence) and sequence[-1] != choice),
                    (*sequence, choice),
                )
                current = next_states.get(next_state)
                if current is None or (
                    candidate[0], candidate[1], candidate[2]
                ) < (current[0], current[1], current[2]):
                    next_states[next_state] = candidate
        states = next_states

    valid = [
        value
        for (cuts, continues, _last, _run), value in states.items()
        if cuts >= minimum_cuts
        and continues >= minimum_continuations
        and value[1] <= maximum_transitions
    ]
    if not valid:
        raise TimelinePlannerError("boundary contract cannot be repaired")
    _cost, _transitions, later_repaired = min(
        valid,
        key=lambda value: (value[0], value[1], value[2]),
    )
    repaired_values = (False, *later_repaired)
    repaired = dict(zip(scene_numbers, repaired_values))
    changed = tuple(
        number
        for number, before, after in zip(scene_numbers, original, repaired_values)
        if before != after
    )
    return repaired, changed


def _section_entry_scene_numbers(template: PlannerTemplate) -> tuple[int, ...]:
    """Return Scenes containing the first annotation of each lyric section."""

    seen_sections: set[str] = set()
    entries: list[int] = []
    for scene in template.scenes:
        scene_sections = {
            lyric.section
            for shot in scene.shots
            for lyric in shot.lyric_annotations
            if lyric.section
        }
        if scene_sections - seen_sections:
            entries.append(scene.scene_number)
        seen_sections.update(scene_sections)
    return tuple(entries)


def generate_planner_content(
    backend: TimelinePlannerBackend,
    *,
    template: PlannerTemplate,
    concept_emd: str,
    direction: DirectionArtifact,
    lip_sync_mode: str,
    lip_sync_target: str,
    scenes_per_batch: int,
    system_prompts: Mapping[str, str],
    runtime_config: LlamaRuntimeConfig,
    scene_emd: str = "",
    staging_candidate_policy: str = "optional",
    interrupt_callback: Any = None,
) -> tuple[PlannerContent | None, tuple[tuple[str, int, int], ...]]:
    from .candidate_policy import validate_staging_candidate_policy
    validate_staging_candidate_policy(staging_candidate_policy)
    if not 1 <= scenes_per_batch <= 6:
        raise TimelinePlannerError("scenes_per_batch must be in 1..6")
    if lip_sync_mode not in {"off", "context_loop", "audio_reference", "lyrics"}:
        raise TimelinePlannerError("unknown lip_sync_mode")
    prompt_keys = set(system_prompts)
    if (
        not set(TASKS).issubset(prompt_keys)
        or prompt_keys - set(TASKS) - {
            "visual-beats-bounded", "actions-bounded", "actions-dance-phrase",
            "lyric-cues", "scene-spine", "scene-spine-body",
            "choreography-choice", "scene-author-event",
            "scene-author-performance", "scene-author-camera",
            "scene-author-composition-choice"
        }
        or any(not value.strip() for value in system_prompts.values())
    ):
        raise TimelinePlannerError("all six Planner system prompts are required")
    direction.validate()
    runtime_config.validate()
    if MOTION_PERFORMANCE_MODES.get(
        direction.motion_policy_profile_id or direction.motion_profile_id
    ) == "scene_author":
        from .scene_author import generate_scene_author_content

        return generate_scene_author_content(
            backend, template=template, concept_emd=concept_emd,
            scene_emd=scene_emd, direction=direction,
            system_prompts=system_prompts, runtime_config=runtime_config,
            staging_candidate_policy=staging_candidate_policy,
            interrupt_callback=interrupt_callback,
        )
    protector, _protected_concept, scene_context, shot_context, directions = _protected_context(
        template, concept_emd, scene_emd, direction
    )
    scene_shared = {"scene_context": scene_context} if scene_context else {}
    dialogue_filter = DialogueFilter(protector.records)
    subject_count = sum(
        1 for line in concept_emd.rstrip().split("\n") if line.startswith("* ")
    )
    subject_roster = [
        {
            "concept_id": f"サブジェクト{index}",
            "subject_ref": f"<Subject {index}>",
        }
        for index in range(1, subject_count + 1)
    ]
    subject_instance_policy = (
        "single_subject_exactly_one_visible_instance"
        if subject_count == 1
        else "defined_subjects_only_no_duplicate_instances"
    )
    all_issues: list[LLMRecordIssue] = []
    all_retries: set[int] = set()
    protocol_recovered_count = 0
    beat_repetition_warning_count = 0
    action_repetition_warning_count = 0
    camera_repetition_warning_count = 0
    # Environment inventory belongs to the final EMD renderer.  It must not be
    # offered as a menu of possible action targets or camera subjects.
    performance_directions = {
        key: value
        for key, value in directions.items()
        if key not in {"camera", "environment"}
    }
    camera_directions = {
        key: value
        for key, value in directions.items()
        if key not in {"motion", "environment"}
    }
    planner_policy = CAMERA_PLANNER_POLICIES.get(
        direction.camera_profile_id, ""
    )
    camera_render_style = CAMERA_RENDER_STYLES.get(
        direction.camera_profile_id, "detailed"
    )
    if camera_render_style == "compact":
        _LOGGER.info(
            "[MV Director - Timeline Planner] Camera render style=compact; "
            "finite Camera selections are unchanged"
        )
    configured_priority_cues = CAMERA_PRIORITY_LYRIC_CUES.get(
        direction.camera_profile_id, ()
    )
    lyric_cue_mode = CAMERA_LYRIC_CUE_MODES.get(
        direction.camera_profile_id,
        "priority_only" if configured_priority_cues else "off",
    )
    lyric_interpretation = CAMERA_LYRIC_INTERPRETATIONS.get(
        direction.camera_profile_id, "literal"
    )
    # Same tasks and output schema. Optional compact variants keep bounded
    # interpretation out of legacy/custom caller prompts unless supplied.
    system_prompts = dict(system_prompts)
    if lyric_interpretation == "bounded":
        for task in ("visual-beats", "actions"):
            if f"{task}-bounded" in system_prompts:
                system_prompts[task] = system_prompts[f"{task}-bounded"]
    if direction.staging_candidates:
        system_prompts["visual-beats"] += (
            "\nselected_staging_candidateは現在Sceneだけに選ばれた任意着想。"
            "採用する場合は対象・支持物・場所・接触を一組の出来事として扱い、"
            "動詞だけを抜き出さない。anchorが「なし」以外なら配置の対象位置をその文と完全一致させ、"
            "可視展開ではその位置の対象と人物の関係を示す。"
            "候補は原歌詞の引用根拠ではない。対象は現在Sceneの原歌詞から選ぶ。\n"
        )
        _LOGGER.info(
            "[MV Director - Timeline Planner] user staging directives; "
            "candidates=%d; scope=scene_visual_beats; selection=scene_local_llm",
            len(direction.staging_candidates),
        )
    planner_policy_contract = (
        {
            "policy_id": "anime_emotional_mv",
            "performance_mode": "lyric_specific_emotional_choreography",
            "generic_locomotion_is_support_only": True,
            "incidental_fixed_fixture_interaction": "forbidden",
            "lyric_trigger_scope": "current_scene_original_lyrics_only",
            "lyric_cue_mode": lyric_cue_mode,
            "noun_only_lyric_visualization": "same_scene_autonomous_visual_predicate",
            "environment_inventory_is_not_action_source": True,
            "lyric_target_consumption": "one_scene_then_requires_new_trigger",
            "external_effect_mode": "autonomous_or_hand_origin_with_visible_effect",
            "eye_expression_mode": "vary_eyelids_with_lyric_phase",
            "whole_body_emotion_mode": "coordinated_head_torso_pelvis_limbs_weight",
            "emotional_amplitude": "exaggerated_readable_full_body",
            "pose_contrast": "large_asymmetric_silhouette_change",
            "camera_phrase": "balanced_energetic_long_arc_short_face_pivot",
            "arc_density": "approximately_half_of_eligible_non_face_slots",
            "arc_energy": "large_amplitude_fast_70_90_percent",
            "face_zoom_frequency": "sparse_section_or_emotional_pivot",
            "later_scene_continue_minimum_ratio": "3/4",
            "all_later_continue_allowed": True,
            # Exact tokens are deliberately entity-local. Broadcasting them in
            # this shared contract lets a small model copy a later Scene's Cue
            # into every slot in the same request.
            "priority_lyric_cues": "entity_local_only",
            "priority_cue_scope": "exact_current_scene_source_only",
            "cue_card_schema": "v2_spatial_anchor_visible_development",
            "grounded_cue_development": "anchor_then_target_event_then_subject_response",
            "priority_cue_scene_arc": (
                "establish_relation_reaction_release_without_later_leakage"
            ),
        }
        if planner_policy == "anime_emotional_mv"
        else {"policy_id": planner_policy}
        if planner_policy
        else {}
    )

    planner_policy_contract["lyric_interpretation"] = lyric_interpretation
    if lyric_interpretation == "bounded":
        planner_policy_contract.update(
            whole_body_emotion_mode="only_parts_needed_for_the_event",
            pose_contrast="event_or_expression_change_not_mandatory_body_turn",
            grounded_cue_development="anchor_then_event_then_optional_subject_response",
        )
    performance_mode = MOTION_PERFORMANCE_MODES.get(direction.motion_profile_id, "event_based")
    body_accent_policy = MOTION_BODY_ACCENT_POLICIES.get(direction.motion_profile_id, "off")
    choreography_policy = MOTION_CHOREOGRAPHY_POLICIES.get(direction.motion_profile_id, "off")
    choreography_phrases = MOTION_CHOREOGRAPHY_PHRASES.get(direction.motion_profile_id, ())
    planner_policy_contract["performance_mode"] = performance_mode
    planner_policy_contract["body_accent_policy"] = body_accent_policy
    planner_policy_contract["choreography_policy"] = choreography_policy
    if performance_mode == "dance_phrase":
        if "actions-dance-phrase" in system_prompts:
            system_prompts["actions"] = system_prompts["actions-dance-phrase"]
        planner_policy_contract.update(
            whole_body_emotion_mode="one_connected_full_body_expression_phrase",
            emotional_amplitude="exaggerated_readable_full_body",
            pose_contrast="preparation_accent_release_across_scene_not_per_shot",
            lower_body_role="scene_level_weight_transfer_not_required_per_shot_no_body_spins",
        )
    if choreography_policy == "scene_choice":
        system_prompts["actions"] = system_prompts["actions"] + (
            "\nselected_choreography_phraseがあるShotでは、そのbody_pathを現在Sceneの着想として参照できる。"
            "候補の始点から動作を毎Shot再開せず、scene_spine_stepのFROMからADVANCEを経てTOへ進む。"
            "継続Sceneはentry_body_stateを実際の始点とし、候補の記載より優先する。"
            "候補全文のコピー、歌詞にない小道具・場所・接触、画角に映らない脚動作を追加しない。"
            "顔Shotはすでに起きた身体accentへの目・眉・歌唱口の反応だけを描く。\n"
        )
    _LOGGER.info(
        "[MV Director - Timeline Planner] performance_mode=%s; motion_profile=%s; "
        "phrase_fields=body_driver,final_state; choreography_policy=%s; "
        "additional_performance_stages=%d",
        performance_mode, direction.motion_profile_id or "none",
        choreography_policy, int(choreography_policy == "scene_choice"),
    )
    _LOGGER.info(
        "[MV Director - Timeline Planner] lyric interpretation=%s; "
        "cue_schema=v2; additional_inference_stages=%d",
        lyric_interpretation,
        int(lyric_interpretation == "bounded" and lyric_cue_mode == "automatic" and "lyric-cues" in system_prompts),
    )

    beat_values: dict[tuple[int, ...], str] = {}
    previous_beat = ""
    recent_beat_history: list[str] = []
    scene_lyrics_by_number: dict[int, list[object]] = {}
    scene_author_body_by_number: dict[int, list[object]] = {}
    scene_priority_cues: dict[int, tuple[dict[str, str], ...]] = {}
    for scene in template.scenes:
        scene_lyrics = [
            value
            for (scene_number, _), context in shot_context.items()
            if scene_number == scene.scene_number
            for value in context["lyrics"]
        ]
        scene_author_body = list(
            dict.fromkeys(
                value
                for (scene_number, _), context in shot_context.items()
                if scene_number == scene.scene_number
                for value in context["author_body"]
            )
        )
        scene_lyrics_by_number[scene.scene_number] = scene_lyrics
        scene_author_body_by_number[scene.scene_number] = scene_author_body
        scene_priority_cues[scene.scene_number] = (
            _priority_lyric_cues_from_sources(
                scene_lyrics,
                scene_author_body,
                configured_priority_cues,
            )
        )
    reading_contexts = (
        _lyric_reading_contexts(
            [scene.scene_number for scene in template.scenes],
            scene_lyrics_by_number,
        )
        if lyric_interpretation == "bounded"
        else {}
    )
    discovered_by_scene: dict[int, list[dict[str, str]]] = {}
    if lyric_interpretation == "bounded" and lyric_cue_mode == "automatic" and "lyric-cues" in system_prompts:
        from .cue_constraints import parse_discovery, select_scene_cue

        sources_by_scene = {
            n: list(dict.fromkeys([str(item["text"]).strip() for item in lyrics]
                                  + scene_author_body_by_number[n]))
            for n, lyrics in scene_lyrics_by_number.items()
        }
        unique_sources = list(dict.fromkeys(s for group in sources_by_scene.values() for s in group if s))
        discoveries: dict[str, dict[str, str] | None] = {}
        _LOGGER.info("[MV Director - Timeline Planner] lyric Cue discovery; unique_lines=%d; batch_lines=16", len(unique_sources))
        discovery_config = replace(runtime_config, max_tokens=min(runtime_config.max_tokens, 768))
        for batch_index, group in enumerate(_chunks(unique_sources, 16)):
            discovery_entities = [_Entity(0, (batch_index, i), {"text": source}) for i, source in enumerate(group)]
            found, issues, retries, missing, recovered = _request_entities(
                backend, task="lyric-cues", record_type="DISCOVERY", entities=discovery_entities,
                shared={}, system_prompt=system_prompts["lyric-cues"], runtime_config=discovery_config,
                interrupt_callback=interrupt_callback,
            )
            all_issues.extend(issues)
            protocol_recovered_count += recovered
            if missing:
                return None, missing
            for entity in discovery_entities:
                source = entity.value["text"]
                try:
                    discoveries[source] = parse_discovery(found[entity.key], source)
                except ValueError as error:
                    raise TimelinePlannerError(f"Invalid lyric discovery for {source!r}: {error}") from error
        for n, sources in sources_by_scene.items():
            if scene_priority_cues.get(n):
                continue
            discovered_by_scene[n] = select_scene_cue(sources, discoveries)
            _LOGGER.info("[MV Director - Timeline Planner] lyric Cue selected; scene=%d; candidates=%s; selected=%s",
                         n, [discoveries[s] for s in sources if discoveries.get(s)], discovered_by_scene[n])
    isolated_cue_scenes = [
        scene.scene_number
        for scene in template.scenes
        if scene_priority_cues.get(scene.scene_number)
    ]
    if isolated_cue_scenes:
        _LOGGER.info(
            "[MV Director - Timeline Planner] priority Cue scope isolation; "
            "scenes=%s; mode=scene_local_requests",
            ",".join(str(value) for value in isolated_cue_scenes),
        )
    selected_staging_by_scene: dict[int, dict[str, str]] = {}
    selected_body_staging_by_scene: dict[int, dict[str, str]] = {}
    used_spatial_candidates: set[int] = set()
    if direction.staging_candidates:
        for scene in template.scenes:
            available = [
                (index, candidate)
                for index, candidate in enumerate(direction.staging_candidates, 1)
                if index not in used_spatial_candidates
            ]
            if not available:
                break
            scene_number = scene.scene_number
            priority = scene_priority_cues.get(scene_number, ())
            discovered = discovered_by_scene.get(scene_number, ())
            current_target = (
                priority[0]["token"] if priority else
                discovered[0]["target"] if discovered else ""
            )
            selection_entity = _Entity(scene_number, (scene_number,), {
                "scene_number": scene_number,
                "lyrics": scene_lyrics_by_number[scene_number],
                "author_body": scene_author_body_by_number[scene_number],
                "current_target": current_target,
                "candidates": [
                    {"id": f"C{index}", "text": candidate}
                    for index, candidate in available
                ],
            })
            for attempt in range(2):
                values, issues, retries, missing, recovered = _request_entities(
                    backend, task="staging-selection", record_type="STAGING",
                    entities=[selection_entity], shared={},
                    system_prompt=system_prompts["staging-selection"],
                    runtime_config=replace(
                        runtime_config, max_tokens=min(runtime_config.max_tokens, 128)
                    ),
                    interrupt_callback=interrupt_callback,
                )
                all_issues.extend(issues)
                all_retries.update(retries)
                protocol_recovered_count += recovered
                if missing:
                    break
                try:
                    selected = parse_staging_selection(
                        values[selection_entity.key], direction.staging_candidates,
                        current_target=current_target,
                    )
                    if selected is not None and selected[0] not in {
                        index for index, _ in available
                    }:
                        raise ValueError("Candidate was already used for a spatial event")
                except ValueError as error:
                    if attempt == 0:
                        selection_entity = replace(selection_entity, value={
                            **selection_entity.value,
                            "retry": "invalid_selection",
                            "last_error": str(error),
                        })
                        continue
                    _LOGGER.warning(
                        "[MV Director - Timeline Planner] staging selection ignored; "
                        "scene=%d; reason=%s", scene_number, error,
                    )
                    break
                if selected is not None:
                    index, anchor = selected
                    selected_staging_by_scene[scene_number] = {
                        "id": f"C{index}",
                        "text": direction.staging_candidates[index - 1],
                        "anchor": anchor,
                    }
                    if anchor != "なし":
                        used_spatial_candidates.add(index)
                    else:
                        selected_body_staging_by_scene[scene_number] = {
                            "id": f"C{index}",
                            "text": direction.staging_candidates[index - 1],
                        }
                    _LOGGER.info(
                        "[MV Director - Timeline Planner] staging selected; "
                        "scene=%d; candidate=C%d; anchored=%s",
                        scene_number, index, "yes" if anchor != "なし" else "no",
                    )
                break
            if scene_number not in selected_staging_by_scene or (
                selected_staging_by_scene[scene_number]["anchor"] == "なし"
            ):
                continue
            body_available = [
                (index, candidate)
                for index, candidate in enumerate(direction.staging_candidates, 1)
                if index not in used_spatial_candidates
            ]
            if not body_available:
                continue
            body_entity = _Entity(scene_number, (scene_number,), {
                "scene_number": scene_number,
                "selection_role": "body",
                "lyrics": scene_lyrics_by_number[scene_number],
                "author_body": scene_author_body_by_number[scene_number],
                "current_target": current_target,
                "selected_event": selected_staging_by_scene[scene_number],
                "candidates": [
                    {"id": f"C{index}", "text": candidate}
                    for index, candidate in body_available
                ],
            })
            for attempt in range(2):
                values, issues, retries, missing, recovered = _request_entities(
                    backend, task="staging-selection", record_type="STAGING",
                    entities=[body_entity], shared={},
                    system_prompt=system_prompts["staging-selection"],
                    runtime_config=replace(
                        runtime_config, max_tokens=min(runtime_config.max_tokens, 128)
                    ),
                    interrupt_callback=interrupt_callback,
                )
                all_issues.extend(issues)
                all_retries.update(retries)
                protocol_recovered_count += recovered
                if missing:
                    break
                try:
                    selected_body = parse_staging_selection(
                        values[body_entity.key], direction.staging_candidates,
                        current_target=current_target,
                    )
                    if selected_body is not None and (
                        selected_body[1] != "なし"
                        or selected_body[0] not in {index for index, _ in body_available}
                    ):
                        raise ValueError("Body candidate must be available and use anchor=なし")
                except ValueError as error:
                    if attempt == 0:
                        body_entity = replace(body_entity, value={
                            **body_entity.value,
                            "retry": "invalid_body_selection",
                            "last_error": str(error),
                        })
                        continue
                    _LOGGER.warning(
                        "[MV Director - Timeline Planner] body staging selection ignored; "
                        "scene=%d; reason=%s", scene_number, error,
                    )
                    break
                if selected_body is not None:
                    body_index = selected_body[0]
                    selected_body_staging_by_scene[scene_number] = {
                        "id": f"C{body_index}",
                        "text": direction.staging_candidates[body_index - 1],
                    }
                    _LOGGER.info(
                        "[MV Director - Timeline Planner] body staging selected; "
                        "scene=%d; candidate=C%d", scene_number, body_index,
                    )
                break
    total_scenes = len(template.scenes)
    for scene_batch in _scene_batches_with_isolated_priority_cues(
        list(template.scenes), scene_priority_cues, scenes_per_batch
    ):
        entities = []
        for scene in scene_batch:
            scene_lyrics = scene_lyrics_by_number[scene.scene_number]
            scene_author_body = scene_author_body_by_number[
                scene.scene_number
            ]
            entities.append(
                _Entity(
                    scene.scene_number,
                    (scene.scene_number,),
                    {
                        "scene_number": scene.scene_number,
                        "scene_start_ms": scene.start_ms,
                        "scene_end_ms": scene.end_ms,
                        "total_scene_count": total_scenes,
                        "timeline_position": (
                            "opening"
                            if scene.scene_number <= max(1, total_scenes // 4)
                            else "closing"
                            if scene.scene_number > max(1, total_scenes * 3 // 4)
                            else "middle"
                        ),
                        "has_resolved_lyrics": bool(scene_lyrics),
                        "lyrics": scene_lyrics,
                        "author_body": scene_author_body,
                        **({"selected_staging_candidate": selected_staging_by_scene[scene.scene_number]}
                    if scene.scene_number in selected_staging_by_scene
                    and selected_staging_by_scene[scene.scene_number]["anchor"] != "なし" else {}),
                        "priority_lyric_cues": list(
                            scene_priority_cues[scene.scene_number]
                        ),
                        "previous_batch_beat": previous_beat,
                        **({"discovered_cues": discovered_by_scene[scene.scene_number]}
                           if scene.scene_number in discovered_by_scene else {}),
                        **(
                            {"lyric_reading_context": reading_contexts[scene.scene_number]}
                            if scene.scene_number in reading_contexts else {}
                        ),
                    },
                )
            )
        (
            values,
            issues,
            retries,
            missing,
            recovered,
            repetition_warnings,
        ) = _request_distinct_entities(
            backend,
            task="visual-beats",
            record_type="BEAT",
            entities=entities,
            shared={
                **scene_shared,
                "subject_roster": subject_roster,
                "direction": performance_directions,
                "planner_policy_contract": planner_policy_contract,
                "scene_context_usage": (
                    "spatial_support_only_never_activates_an_action_target"
                ),
                "recent_visual_beat_history": recent_beat_history[-12:],
            },
            history=recent_beat_history,
            system_prompt=system_prompts["visual-beats"],
            runtime_config=runtime_config,
            interrupt_callback=interrupt_callback,
        )
        all_issues.extend(issues)
        all_retries.update(retries)
        protocol_recovered_count += recovered
        beat_repetition_warning_count += repetition_warnings
        if missing:
            return None, missing
        beat_values.update(
            {key: dialogue_filter.filter(text) for key, text in values.items()}
        )
        recent_beat_history.extend(
            beat_values[(scene.scene_number,)]
            for scene in scene_batch
            if not scene_priority_cues.get(scene.scene_number)
        )
        if scene_batch:
            last_scene_number = scene_batch[-1].scene_number
            previous_beat = (
                ""
                if scene_priority_cues.get(last_scene_number)
                else beat_values.get((last_scene_number,), previous_beat)
            )

    beat_entities = {
        entity.key: entity
        for scene in template.scenes
        for entity in (
            _Entity(
                scene.scene_number,
                (scene.scene_number,),
                {
                    "lyrics": [
                        value
                        for (scene_number, _), context in shot_context.items()
                        if scene_number == scene.scene_number
                        for value in context["lyrics"]
                    ],
                    "author_body": list(
                        dict.fromkeys(
                            value
                            for (scene_number, _), context in shot_context.items()
                            if scene_number == scene.scene_number
                            for value in context["author_body"]
                        )
                    ),
                    **({"selected_staging_candidate": selected_staging_by_scene[scene.scene_number]}
                       if scene.scene_number in selected_staging_by_scene
                       and selected_staging_by_scene[scene.scene_number]["anchor"] != "なし" else {}),
                    "priority_lyric_cues": list(
                        scene_priority_cues.get(scene.scene_number, ())
                    ),
                    **({"discovered_cues": discovered_by_scene[scene.scene_number]}
                       if scene.scene_number in discovered_by_scene else {}),
                    **(
                        {"lyric_reading_context": reading_contexts[scene.scene_number]}
                        if scene.scene_number in reading_contexts else {}
                    ),
                },
            ),
        )
    }
    cue_cards = {
        key: _parse_cue_card(beat_entities[key], text)
        for key, text in beat_values.items()
    }
    staging_retry_entities = [
        _Entity(key[0], key, {
            **beat_entities[key].value,
            "rejected_output": beat_values[key],
            "retry": "selected_staging_anchor",
            "last_error": ",".join(card.violations),
        })
        for key, card in cue_cards.items()
        if "staging_anchor_missing" in card.violations
        or "staging_target_mismatch" in card.violations
    ]
    if staging_retry_entities:
        retry_values, retry_issues, retry_scenes, retry_missing, retry_recovered = (
            _request_entity_batches(
                backend, task="visual-beats", record_type="BEAT",
                entities=staging_retry_entities, batch_size=scenes_per_batch,
                shared={
                    "subject_roster": subject_roster,
                    "direction": performance_directions,
                    "planner_policy_contract": planner_policy_contract,
                    "staging_retry": "Preserve the complete selected spatial "
                    "relation in 配置 and its target at the interaction point.",
                },
                system_prompt=system_prompts["visual-beats"],
                runtime_config=runtime_config,
                interrupt_callback=interrupt_callback,
            )
        )
        all_issues.extend(retry_issues)
        all_retries.update(retry_scenes)
        protocol_recovered_count += retry_recovered
        failed_staging: list[tuple[str, int, int]] = list(retry_missing)
        for entity in staging_retry_entities:
            retry_text = retry_values.get(entity.key)
            if retry_text is not None:
                retry_text = dialogue_filter.filter(retry_text)
                retry_card = _parse_cue_card(beat_entities[entity.key], retry_text)
                if retry_card.valid:
                    beat_values[entity.key] = retry_text
                    cue_cards[entity.key] = retry_card
                    continue
            failed_staging.append(("STAGING_ANCHOR", entity.scene_number, 1))
        if failed_staging:
            _LOGGER.error(
                "[MV Director - Timeline Planner] selected staging anchor was "
                "not preserved after retry; scenes=%s",
                ",".join(str(item[1]) for item in failed_staging),
            )
            return None, tuple(dict.fromkeys(failed_staging))
    required_cue_scopes = dict(scene_priority_cues)
    for scene_number, discovered in discovered_by_scene.items():
        if discovered and discovered[0]["kind"] == "effect":
            required_cue_scopes[scene_number] = ({
                "token": discovered[0]["target"],
                "kind": "external_effect",
            },)
    priority_cue_retry_entities: list[_Entity] = []
    for key, card in cue_cards.items():
        priority_cues = required_cue_scopes.get(key[0], ())
        if not priority_cues:
            continue
        primary_cue = priority_cues[0]
        cue_violations = _priority_cue_card_violations(card, primary_cue)
        if not cue_violations:
            continue
        priority_cue_retry_entities.append(
            _Entity(
                key[0],
                key,
                {
                    **beat_entities[key].value,
                    "rejected_output": beat_values[key],
                    "required_priority_lyric_cue": dict(primary_cue),
                    "priority_cue_violations": list(cue_violations),
                    "retry": "priority_lyric_cue",
                },
            )
        )
    if priority_cue_retry_entities and planner_policy == "anime_emotional_mv":
        _LOGGER.info(
            "[MV Director - Timeline Planner] priority Cue Card retry; "
            "scenes=%s",
            ",".join(
                f"scene{entity.scene_number}:"
                f"{entity.value['required_priority_lyric_cue']['token']}"
                for entity in priority_cue_retry_entities
            ),
        )
        (
            priority_retry_values,
            priority_retry_issues,
            priority_retry_scenes,
            priority_retry_missing,
            priority_retry_recovered,
        ) = _request_entities(
            backend,
            task="visual-beats",
            record_type="BEAT",
            entities=priority_cue_retry_entities,
            shared={
                "subject_roster": subject_roster,
                "direction": performance_directions,
                "planner_policy_contract": planner_policy_contract,
                "recent_visual_beat_history": recent_beat_history[-12:],
                "priority_cue_retry": (
                    "Replace the rejected Cue Card. Select the exact selected "
                    "current-Scene lyric token and give it a visible same-Scene "
                    "relation, reaction, and release without carrying it later."
                ),
            },
            system_prompt=system_prompts["visual-beats"],
            runtime_config=runtime_config,
            interrupt_callback=interrupt_callback,
        )
        all_issues.extend(priority_retry_issues)
        all_retries.update(priority_retry_scenes)
        protocol_recovered_count += priority_retry_recovered
        for entity in priority_cue_retry_entities:
            text = priority_retry_values.get(entity.key)
            if not text:
                continue
            filtered_text = dialogue_filter.filter(text)
            retry_card = _parse_cue_card(
                beat_entities[entity.key], filtered_text
            )
            primary_cue = entity.value["required_priority_lyric_cue"]
            if not _priority_cue_card_violations(retry_card, primary_cue):
                beat_values[entity.key] = filtered_text
                cue_cards[entity.key] = retry_card
        unresolved_priority_cues = []
        for entity in priority_cue_retry_entities:
            primary_cue = entity.value["required_priority_lyric_cue"]
            violations = _priority_cue_card_violations(
                cue_cards[entity.key], primary_cue
            )
            if violations:
                cue_cards[entity.key] = replace(
                    cue_cards[entity.key],
                    valid=False,
                    violations=tuple(
                        dict.fromkeys(
                            (
                                *cue_cards[entity.key].violations,
                                *violations,
                            )
                        )
                    ),
                )
                unresolved_priority_cues.append(
                    f"scene{entity.scene_number}:"
                    f"{primary_cue['token']}="
                    f"{','.join(violations)}"
                )
        if priority_retry_missing or unresolved_priority_cues:
            _LOGGER.warning(
                "[MV Director - Timeline Planner] priority Cue Card retry "
                "remained incomplete; exact source tokens will still be "
                "enforced at Action stage; missing=%s; unresolved=%s",
                len(priority_retry_missing),
                ";".join(unresolved_priority_cues) or "none",
            )
    invalid_cues = {
        key: card for key, card in cue_cards.items() if not card.valid
    }
    grounded_cues = [
        f"scene{key[0]}:{card.target}"
        for key, card in sorted(cue_cards.items())
        if card.valid and card.target not in _CUE_NONE_VALUES
    ]
    priority_cue_labels = [
        f"scene{scene_number}:"
        + ",".join(
            f"{cue['token']}/{cue['kind']}" for cue in cues
        )
        for scene_number, cues in sorted(scene_priority_cues.items())
        if cues
    ]
    _LOGGER.info(
        "[MV Director - Timeline Planner] Cue Card validation; "
        "valid=%d; invalid=%d; grounded=%s; priority=%s",
        len(cue_cards) - len(invalid_cues),
        len(invalid_cues),
        ",".join(grounded_cues) or "none",
        ";".join(priority_cue_labels) or "none",
    )
    if invalid_cues and planner_policy == "anime_emotional_mv":
        _LOGGER.warning(
            "[MV Director - Timeline Planner] rejected ungrounded Cue Card fields "
            "from downstream Action/Camera context; scenes=%s; reasons=%s",
            ",".join(str(key[0]) for key in sorted(invalid_cues)),
            ";".join(
                f"scene{key[0]}:{','.join(card.violations)}"
                for key, card in sorted(invalid_cues.items())
            ),
        )

    action_cue_scopes = dict(required_cue_scopes)
    if lyric_cue_mode == "automatic":
        for key, card in cue_cards.items():
            if card.valid and card.target not in _CUE_NONE_VALUES:
                action_cue_scopes[key[0]] = (
                    {
                        "token": card.target,
                        "kind": (
                            required_cue_scopes[key[0]][0]["kind"]
                            if required_cue_scopes.get(key[0]) else "automatic"
                        ),
                        "evidence": card.evidence,
                    },
                )

    direction_entity = _Entity(0, (1,), {"visual_beats": [
        {"scene_number": key[0], "text": value} for key, value in sorted(beat_values.items())
    ]})
    song_values, issues, retries, missing, recovered = _request_entities(
        backend,
        task="song-direction",
        record_type="DIRECTION",
        entities=[direction_entity],
        shared={**scene_shared},
        system_prompt=system_prompts["song-direction"],
        runtime_config=replace(
            runtime_config, max_tokens=min(runtime_config.max_tokens, 512)
        ),
        interrupt_callback=interrupt_callback,
    )
    all_issues.extend(issues)
    all_retries.update(retries)
    protocol_recovered_count += recovered
    song_direction_fallback = bool(missing)
    song_direction = (
        ""
        if song_direction_fallback
        else dialogue_filter.filter(song_values[(1,)])
    )

    candidate_map = {
        scene.scene_number: build_layout_candidates(
            scene, min_duration_ms=_layout_min_duration_ms(
                scene, performance_mode=performance_mode,
                body_accent_policy=body_accent_policy,
                cue_card=cue_cards.get((scene.scene_number,)),
            )
        )
        for scene in template.scenes
    }
    layout_entities: list[_Entity] = []
    previous_layout_lyrics: list[dict[str, object]] = []
    seen_layout_sections: set[str] = set()
    for scene_index, scene in enumerate(template.scenes):
        lyric_groups = [
            {
                "shot_index": shot_index,
                "lyrics": shot_context[
                    (scene.scene_number, shot_index)
                ]["lyrics"],
            }
            for shot_index, _ in enumerate(scene.shots, 1)
        ]
        current_layout_lyrics = [
            lyric
            for group in lyric_groups
            for lyric in group["lyrics"]
        ]
        current_sections = {
            str(lyric["section"])
            for lyric in current_layout_lyrics
            if lyric["section"]
        }
        unseen_sections = current_sections - seen_layout_sections
        new_section_starts = [
            lyric.start_ms
            for shot in scene.shots
            for lyric in shot.lyric_annotations
            if lyric.section in unseen_sections and lyric.start_ms is not None
        ]
        new_section_start_ms = min(new_section_starts) if new_section_starts else None
        new_section_at_scene_start = (
            new_section_start_ms is not None
            and new_section_start_ms <= scene.start_ms + 500
        )
        section_entry_shot_index = next(
            (
                int(group["shot_index"])
                for group in lyric_groups
                if any(
                    str(lyric["section"]) in unseen_sections
                    for lyric in group["lyrics"]
                    if lyric["section"]
                )
            ),
            0,
        )
        previous_sections = {
            str(lyric["section"])
            for lyric in previous_layout_lyrics
            if lyric["section"]
        }
        layout_entities.append(
            _Entity(
                scene.scene_number,
                (scene.scene_number,),
                {
                    "scene_number": scene.scene_number,
                    "scene_start_ms": scene.start_ms,
                    "scene_end_ms": scene.end_ms,
                    "visual_beat": beat_values[(scene.scene_number,)],
                    "previous_visual_beat": (
                        ""
                        if scene_index == 0
                        else beat_values[(template.scenes[scene_index - 1].scene_number,)]
                    ),
                    "previous_lyrics": previous_layout_lyrics,
                    "section_changed": (
                        bool(current_sections and previous_sections)
                        and current_sections != previous_sections
                    ),
                    "first_section_appearance": bool(unseen_sections),
                    "new_section_start_ms": new_section_start_ms,
                    "new_section_at_scene_start": new_section_at_scene_start,
                    "new_sections": sorted(unseen_sections),
                    "section_entry_shot_index": section_entry_shot_index,
                    "lyric_groups": lyric_groups,
                    "contact_verse": (
                        body_accent_policy == "sparse_chorus_prechorus_verse_contact"
                        and _verse_contact_cue(
                            {section.upper() for section in current_sections},
                            cue_cards.get((scene.scene_number,)),
                        )
                    ),
                    "candidates": [
                        candidate.to_dict()
                        for candidate in candidate_map[scene.scene_number]
                    ],
                },
            )
        )
        seen_layout_sections.update(current_sections)
        previous_layout_lyrics = current_layout_lyrics
    layout_texts, issues, retries, missing, recovered = _request_entity_batches(
        backend,
        task="shot-layout",
        record_type="LAYOUT",
        entities=layout_entities,
        batch_size=scenes_per_batch,
        shared={
            **scene_shared,
            "song_direction": song_direction,
            "planner_policy_contract": planner_policy_contract,
        },
        system_prompt=system_prompts["shot-layout"],
        runtime_config=runtime_config,
        interrupt_callback=interrupt_callback,
    )
    all_issues.extend(issues)
    all_retries.update(retries)
    protocol_recovered_count += recovered
    if missing:
        return None, missing
    (
        layouts,
        continuations,
        layout_repaired_scenes,
        layout_fallback_scenes,
    ) = _decode_layout_texts(template, candidate_map, layout_texts)
    layout_mix_retry = False
    if (
        len(template.scenes) >= 4
        and not _satisfies_boundary_contract(
            template,
            continuations,
            planner_policy=planner_policy,
        )
    ):
        layout_mix_retry = True
        later_values = [
            continuations[scene.scene_number]
            for scene in template.scenes[1:]
        ]
        if planner_policy == "anime_emotional_mv":
            retry_reason = (
                "The emotional choreography profile requires at least three "
                "quarters of later Scene boundaries to remain CONTINUE. Keep "
                "the uninterrupted performance and camera path unless a CUT "
                "is a purposeful emotional or spatial reset."
            )
        elif later_values and all(later_values):
            retry_reason = (
                "Every later boundary was CONTINUE. Keep CONTINUE only for an "
                "uninterrupted action and introduce lyric-driven CUT edits."
            )
        elif later_values and not any(later_values):
            retry_reason = (
                "Every boundary was CUT. Compare each Scene with previous_lyrics "
                "and previous_visual_beat; keep emotional pivots as CUT, but use "
                "CONTINUE for genuinely uninterrupted action phases."
            )
        else:
            retry_reason = (
                "The boundary mix did not meet the minimum CUT and CONTINUE "
                "counts, exceeded the maximum same-mode run, or alternated "
                "CUT and CONTINUE too mechanically. Re-evaluate "
                "every adjacent Scene against the supplied boundary contract."
            )
        later_count = len(template.scenes) - 1
        (
            retry_texts,
            retry_issues,
            retry_scenes,
            retry_missing,
            recovered,
        ) = _request_entity_batches(
            backend,
            task="shot-layout",
            record_type="LAYOUT",
            entities=layout_entities,
            batch_size=scenes_per_batch,
            shared={
                **scene_shared,
                "song_direction": song_direction,
                "planner_policy_contract": planner_policy_contract,
                "boundary_mix_retry_reason": retry_reason,
                "boundary_contract": {
                    "first_scene": "CUT",
                    "later_cut_minimum": (
                        0
                        if planner_policy == "anime_emotional_mv"
                        else max(1, (len(template.scenes) - 1) // 4)
                    ),
                    "later_continue_minimum": max(
                        1,
                        (
                            (later_count * 3 + 3) // 4
                            if planner_policy == "anime_emotional_mv"
                            else len(template.scenes) // 2
                        ),
                    ),
                    "maximum_consecutive_same_mode": (
                        later_count
                        if planner_policy == "anime_emotional_mv"
                        else 3
                    ),
                    "maximum_mode_transitions": max(
                        2, (later_count * 2 + 2) // 3
                    ),
                },
            },
            system_prompt=system_prompts["shot-layout"],
            runtime_config=runtime_config,
            interrupt_callback=interrupt_callback,
        )
        all_issues.extend(retry_issues)
        all_retries.update(retry_scenes)
        protocol_recovered_count += recovered
        if not retry_missing:
            (
                retry_layouts,
                retry_continuations,
                retry_repaired,
                retry_fallback,
            ) = _decode_layout_texts(template, candidate_map, retry_texts)
            layouts = retry_layouts
            continuations = retry_continuations
            layout_repaired_scenes = retry_repaired
            layout_fallback_scenes = retry_fallback
        if not _satisfies_boundary_contract(
            template,
            continuations,
            planner_policy=planner_policy,
        ):
            continuations, boundary_repaired = _repair_boundary_contract(
                template,
                continuations,
                planner_policy=planner_policy,
            )
            layout_repaired_scenes = sorted(
                {*layout_repaired_scenes, *boundary_repaired}
            )
        layout_mix_retry = True
    planned_template = apply_shot_layouts(template, layouts)
    planned_template = apply_scene_continuations(
        planned_template, continuations
    )
    shot_context = _shot_context(planned_template, protector)
    dialogue_filter.add_records(protector.records)

    scene_numbers = [scene.scene_number for scene in planned_template.scenes]
    previous_scene_numbers = {
        number: scene_numbers[index - 1] if index else None
        for index, number in enumerate(scene_numbers)
    }
    scene_shot_counts = {
        scene.scene_number: len(scene.shots)
        for scene in planned_template.scenes
    }

    scene_spine_steps: dict[tuple[int, int], SceneSpineStep] = {}
    scene_spine_raw: dict[tuple[int, int], str] = {}
    scene_spine_skipped: list[int] = []
    scene_choreography: dict[int, tuple[str, str]] = {}
    previous_choreography_id = ""
    if choreography_policy == "scene_choice" and (
        "choreography-choice" not in system_prompts
        or "scene-spine" not in system_prompts
        or len(choreography_phrases) < 2
    ):
        raise TimelinePlannerError(
            "scene_choice requires a choreography-choice prompt and at least two profile phrases"
        )
    if performance_mode == "dance_phrase" and "scene-spine" in system_prompts:
        for scene in planned_template.scenes:
            card = cue_cards.get((scene.scene_number,))
            keys = [(scene.scene_number, index) for index in range(1, len(scene.shots) + 1)]
            if choreography_policy == "scene_choice" and keys:
                choice_entity = _Entity(scene.scene_number, (scene.scene_number,), {
                    "scene_number": scene.scene_number,
                    "lyric_lines": list(dict.fromkeys(
                        str(lyric["text"])
                        for key in keys for lyric in shot_context[key]["lyrics"]
                    )),
                    "sections": list(dict.fromkeys(
                        str(lyric["section"])
                        for key in keys for lyric in shot_context[key]["lyrics"]
                        if lyric.get("section")
                    )),
                    "author_body": list(dict.fromkeys(
                        str(line)
                        for key in keys for line in shot_context[key]["author_body"]
                    )),
                    "camera_coverage": [
                        _camera_editorial_role(
                            shot_context[key], lip_sync_active=lip_sync_mode != "off"
                        ) for key in keys
                    ],
                })
                choices, issues, retries, missing, recovered = _request_entities(
                    backend, task="choreography-choice", record_type="CHOICE",
                    entities=[choice_entity],
                    shared={
                        "scene_number": scene.scene_number,
                        "scene_continuation": scene.continuation,
                        "entry_body_state": _continuation_body_state(
                            previous_scene_numbers[scene.scene_number],
                            continuation=scene.continuation,
                            last_shot_by_scene=scene_shot_counts,
                            cue_cards=cue_cards,
                            scene_spine_steps=scene_spine_steps,
                        ),
                        "visual_beat_grounding": card.to_dict() if card and card.valid else {},
                        "previous_phrase_id": previous_choreography_id,
                        "candidates": [
                            {"id": phrase_id, "body_path": body_path}
                            for phrase_id, body_path in choreography_phrases
                        ],
                    },
                    system_prompt=system_prompts["choreography-choice"],
                    runtime_config=replace(runtime_config, max_tokens=min(runtime_config.max_tokens, 96)),
                    interrupt_callback=interrupt_callback,
                )
                all_issues.extend(issues)
                all_retries.update(retries)
                protocol_recovered_count += recovered
                phrase_id = accept_choreography_choice(
                    choices.get(choice_entity.key, ""),
                    [candidate_id for candidate_id, _ in choreography_phrases],
                ) if not missing else None
                if phrase_id == "FREEFORM":
                    previous_choreography_id = phrase_id
                    _LOGGER.info(
                        "[MV Director - Timeline Planner] choreography freeform; "
                        "scene=%d; shots=%d", scene.scene_number, len(keys),
                    )
                elif phrase_id is not None:
                    scene_choreography[scene.scene_number] = (
                        phrase_id, dict(choreography_phrases)[phrase_id]
                    )
                    previous_choreography_id = phrase_id
                    _LOGGER.info(
                        "[MV Director - Timeline Planner] choreography selected; "
                        "scene=%d; phrase=%s; shots=%d",
                        scene.scene_number, phrase_id, len(keys),
                    )
                else:
                    _LOGGER.warning(
                        "[MV Director - Timeline Planner] choreography choice invalid; "
                        "scene=%d; legacy Action path retained",
                        scene.scene_number,
                    )
            track_external_effect = bool(
                card and card.valid
                and card.phenomenon in {"外部自律", "身体操作"}
            )
            if len(scene.shots) < 2 and not track_external_effect:
                continue
            if card is None or not card.valid:
                continue
            if (
                card.target in _CUE_NONE_VALUES
                and body_accent_policy != "scene_phrase"
            ):
                continue
            spine_entities = [
                _Entity(scene.scene_number, key, {
                    "scene_number": scene.scene_number,
                    "shot_index": key[1],
                    "shot_count": len(keys),
                    "shot_start_ms": shot_context[key]["shot_start_ms"],
                    "shot_end_ms": shot_context[key]["shot_end_ms"],
                    "shot_duration_ms": shot_context[key]["shot_duration_ms"],
                    "lyrics": shot_context[key]["lyrics"],
                    "editorial_role": _camera_editorial_role(
                        shot_context[key], lip_sync_active=lip_sync_mode != "off"
                    ),
                })
                for key in keys
            ]
            if card.contact == "許可" and all(
                entity.value["editorial_role"] == "face_performance_cut"
                for entity in spine_entities
            ):
                scene_spine_skipped.append(scene.scene_number)
                _LOGGER.warning(
                    "[MV Director - Timeline Planner] Scene spine skipped; "
                    "scene=%d; reason=no_event_slot_with_contact_coverage; "
                    "legacy Action/Camera path retained",
                    scene.scene_number,
                )
                continue
            body_phrase_only = (
                body_accent_policy == "scene_phrase"
                and card.target in _CUE_NONE_VALUES
            )
            if body_phrase_only and all(
                entity.value["editorial_role"] == "face_performance_cut"
                for entity in spine_entities
            ):
                scene_spine_skipped.append(scene.scene_number)
                continue
            shared_spine = {
                "scene_number": scene.scene_number,
                "scene_start_ms": scene.start_ms,
                "scene_end_ms": scene.end_ms,
                "lyric_lines": list(dict.fromkeys(
                    str(lyric["text"])
                    for key in keys for lyric in shot_context[key]["lyrics"]
                )),
                "author_body": list(dict.fromkeys(
                    str(line)
                    for key in keys for line in shot_context[key]["author_body"]
                )),
                "visual_beat_grounding": card.to_dict(),
                "body_phrase_policy": body_accent_policy,
                "track_external_effect": track_external_effect,
                "spine_event_kind": (
                    "physical_contact" if card.contact == "許可"
                    else "non_contact_change"
                ),
                "scene_continuation": scene.continuation,
                "entry_body_state": _continuation_body_state(
                    previous_scene_numbers[scene.scene_number],
                    continuation=scene.continuation,
                    last_shot_by_scene=scene_shot_counts,
                    cue_cards=cue_cards,
                    scene_spine_steps=scene_spine_steps,
                ),
                "entry_effect_state": _continuation_effect_state(
                    previous_scene_numbers[scene.scene_number],
                    continuation=scene.continuation,
                    last_shot_by_scene=scene_shot_counts,
                    scene_spine_steps=scene_spine_steps,
                ),
                **({
                    "selected_choreography_phrase": {
                        "id": scene_choreography[scene.scene_number][0],
                        "body_path": scene_choreography[scene.scene_number][1],
                    }
                } if scene.scene_number in scene_choreography else {}),
                **({"selected_body_staging_candidate": selected_body_staging_by_scene[scene.scene_number]}
                   if scene.scene_number in selected_body_staging_by_scene else {}),
            }
            spine_config = replace(
                runtime_config,
                max_tokens=min(runtime_config.max_tokens, max(512, 192 * len(keys) + 128)),
            )
            last_error = ""
            for attempt in range(2):
                raw, issues, retries, missing, recovered = _request_entities(
                    backend, task="scene-spine", record_type="SPINE",
                    entities=spine_entities,
                    shared={**shared_spine, **(
                        {"retry": "invalid_scene_spine", "last_error": last_error}
                        if attempt else {}
                    )},
                    system_prompt=(
                        (
                            system_prompts.get(
                                "scene-spine-body", system_prompts["scene-spine"]
                            ) if body_phrase_only else system_prompts["scene-spine"]
                        )
                        + (
                            "\nselected_choreography_phraseがある場合、その身体経路を着想として歌詞と固定Shotへ具体化してよい。より適切な独自の身体経路を考案してもよい。候補本文の始点姿勢へ毎Scene戻らず、継続時はentry_body_stateから始める。候補の全文を写さず、接触・場所・対象はvisual_beat_groundingだけを根拠にする。\n"
                            if scene.scene_number in scene_choreography else ""
                        )
                    ),
                    runtime_config=spine_config,
                    interrupt_callback=interrupt_callback,
                )
                all_issues.extend(issues)
                all_retries.update(retries)
                protocol_recovered_count += recovered
                if missing:
                    last_error = "missing_spine_slots"
                    continue
                try:
                    steps = tuple(parse_scene_spine_step(raw[key]) for key in keys)
                    validate_scene_spine(steps)
                    if track_external_effect and any(not step.effect_to for step in steps):
                        raise ValueError("external effect endpoint is missing")
                    validate_contact_coverage(
                        steps, contact_allowed=card.contact == "許可"
                    )
                    if body_phrase_only and (
                        steps[next(index for index, step in enumerate(steps)
                                   if step.phase == "event")].show != "whole_body"
                        or any(
                            step.show in {
                                "lyric_target", "lyric_target_hands",
                                "lyric_target_body",
                            }
                            for step in steps
                        )
                    ):
                        raise ValueError("body-only Scene must show its body accent")
                    if any(
                        entity.value["editorial_role"] == "face_performance_cut"
                        and step.show != "face_eyes_mouth"
                        for entity, step in zip(spine_entities, steps)
                    ):
                        raise ValueError("face cut must show eyes and singing mouth")
                except (KeyError, ValueError) as error:
                    last_error = str(error)
                    continue
                scene_spine_steps.update(zip(keys, steps))
                scene_spine_raw.update((key, raw[key]) for key in keys)
                _LOGGER.info(
                    "[MV Director - Timeline Planner] Scene spine accepted; "
                    "scene=%d; shots=%d; attempt=%d",
                    scene.scene_number, len(keys), attempt + 1,
                )
                break
            else:
                scene_spine_skipped.append(scene.scene_number)
                _LOGGER.warning(
                    "[MV Director - Timeline Planner] Scene spine skipped; "
                    "scene=%d; reason=%s; legacy Action/Camera path retained",
                    scene.scene_number, last_error,
                )

    action_values: dict[tuple[int, ...], str] = {}
    body_accent_keys = (
        _sparse_body_accent_keys(
            shot_context, scene_spine_steps, lip_sync_active=lip_sync_mode != "off",
            cue_cards=cue_cards,
            include_prechorus_single=body_accent_policy in {
                "sparse_chorus_prechorus",
                "sparse_chorus_prechorus_verse_contact",
            },
            include_verse_contact=body_accent_policy == "sparse_chorus_prechorus_verse_contact",
            include_all_scenes=body_accent_policy == "scene_phrase",
        )
        if body_accent_policy in {
            "sparse_chorus", "sparse_chorus_prechorus",
            "sparse_chorus_prechorus_verse_contact", "scene_phrase",
        } else set()
    )
    _LOGGER.info(
        "[MV Director - Timeline Planner] body accents; policy=%s; slots=%s",
        body_accent_policy,
        ",".join(f"scene{scene}:shot{shot}" for scene, shot in sorted(body_accent_keys)) or "none",
    )
    previous_action = ""
    recent_action_history: list[str] = []
    for scene_batch in _scene_batches_with_isolated_priority_cues(
        list(planned_template.scenes), action_cue_scopes, scenes_per_batch
    ):
        keys = [
            key for key in planned_template.shot_keys
            if key[0] in {scene.scene_number for scene in scene_batch}
        ]
        entities = []
        prior_key: tuple[int, int] | None = None
        for key in keys:
            context = dict(shot_context[key])
            cue_card = cue_cards[(key[0],)]
            context["visual_beat"] = (
                beat_values[(key[0],)]
                if planner_policy != "anime_emotional_mv" or cue_card.valid
                else ""
            )
            context["visual_beat_grounding"] = cue_card.to_dict()
            selected_staging = selected_staging_by_scene.get(key[0])
            if selected_staging is not None and cue_card.valid:
                context["selected_staging_anchor"] = selected_staging["anchor"]
            if key[0] in selected_body_staging_by_scene:
                context["selected_body_staging_candidate"] = selected_body_staging_by_scene[key[0]]
            if key[0] in scene_choreography:
                context["selected_choreography_phrase"] = {
                    "id": scene_choreography[key[0]][0],
                    "body_path": scene_choreography[key[0]][1],
                }
            if key in scene_spine_steps:
                context["scene_spine_step"] = scene_spine_steps[key].to_dict()
                context["scene_spine_previous_end"] = (
                    scene_spine_steps[(key[0], key[1] - 1)].to_state
                    if (key[0], key[1] - 1) in scene_spine_steps else ""
                )
                context["scene_spine_previous_effect_end"] = (
                    scene_spine_steps[(key[0], key[1] - 1)].effect_to
                    if (key[0], key[1] - 1) in scene_spine_steps else ""
                )
            priority_cues = required_cue_scopes.get(key[0], ())
            context["priority_lyric_cues"] = list(priority_cues)
            discovered = discovered_by_scene.get(key[0], ())
            context["discovered_cue_kind"] = (
                discovered[0]["kind"] if discovered and discovered[0]["target"] == cue_card.target
                else ""
            )
            has_automatic_cue = (
                lyric_cue_mode == "automatic"
                and cue_card.valid
                and cue_card.target not in _CUE_NONE_VALUES
            )
            grounded_cue_phase = (
                _priority_cue_phase(
                    key[-1], scene_shot_counts.get(key[0], 1)
                )
                if priority_cues or has_automatic_cue
                else ""
            )
            if key in scene_spine_steps:
                grounded_cue_phase = {
                    "setup": "establish",
                    "event": "event_and_reaction",
                    "response": "reaction_and_release",
                }[scene_spine_steps[key].phase]
            context["grounded_cue_phase"] = grounded_cue_phase
            context["priority_cue_phase"] = (
                grounded_cue_phase if priority_cues else ""
            )
            context["grounded_cue_required"] = (
                planner_policy == "anime_emotional_mv"
                and (
                    bool(priority_cues)
                    or (
                        lyric_cue_mode == "automatic"
                        and cue_card.valid
                        and cue_card.target not in _CUE_NONE_VALUES
                    )
                )
            )
            context["performance_role"] = _performance_role(
                context,
                lip_sync_active=lip_sync_mode != "off",
            )
            context["performance_mode"] = performance_mode
            if performance_mode == "dance_phrase":
                count = scene_shot_counts.get(key[0], 1)
                phase = ("complete_phrase" if count == 1 else
                         "prepare_and_accent" if key[-1] == 1 else
                         "release_and_reaction" if key[-1] == count else "develop_accent")
                context["performance_phase"] = phase
                context["phrase_position"] = f"{key[-1]}/{count}"
                context["entry_body_state"] = _continuation_body_state(
                    previous_scene_numbers[key[0]],
                    continuation=bool(context["scene_continuation"]) and key[-1] == 1,
                    last_shot_by_scene=scene_shot_counts,
                    cue_cards=cue_cards,
                    scene_spine_steps=scene_spine_steps,
                )
                context["entry_effect_state"] = _continuation_effect_state(
                    previous_scene_numbers[key[0]],
                    continuation=bool(context["scene_continuation"]) and key[-1] == 1,
                    last_shot_by_scene=scene_shot_counts,
                    scene_spine_steps=scene_spine_steps,
                )
                if key in body_accent_keys:
                    context["performance_role"] = "body_phrase_accent"
                elif (
                    body_accent_policy == "off"
                    and context["performance_role"] != "face_and_upper_body_accent"
                ):
                    context["performance_role"] = "continuous_upper_body_phrase"
            context["previous_shot"] = (
                None
                if prior_key is None
                else {"scene_number": prior_key[0], "shot_index": prior_key[1]}
            )
            if prior_key is None:
                context["previous_batch_action"] = previous_action
            if (
                context["performance_role"] == "face_and_upper_body_accent"
                and planner_policy != "anime_emotional_mv"
            ):
                action_values[key] = FACE_PERFORMANCE_CUT_ACTION
            else:
                entities.append(_Entity(key[0], key, context))
            prior_key = key
        if planner_policy == "anime_emotional_mv":
            entities = _with_grounding_transfer_requirements(
                entities,
                automatic=lyric_cue_mode == "automatic",
            )
            transfer_labels = [
                (
                    f"scene{entity.scene_number}:slot{entity.key[-1]}:"
                    f"role={entity.value.get('performance_role', 'none')}:"
                    f"phase={entity.value.get('grounded_cue_phase', 'none')}:"
                    f"anchor={entity.value.get('required_spatial_anchor', 'none')}:"
                    f"development="
                    f"{entity.value.get('required_visible_development', 'none')}"
                )
                for entity in entities
                if entity.value.get("required_spatial_anchor")
                or entity.value.get("required_visible_development")
            ]
            if transfer_labels:
                _LOGGER.info(
                    "[MV Director - Timeline Planner] Action grounding transfer; "
                    "requirements=%s",
                    ";".join(transfer_labels),
                )
        if entities:
            (
                values,
                issues,
                retries,
                missing,
                recovered,
                repetition_warnings,
            ) = _request_distinct_entities(
                backend,
                task="actions",
                record_type="ACTION",
                entities=entities,
                shared={
                    "subject_roster": subject_roster,
                    "direction": performance_directions,
                    "planner_policy_contract": planner_policy_contract,
                    "primary_action_concept": lip_sync_target,
                    "subject_instance_policy": subject_instance_policy,
                    "action_batch_contract": {
                        "slow_or_gentle_action_maximum": max(
                            1, len(entities) // 4
                        ),
                        "generic_hand_raise_or_lower_maximum": 0,
                        "unrequested_lower_body_primary_action_maximum": 0,
                        "unrequested_running_maximum": 0,
                    },
                    "recent_action_history": recent_action_history[-18:],
                },
                history=recent_action_history,
                system_prompt=system_prompts["actions"],
                runtime_config=runtime_config,
                interrupt_callback=interrupt_callback,
            )
            if not missing:
                budget_violations = _action_budget_violations(
                    entities,
                    values,
                    configured_priority_cues=configured_priority_cues,
                )
                if budget_violations:
                    _LOGGER.info(
                        "[MV Director - Timeline Planner] Action quality retry; "
                        "slots=%s",
                        ";".join(
                            f"scene{entity.scene_number}:slot{entity.key[-1]}="
                            f"{','.join(budget_violations[entity.key])}"
                            for entity in entities
                            if entity.key in budget_violations
                        ),
                    )
                    retry_entities = [
                        _Entity(
                            entity.scene_number,
                            entity.key,
                            {
                                **entity.value,
                                **(
                                    {
                                        "rejected_output_withheld": (
                                            "invalid_transport_wrapper"
                                            if "internal_protocol_label"
                                            in budget_violations[entity.key]
                                            else "unexpected_priority_cue"
                                        )
                                    }
                                    if any(
                                        reason
                                        in {
                                            "unexpected_priority_cue",
                                            "internal_protocol_label",
                                        }
                                        for reason in budget_violations[entity.key]
                                    )
                                    else {
                                        "rejected_output": values[entity.key]
                                    }
                                ),
                                "action_quality_violations": list(
                                    budget_violations[entity.key]
                                ),
                            },
                        )
                        for entity in entities
                        if entity.key in budget_violations
                    ]
                    (
                        retry_values,
                        retry_issues,
                        retry_scenes,
                        retry_missing,
                        retry_recovered,
                    ) = _request_entities(
                        backend,
                        task="actions",
                        record_type="ACTION",
                        entities=retry_entities,
                        shared={
                            "subject_roster": subject_roster,
                            "direction": performance_directions,
                            "planner_policy_contract": planner_policy_contract,
                            "primary_action_concept": lip_sync_target,
                            "subject_instance_policy": subject_instance_policy,
                            "action_batch_contract": {
                                "slow_or_gentle_action_maximum": max(
                                    1, len(entities) // 4
                                ),
                                "generic_hand_raise_or_lower_maximum": 0,
                                "unrequested_lower_body_primary_action_maximum": 0,
                                "unrequested_running_maximum": 0,
                            },
                            "recent_action_history": recent_action_history[-18:],
                            "retry": "action_quality_budget",
                            "action_quality_retry": (
                                "Replace the rejected Action choice. Resolve every "
                                "listed quality violation with a decisive, lyric-linked "
                                "performance and a visibly different final silhouette."
                            ),
                        },
                        system_prompt=system_prompts["actions"],
                        runtime_config=runtime_config,
                        interrupt_callback=interrupt_callback,
                    )
                    issues.extend(retry_issues)
                    all_retries.update(retry_scenes)
                    recovered += retry_recovered
                    missing = tuple(retry_missing)
                    values.update(retry_values)
                    remaining_budget_violations = _action_budget_violations(
                        entities,
                        values,
                        configured_priority_cues=configured_priority_cues,
                    )
                    repetition_warnings += len(remaining_budget_violations)
            if not missing and planner_policy == "anime_emotional_mv":
                audit_shared = {
                    "direction": performance_directions,
                    "planner_policy_contract": planner_policy_contract,
                    "recent_action_history": recent_action_history[-18:],
                    "audit_contract": {
                        "verdicts": [
                            "PASS",
                            "REJECT:SEMANTIC_REPETITION",
                            "REJECT:PROFILE_CONFLICT",
                            "REJECT:INCIDENTAL_FIXTURE",
                            "REJECT:UNREQUESTED_LOWER_BODY",
                            "REJECT:UNREQUESTED_CONTACT",
                            "REJECT:REFERENCE_POSE",
                            "REJECT:MISSING_GROUNDED_CUE",
                            "REJECT:FACE_PERFORMANCE_MISSING",
                            "REJECT:BODY_TEMPLATE_REPETITION",
                            "REJECT:BODY_ACCENT_MISSING",
                            "REJECT:INTERNAL_PROTOCOL_LABEL",
                        ],
                        "repair_attempts": _ACTION_AUDIT_REPAIR_ATTEMPTS,
                        "fail_closed": False,
                        "exhaustion_policy": "retain_best_candidate_as_is_with_warning",
                    },
                }
                audit_failures: dict[tuple[int, ...], tuple[str, ...]] = {}
                best_values: dict[tuple[int, ...], str] = dict(values)
                best_scores: dict[tuple[int, ...], tuple[int, int, int, int]] = {}
                best_diagnostics: dict[tuple[int, ...], tuple[str, ...]] = {}
                for audit_round in range(_ACTION_AUDIT_REPAIR_ATTEMPTS + 1):
                    (
                        audit_failures,
                        audit_issues,
                        audit_retries,
                        audit_missing,
                        audit_recovered,
                    ) = _request_action_audit(
                        backend,
                        entities=entities,
                        values=values,
                        shared={**audit_shared, "audit_round": audit_round + 1},
                        system_prompt=system_prompts["action-audit"],
                        runtime_config=runtime_config,
                        interrupt_callback=interrupt_callback,
                    )
                    issues.extend(audit_issues)
                    all_retries.update(audit_retries)
                    recovered += audit_recovered
                    if audit_missing:
                        repetition_warnings += len(audit_missing)
                        _LOGGER.warning(
                            "[MV Director - Timeline Planner] Action audit protocol "
                            "remained incomplete; retained the current LLM-generated "
                            "Action text AS IS; round=%d; missing=%s",
                            audit_round + 1,
                            ",".join(
                                f"scene{scene}:slot{slot}"
                                for _kind, scene, slot in audit_missing
                            ),
                        )
                        break
                    quality_failures = _action_budget_violations(
                        entities,
                        values,
                        configured_priority_cues=configured_priority_cues,
                    )
                    repeated_entities, _ = _repeated_entities(
                        entities, values, recent_action_history
                    )
                    repeated_keys = {
                        entity.key for entity in repeated_entities
                    }
                    rejected_keys = (
                        set(audit_failures)
                        | set(quality_failures)
                        | repeated_keys
                    )
                    diagnostic_labels: dict[tuple[int, ...], tuple[str, ...]] = {}
                    for entity in entities:
                        key = entity.key
                        labels = tuple(
                            [
                                *(
                                    f"audit:{reason}"
                                    for reason in audit_failures.get(key, ())
                                ),
                                *(
                                    f"quality:{reason}"
                                    for reason in quality_failures.get(key, ())
                                ),
                                *(
                                    ("repetition:surface_similarity",)
                                    if key in repeated_keys
                                    else ()
                                ),
                            ]
                        )
                        score = (
                            sum(reason in {
                                "internal_protocol_label", "missing_spatial_anchor",
                                "missing_visible_development",
                            } for reason in quality_failures.get(key, ())),
                            len(quality_failures.get(key, ())),
                            int(key in repeated_keys),
                            len(audit_failures.get(key, ())),
                        )
                        if key not in best_scores or score < best_scores[key]:
                            best_scores[key] = score
                            best_values[key] = values[key]
                            best_diagnostics[key] = labels
                        if labels:
                            diagnostic_labels[key] = labels
                    reason_summary = "; ".join(
                        f"scene{entity.scene_number}:slot{entity.key[-1]}="
                        f"{','.join(diagnostic_labels[entity.key])}"
                        for entity in entities
                        if entity.key in diagnostic_labels
                    )
                    _LOGGER.info(
                        "[MV Director - Timeline Planner] Action audit round "
                        "%d/%d; audit_rejects=%d; quality=%d; repetition=%d; "
                        "reasons=%s",
                        audit_round + 1,
                        _ACTION_AUDIT_REPAIR_ATTEMPTS + 1,
                        len(audit_failures),
                        len(quality_failures),
                        len(repeated_keys),
                        reason_summary or "none",
                    )
                    if not rejected_keys:
                        break
                    if audit_round == _ACTION_AUDIT_REPAIR_ATTEMPTS:
                        unresolved = [
                            entity
                            for entity in entities
                            if entity.key in rejected_keys
                        ]
                        for entity in unresolved:
                            values[entity.key] = best_values[entity.key]
                        repetition_warnings += len(unresolved)
                        best_summary = "; ".join(
                            f"scene{entity.scene_number}:slot{entity.key[-1]}="
                            f"{','.join(best_diagnostics.get(entity.key, ())) or 'audit_reject'}"
                            for entity in unresolved
                        )
                        _LOGGER.warning(
                            "[MV Director - Timeline Planner] Action audit repair "
                            "budget exhausted; retained the lowest-violation "
                            "LLM-generated candidate AS IS; attempts=%d; slots=%s",
                            _ACTION_AUDIT_REPAIR_ATTEMPTS,
                            best_summary,
                        )
                        break
                    retry_entities = [
                        _Entity(
                            entity.scene_number,
                            entity.key,
                            {
                                **entity.value,
                                **(
                                    {
                                        "rejected_output_withheld": (
                                            "invalid_transport_wrapper"
                                            if "internal_protocol_label"
                                            in quality_failures.get(
                                                entity.key, ()
                                            )
                                            else "unexpected_priority_cue"
                                        )
                                    }
                                    if any(
                                        reason
                                        in {
                                            "unexpected_priority_cue",
                                            "internal_protocol_label",
                                        }
                                        for reason in quality_failures.get(
                                            entity.key, ()
                                        )
                                    )
                                    else {
                                        "rejected_output": values[entity.key]
                                    }
                                ),
                                "semantic_audit_reasons": list(
                                    audit_failures.get(entity.key, ())
                                ),
                                "action_quality_violations": list(
                                    quality_failures.get(entity.key, ())
                                ),
                                "action_repetition_detected": (
                                    entity.key in repeated_keys
                                ),
                            },
                        )
                        for entity in entities
                        if entity.key in rejected_keys
                    ]
                    (
                        retry_values,
                        retry_issues,
                        retry_scenes,
                        retry_missing,
                        retry_recovered,
                    ) = _request_entities(
                        backend,
                        task="actions",
                        record_type="ACTION",
                        entities=retry_entities,
                        shared={
                            "subject_roster": subject_roster,
                            "direction": performance_directions,
                            "planner_policy_contract": planner_policy_contract,
                            "primary_action_concept": lip_sync_target,
                            "subject_instance_policy": subject_instance_policy,
                            "recent_action_history": recent_action_history[-18:],
                            "retry": "semantic_audit_rejected_slots",
                            "semantic_audit_retry": (
                                "Replace the rejected Action. Resolve every listed "
                                "semantic_audit_reasons and action_quality_violations "
                                "item, and replace any action_repetition_detected "
                                "candidate without paraphrasing the same action, "
                                "target, contact, or final pose."
                            ),
                        },
                        system_prompt=system_prompts["actions"],
                        runtime_config=runtime_config,
                        interrupt_callback=interrupt_callback,
                    )
                    issues.extend(retry_issues)
                    all_retries.update(retry_scenes)
                    recovered += retry_recovered
                    if retry_missing:
                        values.update(retry_values)
                        repetition_warnings += len(retry_missing)
                        _LOGGER.warning(
                            "[MV Director - Timeline Planner] Action audit repair "
                            "response remained incomplete; retained available "
                            "LLM-generated Action text AS IS; missing=%s",
                            ",".join(
                                f"scene{scene}:slot{slot}"
                                for _kind, scene, slot in retry_missing
                            ),
                        )
                        break
                    values.update(retry_values)
            if not missing:
                final_contract_violations = _action_budget_violations(
                    entities,
                    values,
                    configured_priority_cues=configured_priority_cues,
                )
                hard_missing: list[tuple[str, int, int]] = []
                hard_labels: list[str] = []
                for entity in entities:
                    reasons = final_contract_violations.get(entity.key, ())
                    if "internal_protocol_label" in reasons:
                        kind = "ACTION_PROTOCOL"
                    elif (
                        planner_policy == "anime_emotional_mv"
                        and (
                            "missing_spatial_anchor" in reasons
                            or "missing_visible_development" in reasons
                        )
                    ):
                        kind = "ACTION_GROUNDING"
                    else:
                        continue
                    hard_missing.append(
                        (kind, entity.scene_number, entity.key[-1])
                    )
                    hard_labels.append(
                        f"scene{entity.scene_number}:slot{entity.key[-1]}="
                        f"{','.join(reasons)}"
                    )
                if hard_missing:
                    _LOGGER.error(
                        "[MV Director - Timeline Planner] Action structural "
                        "contract remained invalid after bounded retries; slots=%s",
                        ";".join(hard_labels),
                    )
                    missing = tuple(dict.fromkeys(hard_missing))
        else:
            values, issues, retries, missing = {}, [], (), ()
            recovered = repetition_warnings = 0
        all_issues.extend(issues)
        all_retries.update(retries)
        protocol_recovered_count += recovered
        action_repetition_warning_count += repetition_warnings
        if missing:
            return None, missing
        for key, text in values.items():
            action_values[key] = dialogue_filter.filter(text)
        recent_action_history.extend(
            action_values[key]
            for key in keys
            if key in action_values
            and not action_cue_scopes.get(key[0])
        )
        if keys:
            previous_action = (
                ""
                if action_cue_scopes.get(keys[-1][0])
                else action_values.get(keys[-1], previous_action)
            )

    camera_values: dict[tuple[int, ...], str] = {}
    recent_camera_history: list[str] = []
    camera_continuity_groups: dict[int, int] = {}
    continuity_group = 0
    for scene in planned_template.scenes:
        if not scene.continuation or not continuity_group:
            continuity_group = scene.scene_number
        camera_continuity_groups[scene.scene_number] = continuity_group
    chosen_arc_paths: dict[int, str] = {}
    chosen_camera_plans: dict[int, _CameraPlan] = {}
    all_shot_keys = list(planned_template.shot_keys)
    scene_action_keys = {
        scene.scene_number: [
            key for key in all_shot_keys if key[0] == scene.scene_number
        ]
        for scene in planned_template.scenes
    }
    face_cut_keys = {
        key
        for key in all_shot_keys
        if _camera_editorial_role(
            shot_context[key], lip_sync_active=lip_sync_mode != "off"
        )
        == "face_performance_cut"
    }
    face_arc_transitions = _face_arc_transitions(
        all_shot_keys,
        face_cut_keys,
        {
            key: int(shot_context[key].get("shot_duration_ms", 0))
            for key in all_shot_keys
        },
    )
    emotional_face_zoom_remaining = (
        max(
            0,
            max(1, (len(planned_template.scenes) + 7) // 8)
            - len(face_cut_keys),
        )
        if planner_policy == "anime_emotional_mv"
        else 0
    )
    for scene_batch in _chunks(list(planned_template.scenes), scenes_per_batch):
        keys = [
            key for key in planned_template.shot_keys
            if key[0] in {scene.scene_number for scene in scene_batch}
        ]
        entities = []
        for key in keys:
            cue_card = cue_cards[(key[0],)]
            action_keys = scene_action_keys[key[0]]
            action_position = action_keys.index(key)
            previous_action_key = (
                action_keys[action_position - 1] if action_position else None
            )
            next_action_key = (
                action_keys[action_position + 1]
                if action_position + 1 < len(action_keys) else None
            )
            is_reaction_shot = action_position + 1 == len(action_keys)
            has_grounded_cue = (
                cue_card.valid and cue_card.target not in _CUE_NONE_VALUES
            )
            single_prechorus_body_accent = (
                body_accent_policy in {
                    "sparse_chorus_prechorus",
                    "sparse_chorus_prechorus_verse_contact",
                }
                and key in body_accent_keys
                and _is_prechorus_scene(action_keys, shot_context)
            )
            scene_body_accent = (
                body_accent_policy == "scene_phrase"
                and key in body_accent_keys
            )
            prechorus_body_coverage = (
                ("lyric_target_and_body" if has_grounded_cue else "whole_body_emotion")
                if single_prechorus_body_accent else ""
            )
            scene_body_coverage = (
                ("lyric_target_and_body" if has_grounded_cue else "whole_body_emotion")
                if scene_body_accent else ""
            )
            required_effect_coverage = (
                "lyric_target_and_body"
                if key in body_accent_keys
                and key in scene_spine_steps
                and scene_spine_steps[key].show == "lyric_target"
                else ""
            )
            required_camera_coverage = (
                prechorus_body_coverage or scene_body_coverage
                or required_effect_coverage
                or (scene_spine_steps[key].required_coverage
                    if key in scene_spine_steps else "")
            )
            shot_count = len(action_keys)
            context = {
                **shot_context[key],
                "visual_beat": (
                    beat_values[(key[0],)]
                    if planner_policy != "anime_emotional_mv" or cue_card.valid
                    else ""
                ),
                "visual_beat_grounding": cue_card.to_dict(),
                "locked_action": action_values[key],
                "scene_spine_step": (
                    scene_spine_steps[key].to_dict()
                    if key in scene_spine_steps else {}
                ),
                "single_prechorus_body_accent": single_prechorus_body_accent,
                "body_phrase_accent": scene_body_accent,
                "entry_effect_state": _continuation_effect_state(
                    previous_scene_numbers[key[0]],
                    continuation=bool(shot_context[key]["scene_continuation"]) and key[-1] == 1,
                    last_shot_by_scene=scene_shot_counts,
                    scene_spine_steps=scene_spine_steps,
                ),
                "required_spine_coverage": required_camera_coverage,
                "previous_locked_action": (
                    action_values[previous_action_key]
                    if previous_action_key is not None
                    and is_reaction_shot
                    and previous_action_key not in face_cut_keys else ""
                ),
                "next_locked_action": (
                    action_values[next_action_key]
                    if next_action_key is not None
                    and not is_reaction_shot
                    and next_action_key not in face_cut_keys else ""
                ),
                "grounded_cue_phase": (
                    _priority_cue_phase(action_position + 1, shot_count)
                    if has_grounded_cue else ""
                ),
                "performance_phase": (
                    "complete_phrase" if shot_count == 1 else
                    "prepare_and_accent" if action_position == 0 else
                    "release_and_reaction" if action_position + 1 == shot_count
                    else "develop_accent"
                ) if performance_mode == "dance_phrase" else "",
                "camera_continuity_group": camera_continuity_groups[key[0]],
                "previous_arc_path": chosen_arc_paths.get(camera_continuity_groups[key[0]], ""),
                "previous_camera_state": (
                    {"end_scale": chosen_camera_plans[camera_continuity_groups[key[0]]].end_scale,
                     "end_view": chosen_camera_plans[camera_continuity_groups[key[0]]].end_view}
                    if camera_continuity_groups[key[0]] in chosen_camera_plans else {}
                ),
                "previous_camera_in_batch": (
                    {"scene_number": keys[keys.index(key) - 1][0], "shot_index": keys[keys.index(key) - 1][1]}
                    if keys.index(key) and camera_continuity_groups[keys[keys.index(key)-1][0]] == camera_continuity_groups[key[0]]
                    else {}
                ),
                "lip_sync_active": lip_sync_mode != "off",
                "lip_sync_target": lip_sync_target,
                "editorial_role": _camera_editorial_role(
                    shot_context[key],
                    lip_sync_active=lip_sync_mode != "off",
                ),
                "face_arc_transition": (
                    face_arc_transitions.get(key, "")
                    if required_camera_coverage not in {
                        "lyric_target", "lyric_target_and_hands",
                        "lyric_target_and_body", "face_eyes_mouth"
                    } else ""
                ),
            }
            if context["editorial_role"] == "face_performance_cut":
                camera_values[key] = (
                    ANIME_EMOTIONAL_FACE_PERFORMANCE_CUT_CAMERA
                    if planner_policy == "anime_emotional_mv"
                    else FACE_PERFORMANCE_CUT_CAMERA
                )
            else:
                entities.append(_Entity(key[0], key, context))
        if entities:
            anime_story_mv = planner_policy == "anime_story_mv"
            anime_emotional_mv = planner_policy == "anime_emotional_mv"
            emotional_transitions: dict[tuple[int, ...], str] = {}
            face_zoom_keys: set[tuple[int, ...]] = set()
            batch_has_face_cut = any(key in face_cut_keys for key in keys)
            if anime_emotional_mv:
                batch_face_target = (
                    1
                    if emotional_face_zoom_remaining > 0
                    and not batch_has_face_cut
                    else 0
                )
                (
                    long_arc_keys,
                    face_zoom_keys,
                    emotional_transitions,
                ) = _anime_emotional_mv_camera_emphasis(
                    entities,
                    face_target=batch_face_target,
                )
                emotional_face_zoom_remaining -= len(face_zoom_keys)
            else:
                long_arc_keys = (
                    _anime_story_mv_long_arc_keys(entities)
                    if anime_story_mv
                    else set()
                )
            face_zoom_key = (
                _anime_story_mv_face_zoom_key(entities, long_arc_keys)
                if anime_story_mv
                and lip_sync_mode != "off"
                and not batch_has_face_cut
                else None
            )
            if face_zoom_key is not None:
                face_zoom_keys.add(face_zoom_key)
            arc_roll_key = (
                _select_arc_roll(entities, long_arc_keys, emotional_transitions)
                if anime_emotional_mv
                and CAMERA_ARC_ROLL_POLICIES.get(direction.camera_profile_id)
                == "selective_arc"
                else None
            )
            if long_arc_keys or face_zoom_keys or anime_emotional_mv:
                entities = [
                    _Entity(
                        entity.scene_number,
                        entity.key,
                        {
                            **entity.value,
                            "face_arc_transition": (
                                emotional_transitions.get(entity.key)
                                or entity.value.get("face_arc_transition", "")
                            ),
                            "long_arc_emphasis": entity.key in long_arc_keys,
                            "arc_roll_emphasis": entity.key == arc_roll_key,
                            "long_arc_duration_fraction": "70-90%",
                            "face_zoom_emphasis": entity.key in face_zoom_keys,
                            "arc_permission": (
                                "required"
                                if entity.key in long_arc_keys
                                or bool(
                                    emotional_transitions.get(entity.key)
                                    or entity.value.get("face_arc_transition", "")
                                )
                                else "forbidden"
                                if anime_emotional_mv
                                else "available"
                            ),
                            "face_zoom_duration_fraction": (
                                "35-55%"
                                if anime_emotional_mv
                                else "70-90%"
                            ),
                            "camera_protocol": (
                                "finite_v1"
                                if anime_emotional_mv
                                else "free_text_v1"
                            ),
                        },
                    )
                    for entity in entities
                ]
            face_arc_count = sum(
                bool(entity.value.get("face_arc_transition"))
                for entity in entities
            )
            arc_required = (
                not (anime_story_mv or anime_emotional_mv)
                and face_arc_count == 0
                and not any(
                    re.search(r"(?i)\barc(?: shot)?\b", value)
                    for value in recent_camera_history[-4:]
                )
            )
            # Face handoffs and long-Arc emphasis can occupy different slots.
            # A max() of their counts falsely treats required Arcs as excess.
            arc_maximum = max(
                len({
                    entity.key for entity in entities
                    if entity.key in long_arc_keys
                    or entity.value.get("face_arc_transition")
                }),
                int(arc_required),
            )
            camera_batch_contract = {
                "camera_profile_id": direction.camera_profile_id,
                "arc_shot_maximum": arc_maximum,
                "face_arc_transition_count": face_arc_count,
                "long_arc_emphasis_count": len(long_arc_keys),
                "arc_roll_emphasis_count": int(arc_roll_key is not None),
                "long_arc_duration_fraction": "70-90%" if long_arc_keys else "none",
                "face_zoom_emphasis_count": len(face_zoom_keys),
                "tracking_shot_maximum": 1,
                "same_other_motion_type_maximum": 2,
                "same_exact_camera_plan_maximum": 1,
                "slow_speed_maximum": max(1, len(entities) // 4),
                "unrequested_lower_body_detail_maximum": 0,
            }
            camera_protocol_contract = (
                {
                    "id": "finite_v1",
                    "fields": list(_CAMERA_PLAN_FIELDS),
                    "start_scale_values": sorted(_CAMERA_PLAN_SCALES),
                    "end_scale_values": sorted(_CAMERA_PLAN_SCALES),
                    "start_view_values": sorted(_CAMERA_PLAN_VIEWS),
                    "end_view_values": sorted(_CAMERA_PLAN_VIEWS),
                    "path_values": sorted(_CAMERA_PLAN_PATHS),
                    "arc_roll_path_values": sorted(_ARC_ROLL_PATHS),
                    "coverage_values": sorted(_CAMERA_PLAN_COVERAGE),
                    "serialization": "python_owned_fixed_h3_camera_sentence",
                    "free_prose": False,
                }
                if anime_emotional_mv
                else {"id": "free_text_v1", "free_prose": True}
            )
            if anime_emotional_mv:
                _LOGGER.info(
                    "[MV Director - Timeline Planner] Camera role assignment; "
                    "scenes=%s; long_arcs=%d; arc_rolls=%d; face_zooms=%d; "
                    "arc_forbidden=%d; short_arc_ineligible=%d",
                    ",".join(str(scene.scene_number) for scene in scene_batch),
                    len(long_arc_keys),
                    int(arc_roll_key is not None),
                    len(face_zoom_keys),
                    sum(
                        entity.value.get("arc_permission") == "forbidden"
                        for entity in entities
                    ),
                    sum(
                        int(entity.value.get("shot_duration_ms", 0)) < 2500
                        for entity in entities
                    ),
                )
            (
                values,
                issues,
                retries,
                missing,
                recovered,
                repetition_warnings,
            ) = _request_distinct_entities(
                backend,
                task="cameras",
                record_type="CAMERA",
                entities=entities,
                shared={
                    "direction": camera_directions,
                    "planner_policy_contract": planner_policy_contract,
                    "subject_instance_policy": subject_instance_policy,
                    "arc_required": arc_required,
                    "camera_batch_contract": camera_batch_contract,
                    "camera_protocol_contract": camera_protocol_contract,
                    "recent_camera_history": recent_camera_history[-12:],
                },
                history=recent_camera_history,
                system_prompt=system_prompts["cameras"],
                runtime_config=runtime_config,
                interrupt_callback=interrupt_callback,
            )
            if not missing:
                budget_violations = _camera_budget_violations(
                    entities,
                    values,
                    arc_maximum=arc_maximum,
                    recent_history=recent_camera_history[-12:],
                )
                if budget_violations:
                    original_camera_values = dict(values)
                    original_camera_violations = dict(budget_violations)
                    retry_entities = [
                        _Entity(
                            entity.scene_number,
                            entity.key,
                            {
                                **entity.value,
                                "rejected_output": values[entity.key],
                                "camera_quality_violations": list(
                                    budget_violations[entity.key]
                                ),
                                "disallowed_motion_types": sorted(
                                    {
                                        reason.split(":", 1)[1]
                                        for reason in budget_violations[entity.key]
                                        if reason.startswith("motion_budget:")
                                    }
                                ),
                            },
                        )
                        for entity in entities
                        if entity.key in budget_violations
                    ]
                    (
                        retry_values,
                        retry_issues,
                        retry_scenes,
                        retry_missing,
                        retry_recovered,
                    ) = _request_entities(
                        backend,
                        task="cameras",
                        record_type="CAMERA",
                        entities=retry_entities,
                        shared={
                            "direction": camera_directions,
                            "planner_policy_contract": planner_policy_contract,
                            "subject_instance_policy": subject_instance_policy,
                            "arc_required": False,
                            "camera_batch_contract": camera_batch_contract,
                            "camera_protocol_contract": camera_protocol_contract,
                            "recent_camera_history": recent_camera_history[-12:],
                            "retry": "camera_quality_budget",
                            "camera_quality_retry": (
                                "Replace the rejected Camera choice. Obey every "
                                "listed budget and do not paraphrase the same "
                                "framing, body-region focus, path, or speed."
                            ),
                        },
                        system_prompt=system_prompts["cameras"],
                        runtime_config=runtime_config,
                        interrupt_callback=interrupt_callback,
                    )
                    issues.extend(retry_issues)
                    all_retries.update(retry_scenes)
                    recovered += retry_recovered
                    values.update(retry_values)
                    remaining_budget_violations = _camera_budget_violations(
                        entities,
                        values,
                        arc_maximum=arc_maximum,
                        recent_history=recent_camera_history[-12:],
                    )
                    hard_camera_reasons = {
                        "required_h3_motion_type",
                        "exactly_one_h3_motion_type",
                        "unassigned_arc",
                    }
                    affected_keys = (
                        set(original_camera_violations)
                        | set(remaining_budget_violations)
                    )
                    for key in affected_keys:
                        original_reasons = original_camera_violations.get(key, ())
                        retry_reasons = remaining_budget_violations.get(key, ())
                        original_score = (
                            sum(
                                reason in hard_camera_reasons
                                for reason in original_reasons
                            ),
                            len(original_reasons),
                        )
                        retry_score = (
                            sum(
                                reason in hard_camera_reasons
                                for reason in retry_reasons
                            ),
                            len(retry_reasons),
                        )
                        if original_score <= retry_score:
                            values[key] = original_camera_values[key]
                    selected_camera_violations = _camera_budget_violations(
                        entities,
                        values,
                        arc_maximum=arc_maximum,
                        recent_history=recent_camera_history[-12:],
                    )
                    repetition_warnings += len(selected_camera_violations)
                    if selected_camera_violations:
                        reason_summary = "; ".join(
                            f"scene{entity.scene_number}:slot{entity.key[-1]}="
                            f"{','.join(selected_camera_violations[entity.key])}"
                            for entity in entities
                            if entity.key in selected_camera_violations
                        )
                        _LOGGER.info(
                            "[MV Director - Timeline Planner] Camera quality "
                            "retry left profile-quality violations; retained the "
                            "lowest-violation LLM-generated candidate AS IS; "
                            "slots=%s",
                            reason_summary,
                        )
                    if retry_missing:
                        repetition_warnings += len(retry_missing)
                        _LOGGER.warning(
                            "[MV Director - Timeline Planner] Camera quality "
                            "retry response remained incomplete; retained the "
                            "existing LLM-generated Camera text AS IS; missing=%s",
                            ",".join(
                                f"scene{scene}:slot{slot}"
                                for _kind, scene, slot in retry_missing
                            ),
                        )
            if not missing and anime_emotional_mv:
                remaining_budget_violations = _camera_budget_violations(
                    entities,
                    values,
                    arc_maximum=arc_maximum,
                    recent_history=recent_camera_history[-12:],
                )
                if remaining_budget_violations:
                    _LOGGER.info(
                        "[MV Director - Timeline Planner] Camera quality "
                        "violations remained after one bounded retry; finite "
                        "structural fallback will replace those slots; count=%d",
                        len(remaining_budget_violations),
                    )
                fallback_rows: list[str] = []
                used_rendered_plans = set(recent_camera_history[-12:])
                for ordinal, entity in enumerate(entities):
                    plan, selection_violations = _select_continuous_camera_plan(
                        entity, values.get(entity.key, ""), ordinal,
                        used_rendered_plans, chosen_arc_paths,
                        remaining_budget_violations.get(entity.key, ()),
                    )
                    if selection_violations:
                        fallback_rows.append(
                            f"scene{entity.scene_number}:slot{entity.key[-1]}="
                            + ",".join(selection_violations)
                        )
                    assert plan is not None
                    if performance_mode == "dance_phrase":
                        group = int(entity.value["camera_continuity_group"])
                        index = all_shot_keys.index(entity.key)
                        previous_key = all_shot_keys[index - 1] if index else None
                        previous_plan = chosen_camera_plans.get(group)
                        if previous_key in face_cut_keys and camera_continuity_groups[previous_key[0]] == group:
                            previous_plan = _CameraPlan("Zoom In", "head_and_shoulders", "face_closeup",
                                                       "front", "front", "zoom_in_35_55", "face_eyes_mouth")
                        connected = _connect_camera_geometry(plan, previous_plan, chosen_arc_paths.get(group, ""))
                        connected_entity = _Entity(entity.scene_number, entity.key, {
                            **entity.value,
                            "previous_arc_path": chosen_arc_paths.get(group, ""),
                        })
                        if _camera_plan_contract_violations(connected_entity, connected):
                            connected = _connect_camera_geometry(
                                _fallback_camera_plan(connected_entity, ordinal),
                                previous_plan,
                                chosen_arc_paths.get(group, ""),
                            )
                            _LOGGER.info(
                                "[MV Director - Timeline Planner] Camera geometry "
                                "fallback after continuity connection; scene=%d; shot=%d",
                                entity.scene_number, entity.key[-1],
                            )
                        if connected != plan:
                            _LOGGER.info("[MV Director - Timeline Planner] Camera continuity geometry connected; scene=%d; shot=%d; start=%s/%s",
                                         entity.scene_number, entity.key[-1], connected.start_scale, connected.start_view)
                        plan = connected
                        if _camera_motion_type(plan.motion) == "Arc Shot":
                            chosen_arc_paths[group] = _arc_base_path(plan.path)
                    chosen_camera_plans[int(entity.value["camera_continuity_group"])] = plan
                    rendered_plan = _render_camera_plan(
                        plan, style=camera_render_style
                    )
                    values[entity.key] = rendered_plan
                    used_rendered_plans.add(rendered_plan)
                if fallback_rows:
                    _LOGGER.info(
                        "[MV Director - Timeline Planner] Camera finite protocol "
                        "fallback applied; slots=%s",
                        ";".join(fallback_rows),
                    )
                repeated_entities, _ = _repeated_entities(
                    entities, values, recent_camera_history
                )
                if repeated_entities:
                    _LOGGER.info(
                        "[MV Director - Timeline Planner] Camera repetition "
                        "remained after bounded diversity retries; retained "
                        "LLM-generated text AS IS; count=%d",
                        len(repeated_entities),
                    )
        else:
            values, issues, retries, missing = {}, [], (), ()
            recovered = repetition_warnings = 0
        all_issues.extend(issues)
        all_retries.update(retries)
        protocol_recovered_count += recovered
        camera_repetition_warning_count += repetition_warnings
        if missing:
            return None, missing
        camera_values.update(
            {key: dialogue_filter.filter(text) for key, text in values.items()}
        )
        recent_camera_history.extend(
            camera_values[key] for key in keys if key in camera_values
        )

    empty_shots = [
        key
        for key in planned_template.shot_keys
        if not action_values.get(key, "")
        and not camera_values.get(key, "")
        and not shot_context[key]["author_body"]
    ]
    if empty_shots:
        return None, tuple(("FILTERED", scene, shot) for scene, shot in empty_shots)

    content = PlannerContent(
        visual_beats=tuple(
            (key[0], value) for key, value in sorted(beat_values.items())
        ),
        song_direction=song_direction,
        shot_layouts=tuple(sorted(layouts.items())),
        scene_continuations=tuple(sorted(continuations.items())),
        actions=tuple((key[0], key[1], value) for key, value in sorted(action_values.items())),
        cameras=tuple((key[0], key[1], value) for key, value in sorted(camera_values.items())),
        issue_count=(
            len(all_issues)
            + len(layout_repaired_scenes)
            + len(layout_fallback_scenes)
            + (1 if layout_mix_retry else 0)
            + (1 if song_direction_fallback else 0)
        ),
        retried_scenes=tuple(sorted(all_retries)),
        removed_generated_dialogue_count=dialogue_filter.removed_count,
        unused_protected_dialogue_ids=dialogue_filter.unused_ids,
        layout_repaired_scenes=tuple(layout_repaired_scenes),
        layout_fallback_scenes=tuple(layout_fallback_scenes),
        layout_mix_retry=layout_mix_retry,
        protocol_recovered_count=protocol_recovered_count,
        repetition_warning_count=(
            beat_repetition_warning_count
            + action_repetition_warning_count
            + camera_repetition_warning_count
        ),
        beat_repetition_warning_count=beat_repetition_warning_count,
        action_repetition_warning_count=action_repetition_warning_count,
        camera_repetition_warning_count=camera_repetition_warning_count,
        song_direction_fallback=song_direction_fallback,
        scene_spine_steps=tuple(
            (key[0], key[1], text) for key, text in sorted(scene_spine_raw.items())
        ),
        scene_spine_skipped_scenes=tuple(scene_spine_skipped),
    )
    return content, ()


def render_planner_content(
    *,
    content: PlannerContent,
    concept_emd: str,
    template: PlannerTemplate,
    direction: DirectionArtifact,
    lip_sync_mode: str,
    lip_sync_target: str,
    lip_sync_audio_slot: int,
    scene_emd: str = "",
) -> EMDTextArtifact:
    if content.typed_output:
        planned_template = template
    else:
        planned_template = apply_shot_layouts(
            template,
            {scene: starts for scene, starts in content.shot_layouts},
        )
        planned_template = apply_scene_continuations(
            planned_template,
            {scene: value for scene, value in content.scene_continuations},
        )
    return render_completed_emd(
        concept_emd=concept_emd,
        scene_emd=scene_emd,
        template=planned_template,
        direction=direction,
        actions={(scene, shot): text for scene, shot, text in content.actions},
        cameras={(scene, shot): text for scene, shot, text in content.cameras},
        events={(scene, shot): text for scene, shot, text in content.events},
        typed_output=content.typed_output,
        motion_compositions={(s, shot): (source, index, text)
                             for s, shot, source, index, text in content.motion_compositions},
        lip_sync_mode=lip_sync_mode,
        lip_sync_target=lip_sync_target,
        lip_sync_audio_slot=lip_sync_audio_slot,
    )


def plan_timeline(
    backend: TimelinePlannerBackend,
    *,
    template_emd: str,
    concept_emd: str,
    direction: DirectionArtifact | None,
    lip_sync_mode: str,
    lip_sync_target: str,
    lip_sync_audio_slot: int,
    scenes_per_batch: int,
    system_prompts: Mapping[str, str],
    runtime_config: LlamaRuntimeConfig,
    scene_emd: str = "",
    staging_candidate_policy: str = "optional",
    interrupt_callback: Any = None,
) -> TimelinePlannerResult:
    template = parse_template_emd(template_emd)
    concept = normalize_concept_emd(concept_emd)
    scene = normalize_scene_emd(scene_emd)
    selected_direction = direction or DirectionArtifact()
    content, missing = generate_planner_content(
        backend,
        template=template,
        concept_emd=concept,
        scene_emd=scene,
        direction=selected_direction,
        lip_sync_mode=lip_sync_mode,
        lip_sync_target=lip_sync_target,
        scenes_per_batch=scenes_per_batch,
        system_prompts=system_prompts,
        runtime_config=runtime_config,
        staging_candidate_policy=staging_candidate_policy,
        interrupt_callback=interrupt_callback,
    )
    if content is None:
        return TimelinePlannerResult(
            EMDTextArtifact.create("MVD_EMD_TEMPLATE_V1", template_emd),
            None,
            False,
            missing,
        )
    emd = render_planner_content(
        content=content,
        concept_emd=concept,
        scene_emd=scene,
        template=template,
        direction=selected_direction,
        lip_sync_mode=lip_sync_mode,
        lip_sync_target=lip_sync_target,
        lip_sync_audio_slot=lip_sync_audio_slot,
    )
    return TimelinePlannerResult(emd, content, True, ())
