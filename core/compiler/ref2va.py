"""Deterministic EMD-to-Context-Loop Ref2VA compiler."""

from __future__ import annotations

from dataclasses import dataclass
import json
import re
from typing import Any

from ..artifacts.references import (
    RequiredReference,
    RequiredReferencesArtifact,
)
from ..emd import EMDDocument, parse_emd
from ..emd.ast import AudioDirective, Scene, Shot, Subject
from ..h3_contract import (
    DEFAULT_H3_TIMING_PROFILE,
    H3TimingProfile,
    build_environment_definition,
    build_environment_retention,
)

from .protection import protect_unit
from .translator import PromptTranslator, translate_exact


_TRANSLATION_REQUIRED_RE = re.compile(
    r"[\u3040-\u30ff\u3400-\u9fff\uac00-\ud7af]"
)


@dataclass(frozen=True, slots=True)
class CompileResult:
    plan: dict[str, Any]
    required_references: RequiredReferencesArtifact

    def plan_json(self) -> str:
        return json.dumps(
            self.plan,
            ensure_ascii=False,
            sort_keys=True,
            indent=2,
            allow_nan=False,
        ) + "\n"


def format_time_ms(value: int) -> str:
    minutes, remainder = divmod(value, 60_000)
    seconds, millis = divmod(remainder, 1_000)
    return f"{minutes:02d}:{seconds:02d}.{millis:03d}"


class _TranslationTable:
    def __init__(self, document: EMDDocument, translator: PromptTranslator) -> None:
        self.document = document
        self.translator = translator
        self._values: dict[str, str] = {}

    def build(self) -> None:
        units: list[str] = []
        keys: list[str] = []

        def add(key: str, text: str) -> None:
            keys.append(key)
            units.append(text)

        for subject_index, subject in enumerate(self.document.subjects):
            add(f"subject.{subject_index}.description", subject.description)
        if self.document.scene_setting is not None:
            for index, text in enumerate(self.document.scene_setting.environment):
                add(f"scene_setting.environment.{index}", text)
            for index, text in enumerate(self.document.scene_setting.time_lighting):
                add(f"scene_setting.time_lighting.{index}", text)
        for index, directive in enumerate(self.document.retention):
            add(f"retention.{index}.description", directive.description)
        for section, values in self.document.common_prompt:
            for index, text in enumerate(values):
                add(f"common.{section}.{index}", text)
        for scene_index, scene in enumerate(self.document.scenes):
            for index, text in enumerate(scene.descriptions):
                add(f"scene.{scene_index}.description.{index}", text)
            for shot_index, shot in enumerate(scene.shots):
                for index, text in enumerate(shot.body):
                    add(f"scene.{scene_index}.shot.{shot_index}.body.{index}", text)

        protected = [protect_unit(text, self.document.subjects) for text in units]
        fragment_locations: list[tuple[int, int]] = []
        fragment_units: list[str] = []
        for unit_index, item in enumerate(protected):
            for fragment_index, fragment in enumerate(item.fragments):
                if _TRANSLATION_REQUIRED_RE.search(fragment):
                    fragment_locations.append((unit_index, fragment_index))
                    fragment_units.append(fragment)
        translated = translate_exact(
            self.translator,
            fragment_units,
        )
        translated_fragments: dict[int, dict[int, str]] = {}
        for (unit_index, fragment_index), text in zip(
            fragment_locations, translated
        ):
            translated_fragments.setdefault(unit_index, {})[fragment_index] = text
        self._values = {
            key: item.restore(translated_fragments.get(index))
            for index, (key, item) in enumerate(zip(keys, protected))
        }

    def get(self, key: str) -> str:
        return self._values[key]


