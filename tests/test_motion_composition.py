import json
from dataclasses import replace
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from core.artifacts import DirectionArtifact
from core.direction.enhancer import DirectionEnhancerInput, enhance_direction, split_staging_directives
from core.direction.profile_loader import load_direction_profile
from core.direction.profiles import (MOTION_COMPOSITION_RESELECTIONS, MOTION_COMPOSITION_TIMINGS, MOTION_PROFILES,
                                     MOTION_TEMPLATES, planner_profile_metadata)
from core.emd import parse_emd
from core.emd.motion_templates import split_motion_templates
from core.planner import plan_timeline, PlannerContent
from core.planner.motion_composition import select_motion_composition
from core.planner.scene_author import build_composition_choice_grammar, count_motion_composition_choices
from core.planner.template import parse_template_emd
from types import SimpleNamespace
from core.compiler.ref2va import compile_ref2va
from core.compiler.translator import IdentityTranslator
from nodes.node_timeline_planner.node import _system_prompts
from test_scene_author import Backend, CONCEPT, _runtime


TEMPLATE = (
    "> `シーン` 1\n# シーン 00:00.000 --> 00:08.000\n* `H3長` 192\n"
    "## ショット 00:00.000\n* 未計画\n"
    "## ショット 00:04.000\n* 未計画\n")


def run(backend, direction, template=TEMPLATE, concept=CONCEPT):
    return plan_timeline(
        backend, template_emd=template, concept_emd=concept, direction=direction,
        lip_sync_mode="off", lip_sync_target="サブジェクト1", lip_sync_audio_slot=1,
        scenes_per_batch=1, system_prompts=_system_prompts(), runtime_config=_runtime())


