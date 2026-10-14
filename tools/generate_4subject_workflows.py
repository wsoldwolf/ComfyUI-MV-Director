"""Regenerate the two saved four-Subject Context Loop workflows.

The saved four-Subject files are the editable source of truth. Preserve their
media, embedded text/Plan, model settings, bypasses, wiring and layout; do not
derive them again from the single-Subject workflows or restore retired variants.
"""

from __future__ import annotations

import argparse
import copy
import json
from pathlib import Path
import sys
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from tools.generate_workflows import (
    _connect, _disconnect_input, _input_index, _json_text,
    _markdown_note, sync_subject_inputs, validate_workflow,
)

WORKFLOW_FILENAMES = (
    "01_plan_compiler_context_loop_4subject.json",
    "02_video_context_loop_4subject.json",
)
# Keep the established environment reference at Picture 2.
SUBJECT_PICTURES = (1, 3, 4, 5)


def _only(workflow: dict[str, Any], type_name: str) -> dict[str, Any]:
    nodes = [node for node in workflow["nodes"] if node["type"] == type_name]
    if len(nodes) != 1:
        raise ValueError(f"expected one {type_name}, found {len(nodes)}")
    return nodes[0]


def _source(workflow: dict[str, Any], target: dict[str, Any], name: str) -> dict[str, Any]:
    link_id = target["inputs"][_input_index(target, name)].get("link")
    link = next((row for row in workflow["links"] if row[0] == link_id), None)
    if link is None:
        raise ValueError(f"required source is not connected: {target['type']}.{name}")
    return next(node for node in workflow["nodes"] if node["id"] == link[1])


def _append(workflow: dict[str, Any], node: dict[str, Any]) -> dict[str, Any]:
    node = copy.deepcopy(node)
    node["id"] = max(int(n["id"]) for n in workflow["nodes"]) + 1
    node["order"] = max(int(n.get("order", 0)) for n in workflow["nodes"]) + 1
    for item in node.get("inputs", []):
        item["link"] = None
    for item in node.get("outputs", []):
        item["links"] = None
    workflow["nodes"].append(node)
    workflow["last_node_id"] = node["id"]
    return node


def _widget(node: dict[str, Any], name: str, index: int, value: Any) -> None:
    node["widgets_values"][index] = value
    named = node.get("widgets_values_named")
    if isinstance(named, dict) and name in named:
        named[name] = value


def _note(workflow: dict[str, Any], position: tuple[int, int], size: tuple[int, int],
          title: str, body: str) -> None:
    _append(workflow, _markdown_note(0, position, size, title, body))


def _prepare(source: dict[str, Any]) -> dict[str, Any]:
    workflow = copy.deepcopy(source)
    # Generated variants must not retain another document's identity.
    workflow.pop("id", None)
    if "revision" in workflow:
        workflow["revision"] = 0
    workflow["last_node_id"] = max(int(n["id"]) for n in workflow["nodes"])
    workflow["last_link_id"] = max((int(r[0]) for r in workflow["links"]), default=0)
    for node in workflow["nodes"]:
        if node["type"] == "Label (rgthree)":
            node["title"] = "4 SUBJECT • " + node.get("title", "MV Director")
            node["size"][0] += 350
    return workflow


