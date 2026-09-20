"""Generate the six distributable MV Director workflows.

The video graphs deliberately start from the pinned Context Loop Ref2V Basic
workflow.  This preserves its recursive sampling, checkpoint, review, and
assembly wiring while replacing only the authoring and audio-policy edges
owned by MV Director.
"""

from __future__ import annotations

import argparse
import base64
import json
from pathlib import Path
import sys
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from core.h3_contract import (
    build_environment_definition,
    build_environment_retention,
)


CONTRACT_ID = "context-loop-0.6.9@9860a063784c8c23b58e00107f2180e0df3c43d9"
VIDEO_DENOISING_STEPS = 8
H3_DIFFUSION_MODEL = (
    "MiniMaxH3\\minimax_h3_ref2va_pruned_int8_convrot.safetensors"
)
H3_TEXT_ENCODER = (
    "MiniMaxH3\\qwen3vl_32b_minimax_h3_nvfp4_awq.safetensors"
)
H3_VIDEO_VAE = "MiniMaxH3\\minimax_h3_video_vae_fp16.safetensors"
H3_AUDIO_VAE = "MiniMaxH3\\minimax_h3_audio_vae_fp32.safetensors"
H3_ATTENTION_BACKEND = "comfy kitchen attention"
H3_REFERENCE_IMAGE_SIZE = "max"
REVIEW_ENABLED = False
OUTPUT_ASPECT_RATIO = "16:9 (Widescreen)"
OUTPUT_MEGAPIXELS = 0.4
OUTPUT_MULTIPLE = 32
TURBO_LORA_NAME = (
    "MiniMaxH3\\minimax_h3_ref2v_turbo_4step_v0.1_comfyui_bf16.safetensors"
)
TEXT_MODEL = "Qwen3-8B-Abliterated/qwen3-8b-abliterated-Q4_K_M.gguf"
VISION_MODEL = "Qwen3-VL-4B-Instruct/Qwen3-VL-4B-Instruct-Q4_K_M.gguf"
WHISPER_MODEL = "medium.pt"
CHARACTER_IMAGE = "image001_mikofox.jpg"
BACKGROUND_IMAGE = "image002_keinai.jpg"
FULL_MIX_AUDIO = "bgm_millennium_torii.mp3"
VOCAL_AUDIO = "bgm_millennium_torii_vocal.mp3"
LYRICS_BASENAME = "bgm_millennium_torii_lyrics.txt"
CHARACTER_HINT = (
    "狐巫女。狐耳、耳の先端は黒い。狐尻尾、尾の先端は白。"
    "白い足袋と、赤い鼻緒の黒い木下駄を着用する。"
    "下駄の木製台全体は黒色で、赤いのは鼻緒だけである。"
    "目尻は赤い化粧が施されている。"
    "眉毛は丸く、横に線が伸びない、色は髪と同じである。"
)
BACKGROUND_INSTRUCTION = (
    "人物、動物、キャラクター及び画面構成資料としての特徴は記述しない。"
    "場所、空間構成、建築、植生、時刻、天候及び環境照明だけを観察する。"
)

SOURCE_COLOR = "#232"
SOURCE_BGCOLOR = "#353"
PROCESS_COLOR = "#223"
PROCESS_BGCOLOR = "#335"
NOTE_COLOR = "#432"
NOTE_BGCOLOR = "#653"
README_COLOR = "#322"
README_BGCOLOR = "#533"

MODES = {
    "context_loop": {
        "number": 1,
        "label": "Context Loop",
        "planner_mode": "context_loop",
        "alignment": "off",
        "audio_profile": "Lip-sync to source audio",
        "summary": "Context Loopのsource-audio lockとLip-Sync Optionsを使用",
    },
    "audio_reference": {
        "number": 2,
        "label": "Audio Reference",
        "planner_mode": "audio_reference",
        "alignment": "source_scenes_to_plan",
        "audio_profile": "Use source soundtrack only",
        "summary": "Scene単位に切り出したvocalを固定<Audio 1>参照として使用",
    },
    "lyrics": {
        "number": 3,
        "label": "Lyrics",
        "planner_mode": "lyrics",
        "alignment": "off",
        "audio_profile": "Use source soundtrack only",
        "summary": "歌詞directiveだけで口形を誘導し追加lip-sync経路を使用しない",
    },
}


def _json_text(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, indent=2)


def _embedded(text: str) -> str:
    return base64.b64encode(text.encode("utf-8")).decode("ascii")


def _input(name: str, type_name: str, link: int | None = None) -> dict[str, Any]:
    return {"name": name, "type": type_name, "link": link}


def _widget_input(
    name: str, type_name: str, link: int | None = None
) -> dict[str, Any]:
    return {
        "name": name,
        "type": type_name,
        "link": link,
        "widget": {"name": name},
    }


def _output(
    name: str, type_name: str, links: list[int] | None = None
) -> dict[str, Any]:
    return {"name": name, "type": type_name, "links": links}


def _node(
    node_id: int,
    type_name: str,
    pos: tuple[int, int],
    size: tuple[int, int],
    title: str,
    *,
    inputs: list[dict[str, Any]] | None = None,
    outputs: list[dict[str, Any]] | None = None,
    widgets: list[Any] | None = None,
    order: int | None = None,
    mode: int = 0,
) -> dict[str, Any]:
    return {
        "id": node_id,
        "type": type_name,
        "pos": list(pos),
        "size": list(size),
        "flags": {},
        "order": node_id if order is None else order,
        "mode": mode,
        "inputs": inputs or [],
        "outputs": outputs or [],
        "title": title,
        "properties": {"Node name for S&R": type_name},
        "widgets_values": widgets or [],
    }


def _note(node_id: int, pos: tuple[int, int], title: str, text: str) -> dict[str, Any]:
    return _node(
        node_id,
        "Note",
        pos,
        (960, 280),
        title,
        widgets=[text],
    )


def _set_palette(
    node: dict[str, Any], color: str, bgcolor: str
) -> dict[str, Any]:
    node["color"] = color
    node["bgcolor"] = bgcolor
    return node


def _markdown_note(
    node_id: int,
    pos: tuple[int, int],
    size: tuple[int, int],
    title: str,
    text: str,
    *,
    readme: bool = False,
    order: int | None = None,
) -> dict[str, Any]:
    node = _node(
        node_id,
        "MarkdownNote",
        pos,
        size,
        title,
        widgets=[text],
        order=order,
    )
    node["properties"] = {
        "ue_properties": {
            "widget_ue_connectable": {},
            "version": "7.8",
            "input_ue_unconnectable": {},
        }
    }
    node["widgets_values_named"] = {"text": text}
    return _set_palette(
        node,
        README_COLOR if readme else NOTE_COLOR,
        README_BGCOLOR if readme else NOTE_BGCOLOR,
    )


