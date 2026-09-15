"""Parser for MVD_LLM_RECORDS_V1."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Mapping

from core.artifacts.base import normalize_newlines, sha256_text


PROTOCOL_ID = "MVD_LLM_RECORDS_V1"
ISSUE_REASONS = frozenset(
    {
        "field_count",
        "unknown_type",
        "invalid_slot",
        "unknown_slot",
        "empty_text",
        "duplicate",
    }
)


class ProtocolError(ValueError):
    """The parser invocation or whole response is invalid."""


@dataclass(frozen=True, slots=True)
class LLMRecord:
    record_type: str
    slot: int
    text: str
    line_number: int

    def to_dict(self) -> dict[str, object]:
        return {
            "record_type": self.record_type,
            "slot": self.slot,
            "text": self.text,
            "line_number": self.line_number,
        }


@dataclass(frozen=True, slots=True)
class LLMRecordIssue:
    line_number: int
    reason: str
    raw_sha256: str

    def __post_init__(self) -> None:
        if self.reason not in ISSUE_REASONS:
            raise ProtocolError(f"unsupported issue reason: {self.reason}")

    def to_dict(self) -> dict[str, object]:
        return {
            "line_number": self.line_number,
            "reason": self.reason,
            "raw_sha256": self.raw_sha256,
        }


@dataclass(frozen=True, slots=True)
class LLMRecordParseResult:
    records: tuple[LLMRecord, ...]
    issues: tuple[LLMRecordIssue, ...]
    missing: tuple[tuple[str, int], ...]
    protocol: str = PROTOCOL_ID

    def to_dict(self) -> dict[str, object]:
        return {
            "protocol": self.protocol,
            "records": [record.to_dict() for record in self.records],
            "issues": [issue.to_dict() for issue in self.issues],
            "missing": [list(key) for key in self.missing],
        }


def _validate_configuration(
    allowed_slots: Mapping[str, set[int] | frozenset[int]],
    required: set[tuple[str, int]] | frozenset[tuple[str, int]],
) -> None:
    if not allowed_slots:
        raise ProtocolError("allowed_slots must not be empty")
    for record_type, slots in allowed_slots.items():
        if (
            not isinstance(record_type, str)
            or not record_type
            or record_type != record_type.upper()
            or not record_type.isascii()
        ):
            raise ProtocolError(f"invalid record type: {record_type!r}")
        if not isinstance(slots, (set, frozenset)) or not slots:
            raise ProtocolError(f"slots for {record_type} must be a non-empty set")
        if any(not isinstance(slot, int) or isinstance(slot, bool) or slot < 1 for slot in slots):
            raise ProtocolError(f"slots for {record_type} must be positive integers")
    allowed_keys = {
        (record_type, slot)
        for record_type, slots in allowed_slots.items()
        for slot in slots
    }
    if not required <= allowed_keys:
        raise ProtocolError("required keys must be included in allowed_slots")


def parse_llm_records(
    response: str,
    *,
    allowed_slots: Mapping[str, set[int] | frozenset[int]],
    required: set[tuple[str, int]] | frozenset[tuple[str, int]],
) -> LLMRecordParseResult:
    """Parse valid records while retaining deterministic issues.

    The function never performs retries and never discards a valid record
    because another physical line is malformed.
    """

    if not isinstance(response, str):
        raise ProtocolError("response must be a string")
    if "\x00" in response:
        raise ProtocolError("response must not contain NUL")
    _validate_configuration(allowed_slots, required)

    records: list[LLMRecord] = []
    issues: list[LLMRecordIssue] = []
    seen: set[tuple[str, int]] = set()

    for line_number, raw_line in enumerate(normalize_newlines(response).split("\n"), 1):
        stripped = raw_line.strip()
        if not stripped or stripped in {"```", "```text"}:
            continue

        fields = raw_line.split("\t", 2)
        if len(fields) != 3:
            issues.append(
                LLMRecordIssue(line_number, "field_count", sha256_text(raw_line))
            )
            continue

        record_type, slot_text, text = fields
        if record_type not in allowed_slots:
            issues.append(
                LLMRecordIssue(line_number, "unknown_type", sha256_text(raw_line))
            )
            continue
        if not slot_text.isascii() or not slot_text.isdecimal():
            issues.append(
                LLMRecordIssue(line_number, "invalid_slot", sha256_text(raw_line))
            )
            continue
        slot = int(slot_text)
        if slot < 1:
            issues.append(
                LLMRecordIssue(line_number, "invalid_slot", sha256_text(raw_line))
            )
            continue
        if slot not in allowed_slots[record_type]:
            issues.append(
                LLMRecordIssue(line_number, "unknown_slot", sha256_text(raw_line))
            )
            continue

        normalized_text = text.replace("\t", " ").strip()
        if not normalized_text:
            issues.append(
                LLMRecordIssue(line_number, "empty_text", sha256_text(raw_line))
            )
            continue

        key = (record_type, slot)
        if key in seen:
            issues.append(
                LLMRecordIssue(line_number, "duplicate", sha256_text(raw_line))
            )
            continue
        seen.add(key)
        records.append(LLMRecord(record_type, slot, normalized_text, line_number))

    missing = tuple(sorted(required - seen))
    return LLMRecordParseResult(tuple(records), tuple(issues), missing)

