"""Deterministic EMD-to-Context-Loop Ref2VA compiler."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from core.artifacts.base import canonical_json
from core.artifacts.references import (
    RequiredReference,
    RequiredReferencesArtifact,
)
from core.emd import EMDDocument, parse_emd
from core.emd.ast import AudioDirective, Scene, Shot, Subject
from core.h3_contract import DEFAULT_H3_TIMING_PROFILE, H3TimingProfile

from .protection import protect_unit
from .translator import PromptTranslator, translate_exact


@dataclass(frozen=True, slots=True)
class CompileResult:
    plan: dict[str, Any]
    required_references: RequiredReferencesArtifact

    def plan_json(self) -> str:
        return canonical_json(self.plan)


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
            if subject.name is not None:
                add(f"subject.{subject_index}.name", subject.name)
            for index, text in enumerate(subject.descriptions):
                add(f"subject.{subject_index}.description.{index}", text)
        for index, text in enumerate(self.document.retention):
            add(f"retention.{index}", text)
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
        translated = translate_exact(self.translator, [item.text for item in protected])
        self._values = {
            key: item.restore(value)
            for key, item, value in zip(keys, protected, translated)
        }

    def get(self, key: str) -> str:
        return self._values[key]


def _subject_definition(
    subject: Subject, index: int, translations: _TranslationTable
) -> list[str]:
    name = (
        translations.get(f"subject.{index}.name")
        if subject.name is not None
        else None
    )
    descriptions = [
        translations.get(f"subject.{index}.description.{item_index}")
        for item_index in range(len(subject.descriptions))
    ]
    description = " ".join(descriptions)
    noun = name or subject.concept_type
    if subject.picture_ref is not None:
        return [
            f"{subject.picture_ref} is the connected visual reference for {noun}.",
            f"{subject.subject_ref} is the {subject.concept_type} defined by "
            f"{subject.picture_ref}, described here: {description}",
        ]
    return [
        f"{subject.subject_ref} is the {subject.concept_type} described here: {description}"
    ]


def _retention_lines(
    document: EMDDocument, translations: _TranslationTable
) -> list[str]:
    if document.retention:
        return [
            translations.get(f"retention.{index}")
            for index in range(len(document.retention))
        ]
    lines: list[str] = []
    for subject in document.subjects:
        if subject.picture_ref is not None:
            lines.extend(
                [
                    f"{subject.picture_ref}: fully_preserved - use the connected image "
                    "as the visual identity reference.",
                    f"{subject.subject_ref}: fully_preserved - preserve the identity and "
                    f"described attributes from {subject.picture_ref}.",
                ]
            )
        else:
            lines.append(
                f"{subject.subject_ref}: fully_preserved - preserve the described "
                "identity and attributes across shots."
            )
    return lines


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

    summary = scene_lines[0] if scene_lines else translations.get(
        f"scene.{scene_index}.shot.0.body.0"
    )
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
    for subject in document.subjects:
        if subject.picture_ref is None:
            continue
        slot = int(subject.picture_ref.removeprefix("<Picture ").removesuffix(">"))
        references.append(
            RequiredReference(
                concept_id=subject.concept_id,
                subject_ref=subject.subject_ref,
                h3_ref=subject.picture_ref,
                required_input=f"ref_images.ref_image_{slot - 1}",
                purpose="visual_identity",
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
    steps: int = 20,
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
        translations.get(f"common.{section}.{index}")
        for section, values in document.common_prompt
        for index in range(len(values))
    ]
    if prefix:
        plan["prompt_prefix"] = prefix
    for index, scene in enumerate(document.scenes):
        prompt, audio_fields = _scene_prompt(
            document, scene, index, translations
        )
        scene_plan: dict[str, Any] = {
            "id": f"scene_{scene.scene_number:04d}",
            "length": scene.h3_length,
            "prompt": prompt,
            "context_length": (
                timing_profile.first_scene_context_length
                if index == 0
                else timing_profile.continuation_context_length
            ),
            "audio_context_length": timing_profile.audio_context_length,
        }
        scene_plan.update(audio_fields)
        plan["shots"].append(scene_plan)
    return CompileResult(plan, _required_references(document))