def _workflow_label(
    node_id: int,
    pos: tuple[int, int],
    size: tuple[int, int],
    title: str,
    *,
    order: int | None = None,
) -> dict[str, Any]:
    node = _node(
        node_id,
        "Label (rgthree)",
        pos,
        size,
        title,
        order=order,
    )
    node["flags"] = {"allow_interaction": True}
    node["properties"] = {
        "fontSize": 48,
        "fontFamily": "Arial",
        "fontColor": "#00ffff",
        "textAlign": "left",
        "backgroundColor": "transparent",
        "padding": 0,
        "borderRadius": 0,
        "angle": 0,
        "ue_properties": {
            "widget_ue_connectable": {},
            "input_ue_unconnectable": {},
            "version": "7.8",
        },
    }
    return _set_palette(node, "#fff0", "#fff0")


def _shared_seed_node(node_id: int, pos: tuple[int, int]) -> dict[str, Any]:
    node = _set_palette(
        _node(
            node_id,
            "MVDirectorSeed32",
            pos,
            (330, 318),
            "",
            inputs=[
                _widget_input("mode", "COMBO"),
                _widget_input("seed", "INT"),
            ],
            outputs=[_output("seed", "INT")],
            widgets=["fixed", 42],
        ),
        SOURCE_COLOR,
        SOURCE_BGCOLOR,
    )
    node.pop("title", None)
    return node


def _new_workflow() -> dict[str, Any]:
    return {
        "last_node_id": 0,
        "last_link_id": 0,
        "nodes": [],
        "links": [],
        "groups": [],
        "config": {},
        "extra": {"ds": {"scale": 0.72, "offset": [40, 40]}},
        "version": 0.4,
    }


def _node_by_id(workflow: dict[str, Any], node_id: int) -> dict[str, Any]:
    return next(node for node in workflow["nodes"] if int(node["id"]) == node_id)


def _input_index(node: dict[str, Any], name: str) -> int:
    for index, item in enumerate(node.get("inputs", [])):
        if item.get("name") == name:
            return index
    raise KeyError(f"{node['type']} has no workflow input {name!r}")


def _ensure_widget_inputs(
    node: dict[str, Any], fields: tuple[tuple[str, str], ...]
) -> None:
    """Add connectable widget sockets missing from an older saved workflow."""

    existing = {item.get("name") for item in node.get("inputs", [])}
    for name, type_name in fields:
        if name not in existing:
            node.setdefault("inputs", []).append(_widget_input(name, type_name))


def _connect(
    workflow: dict[str, Any],
    origin_id: int,
    origin_slot: int,
    target_id: int,
    target_name: str,
    type_name: str,
) -> int:
    workflow["last_link_id"] = int(workflow.get("last_link_id", 0)) + 1
    link_id = workflow["last_link_id"]
    origin = _node_by_id(workflow, origin_id)
    target = _node_by_id(workflow, target_id)
    target_slot = _input_index(target, target_name)
    target["inputs"][target_slot]["link"] = link_id
    links = origin["outputs"][origin_slot].get("links")
    if links is None:
        links = []
        origin["outputs"][origin_slot]["links"] = links
    links.append(link_id)
    workflow["links"].append(
        [link_id, origin_id, origin_slot, target_id, target_slot, type_name]
    )
    return link_id


def _remove_nodes(workflow: dict[str, Any], node_ids: set[int]) -> None:
    removed_links = {
        int(link[0])
        for link in workflow["links"]
        if int(link[1]) in node_ids or int(link[3]) in node_ids
    }
    workflow["nodes"] = [
        node for node in workflow["nodes"] if int(node["id"]) not in node_ids
    ]
    workflow["links"] = [
        link for link in workflow["links"] if int(link[0]) not in removed_links
    ]
    for node in workflow["nodes"]:
        for item in node.get("inputs", []):
            if item.get("link") in removed_links:
                item["link"] = None
        for item in node.get("outputs", []):
            if item.get("links"):
                item["links"] = [
                    value for value in item["links"] if value not in removed_links
                ] or None


def _disconnect_input(
    workflow: dict[str, Any], target_id: int, target_name: str
) -> None:
    target = _node_by_id(workflow, target_id)
    target_slot = _input_index(target, target_name)
    link_id = target["inputs"][target_slot].get("link")
    if link_id is None:
        return
    workflow["links"] = [
        link for link in workflow["links"] if int(link[0]) != int(link_id)
    ]
    target["inputs"][target_slot]["link"] = None
    for node in workflow["nodes"]:
        for output in node.get("outputs", []):
            if output.get("links"):
                output["links"] = [
                    value
                    for value in output["links"]
                    if value is not None and int(value) != int(link_id)
                ] or None


def _fallback_plan(mode: str) -> dict[str, Any]:
    audio_line = {
        "context_loop": (
            "<Subject 1> performs visible lip movements synchronized to the "
            "locked source vocal."
        ),
        "audio_reference": (
            "<Subject 1> performs visible lip movements synchronized to <Audio 1>."
        ),
        "lyrics": (
            "<Subject 1> performs visible lip movements to "
            "<d>[Japanese]千年鳥居をくぐるそなたよ</d>."
        ),
    }[mode]
    scene: dict[str, Any] = {
        "id": "scene_0001",
        "length": 243,
        "prompt": [
            "subject_definitions:",
            "<Picture 1> defines <Subject 1>, the performer in the reference image.",
            build_environment_definition(
                "<Picture 2>",
                "A moonlit shrine approach in a forest with a red torii gate.",
            ),
            "",
            "summary:",
            "[reference generation] A moonlit performance at a shrine approach.",
            "",
            "retention_analysis:",
            "<Subject 1>: fully_preserved - preserve identity, clothing, and proportions.",
            "<Picture 1>: fully_preserved - preserve the visible performer design.",
            build_environment_retention("<Picture 2>"),
            "",
            "detailed_description:",
            "[Shot 1] <Subject 1> walks toward the torii gate and sings.",
            audio_line,
            "",
            "overall_soundscape:",
            "Preserve the selected music-video soundtrack policy.",
            "",
            "non_diegetic_music:",
            "No additional generated music is requested.",
        ],
        "context_length": 0,
        "audio_context_length": 22,
    }
    if mode == "context_loop":
        scene.update(
            {
                "source_reference": "off",
                "generated_continuity": "off",
                "source_audio_target": "locked",
            }
        )
    return {
        "prompt_prefix": ["Render every scene as photorealistic live-action cinema."],
        "defaults": {"steps": VIDEO_DENOISING_STEPS},
        "shots": [scene],
    }


def _lyrics_text() -> str:
    path = ROOT / "assets" / "bgm" / LYRICS_BASENAME
    return path.read_text(encoding="utf-8")


def _load_text_node(
    node_id: int,
    pos: tuple[int, int],
    title: str,
    text: str,
    basename: str,
    size: tuple[int, int] = (380, 180),
) -> dict[str, Any]:
    metadata = _json_text(
        {"name": basename, "size": len(text.encode("utf-8")), "type": "text/plain"}
    )
    return _node(
        node_id,
        "MVDirectorLoadTextFile",
        pos,
        size,
        title,
        outputs=[_output("text", "STRING")],
        widgets=[_embedded(text), basename, metadata],
    )


