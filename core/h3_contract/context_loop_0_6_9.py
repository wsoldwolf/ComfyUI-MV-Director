"""Versioned ComfyUI and Context Loop adapter used by graph and Plan contracts."""

from __future__ import annotations

import re
from dataclasses import dataclass


COMFYUI_BASELINE_VERSION = "0.36.0"
COMFYUI_BASELINE_COMMIT = "ee71d5c4993f29086b27fde1629a945ae48425bf"
CONTEXT_LOOP_BASELINE_VERSION = "0.6.9"
CONTEXT_LOOP_BASELINE_COMMIT = "9860a063784c8c23b58e00107f2180e0df3c43d9"
CONTRACT_ID = (
    f"context-loop-{CONTEXT_LOOP_BASELINE_VERSION}@"
    f"{CONTEXT_LOOP_BASELINE_COMMIT}"
)


@dataclass(frozen=True, slots=True)
class ContextLoopContract:
    contract_id: str
    ref2va_node_types: frozenset[str]
    image_input_pattern: re.Pattern[str]


CONTEXT_LOOP_0_6_9 = ContextLoopContract(
    contract_id=CONTRACT_ID,
    ref2va_node_types=frozenset({"MiniMaxH3ReferenceToVideo"}),
    image_input_pattern=re.compile(r"^(?:ref_images\.)?ref_image_([0-8])$"),
)
