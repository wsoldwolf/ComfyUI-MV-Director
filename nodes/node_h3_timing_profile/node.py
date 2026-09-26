"""Pinned Context Loop H3 timing profile node."""

from __future__ import annotations

from dataclasses import replace
from typing import Any

try:
    from ...core.h3_contract import CONTRACT_ID, DEFAULT_H3_TIMING_PROFILE, SUPPORTED_CONTRACT_IDS
except ImportError:
    from core.h3_contract import CONTRACT_ID, DEFAULT_H3_TIMING_PROFILE, SUPPORTED_CONTRACT_IDS


class MVDirectorH3TimingProfile:
    RETURN_TYPES = ("MV_DIRECTOR_H3_TIMING_PROFILE", "STRING", "STRING")
    RETURN_NAMES = ("timing_profile", "profile_json", "status")
    FUNCTION = "build_profile"
    CATEGORY = "MV Director/Utilities"
    DESCRIPTION = "Share a pinned Context Loop timing contract. Default: 0.7.0 at d80304f."

    @classmethod
    def INPUT_TYPES(cls) -> dict[str, Any]:
        return {"required": {"contract": (list(SUPPORTED_CONTRACT_IDS), {"default": CONTRACT_ID})}}

    def build_profile(self, contract: str):
        if contract not in SUPPORTED_CONTRACT_IDS:
            raise ValueError("unsupported H3 timing contract")
        profile = replace(DEFAULT_H3_TIMING_PROFILE, contract=contract)
        profile.validate()
        return profile, profile.to_json(), f"contract={contract}; fps={profile.fps}"