def _timing_node(
    node_id: int,
    pos: tuple[int, int],
    size: tuple[int, int] = (380, 100),
) -> dict[str, Any]:
    return _node(
        node_id,
        "MVDirectorH3TimingProfile",
        pos,
        size,
        "H3 Timing Profile",
        outputs=[
            _output("timing_profile", "MV_DIRECTOR_H3_TIMING_PROFILE"),
            _output("profile_json", "STRING"),
            _output("status", "STRING"),
        ],
        widgets=[CONTRACT_ID],
    )


def _lyric_node(node_id: int, pos: tuple[int, int]) -> dict[str, Any]:
    return _node(
        node_id,
        "MVDirectorLyricSegmentation",
        pos,
        (460, 430),
        "Lyric Segmentation",
        inputs=[
            _input("vocal_audio", "AUDIO"),
            _input("lyrics_text", "STRING"),
            _input("h3_timing_profile", "MV_DIRECTOR_H3_TIMING_PROFILE"),
        ],
        outputs=[
            _output("template_emd", "STRING"),
            _output("srt_text", "STRING"),
            _output("timeline", "MV_DIRECTOR_TIMELINE"),
            _output("status", "STRING"),
        ],
        widgets=[WHISPER_MODEL, "ja", 10000, 0, "reuse", False],
    )


def _save_text_node(
    node_id: int, pos: tuple[int, int], title: str, prefix: str, format_name: str
) -> dict[str, Any]:
    return _node(
        node_id,
        "SaveText",
        pos,
        (350, 160),
        title,
        inputs=[_input("text", "STRING")],
        outputs=[_output("text", "STRING")],
        widgets=[prefix, format_name],
    )


def build_plan_workflow(mode: str) -> dict[str, Any]:
    spec = MODES[mode]
    workflow = _new_workflow()
    lyrics = _lyrics_text()
    workflow["nodes"] = [
        _note(
            1,
            (40, 20),
            f"MV Director • {spec['label']} • Plan / Compiler",
            (
                f"{spec['summary']}。\n\n"
                "1. 人物参照画像、背景画像、vocal、歌詞、Vision/Text GGUF、Whisperを確認します。\n"
                "2. QueueしてEMD、SRT、Context Loop Planを出力します。\n"
                f"3. 保存された {mode}_plan_*.txt を同方式のVideo workflowへ読み込みます。\n\n"
                f"Baseline: {CONTRACT_ID}"
            ),
        ),
        _node(
            2,
            "LoadImage",
            (40, 360),
            (340, 360),
            "Character Reference Image",
            outputs=[_output("IMAGE", "IMAGE"), _output("MASK", "MASK")],
            widgets=[CHARACTER_IMAGE],
        ),
        _node(
            3,
            "MVDirectorImageToSubjectEMD",
            (440, 330),
            (500, 800),
            "Character Vision / Subject EMD",
            inputs=[_input("image", "IMAGE")],
            outputs=[
                _output("emd_fragment", "STRING"),
                _output("reference_bindings", "MV_DIRECTOR_REFERENCE_BINDINGS"),
                _output("image", "IMAGE"),
                _output("observations_json", "STRING"),
            ],
            widgets=[
                VISION_MODEL,
                "subject_only",
                CHARACTER_HINT,
                "",
                "lock_identity",
                "warn",
                "manual",
                "person",
                1,
                1024,
                1024,
                0.1,
                0.9,
                1.05,
                -1,
                512,
                16384,
                True,
                "q8_0",
                True,
                False,
                1,
                "fixed",
                "reuse",
                "<Picture 1>",
            ],
        ),
        _node(
            4,
            "LoadAudio",
            (40, 820),
            (340, 110),
            "Vocal Stem",
            outputs=[_output("AUDIO", "AUDIO")],
            widgets=[VOCAL_AUDIO],
        ),
        _load_text_node(5, (40, 980), "Plain Lyrics", lyrics, LYRICS_BASENAME),
        _timing_node(6, (40, 1210)),
        _lyric_node(7, (480, 1210)),
        _node(
            8,
            "MVDirectorDirectionEnhancer",
            (1040, 300),
            (480, 640),
            "Direction Enhancer",
            inputs=[
                _input("concept_emd", "STRING"),
                _input("scene_emd", "STRING"),
            ],
            outputs=[
                _output("direction", "MV_DIRECTOR_DIRECTION"),
                _output("direction_emd_preview", "STRING"),
                _output("status", "STRING"),
            ],
            widgets=[
                "profile",
                "",
                "anime_emotional_mv",
                "anime_emotional_mv",
                "anime_emotional_mv",
                TEXT_MODEL,
                "",
                768,
                0.2,
                0.9,
                1.05,
                -1,
                512,
                16384,
                True,
                "q8_0",
                True,
                False,
                1,
                "fixed",
                "reuse",
                "",
                "",
            ],
        ),
        _node(
            9,
            "MVDirectorTimelinePlanner",
            (1040, 1060),
            (520, 760),
            "Timeline Planner",
            inputs=[
                _input("template_emd", "STRING"),
                _input("concept_emd", "STRING"),
                _input("scene_emd", "STRING"),
                _input("direction", "MV_DIRECTOR_DIRECTION"),
                _input("model_name_override", "STRING"),
            ],
            outputs=[
                _output("emd_text", "STRING"),
                _output("emd", "MV_DIRECTOR_EMD"),
                _output("status", "STRING"),
            ],
            widgets=[
                spec["planner_mode"],
                "サブジェクト1",
                1,
                TEXT_MODEL,
                "auto",
                1536,
                0.1,
                0.9,
                1.05,
                -1,
                256,
                16384,
                True,
                "q8_0",
                True,
                False,
                1,
                "fixed",
                3,
                "reuse",
                False,
            ],
        ),
        _node(
            10,
            "MVDirectorEMDCompiler",
            (1660, 1060),
            (500, 650),
            "Ref2VA EMD Compiler",
            inputs=[
                _input("emd_text", "STRING"),
                _input("h3_timing_profile", "MV_DIRECTOR_H3_TIMING_PROFILE"),
            ],
            outputs=[
                _output("plan_json", "STRING"),
                _output("required_references", "MV_DIRECTOR_REQUIRED_REFERENCES"),
                _output("status", "STRING"),
            ],
            widgets=[
                "ja_to_en",
                TEXT_MODEL,
                "auto",
                VIDEO_DENOISING_STEPS,
                4096,
                0.0,
                0.9,
                1.05,
                -1,
                256,
                16384,
                True,
                "q8_0",
                True,
                False,
                1,
                "fixed",
                "reuse",
            ],
        ),
        _save_text_node(
            11,
            (2260, 1040),
            "Save Context Loop Plan (.txt handoff)",
            f"mv_director/{mode}_plan",
            "txt",
        ),
        _save_text_node(
            12,
            (2260, 1260),
            "Save Completed EMD",
            f"mv_director/{mode}_emd",
            "md",
        ),
        _save_text_node(
            13,
            (2260, 1480),
            "Save SRT body (.txt; rename to .srt)",
            f"mv_director/{mode}_lyrics",
            "txt",
        ),
        _node(
            14,
            "LoadImage",
            (40, 1740),
            (340, 360),
            "Background Reference Image",
            outputs=[_output("IMAGE", "IMAGE"), _output("MASK", "MASK")],
            widgets=[BACKGROUND_IMAGE],
        ),
        _node(
            15,
            "MVDirectorImageToSubjectEMD",
            (440, 1700),
            (500, 800),
            "Background Vision (Scene Only)",
            inputs=[_input("image", "IMAGE")],
            outputs=[
                _output("emd_fragment", "STRING"),
                _output("reference_bindings", "MV_DIRECTOR_REFERENCE_BINDINGS"),
                _output("image", "IMAGE"),
                _output("observations_json", "STRING"),
            ],
            widgets=[
                VISION_MODEL,
                "scene_only",
                "",
                BACKGROUND_INSTRUCTION,
                "lock_identity",
                "warn",
                "manual",
                "location",
                2,
                1024,
                1024,
                0.1,
                0.9,
                1.05,
                -1,
                512,
                16384,
                True,
                "q8_0",
                True,
                False,
                1,
                "fixed",
                "reuse",
                "<Picture 2>",
            ],
        ),
    ]
    workflow["last_node_id"] = 15
    workflow["extra"]["mv_director"] = {
        "kind": "plan_compiler",
        "lip_sync_mode": mode,
        "contract": CONTRACT_ID,
    }
    _connect(workflow, 2, 0, 3, "image", "IMAGE")
    _connect(workflow, 4, 0, 7, "vocal_audio", "AUDIO")
    _connect(workflow, 5, 0, 7, "lyrics_text", "STRING")
    _connect(
        workflow,
        6,
        0,
        7,
        "h3_timing_profile",
        "MV_DIRECTOR_H3_TIMING_PROFILE",
    )
    _connect(workflow, 3, 0, 8, "concept_emd", "STRING")
    _connect(workflow, 14, 0, 15, "image", "IMAGE")
    _connect(workflow, 15, 0, 8, "scene_emd", "STRING")
    _connect(workflow, 7, 0, 9, "template_emd", "STRING")
    _connect(workflow, 3, 0, 9, "concept_emd", "STRING")
    _connect(workflow, 15, 0, 9, "scene_emd", "STRING")
    _connect(workflow, 8, 0, 9, "direction", "MV_DIRECTOR_DIRECTION")
    _connect(workflow, 9, 0, 10, "emd_text", "STRING")
    _connect(
        workflow,
        6,
        0,
        10,
        "h3_timing_profile",
        "MV_DIRECTOR_H3_TIMING_PROFILE",
    )
    _connect(workflow, 10, 0, 11, "text", "STRING")
    _connect(workflow, 9, 0, 12, "text", "STRING")
    _connect(workflow, 7, 1, 13, "text", "STRING")
    return _decorate_plan_workflow(workflow, mode)


