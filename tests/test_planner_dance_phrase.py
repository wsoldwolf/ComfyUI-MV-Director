"""P0 transport/safety regressions; fake outputs are not creative-quality evidence."""

import json
import tempfile
from pathlib import Path
import unittest
from unittest.mock import patch

from core.artifacts import DirectionArtifact
from core.direction.profile_loader import DirectionProfileError, load_direction_profile
from core.direction.profiles import (
    MOTION_BODY_ACCENT_POLICIES,
    MOTION_PERFORMANCE_MODES,
    planner_profile_metadata,
)
from core.inference import build_cache_key
from core.planner import parse_template_emd, plan_timeline
from core.planner.layout import build_layout_candidates
from core.planner.engine import (
    _CameraPlan, _CueCard, _Entity, _action_audit_failures,
    _action_budget_violations, _camera_plan_contract_violations,
    _fallback_camera_plan, _sparse_body_accent_keys,
    _is_prechorus_scene, _layout_min_duration_ms,
)
from core.planner.scene_spine import SceneSpineStep
from test_timeline_planner import CONCEPT, TEMPLATE, FakePlannerBackend, prompts, runtime


class DancePhraseTests(unittest.TestCase):
    def test_emotional_motion_profile_and_action_prompt_allow_scene_level_full_body_phrase(self):
        root = Path(__file__).resolve().parents[1]
        profile = load_direction_profile(root / "profiles/motion/anime_emotional_mv.md", "motion")
        action_prompt = (root / "prompts/timeline_planner_actions_dance_phrase_system_prompt.txt").read_text(encoding="utf-8")
        self.assertEqual(profile.performance_mode, "dance_phrase")
        self.assertEqual(profile.body_accent_policy, "sparse_chorus_prechorus_verse_contact")
        self.assertIn("連続した全身フレーズ", profile.render_prompt)
        self.assertIn("少なくとも一つの通常Shotに踏み替え", action_prompt)
        self.assertNotIn("上半身だけで完結する演技を積極的に選び", action_prompt)

    def test_song_direction_has_bounded_concise_output_budget(self):
        seen = []
        class Capture(FakePlannerBackend):
            def complete_planner(self, *, task, config, **kwargs):
                if task == "song-direction":
                    seen.append(config.max_tokens)
                return super().complete_planner(task=task, config=config, **kwargs)
        result = plan_timeline(Capture(), template_emd=TEMPLATE, concept_emd=CONCEPT,
            direction=DirectionArtifact(camera_profile_id="anime_emotional_mv"),
            lip_sync_mode="off", lip_sync_target="サブジェクト1", lip_sync_audio_slot=1,
            scenes_per_batch=3, system_prompts=prompts(), runtime_config=runtime())
        self.assertTrue(result.complete)
        self.assertEqual(seen, [min(runtime().max_tokens, 512)])

    def test_compact_action_prompt_is_selected_only_by_motion_opt_in(self):
        from nodes.node_timeline_planner.node import _system_prompts
        loaded = _system_prompts()
        # This test isolates Motion prompt routing; Scene-spine integration has
        # a dedicated test with a backend that implements the new task.
        loaded.pop("scene-spine")
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
            expected = "actions-dance-phrase" if motion in {"anime_story_mv", "anime_emotional_mv"} else "actions"
            self.assertTrue(seen)
            self.assertTrue(all(value == loaded[expected] for value in seen))

    def test_motion_metadata_is_optional_strict_and_kind_scoped(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "custom.md"
            body = "# 共通プロンプト\n## モーション\n* 全身で演じる。\n"
            path.write_text(body, encoding="utf-8")
            self.assertEqual(load_direction_profile(path, "motion").performance_mode, "event_based")
            self.assertEqual(load_direction_profile(path, "motion").body_accent_policy, "off")
            for mode in ("event_based", "dance_phrase"):
                path.write_text("# プロファイル\n* `performance_mode` " + mode + "\n" + body, encoding="utf-8")
                self.assertEqual(load_direction_profile(path, "motion").performance_mode, mode)
            for mode in ("dance", "Dance_phrase", "dance_phrase extra"):
                path.write_text("# プロファイル\n* `performance_mode` " + mode + "\n" + body, encoding="utf-8")
                with self.assertRaisesRegex(DirectionProfileError, "performance_mode"):
                    load_direction_profile(path, "motion")
            path.write_text(
                "# プロファイル\n* `performance_mode` dance_phrase\n"
                "* `body_accent_policy` sparse_chorus\n" + body,
                encoding="utf-8",
            )
            self.assertEqual(load_direction_profile(path, "motion").body_accent_policy, "sparse_chorus")
            path.write_text(
                "# プロファイル\n* `performance_mode` dance_phrase\n"
                "* `body_accent_policy` sparse_chorus_prechorus\n" + body,
                encoding="utf-8",
            )
            self.assertEqual(
                load_direction_profile(path, "motion").body_accent_policy,
                "sparse_chorus_prechorus",
            )
            for header in (
                "* `body_accent_policy` every_shot\n",
                "* `performance_mode` event_based\n* `body_accent_policy` sparse_chorus\n",
            ):
                path.write_text("# プロファイル\n" + header + body, encoding="utf-8")
                with self.assertRaisesRegex(DirectionProfileError, "body_accent_policy"):
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
        self.assertEqual(len(set(keys)), len(keys))
        self.assertEqual(planner_profile_metadata("anime_emotional_mv")["performance_mode"], "event_based")

        keys = []
        for policy in (
            "off", "sparse_chorus", "sparse_chorus_prechorus",
            "sparse_chorus_prechorus_verse_contact",
        ):
            with patch.dict(MOTION_BODY_ACCENT_POLICIES, {"custom": policy}):
                keys.append(build_cache_key(task="timeline-planner", algorithm_version="test",
                    inputs={"planner_profile": planner_profile_metadata("anime_emotional_mv", "custom")}))
        self.assertEqual(len(set(keys)), len(keys))

    def test_emotional_development_policy_preserves_story_baseline(self):
        self.assertEqual(MOTION_BODY_ACCENT_POLICIES["anime_story_mv"], "off")
        self.assertEqual(MOTION_BODY_ACCENT_POLICIES["anime_emotional_mv"], "sparse_chorus_prechorus_verse_contact")
        for motion, first_role in (
            ("anime_story_mv", "continuous_upper_body_phrase"),
            ("anime_emotional_mv", "body_phrase_accent"),
        ):
            backend = FakePlannerBackend()
            result = plan_timeline(
                backend, template_emd=TEMPLATE.replace("VERSE1", "CHORUS"), concept_emd=CONCEPT,
                direction=DirectionArtifact(camera_profile_id="anime_emotional_mv", motion_profile_id=motion),
                lip_sync_mode="off", lip_sync_target="サブジェクト1", lip_sync_audio_slot=1,
                scenes_per_batch=3, system_prompts=prompts(), runtime_config=runtime(),
            )
            self.assertTrue(result.complete)
            payload = next(payload for task, payload in backend.calls if task == "actions")
            self.assertEqual(payload["slots"][0]["performance_role"], first_role)
            self.assertEqual(
                sum(slot["performance_role"] == "body_phrase_accent" for slot in payload["slots"]),
                int(motion == "anime_emotional_mv"),
            )
            self.assertEqual(
                payload["planner_policy_contract"]["body_accent_policy"],
                MOTION_BODY_ACCENT_POLICIES[motion],
            )

    def test_verse_contact_gets_one_non_event_body_accent_only(self):
        context = {
            (3, index): {
                "lyrics": [{"section": "VERSE", "text": "苔へと還る"}],
                "shot_index": index, "scene_shot_count": 2,
                "scene_continuation": True, "shot_duration_ms": 4500,
            }
            for index in (1, 2)
        }
        setup = SceneSpineStep(
            "setup", "石畳に立つ", "重心から体幹と両腕へ動きを伝える",
            "大樹の前で姿勢を収める", "whole_body",
        )
        event = SceneSpineStep(
            "event", "大樹の前に立つ", "苔に一度触れる",
            "指を離す", "lyric_target_hands",
        )
        contact = {(3,): _CueCard(valid=True, target="苔", contact="許可")}
        kwargs = dict(lip_sync_active=True, cue_cards=contact, include_verse_contact=True)
        self.assertEqual(
            _sparse_body_accent_keys(
                context, {(3, 1): setup, (3, 2): event}, **kwargs,
            ),
            {(3, 1)},
        )
        self.assertEqual(
            _sparse_body_accent_keys(
                context, {(3, 1): event, (3, 2): setup}, **kwargs,
            ),
            {(3, 2)},
        )
        self.assertEqual(
            _sparse_body_accent_keys(context, {(3, 1): setup}, **kwargs), set()
        )
        self.assertEqual(
            _sparse_body_accent_keys(
                context, {(3, 1): setup, (3, 2): event},
                lip_sync_active=True, cue_cards=contact,
            ),
            set(),
        )
        no_contact = {(3,): _CueCard(valid=True, target="苔", contact="禁止")}
        self.assertEqual(
            _sparse_body_accent_keys(
                context, {(3, 1): setup, (3, 2): event},
                lip_sync_active=True, cue_cards=no_contact,
                include_verse_contact=True,
            ),
            set(),
        )

    def test_only_verse_contact_shortens_dance_layout_candidates(self):
        scene = parse_template_emd(
            TEMPLATE.replace("## ショット 00:05.000\n* 未計画\n", "")
        ).scenes[0]
        policy = "sparse_chorus_prechorus_verse_contact"
        contact = _CueCard(valid=True, target="苔", contact="許可")
        base = _layout_min_duration_ms(
            scene, performance_mode="dance_phrase",
            body_accent_policy=policy, cue_card=None,
        )
        short = _layout_min_duration_ms(
            scene, performance_mode="dance_phrase",
            body_accent_policy=policy, cue_card=contact,
        )
        self.assertEqual((base, short), (4000, 3000))
        self.assertGreater(
            len(build_layout_candidates(scene, min_duration_ms=short)),
            len(build_layout_candidates(scene, min_duration_ms=base)),
        )
        self.assertEqual(
            _layout_min_duration_ms(
                scene, performance_mode="event_based",
                body_accent_policy=policy, cue_card=contact,
            ),
            1500,
        )
    def test_body_accent_audit_code_is_finite_and_nonblocking(self):
        entity = _Entity(1, (1, 1), {"performance_role": "body_phrase_accent"})
        self.assertEqual(
            _action_audit_failures([entity], {entity.key: "REJECT:BODY_ACCENT_MISSING"}),
            {entity.key: ("BODY_ACCENT_MISSING",)},
        )
        ordinary = _Entity(1, (1, 2), {"performance_role": "expressive_hand_arm_performance"})
        self.assertEqual(
            _action_audit_failures(
                [ordinary], {ordinary.key: "REJECT:BODY_ACCENT_MISSING"}
            ),
            {},
        )

    def test_long_single_prechorus_accent_is_selective(self):
        key = (6, 1)
        context = {
            key: {
                "lyrics": [{"section": "PRE-CHORUS", "text": "御神木は"}],
                "shot_index": 1, "scene_shot_count": 1,
                "scene_continuation": True, "shot_duration_ms": 7792,
            }
        }
        kwargs = {"lip_sync_active": True, "include_prechorus_single": True}
        self.assertEqual(_sparse_body_accent_keys(context, {}, **kwargs), {key})
        self.assertEqual(
            _sparse_body_accent_keys(context, {}, lip_sync_active=True), set()
        )
        short = {key: {**context[key], "shot_duration_ms": 5999}}
        self.assertEqual(_sparse_body_accent_keys(short, {}, **kwargs), set())
        contact = {(6,): _CueCard(valid=True, target="御神木", contact="許可")}
        self.assertEqual(
            _sparse_body_accent_keys(context, {}, cue_cards=contact, **kwargs), set()
        )
        contact_spine = {
            key: SceneSpineStep(
                "event", "人物は道に立つ", "御神木に触れる",
                "手を離す", "lyric_target_hands",
            ),
        }
        self.assertEqual(
            _sparse_body_accent_keys(
                context, contact_spine, cue_cards=contact, **kwargs
            ),
            {key},
        )
        face = {key: {**context[key], "scene_continuation": False,
                      "section_entry": True}}
        self.assertEqual(_sparse_body_accent_keys(face, {}, **kwargs), set())
        two_shots = {
            **context,
            (6, 2): {**context[key], "shot_index": 2, "scene_shot_count": 2,
                     "shot_duration_ms": 4500},
        }
        two_shots[key] = {**context[key], "scene_shot_count": 2,
                          "shot_duration_ms": 3500}
        self.assertEqual(_sparse_body_accent_keys(two_shots, {}, **kwargs), set())
        self.assertEqual(
            _sparse_body_accent_keys(two_shots, {}, cue_cards=contact, **kwargs),
            set(),
        )
        self.assertEqual(
            _sparse_body_accent_keys(
                two_shots, contact_spine, cue_cards=contact, **kwargs
            ),
            set(),
        )
        two_shots[(6, 2)]["shot_duration_ms"] = 2999
        self.assertEqual(_sparse_body_accent_keys(two_shots, {}, **kwargs), set())
        two_shots[key]["shot_duration_ms"] = 2999
        self.assertEqual(_sparse_body_accent_keys(two_shots, {}, **kwargs), set())

    def test_single_prechorus_role_reaches_action_without_rewriting(self):
        template = """> `シーン` 1
# シーン 00:00.000 --> 00:07.792
* `H3長` 209
> `セクション` PRE-CHORUS
> `歌詞開始` 00:05.700
> `歌詞終了` 00:07.300
> `歌詞` 御神木は
## ショット 00:00.000
* 未計画
"""
        backend = FakePlannerBackend()
        result = plan_timeline(
            backend, template_emd=template, concept_emd=CONCEPT,
            direction=DirectionArtifact(
                motion_profile_id="anime_emotional_mv",
                camera_profile_id="anime_emotional_mv",
            ),
            lip_sync_mode="off", lip_sync_target="サブジェクト1",
            lip_sync_audio_slot=1, scenes_per_batch=1,
            system_prompts=prompts(), runtime_config=runtime(),
        )
        self.assertTrue(result.complete)
        action_request = next(payload for task, payload in backend.calls if task == "actions")
        self.assertEqual(action_request["slots"][0]["performance_role"], "body_phrase_accent")
        self.assertEqual(action_request["slots"][0]["performance_phase"], "complete_phrase")
        self.assertGreaterEqual(action_request["slots"][0]["shot_duration_ms"], 6000)
        camera_request = next(payload for task, payload in backend.calls if task == "cameras")
        camera_slot = camera_request["slots"][0]
        self.assertTrue(camera_slot["single_prechorus_body_accent"])
        self.assertEqual(camera_slot["required_spine_coverage"], "whole_body_emotion")

    def test_prechorus_body_accent_camera_keeps_wide_phase(self):
        entity = _Entity(6, (6, 1), {
            "shot_duration_ms": 7792,
            "required_spine_coverage": "lyric_target_and_body",
            "single_prechorus_body_accent": True,
        })
        narrow = _CameraPlan(
            "Push In at fast speed", "medium", "medium", "front_three_quarter",
            "front_three_quarter", "push_in", "lyric_target_and_body",
        )
        self.assertIn(
            "prechorus_body_accent_not_visible",
            _camera_plan_contract_violations(entity, narrow),
        )
        fallback = _fallback_camera_plan(entity, 0)
        self.assertEqual(_camera_plan_contract_violations(entity, fallback), ())

    def test_split_prechorus_uses_scene_lyrics_when_later_shot_has_none(self):
        context = {
            (6, 1): {"lyrics": [{"section": "PRE-CHORUS", "text": "御神木は"}]},
            (6, 2): {"lyrics": []},
        }
        self.assertTrue(_is_prechorus_scene([(6, 1), (6, 2)], context))
        context[(6, 1)]["lyrics"] = [{"section": "VERSE", "text": "御神木は"}]
        self.assertFalse(_is_prechorus_scene([(6, 1), (6, 2)], context))

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
                    self.assertEqual(payload["planner_policy_contract"]["emotional_amplitude"],
                        "exaggerated_readable_full_body")
                    if motion:
                        self.assertEqual(payload["planner_policy_contract"]["whole_body_emotion_mode"],
                            "one_connected_full_body_expression_phrase")
                if task == "actions":
                    for slot in payload["slots"]:
                        self.assertEqual(slot["performance_mode"], expected)
                        self.assertIn("胸郭と肩の反転", str(slot))
                        self.assertIn("鳥居へ正対して静止", str(slot))
            camera_slots = [
                slot for task, payload in backend.calls if task == "cameras"
                for slot in payload["slots"]
            ]
            self.assertEqual(len(camera_slots), 2)
            self.assertEqual(
                camera_slots[0]["next_locked_action"],
                camera_slots[1]["locked_action"],
            )
            self.assertEqual(
                camera_slots[1]["previous_locked_action"],
                camera_slots[0]["locked_action"],
            )
            self.assertEqual(
                [slot["performance_phase"] for slot in camera_slots],
                ["prepare_and_accent", "release_and_reaction"]
                if motion else ["", ""],
            )
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