def build_plan_workflow(source: dict[str, Any], mode: str) -> dict[str, Any]:
    workflow = _prepare(source)
    sync_subject_inputs(workflow)
    enhancer = _only(workflow, "MVDirectorDirectionEnhancer")
    planner = _only(workflow, "MVDirectorTimelinePlanner")
    vision = _source(workflow, enhancer, "concept_emd")
    if vision["type"] != "MVDirectorImageToSubjectEMD":
        raise ValueError("the source workflow needs a Subject Vision input")
    image = _source(workflow, vision, "image")
    if image["type"] != "LoadImage":
        raise ValueError("the source Subject Vision needs LoadImage")
    for number, picture in enumerate(SUBJECT_PICTURES, 1):
        if number == 1:
            subject_image, subject_vision = image, vision
        else:
            subject_image = _append(workflow, image)
            subject_vision = _append(workflow, vision)
            x = 40 + (number - 2) * 1100
            subject_image["pos"] = [x, 2740]
            subject_vision["pos"] = [x + 410, 2740]
            _widget(subject_image, "image", 0, "")
            _widget(subject_vision, "subject_hint", 2, "")
            _widget(subject_vision, "additional_instruction", 3, "")
            _connect(workflow, subject_image["id"], 0, subject_vision["id"], "image", "IMAGE")
            # Reuse the established seed input, without adding a new seed policy.
            seed_input = vision["inputs"][_input_index(vision, "seed")]
            seed_link = next((r for r in workflow["links"] if r[0] == seed_input.get("link")), None)
            if seed_link is not None:
                _connect(workflow, seed_link[1], seed_link[2], subject_vision["id"], "seed", "INT")
            name = f"concept_emd_{number}"
            _disconnect_input(workflow, enhancer["id"], name)
            _connect(workflow, subject_vision["id"], 0, enhancer["id"], name, "STRING")
            _note(workflow, (x, 2510), (910, 170),
                  f"Subject {number} • Picture {picture} — 画像設定必須",
                  f"このSubjectの画像を選択してください。動画WFでも同じ画像をPicture {picture}へ設定します。\n\n"
                  "subject_hintは空欄です。衣装・顔・小道具等の補助説明が必要な場合だけ記入してください。"
                  "被覆や模様は、この画像の人物の部位・範囲・色・素材を明記します。"
                  "普通の顔や一時的な遮蔽を、恒常的な顔面被覆に読み替えないでください。"
                  "物体をSubjectにする場合はconcept_typeを変更します。")
        subject_image["title"] = f"Subject {number} Reference • <Picture {picture}>"
        subject_vision["title"] = f"Subject {number} Vision / EMD • <Picture {picture}>"
        _widget(subject_vision, "analysis_profile", 1, "subject_only")
        _widget(subject_vision, "picture_reference_mode", 6, "manual")
        _widget(subject_vision, "picture_index", 8, picture)
        # The last legacy widget is a display-only binding preview.
        if subject_vision["widgets_values"][-1] == "<Picture 1>":
            subject_vision["widgets_values"][-1] = f"<Picture {picture}>"

    # The Enhancer merges once, in port order; never feed those Subjects twice.
    for name in ("concept_emd", "concept_emd_2", "concept_emd_3", "concept_emd_4"):
        _disconnect_input(workflow, planner["id"], name)
    _connect(workflow, enhancer["id"], 3, planner["id"], "concept_emd", "STRING")
    for node in workflow["nodes"]:
        if node["type"] == "SaveText":
            prefix = node["widgets_values"][0]
            basename = prefix.replace("\\", "/").rsplit("/", 1)[-1]
            _widget(node, "filename_prefix", 0, f"mv_director/4subject/{basename}")
    _note(workflow, (-350, 3580), (3500, 220), "4 Subject — 前段の使い方",
          "Subject 1〜4の画像を各一枚設定して実行します。追加3欄は意図的に空欄です。\n\n"
          "番号はEnhancerのconcept_emd → concept_emd_2 → concept_emd_3 → concept_emd_4の順。"
          "各Visionは一つのSubjectを定義し、合計4件までです。人物だけでなく物体も指定できます。\n\n"
          "対応: Subject 1=Picture 1、Subject 2=Picture 3、Subject 3=Picture 4、Subject 4=Picture 5。"
          "背景はPicture 2で、Subject件数には含みません。歌唱対象はPlannerのlip_sync_targetで指定します。\n\n"
          "外見補助は各Visionのsubject_hintへ人物別に記入します。lock_identityではその本文を保持します。"
          "共通演出へ全員の被覆や装飾として書かず、確かな部位・範囲・材質を指定してください。\n\n"
          f"保存先: mv_director/4subject/{mode}_plan_*.txt。対応する_4subject_動画WFへ読み込みます。"
          "通常版WFと同じ歌詞・vocal・モデル設定を引き継ぎます。")
    validate_workflow(workflow)
    return workflow