def _decorate_plan_workflow(
    workflow: dict[str, Any], mode: str
) -> dict[str, Any]:
    """Apply the documented layout and palette established by workflow 01."""

    spec = MODES[mode]
    _remove_nodes(workflow, {1})
    layout: dict[int, tuple[list[float], list[float], int]] = {
        2: ([40, 340], [340, 360], 1),
        14: ([40, 750], [340, 360], 2),
        6: ([450, 180], [500, 100], 11),
        4: ([40, 2010], [330, 140], 12),
        5: ([40, 1780], [330, 180], 0),
        3: ([450, 330], [500, 800], 14),
        15: ([450, 1180], [500, 800], 15),
        7: ([453.2777777777778, 2040], [490, 240], 16),
        8: ([1020, 330], [500, 720], 17),
        9: ([1020, 1120], [500, 620], 19),
        10: ([1590.631977777778, 1118.0316289243062], [500, 510], 20),
        11: ([2170.631977777781, 1118.0316289243062], [350, 170], 22),
        12: ([2170.631977777781, 1338.0316289243062], [350, 170], 21),
        13: ([2170.631977777781, 1558.0316289243062], [350, 170], 18),
    }
    source_ids = {2, 4, 5, 14}
    for node_id, (pos, size, order) in layout.items():
        node = _node_by_id(workflow, node_id)
        node["pos"] = pos
        node["size"] = size
        node["order"] = order
        _set_palette(
            node,
            SOURCE_COLOR if node_id in source_ids else PROCESS_COLOR,
            SOURCE_BGCOLOR if node_id in source_ids else PROCESS_BGCOLOR,
        )

    seed = _shared_seed_node(16, (40, 1410))
    seed["size"] = [330, 318]
    seed["order"] = 9
    workflow["nodes"].append(seed)
    for target_id in (3, 8, 9, 10, 15):
        target = _node_by_id(workflow, target_id)
        _ensure_widget_inputs(target, (("seed", "INT"),))
        _connect(workflow, 16, 0, target_id, "seed", "INT")

    mode_readme = {
        "context_loop": (
            "この版はContext Loop標準リップシンクを使用します。"
            "VRAM 8GB環境では動画生成段階が停止しやすいため、"
            "Audio Reference版又はLyrics版も検討してください。"
        ),
        "audio_reference": (
            "この版はSceneごとのvocal区間を<Audio 1>として参照し、"
            "Context Loopのsource-audio lockを使用しません。"
        ),
        "lyrics": (
            "この版は歌詞directiveだけで口形を誘導し、追加の音声参照又は"
            "Context Loop Lip-Sync Optionsを使用しません。"
        ),
    }[mode]
    readme = (
        "このワークフローはMV生成を自動化する言語フロントエンドです。"
        "人物・背景画像、歌詞、ボーカルステムから、動画生成段階で使用する"
        "Context Loop Plan JSONを生成します。\n\n"
        "Plan / CompilerとVideoは意図的に分離しています。生成したPlanを固定したまま"
        "Video段階だけを再Queueでき、動画側で停止してもVision、Whisper、Planner及び"
        "Compilerを再実行せずに済みます。\n\n"
        + mode_readme
    )
    output_number = int(spec["number"]) * 2
    output_note = (
        "ComfyUI\\output\\mv_director に次の三ファイルを保存します。\n\n"
        "|名称|説明|\n|----|----|\n"
        f"|{mode}_plan_XXXXX.txt|動画生成Plan JSON|\n"
        f"|{mode}_emd_XXXXX.md|Compiler入力前の完成EMD|\n"
        f"|{mode}_lyrics_XXXXX.txt|拡張子を.srtへ変更できる字幕本文|\n\n"
        "対応するVideo workflowへ人物・背景画像、vocal、full mixと保存済みPlanを"
        "指定してください。\n\n"
        f"> ComfyUI-MV-Director\\workflows\\{output_number:02d}_video_{mode}.json"
    )
    notes = [
        _workflow_label(
            17,
            (-350.01750520278983, 53.858399792818155),
            (1149.65625, 48),
            f"MV-Director {spec['label']} Lip-Sync 言語ワークフロー",
            order=6,
        ),
        _markdown_note(
            18,
            (-350, 340),
            (350, 350),
            "1. キャラクター立ち絵を設定",
            (
                "全身が見える人物参照を指定します。正面一枚でも使用できますが、"
                "背面等の見えない情報はMiniMax H3の概念で補完されます。\n\n"
                "複数構図を一枚へ置く場合は、同一人物のreference sheetとして"
                "判読できる余白と統一した衣装を保ってください。"
            ),
            order=7,
        ),
        _markdown_note(
            19,
            (-340, 760),
            (350, 350),
            "2. 背景画像を設定",
            (
                "MVの舞台となる背景画像を指定します。人物参照とは別Pictureとして"
                "扱い、建築、植生、地形及び空間同一性を補助します。\n\n"
                "中央下部に人物が動ける空間のある構図は、H3が移動可能領域を"
                "認識しやすくなります。"
            ),
            order=3,
        ),
        _markdown_note(
            20,
            (-320, 1420),
            (330, 110),
            "3. シードの設定",
            (
                "共有seedをVision、Direction、Planner、Compilerへ渡します。"
                "比較検証ではfixedにすると、設定変更による差を追跡しやすくなります。"
            ),
            order=10,
        ),
        _markdown_note(
            21,
            (-320, 1780),
            (330, 110),
            "4. 歌詞の設定",
            (
                "歌詞をUTF-8テキストで指定します。歌詞とvocalからWhisper及び"
                "整列アルゴリズムがScene時間枠とTemplate EMDを生成します。"
            ),
            order=4,
        ),
        _markdown_note(
            22,
            (-330, 2010),
            (330, 130),
            "5. ボーカルステムの設定",
            (
                "ボーカルだけの音源を指定します。楽器を含むfull mixは歌詞整列の"
                "入力にしません。Suno等で分離したvocal stemを使用できます。"
            ),
            order=13,
        ),
        _markdown_note(
            23,
            (2540, 1120),
            (370, 600),
            "6. 出力の確認",
            output_note,
            order=5,
        ),
        _markdown_note(
            24,
            (-350, 150),
            (730, 140),
            "README",
            readme,
            readme=True,
            order=8,
        ),
    ]
    workflow["nodes"].extend(notes)
    workflow["nodes"].sort(key=lambda item: (int(item.get("order", 0)), int(item["id"])))
    workflow["last_node_id"] = 24
    workflow["extra"]["ds"] = {
        "scale": 0.9583200000000043,
        "offset": [916.7349516147216, -542.3761388593111],
    }
    return workflow


