import copy
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from core.lyrics import parse_plain_lyrics
from core.utilities import decode_embedded_text
from tools.generate_4subject_workflows import WORKFLOW_FILENAMES
from tools.generate_workflows import (CHARACTER_HINT, DEFAULT_USER_PROMPT, LOCAL_FACE_CANDIDATE,
                                      PLAN_12B_FILENAME, PLAN_12B_N_CTX, TEXT_MODEL_12B,
                                      PLAN_26B_IQ2_M_FILENAME, PLAN_26B_IQ2_M_29GPU_FILENAME,
                                      PLAN_26B_IQ2_M_30GPU_FILENAME, PLAN_26B_IQ2_M_GPU_LAYERS,
                                      PLAN_26B_IQ2_M_29GPU_LAYERS, PLAN_26B_IQ2_M_30GPU_LAYERS,
                                      PLAN_26B_IQ2_M_N_BATCH, PLAN_26B_IQ2_M_N_CTX,
                                      TEXT_MODEL_26B_IQ2_M, build_12b_plan_variant,
                                      build_26b_iq2_m_plan_variant,
                                      sync_candidate_policy, sync_direction_settings, sync_model_runtime, sync_planner_schema,
                                      sync_timing_contract, sync_context_loop_runtime,
                                      sync_compiler_schema, sync_step_ownership, sync_video_acceleration,
                                      validate_workflow, write_workflows, build_plan_workflow as _build_legacy_plan_workflow)


ROOT = Path(__file__).resolve().parents[1]
WORKFLOWS = ROOT / "workflows"
CONTRACT_ID = "context-loop-0.7.0@d80304f05ecc2f504e64cbfb636e2a21d4409909"
H3_BASE_MODEL = (
    "MiniMaxH3\\minimax_h3_fl2va_pruned_int8_convrot.safetensors"
)
H3_OVERLAY_MODEL = (
    "MiniMaxH3\\minimax_h3_ref2va_pruned_int8_convrot.safetensors"
)
H3_TEXT_ENCODER = (
    "MiniMaxH3\\qwen3vl_32b_minimax_h3_nvfp4_awq.safetensors"
)

FILES = {"context_loop": WORKFLOW_FILENAMES}


def build_legacy_plan_workflow(mode):
    # Compatibility helper tests use synthetic lyrics, not retired demo assets.
    with patch("tools.generate_workflows._lyrics_text", return_value="[Verse 1]\n検証用の歌詞\n"):
        workflow = _build_legacy_plan_workflow(mode)
    slots = {
        "MVDirectorImageToSubjectEMD": (0, 14, 15, 16),
        "MVDirectorDirectionEnhancer": (5, 11, 12, 13),
        "MVDirectorTimelinePlanner": (3, 9, 10, 11),
        "MVDirectorEMDCompiler": (1, 7, 8, 9),
    }
    for node in workflow["nodes"]:
        if node["type"] in slots:
            node["widgets_values_named"] = {
                key: node["widgets_values"][index]
                for key, index in zip(("model_name", "gpu_layers", "n_batch", "n_ctx"), slots[node["type"]])
            }
            if node["type"] == "MVDirectorTimelinePlanner":
                node["widgets_values_named"]["staging_candidate_policy"] = "optional"
    return workflow


def load(name: str) -> dict:
    return json.loads((WORKFLOWS / name).read_text(encoding="utf-8"))


def nodes_by_id(workflow: dict) -> dict[int, dict]:
    return {int(node["id"]): node for node in workflow["nodes"]}


def only_type(workflow: dict, type_name: str) -> dict:
    values = [node for node in workflow["nodes"] if node["type"] == type_name]
    if len(values) != 1:
        raise AssertionError(f"expected one {type_name}; got {len(values)}")
    return values[0]


def titled_node(workflow: dict, title: str) -> dict:
    values = [node for node in workflow["nodes"] if node.get("title") == title]
    if len(values) != 1:
        raise AssertionError(f"expected one node titled {title}; got {len(values)}")
    return values[0]


def input_link(workflow: dict, node: dict, input_name: str) -> list:
    item = next(value for value in node["inputs"] if value["name"] == input_name)
    link_id = item["link"]
    if link_id is None:
        raise AssertionError(f"{node['type']}.{input_name} is disconnected")
    return next(link for link in workflow["links"] if int(link[0]) == int(link_id))


