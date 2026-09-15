"""Token budget checks performed before an inference call."""

from __future__ import annotations

import math
from dataclasses import dataclass


class ContextBudgetError(ValueError):
    pass


@dataclass(frozen=True, slots=True)
class ContextBudget:
    serialized_input_tokens: int
    reserved_output_tokens: int
    safety_margin: int
    effective_context: int
    estimated: bool = False

    @property
    def required_tokens(self) -> int:
        return (
            self.serialized_input_tokens
            + self.reserved_output_tokens
            + self.safety_margin
        )

    @property
    def remaining_tokens(self) -> int:
        return self.effective_context - self.required_tokens

    def validate(self) -> None:
        values = (
            self.serialized_input_tokens,
            self.reserved_output_tokens,
            self.safety_margin,
            self.effective_context,
        )
        if any(not isinstance(value, int) or isinstance(value, bool) for value in values):
            raise ValueError("context budget values must be integers")
        if any(value < 0 for value in values[:3]) or self.effective_context < 1:
            raise ValueError("context budget values are out of range")
        if self.required_tokens > self.effective_context:
            raise ContextBudgetError(
                "context budget exceeded: "
                f"input={self.serialized_input_tokens}, "
                f"reserved_output={self.reserved_output_tokens}, "
                f"safety_margin={self.safety_margin}, "
                f"required={self.required_tokens}, "
                f"effective_context={self.effective_context}"
            )


def build_context_budget(
    serialized_input_tokens: int,
    reserved_output_tokens: int,
    effective_context: int,
    *,
    estimated: bool = False,
) -> ContextBudget:
    for name, value in (
        ("serialized_input_tokens", serialized_input_tokens),
        ("reserved_output_tokens", reserved_output_tokens),
        ("effective_context", effective_context),
    ):
        if not isinstance(value, int) or isinstance(value, bool):
            raise ValueError(f"{name} must be an integer")
    if serialized_input_tokens < 0 or reserved_output_tokens < 0:
        raise ValueError("token counts must be non-negative")
    if effective_context < 1:
        raise ValueError("effective_context must be positive")
    margin = max(1024, math.ceil(effective_context * 0.08))
    budget = ContextBudget(
        serialized_input_tokens,
        reserved_output_tokens,
        margin,
        effective_context,
        estimated,
    )
    budget.validate()
    return budget