def _decorate_video_workflow(
    workflow: dict[str, Any], mode: str
) -> dict[str, Any]:
    """Apply the compact layout and palette established by workflow 02."""

    spec = MODES[mode]
    _remove_nodes(workflow, {31, 50, 51, 52, 53, 54, 55, 56, 57, 58})
    layout: dict[int, tuple[list[float], list[float], int, str, str]] = {
        1: ([1910, 160], [580, 130], 3, "#223", "#335"),
        2: ([1920, 350], [570, 150], 2, "#223", "#335"),
        3: ([3790, 160], [360, 108], 4, "#223", "#335"),
        4: ([1920, 560], [570, 100], 1, "#223", "#335"),
        5: ([1925.5882185973674, 721.4706187338029], [560, 100], 0, "#223", "#335"),
        7: ([1380, 500], [360, 256], 31, "#223", "#335"),
        8: ([2600, 160], [460, 400], 32, "#223", "#335"),
        10: ([3240, 1090], [360, 132], 33, "#223", "#335"),
        11: ([2600, 1130], [530, 364], 35, "#223", "#335"),
        12: ([3230, 160], [420, 260], 36, "#223", "#335"),
        13: ([3240, 680], [360, 132], 25, "#223", "#335"),
        14: ([3230, 520], [360, 104], 37, "#223", "#335"),
        15: ([3240, 860], [360, 176], 34, "#223", "#335"),
        16: ([3800, 330], [360, 326], 38, "#323", "#535"),
        17: ([3790, 730], [360, 104], 39, "#223", "#335"),
        18: ([3790, 880], [360, 104], 40, "#223", "#335"),
        19: ([4260, 160], [420, 250], 41, "#223", "#335"),
        20: ([4260, 510], [460, 220], 42, "#223", "#335"),
        21: ([4963.076666985372, 1382.7972561496085], [440, 360], 45, "#223", "#335"),
        22: ([1930, 1060], [360, 108], 23, "#232", "#353"),
        23: ([4980.839160839156, 1103.6362782725091], [420, 220], 44, "#223", "#335"),
        24: ([240, 190], [1000, 1090], 29, "#223", "#335"),
        26: ([-780, 570], [350, 340], 5, "#232", "#353"),
        28: ([4820, 160], [760, 880], 43, "#223", "#335"),
        29: ([1380, 200], [360, 236], 30, "#223", "#335"),
        30: ([-270, 180], [360, 152], 28, "#223", "#335"),
        32: ([-780, 1590], [360, 136], 8, "#232", "#353"),
        33: ([-780, 1400], [360, 136], 7, "#232", "#353"),
        35: ([-210, 1260], [340, 100], 19, "#233", "#355"),
        37: ([-240, 1430], [420, 300], 22, "#233", "#355"),
        38: ([830, 1450], [380, 220], 27, "#223", "#335"),
        39: ([-780, 100], [350, 180], 6, "#232", "#353"),
        44: ([1930, 890], [560, 90], 21, "#223", "#335"),
        45: ([-780, 960], [350, 360], 9, "#232", "#353"),
        47: ([-780, 350], [360, 160], 13, "#232", "#353"),
        48: ([291.09965407461857, 1448.9001519166202], [420, 250], 24, "#233", "#355"),
        49: ([-235.7552796705333, 855.0127906997371], [400, 330], 18, "#232", "#353"),
    }
    if mode == "context_loop":
        layout[40] = ([-260, 430], [400, 260], 26, "#223", "#335")
    elif mode == "audio_reference":
        layout.update(
            {
                34: ([-780, 1810], [360, 180], 46, "#232", "#353"),
                36: ([-240, 1810], [490, 240], 47, "#233", "#355"),
                40: ([2600, 1530], [530, 210], 48, "#223", "#335"),
            }
        )
    for node_id, (pos, size, order, color, bgcolor) in layout.items():
        if not any(int(node["id"]) == node_id for node in workflow["nodes"]):
            continue
        node = _node_by_id(workflow, node_id)
        node["pos"] = pos
        node["size"] = size
        node["order"] = order
        _set_palette(node, color, bgcolor)

    readme = (
        "このワークフローは保存済みContext Loop Plan JSONからMiniMax H3の"
        "Sceneを生成し、Review、checkpoint及び最終連結を行うVideo段階です。\n\n"
        "Plan / Compiler段階を分離しているため、同じ演出計画を固定したまま"
        "Video段階だけを再Queueできます。動画生成又はReviewで停止しても、Vision、Whisper、"
        "Direction、Planner及びCompilerを再実行する必要はありません。\n\n"
        f"方式: {spec['summary']}。"
    )
    readme_node = _markdown_note(
        50,
        (-1150, -90),
        (730, 140),
        "README",
        readme,
        readme=True,
        order=11,
    )

    plan_note = (
        f"対応する {int(spec['number']) * 2 - 1:02d}_plan_compiler_{mode}.json "
        f"が保存した {mode}_plan_XXXXX.txt をCompiled Plan JSONへ指定します。\n\n"
        "Production PlanはPlanのScene/Shot、prompt、frame数を読み取ります。"
        "Planを変更したい場合はこのworkflowでJSONを手編集せず、前段から再生成します。"
    )
    audio_mode_note = {
        "context_loop": (
            "full mixとvocalを別々に指定します。vocalはContext Loop Lip-Sync "
            "Optionsへ渡し、full mixは最終soundtrackとして保持します。"
        ),
        "audio_reference": (
            "前段と同じ歌詞・vocalでLyric Segmentation cacheを再利用し、"
            "各Sceneのvocal区間を<Audio 1>へ渡します。"
        ),
        "lyrics": (
            "full mixとvocalを別々に指定します。口形はPlan内の歌詞directiveで"
            "誘導し、追加lip-sync経路は使用しません。"
        ),
    }[mode]
    notes = [
        _workflow_label(
            51,
            (-1150, -190),
            (1149.65625, 48),
            f"MV-Director {spec['label']} Lip-Sync 動画ワークフロー",
            order=10,
        ),
        _markdown_note(
            52,
            (-1150, 100),
            (350, 180),
            "1. プランJSONを指定",
            plan_note,
            order=12,
        ),
        _markdown_note(
            54,
            (-1150, 350),
            (350, 160),
            "2. 出力解像度の指定",
            (
                "調整・ドラフト段階では0.4MPを推奨します。本番時も幅と高さは"
                "32の倍数を維持してください。\n\n"
                "|メガピクセル|アスペクト比|目安|\n|----|----|----|\n"
                "|0.4|4:3|VGA|\n|0.9|16:9|HD|\n|2.0|16:9|FHD|"
            ),
            order=20,
        ),
        _markdown_note(
            55,
            (-1150, 570),
            (350, 160),
            "3. キャラクター画像の指定",
            (
                "前段で指定した人物素材と同じ画像を指定します。"
                "<Picture 1>として人物の視覚同一性に使用されます。"
            ),
            order=14,
        ),
        _markdown_note(
            56,
            (-1150, 960),
            (350, 160),
            "4. 背景画像の指定",
            (
                "前段で指定した背景素材と同じ画像を指定します。"
                "<Picture 2>として建築、植生、地形及び空間同一性に使用されます。"
            ),
            order=15,
        ),
        _markdown_note(
            57,
            (-1150, 1400),
            (350, 130),
            "5. ボーカルステムの指定",
            (
                audio_mode_note
                + "\n\nAudio Pad PairはPlanの最終frame境界までPCM無音を追加します。"
            ),
            order=16,
        ),
        _markdown_note(
            58,
            (-1150, 1590),
            (350, 130),
            "6. フルミックスの指定",
            (
                "ボーカルと伴奏を含む完成音源を指定します。"
                "Scene生成後、最終的にこの音源をsoundtrackとして使用します。"
            ),
            order=17,
        ),
    ]
    workflow["nodes"].append(readme_node)
    workflow["nodes"].extend(notes)
    workflow["nodes"].sort(key=lambda item: (int(item.get("order", 0)), int(item["id"])))
    workflow["last_node_id"] = max(int(node["id"]) for node in workflow["nodes"])
    group_height = 2320 if mode == "audio_reference" else 1712
    workflow["groups"] = [
        {"id": 1, "title": "01 • PROJECT & SCENES", "bounding": [-350, 70, 2200, group_height], "color": "#315566", "flags": {}},
        {"id": 2, "title": "02 • MODELS & INPUTS", "bounding": [1870, 70, 670, 1710], "color": "#393f58", "flags": {}},
        {"id": 3, "title": "03 • PREPARE SCENE", "bounding": [2560, 70, 610, 1710], "color": "#394c49", "flags": {}},
        {"id": 4, "title": "04 • PREPARE SCENE", "bounding": [3190, 70, 530, 1710], "color": "#393f58", "flags": {}},
        {"id": 5, "title": "05 • SAMPLE & DECODE", "bounding": [3740, 70, 460, 1710], "color": "#394c49", "flags": {}},
        {"id": 6, "title": "06 • SAVE & REVIEW", "bounding": [4220, 70, 540, 1710], "color": "#393f58", "flags": {}},
        {"id": 7, "title": "07 • REVIEW & CONTINUE", "bounding": [4780, 70, 840, 1700], "color": "#394c49", "flags": {}},
    ]
    workflow["extra"]["ds"] = {
        "scale": 0.32287908799076204,
        "offset": [-402.2806842890321, 876.0599049625927],
    }
    return workflow


