"""Four-port Subject merging and node integration, without models or GPU."""

import itertools
import json
from types import SimpleNamespace
import unittest
from unittest.mock import MagicMock, patch

from core.compiler import IdentityTranslator, compile_ref2va
from core.direction import DirectionEnhancerError, DirectionEnhancerInput, build_direction_payload
from core.emd import SubjectEMDFragmentError, merge_subject_emd, parse_emd
from core.planner import TimelinePlannerError, normalize_concept_emd
from core.planner.template import DEFAULT_CONCEPT_EMD
from nodes import NODE_CLASS_MAPPINGS


SUBJECTS = tuple(f"# サブジェクト\n* `画像{i}` Person {i}.\n" for i in range(1, 5))
AUTHORED_TEMPLATE = (
    "> `シーン` 1\n# シーン 00:00.000 --> 00:01.000\n* `H3長` 22\n"
    "## ショット 00:00.000\n"
    "* `演出` Wind moves the leaves.\n"
    "* `演技` `サブジェクト1` waves.\n"
    "* `カメラ` Static Shot.\n"
)


def enhancer_args(**overrides):
    values = dict(
        user_request="", style_profile="anime_emotional_mv",
        motion_profile="anime_emotional_mv", camera_profile="anime_emotional_mv",
        model_name="unused.gguf", chat_format="", max_tokens=768,
        temperature=0.2, top_p=0.9, repetition_penalty=1.05, gpu_layers=-1,
        n_batch=256, n_ctx=24576, flash_attn=True, kv_cache_type="q8_0",
        op_offload=True, keep_model_loaded=False, seed=1, cache_mode="reuse",
        retention_policy="compiler_default",
    )
    values.update(overrides)
    return values


def planner_args(**overrides):
    values = enhancer_args()
    for name in ("user_request", "style_profile", "motion_profile", "camera_profile", "retention_policy"):
        del values[name]
    values.update(template_emd=AUTHORED_TEMPLATE, lip_sync_mode="off",
                  lip_sync_target="サブジェクト1", lip_sync_audio_slot=1, chat_format="auto")
    values.update(overrides)
    return values


