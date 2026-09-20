"""Generation-time contracts; never repair or compose returned Action text."""

import json
from collections.abc import Mapping, Sequence


def _slots(values: Sequence[int]) -> None:
    if not values or any(type(v) is not int or v < 1 for v in values):
        raise ValueError("Planner grammar requires positive integer slots")
    if len(set(values)) != len(values):
        raise ValueError("Planner grammar slots must be unique")


def build_action_grammar(slots: Sequence[Mapping[str, object]]) -> str:
    """Lock assigned LLM fragments at the start; leave realization prose free.

    A bounded bridge joins two required fragments in a single coverage Shot.
    This avoids an unbounded free prefix that can consume the entire token
    budget before the sampler ever reaches the required literal.
    """
    _slots([s["slot"] for s in slots])
    quote = lambda value: json.dumps(value, ensure_ascii=False)
    rows = []
    for slot in slots:
        fragments = []
        for field in ("required_spatial_anchor", "required_visible_development"):
            fragment = slot.get(field, "")
            if not isinstance(fragment, str) or any(ord(c) < 32 for c in fragment):
                raise ValueError(f"{field} must be single-line text")
            if fragment.strip() and fragment not in fragments:
                fragments.append(fragment)
        body = (
            " bridge ".join(quote(f) for f in fragments) + " char*"
            if fragments else "char+"
        )
        rows.append(quote(f"ACTION\t{slot['slot']}\t") + " " + body)
    return (
        "root ::= " + ' "\\n" '.join(rows) + ' "\\n"?\n'
        + r"char ::= [^\x00-\x1f]" + "\n"
        + "bridge ::= char{0,32}\n"
    )


def build_action_audit_grammar(slots: Sequence[int], reasons: Sequence[str]) -> str:
    """One finite primary verdict per slot keeps audit output short."""
    _slots(slots)
    if not reasons or any(not r or any(c not in "ABCDEFGHIJKLMNOPQRSTUVWXYZ_" for c in r) for r in reasons):
        raise ValueError("Audit grammar requires finite uppercase reason codes")
    quote = lambda value: json.dumps(value, ensure_ascii=False)
    return (
        "root ::= " + ' "\\n" '.join(quote(f"AUDIT\t{s}\t") + " verdict" for s in slots)
        + ' "\\n"?\n'
        + 'verdict ::= "PASS" | "REJECT:" reason\n'
        + "reason ::= " + " | ".join(quote(r) for r in sorted(set(reasons))) + "\n"
    )
