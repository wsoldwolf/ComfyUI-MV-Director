"""LLM-owned carryable inventory; no noun dictionary or prose repair."""
from __future__ import annotations

from dataclasses import dataclass
import json
import logging
import re
from typing import Any, Mapping

from ..artifacts import canonical_json
from ..inference import LlamaRuntimeConfig
from ..inference.budget import ContextBudgetError
from ..protocols import parse_llm_records
from .requests import normalize_record_response
from .prop_decision import _unique_object

TASK = "subject-prop-inventory"
RECORD = "PROP_INVENTORY"
ITEM_FIELDS = frozenset({"id", "subject", "label", "evidence", "initial_state"})
_LOGGER = logging.getLogger("mv_director.nodes")


@dataclass(frozen=True)
class PropInventoryResult:
    props: tuple[Mapping[str, str], ...]
    attempts: int
    status: str


def parse_prop_inventory(response: str):
    parsed = parse_llm_records(normalize_record_response(response, RECORD),
        allowed_slots={RECORD: frozenset({1})}, required=frozenset({(RECORD, 1)}))
    if parsed.issues or parsed.missing:
        return None
    try:
        value = json.loads(parsed.records[0].text, object_pairs_hook=_unique_object)
    except (TypeError, ValueError):
        return None
    if not isinstance(value, dict) or set(value) != {"props"} or not isinstance(value["props"], list):
        return None
    if len(value["props"]) > 32:
        return None
    seen = set()
    for prop in value["props"]:
        if not isinstance(prop, dict) or set(prop) != ITEM_FIELDS:
            return None
        if not all(isinstance(v, str) and v.strip() and len(v) <= 400
                   and not any(ord(c) < 32 for c in v) for v in prop.values()):
            return None
        if not re.fullmatch(r"P[1-9][0-9]*", prop["id"]) or prop["id"] in seen:
            return None
        seen.add(prop["id"])
    # A valid empty inventory differs from an invalid response. This does not
    # certify that the LLM found every object in the source material.
    return tuple(value["props"])


def request_prop_inventory(backend: Any, *, subject_emd: str,
                           fixed_boundary: Mapping[str, str], scene_number: int,
                           system_prompt: str, runtime_config: LlamaRuntimeConfig,
                           interrupt_callback=None) -> PropInventoryResult:
    request = {"protocol": "MVD_LLM_RECORDS_V1", "task": TASK,
               "scene_number": scene_number, "subject_emd": subject_emd,
               "fixed_boundary_performances": dict(fixed_boundary),
               "slots": [{"slot": 1}]}
    for attempt in range(1, 3):
        if interrupt_callback:
            interrupt_callback()
        if attempt > 1:
            request["retry"] = "invalid_inventory_transport_only"
        try:
            response = backend.complete_planner(task=TASK, system_prompt=system_prompt,
                payload=canonical_json(request), config=runtime_config,
                interrupt_callback=interrupt_callback)
        except ContextBudgetError:
            _LOGGER.warning("[MV Director - Timeline Planner] prop inventory skipped; "
                            "reason=context_budget; continuing existing authorship")
            return PropInventoryResult((), attempt, "context_budget")
        props = parse_prop_inventory(response)
        if props is not None:
            return PropInventoryResult(props, attempt, "transport_valid")
    return PropInventoryResult((), 2, "invalid_transport")


def build_prop_inventory_grammar():
    return ('root ::= ' + json.dumps(f"{RECORD}\t1\t") + ' char+ "\\n"?\n'
            + r"char ::= [^\x00-\x1f]" + "\n")