def _audio_pad_node(node_id: int, alignment: str) -> dict[str, Any]:
    return _node(
        node_id,
        "MVDirectorAudioPadPair",
        (1500, 2580),
        (420, 300),
        "Audio Pad Pair",
        inputs=[
            _input("audio_a", "AUDIO"),
            _input("audio_b", "AUDIO"),
            _input("timeline", "MV_DIRECTOR_TIMELINE"),
            _input("h3_timing_profile", "MV_DIRECTOR_H3_TIMING_PROFILE"),
            _input("plan_json", "STRING"),
        ],
        outputs=[
            _output("padded_audio_a", "AUDIO"),
            _output("padded_audio_b", "AUDIO"),
            _output("status", "STRING"),
            _output("reference_audio_b", "AUDIO"),
        ],
        widgets=[0, 0, "end", alignment],
    )


def _audio_tracks_node(node_id: int) -> dict[str, Any]:
    return _node(
        node_id,
        "MiniMaxH3AudioTracks",
        (2460, 2580),
        (380, 220),
        "H3 Audio Tracks",
        inputs=[
            _input("full_mix", "AUDIO"),
            _input("vocals", "AUDIO"),
            _input("instrumental", "AUDIO"),
        ],
        outputs=[
            _output("source_timeline", "H3_SOURCE_TIMELINE"),
            _output("status", "STRING"),
        ],
    )


def _scene_debug_splitter_node(
    node_id: int,
    pos: tuple[int, int] = (1980, 2580),
) -> dict[str, Any]:
    return _node(
        node_id,
        "MVDirectorSceneDebugSplitter",
        pos,
        (420, 250),
        "Scene Debug Splitter",
        inputs=[
            _input("plan_json", "STRING"),
            _input("vocal_audio", "AUDIO"),
            _input("full_mix_audio", "AUDIO"),
            _widget_input("enable", "BOOLEAN"),
            _widget_input("scene_start", "INT"),
            _widget_input("scene_length", "INT"),
        ],
        outputs=[
            _output("plan_json", "STRING"),
            _output("vocal_audio", "AUDIO"),
            _output("full_mix_audio", "AUDIO"),
        ],
        widgets=[False, 1, 1],
    )


