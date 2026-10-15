"""Parse the UI's shared-vocal target list without inferring performers."""
from __future__ import annotations

import re

from .errors import TimelinePlannerError


def parse_lip_sync_targets(value: str, *, subject_count: int | None = None) -> tuple[str, ...]:
    """Keep single-target compatibility; require distinct, defined Subject IDs."""
    if not isinstance(value, str):
        raise TimelinePlannerError("lip_sync_target must be a string")
    targets = tuple(part.strip() for part in re.split(r"[,，、]", value))
    if not targets or any(not re.fullmatch(r"サブジェクト[1-4]", target) for target in targets):
        raise TimelinePlannerError("lip_sync_target must be サブジェクト1..4 separated by commas")
    if len(set(targets)) != len(targets):
        raise TimelinePlannerError("lip_sync_target contains a duplicate Subject")
    if subject_count is not None and any(int(target[-1]) > subject_count for target in targets):
        raise TimelinePlannerError("lip-sync target references undefined concept ID")
    return targets
