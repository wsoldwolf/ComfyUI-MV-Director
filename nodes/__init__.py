"""ComfyUI-facing node registrations."""

from .node_image_to_subject_emd import MVDirectorImageToSubjectEMD
from .node_direction_enhancer import MVDirectorDirectionEnhancer
from .node_lyric_segmentation import MVDirectorLyricSegmentation
from .node_timeline_planner import MVDirectorTimelinePlanner


NODE_CLASS_MAPPINGS = {
    "MVDirectorImageToSubjectEMD": MVDirectorImageToSubjectEMD,
    "MVDirectorDirectionEnhancer": MVDirectorDirectionEnhancer,
    "MVDirectorLyricSegmentation": MVDirectorLyricSegmentation,
    "MVDirectorTimelinePlanner": MVDirectorTimelinePlanner,
}

NODE_DISPLAY_NAME_MAPPINGS = {
    "MVDirectorImageToSubjectEMD": "MV Director - Image to Subject EMD",
    "MVDirectorDirectionEnhancer": "MV Director - Direction Enhancer",
    "MVDirectorLyricSegmentation": "MV Director - Lyric Segmentation",
    "MVDirectorTimelinePlanner": "MV Director - Timeline Planner",
}

__all__ = ["NODE_CLASS_MAPPINGS", "NODE_DISPLAY_NAME_MAPPINGS"]
