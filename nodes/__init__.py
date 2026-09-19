"""ComfyUI-facing node registrations."""

from .node_image_to_subject_emd import MVDirectorImageToSubjectEMD
from .node_direction_enhancer import MVDirectorDirectionEnhancer
from .node_emd_compiler import MVDirectorEMDCompiler
from .node_lyric_segmentation import MVDirectorLyricSegmentation
from .node_timeline_planner import MVDirectorTimelinePlanner
from .node_audio_pad_pair import MVDirectorAudioPadPair
from .node_h3_timing_profile import MVDirectorH3TimingProfile
from .node_seed32 import MVDirectorSeed32
from .node_string_combo import MVDirectorStringCombo
from .node_connected_combo import MVDirectorConnectedCombo
from .node_load_text_file import MVDirectorLoadTextFile
from .node_scene_debug_splitter import MVDirectorSceneDebugSplitter
from .common.node_logging import instrument_node_class


NODE_CLASS_MAPPINGS = {
    "MVDirectorImageToSubjectEMD": MVDirectorImageToSubjectEMD,
    "MVDirectorDirectionEnhancer": MVDirectorDirectionEnhancer,
    "MVDirectorEMDCompiler": MVDirectorEMDCompiler,
    "MVDirectorLyricSegmentation": MVDirectorLyricSegmentation,
    "MVDirectorTimelinePlanner": MVDirectorTimelinePlanner,
    "MVDirectorAudioPadPair": MVDirectorAudioPadPair,
    "MVDirectorH3TimingProfile": MVDirectorH3TimingProfile,
    "MVDirectorSeed32": MVDirectorSeed32,
    "MVDirectorStringCombo": MVDirectorStringCombo,
    "MVDirectorConnectedCombo": MVDirectorConnectedCombo,
    "MVDirectorLoadTextFile": MVDirectorLoadTextFile,
    "MVDirectorSceneDebugSplitter": MVDirectorSceneDebugSplitter,
}

NODE_DISPLAY_NAME_MAPPINGS = {
    "MVDirectorImageToSubjectEMD": "MV Director - Image to Subject EMD",
    "MVDirectorDirectionEnhancer": "MV Director - Direction Enhancer",
    "MVDirectorEMDCompiler": "MV Director - EMD Compiler (Ref2VA)",
    "MVDirectorLyricSegmentation": "MV Director - Lyric Segmentation",
    "MVDirectorTimelinePlanner": "MV Director - Timeline Planner",
    "MVDirectorAudioPadPair": "MV Director - Audio Pad Pair (PCM Silence)",
    "MVDirectorH3TimingProfile": "MV Director - H3 Timing Profile",
    "MVDirectorSeed32": "MV Director - 32-bit Seed",
    "MVDirectorStringCombo": "MV Director - String Combo",
    "MVDirectorConnectedCombo": "MV Director - Connected Combo",
    "MVDirectorLoadTextFile": "MV Director - Load Text File",
    "MVDirectorSceneDebugSplitter": "MV Director - Scene Debug Splitter",
}

for _node_name, _node_class in NODE_CLASS_MAPPINGS.items():
    instrument_node_class(
        _node_class,
        NODE_DISPLAY_NAME_MAPPINGS.get(_node_name, _node_name),
    )

__all__ = ["NODE_CLASS_MAPPINGS", "NODE_DISPLAY_NAME_MAPPINGS"]