def build_video_workflow(mode: str, base_path: Path) -> dict[str, Any]:
    spec = MODES[mode]
    workflow = json.loads(base_path.read_text(encoding="utf-8"))
    # The compact workflow uses the modern Plan directly.  The legacy prompt
    # editor, recovery manifest loader, recovery assembler, and detached text
    # encoder are intentionally absent from the distributable graph.
    _remove_nodes(workflow, {6, 9, 25, 27})
    _disconnect_input(workflow, 22, "model")
    workflow["last_node_id"] = max(int(node["id"]) for node in workflow["nodes"])
    workflow["last_link_id"] = max(int(link[0]) for link in workflow["links"])
    _connect(workflow, 24, 0, 29, "plan", "H3_CHAIN_PLAN")

    _node_by_id(workflow, 1)["widgets_values"] = [H3_DIFFUSION_MODEL, "default"]
    _node_by_id(workflow, 2)["widgets_values"] = [
        H3_TEXT_ENCODER,
        "minimax",
        "default",
    ]
    _node_by_id(workflow, 4)["widgets_values"] = [H3_VIDEO_VAE]
    _node_by_id(workflow, 5)["widgets_values"] = [H3_AUDIO_VAE]
    _node_by_id(workflow, 22)["widgets_values"] = [H3_ATTENTION_BACKEND]
    review = _node_by_id(workflow, 28)
    review["widgets_values"][0] = REVIEW_ENABLED

    note = _node_by_id(workflow, 31)
    note["title"] = f"START HERE • MV Director • {spec['label']}"
    preparation = (
        "full mix、vocal stem、歌詞、人物・背景参照画像、Whisper"
        if mode == "audio_reference"
        else "full mix、vocal stem、人物・背景参照画像"
    )
    segmentation_note = (
        "4. Plan/Compiler側と同じ歌詞・vocalを使うとsegmentation cacheを再利用できます。\n\n"
        if mode == "audio_reference"
        else "4. 動画生成側ではLyric Segmentationを再実行しません。\n\n"
    )
    note["widgets_values"] = [
        (
            f"{spec['summary']}。\n\n"
            f"1. {mode}_plan_*.txtをPlan JSONノードへD&Dします。\n"
            f"2. {preparation}を確認します。\n"
            "3. H3モデル/VAEを確認してQueueします。\n"
            f"{segmentation_note}"
            "Audio Referenceだけは整列済みvocalをCurrent Scene時刻で切り出し、"
            "固定ref_audio_0へ渡します。\n"
            f"Baseline: {CONTRACT_ID}"
        )
    ]

    image = _node_by_id(workflow, 26)
    image["widgets_values"] = [CHARACTER_IMAGE]
    image["title"] = "Reference Image • <Picture 1>"

    plan_json = _json_text(_fallback_plan(mode))
    plan = _node_by_id(workflow, 24)
    _ensure_widget_inputs(
        plan,
        (
            ("plan_json", "STRING"),
            ("run_name", "STRING"),
            ("generation_fingerprint", "STRING"),
            ("width", "INT"),
            ("height", "INT"),
            ("encode_mode", "COMBO"),
            ("crop", "COMBO"),
            ("default_duration_seconds", "FLOAT"),
            ("default_steps", "INT"),
            ("base_seed", "INT"),
            ("segment_crf", "INT"),
            ("video_blend_frames", "INT"),
        ),
    )
    plan["pos"] = [81.27143641603425, 808.5988944915174]
    plan["size"] = [1000, 1090]
    plan["widgets_values"][0] = plan_json
    plan["widgets_values"][1] = f"mv_director_{mode}"
    plan["widgets_values"][2] = f"mv-director-{mode}-{CONTRACT_ID}"
    plan["widgets_values"][8] = VIDEO_DENOISING_STEPS
    _node_by_id(workflow, 15)["widgets_values"][1] = VIDEO_DENOISING_STEPS

    profile = _node_by_id(workflow, 30)
    profile["widgets_values"] = ["Visual continuity", spec["audio_profile"]]

    ref_node = _node_by_id(workflow, 11)
    ref_node["title"] = "Reference Conditioning • MV Director Plan"
    ref_node["widgets_values"][0] = "\n".join(_fallback_plan(mode)["shots"][0]["prompt"])
    ref_node["widgets_values"][4] = H3_REFERENCE_IMAGE_SIZE

    additions = [
        _node(
            32,
            "LoadAudio",
            (76.18564224970699, 2245.835943397865),
            (360, 136),
            "Full Mix",
            outputs=[_output("AUDIO", "AUDIO")],
            widgets=[FULL_MIX_AUDIO],
        ),
        _node(
            33,
            "LoadAudio",
            (80, 2060),
            (360, 136),
            "Vocal Stem",
            outputs=[_output("AUDIO", "AUDIO")],
            widgets=[VOCAL_AUDIO],
        ),
        _timing_node(35, (90, 2650), (340, 100)),
        _audio_pad_node(37, spec["alignment"]),
        _audio_tracks_node(38),
        _scene_debug_splitter_node(48),
        _shared_seed_node(49, (-235.7552796705333, 855.0127906997371)),
        _load_text_node(
            39,
            (76.77573693416907, 2427.2389436196327),
            "Compiled Plan JSON (.txt handoff)",
            plan_json,
            f"{mode}_plan.txt",
            (360, 90),
        ),
        _node(
            44,
            "LoraLoaderModelOnly",
            (1663.157664449174, 3023.105301372301),
            (650, 100),
            "LIGHTX2V TURBO — 4 STEP v0.1",
            inputs=[
                _input("model", "MODEL"),
                _widget_input("lora_name", "COMBO"),
                _widget_input("strength_model", "FLOAT"),
            ],
            outputs=[_output("MODEL", "MODEL")],
            widgets=[TURBO_LORA_NAME, 1.0],
        ),
        _node(
            45,
            "LoadImage",
            (2431.488682584539, 1797.7764759658048),
            (360, 360),
            "Background Reference • <Picture 2>",
            outputs=[_output("IMAGE", "IMAGE"), _output("MASK", "MASK")],
            widgets=[BACKGROUND_IMAGE],
        ),
        _node(
            47,
            "ResolutionSelector",
            (-294.2352129891423, 1022.9692406773994),
            (270, 150),
            "Output Resolution",
            inputs=[
                _widget_input("aspect_ratio", "COMBO"),
                _widget_input("megapixels", "FLOAT"),
                _widget_input("multiple", "INT"),
                {
                    **_widget_input("preview", "RESOLUTION_PREVIEW"),
                    "shape": 7,
                },
            ],
            outputs=[
                _output("width", "INT"),
                _output("height", "INT"),
            ],
            widgets=[OUTPUT_ASPECT_RATIO, OUTPUT_MEGAPIXELS, OUTPUT_MULTIPLE],
            order=12,
        ),
    ]
    if mode == "audio_reference":
        lyrics = _lyrics_text()
        additions.extend(
            [
                _load_text_node(
                    34, (500, 1900), "Plain Lyrics", lyrics, "lyrics.txt"
                ),
                _lyric_node(36, (960, 1900)),
            ]
        )
    workflow["nodes"].extend(additions)
    workflow["last_node_id"] = 49

    _connect(workflow, 32, 0, 37, "audio_a", "AUDIO")
    _connect(workflow, 33, 0, 37, "audio_b", "AUDIO")
    if mode == "audio_reference":
        _connect(workflow, 33, 0, 36, "vocal_audio", "AUDIO")
        _connect(workflow, 34, 0, 36, "lyrics_text", "STRING")
        _connect(
            workflow,
            35,
            0,
            36,
            "h3_timing_profile",
            "MV_DIRECTOR_H3_TIMING_PROFILE",
        )
        _connect(workflow, 36, 2, 37, "timeline", "MV_DIRECTOR_TIMELINE")
    _connect(
        workflow,
        35,
        0,
        37,
        "h3_timing_profile",
        "MV_DIRECTOR_H3_TIMING_PROFILE",
    )
    splitter_vocal_slot = 3 if mode == "audio_reference" else 1
    _connect(workflow, 37, splitter_vocal_slot, 48, "vocal_audio", "AUDIO")
    _connect(workflow, 37, 0, 48, "full_mix_audio", "AUDIO")
    _connect(workflow, 48, 2, 38, "full_mix", "AUDIO")
    _connect(workflow, 48, 1, 38, "vocals", "AUDIO")
    _connect(workflow, 38, 0, 7, "source_timeline", "H3_SOURCE_TIMELINE")
    _disconnect_input(workflow, 24, "plan_json_input")
    _disconnect_input(workflow, 37, "plan_json")
    _connect(workflow, 39, 0, 48, "plan_json", "STRING")
    _connect(workflow, 48, 0, 24, "plan_json_input", "STRING")
    _connect(workflow, 39, 0, 37, "plan_json", "STRING")
    _connect(workflow, 45, 0, 11, "ref_images.ref_image_1", "IMAGE")
    _connect(workflow, 1, 0, 44, "model", "MODEL")
    _connect(workflow, 44, 0, 22, "model", "MODEL")
    _connect(workflow, 47, 0, 24, "width", "INT")
    _connect(workflow, 47, 1, 24, "height", "INT")
    _connect(workflow, 49, 0, 24, "base_seed", "INT")

    if mode == "context_loop":
        lip = _node(
            40,
            "MiniMaxH3LipSyncOptions",
            (1980, 2240),
            (400, 260),
            "Context Loop Lip-Sync Options",
            inputs=[_input("voice", "AUDIO")],
            outputs=[
                _output("lip_sync_options", "H3_LIP_SYNC_OPTIONS"),
                _output("voice", "AUDIO"),
                _output("status", "STRING"),
            ],
            widgets=[1.0, 0.2, 0.0, 0.15, 0.2],
        )
        workflow["nodes"].append(lip)
        _connect(workflow, 48, 1, 40, "voice", "AUDIO")
        _connect(workflow, 40, 0, 30, "lip_sync_options", "H3_LIP_SYNC_OPTIONS")
        _connect(workflow, 40, 1, 12, "lip_sync_voice", "AUDIO")
        _connect(workflow, 5, 0, 12, "audio_vae", "VAE")
    elif mode == "audio_reference":
        trim = _node(
            40,
            "TrimAudioDuration",
            (2470, 2290),
            (380, 210),
            "Current Scene Vocal Reference",
            inputs=[
                _input("audio", "AUDIO"),
                _widget_input("start_index", "FLOAT"),
                _widget_input("duration", "FLOAT"),
            ],
            outputs=[_output("AUDIO", "AUDIO")],
            widgets=[0.0, 60.0],
        )
        workflow["nodes"].append(trim)
        _connect(workflow, 48, 1, 40, "audio", "AUDIO")
        _connect(workflow, 8, 10, 40, "start_index", "FLOAT")
        _connect(workflow, 8, 11, 40, "duration", "FLOAT")
        _connect(workflow, 40, 0, 11, "ref_audios.ref_audio_0", "AUDIO")

    workflow["extra"]["ds"] = {"scale": 0.52, "offset": [20, 20]}
    workflow["extra"]["mv_director"] = {
        "kind": "video_generation",
        "lip_sync_mode": mode,
        "contract": CONTRACT_ID,
        "context_loop_base": "Ref2V Basic - MiniMax H3 0.6.json",
    }
    return _decorate_video_workflow(workflow, mode)


