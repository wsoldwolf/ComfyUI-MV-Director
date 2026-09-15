"""ComfyUI-facing node registrations."""

from .node_image_to_subject_emd import MVDirectorImageToSubjectEMD
from .node_direction_enhancer import MVDirectorDirectionEnhancer


NODE_CLASS_MAPPINGS = {
    "MVDirectorImageToSubjectEMD": MVDirectorImageToSubjectEMD,
    "MVDirectorDirectionEnhancer": MVDirectorDirectionEnhancer,
}

NODE_DISPLAY_NAME_MAPPINGS = {
    "MVDirectorImageToSubjectEMD": "MV Director - Image to Subject EMD",
    "MVDirectorDirectionEnhancer": "MV Director - Direction Enhancer",
}

__all__ = ["NODE_CLASS_MAPPINGS", "NODE_DISPLAY_NAME_MAPPINGS"]
