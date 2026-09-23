"""Bounded, author-enabled composition; no judgement of LLM prose quality."""
from __future__ import annotations

from ..direction.profiles import MOTION_TEMPLATES


def select_motion_composition(scene, positions, direction, concept_emd):
    profile = direction.motion_policy_profile_id or direction.motion_profile_id
    if direction.motion_templates is None and direction.motion_profile_id == "passthrough":
        return None, "authored_common_motion"
    templates = (direction.motion_templates if direction.motion_templates is not None
                 else MOTION_TEMPLATES.get(profile, ()))
    if not templates:
        return None, "disabled"
    if sum(line.startswith("* ") for line in concept_emd.splitlines()) != 1:
        return None, "requires_one_subject"
    if any(p["fixed_performance"] or p["author_body"] for p in positions):
        return None, "authored_performance"
    eligible = [p for p in positions if not p["fixed_camera"]
                and p["end_ms"] - p["start_ms"] >= 4000]
    if not eligible:
        return None, "no_four_second_unfixed_camera_shot"
    target = max(eligible, key=lambda p: p["end_ms"] - p["start_ms"])
    index = (scene.scene_number - 1) % len(templates)
    source = "user" if direction.motion_templates is not None else f"profile:{profile}"
    return (scene.scene_number, target["shot"], source, index + 1, templates[index]), ""