class SubjectFragmentTests(unittest.TestCase):
    def test_single_fragment_is_lossless_except_outer_whitespace_and_newlines(self):
        raw = " \r\n# サブジェクト\r\n\r\n* `画像9` `動画3` Person  with spacing.\r\n "
        result = merge_subject_emd(raw)
        expected = "# サブジェクト\n\n* `画像9` `動画3` Person  with spacing.\n"
        self.assertEqual(result.text, expected)
        self.assertEqual(normalize_concept_emd(raw), expected)

    def test_four_inputs_keep_media_slots_and_source_order(self):
        result = merge_subject_emd(*SUBJECTS)
        document = parse_emd(result.text + AUTHORED_TEMPLATE)
        self.assertEqual(result.text.count("# サブジェクト"), 1)
        self.assertEqual([s.concept_id for s in document.subjects], [f"サブジェクト{i}" for i in range(1, 5)])
        self.assertEqual([s.references for s in document.subjects], [(f"<Picture {i}>",) for i in range(1, 5)])
        self.assertEqual(result.bindings[3].to_dict(), {
            "input_name": "concept_emd_4", "input_subject_index": 1, "concept_id": "サブジェクト4",
        })
        json.dumps([item.to_dict() for item in result.bindings])

    def test_all_empty_and_sparse_input_combinations(self):
        for enabled in itertools.product((False, True), repeat=4):
            with self.subTest(enabled=enabled):
                result = merge_subject_emd(*(s if present else "\n " for s, present in zip(SUBJECTS, enabled)))
                indices = [i for i, present in enumerate(enabled, 1) if present]
                self.assertEqual(len(result.bindings), len(indices))
                if indices:
                    document = parse_emd(result.text + AUTHORED_TEMPLATE)
                    self.assertEqual([s.description for s in document.subjects], [f"Person {i}." for i in indices])
                    self.assertEqual([s.concept_id for s in document.subjects], [f"サブジェクト{i}" for i in range(1, len(indices) + 1)])
                else:
                    self.assertEqual(result.text, "")
                    self.assertEqual(normalize_concept_emd(result.text), DEFAULT_CONCEPT_EMD)

    def test_existing_multi_row_fragment_can_be_followed_by_other_ports(self):
        first = "# サブジェクト\n* `画像7` A.\n* `画像3` B.\n"
        result = merge_subject_emd(first, "", SUBJECTS[2], SUBJECTS[3])
        self.assertEqual([b.input_subject_index for b in result.bindings], [1, 2, 1, 1])
        self.assertIn("concept_emd_3[1]=サブジェクト3", result.status)

    def test_same_description_or_shared_reference_is_not_deduplicated(self):
        result = merge_subject_emd(SUBJECTS[0], SUBJECTS[0])
        self.assertEqual(len(result.bindings), 2)
        self.assertEqual(result.text.count("Person 1."), 2)

    def test_total_limit_is_four_rows_not_four_ports(self):
        four = "# サブジェクト\n" + "* Person.\n" * 4
        self.assertEqual(len(merge_subject_emd(four).bindings), 4)
        with self.assertRaisesRegex(SubjectEMDFragmentError, "exceeded at concept_emd_2"):
            merge_subject_emd(four, SUBJECTS[1])
        with self.assertRaisesRegex(SubjectEMDFragmentError, "at most 4"):
            merge_subject_emd(four + "* Fifth.\n")

    def test_invalid_input_identifies_port(self):
        for invalid in (None, 12, "\x00", "# サブジェクト\n", "# サブジェクト\n* `画像0` Bad.",
                        "# シーン設定\n## 環境\n* Sea.", SUBJECTS[0] + AUTHORED_TEMPLATE):
            with self.subTest(invalid=invalid), self.assertRaisesRegex(SubjectEMDFragmentError, "concept_emd_3"):
                merge_subject_emd(concept_emd_3=invalid)

    def test_compiler_receives_global_subjects_and_unchanged_media_slots(self):
        result = merge_subject_emd(*SUBJECTS)
        emd = result.text + AUTHORED_TEMPLATE.replace("サブジェクト1", "サブジェクト4")
        compiled = compile_ref2va(emd, IdentityTranslator())
        references = compiled.required_references.references
        self.assertEqual([(r.concept_id, r.subject_ref, r.h3_ref, r.required_input) for r in references], [
            (f"サブジェクト{i}", f"<Subject {i}>", f"<Picture {i}>", f"ref_images.ref_image_{i - 1}")
            for i in range(1, 5)
        ])
        self.assertIn("<Subject 4> waves.", compiled.plan_json())


