"""Current-only Planner contracts: no model or GPU required."""
import json
import unittest
from unittest.mock import patch

from core.artifacts import DirectionArtifact
from core.planner import PlannerContent, TimelinePlannerError, plan_timeline
from core.inference import LlamaRuntimeConfig, TokenCount
from nodes import NODE_CLASS_MAPPINGS
from nodes.node_timeline_planner.node import _LlamaPlannerBackend, _system_prompts
from scene_author_fixtures import Backend, CONCEPT, TEMPLATE, _runtime


class PlannerApiTests(unittest.TestCase):
    def plan(self, direction=None, **overrides):
        backend = Backend()
        kwargs = dict(
            template_emd=TEMPLATE, concept_emd=CONCEPT,
            direction=direction, lip_sync_mode="off", lip_sync_target="サブジェクト1",
            lip_sync_audio_slot=1,
            system_prompts=_system_prompts(), runtime_config=_runtime(),
        )
        kwargs.update(overrides)
        return backend, plan_timeline(backend, **kwargs)

    def test_every_profile_and_passthrough_uses_scene_author(self):
        for profile in ("", "passthrough", "anime_emotional_mv", "anime_story_mv",
                        "natural_performance", "limited_animation"):
            with self.subTest(profile=profile):
                backend, result = self.plan(DirectionArtifact(motion_profile_id=profile))
                self.assertTrue(result.complete)
                self.assertEqual([task for task, _ in backend.calls],
                                 ["scene-author-event", "scene-author-performance", "scene-author-camera"])
                self.assertIn("* `演技` 人物が片手を胸元に置く。", result.emd.text)

    def test_cache_is_strict_json_and_round_trips(self):
        _, result = self.plan()
        serialized = json.loads(json.dumps(result.content.to_dict()))
        self.assertEqual(PlannerContent.from_dict(serialized), result.content)
        self.assertEqual(serialized["schema"], "MVD_SCENE_AUTHOR_CONTENT_V1")
        for key in ("visual_beats", "song_direction", "shot_layouts", "scene_spine_steps",
                    "layout_mix_retry", "action_repetition_warning_count"):
            self.assertNotIn(key, serialized)
        with self.assertRaisesRegex(ValueError, "obsolete Planner cache"):
            PlannerContent.from_dict({"visual_beats": []})

    def test_required_prompts_and_inputs_fail_before_inference(self):
        for kwargs in ({"system_prompts": {}},
                       {"lip_sync_mode": "unknown"}):
            with self.subTest(kwargs=kwargs), self.assertRaises(TimelinePlannerError):
                self.plan(**kwargs)

    def test_prompt_registry_has_only_current_tasks(self):
        self.assertEqual(set(_system_prompts()), {
            "scene-author-event", "scene-author-performance", "scene-author-camera",
            "scene-author-composition-choice",
        })

    def test_public_node_surface_is_retained(self):
        node = NODE_CLASS_MAPPINGS["MVDirectorTimelinePlanner"]
        self.assertEqual(node.RETURN_NAMES, ("emd_text", "emd", "status"))
        self.assertIn("scene_emd", node.INPUT_TYPES()["optional"])
        self.assertIn("staging_candidate_policy", node.INPUT_TYPES()["optional"])
        self.assertNotIn("scenes_per_batch", node.INPUT_TYPES()["required"])
        self.assertEqual(node.INPUT_TYPES()["required"]["n_ctx"][1]["default"], 24576)

    def test_progress_counts_current_stages_only(self):
        backend = _LlamaPlannerBackend(None)
        with patch("nodes.node_timeline_planner.node.configure_node_progress") as progress:
            backend.configure_progress(4)
            progress.assert_called_once_with(13)
            backend.configure_progress(4, scene_author_counts={
                "scene-author-event": 1, "scene-author-performance": 2,
                "scene-author-camera": 3, "scene-author-composition-choice": 1,
            })
            self.assertEqual(progress.call_args.args, (8,))

    def test_backend_rejects_retired_tasks(self):
        backend = _LlamaPlannerBackend(None)
        with self.assertRaisesRegex(ValueError, "unsupported Planner task"):
            backend.complete_planner(task="action-audit", system_prompt="x",
                                     payload="{}", config=_runtime())

    def test_call_seed_remains_reproducible_and_distinct(self):
        seed = _LlamaPlannerBackend._call_seed
        self.assertEqual(seed(1, "scene-author-camera", 1, "{}"),
                         seed(1, "scene-author-camera", 1, "{}"))
        self.assertNotEqual(seed(1, "scene-author-camera", 1, "{}"),
                            seed(1, "scene-author-camera", 2, "{}"))

    def test_backend_logs_current_stage_and_preserves_payload(self):
        class Lifecycle:
            effective_n_ctx = 24576
            def count_serialized_prompt(self, text):
                return TokenCount(100, False)
            def complete_chat(self, messages, config, **kwargs):
                self.messages, self.config, self.kwargs = messages, config, kwargs
                return "CAMERA\t1\tArc Shot."
        lifecycle = Lifecycle()
        backend = _LlamaPlannerBackend(lifecycle)
        payload = json.dumps({"slots": [{"slot": 1, "scene_number": 1}]})
        with self.assertLogs("mv_director.nodes", level="INFO") as logs:
            backend.complete_planner(task="scene-author-camera", system_prompt="x",
                                     payload=payload, config=LlamaRuntimeConfig(max_tokens=4096))
        self.assertEqual(lifecycle.messages[1]["content"], "/no_think\n" + payload)
        self.assertEqual(lifecycle.config.max_tokens, 1024)
        self.assertIn("grammar", lifecycle.kwargs)
        self.assertIn("inference completed", "\n".join(logs.output))