def validate_workflow(workflow: dict[str, Any]) -> None:
    nodes = {int(node["id"]): node for node in workflow["nodes"]}
    if len(nodes) != len(workflow["nodes"]):
        raise ValueError("duplicate workflow node id")
    links = {int(link[0]): link for link in workflow["links"]}
    if len(links) != len(workflow["links"]):
        raise ValueError("duplicate workflow link id")
    for link_id, link in links.items():
        _link_id, origin_id, origin_slot, target_id, target_slot, type_name = link
        origin = nodes[int(origin_id)]
        target = nodes[int(target_id)]
        if int(origin_slot) >= len(origin.get("outputs", [])):
            raise ValueError(f"link {link_id} has invalid origin slot")
        if int(target_slot) >= len(target.get("inputs", [])):
            raise ValueError(f"link {link_id} has invalid target slot")
        if target["inputs"][int(target_slot)].get("link") != link_id:
            raise ValueError(f"link {link_id} target metadata mismatch")
        if type_name != origin["outputs"][int(origin_slot)].get("type"):
            raise ValueError(f"link {link_id} origin type mismatch")


def write_workflows(context_loop_root: Path, output_dir: Path) -> None:
    base_path = (
        context_loop_root
        / "example_workflows"
        / "Ref2V Basic - MiniMax H3 0.6.json"
    )
    if not base_path.is_file():
        raise FileNotFoundError(base_path)
    output_dir.mkdir(parents=True, exist_ok=True)
    for mode, spec in MODES.items():
        number = int(spec["number"])
        plan = build_plan_workflow(mode)
        video = build_video_workflow(mode, base_path)
        validate_workflow(plan)
        validate_workflow(video)
        plan_path = output_dir / f"{number * 2 - 1:02d}_plan_compiler_{mode}.json"
        video_path = output_dir / f"{number * 2:02d}_video_{mode}.json"
        plan_path.write_text(_json_text(plan) + "\n", encoding="utf-8")
        video_path.write_text(_json_text(video) + "\n", encoding="utf-8")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--context-loop-root",
        type=Path,
        default=Path(
            r"C:\Software\ComfyUI\custom_nodes\ComfyUI-MiniMaxH3-Contex-Loop"
        ),
    )
    parser.add_argument("--output-dir", type=Path, default=ROOT / "workflows")
    args = parser.parse_args()
    write_workflows(args.context_loop_root, args.output_dir)


if __name__ == "__main__":
    main()
