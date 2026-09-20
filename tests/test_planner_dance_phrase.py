"""P0 transport/safety regressions; fake outputs are not creative-quality evidence."""

import tempfile
from pathlib import Path
import unittest
from unittest.mock import patch

from core.artifacts import DirectionArtifact
from core.direction.profile_loader import DirectionProfileError, load_direction_profile
from core.direction.profiles import MOTION_PERFORMANCE_MODES, planner_profile_metadata
from core.inference import build_cache_key
from core.planner import plan_timeline
from core.planner.engine import _Entity, _action_budget_violations
from test_timeline_planner import CONCEPT, TEMPLATE, FakePlannerBackend, prompts, runtime


class DancePhraseTests(unittest.TestCase):
    def test_compact_action_prompt_is_selected_only_by_motion_opt_in(self):
        from nodes.node_timeline_planner.node import _system_prompts
        loaded = _system_prompts()
        self.assertLess(len(loaded["actions-dance-phrase"]), len(loaded["actions"]))
        for motion in ("", "anime_story_mv", "anime_emotional_mv"):
            seen = []
            class Capture(FakePlannerBackend):
                def complete_planner(self, *, task, system_prompt, **kwargs):
                    if task == "actions":
                        seen.append(system_prompt)
                    return super().complete_planner(task=task, system_prompt=system_prompt, **kwargs)
            result = plan_timeline(Capture(), template_emd=TEMPLATE, concept_emd=CONCEPT,
                direction=DirectionArtifact(camera_profile_id="anime_emotional_mv", motion_profile_id=motion),
                lip_sync_mode="off", lip_sync_target="サブジェクト1", lip_sync_audio_slot=1,
                scenes_per_batch=3, system_prompts=loaded, runtime_config=runtime())
            self.assertTrue(result.complete)
            expected = "actions-dance-phrase" if motion == "anime_emotional_mv" else "actions"
            self.assertTrue(seen)
            self.assertTrue(all(value == loaded[expected] for value in seen))

    def test_motion_metadata_is_optional_strict_and_kind_scoped(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "custom.md"
            body = "# 共通プロンプト\n## モーション\n* 全身で演じる。\n"
            path.write_text(body, encoding="utf-8")
            self.assertEqual(load_direction_profile(path, "motion").performance_mode, "event_based")
            for mode in ("event_based", "dance_phrase"):
                path.write_text("# プロファイル\n* `performance_mode` " + mode + "\n" + body, encoding="utf-8")
                self.assertEqual(load_direction_profile(path, "motion").performance_mode, mode)
            for mode in ("dance", "Dance_phrase", "dance_phrase extra"):
                path.write_text("# プロファイル\n* `performance_mode` " + mode + "\n" + body, encoding="utf-8")
                with self.assertRaisesRegex(DirectionProfileError, "performance_mode"):
                    load_direction_profile(path, "motion")
            for kind, heading in (("camera", "カメラ"), ("style", "スタイル")):
                path.write_text("# プロファイル\n* `performance_mode` dance_phrase\n" + body.replace("モーション", heading), encoding="utf-8")
                with self.assertRaisesRegex(DirectionProfileError, "not supported by " + kind):
                    load_direction_profile(path, kind)

    def test_metadata_alone_invalidates_planner_cache(self):
        keys = []
        for mode in ("event_based", "dance_phrase"):
            with patch.dict(MOTION_PERFORMANCE_MODES, {"custom": mode}):
                keys.append(build_cache_key(task="timeline-planner", algorithm_version="test",
                    inputs={"planner_profile": planner_profile_metadata("anime_emotional_mv", "custom")}))
        self.assertNotEqual(*keys)
        self.assertEqual(planner_profile_metadata("anime_emotional_mv")["performance_mode"], "event_based")

    def test_opt_in_reaches_existing_stages_without_added_calls_or_text_rewrite(self):
        calls = {}
        actions = {}
        for motion, expected in (("", "event_based"), ("anime_emotional_mv", "dance_phrase")):
            backend = FakePlannerBackend()
            result = plan_timeline(backend, template_emd=TEMPLATE, concept_emd=CONCEPT,
                direction=DirectionArtifact(camera_profile_id="anime_emotional_mv", motion_profile_id=motion),
                lip_sync_mode="off", lip_sync_target="サブジェクト1", lip_sync_audio_slot=1,
                scenes_per_batch=3, system_prompts=prompts(), runtime_config=runtime())
            self.assertTrue(result.complete)
            calls[motion] = [task for task, _ in backend.calls]
            actions[motion] = result.content.actions
            for task, payload in backend.calls:
                if task in {"visual-beats", "actions", "action-audit"}:
                    self.assertEqual(payload["planner_policy_contract"]["performance_mode"], expected)
                if task == "actions":
                    for slot in payload["slots"]:
                        self.assertEqual(slot["performance_mode"], expected)
                        self.assertIn("胸郭と肩の反転", str(slot))
                        self.assertIn("鳥居へ正対して静止", str(slot))
        self.assertEqual(calls[""], calls["anime_emotional_mv"])
        self.assertEqual(actions[""], actions["anime_emotional_mv"])

    def test_dance_steps_do_not_disable_running_grounding_or_protocol_checks(self):
        text = "左足へ重心を移し、膝の反発から胸郭を起こして片腕を斜めへ伸ばす。"
        for mode in ("event_based", "dance_phrase"):
            entity = _Entity(1, (1, 1), {"performance_mode": mode, "lyrics": [{"text": "想いを届けたい"}]})
            issues = _action_budget_violations([entity], {entity.key: text})
            self.assertEqual("unrequested_lower_body_primary_action" in issues.get(entity.key, ()), mode == "event_based")
        entity = _Entity(1, (1, 1), {"performance_mode": "dance_phrase", "required_spatial_anchor": "大樹の根元の苔"})
        issues = _action_budget_violations([entity], {entity.key: "走り出す。"})[entity.key]
        self.assertIn("unrequested_running", issues)
        self.assertIn("missing_spatial_anchor", issues)


if __name__ == "__main__":
    unittest.main()
