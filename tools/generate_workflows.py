"""Generate the six distributable MV Director workflows.

The video graphs deliberately start from the pinned Context Loop Ref2V Basic
workflow.  This preserves its recursive sampling, checkpoint, review, and
assembly wiring while replacing only the authoring and audio-policy edges
owned by MV Director.
"""

from __future__ import annotations

import argparse
import base64
import copy
import json
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
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
TEXT_MODEL = "Qwen3-4B-abliterated/Qwen3-4B-abliterated-q5_k_m.gguf"
VISION_MODEL = "Qwen3-VL-4B-Instruct/Qwen3-VL-4B-Instruct-Q4_K_M.gguf"
WHISPER_MODEL = "medium.pt"
CHARACTER_IMAGE = "image001_mikofox (2).jpg"
BACKGROUND_IMAGE = "image002_keinai.jpg"
FULL_MIX_AUDIO = "autumn_fox_shrine.mp3"
VOCAL_AUDIO = "autumn_fox_shrine_vocal.mp3"
LYRICS_BASENAME = "autumn_fox_shrine.txt"
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
                    value for value in output["links"] if int(value) != int(link_id)
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
            "",
            "summary:",
            "[reference generation] A moonlit performance at a shrine approach.",
            "",
            "retention_analysis:",
            "<Subject 1>: fully_preserved - preserve identity, clothing, and proportions.",
            "<Picture 1>: fully_preserved - preserve the visible performer design.",
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
                _input("observations_json", "STRING"),
            ],
            outputs=[
                _output("direction", "MV_DIRECTOR_DIRECTION"),
                _output("direction_emd_preview", "STRING"),
                _output("status", "STRING"),
            ],
            widgets=[
                "profile",
                "",
                "anime_story_mv",
                "anime_story_mv",
                "anime_story_mv",
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
                "none",
                "location",
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
                "none",
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
    _connect(workflow, 15, 3, 8, "observations_json", "STRING")
    _connect(workflow, 7, 0, 9, "template_emd", "STRING")
    _connect(workflow, 3, 0, 9, "concept_emd", "STRING")
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
        (1980, 2580),
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


def build_video_workflow(mode: str, base_path: Path) -> dict[str, Any]:
    spec = MODES[mode]
    workflow = json.loads(base_path.read_text(encoding="utf-8"))
    _remove_nodes(workflow, {27})
    _disconnect_input(workflow, 22, "model")
    workflow["last_node_id"] = max(int(node["id"]) for node in workflow["nodes"])
    workflow["last_link_id"] = max(int(link[0]) for link in workflow["links"])

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
            46,
            "MVDirectorH3BackgroundReference",
            (1550, 600),
            (500, 180),
            "Bind Background • <Picture 2>",
            inputs=[
                _input("plan_json", "STRING"),
                _input("background_image", "IMAGE"),
            ],
            outputs=[
                _output("plan_json", "STRING"),
                _output("background_image", "IMAGE"),
                _output("status", "STRING"),
            ],
            widgets=[2],
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
    workflow["last_node_id"] = 47

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
    _connect(workflow, 37, 0, 38, "full_mix", "AUDIO")
    _connect(workflow, 37, 1, 38, "vocals", "AUDIO")
    _connect(workflow, 38, 0, 7, "source_timeline", "H3_SOURCE_TIMELINE")
    _disconnect_input(workflow, 24, "plan_json_input")
    _disconnect_input(workflow, 37, "plan_json")
    _connect(workflow, 39, 0, 46, "plan_json", "STRING")
    _connect(workflow, 45, 0, 46, "background_image", "IMAGE")
    _connect(workflow, 46, 0, 24, "plan_json_input", "STRING")
    _connect(workflow, 46, 0, 37, "plan_json", "STRING")
    _connect(workflow, 46, 1, 11, "ref_images.ref_image_1", "IMAGE")
    _connect(workflow, 1, 0, 44, "model", "MODEL")
    _connect(workflow, 44, 0, 22, "model", "MODEL")
    _connect(workflow, 47, 0, 24, "width", "INT")
    _connect(workflow, 47, 1, 24, "height", "INT")

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
        _connect(workflow, 37, 1, 40, "voice", "AUDIO")
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
        _connect(workflow, 37, 3, 40, "audio", "AUDIO")
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
    return workflow


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


def _node_by_title(workflow: dict[str, Any], title: str) -> dict[str, Any]:
    matches = [node for node in workflow["nodes"] if node.get("title") == title]
    if len(matches) != 1:
        raise ValueError(f"expected one workflow node titled {title!r}")
    return matches[0]


def _node_by_type(workflow: dict[str, Any], type_name: str) -> dict[str, Any]:
    matches = [node for node in workflow["nodes"] if node.get("type") == type_name]
    if len(matches) != 1:
        raise ValueError(f"expected one workflow node of type {type_name!r}")
    return matches[0]


def _sync_node_widgets(
    target: dict[str, Any], source: dict[str, Any]
) -> None:
    """Copy generated defaults while retaining debug layout and wiring."""

    values = copy.deepcopy(source.get("widgets_values", []))
    target["widgets_values"] = values
    named = target.get("widgets_values_named")
    if not isinstance(named, dict):
        return
    # ComfyUI stores control_after_generate ("randomize") in the named map
    # even though it is not a graph input.  Preserve that serialized order so
    # the following cache_mode value cannot shift by one position.
    for name, value in zip(tuple(named), values):
        named[name] = copy.deepcopy(value)


def _sync_development_workflows(
    output_dir: Path,
    reference_plan: dict[str, Any],
    reference_video: dict[str, Any],
) -> None:
    """Keep hand-edited debug graphs on the same runtime defaults.

    Debug-only Preview nodes, pass-through prompts, positions, and links remain
    untouched.  Only user-facing configuration widgets are synchronized.
    """

    development = output_dir / "development"
    pairs = (
        (
            development / "01_plan_compiler_context_loop_debug.json",
            reference_plan,
            (
                "Character Reference Image",
                "Character Vision / Subject EMD",
                "Vocal Stem",
                "Plain Lyrics",
                "Lyric Segmentation",
                "Direction Enhancer",
                "Timeline Planner",
                "Ref2VA EMD Compiler",
                "Background Reference Image",
                "Background Vision (Scene Only)",
            ),
            (),
        ),
        (
            development / "02_video_context_loop_debug.json",
            reference_video,
            (
                "H3 Diffusion Model",
                "H3 Text Encoder",
                "Video VAE",
                "Audio VAE",
                "Reference Conditioning • MV Director Plan",
                "Model Attention Backend",
                "Production Plan",
                "Review Candidates",
                "Reference Image • <Picture 1>",
                "Full Mix",
                "Vocal Stem",
                "LIGHTX2V TURBO — 4 STEP v0.1",
                "Background Reference • <Picture 2>",
            ),
            ("ResolutionSelector",),
        ),
    )
    for path, reference, titles, type_names in pairs:
        if not path.is_file():
            continue
        workflow = json.loads(path.read_text(encoding="utf-8"))
        for title in titles:
            _sync_node_widgets(
                _node_by_title(workflow, title),
                _node_by_title(reference, title),
            )
        for type_name in type_names:
            _sync_node_widgets(
                _node_by_type(workflow, type_name),
                _node_by_type(reference, type_name),
            )
        validate_workflow(workflow)
        path.write_text(_json_text(workflow) + "\n", encoding="utf-8")


def write_workflows(context_loop_root: Path, output_dir: Path) -> None:
    base_path = (
        context_loop_root
        / "example_workflows"
        / "Ref2V Basic - MiniMax H3 0.6.json"
    )
    if not base_path.is_file():
        raise FileNotFoundError(base_path)
    output_dir.mkdir(parents=True, exist_ok=True)
    generated: dict[str, tuple[dict[str, Any], dict[str, Any]]] = {}
    for mode, spec in MODES.items():
        number = int(spec["number"])
        plan = build_plan_workflow(mode)
        video = build_video_workflow(mode, base_path)
        validate_workflow(plan)
        validate_workflow(video)
        generated[mode] = (plan, video)
        plan_path = output_dir / f"{number * 2 - 1:02d}_plan_compiler_{mode}.json"
        video_path = output_dir / f"{number * 2:02d}_video_{mode}.json"
        plan_path.write_text(_json_text(plan) + "\n", encoding="utf-8")
        video_path.write_text(_json_text(video) + "\n", encoding="utf-8")
    _sync_development_workflows(
        output_dir,
        *generated["context_loop"],
    )


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