def build_video_workflow(source: dict[str, Any], mode: str) -> dict[str, Any]:
    workflow = _prepare(source)
    conditioning = _only(workflow, "MiniMaxH3ReferenceToVideo")
    image = _source(workflow, conditioning, "ref_images.ref_image_0")
    if image["type"] != "LoadImage":
        raise ValueError("the source video workflow needs LoadImage for Picture 1")
    image["title"] = "Subject 1 Reference • <Picture 1>"
    base_y = int(max(n["pos"][1] + n["size"][1] for n in workflow["nodes"])) + 180
    # Preserve existing links by remapping target slots after autogrow insertion.
    inputs = conditioning["inputs"]
    insertion = max(i for i, item in enumerate(inputs) if item["name"].startswith("ref_images.")) + 1
    for index in range(2, 5):
        name = f"ref_images.ref_image_{index}"
        if not any(item["name"] == name for item in inputs):
            inputs.insert(insertion, {"name": name, "localized_name": f"ref_image_{index}",
                                      "shape": 7, "type": "IMAGE", "link": None})
            insertion += 1
    for slot, item in enumerate(inputs):
        if item.get("link") is not None:
            row = next(r for r in workflow["links"] if r[0] == item["link"])
            row[4] = slot
    conditioning["size"][1] += 60
    for number, picture in enumerate(SUBJECT_PICTURES[1:], 2):
        subject_image = _append(workflow, image)
        x = -780 + (number - 2) * 450
        subject_image["pos"] = [x, base_y + 200]
        subject_image["title"] = f"Subject {number} Reference • <Picture {picture}>"
        _widget(subject_image, "image", 0, "")
        _disconnect_input(workflow, conditioning["id"], f"ref_images.ref_image_{picture - 1}")
        _connect(workflow, subject_image["id"], 0, conditioning["id"],
                 f"ref_images.ref_image_{picture - 1}", "IMAGE")
    splitter = _only(workflow, "MVDirectorSceneDebugSplitter")
    loader = _source(workflow, splitter, "plan_json")
    if loader["type"] != "MVDirectorLoadTextFile":
        raise ValueError("the source video workflow needs Load Text File for Plan JSON")
    # Do not accidentally render a saved one-Subject Plan in the new variant.
    for index, name in enumerate(("file_data_base64", "basename", "browser_metadata_json")):
        _widget(loader, name, index, "")
    plan = _only(workflow, "MiniMaxH3ChainPlanModern")
    _widget(plan, "run_name", 1, f"mv_director_4subject_{mode}")
    _note(workflow, (-780, base_y), (1250, 150), "4 Subject — 動画生成の使い方",
          "_4subject_前段WFで生成したPlan JSON(txt)をLoad Text Fileへ読み込みます。"
          "通常版の保存済みPlanはこのWFへ引き継ぎません。\n\n"
          "前段と同じ画像を設定: Subject 1=Picture 1、背景=Picture 2、"
          "Subject 2=Picture 3、Subject 3=Picture 4、Subject 4=Picture 5。追加3欄は画像設定必須です。\n\n"
          "音声経路・解像度・step・高速化設定は通常版を保持しています。参照画像5枚は処理時間とVRAM負荷を増やします。")
    validate_workflow(workflow)
    return workflow


def prepare_saved_workflow(source: dict[str, Any], *, plan: bool) -> dict[str, Any]:
    """Validate an existing four-Subject graph without resetting user settings."""
    workflow = copy.deepcopy(source)
    if plan:
        sync_subject_inputs(workflow)
        enhancer = _only(workflow, "MVDirectorDirectionEnhancer")
        for number in range(1, 5):
            name = "concept_emd" if number == 1 else f"concept_emd_{number}"
            if _source(workflow, enhancer, name)["type"] != "MVDirectorImageToSubjectEMD":
                raise ValueError(f"four-Subject source requires a Vision input: {name}")
    else:
        conditioning = _only(workflow, "MiniMaxH3ReferenceToVideo")
        for picture in SUBJECT_PICTURES:
            name = f"ref_images.ref_image_{picture - 1}"
            if not any(port["name"] == name for port in conditioning["inputs"]):
                raise ValueError(f"four-Subject source is missing reference input: {name}")
            if _source(workflow, conditioning, name)["type"] != "LoadImage":
                raise ValueError(f"four-Subject source requires an image input: {name}")
    validate_workflow(workflow)
    return workflow


def write_workflows(source_dir: Path, output_dir: Path) -> list[Path]:
    # Validate both before writing either. In-place synchronization is supported.
    outputs = []
    for index, name in enumerate(WORKFLOW_FILENAMES):
        source_path = source_dir / name
        source_text = source_path.read_text(encoding="utf-8")
        source = json.loads(source_text)
        workflow = prepare_saved_workflow(source, plan=index == 0)
        # Keep browser-saved formatting too, unless a schema migration is needed.
        formatted = source_text if workflow == source else _json_text(workflow) + "\n"
        outputs.append((output_dir / name, formatted))
    output_dir.mkdir(parents=True, exist_ok=True)
    for path, formatted in outputs:
        if not path.exists() or path.read_text(encoding="utf-8") != formatted:
            path.write_text(formatted, encoding="utf-8")
    return [path for path, _ in outputs]


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-dir", type=Path, default=ROOT / "workflows")
    parser.add_argument("--output-dir", type=Path, default=ROOT / "workflows")
    args = parser.parse_args()
    for path in write_workflows(args.source_dir, args.output_dir):
        print(path)


if __name__ == "__main__":
    main()
