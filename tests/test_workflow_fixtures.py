import json
from pathlib import Path
import unittest

from core.compiler import IdentityTranslator, compile_ref2va
from core.utilities import decode_embedded_text


FIXTURE_DIR = Path(__file__).parent / "fixtures" / "workflows"


def load_fixture(name: str) -> dict:
    return json.loads((FIXTURE_DIR / name).read_text(encoding="utf-8"))


def node_map(workflow: dict) -> dict[int, dict]:
    return {node["id"]: node for node in workflow["nodes"]}


class WorkflowFixtureTests(unittest.TestCase):
    def test_fixture_json_links_reference_existing_nodes(self) -> None:
        for path in sorted(FIXTURE_DIR.glob("*.json")):
            with self.subTest(path=path.name):
                workflow = json.loads(path.read_text(encoding="utf-8"))
                nodes = node_map(workflow)
                self.assertEqual(workflow["version"], 0.4)
                for link in workflow["links"]:
                    self.assertIn(link[1], nodes)
                    self.assertIn(link[3], nodes)

    def test_srt_only_routes_embedded_lyrics_to_segmentation_and_saver(self) -> None:
        workflow = load_fixture("srt_only.json")
        nodes = node_map(workflow)
        self.assertEqual(nodes[2]["type"], "MVDirectorLoadTextFile")
        self.assertEqual(nodes[4]["type"], "MVDirectorLyricSegmentation")
        self.assertEqual(nodes[5]["type"], "SaveText|pysssss")
        self.assertIn([2, 2, 0, 4, 1, "STRING"], workflow["links"])
        self.assertIn([4, 4, 1, 5, 0, "STRING"], workflow["links"])

    def test_compiler_only_has_no_image_or_upstream_core_dependency(self) -> None:
        workflow = load_fixture("ref2va_compiler_only.json")
        nodes = node_map(workflow)
        types = {node["type"] for node in workflow["nodes"]}
        self.assertNotIn("MVDirectorImageToSubjectEMD", types)
        self.assertNotIn("MVDirectorTimelinePlanner", types)
        self.assertEqual(nodes[3]["type"], "MVDirectorEMDCompiler")
        self.assertEqual(nodes[3]["widgets_values"][-2:], ["randomize", "reuse"])
        self.assertIn([4, 3, 0, 5, 1, "STRING"], workflow["links"])
        encoded, basename, metadata = nodes[1]["widgets_values"]
        emd = decode_embedded_text(encoded, basename, metadata)
        result = compile_ref2va(emd, IdentityTranslator())
        self.assertEqual(result.required_references.references, ())
        self.assertEqual(json.loads(result.plan_json())["shots"][0]["length"], 22)

    def test_auto_h3_uses_image_node_passthrough_to_picture_one(self) -> None:
        workflow = load_fixture("image_subject_auto_h3.json")
        nodes = node_map(workflow)
        self.assertEqual(nodes[2]["type"], "MVDirectorImageToSubjectEMD")
        self.assertEqual(nodes[2]["widgets_values"][-2:], ["randomize", "reuse"])
        self.assertEqual(nodes[3]["type"], "MiniMaxH3ReferenceToVideo")
        self.assertIn([1, 1, 0, 2, 0, "IMAGE"], workflow["links"])
        self.assertIn([2, 2, 2, 3, 0, "IMAGE"], workflow["links"])
        self.assertEqual(nodes[3]["inputs"][0]["name"], "ref_images.ref_image_0")


if __name__ == "__main__":
    unittest.main()
