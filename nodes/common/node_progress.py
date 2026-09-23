"""Best-effort ComfyUI progress for MV Director node executions.

Work units count completed operations, not elapsed time or generated tokens.
The final unit is reserved for a successful node return; retries may grow the
denominator, so an in-flight or blocked node never reports completion.
"""

from __future__ import annotations

from contextvars import ContextVar
from typing import Any


_ACTIVE_PROGRESS: ContextVar["NodeProgress | None"] = ContextVar(
    "mvd_node_progress", default=None
)


class NodeProgress:
    def __init__(self) -> None:
        self.completed = 0
        self.total = 2
        try:
            from comfy.utils import ProgressBar  # type: ignore
        except ImportError:
            self.bar: Any = None
        else:
            self.bar = ProgressBar(self.total)
            self.bar.update_absolute(0)

    def configure(self, work_units: int) -> None:
        """Declare an estimate of operations before the final completion unit."""
        self.total = max(self.completed + 2, int(work_units) + 1)
        self._publish()

    def advance(self, count: int = 1) -> None:
        if count < 1:
            raise ValueError("progress count must be positive")
        self.completed += count
        if self.completed >= self.total:
            self.total = self.completed + 1
        self._publish()

    def finish(self) -> None:
        if self.bar is not None:
            self.bar.update_absolute(self.total, total=self.total)

    def _publish(self) -> None:
        if self.bar is not None:
            self.bar.update_absolute(self.completed, total=self.total)


def current_progress() -> NodeProgress | None:
    return _ACTIVE_PROGRESS.get()


def configure_progress(work_units: int) -> None:
    progress = current_progress()
    if progress is not None:
        progress.configure(work_units)


def advance_progress(count: int = 1) -> None:
    progress = current_progress()
    if progress is not None:
        progress.advance(count)


def begin_progress() -> tuple[NodeProgress, Any]:
    progress = NodeProgress()
    return progress, _ACTIVE_PROGRESS.set(progress)


def end_progress(token: Any) -> None:
    _ACTIVE_PROGRESS.reset(token)
