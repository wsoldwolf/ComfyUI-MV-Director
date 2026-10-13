import copy
import json
from pathlib import Path
import tempfile
import unittest

from tools.generate_4subject_workflows import (
    PREFIX, SUBJECT_PICTURES, build_plan_workflow, build_video_workflow, write_workflows,
)
from tools.generate_workflows import MODES, validate_workflow


ROOT = Path(__file__).resolve().parents[1]
WORKFLOWS = ROOT / "workflows"


def load(name):
    return json.loads((WORKFLOWS / name).read_text(encoding="utf-8"))


def node_of(workflow, type_name):
    return next(n for n in workflow["nodes"] if n["type"] == type_name)


def origin(workflow, node, input_name):
    port = next(i for i in node["inputs"] if i["name"] == input_name)
    link = next(r for r in workflow["links"] if r[0] == port["link"])
    return next(n for n in workflow["nodes"] if n["id"] == link[1]), link[2]


class FourSubjectWorkflowTests(unittest.TestCase):
    def test_four_visions_merge_once_and_preserve_inputs(self):
        source = load("01_plan_compiler_context_loop.json")
        before = copy.deepcopy(source)
        workflow = build_plan_workflow(source, "context_loop")
        self.assertEqual(source, before)
        enhancer = node_of(workflow, "MVDirectorDirectionEnhancer")
        planner = node_of(workflow, "MVDirectorTimelinePlanner")
        self.assertEqual(origin(workflow, planner, "concept_emd"), (enhancer, 3))
        for number, picture in enumerate(SUBJECT_PICTURES, 1):
            name = "concept_emd" if number == 1 else f"concept_emd_{number}"
            vision, slot = origin(workflow, enhancer, name)
            self.assertEqual(slot, 0)
            self.assertEqual(vision["type"], "MVDirectorImageToSubjectEMD")
            self.assertEqual(vision["widgets_values"][1], "subject_only")
            self.assertEqual(vision["widgets_values"][6], "manual")
            self.assertEqual(vision["widgets_values"][8], picture)
            image, _ = origin(workflow, vision, "image")
            self.assertEqual(image["type"], "LoadImage")
            if number > 1:
                self.assertEqual(image["widgets_values"][0], "")
                self.assertEqual(vision["widgets_values"][2:4], ["", ""])
            seed, slot = origin(workflow, vision, "seed")
            old_seed, old_slot = origin(before, source_node(before, 3), "seed")
            self.assertEqual((seed["id"], slot), (old_seed["id"], old_slot))
        for name in ("concept_emd_2", "concept_emd_3", "concept_emd_4"):
            self.assertIsNone(next(i for i in planner["inputs"] if i["name"] == name)["link"])
        background, _ = origin(workflow, enhancer, "scene_emd")
        self.assertEqual(background["widgets_values"][8], 2)
        self.assertEqual(background, source_node(before, background["id"]))
        for node in workflow["nodes"]:
            if node["type"] == "SaveText":
                self.assertIn("mv_director/4subject/", node["widgets_values"][0])
                self.assertEqual(node["widgets_values_named"]["filename_prefix"], node["widgets_values"][0])
        for type_name in ("MVDirectorDirectionEnhancer", "MVDirectorTimelinePlanner", "MVDirectorEMDCompiler"):
            self.assertEqual(node_of(workflow, type_name)["widgets_values"], node_of(source, type_name)["widgets_values"])

    def test_video_reference_mapping_and_shifted_audio_links(self):
        for mode, spec in MODES.items():
            with self.subTest(mode=mode):
                source = load(f"{spec['number'] * 2:02d}_video_{mode}.json")
                before = copy.deepcopy(source)
                workflow = build_video_workflow(source, mode)
                self.assertEqual(source, before)
                conditioning = node_of(workflow, "MiniMaxH3ReferenceToVideo")
                for number, picture in enumerate(SUBJECT_PICTURES, 1):
                    image, slot = origin(workflow, conditioning, f"ref_images.ref_image_{picture - 1}")
                    self.assertEqual(image["type"], "LoadImage")
                    self.assertEqual(slot, 0)
                    self.assertIn(f"Subject {number}", image["title"])
                    if number > 1:
                        self.assertEqual(image["widgets_values"][0], "")
                self.assertEqual(origin(workflow, conditioning, "ref_images.ref_image_1"),
                                 origin(source, node_of(source, "MiniMaxH3ReferenceToVideo"), "ref_images.ref_image_1"))
                for link in before["links"]:
                    if link[3] != conditioning["id"]:
                        continue
                    name = node_of(before, "MiniMaxH3ReferenceToVideo")["inputs"][link[4]]["name"]
                    old_origin, old_slot = origin(before, node_of(before, "MiniMaxH3ReferenceToVideo"), name)
                    new_origin, new_slot = origin(workflow, conditioning, name)
                    self.assertEqual((old_origin["id"], old_slot), (new_origin["id"], new_slot))
                splitter = node_of(workflow, "MVDirectorSceneDebugSplitter")
                loader, _ = origin(workflow, splitter, "plan_json")
                self.assertEqual(loader["widgets_values"][:3], ["", "", ""])
                if mode == "audio_reference":
                    lyrics = [n for n in workflow["nodes"] if n["type"] == "MVDirectorLoadTextFile" and n["id"] != loader["id"]]
                    self.assertEqual(len(lyrics), 1)
                    self.assertEqual(lyrics[0], source_node(before, lyrics[0]["id"]))
                for node in before["nodes"]:
                    if node["type"] not in {"LoadImage", "MVDirectorLoadTextFile", "MiniMaxH3ChainPlanModern"}:
                        self.assertEqual(node.get("widgets_values"), source_node(workflow, node["id"]).get("widgets_values"))
                self.check_links(workflow)

    def check_links(self, workflow):
        validate_workflow(workflow)
        rows = {r[0]: r for r in workflow["links"]}
        for node in workflow["nodes"]:
            for index, output in enumerate(node.get("outputs", [])):
                for link_id in output.get("links") or []:
                    self.assertEqual(rows[link_id][1:3], [node["id"], index])
            for index, port in enumerate(node.get("inputs", [])):
                if port.get("link") is not None:
                    self.assertEqual(rows[port["link"]][3:5], [node["id"], index])

    def test_writer_is_deterministic_and_leaves_sources_untouched(self):
        before = {p: p.read_bytes() for p in WORKFLOWS.glob("*.json") if not p.name.startswith(PREFIX)}
        with tempfile.TemporaryDirectory() as temp_dir:
            paths = write_workflows(WORKFLOWS, Path(temp_dir))
            self.assertEqual(len(paths), 6)
            first = {p.name: p.read_bytes() for p in paths}
            write_workflows(WORKFLOWS, Path(temp_dir))
            self.assertEqual(first, {p.name: p.read_bytes() for p in paths})
            for path in paths:
                self.assertTrue(path.name.startswith(PREFIX))
                self.check_links(json.loads(path.read_text(encoding="utf-8")))
        self.assertEqual(before, {p: p.read_bytes() for p in before})

    def test_saved_variants_match_generator_and_new_blocks_do_not_overlap(self):
        for mode, spec in MODES.items():
            for offset, phase, builder in ((-1, "plan_compiler", build_plan_workflow),
                                           (0, "video", build_video_workflow)):
                name = f"{spec['number'] * 2 + offset:02d}_{phase}_{mode}.json"
                with self.subTest(name=name):
                    source = load(name)
                    workflow = builder(source, mode)
                    self.assertEqual(workflow, load(PREFIX + name))
                    old_ids = {n["id"] for n in source["nodes"]}
                    for node in workflow["nodes"]:
                        if node["id"] in old_ids:
                            continue
                        ax, ay = node["pos"]
                        aw, ah = node["size"]
                        for other in workflow["nodes"]:
                            if node["id"] == other["id"]:
                                continue
                            bx, by = other["pos"]
                            bw, bh = other["size"]
                            overlap = ax < bx + bw and ax + aw > bx and ay < by + bh and ay + ah > by
                            self.assertFalse(overlap, (node["id"], other["id"]))


def source_node(workflow, node_id):
    return next(n for n in workflow["nodes"] if n["id"] == node_id)


if __name__ == "__main__":
    unittest.main()
