"""ComfyUI-facing node registrations."""

from .node_image_to_subject_emd import MVDirectorImageToSubjectEMD


NODE_CLASS_MAPPINGS = {
    "MVDirectorImageToSubjectEMD": MVDirectorImageToSubjectEMD,
}

NODE_DISPLAY_NAME_MAPPINGS = {
    "MVDirectorImageToSubjectEMD": "MV Director - Image to Subject EMD",
}

__all__ = ["NODE_CLASS_MAPPINGS", "NODE_DISPLAY_NAME_MAPPINGS"]