def _subject_definition(
    subject: Subject, index: int, translations: _TranslationTable
) -> list[str]:
    description = translations.get(f"subject.{index}.description")
    singleton = (
        " Render exactly one physical instance of this Subject, with one head "
        "and one body. Never show a duplicate, twin, clone, reflection, "
        "background lookalike, inset view, split-screen copy, or second "
        "representation of this Subject."
    )
    if not subject.references:
        return [
            f"{subject.subject_ref} is described here: {description}{singleton}"
        ]
    separator = (
        ""
        if description.rstrip().endswith((".", "!", "?", "。", "！", "？"))
        else "."
    )
    references = ", ".join(subject.references)
    has_visual_reference = any(
        reference.startswith(("<Picture ", "<Video "))
        for reference in subject.references
    )
    composition_contract = (
        " The reference is identity evidence, not a storyboard, montage, or "
        "layout template. Render one unified full-frame continuous camera view "
        "that fills the entire image. Never create an internal border, seam, "
        "divider, panel, inset, picture-in-picture, side-by-side view, or "
        "simultaneous alternate angle. If the reference contains multiple views, "
        "fuse only compatible identity features into this one view. Camera angle "
        "and framing changes must happen over time or at a scene cut, never "
        "simultaneously within one frame. The current Scene environment and "
        "time-lighting directions are the sole authority for the rendered world "
        "and fully replace every background and illumination visible inside this "
        "identity reference. "
        "Treat any blank or white studio field, daylight, backdrop, panel-specific "
        "setting, or other conflicting reference environment as non-renderable "
        "source residue. Continue the specified Scene environment across the "
        "entire frame, including behind and around the Subject. Generate a newly "
        "staged Shot from the current action and camera instructions. The first "
        "output frame must already use the new Shot-specific body pose, gaze, "
        "blocking, framing, viewpoint, camera height, and camera distance. Never "
        "show, reconstruct, paste, hold, or transition from the reference image "
        "itself as a frame, still, plate, poster, inset, background, or composition. "
        "Keep visible skin and clothing clean and intact unless an author-written "
        "Shot explicitly requires a physical condition. Lyric text inside <d> is "
        "vocal content only: figurative words about wounds, scars, pain, blood, or "
        "a broken heart never authorize a visible cut, scar, bruise, bleeding, "
        "bandage, lesion, stain, tattoo-like mark, torn skin, or damaged clothing."
        if has_visual_reference
        else ""
    )
    return [
        f"{subject.subject_ref} is described here: {description.rstrip()}{separator} "
        "Every explicitly described local shape, count, placement, scale, color, "
        "material, and exclusion is a literal identity constraint. Never normalize "
        "an unusual facial, anatomical, garment, or accessory feature into a "
        "conventional default. "
        f"Use these connected references only for its visual identity and design: "
        f"{references}. Treat every panel or alternate view as identity material "
        f"for the same single physical instance.{singleton} Do not copy a "
        "reference pose, framing, composition, panel layout, or background; "
        f"follow the current Shot instead.{composition_contract}"
    ]


def _retention_lines(
    document: EMDDocument, translations: _TranslationTable
) -> list[str]:
    lines: list[str] = []
    if document.retention:
        subject_refs = {
            subject.concept_id: subject.subject_ref for subject in document.subjects
        }
        lines.extend(
            f"{subject_refs[directive.concept_id]}: {directive.mode} - "
            f"{translations.get(f'retention.{index}.description')}"
            for index, directive in enumerate(document.retention)
        )
    else:
        for subject in document.subjects:
            lines.append(
                f"{subject.subject_ref}: fully_preserved - preserve the described "
                "identity and attributes across shots. Preserve every stated local "
                "shape, count, placement, scale, color, material, and exclusion "
                "literally; never replace an unusual feature with a conventional default."
            )
    if document.scene_setting is not None and document.scene_setting.picture_ref:
        lines.append(build_environment_retention(document.scene_setting.picture_ref))
    return lines


def _environment_description(
    document: EMDDocument, translations: _TranslationTable
) -> str:
    setting = document.scene_setting
    if setting is None:
        return ""
    parts = [
        translations.get(f"scene_setting.environment.{index}")
        for index in range(len(setting.environment))
    ]
    parts.extend(
        translations.get(f"scene_setting.time_lighting.{index}")
        for index in range(len(setting.time_lighting))
    )
    return " ".join(value.strip() for value in parts if value.strip())


