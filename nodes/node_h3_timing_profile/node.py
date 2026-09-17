"""Pinned Context Loop H3 timing profile node."""

from __future__ import annotations

from typing import Any

try:
    from ...core.h3_contract import CONTRACT_ID, DEFAULT_H3_TIMING_PROFILE
except ImportError:
    from core.h3_contract import CONTRACT_ID, DEFAULT_H3_TIMING_PROFILE


class MVDirectorH3TimingProfile:
    RETURN_TYPES = ("MV_DIRECTOR_H3_TIMING_PROFILE", "STRING", "STRING")
    RETURN_NAMES = ("timing_profile", "profile_json", "status")
    FUNCTION = "build_profile"
    CATEGORY = "MV Director/Utilities"
    DESCRIPTION = "Share the pinned Context Loop 0.6.9 timing contract."

    @classmethod
    def INPUT_TYPES(cls) -> dict[str, Any]:
        return {"required": {"contract": ([CONTRACT_ID], {"default": CONTRACT_ID})}}

    def build_profile(self, contract: str):
        if contract != CONTRACT_ID:
            raise ValueError("unsupported H3 timing contract")
        profile = DEFAULT_H3_TIMING_PROFILE
        profile.validate()
        return profile, profile.to_json(), f"contract={contract}; fps={profile.fps}"
