"""Scene-local prop decisions, not a mandatory semantic audit.

Only transport and field ownership are validated here. Physical plausibility
is judged from the LLM output; Python never rewrites the authored decisions.
Invalid transport falls back to existing authorship without prose repair.
"""
from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass
import json
import logging
from typing import Any, Mapping

from ..artifacts import canonical_json
from ..inference import LlamaRuntimeConfig
from ..inference.budget import ContextBudgetError
from ..protocols import parse_llm_records
from .requests import normalize_record_response

TASK = "scene-author-prop-decision"
RECORD = "PROP_DECISION"
FIELDS = frozenset({"prop_locations", "right_hand", "left_hand", "transition",
                    "performance_scope", "end_state"})
DecisionValue = str | Mapping[str, str]
_LOGGER = logging.getLogger("mv_director.nodes")


@dataclass(frozen=True)
class PropDecisionResult:
    decisions: Mapping[int, Mapping[str, DecisionValue]]
    attempts: int
    status: str


def _unique_object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("duplicate decision field")
        result[key] = value
    return result


def parse_prop_decisions(response: str, shots: tuple[int, ...], *, prop_ids: frozenset[str] | None = None):
    """Reject partial/ambiguous transport; do not infer or repair meaning."""
    parsed = parse_llm_records(normalize_record_response(response, RECORD),
        allowed_slots={RECORD: frozenset(range(1, len(shots) + 1))},
        required=frozenset((RECORD, i) for i in range(1, len(shots) + 1)))
    if parsed.issues or parsed.missing:
        return None
    result = {}
    for record in parsed.records:
        try:
            value = json.loads(record.text, object_pairs_hook=_unique_object)
        except (ValueError, TypeError):
            return None
        if not isinstance(value, dict) or set(value) != FIELDS:
            return None
        def valid_text(v):
            return (isinstance(v, str) and bool(v.strip()) and len(v) <= 400
                    and not any(ord(c) < 32 for c in v))
        for field, entry in value.items():
            if field in {"prop_locations", "end_state"} and isinstance(entry, dict):
                if not entry or not all(valid_text(k) and valid_text(v) for k, v in entry.items()):
                    return None
            elif not valid_text(entry):
                return None
        if (isinstance(value["prop_locations"], dict) and isinstance(value["end_state"], dict)
                and set(value["prop_locations"]) != set(value["end_state"])):
            return None
        if prop_ids is not None and prop_ids:
            # Coverage is structural, not proof that these locations are true.
            # In inventory mode neither prose nor a partial prop map can hide
            # the loss of an ID between the inventory and a Shot's end state.
            if any(not isinstance(value[field], dict) or set(value[field]) != prop_ids
                   for field in ("prop_locations", "end_state")):
                return None
        result[shots[record.slot - 1]] = value
    return result


def request_prop_decisions(backend: Any, *, shared: Mapping[str, object],
                           system_prompt: str, runtime_config: LlamaRuntimeConfig,
                           interrupt_callback=None) -> PropDecisionResult:
    """At most two calls. Invalid transport returns no authoritative decision."""
    positions = shared.get("shot_positions", [])
    shots = tuple(p["shot"] for p in positions)
    if (not shots or any(type(s) is not int or s < 1 for s in shots)
            or len(set(shots)) != len(shots)):
        raise ValueError("prop decisions require unique positive Shot numbers")
    request = deepcopy(dict(shared))
    request.update(protocol="MVD_LLM_RECORDS_V1", task=TASK,
                   slots=[{"slot": i, "shot": s,
                           "scene_number": shared["scene_number"]}
                          for i, s in enumerate(shots, 1)])
    inventory = shared.get("prop_inventory")
    prop_ids = frozenset(p["id"] for p in inventory) if inventory is not None else None
    for attempt in range(1, 3):
        if interrupt_callback:
            interrupt_callback()
        if attempt > 1:
            request["retry"] = "invalid_prop_decision_transport_only"
            if prop_ids:
                request["required_prop_ids_in_each_shot"] = sorted(prop_ids)
        try:
            response = backend.complete_planner(task=TASK, system_prompt=system_prompt,
                payload=canonical_json(request), config=runtime_config,
                interrupt_callback=interrupt_callback)
        except ContextBudgetError:
            _LOGGER.warning("[MV Director - Timeline Planner] prop decision skipped; "
                            "scene=%s; reason=context_budget; continuing existing authorship",
                            shared["scene_number"])
            return PropDecisionResult({}, attempt, "context_budget")
        decisions = parse_prop_decisions(response, shots, prop_ids=prop_ids)
        if decisions is not None:
            return PropDecisionResult(decisions, attempt, "transport_valid")
    return PropDecisionResult({}, 2, "invalid_transport")


def build_prop_decision_grammar(slots):
    numbers = [s["slot"] for s in slots]
    if (not numbers or any(type(n) is not int or n < 1 for n in numbers)
            or len(set(numbers)) != len(numbers)):
        raise ValueError("invalid prop decision slots")
    root = ' "\\n" '.join(json.dumps(f"{RECORD}\t{n}\t") + " char+" for n in numbers)
    return 'root ::= ' + root + ' "\\n"?\n' + r"char ::= [^\x00-\x1f]" + "\n"
