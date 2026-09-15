"""Versioned Context Loop adapter used by graph and Plan contracts."""

from __future__ import annotations

import re
from dataclasses import dataclass


CONTRACT_ID = "context-loop-0.6.6@136db5dbbf25405063a96e898ae880e8785b7f29"


@dataclass(frozen=True, slots=True)
class ContextLoopContract:
    contract_id: str
    ref2va_node_types: frozenset[str]
    image_input_pattern: re.Pattern[str]


CONTEXT_LOOP_0_6_6 = ContextLoopContract(
    contract_id=CONTRACT_ID,
    ref2va_node_types=frozenset({"MiniMaxH3ReferenceToVideo"}),
    image_input_pattern=re.compile(r"^(?:ref_images\.)?ref_image_([0-8])$"),
)

