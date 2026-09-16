"""Consistent lifecycle logging for every public MV Director node."""

from __future__ import annotations

from functools import wraps
import logging
from time import perf_counter
from typing import Any


LOGGER = logging.getLogger("mv_director.nodes")
LOGGER.setLevel(logging.INFO)
LOGGER.addHandler(logging.NullHandler())
_MAX_STATUS_CHARS = 1000


def _single_line(value: Any) -> str:
    text = " ".join(str(value).replace("\r", "\n").splitlines()).strip()
    if len(text) > _MAX_STATUS_CHARS:
        return text[: _MAX_STATUS_CHARS - 3] + "..."
    return text


def _result_status(node_class: type[Any], result: Any) -> str:
    if isinstance(result, dict):
        ui = result.get("ui")
        if isinstance(ui, dict):
            status = ui.get("status")
            if isinstance(status, (list, tuple)) and status:
                return _single_line(status[0])
            if isinstance(status, str):
                return _single_line(status)
        values = result.get("result")
    else:
        values = result
    names = getattr(node_class, "RETURN_NAMES", ())
    if (
        isinstance(names, (list, tuple))
        and "status" in names
        and isinstance(values, (list, tuple))
    ):
        index = names.index("status")
        if index < len(values):
            return _single_line(values[index])
    return ""


def _is_blocked(status: str) -> bool:
    lowered = status.casefold()
    return "complete=no" in lowered or "blocked" in lowered


def instrument_node_class(node_class: type[Any], display_name: str) -> None:
    """Wrap the ComfyUI entrypoint once with name-prefixed lifecycle logs."""

    function_name = getattr(node_class, "FUNCTION", "")
    original = getattr(node_class, function_name, None)
    if not function_name or not callable(original):
        raise TypeError(f"{node_class.__name__} has no callable FUNCTION")
    if getattr(original, "__mvd_node_logged__", False):
        return

    @wraps(original)
    def logged(self: Any, *args: Any, **kwargs: Any) -> Any:
        started = perf_counter()
        LOGGER.info("[%s] started", display_name)
        try:
            result = original(self, *args, **kwargs)
        except BaseException as exc:
            elapsed = perf_counter() - started
            LOGGER.error(
                "[%s] failed; elapsed=%.3fs; error=%s: %s",
                display_name,
                elapsed,
                type(exc).__name__,
                _single_line(exc),
            )
            raise
        elapsed = perf_counter() - started
        status = _result_status(node_class, result)
        if _is_blocked(status):
            LOGGER.warning(
                "[%s] blocked; elapsed=%.3fs; status=%s",
                display_name,
                elapsed,
                status,
            )
        elif status:
            LOGGER.info(
                "[%s] completed; elapsed=%.3fs; status=%s",
                display_name,
                elapsed,
                status,
                extra={"color": "cyan"},
            )
        else:
            LOGGER.info(
                "[%s] completed; elapsed=%.3fs",
                display_name,
                elapsed,
                extra={"color": "cyan"},
            )
        return result

    logged.__mvd_node_logged__ = True
    logged.__mvd_node_display_name__ = display_name
    setattr(node_class, function_name, logged)