class MotionCompositionTests(unittest.TestCase):
    def test_user_sections_are_separated(self):
        text = "# 共通プロンプト\n* 夜。\n# モーション補完\n* 一歩踏み替える。\n# 演出候補\n* 花が舞う。"
        clean, candidates = split_staging_directives(text)
        self.assertEqual(clean, "# 共通プロンプト\n* 夜。")
        self.assertEqual(candidates, ("花が舞う。",))
        self.assertEqual(split_motion_templates(text)[1], ("一歩踏み替える。",))
        self.assertIsNone(split_motion_templates("指定なし")[1])
        self.assertEqual(split_motion_templates("# モーション補完\n* 無効")[1], ())

    def test_invalid_directive_is_not_silently_ignored(self):
        for text in ("# モーション補完", "# モーション補完\n本文",
                     "# モーション補完\n* 無効\n* 動く。",
                     "# モーション補完\n* 動く。\n# モーション補完\n* 動く。",
                     "# モーション補完\n" + "* 動く。\n" * 13):
            with self.subTest(text=text), self.assertRaises(ValueError):
                split_motion_templates(text)

    def test_artifact_distinguishes_inherit_disabled_and_custom(self):
        for value in (None, (), ("両足で支える。",)):
            direction = DirectionArtifact(motion_templates=value)
            restored = DirectionArtifact.from_dict(json.loads(direction.to_json()))
            self.assertEqual(restored.motion_templates, value)

    def test_profile_templates_are_not_global_prompt(self):
        self.assertNotIn("支持足で身体を受け", MOTION_PROFILES["anime_scene_composed_mv"])
        meta = planner_profile_metadata("", "anime_scene_composed_mv")
        self.assertEqual(len(meta["motion_templates"]), 3)
        self.assertEqual(meta["composition_timing"], "post_author")
        self.assertEqual(meta["composition_reselection"], "guarded_no_drop")
        self.assertIn("支持足で身体を受け", meta["motion_templates"][0])
        self.assertIn("新しい足場に着く", meta["motion_templates"][1])
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "wrong.md"
            path.write_text("# 共通プロンプト\n## スタイル\n* アニメ。\n# モーション補完\n* 動く。", encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "only by motion"):
                load_direction_profile(path, "style")

    def test_post_author_composition_keeps_llm_requests_clean_and_reaches_emd(self):
        backend = Backend()
        direction = DirectionArtifact(motion_profile_id="anime_scene_composed_mv")
        with self.assertLogs("mv_director.nodes", level="INFO") as logs:
            result = run(backend, direction)
        self.assertTrue(result.complete)
        addition = result.content.motion_compositions[0]
        self.assertEqual(addition[:4], (1, 1, "profile:anime_scene_composed_mv", 1))
        raw = "胸から腕へ動きを渡し、手を離す。"
        self.assertEqual(result.content.actions[0][2], raw)
        camera = next(p for task, p in backend.calls if task == "scene-author-camera")
        self.assertEqual(camera["accepted_performances"]["1"], raw)
        performance = next(p for task, p in backend.calls if task == "scene-author-performance")
        self.assertNotIn("scheduled_motion_composition", performance)
        self.assertNotIn(addition[4], json.dumps(camera, ensure_ascii=False))
        self.assertEqual(result.emd.text.count(addition[4]), 1)
        self.assertIn("> `モーション補完` source=profile:", result.emd.text)
        doc = parse_emd(result.emd.text)
        self.assertEqual(len([d for d in doc.scenes[0].shots[0].directives if d.kind == "演技"]), 2)
        self.assertFalse(any("sha256=" in b for s in doc.scenes for shot in s.shots for b in shot.body))
        self.assertEqual(PlannerContent.from_dict(result.content.to_dict()), result.content)
        self.assertTrue(any("motion composition scheduled" in line for line in logs.output))
        self.assertTrue(any("timing=post_author" in line for line in logs.output))
        self.assertEqual(sum(task == "scene-author-composition-choice" for task, _ in backend.calls), 1)
        compiled = compile_ref2va(result.emd.text, IdentityTranslator())
        serialized = json.dumps(compiled.plan, ensure_ascii=False)
        self.assertIn(addition[4], serialized)
        self.assertNotIn("sha256=", serialized)
        self.assertNotIn("モーション補完", serialized)

    def test_pre_author_timing_remains_available_for_existing_profiles(self):
        backend = Backend()
        with patch.dict(MOTION_COMPOSITION_TIMINGS,
                        {"anime_scene_composed_mv": "pre_author"}):
            result = run(backend, DirectionArtifact(
                motion_profile_id="anime_scene_composed_mv"))
        addition = result.content.motion_compositions[0]
        performance = next(p for task, p in backend.calls if task == "scene-author-performance")
        camera = next(p for task, p in backend.calls if task == "scene-author-camera")
        self.assertEqual(performance["scheduled_motion_composition"]["text"], addition[4])
        self.assertEqual(camera["accepted_performances"]["1"],
                         "胸から腕へ動きを渡し、手を離す。 " + addition[4])
        self.assertEqual(result.emd.text.count(addition[4]), 1)

    def test_choice_changes_only_optional_composition_after_camera(self):
        class ChoiceBackend(Backend):
            def complete_planner(self, *, task, payload, **kwargs):
                if task == "scene-author-composition-choice":
                    request = json.loads(payload)
                    self.calls.append((task, request))
                    return "CHOICE\t1\t2"
                return super().complete_planner(task=task, payload=payload, **kwargs)

        backend = ChoiceBackend()
        result = run(backend, DirectionArtifact(motion_profile_id="anime_scene_composed_mv"))
        self.assertTrue(result.complete)
        self.assertEqual(result.content.motion_compositions[0][3], 2)
        self.assertEqual(result.content.motion_compositions[0][4], MOTION_TEMPLATES["anime_scene_composed_mv"][1])
        self.assertEqual(result.content.actions[0][2], "胸から腕へ動きを渡し、手を離す。")
        choice = next(payload for task, payload in backend.calls if task == "scene-author-composition-choice")
        self.assertEqual(choice["current_choice"], 1)
        self.assertEqual(choice["shots"][0]["performance"], result.content.actions[0][2])
        self.assertIn("Arc Shot", choice["shots"][0]["camera"])
        self.assertEqual(count_motion_composition_choices(
            parse_template_emd(TEMPLATE), DirectionArtifact(motion_profile_id="anime_scene_composed_mv"), CONCEPT,
        ), 1)

    def test_invalid_choice_retries_then_keeps_original(self):
        class InvalidBackend(Backend):
            def complete_planner(self, *, task, payload, **kwargs):
                if task == "scene-author-composition-choice":
                    request = json.loads(payload)
                    self.calls.append((task, request))
                    return "CHOICE\t1\t0"
                return super().complete_planner(task=task, payload=payload, **kwargs)

        backend = InvalidBackend()
        result = run(backend, DirectionArtifact(motion_profile_id="anime_scene_composed_mv"))
        self.assertTrue(result.complete)
        self.assertEqual(result.content.motion_compositions[0][3], 1)
        calls = [payload for task, payload in backend.calls if task == "scene-author-composition-choice"]
        self.assertEqual(len(calls), 2)
        self.assertEqual(calls[1]["retry"], "invalid_choice_only")
        self.assertIn('"10"', build_composition_choice_grammar(12))
        with self.assertRaises(ValueError):
            build_composition_choice_grammar(13)

    def test_reselection_off_preserves_previous_path(self):
        backend = Backend()
        with patch.dict(MOTION_COMPOSITION_RESELECTIONS,
                        {"anime_scene_composed_mv": "off"}):
            result = run(backend, DirectionArtifact(motion_profile_id="anime_scene_composed_mv"))
        self.assertTrue(result.complete)
        self.assertFalse(any(task == "scene-author-composition-choice" for task, _ in backend.calls))

    def test_post_author_timing_survives_author_common_motion_override(self):
        backend = Backend()
        result = run(backend, DirectionArtifact(
            motion_profile_id="passthrough",
            motion_policy_profile_id="anime_scene_composed_mv",
            motion_templates=("作者指定の一歩。",),
        ))
        self.assertEqual(result.content.motion_compositions[0][2], "user")
        self.assertEqual(result.emd.text.count("作者指定の一歩。"), 1)
        performance = next(p for task, p in backend.calls if task == "scene-author-performance")
        camera = next(p for task, p in backend.calls if task == "scene-author-camera")
        self.assertNotIn("scheduled_motion_composition", performance)
        self.assertNotIn("作者指定の一歩。", json.dumps(camera, ensure_ascii=False))

    def test_user_replaces_profile_and_disabled_stays_off(self):
        for templates in ((), ("人物が体重を左から右へ渡す。",)):
            result = run(Backend(), DirectionArtifact(
                motion_profile_id="anime_scene_composed_mv", motion_templates=templates))
            self.assertEqual(len(result.content.motion_compositions), len(templates))
            if templates:
                self.assertEqual(result.content.motion_compositions[0][2], "user")
                self.assertEqual(result.content.motion_compositions[0][4], templates[0])
            self.assertNotIn(MOTION_TEMPLATES["anime_scene_composed_mv"][0], result.emd.text)

    def test_manual_performance_generic_body_and_short_shot_are_not_modified(self):
        direction = DirectionArtifact(motion_profile_id="anime_scene_composed_mv")
        sources = [
            TEMPLATE.replace("* 未計画", "* `演技` 両足を揃えて静止する。", 1),
            TEMPLATE.replace("* 未計画", "* 作者の演技をそのまま維持する。", 1),
            TEMPLATE.replace("00:08.000", "00:02.000").replace("192", "39").replace("00:04.000", "00:01.000"),
            TEMPLATE.replace("* 未計画", "* `カメラ` 顔だけを映す。"),
        ]
        for source in sources:
            with self.subTest(source=source):
                result = run(Backend(), direction, source)
                self.assertTrue(result.complete)
                self.assertEqual(result.content.motion_compositions, ())

    def test_existing_profile_keeps_composition_off(self):
        result = run(Backend(), DirectionArtifact(motion_profile_id="anime_scene_author_mv"))
        self.assertEqual(result.content.motion_compositions, ())

    def test_cycle_and_authored_common_priority(self):
        positions = [{"shot": 1, "start_ms": 0, "end_ms": 4000, "fixed_camera": "",
                      "fixed_performance": "", "author_body": []}]
        direction = DirectionArtifact(motion_profile_id="anime_scene_composed_mv")
        for scene, expected in ((1, 1), (2, 2), (3, 3), (4, 1)):
            selected, _ = select_motion_composition(SimpleNamespace(scene_number=scene), positions, direction, CONCEPT)
            self.assertEqual(selected[3], expected)
        authored = replace(direction, motion_profile_id="passthrough",
                           motion_policy_profile_id="anime_scene_composed_mv")
        self.assertEqual(select_motion_composition(SimpleNamespace(scene_number=1), positions, authored, CONCEPT),
                         (None, "authored_common_motion"))
        selected, _ = select_motion_composition(SimpleNamespace(scene_number=1), positions,
            replace(authored, motion_templates=("作者の補完。",)), CONCEPT)
        self.assertEqual(selected[4], "作者の補完。")

    def test_rerendered_emd_does_not_add_again(self):
        direction = DirectionArtifact(motion_profile_id="anime_scene_composed_mv")
        first = run(Backend(), direction)
        template = first.emd.text[first.emd.text.index("> `シーン`"):]
        backend = Backend()
        second = run(backend, direction, template)
        self.assertTrue(second.complete)
        self.assertEqual(second.content.motion_compositions, ())
        self.assertEqual(backend.calls, [])
        self.assertEqual(second.emd.text.count(first.content.motion_compositions[0][4]), 1)

    def test_enhancer_transports_user_templates_without_global_leak(self):
        class EnhancerBackend:
            def complete_direction(self, **kwargs):
                self.payload = json.loads(kwargs["payload"])
                return "MVD_LLM_RECORDS_V1\nSTYLE\t1\tセルアニメ。\nEND"
        backend = EnhancerBackend()
        result = enhance_direction(
            backend, value=DirectionEnhancerInput(
                motion_profile="anime_scene_composed_mv",
                user_request="# モーション補完\n* 人物が踏み替える。"),
            system_prompt="test", runtime_config=_runtime())
        self.assertEqual(result.direction.motion_templates, ("人物が踏み替える。",))
        self.assertNotIn("人物が踏み替える", json.dumps(backend.payload, ensure_ascii=False))
        self.assertNotIn("人物が踏み替える", result.direction_emd_preview)
