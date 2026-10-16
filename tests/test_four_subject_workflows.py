import copy
import json
from pathlib import Path
import tempfile
import unittest

from tools.generate_4subject_workflows import (
    WORKFLOW_FILENAMES, SUBJECT_PICTURES, build_plan_workflow, build_video_workflow,
    prepare_saved_workflow, write_workflows,
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
        source = load(WORKFLOW_FILENAMES[0])
        before = copy.deepcopy(source)
        workflow = prepare_saved_workflow(source, plan=True)
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
                self.assertEqual(image["widgets_values"], source_node(before, image["id"])["widgets_values"])
                self.assertEqual(vision["widgets_values"][2:4], source_node(before, vision["id"])["widgets_values"][2:4])
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
        for mode, spec in (("context_loop", MODES["context_loop"]),):
            with self.subTest(mode=mode):
                source = load(WORKFLOW_FILENAMES[1])
                before = copy.deepcopy(source)
                workflow = prepare_saved_workflow(source, plan=False)
                self.assertEqual(source, before)
                conditioning = node_of(workflow, "MiniMaxH3ReferenceToVideo")
                for number, picture in enumerate(SUBJECT_PICTURES, 1):
                    image, slot = origin(workflow, conditioning, f"ref_images.ref_image_{picture - 1}")
                    self.assertEqual(image["type"], "LoadImage")
                    self.assertEqual(slot, 0)
                    self.assertIn(f"Subject {number}", image["title"])
                    if number > 1:
                        self.assertEqual(image["widgets_values"], source_node(before, image["id"])["widgets_values"])
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
                self.assertEqual(loader["widgets_values"], source_node(before, loader["id"])["widgets_values"])
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
        before = {p: p.read_bytes() for p in WORKFLOWS.glob("*.json")}
        with tempfile.TemporaryDirectory() as temp_dir:
            paths = write_workflows(WORKFLOWS, Path(temp_dir))
            self.assertEqual([p.name for p in paths], list(WORKFLOW_FILENAMES))
            first = {p.name: p.read_bytes() for p in paths}
            write_workflows(WORKFLOWS, Path(temp_dir))
            self.assertEqual(first, {p.name: p.read_bytes() for p in paths})
            for path in paths:
                self.assertEqual(load(path.name), json.loads(path.read_text(encoding="utf-8")))
                self.check_links(json.loads(path.read_text(encoding="utf-8")))
            self.assertEqual({p.name for p in Path(temp_dir).glob("*.json")}, set(WORKFLOW_FILENAMES))
        self.assertEqual(before, {p: p.read_bytes() for p in before})

    def test_saved_pair_preserves_every_user_setting(self):
        for index, name in enumerate(WORKFLOW_FILENAMES):
            with self.subTest(name=name):
                source = load(name)
                before = copy.deepcopy(source)
                workflow = prepare_saved_workflow(source, plan=index == 0)
                self.assertEqual(source, before)
                self.assertEqual(workflow, source)
                self.check_links(workflow)

    def test_in_place_generation_is_idempotent_and_ignores_other_files(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            for name in WORKFLOW_FILENAMES:
                (root / name).write_bytes((WORKFLOWS / name).read_bytes())
            unrelated = root / "01_plan_compiler_context_loop.json"
            unrelated.write_text("unrelated source", encoding="utf-8")
            write_workflows(root, root)
            first = {p.name: p.read_bytes() for p in root.iterdir()}
            write_workflows(root, root)
            self.assertEqual(first, {p.name: p.read_bytes() for p in root.iterdir()})
            self.assertEqual(unrelated.read_text(encoding="utf-8"), "unrelated source")
            for name in WORKFLOW_FILENAMES:
                self.assertEqual(load(name), json.loads((root / name).read_text(encoding="utf-8")))

    def test_browser_edited_layout_and_viewport_remain_the_generation_source(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            source_dir = Path(temp_dir) / 'edited'
            source_dir.mkdir()
            expected = {}
            for name in WORKFLOW_FILENAMES:
                workflow = load(name)
                for index, node in enumerate(workflow['nodes']):
                    node['pos'] = [node['pos'][0] + 125.25, node['pos'][1] - 61.5]
                    node['size'] = [node['size'][0] + 15, node['size'][1] + 9]
                    node.setdefault('flags', {})['collapsed'] = index % 3 == 0
                for group in workflow['groups']:
                    x, y, width, height = group['bounding']
                    group['bounding'] = [x + 125.25, y - 61.5, width + 15, height + 9]
                workflow.setdefault('extra', {})['ds'] = {'scale': 0.35, 'offset': [103.5, -42]}
                source_dir.joinpath(name).write_text(json.dumps(workflow, ensure_ascii=False), encoding='utf-8')
                expected[name] = workflow
            output_dir = Path(temp_dir) / 'generated'
            paths = write_workflows(source_dir, output_dir)
            for path in paths:
                self.assertEqual(json.loads(path.read_text(encoding='utf-8')), expected[path.name])
            first = {path.name: path.read_bytes() for path in paths}
            write_workflows(output_dir, output_dir)
            self.assertEqual(first, {path.name: path.read_bytes() for path in paths})

    def test_missing_second_source_does_not_write_first_or_restore_legacy(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            (root / WORKFLOW_FILENAMES[0]).write_bytes((WORKFLOWS / WORKFLOW_FILENAMES[0]).read_bytes())
            output = root / "output"
            with self.assertRaises(FileNotFoundError):
                write_workflows(root, output)
            self.assertFalse(output.exists())

    def test_incomplete_subject_sources_are_rejected(self):
        for plan, name in ((True, WORKFLOW_FILENAMES[0]), (False, WORKFLOW_FILENAMES[1])):
            source = load(name)
            target = node_of(source, "MVDirectorDirectionEnhancer" if plan else "MiniMaxH3ReferenceToVideo")
            missing = "concept_emd_4" if plan else "ref_images.ref_image_4"
            target["inputs"] = [p for p in target["inputs"] if p["name"] != missing]
            with self.subTest(name=name), self.assertRaises(ValueError):
                prepare_saved_workflow(source, plan=plan)

    def test_invalid_second_source_does_not_replace_output_pair(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            output = root / "output"
            output.mkdir()
            for name in WORKFLOW_FILENAMES:
                (root / name).write_bytes((WORKFLOWS / name).read_bytes())
                (output / name).write_text("existing output", encoding="utf-8")
            workflow = load(WORKFLOW_FILENAMES[1])
            node_of(workflow, "MiniMaxH3ReferenceToVideo")["inputs"] = []
            (root / WORKFLOW_FILENAMES[1]).write_text(json.dumps(workflow), encoding="utf-8")
            with self.assertRaises(ValueError):
                write_workflows(root, output)
            self.assertTrue(all(p.read_text(encoding="utf-8") == "existing output"
                                for p in output.iterdir()))



def source_node(workflow, node_id):
    return next(n for n in workflow["nodes"] if n["id"] == node_id)


if __name__ == "__main__":
    unittest.main()
