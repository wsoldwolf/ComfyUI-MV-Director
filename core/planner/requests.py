"""Planner line-protocol requests and bounded transport recovery.

Transport recovery is shared by Scene Author stages and independent of
the creative meaning of the generated prose.
"""

from __future__ import annotations

import json
import logging
import re
from typing import Any, Mapping

from ..artifacts import canonical_json, normalize_newlines
from ..inference import LlamaRuntimeConfig
from ..protocols import LLMRecordIssue, parse_llm_records
from .request_budget import complete_with_context_recovery
from .text_normalization import strip_generated_line_continuation
from .types import PlannerEntity, TimelinePlannerBackend

_LOGGER = logging.getLogger("mv_director.nodes")

def normalize_record_response(response: str, record_type: str) -> str:
    """Normalize transport spelling without changing slots or generated prose."""

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


def request_entities(
    backend: TimelinePlannerBackend,
    *,
    task: str,
    record_type: str,
    entities: list[PlannerEntity],
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
        normalize_record_response(response, record_type),
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
            normalize_record_response(retry_response, record_type),
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
            normalize_record_response(isolated_response, record_type),
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