class DistributableWorkflowTests(unittest.TestCase):
    def test_26b_iq2_m_variant_preserves_wf01_and_offloads_vision_projector(self) -> None:
        source = build_legacy_plan_workflow("context_loop")
        variant = build_26b_iq2_m_plan_variant(source)
        for key in ("links", "groups", "extra"):
            self.assertEqual(variant[key], source[key])
        slots = {
            "MVDirectorImageToSubjectEMD": (0, 14, 15, 16),
            "MVDirectorDirectionEnhancer": (5, 11, 12, 13),
            "MVDirectorTimelinePlanner": (3, 9, 10, 11),
            "MVDirectorEMDCompiler": (1, 7, 8, 9),
        }
        for original, changed in zip(source["nodes"], variant["nodes"], strict=True):
            self.assertEqual(changed["id"], original["id"])
            self.assertEqual(changed["pos"], original["pos"])
            self.assertEqual(changed["size"], original["size"])
            if changed["type"] not in slots:
                if changed["type"] != "MarkdownNote":
                    self.assertEqual(changed, original)
                continue
            model, gpu, batch, context = slots[changed["type"]]
            values = changed["widgets_values"]
            named = changed["widgets_values_named"]
            self.assertEqual(values[model], TEXT_MODEL_26B_IQ2_M)
            self.assertEqual(values[gpu], PLAN_26B_IQ2_M_GPU_LAYERS)
            self.assertEqual(values[batch], PLAN_26B_IQ2_M_N_BATCH)
            self.assertEqual(values[context], PLAN_26B_IQ2_M_N_CTX)
            for field, expected in (
                ("model_name", TEXT_MODEL_26B_IQ2_M),
                ("gpu_layers", PLAN_26B_IQ2_M_GPU_LAYERS),
                ("n_batch", PLAN_26B_IQ2_M_N_BATCH),
                ("n_ctx", PLAN_26B_IQ2_M_N_CTX),
            ):
                self.assertEqual(named[field], expected)
            if changed["type"] == "MVDirectorImageToSubjectEMD":
                self.assertFalse(values[24])
                self.assertFalse(named["mmproj_use_gpu"])
                self.assertIn("mmproj_use_gpu", [p["name"] for p in changed["inputs"]])
        validate_workflow(variant)

    def test_retired_variant_sync_fails_without_writing(self) -> None:
        for flag in ("variant_12b_only", "variant_26b_iq2_m_only",
                     "variant_26b_iq2_m_29gpu_only", "variant_26b_iq2_m_30gpu_only"):
            with self.subTest(flag=flag), tempfile.TemporaryDirectory() as directory:
                target = Path(directory)
                source = (WORKFLOWS / WORKFLOW_FILENAMES[0]).read_bytes()
                (target / WORKFLOW_FILENAMES[0]).write_bytes(source)
                with self.assertRaisesRegex(ValueError, "no longer distributed"):
                    write_workflows(Path("unused"), target, **{flag: True})
                self.assertEqual(list(p.name for p in target.iterdir()), [WORKFLOW_FILENAMES[0]])
                self.assertEqual((target / WORKFLOW_FILENAMES[0]).read_bytes(), source)

    def test_26b_29gpu_variant_changes_only_planner_and_compiler_layers(self) -> None:
        source = build_legacy_plan_workflow("context_loop")
        baseline = build_26b_iq2_m_plan_variant(source)
        tuned = build_26b_iq2_m_plan_variant(
            source, planner_compiler_gpu_layers=PLAN_26B_IQ2_M_29GPU_LAYERS,
        )
        for original, changed in zip(baseline["nodes"], tuned["nodes"], strict=True):
            self.assertEqual(original["id"], changed["id"])
            if original["type"] in {"MVDirectorTimelinePlanner", "MVDirectorEMDCompiler"}:
                self.assertEqual(changed["widgets_values_named"]["gpu_layers"], 29)
                self.assertEqual(
                    changed["widgets_values"][9 if original["type"] == "MVDirectorTimelinePlanner" else 7],
                    29,
                )
                reverted = copy.deepcopy(changed)
                reverted["widgets_values_named"]["gpu_layers"] = PLAN_26B_IQ2_M_GPU_LAYERS
                reverted["widgets_values"][9 if original["type"] == "MVDirectorTimelinePlanner" else 7] = PLAN_26B_IQ2_M_GPU_LAYERS
                self.assertEqual(reverted, original)
            else:
                self.assertEqual(changed, original)
        validate_workflow(tuned)

    def test_26b_30gpu_variant_changes_only_planner_and_compiler_layers(self) -> None:
        source = build_legacy_plan_workflow("context_loop")
        baseline = build_26b_iq2_m_plan_variant(source)
        tuned = build_26b_iq2_m_plan_variant(
            source, planner_compiler_gpu_layers=PLAN_26B_IQ2_M_30GPU_LAYERS,
        )
        for original, changed in zip(baseline["nodes"], tuned["nodes"], strict=True):
            if original["type"] in {"MVDirectorTimelinePlanner", "MVDirectorEMDCompiler"}:
                slot = 9 if original["type"] == "MVDirectorTimelinePlanner" else 7
                self.assertEqual(changed["widgets_values"][slot], 30)
                self.assertEqual(changed["widgets_values_named"]["gpu_layers"], 30)
                reverted = copy.deepcopy(changed)
                reverted["widgets_values"][slot] = PLAN_26B_IQ2_M_GPU_LAYERS
                reverted["widgets_values_named"]["gpu_layers"] = PLAN_26B_IQ2_M_GPU_LAYERS
                self.assertEqual(reverted, original)
            else:
                self.assertEqual(changed, original)
        validate_workflow(tuned)

    def test_12b_variant_preserves_wf01_layout_and_sets_every_inference_node(self) -> None:
        source = build_legacy_plan_workflow("context_loop")
        variant = build_12b_plan_variant(source)
        self.assertEqual(variant["links"], source["links"])
        self.assertEqual(variant["groups"], source["groups"])
        self.assertEqual(variant["extra"], source["extra"])
        model_nodes = {
            "MVDirectorImageToSubjectEMD": (0, 16),
            "MVDirectorDirectionEnhancer": (5, 13),
            "MVDirectorTimelinePlanner": (3, 11),
            "MVDirectorEMDCompiler": (1, 9),
        }
        for original, changed in zip(source["nodes"], variant["nodes"], strict=True):
            self.assertEqual(changed["id"], original["id"])
            self.assertEqual(changed["pos"], original["pos"])
            self.assertEqual(changed["size"], original["size"])
            if changed["type"] in model_nodes:
                model_slot, context_slot = model_nodes[changed["type"]]
                self.assertEqual(changed["widgets_values"][model_slot], TEXT_MODEL_12B)
                self.assertEqual(changed["widgets_values"][context_slot], PLAN_12B_N_CTX)
                self.assertEqual(changed["widgets_values_named"]["model_name"], TEXT_MODEL_12B)
                self.assertEqual(changed["widgets_values_named"]["n_ctx"], PLAN_12B_N_CTX)
            elif changed["type"] != "MarkdownNote":
                self.assertEqual(changed, original)
        validate_workflow(variant)

    def test_acceleration_sync_preserves_inputs_and_is_idempotent(self) -> None:
        workflow = load(WORKFLOW_FILENAMES[1])
        before = copy.deepcopy(workflow)
        sync_video_acceleration(workflow)
        validate_workflow(workflow)
        self.assertEqual(only_type(workflow, "MVDirectorLoadTextFile"),
                         only_type(before, "MVDirectorLoadTextFile"))
        self.assertEqual(only_type(workflow, "MiniMaxH3ChainPlanStudio"),
                         only_type(before, "MiniMaxH3ChainPlanStudio"))
        for original in before["nodes"]:
            current = next(n for n in workflow["nodes"] if n["id"] == original["id"])
            self.assertEqual(current["pos"], original["pos"])
            self.assertEqual(current["size"], original["size"])
        snapshot = copy.deepcopy(workflow)
        sync_video_acceleration(workflow)
        self.assertEqual(workflow, snapshot)

    def test_acceleration_sync_migrates_old_chain_without_rebuilding(self) -> None:
        from tools.generate_workflows import _remove_nodes, _connect
        workflow = load(FILES["context_loop"][1])
        attention = only_type(workflow, "ModelAttentionBackend")
        sigma = only_type(workflow, "MiniMaxH3SigmaShift")
        retired = {node["id"] for node in workflow["nodes"] if node["type"] in {
            "BlockSparseAttention", "SpectrumApplyMiniMaxH3", "ModelPatchTorchSettings"}}
        _remove_nodes(workflow, retired)
        _connect(workflow, attention["id"], 0, sigma["id"], "model", "MODEL")
        attention["pos"] = [1920, 1200]
        saved_loader = copy.deepcopy(only_type(workflow, "MVDirectorLoadTextFile"))
        sync_video_acceleration(workflow)
        validate_workflow(workflow)
        self.assertEqual(only_type(workflow, "MVDirectorLoadTextFile"), saved_loader)
        self.assertEqual(only_type(workflow, "MiniMaxH3ChainPlanModern")["widgets_values"][8], 20)
        snapshot = copy.deepcopy(workflow)
        sync_video_acceleration(workflow)
        self.assertEqual(workflow, snapshot)

    def test_loop_trim_migration_preserves_plan_links_and_layout(self) -> None:
        for mode, (_plan, name) in FILES.items():
            with self.subTest(mode=mode):
                workflow = load(name)
                trim = only_type(workflow, "MiniMaxH3LoopTrim")
                trim["widgets_values"] = [0, 24, True, 0]
                trim["inputs"] = [item for item in trim["inputs"]
                                  if item["name"] != "audio_trim_mode"]
                trim["inputs"].append({"name": "retain_overlap_frames", "type": "INT",
                                       "widget": {"name": "retain_overlap_frames"}, "link": None})
                trim["widgets_values_named"] = {"retain_overlap_frames": 0}
                before = copy.deepcopy(workflow)
                sync_context_loop_runtime(workflow)
                self.assertEqual(trim["widgets_values"], [0, 24, True, "sync_with_video"])
                self.assertEqual(trim["widgets_values_named"], {"audio_trim_mode": "sync_with_video"})
                self.assertNotIn("retain_overlap_frames", [item["name"] for item in trim["inputs"]])
                self.assertIn("audio_trim_mode", [item["name"] for item in trim["inputs"]])
                self.assertEqual(workflow["links"], before["links"])
                for node, original in zip(workflow["nodes"], before["nodes"]):
                    if node["type"] != "MiniMaxH3LoopTrim":
                        self.assertEqual(node, original)
                self.assertEqual(trim["pos"], only_type(before, "MiniMaxH3LoopTrim")["pos"])
                validate_workflow(workflow)
                synced = copy.deepcopy(workflow)
                sync_context_loop_runtime(workflow)
                self.assertEqual(workflow, synced)
                trim["widgets_values"][3] = "fresh_narration_keep_start"
                sync_context_loop_runtime(workflow)
                self.assertEqual(trim["widgets_values"][3], "fresh_narration_keep_start")

    def test_video_loop_trim_uses_current_audio_mode(self) -> None:
        for _plan, name in FILES.values():
            trim = only_type(load(name), "MiniMaxH3LoopTrim")
            self.assertEqual(trim["widgets_values"][3], "sync_with_video")
            self.assertNotIn("retain_overlap_frames", [item["name"] for item in trim["inputs"]])

    def test_timing_sync_preserves_user_settings_and_is_idempotent(self) -> None:
        legacy = "context-loop-0.6.9@9860a063784c8c23b58e00107f2180e0df3c43d9"
        for mode, names in FILES.items():
            for name in names:
                with self.subTest(workflow=name):
                    workflow = load(name)
                    timing = only_type(workflow, "MVDirectorH3TimingProfile")
                    self.assertEqual(timing["widgets_values"][0], CONTRACT_ID)
                    self.assertEqual(workflow["extra"]["mv_director"]["contract"], CONTRACT_ID)
                    timing["widgets_values"][0] = legacy
                    before = copy.deepcopy(workflow)
                    sync_timing_contract(workflow, mode)
                    self.assertEqual(workflow["links"], before["links"])
                    self.assertEqual(workflow.get("groups"), before.get("groups"))
                    for node, original in zip(workflow["nodes"], before["nodes"]):
                        if node["type"] not in {
                            "MVDirectorH3TimingProfile", "MiniMaxH3ChainPlanModern", "MarkdownNote"
                        }:
                            self.assertEqual(node, original)
                        for key in ("pos", "size", "color", "bgcolor", "inputs", "outputs"):
                            self.assertEqual(node.get(key), original.get(key))
                    synced = copy.deepcopy(workflow)
                    sync_timing_contract(workflow, mode)
                    self.assertEqual(workflow, synced)

    def test_candidate_policy_migration_preserves_existing_settings(self) -> None:
        workflow = build_legacy_plan_workflow("context_loop")
        planner = only_type(workflow, "MVDirectorTimelinePlanner")
        planner["widgets_values"] = planner["widgets_values"][:20]
        before = copy.deepcopy(workflow)
        sync_candidate_policy(workflow)
        self.assertEqual(planner["widgets_values"], only_type(before, "MVDirectorTimelinePlanner")["widgets_values"] + ["optional"])
        for node, original in zip(workflow["nodes"], before["nodes"]):
            if node["type"] != "MVDirectorTimelinePlanner":
                self.assertEqual(node, original)
            else:
                self.assertEqual({k:v for k,v in node.items() if k != "widgets_values"},
                                 {k:v for k,v in original.items() if k != "widgets_values"})
        planner["widgets_values"][20] = "prefer_matched"
        sync_candidate_policy(workflow)
        self.assertEqual(planner["widgets_values"][20], "prefer_matched")

    def test_compiler_steps_migration_preserves_widgets_and_layout(self) -> None:
        workflow = load("01_plan_compiler.json")
        node = only_type(workflow, "MVDirectorEMDCompiler")
        expected = copy.deepcopy(workflow)
        node["widgets_values"].insert(3, 12)
        sync_compiler_schema(workflow)
        self.assertEqual(workflow, expected)
        sync_compiler_schema(workflow)
        self.assertEqual(workflow, expected)

    def test_compiler_steps_migration_rejects_linked_steps_before_mutation(self) -> None:
        workflow = load("01_plan_compiler.json")
        node = only_type(workflow, "MVDirectorEMDCompiler")
        node["widgets_values"].insert(3, 12)
        node["inputs"].append({"name": "steps", "link": 123})
        before = copy.deepcopy(workflow)
        with self.assertRaisesRegex(ValueError, "manual migration"):
            sync_compiler_schema(workflow)
        self.assertEqual(workflow, before)

    def test_compiler_steps_migration_reindexes_later_input_links(self) -> None:
        workflow = load("01_plan_compiler.json")
        node = only_type(workflow, "MVDirectorEMDCompiler")
        expected = copy.deepcopy(workflow)
        only_type(expected, "MVDirectorEMDCompiler").pop("widgets_values_named", None)
        node["widgets_values"].insert(3, 12)
        node["inputs"].insert(0, {"name": "steps", "link": None})
        for link in workflow["links"]:
            if link[3] == node["id"]:
                link[4] += 1
        node["widgets_values_named"] = {"steps": 12, "denoising_steps": 12, "seed": 42}
        sync_compiler_schema(workflow)
        self.assertEqual(node.pop("widgets_values_named"), {"seed": 42})
        self.assertEqual(workflow, expected)
        validate_workflow(workflow)

    def test_step_ownership_removes_only_saved_step_overrides(self) -> None:
        workflow = load("02_video_generator.json")
        node = only_type(workflow, "MiniMaxH3ChainPlanModern")
        node["widgets_values"][8] = 12
        original = json.loads(node["widgets_values"][0])
        original["defaults"] = {"temperature": 0.5}
        saved = copy.deepcopy(original)
        saved["steps"] = 20
        saved["defaults"]["steps"] = 16
        saved["shots"][0]["steps"] = 24
        node["widgets_values"][0] = json.dumps(saved, ensure_ascii=False)
        node["widgets_values_named"] = {"plan_json": node["widgets_values"][0], "default_steps": 12}
        before = copy.deepcopy(workflow)
        sync_step_ownership(workflow)
        self.assertEqual(json.loads(node["widgets_values"][0]), original)
        self.assertEqual(node["widgets_values_named"]["plan_json"], node["widgets_values"][0])
        self.assertEqual(node["widgets_values"][8], 12)
        for actual, prior in zip(workflow["nodes"], before["nodes"]):
            if actual["id"] != node["id"]:
                self.assertEqual(actual, prior)
            else:
                for key in actual:
                    if key not in {"widgets_values", "widgets_values_named"}:
                        self.assertEqual(actual[key], prior[key])
        once = copy.deepcopy(workflow)
        sync_step_ownership(workflow)
        self.assertEqual(workflow, once)

    def test_planner_schema_migration_is_idempotent_and_preserves_user_graph(self) -> None:
        workflow = load("01_plan_compiler.json")
        planner = only_type(workflow, "MVDirectorTimelinePlanner")
        planner["widgets_values"].insert(18, 3)
        planner["widgets_values_named"] = {"scenes_per_batch": 3, "seed": 123}
        before = copy.deepcopy(workflow)
        sync_planner_schema(workflow)
        self.assertEqual(workflow["links"], before["links"])
        self.assertEqual(workflow["groups"], before["groups"])
        self.assertEqual(planner["widgets_values_named"], {"seed": 123})
        for node, original in zip(workflow["nodes"], before["nodes"]):
            for field in ("pos", "size", "color", "bgcolor", "outputs"):
                self.assertEqual(node.get(field), original.get(field))
            if node["type"] not in {"MVDirectorTimelinePlanner", "MarkdownNote"}:
                self.assertEqual(node, original)
        once = copy.deepcopy(workflow)
        sync_planner_schema(workflow)
        self.assertEqual(workflow, once)

    def test_planner_schema_migration_rejects_linked_retired_widget(self) -> None:
        workflow = load("01_plan_compiler.json")
        planner = only_type(workflow, "MVDirectorTimelinePlanner")
        planner["inputs"].append({"name": "scenes_per_batch", "link": 123})
        before = copy.deepcopy(planner)
        with self.assertRaisesRegex(ValueError, "manual migration"):
            sync_planner_schema(workflow)
        self.assertEqual(planner, before)
        video = load("02_video_generator.json")
        before_video = copy.deepcopy(video)
        sync_candidate_policy(video)
        self.assertEqual(video, before_video)

    def test_direction_sync_preserves_layout_and_video_plan(self) -> None:
        workflow = load("01_plan_compiler.json")
        enhancer = only_type(workflow, "MVDirectorDirectionEnhancer")
        enhancer["widgets_values"][3] = "anime_emotional_mv"
        enhancer["widgets_values_named"] = {"motion_profile": "anime_emotional_mv"}
        prompt = titled_node(workflow, "ユーザープロンプト")
        prompt["widgets_values"] = ["old input"]
        prompt["widgets_values_named"] = {"value": "old input"}
        before = copy.deepcopy(workflow)
        sync_direction_settings(workflow)
        self.assertEqual(enhancer["widgets_values"][3], "anime_scene_composed_mv")
        self.assertEqual(enhancer["widgets_values_named"]["motion_profile"], "anime_scene_composed_mv")
        self.assertEqual(prompt["widgets_values_named"]["value"], DEFAULT_USER_PROMPT)
        self.assertEqual(DEFAULT_USER_PROMPT.count(LOCAL_FACE_CANDIDATE), 1)
        self.assertEqual(len([x for x in DEFAULT_USER_PROMPT.splitlines() if x.startswith("* ")]), 10)
        for actual, original in zip(workflow["nodes"], before["nodes"]):
            if actual["id"] not in {enhancer["id"], prompt["id"]}:
                self.assertEqual(actual, original)
            else:
                for key in set(actual) | set(original):
                    if key not in {"widgets_values", "widgets_values_named"}:
                        self.assertEqual(actual.get(key), original.get(key))
        video = load("02_video_generator.json")
        original_video = copy.deepcopy(video)
        sync_direction_settings(video)
        self.assertEqual(video, original_video)

    def test_runtime_sync_preserves_layout_metadata_and_non_runtime_settings(self) -> None:
        workflow = load("01_plan_compiler.json")
        node = only_type(workflow, "MVDirectorEMDCompiler")
        node["widgets_values"][1] = "old-model.gguf"
        node["widgets_values_named"] = {"model_name": "old-model.gguf", "n_ctx": 8}
        before = copy.deepcopy(workflow)
        sync_model_runtime(workflow, "context_loop")
        self.assertEqual(node["widgets_values_named"]["model_name"], node["widgets_values"][1])
        self.assertEqual(node["widgets_values_named"]["n_ctx"], 16384)
        self.assertEqual(node["widgets_values"][3], 4096)
        self.assertNotIn("denoising_steps", node["widgets_values_named"])
        for actual, original in zip(workflow["nodes"], before["nodes"]):
            for key in set(actual) | set(original):
                if key not in {"widgets_values", "widgets_values_named"}:
                    self.assertEqual(actual.get(key), original.get(key), (actual["id"], key))
            if actual["type"] not in {"MVDirectorEMDCompiler", "MVDirectorTimelinePlanner", "MVDirectorDirectionEnhancer"}:
                self.assertEqual(actual, original)
        video = load("02_video_generator.json")
        original = copy.deepcopy(video)
        sync_model_runtime(video, "context_loop")
        self.assertEqual(video, original)

    def test_runtime_sync_keeps_compact_json_and_video_bytes(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            output_dir = Path(temporary)
            for pair in FILES.values():
                for name in pair:
                    (output_dir / name).write_text(json.dumps(load(name), ensure_ascii=False), encoding="utf-8")
            original_video = {pair[1]: (output_dir / pair[1]).read_bytes() for pair in FILES.values()}
            write_workflows(Path("unused-context-loop-root"), output_dir, runtime_only=True)
            for plan_name, video_name in FILES.values():
                self.assertEqual(len((output_dir / plan_name).read_text(encoding="utf-8").splitlines()), 1)
                self.assertEqual((output_dir / video_name).read_bytes(), original_video[video_name])

    def test_distributable_workflow_inventory(self) -> None:
        self.assertEqual({p.name for p in WORKFLOWS.glob("*.json")}, set(WORKFLOW_FILENAMES))
        self.assertEqual(set(WORKFLOW_FILENAMES), {"01_plan_compiler.json", "02_video_generator.json"})
        self.assertFalse(list((WORKFLOWS / "obsolate").rglob("*.json")))

    def test_default_generator_preserves_saved_pair_without_external_checkout(self) -> None:
        before = {name: (WORKFLOWS / name).read_bytes() for name in WORKFLOW_FILENAMES}
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory)
            paths = write_workflows(Path("missing-context-loop-checkout"), output)
            self.assertEqual({p.name for p in paths}, set(WORKFLOW_FILENAMES))
            self.assertEqual({p.name for p in output.iterdir()}, set(WORKFLOW_FILENAMES))
            self.assertEqual({p.name: p.read_bytes() for p in paths}, before)
            write_workflows(Path("unused"), output)
            self.assertEqual({p.name: p.read_bytes() for p in paths}, before)
        self.assertEqual(before, {name: (WORKFLOWS / name).read_bytes() for name in before})

    def test_default_generator_rejects_missing_source_pair_before_writes(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "source"
            source.mkdir()
            (source / WORKFLOW_FILENAMES[0]).write_bytes((WORKFLOWS / WORKFLOW_FILENAMES[0]).read_bytes())
            with self.assertRaises(FileNotFoundError):
                write_workflows(Path("unused"), root / "output", source_dir=source)
            self.assertFalse((root / "output").exists())

    def test_sync_flags_ignore_retired_and_unrelated_files(self) -> None:
        flags = ("runtime_only", "direction_only", "candidate_only", "timing_only",
                 "video_runtime_only", "planner_schema_only", "step_ownership_only",
                 "acceleration_only", "subject_inputs_only", "lyric_outputs_only")
        for flag in flags:
            with self.subTest(flag=flag), tempfile.TemporaryDirectory() as directory:
                root = Path(directory)
                for name in WORKFLOW_FILENAMES:
                    (root / name).write_bytes((WORKFLOWS / name).read_bytes())
                unrelated = root / "03_plan_compiler_audio_reference.json"
                unrelated.write_text("not a workflow", encoding="utf-8")
                retired = root / "obsolate"
                retired.mkdir()
                (retired / "old.json").write_text("do not touch", encoding="utf-8")
                write_workflows(Path("unused"), root, **{flag: True})
                self.assertEqual({p.name for p in root.glob("*.json")},
                                 {*WORKFLOW_FILENAMES, unrelated.name})
                self.assertEqual(unrelated.read_text(encoding="utf-8"), "not a workflow")
                self.assertEqual((retired / "old.json").read_text(encoding="utf-8"), "do not touch")

    def test_link_metadata_is_bidirectionally_consistent(self) -> None:
        for name in WORKFLOW_FILENAMES:
            with self.subTest(name=name):
                workflow = load(name)
                validate_workflow(workflow)
                nodes = nodes_by_id(workflow)
                links = {r[0]: r for r in workflow["links"]}
                for node in workflow["nodes"]:
                    for slot, port in enumerate(node.get("inputs", [])):
                        if port.get("link") is not None:
                            self.assertEqual(links[port["link"]][3:5], [node["id"], slot])
                    for slot, port in enumerate(node.get("outputs", [])):
                        for link in port.get("links") or []:
                            self.assertEqual(links[link][1:3], [node["id"], slot])
                for link in links.values():
                    self.assertIn(link[0], nodes[link[1]]["outputs"][link[2]]["links"])

    def test_current_pair_has_context_loop_and_four_subject_slots(self) -> None:
        plan = load(WORKFLOW_FILENAMES[0])
        video = load(WORKFLOW_FILENAMES[1])
        for workflow in (plan, video):
            self.assertEqual(workflow["extra"]["mv_director"]["lip_sync_mode"], "context_loop")
        enhancer = only_type(plan, "MVDirectorDirectionEnhancer")
        planner = only_type(plan, "MVDirectorTimelinePlanner")
        self.assertEqual(planner["widgets_values_named"]["lip_sync_mode"], "context_loop")
        self.assertEqual(input_link(plan, planner, "concept_emd")[1:3], [enhancer["id"], 3])
        for number, picture in enumerate((1, 3, 4, 5), 1):
            port = "concept_emd" if number == 1 else f"concept_emd_{number}"
            vision = nodes_by_id(plan)[input_link(plan, enhancer, port)[1]]
            self.assertEqual(vision["type"], "MVDirectorImageToSubjectEMD")
            self.assertEqual(vision["widgets_values_named"]["picture_index"], picture)
            conditioning = only_type(video, "MiniMaxH3ReferenceToVideo")
            image = nodes_by_id(video)[input_link(video, conditioning, f"ref_images.ref_image_{picture - 1}")[1]]
            self.assertEqual(image["type"], "LoadImage")
            if number > 1:
                self.assertIsNone(next(p for p in planner["inputs"] if p["name"] == port)["link"])

    def test_plan_outputs_include_plan_emd_srt_and_lrc(self) -> None:
        plan = load(WORKFLOW_FILENAMES[0])
        saves = [n for n in plan["nodes"] if n["type"] == "SaveText"]
        self.assertEqual(len(saves), 4)
        prefixes = [n["widgets_values"][0] for n in saves]
        for suffix in ("plan", "emd", "lyrics_srt", "lyrics_lrc"):
            self.assertTrue(any(p.endswith("context_loop_" + suffix) for p in prefixes), prefixes)
        segmentation = only_type(plan, "MVDirectorLyricSegmentation")
        self.assertEqual(segmentation["outputs"][-1]["name"], "lrc_text")
        compiler = only_type(plan, "MVDirectorEMDCompiler")
        self.assertNotIn("steps", [p["name"] for p in compiler["inputs"]])

    def test_video_preserves_json_handoff_studio_and_source_audio(self) -> None:
        video = load(WORKFLOW_FILENAMES[1])
        splitter = only_type(video, "MVDirectorSceneDebugSplitter")
        loader = nodes_by_id(video)[input_link(video, splitter, "plan_json")[1]]
        self.assertEqual(loader["type"], "MVDirectorLoadTextFile")
        production = only_type(video, "MiniMaxH3ChainPlanModern")
        studio = only_type(video, "MiniMaxH3ChainPlanStudio")
        start = only_type(video, "MiniMaxH3ChainLoopStart")
        self.assertEqual(input_link(video, production, "plan_json_input")[1:3], [splitter["id"], 0])
        self.assertEqual(input_link(video, studio, "plan")[1:3], [production["id"], 0])
        self.assertEqual(input_link(video, start, "plan")[1:3], [studio["id"], 0])
        tracks = only_type(video, "MiniMaxH3AudioTracks")
        self.assertEqual(input_link(video, studio, "source_timeline")[1:3], [tracks["id"], 0])
        self.assertEqual(input_link(video, start, "source_timeline")[1:3], [tracks["id"], 0])
        self.assertFalse(splitter["widgets_values_named"]["enable"])

    def test_lipsync_audio_and_global_steps_are_wired(self) -> None:
        video = load(WORKFLOW_FILENAMES[1])
        splitter = only_type(video, "MVDirectorSceneDebugSplitter")
        lip = only_type(video, "MiniMaxH3LipSyncOptions")
        profile = only_type(video, "MiniMaxH3GenerationProfile")
        context = only_type(video, "MiniMaxH3ChainContext")
        self.assertEqual(input_link(video, lip, "voice")[1:3], [splitter["id"], 1])
        self.assertEqual(input_link(video, profile, "lip_sync_options")[1:3], [lip["id"], 0])
        self.assertEqual(input_link(video, context, "lip_sync_voice")[1:3], [lip["id"], 1])
        audio_vae = nodes_by_id(video)[input_link(video, context, "audio_vae")[1]]
        self.assertEqual(audio_vae["type"], "VAELoader")
        self.assertEqual(only_type(video, "MiniMaxH3ChainPlanModern")["widgets_values_named"]["default_steps"], 20)
        self.assertEqual(only_type(video, "ResolutionSelector")["widgets_values_named"]["megapixels"], 0.9)
        self.assertEqual(only_type(video, "LoraLoaderModelOnly")["mode"], 4)

    def test_workflow_documentation_lists_only_supported_pair(self) -> None:
        documented = (WORKFLOWS / "README.md").read_text(encoding="utf-8")
        for name in WORKFLOW_FILENAMES:
            self.assertIn(name, documented)
        self.assertIn("保留中", documented)
        self.assertIn("Audio参照", documented)
        self.assertIn("歌詞方式", documented)
        self.assertIn("Plan Studio", documented)
        self.assertNotIn("基本6", documented)


if __name__ == "__main__":
    unittest.main()
