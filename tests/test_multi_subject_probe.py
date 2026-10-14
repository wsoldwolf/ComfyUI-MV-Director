"""CPU preparation of the production-node probe, never model execution."""
import json
from pathlib import Path
import unittest

from tools.debug_multi_subject_pipeline import (
    NODE_STAGES, implementation_manifest, prepare, workflow_settings,
)


ROOT = Path(__file__).resolve().parents[1]
WORKFLOW = ROOT / "workflows/01_plan_compiler_context_loop.json"
CASE = {
    "seed": 20261013,
    "concept_emd": "# サブジェクト\n* 一人目の人物。\n",
    "concept_emd_2": "# サブジェクト\n* 二人目の人物。\n",
    "concept_emd_3": "# サブジェクト\n* 木。\n",
    "concept_emd_4": "# サブジェクト\n* 舞台。\n",
    "user_request": "役割と衣装を区別する。",
    "template_emd": "> `シーン` 1\n# シーン 00:00.000 --> 00:08.000\n"
                    "* `H3長` 192\n## ショット 00:00.000\n* 未計画\n",
}


class MultiSubjectProbeTests(unittest.TestCase):
    def test_manifest_records_source_hashes_without_research_or_models(self):
        manifest = implementation_manifest()
        self.assertIn("prompts/timeline_planner_scene_author_performance_system_prompt.txt", manifest)
        self.assertIn("core/compiler/ref2va.py", manifest)
        self.assertTrue(all(len(value) == 64 for value in manifest.values()))
        self.assertFalse(any("research" in name or name.endswith(".gguf") for name in manifest))

    def setUp(self):
        self.workflow = json.loads(WORKFLOW.read_text(encoding="utf-8"))

    def test_real_workflow_widgets_match_each_production_schema(self):
        for stage, _, cls in NODE_STAGES:
            with self.subTest(stage=stage):
                settings = workflow_settings(self.workflow, cls)
                self.assertTrue(settings["model_name"].endswith("Q4_K_S.gguf"))
                self.assertEqual(settings["max_tokens"], 4096)
                self.assertEqual(settings["kv_cache_type"], "q8_0")
                self.assertEqual(settings["cache_mode"], "disabled")
                self.assertIs(settings["keep_model_loaded"], False)

    def test_seed_control_is_not_mistaken_for_cache_widget(self):
        cls = NODE_STAGES[1][2]
        settings = workflow_settings(self.workflow, cls)
        self.assertEqual(settings["seed"], 1)
        self.assertEqual(settings["staging_candidate_policy"], "optional")
        self.assertIs(settings["save_debug_output"], False)

    def test_schema_drift_requires_explicit_migration(self):
        cls = NODE_STAGES[0][2]
        for delta in ("missing", "extra"):
            changed = json.loads(json.dumps(self.workflow))
            item = next(n for n in changed["nodes"] if n["type"] == cls.__name__)
            if delta == "missing":
                item["widgets_values"].pop()
            else:
                item["widgets_values"].append("unmapped")
            with self.subTest(delta=delta), self.assertRaisesRegex(ValueError, "widget"):
                workflow_settings(changed, cls)

    def test_all_four_ports_merge_once_before_planner_without_inference(self):
        value = prepare(CASE, self.workflow)
        self.assertEqual(value["subject_count"], 4)
        self.assertEqual(value["scene_count"], 1)
        self.assertTrue(value["enhancer_requires_inference"])
        self.assertEqual(value["planner"]["concept_emd"].count("# サブジェクト"), 1)
        self.assertNotIn("concept_emd_2", value["planner"])
        self.assertEqual(value["enhancer"]["concept_emd_4"], CASE["concept_emd_4"])
        for stage, _, _ in NODE_STAGES:
            self.assertEqual(value[stage]["seed"], CASE["seed"])
        self.assertEqual(value["subject_map"][3]["concept_id"], "サブジェクト4")

    def test_single_subject_control_and_empty_case_are_distinct(self):
        single = {k: v for k, v in CASE.items() if k not in (
            "concept_emd_2", "concept_emd_3", "concept_emd_4")}
        self.assertEqual(prepare(single, self.workflow)["subject_count"], 1)
        with self.assertRaisesRegex(ValueError, "at least one Subject"):
            prepare({**single, "concept_emd": ""}, self.workflow)


if __name__ == "__main__":
    unittest.main()
