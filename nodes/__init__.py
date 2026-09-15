"""ComfyUI-facing node registrations."""

from .node_image_to_subject_emd import MVDirectorImageToSubjectEMD
from .node_direction_enhancer import MVDirectorDirectionEnhancer
from .node_lyric_segmentation import MVDirectorLyricSegmentation


NODE_CLASS_MAPPINGS = {
    "MVDirectorImageToSubjectEMD": MVDirectorImageToSubjectEMD,
    "MVDirectorDirectionEnhancer": MVDirectorDirectionEnhancer,
    "MVDirectorLyricSegmentation": MVDirectorLyricSegmentation,
}

NODE_DISPLAY_NAME_MAPPINGS = {
    "MVDirectorImageToSubjectEMD": "MV Director - Image to Subject EMD",
    "MVDirectorDirectionEnhancer": "MV Director - Direction Enhancer",
    "MVDirectorLyricSegmentation": "MV Director - Lyric Segmentation",
}

__all__ = ["NODE_CLASS_MAPPINGS", "NODE_DISPLAY_NAME_MAPPINGS"]
