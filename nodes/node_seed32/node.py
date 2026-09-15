"""Shared positive signed-32-bit seed source."""

from __future__ import annotations

import secrets
from typing import Any


MAX_SEED = 2_147_483_647


class MVDirectorSeed32:
    RETURN_TYPES = ("INT",)
    RETURN_NAMES = ("seed",)
    FUNCTION = "make_seed"
    CATEGORY = "MV Director/Utilities"
    DESCRIPTION = "Create one seed in 1..2147483647 for GGUF and H3 branches."

    @classmethod
    def INPUT_TYPES(cls) -> dict[str, Any]:
        return {
            "required": {
                "mode": (["fixed", "random"], {"default": "fixed"}),
                "seed": (
                    "INT",
                    {
                        "default": -1,
                        "min": -1,
                        "max": MAX_SEED,
                        "control_after_generate": False,
                    },
                ),
            }
        }

    @classmethod
    def VALIDATE_INPUTS(cls, mode: str, seed: int) -> bool | str:
        if mode not in {"fixed", "random"}:
            return "mode must be fixed or random"
        if isinstance(seed, bool) or not isinstance(seed, int) or seed < -1 or seed > MAX_SEED:
            return "seed must be -1 or an integer in 1..2147483647"
        if seed == 0:
            return "seed must not be zero"
        return True

    @classmethod
    def IS_CHANGED(cls, mode: str, seed: int) -> float | int:
        return float("nan") if mode == "random" else seed

    def make_seed(self, mode: str, seed: int) -> tuple[int]:
        validation = self.VALIDATE_INPUTS(mode, seed)
        if validation is not True:
            raise ValueError(validation)
        if mode == "random" or seed == -1:
            seed = secrets.randbelow(MAX_SEED) + 1
        return (seed,)
