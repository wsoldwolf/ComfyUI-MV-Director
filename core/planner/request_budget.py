"""Bound every Planner request, including quality and missing-record retries."""

from __future__ import annotations

import json
import logging
from typing import Any

from ..artifacts import canonical_json
from ..inference import ContextBudgetError, LlamaRuntimeConfig
from .section_context import reduce_section_context


_LOGGER = logging.getLogger("mv_director.nodes")
# Only optional copies of previous outputs are expendable. Direction, current
# lyrics, locked Action, retry reasons and previous_arc_path are never removed.
_OPTIONAL_HISTORIES = (
    "recent_camera_history", "recent_action_history",
    "recent_visual_beat_history", "forbidden_recent_outputs",
)


def complete_with_context_recovery(
    backend: Any,
    *,
    task: str,
    system_prompt: str,
    payload: str,
    config: LlamaRuntimeConfig,
    interrupt_callback: Any = None,
) -> str:
    """Split before inference; preserve original slot IDs and returned TEXT.

    The backend raises ContextBudgetError during its token preflight. A split
    does not repeat a completed generation. Split responses remain ordinary
    line records and pass through the caller's existing validation/recovery.
    """
    if interrupt_callback is not None:
        interrupt_callback()
    try:
        return backend.complete_planner(
            task=task, system_prompt=system_prompt, payload=payload,
            config=config, interrupt_callback=interrupt_callback,
        )
    except ContextBudgetError as exc:
        request = json.loads(payload)
        slots = request.get("slots", [])
        retry = request.get("retry", "no")
        # Keep Scene-wide performance generation together before splitting slots.
        # Only distant reading context is expendable, never active lyrics or prose.
        reduced = reduce_section_context(request)
        if reduced is not None:
            _LOGGER.info(
                "[MV Director - Timeline Planner] section reading context reduced; "
                "task=%s; scene=%s; reason=%s", task, request.get("scene_number"), exc,
            )
            return complete_with_context_recovery(
                backend, task=task, system_prompt=system_prompt,
                payload=canonical_json(reduced), config=config,
                interrupt_callback=interrupt_callback,
            )
        if len(slots) > 1:
            midpoint = len(slots) // 2
            _LOGGER.info(
                "[MV Director - Timeline Planner] context request split; task=%s; "
                "retry=%s; slots=%s; parts=%d+%d; reason=%s",
                task, retry, [slot["slot"] for slot in slots],
                midpoint, len(slots) - midpoint, exc,
            )
            responses = []
            for part in (slots[:midpoint], slots[midpoint:]):
                responses.append(complete_with_context_recovery(
                    backend, task=task, system_prompt=system_prompt,
                    payload=canonical_json({**request, "slots": part}),
                    config=config, interrupt_callback=interrupt_callback,
                ))
            return "\n".join(responses)

        # A singleton cannot be split further. Retain the newest half of one
        # history at a time and remeasure, ending at an empty optional history.
        candidates = [key for key in _OPTIONAL_HISTORIES
                      if isinstance(request.get(key), list) and request[key]]
        if candidates:
            key = max(candidates, key=lambda name: len(canonical_json({name: request[name]})))
            history = request[key]
            retained = len(history) // 2
            request[key] = history[-retained:] if retained else []
            _LOGGER.info(
                "[MV Director - Timeline Planner] context history reduced; task=%s; "
                "retry=%s; slots=%s; history=%s; removed=%d; retained=%d; reason=%s",
                task, retry, [slot["slot"] for slot in slots], key,
                len(history) - retained, retained, exc,
            )
            return complete_with_context_recovery(
                backend, task=task, system_prompt=system_prompt,
                payload=canonical_json(request), config=config,
                interrupt_callback=interrupt_callback,
            )

        raise ContextBudgetError(
            f"Planner request cannot fit after context recovery; task={task}; "
            f"retry={retry}; slots={[slot['slot'] for slot in slots]}; "
            "required instructions and slot content were retained. Shorten the "
            f"profile/input or increase n_ctx. {exc}"
        ) from exc
