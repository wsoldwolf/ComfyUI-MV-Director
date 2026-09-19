"""Public namespace contract for MV Director nodes and sockets."""

from __future__ import annotations


NODE_TYPE_PREFIX = "MVDirector"
SOCKET_TYPE_PREFIX = "MV_DIRECTOR_"
CATEGORY_PREFIX = "MV Director/"

PUBLIC_NODE_TYPES = (
    "MVDirectorImageToSubjectEMD",
    "MVDirectorDirectionEnhancer",
    "MVDirectorTimelinePlanner",
    "MVDirectorEMDCompiler",
    "MVDirectorLyricSegmentation",
    "MVDirectorAudioPadPair",
    "MVDirectorH3TimingProfile",
    "MVDirectorSeed32",
    "MVDirectorStringCombo",
    "MVDirectorConnectedCombo",
    "MVDirectorLoadTextFile",
    "MVDirectorSceneDebugSplitter",
)

CUSTOM_SOCKET_TYPES = (
    "MV_DIRECTOR_REFERENCE_BINDINGS",
    "MV_DIRECTOR_DIRECTION",
    "MV_DIRECTOR_TIMELINE",
    "MV_DIRECTOR_EMD",
    "MV_DIRECTOR_H3_TIMING_PROFILE",
    "MV_DIRECTOR_REQUIRED_REFERENCES",
)

PUBLIC_CATEGORIES = (
    "MV Director/Core",
    "MV Director/Input",
    "MV Director/Audio",
    "MV Director/Utilities",
)


def validate_namespace_contract() -> None:
    if len(PUBLIC_NODE_TYPES) != len(set(PUBLIC_NODE_TYPES)):
        raise ValueError("public node type IDs must be unique")
    if len(CUSTOM_SOCKET_TYPES) != len(set(CUSTOM_SOCKET_TYPES)):
        raise ValueError("custom socket type IDs must be unique")
    if any(not value.startswith(NODE_TYPE_PREFIX) for value in PUBLIC_NODE_TYPES):
        raise ValueError("all public node type IDs must use MVDirector")
    if any(
        not value.startswith(SOCKET_TYPE_PREFIX) for value in CUSTOM_SOCKET_TYPES
    ):
        raise ValueError("all custom socket IDs must use MV_DIRECTOR_")
    if any(not value.startswith(CATEGORY_PREFIX) for value in PUBLIC_CATEGORIES):
        raise ValueError("all public categories must use MV Director/")
    if any(value.startswith(("CL", "MiniMaxH3")) for value in PUBLIC_NODE_TYPES):
        raise ValueError("legacy public node aliases are forbidden")
