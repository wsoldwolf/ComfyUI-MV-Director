"""Scene Author result and transport contracts."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping, Protocol

from ..artifacts import EMDTextArtifact
from ..inference import LlamaRuntimeConfig


class TimelinePlannerBackend(Protocol):
    def complete_planner(
        self, *, task: str, system_prompt: str, payload: str,
        config: LlamaRuntimeConfig, interrupt_callback: Any = None,
    ) -> str:
        ...


@dataclass(frozen=True, slots=True)
class PlannerContent:
    actions: tuple[tuple[int, int, str], ...]
    cameras: tuple[tuple[int, int, str], ...]
    issue_count: int
    retried_scenes: tuple[int, ...]
    protocol_recovered_count: int = 0
    events: tuple[tuple[int, int, str], ...] = ()
    motion_compositions: tuple[tuple[int, int, str, int, str], ...] = ()
    terminal_states: tuple[tuple[int, str, str, str], ...] = ()

    @property
    def typed_output(self) -> bool:
        return True

    def to_dict(self) -> dict[str, object]:
        return {
            "schema": "MVD_SCENE_AUTHOR_CONTENT_V1",
            "actions": [list(row) for row in self.actions],
            "cameras": [list(row) for row in self.cameras],
            "events": [list(row) for row in self.events],
            "issue_count": self.issue_count,
            "retried_scenes": list(self.retried_scenes),
            "protocol_recovered_count": self.protocol_recovered_count,
            "motion_compositions": [list(row) for row in self.motion_compositions],
            "terminal_states": [list(row) for row in self.terminal_states],
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "PlannerContent":
        if value.get("schema") != "MVD_SCENE_AUTHOR_CONTENT_V1":
            raise ValueError("obsolete Planner cache schema; regenerate with Scene Author")
        def records(key: str) -> tuple[tuple[int, int, str], ...]:
            return tuple((int(row[0]), int(row[1]), str(row[2])) for row in value[key])
        return cls(
            actions=records("actions"), cameras=records("cameras"), events=records("events"),
            issue_count=int(value["issue_count"]),
            retried_scenes=tuple(int(item) for item in value["retried_scenes"]),
            protocol_recovered_count=int(value["protocol_recovered_count"]),
            motion_compositions=tuple(
                (int(r[0]), int(r[1]), str(r[2]), int(r[3]), str(r[4]))
                for r in value["motion_compositions"]),
            terminal_states=tuple(
                (int(r[0]), str(r[1]), str(r[2]), str(r[3]))
                for r in value["terminal_states"]),
        )


@dataclass(frozen=True, slots=True)
class TimelinePlannerResult:
    emd: EMDTextArtifact
    content: PlannerContent | None
    complete: bool
    missing: tuple[tuple[str, int, int], ...]


@dataclass(frozen=True, slots=True)
class PlannerEntity:
    scene_number: int
    key: tuple[int, ...]
    value: dict[str, object]