def _shot_marker(scene: Scene, shot: Shot, index: int) -> str:
    if index == 0:
        return "[Shot 1]"
    relative = shot.start_ms - scene.start_ms
    return f"[Shot {index + 1}] At {format_time_ms(relative)},"


def _target_ref(document: EMDDocument, concept_id: str) -> str:
    for subject in document.subjects:
        if subject.concept_id == concept_id:
            return subject.subject_ref
    return f"`{concept_id}`"


def _audio_prompt(
    document: EMDDocument, directives: tuple[AudioDirective, ...]
) -> tuple[list[str], str, dict[str, str]]:
    soundscape: list[str] = []
    music = "No additional non-diegetic music is requested."
    fields: dict[str, str] = {}
    if not directives:
        return ["No scene-specific soundscape instruction is provided."], music, fields
    for directive in directives:
        if directive.mode == "context_loop":
            target = _target_ref(document, directive.target_concept_id or "")
            soundscape.append(
                f"Use the locked source vocal as the lip-sync timing target for {target}."
            )
            fields.update(
                source_reference="off",
                generated_continuity="off",
                source_audio_target="locked",
            )
        elif directive.mode == "audio_reference":
            target = _target_ref(document, directive.target_concept_id or "")
            soundscape.append(
                f"{target} performs visible lip movements synchronized to "
                f"<Audio {directive.audio_slot}>."
            )
        elif directive.mode == "explicit_dialogue_only":
            soundscape.append(
                "Do not add speech beyond dialogue explicitly provided with d tags."
            )
        elif directive.mode == "silence":
            soundscape.append(
                "Complete silence. No speech, music, ambience, or sound effects."
            )
            music = "No non-diegetic music."
            fields.update(
                source_reference="off",
                generated_continuity="off",
                source_audio_target="off",
            )
    return soundscape, music, fields


def _scene_prompt(
    document: EMDDocument,
    scene: Scene,
    scene_index: int,
    translations: _TranslationTable,
) -> tuple[list[str], dict[str, str]]:
    subject_lines: list[str] = []
    for subject_index, subject in enumerate(document.subjects):
        subject_lines.extend(_subject_definition(subject, subject_index, translations))
    if document.scene_setting is not None and document.scene_setting.picture_ref:
        subject_lines.append(
            build_environment_definition(
                document.scene_setting.picture_ref,
                _environment_description(document, translations),
            )
        )

    scene_lines = [
        translations.get(f"scene.{scene_index}.description.{index}")
        for index in range(len(scene.descriptions))
    ]
    shot_lines: list[str] = []
    for shot_index, shot in enumerate(scene.shots):
        marker = _shot_marker(scene, shot, shot_index)
        bodies = [
            translations.get(f"scene.{scene_index}.shot.{shot_index}.body.{index}")
            for index in range(len(shot.body))
        ]
        parts = list(bodies)
        for concept_id, lyric in shot.lyric_lip_sync:
            target = _target_ref(document, concept_id)
            parts.append(
                f"{target} performs visible lip movements to "
                f"<d>[Japanese]{lyric}</d>."
            )
        shot_lines.append(f"{marker} {' '.join(parts)}")

    summary_body = scene_lines[0] if scene_lines else translations.get(
        f"scene.{scene_index}.shot.0.body.0"
    )
    summary = summary_body.strip()
    if not summary.startswith("[reference generation]"):
        summary = f"[reference generation] {summary}"
    soundscape, music, audio_fields = _audio_prompt(
        document, scene.audio_directives
    )
    prompt: list[str] = []
    sections = (
        ("subject_definitions:", subject_lines),
        ("summary:", [summary]),
        ("retention_analysis:", _retention_lines(document, translations)),
        ("detailed_description:", scene_lines + shot_lines),
        ("overall_soundscape:", soundscape),
        ("non_diegetic_music:", [music]),
    )
    for section_index, (heading, values) in enumerate(sections):
        if section_index:
            prompt.append("")
        prompt.append(heading)
        prompt.extend(values)
    return prompt, audio_fields