class MultiSubjectNodeTests(unittest.TestCase):
    def test_optional_ports_are_appended_without_widgets(self):
        for node_type in ("MVDirectorDirectionEnhancer", "MVDirectorTimelinePlanner"):
            optional = NODE_CLASS_MAPPINGS[node_type].INPUT_TYPES()["optional"]
            self.assertEqual(list(optional)[-3:], ["concept_emd_2", "concept_emd_3", "concept_emd_4"])
            for name in list(optional)[-3:]:
                self.assertEqual(optional[name], ("STRING", {"forceInput": True}))
        self.assertEqual(NODE_CLASS_MAPPINGS["MVDirectorDirectionEnhancer"].RETURN_NAMES,
                         ("direction", "direction_emd_preview", "status", "subjects_emd"))

    def test_direction_core_merges_and_retains_per_port_provenance(self):
        from core.direction import enhance_direction
        from core.inference import LlamaRuntimeConfig
        value = DirectionEnhancerInput(concept_emd=SUBJECTS[0], concept_emd_4=SUBJECTS[3])
        payload = json.loads(build_direction_payload(value))
        self.assertEqual(payload["concept_emd"], merge_subject_emd(SUBJECTS[0], concept_emd_4=SUBJECTS[3]).text.strip())
        backend = SimpleNamespace(complete_direction=MagicMock(return_value="STYLE\t1\t画風。"))
        result = enhance_direction(backend, value=value, system_prompt="fixed", runtime_config=LlamaRuntimeConfig())
        sources = [p.source_ref for p in result.direction.provenance if p.source == "vision"]
        self.assertEqual(sources, ["concept_emd", "concept_emd_4"])
        self.assertEqual(backend.complete_direction.call_count, 1)

    def test_enhancer_no_model_branch_returns_merged_output_in_fourth_slot(self):
        node = NODE_CLASS_MAPPINGS["MVDirectorDirectionEnhancer"]()
        request = "# 共通プロンプト\n## スタイル\n* 実写。\n## モーション\n* 演技。\n## カメラ\n* 撮影。\n"
        with patch("nodes.node_direction_enhancer.node.resolve_comfy_gguf_model", side_effect=AssertionError("no GPU")):
            result = node.enhance(**enhancer_args(user_request=request, concept_emd=SUBJECTS[0], concept_emd_4=SUBJECTS[3]))
        self.assertEqual(result[3], merge_subject_emd(SUBJECTS[0], concept_emd_4=SUBJECTS[3]).text)
        self.assertIn("concept_emd_4[1]=サブジェクト2", result[2])

    def test_empty_enhancer_does_not_invent_a_subject(self):
        value = DirectionEnhancerInput()
        self.assertEqual(value.normalized_concept_emd, "")
        self.assertEqual(value.merged_subjects.text, "")

    def test_retention_validation_uses_merged_subject_count(self):
        value = DirectionEnhancerInput(
            concept_emd=SUBJECTS[0], concept_emd_4=SUBJECTS[3], retention_policy="passthrough",
            direction_emd_passthrough="# 保持分析\n* `サブジェクト2`: `fully_preserved` 保持する。\n",
        )
        value.validate()

    def test_planner_authored_shots_accept_four_ports_without_loading_a_model(self):
        node = NODE_CLASS_MAPPINGS["MVDirectorTimelinePlanner"]()
        with patch("nodes.node_timeline_planner.node.resolve_comfy_gguf_model", side_effect=AssertionError("no GPU")):
            result = node.plan(**planner_args(**dict(zip(
                ("concept_emd", "concept_emd_2", "concept_emd_3", "concept_emd_4"), SUBJECTS,
            ))))
        self.assertEqual(len(parse_emd(result[0]).subjects), 4)
        self.assertIn("subjects=4", result[2])
        self.assertIn("source=author_shots", result[2])

    def test_overflow_is_rejected_before_model_resolution(self):
        four = "# サブジェクト\n" + "* Person.\n" * 4
        for node_type, args, module, error in (
            ("MVDirectorDirectionEnhancer", enhancer_args, "node_direction_enhancer", DirectionEnhancerError),
            ("MVDirectorTimelinePlanner", planner_args, "node_timeline_planner", TimelinePlannerError),
        ):
            with self.subTest(node=node_type):
                node = NODE_CLASS_MAPPINGS[node_type]()
                with patch(f"nodes.{module}.node.resolve_comfy_gguf_model", side_effect=AssertionError("no GPU")), self.assertRaisesRegex(error, "at most 4"):
                    getattr(node, node.FUNCTION)(**args(concept_emd=four, concept_emd_2=SUBJECTS[1]))

    def test_full_author_emd_owns_subjects_and_reports_ignored_inputs(self):
        node = NODE_CLASS_MAPPINGS["MVDirectorTimelinePlanner"]()
        authored = SUBJECTS[0] + AUTHORED_TEMPLATE
        with self.assertLogs("mv_director.nodes", level="WARNING"), patch(
            "nodes.node_timeline_planner.node.resolve_comfy_gguf_model", side_effect=AssertionError("no GPU"),
        ):
            result = node.plan(**planner_args(template_emd=authored, concept_emd_2="Not a valid fragment"))
        self.assertEqual(result[0], authored)
        self.assertIn("subject_inputs=ignored_author_emd", result[2])

    def test_enhancer_cache_is_separated_by_source_ports_and_changed_subjects(self):
        store = {}
        cache = SimpleNamespace(get=lambda key: store.get(key),
                                put_success=lambda key, payload: store.update({key: json.loads(json.dumps(payload))}))
        model = SimpleNamespace(selection_id="model", fingerprint="hash", size=1, mtime_ns=1, path="unused.gguf")
        node = NODE_CLASS_MAPPINGS["MVDirectorDirectionEnhancer"]()
        node._lifecycle = SimpleNamespace(ensure_loaded=MagicMock(), clear=MagicMock())
        node._backend = SimpleNamespace(complete_direction=MagicMock(return_value="STYLE\t1\t画風。"))
        args = enhancer_args(concept_emd=SUBJECTS[0], concept_emd_2=SUBJECTS[1])
        with patch("nodes.node_direction_enhancer.node.resolve_comfy_gguf_model", return_value=model), patch(
            "nodes.node_direction_enhancer.node._cache", return_value=cache,
        ):
            first = node.enhance(**args)
            hit = node.enhance(**args)
            moved = node.enhance(**{**args, "concept_emd_2": "", "concept_emd_4": SUBJECTS[1]})
            changed = node.enhance(**{**args, "concept_emd_2": SUBJECTS[2]})
        self.assertIn("cache=hit", hit[2])
        self.assertEqual(first[3], moved[3])
        self.assertNotEqual(first[3], changed[3])
        self.assertEqual(node._backend.complete_direction.call_count, 3)
        self.assertIn("concept_emd_4", [p.source_ref for p in moved[0].provenance])

    def test_planner_stages_and_cache_use_merged_text_without_per_subject_calls(self):
        from scene_author_fixtures import Backend
        fake = Backend()
        stage_calls = []

        def complete(**kwargs):
            stage_calls.append(kwargs)
            if kwargs["task"] == "subject-prop-inventory":
                return 'PROP_INVENTORY\t1\t{"props":[]}'
            return fake.complete_planner(**kwargs)

        store = {}
        cache = SimpleNamespace(get=lambda key: store.get(key),
                                put_success=lambda key, payload: store.update({key: json.loads(json.dumps(payload))}))
        model = SimpleNamespace(selection_id="model", fingerprint="hash", size=1, mtime_ns=1, path="unused.gguf")
        node = NODE_CLASS_MAPPINGS["MVDirectorTimelinePlanner"]()
        node._lifecycle = SimpleNamespace(ensure_loaded=MagicMock(), clear=MagicMock(), effective_n_ctx=24576)
        node._backend.complete_planner = complete
        args = planner_args(
            concept_emd=SUBJECTS[0], concept_emd_4=SUBJECTS[3], save_debug_output=True,
            template_emd=AUTHORED_TEMPLATE + "## ショット 00:00.500\n* 未計画\n",
            lip_sync_mode="context_loop", lip_sync_target="サブジェクト2",
        )
        with patch("nodes.node_timeline_planner.node.resolve_comfy_gguf_model", return_value=model), patch(
            "nodes.node_timeline_planner.node._cache", return_value=cache,
        ), patch("nodes.node_timeline_planner.node._debug_write", return_value="debug.json") as debug:
            first = node.plan(**args)
            hit = node.plan(**args)
            changed = node.plan(**{**args, "concept_emd_4": SUBJECTS[2]})
        self.assertIn("cache=hit", hit[2])
        self.assertEqual(first[0], hit[0])
        self.assertNotEqual(first[0], changed[0])
        self.assertEqual([call["task"] for call in stage_calls[:4]], [
            "subject-prop-inventory", "scene-author-event", "scene-author-performance", "scene-author-camera",
        ])
        self.assertEqual(len(stage_calls), 8)
        merged_text = merge_subject_emd(SUBJECTS[0], concept_emd_4=SUBJECTS[3]).text
        for call in stage_calls[:4]:
            self.assertEqual(json.loads(call["payload"])["subject_emd"], merged_text)
        self.assertEqual(debug.call_args.args[1]["subject_map"][1], {
            "input_name": "concept_emd_4", "input_subject_index": 1, "concept_id": "サブジェクト2",
        })
        self.assertIn("`Context Loop` `サブジェクト2`", first[0])


if __name__ == "__main__":
    unittest.main()
