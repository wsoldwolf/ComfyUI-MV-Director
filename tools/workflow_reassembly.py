"""Add an opt-in, model-free reassembly branch to a saved video workflow."""
from __future__ import annotations

import copy
from typing import Any

from tools.generate_workflows import _connect, validate_workflow

SCHEMA = "mvd-execution-paths-v1"


def sync_reassembly_path(workflow: dict[str, Any]) -> None:
    """One-time migration; subsequent generation preserves the saved layout/modes."""
    if workflow.get("extra", {}).get("mv_director", {}).get("execution_paths"):
        validate_workflow(workflow)
        return
    from tools.generate_4subject_workflows import _append, _only
    from tools.generate_workflows import _markdown_note

    plan = _only(workflow, "MiniMaxH3ChainPlanModern")
    audio = _only(workflow, "MiniMaxH3AudioTracks")
    save = _only(workflow, "MiniMaxH3ChainSegmentSave")
    review = _only(workflow, "MiniMaxH3ChainReview")
    end = _only(workflow, "MiniMaxH3ChainLoopEnd")
    assemble = _only(workflow, "MiniMaxH3ChainAssemble")
    generation = [save, review, end, assemble]
    for node, pos in zip(generation, ([8160, 160], [7380, 160], [8160, 560], [8160, 840])):
        node["pos"] = pos
        node.setdefault("properties", {})["mv_director_execution_role"] = "generation"
        node["mode"] = 0

    load = _append(workflow, {
        "type": "MiniMaxH3ChainManifestLoad", "pos": [8860, 160], "size": [650, 150],
        "flags": {}, "mode": 2, "title": "Load Full Run Manifest — no rendering",
        "properties": {"Node name for S&R": "MiniMaxH3ChainManifestLoad",
                       "mv_director_execution_role": "reassembly"},
        "inputs": [
            {"name": "plan", "type": "H3_CHAIN_PLAN", "link": None},
            {"name": "external_context", "type": "H3_CHAIN_EXTERNAL_CONTEXT", "shape": 7, "link": None},
            {"name": "source_timeline", "type": "H3_SOURCE_TIMELINE", "shape": 7, "link": None},
        ],
        "outputs": [
            {"name": "manifest", "type": "H3_CHAIN_MANIFEST", "links": None},
            {"name": "manifest_json", "type": "STRING", "links": None},
            {"name": "status", "type": "STRING", "links": None},
        ], "widgets_values": [],
    })
    reassemble = _append(workflow, assemble)
    reassemble.update(pos=[8860, 410], mode=2, title="Reassemble Final Video — selected ALT / original")
    reassemble["properties"]["mv_director_execution_role"] = "reassembly"
    # Keep all delivery options, but never overwrite the ordinary filename or
    # erase checkpoints merely by assembling an alternate selection.
    reassemble["widgets_values"][1] += "_reassembled"
    reassemble["widgets_values"][8] = False
    named = reassemble.get("widgets_values_named", {})
    if named:
        named["filename"] = reassemble["widgets_values"][1]
        named["delete_checkpoints_after_assembly"] = False
    _connect(workflow, plan["id"], 0, load["id"], "plan", "H3_CHAIN_PLAN")
    _connect(workflow, audio["id"], 0, load["id"], "source_timeline", "H3_SOURCE_TIMELINE")
    _connect(workflow, load["id"], 0, reassemble["id"], "manifest", "H3_CHAIN_MANIFEST")
    _connect(workflow, audio["id"], 0, reassemble["id"], "source_timeline", "H3_SOURCE_TIMELINE")

    groups = workflow.setdefault("groups", [])
    # The old review group is empty after moving its nodes. Other fine-grained
    # preparation/model groups and their existing bypasses remain untouched.
    groups[:] = [g for g in groups if g.get("title") != "REVIEW & CONTINUE"]
    for group in groups:
        if group.get("title") == "SAVE & REVIEW":
            group.update(title="TRIM SCENE", bounding=[6700, 70, 540, 370])
    next_group = max((g.get("id", 0) for g in groups), default=0) + 1
    groups.extend([
        {"id": next_group, "title": "EXECUTION 1 - GENERATE", "bounding": [7330, 70, 1440, 1590],
         "color": "#394c49", "flags": {}},
        {"id": next_group + 1, "title": "EXECUTION 2 - REASSEMBLE", "bounding": [8820, 70, 800, 1220],
         "color": "#665080", "flags": {}},
    ])
    control = _append(workflow, {
        "type": "Fast Groups Muter (rgthree)", "pos": [7380, -440], "size": [640, 280],
        "flags": {}, "mode": 0, "inputs": [],
        "outputs": [{"name": "OPT_CONNECTION", "type": "*", "links": None}],
        "title": "MV Director — GENERATE / REASSEMBLE",
        "properties": {"matchColors": "", "matchTitle": "^EXECUTION [12] - ",
                       "showNav": True, "showAllGraphs": False, "sort": "alphanumeric",
                       "customSortAlphabet": "", "toggleRestriction": "always one"},
    })
    # Keep native buttons on a separate Note. The rgthree group service removes
    # non-group widgets during refresh; adding buttons to its node is unstable.
    native_control = _append(workflow, _markdown_note(
        0, (8070, -440), (650, 320), "MV Director — explicit mode buttons",
        "# 実行モード切替\n\n下のボタンはrgthreeのwidgetクラスに依存せず、"
        "二つのEXECUTIONグループ内の対象ノードだけを直接切り替えます。\n\n"
        "通常生成 / GENERATE または 再連結 / REASSEMBLE を選んでからQueueしてください。"
    ))
    config = {
        "schema": SCHEMA, "controller_id": native_control["id"],
        "rgthree_controller_id": control["id"],
        "generation_node_ids": [n["id"] for n in generation],
        "generation_output_ids": [save["id"], review["id"], assemble["id"]],
        "reassembly_node_ids": [load["id"], reassemble["id"]],
        "reassembly_output_ids": [reassemble["id"]],
    }
    control["properties"]["mv_director_execution_control"] = copy.deepcopy(config)
    native_control["properties"]["mv_director_execution_control"] = copy.deepcopy(config)
    workflow.setdefault("extra", {}).setdefault("mv_director", {})["execution_paths"] = config
    _append(workflow, _markdown_note(
        0, (7380, -980), (2240, 440), "Execution mode / safety / frontend compatibility",
        "通常はGENERATEだけ有効、REASSEMBLEはMuteです。ALT採用後はパネルの"
        "『再連結に切替 / REASSEMBLE』を押してQueueします。別WFは不要です。\n\n"
        "再連結はProduction Planから保存済みRun全体を読み、選択中のALTを反映します。"
        "StudioのALTドラフトを経由せず、元Plan・Run・解像度・音源を維持します。"
        "Scene Debug Splitterは無効にしてください。出力名は通常版と分けています。\n\n"
        "rgthreeのalways oneが動作しないfrontendでは、MV Director追加の明示ボタンを使います。"
        "ブラウザを更新して追加JSを読み込んでください。標準のMute操作でも切替可能です。"
        "両方の出力が有効な通常QueueはMV Directorが送信前に拒否します。"
        "この保護は本WFのブラウザ送信のみで、外部API送信を制御しません。\n\n"
        "切替対象は二つのEXECUTIONグループだけです。LoRAや未使用画像などの既存バイパスは"
        "変えません。再連結モードではSave Segment・Review・通常AssembleもMuteになります。"
    ))
    # Remove the obsolete separate-workflow instruction from the existing note.
    for node in workflow["nodes"]:
        if node.get("type") != "MarkdownNote":
            continue
        values = node.get("widgets_values", [])
        if not values:
            continue
        old = "再連結時は生成系OUTPUTノードも動く通常Queueを避け、連結だけの別WFを使ってください。"
        new = "再連結時は切替パネルでREASSEMBLEだけを有効にしてQueueします。別WFは不要です。"
        values[0] = values[0].replace(old, new)
        if "text" in node.get("widgets_values_named", {}):
            node["widgets_values_named"]["text"] = values[0]
    validate_workflow(workflow)
