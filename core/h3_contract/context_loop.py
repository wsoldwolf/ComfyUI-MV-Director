"""Supported pinned Context Loop contracts; no runtime Git auto-detection."""

from .context_loop_0_6_9 import CONTEXT_LOOP_0_6_9, ContextLoopContract

COMFYUI_BASELINE_VERSION = "0.37.2"
COMFYUI_BASELINE_COMMIT = "830232b856045ca2892833212d7771078a13edd5"
CONTEXT_LOOP_BASELINE_VERSION = "0.7.0"
CONTEXT_LOOP_BASELINE_COMMIT = "d80304f05ecc2f504e64cbfb636e2a21d4409909"
CONTRACT_ID = f"context-loop-{CONTEXT_LOOP_BASELINE_VERSION}@{CONTEXT_LOOP_BASELINE_COMMIT}"
LEGACY_CONTRACT_ID = CONTEXT_LOOP_0_6_9.contract_id
SUPPORTED_CONTRACT_IDS = (CONTRACT_ID, LEGACY_CONTRACT_ID)

CONTEXT_LOOP_0_7_0 = ContextLoopContract(
    contract_id=CONTRACT_ID,
    ref2va_node_types=CONTEXT_LOOP_0_6_9.ref2va_node_types,
    image_input_pattern=CONTEXT_LOOP_0_6_9.image_input_pattern,
)