def _required_references(document: EMDDocument) -> RequiredReferencesArtifact:
    references: list[RequiredReference] = []
    if document.scene_setting is not None and document.scene_setting.picture_ref:
        h3_ref = document.scene_setting.picture_ref
        slot = int(h3_ref.removeprefix("<Picture ").removesuffix(">"))
        references.append(
            RequiredReference(
                concept_id=None,
                subject_ref=None,
                h3_ref=h3_ref,
                required_input=f"ref_images.ref_image_{slot - 1}",
                purpose="environment_reference",
            )
        )
    for subject in document.subjects:
        for h3_ref in subject.references:
            if h3_ref.startswith("<Picture "):
                slot = int(h3_ref.removeprefix("<Picture ").removesuffix(">"))
                required_input = f"ref_images.ref_image_{slot - 1}"
                purpose = "visual_identity"
            elif h3_ref.startswith("<Video "):
                slot = int(h3_ref.removeprefix("<Video ").removesuffix(">"))
                required_input = f"ref_videos.ref_video_{slot - 1}"
                purpose = "motion_reference"
            else:
                slot = int(h3_ref.removeprefix("<Audio ").removesuffix(">"))
                required_input = f"ref_audios.ref_audio_{slot - 1}"
                purpose = "subject_audio_reference"
            references.append(
                RequiredReference(
                    concept_id=subject.concept_id,
                    subject_ref=subject.subject_ref,
                    h3_ref=h3_ref,
                    required_input=required_input,
                    purpose=purpose,
                )
            )
    for scene in document.scenes:
        for directive in scene.audio_directives:
            if directive.mode != "audio_reference":
                continue
            subject = next(
                item
                for item in document.subjects
                if item.concept_id == directive.target_concept_id
            )
            slot = directive.audio_slot or 0
            candidate = RequiredReference(
                concept_id=subject.concept_id,
                subject_ref=subject.subject_ref,
                h3_ref=f"<Audio {slot}>",
                required_input=f"ref_audios.ref_audio_{slot - 1}",
                purpose="lip_sync_audio_reference",
            )
            if candidate not in references:
                references.append(candidate)
    artifact = RequiredReferencesArtifact(tuple(references))
    artifact.validate()
    return artifact


def compile_ref2va(
    source: str,
    translator: PromptTranslator,
    *,
    steps: int = 8,
    timing_profile: H3TimingProfile = DEFAULT_H3_TIMING_PROFILE,
) -> CompileResult:
    if not isinstance(steps, int) or isinstance(steps, bool) or steps < 1:
        raise ValueError("steps must be a positive integer")
    timing_profile.validate()
    document = parse_emd(source, timing_profile=timing_profile)
    translations = _TranslationTable(document, translator)
    translations.build()

    plan: dict[str, Any] = {"defaults": {"steps": steps}, "shots": []}
    prefix = [
        translations.get(f"scene_setting.environment.{index}")
        for index in range(
            len(document.scene_setting.environment)
            if document.scene_setting is not None
            else 0
        )
    ]
    prefix.extend(
        translations.get(f"scene_setting.time_lighting.{index}")
        for index in range(
            len(document.scene_setting.time_lighting)
            if document.scene_setting is not None
            else 0
        )
    )
    prefix.extend(
        translations.get(f"common.{section}.{index}")
        for section, values in document.common_prompt
        for index in range(len(values))
    )
    if prefix:
        plan["prompt_prefix"] = prefix
    for index, scene in enumerate(document.scenes):
        prompt, audio_fields = _scene_prompt(
            document, scene, index, translations
        )
        continuation = index > 0 and scene.continuation
        scene_plan: dict[str, Any] = {
            "id": f"scene_{scene.scene_number:04d}",
            "length": scene.h3_length,
            "prompt": prompt,
            "context_length": (
                timing_profile.continuation_context_length
                if continuation
                else 0
            ),
            "audio_context_length": (
                timing_profile.audio_context_length if continuation else 0
            ),
        }
        if continuation:
            scene_plan["continuation_mode"] = "guide"
        scene_plan.update(audio_fields)
        plan["shots"].append(scene_plan)
    return CompileResult(plan, _required_references(document))
