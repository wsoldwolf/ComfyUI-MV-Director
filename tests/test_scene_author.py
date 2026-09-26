"""CPU contract tests for user-owned and generated Scene authoring."""

import json
from pathlib import Path
import unittest

from core.artifacts import DirectionArtifact
from core.direction.enhancer import DirectionEnhancerInput, enhance_direction
from core.emd import parse_emd
from core.inference import LlamaRuntimeConfig
from core.planner import PlannerContent, plan_timeline
from core.planner.scene_author import build_scene_author_grammar, _split_terminal_state
from nodes.node_timeline_planner.node import _system_prompts


from scene_author_fixtures import Backend, CONCEPT, TEMPLATE, _runtime


class SceneAuthorTests(unittest.TestCase):
    def test_arc_roll_policy_reaches_camera_only_and_preserves_fixed_fields(self):
        for profile, expected in (("anime_emotional_mv", "selective_arc"),
                                  ("anime_story_mv", "off")):
            with self.subTest(profile=profile):
                backend = Backend()
                result = plan_timeline(
                    backend, template_emd=TEMPLATE, concept_emd=CONCEPT,
                    direction=DirectionArtifact(motion_profile_id="anime_scene_author_mv",
                                                camera_profile_id=profile),
                    lip_sync_mode="off", lip_sync_target="サブジェクト1",
                    lip_sync_audio_slot=1,
                    system_prompts=_system_prompts(), runtime_config=_runtime(),
                )
                self.assertTrue(result.complete)
                for task, payload in backend.calls:
                    if task == "scene-author-camera":
                        self.assertEqual(payload["arc_roll_policy"], expected)
                        self.assertEqual(payload["fixed_cameras"], {"1": "目と口が見える正面。"})
                    else:
                        self.assertNotIn("arc_roll_policy", payload)
                self.assertIn("`カメラ` 目と口が見える正面。", result.emd.text)
        prompt = _system_prompts()["scene-author-camera"]
        self.assertIn("Roll Clockwise", prompt)
        self.assertIn("Roll Counterclockwise", prompt)
        self.assertIn("Tiltではなく", prompt)
        self.assertIn("水平への復帰", prompt)

    def test_matched_candidate_policy_is_advisory_and_preserves_author_fields(self):
        backend = Backend()
        result = plan_timeline(
            backend, template_emd=TEMPLATE, concept_emd=CONCEPT,
            direction=DirectionArtifact(
                motion_profile_id="anime_scene_author_mv",
                staging_candidates=("花の場面で花びらが舞う。",),
            ),
            lip_sync_mode="off", lip_sync_target="サブジェクト1",
            lip_sync_audio_slot=1,
            system_prompts=_system_prompts(), runtime_config=_runtime(),
            staging_candidate_policy="prefer_matched",
        )
        self.assertTrue(result.complete)
        self.assertEqual(len(backend.calls), 3)
        for _, request in backend.calls:
            self.assertEqual(request["staging_candidate_policy"], "prefer_matched")
        self.assertEqual(backend.calls[0][1]["fixed_events"], {"1": "木の根元に苔がある。"})
        self.assertIn("`演出` 木の根元に苔がある。", result.emd.text)
        # The mocked LLM chooses no Event for Shot 2; preference must not
        # trigger semantic retries, inject a flower, or reject the result.
        self.assertNotIn("花びらが舞う", result.emd.text)
        self.assertIn("prefer_matched", _system_prompts()["scene-author-event"])

    def test_candidate_policy_default_and_invalid_value(self):
        from core.planner.candidate_policy import validate_staging_candidate_policy
        from nodes.node_timeline_planner.node import MVDirectorTimelinePlanner
        option = MVDirectorTimelinePlanner.INPUT_TYPES()["optional"]["staging_candidate_policy"]
        self.assertEqual(option[1]["default"], "optional")
        validate_staging_candidate_policy("optional")
        validate_staging_candidate_policy("prefer_matched")
        with self.assertRaises(ValueError):
            validate_staging_candidate_policy("force_all")

    def test_scene_author_grammar_binds_requested_slots(self):
        event = build_scene_author_grammar(
            "scene-author-event",
            [{"slot": 1, "shot": 1}, {"slot": 2, "shot": 2}],
        )
        performance = build_scene_author_grammar(
            "scene-author-performance",
            [{"slot": 1}, {"slot": 2}],
        )
        self.assertIn("EVENT\\t1\\t", event)
        self.assertIn("EVENT\\t2\\t", event)
        self.assertNotIn("SHOT=", event)
        self.assertIn("PERFORMANCE\\t1\\t", performance)
        self.assertIn("PERFORMANCE\\t2\\t", performance)
        self.assertNotIn("PERFORMANCE\\t3\\t", performance)

    def test_terminal_state_transport_does_not_change_prose(self):
        self.assertEqual(
            _split_terminal_state("苔に触れる。｜END_STATE=手は幹から離れた。"),
            ("苔に触れる。", "手は幹から離れた。"),
        )
        self.assertEqual(_split_terminal_state("元の本文。"), ("元の本文。", ""))
        self.assertEqual(
            _split_terminal_state("元の本文。END_STATE=両足支持。"),
            ("元の本文。", "両足支持。"),
        )
        self.assertEqual(
            _split_terminal_state("Arc Shot. END_STATE=front left."),
            ("Arc Shot.", "front left."),
        )
        self.assertEqual(
            _split_terminal_state("Arc Shot\u3000END_STATE=正面。"),
            ("Arc Shot", "正面。"),
        )
        self.assertEqual(
            _split_terminal_state("腕を下げる。END_STATE\u3000両足支持。"),
            ("腕を下げる。", "両足支持。"),
        )
        self.assertEqual(_split_terminal_state("元の本文。｜END_STATE="),
                         ("元の本文。｜END_STATE=", ""))

    def test_profile_and_prompt_load(self):
        from core.direction.profile_loader import load_direction_profile
        path = Path(__file__).resolve().parents[1] / "profiles/motion/anime_scene_author_mv.md"
        self.assertEqual(load_direction_profile(path, "motion").kind, "motion")
        prompts = _system_prompts()
        self.assertTrue(all(prompts[f"scene-author-{kind}"] for kind in ("event", "performance", "camera")))
        self.assertIn("候補全体の対象・場所・変化", prompts["scene-author-event"])
        self.assertIn("同じSceneの到達可能な空間", prompts["scene-author-event"])
        self.assertIn("手の届く距離まで進んでから接触", prompts["scene-author-performance"])
        self.assertIn("そこから向かう人物の移動", prompts["scene-author-camera"])
        for stage in ("performance", "camera"):
            self.assertIn("accepted_events_by_shot", prompts[f"scene-author-{stage}"])
            self.assertNotIn("accepted_eventは", prompts[f"scene-author-{stage}"])

    def test_user_motion_prose_overrides_profile_text_but_keeps_planner_mode(self):
        class NoModel:
            def complete_direction(self, **_kwargs):
                raise AssertionError("all direction prose is author-owned")

        result = enhance_direction(
            NoModel(),
            value=DirectionEnhancerInput(
                user_request=(
                    "# 共通プロンプト\n"
                    "## スタイル\n* 作者の画風。\n"
                    "## モーション\n* 作者の振付。\n"
                    "## カメラ\n* 作者の撮影。\n"
                ),
                motion_profile="anime_scene_author_mv",
                retention_policy="compiler_default",
            ),
            system_prompt="",
            runtime_config=_runtime(),
        )
        direction = result.direction
        self.assertEqual(direction.motion_profile_id, "passthrough")
        self.assertEqual(direction.motion_policy_profile_id, "anime_scene_author_mv")
        self.assertEqual(direction.motion_direction, ("作者の振付。",))
        self.assertEqual(
            DirectionArtifact.from_dict(direction.to_dict()).motion_policy_profile_id,
            "anime_scene_author_mv",
        )
        backend = Backend()
        planned = plan_timeline(
            backend, template_emd=TEMPLATE, concept_emd=CONCEPT,
            direction=direction, lip_sync_mode="off",
            lip_sync_target="サブジェクト1", lip_sync_audio_slot=1,
            system_prompts=_system_prompts(),
            runtime_config=_runtime(),
        )
        self.assertTrue(planned.complete)
        self.assertEqual([name for name, _ in backend.calls],
                         ["scene-author-event", "scene-author-performance",
                          "scene-author-camera"])
        self.assertIn("* 作者の振付。", planned.emd.text)

    def test_fixed_fields_win_and_only_missing_fields_are_generated(self):
        backend = Backend()
        result = plan_timeline(
            backend, template_emd=TEMPLATE, concept_emd=CONCEPT,
            direction=DirectionArtifact(
                motion_profile_id="anime_scene_author_mv",
                staging_candidates=("使わなくてもよい候補。",),
            ),
            lip_sync_mode="off", lip_sync_target="サブジェクト1",
            lip_sync_audio_slot=1,
            system_prompts=_system_prompts(), runtime_config=_runtime(),
        )
        self.assertTrue(result.complete)
        self.assertEqual([task for task, _ in backend.calls],
                         ["scene-author-event", "scene-author-performance",
                          "scene-author-camera"])
        self.assertEqual(backend.calls[0][1]["slots"][0]["position"]["shot"], 2)
        self.assertEqual(backend.calls[2][1]["accepted_performances"][str(1)],
                         "人物が片手を胸元に置く。")
        self.assertEqual(backend.calls[2][1]["accepted_performances"][str(2)],
                         "胸から腕へ動きを渡し、手を離す。")
        self.assertEqual(backend.calls[1][1]["accepted_events_by_shot"],
                         {"1": "木の根元に苔がある。", "2": "なし"})
        self.assertEqual(backend.calls[0][1]["staging_candidates_optional"], ["使わなくてもよい候補。"])
        self.assertNotIn("使わなくてもよい候補。", result.emd.text)
        self.assertEqual(result.content.events, ())
        self.assertTrue(result.content.typed_output)
        document = parse_emd(result.emd.text)
        first, second = document.scenes[0].shots
        self.assertEqual([item.kind for item in first.directives], ["演出", "演技", "カメラ"])
        self.assertEqual([item.kind for item in second.directives], ["演技", "カメラ"])
        self.assertIn("Arc Shotで腕と表情を追う。", result.emd.text)
        self.assertEqual(PlannerContent.from_dict(result.content.to_dict()), result.content)

    def test_all_authored_fields_skip_the_model(self):
        backend = Backend()
        source = TEMPLATE.replace("## ショット 00:00.500\n* 未計画",
            "## ショット 00:00.500\n* `演出` 花が揺れる。\n"
            "* `演技` 人物が視線を上げる。\n* `カメラ` 横から追う。")
        result = plan_timeline(
            backend, template_emd=source, concept_emd=CONCEPT,
            direction=DirectionArtifact(motion_profile_id="anime_scene_author_mv"),
            lip_sync_mode="off", lip_sync_target="サブジェクト1",
            lip_sync_audio_slot=1,
            system_prompts=_system_prompts(), runtime_config=_runtime(),
        )
        self.assertTrue(result.complete)
        self.assertEqual(backend.calls, [])
        self.assertIn("人物が視線を上げる。", result.emd.text)

    def test_singing_camera_receives_lyric_windows_without_extra_stage(self):
        source = (
            "> `シーン` 1\n# シーン 00:00.000 --> 00:01.000\n* `H3長` 22\n"
            "> `歌詞開始` 00:00.100\n> `歌詞終了` 00:00.900\n"
            "> `歌詞` それでも永遠を\n## ショット 00:00.000\n"
            "* `演出` なし\n* `演技` 胸元の片手を静かに開く。\n"
        )
        backend = Backend()
        prompts = _system_prompts()
        result = plan_timeline(
            backend, template_emd=source, concept_emd=CONCEPT,
            direction=DirectionArtifact(motion_profile_id="anime_scene_author_mv"),
            lip_sync_mode="context_loop", lip_sync_target="サブジェクト1",
            lip_sync_audio_slot=1,
            system_prompts=prompts, runtime_config=_runtime(),
        )
        self.assertTrue(result.complete)
        self.assertEqual([task for task, _ in backend.calls], ["scene-author-camera"])
        payload = backend.calls[0][1]
        lyric = payload["original_lyrics"][0]["lyrics"][0]
        self.assertEqual((lyric["start_ms"], lyric["end_ms"]), (100, 900))
        self.assertEqual(payload["accepted_performances"], {"1": "胸元の片手を静かに開く。"})
        self.assertIn("句境界", prompts["scene-author-camera"])
        self.assertIn("歌詞のない区間", prompts["scene-author-camera"])
        self.assertIn("作者固定Cameraを変更せず", prompts["scene-author-camera"])
        self.assertIn("その演技を保ち、歌唱口と近くの手・小物を同時に読める", prompts["scene-author-camera"])
        self.assertIn("一律の顔アップを要求しない", prompts["scene-author-camera"])

    def test_local_face_candidate_reaches_camera_without_overwriting_fixed_shot(self):
        candidate = "サビの短い有声句を、両眉・両目・鼻・口全体が見える顔いっぱいの接写で見せる。"
        backend = Backend()
        prompts = _system_prompts()
        result = plan_timeline(
            backend, template_emd=TEMPLATE, concept_emd=CONCEPT,
            direction=DirectionArtifact(
                motion_profile_id="anime_scene_author_mv",
                staging_candidates=(candidate,),
            ),
            lip_sync_mode="off", lip_sync_target="サブジェクト1",
            lip_sync_audio_slot=1,
            system_prompts=prompts, runtime_config=_runtime(),
        )
        self.assertTrue(result.complete)
        self.assertEqual(len(backend.calls), 3)
        camera = next(payload for task, payload in backend.calls
                      if task == "scene-author-camera")
        self.assertEqual(camera["staging_candidates_optional"], [candidate])
        self.assertEqual(camera["fixed_cameras"], {"1": "目と口が見える正面。"})
        self.assertEqual([slot["shot"] for slot in camera["slots"]], [2])
        self.assertIn("* `カメラ` 目と口が見える正面。", result.emd.text)
        self.assertIn("* `演技` 人物が片手を胸元に置く。", result.emd.text)
        self.assertNotIn(candidate, result.emd.text)
        self.assertIn("肩・手を画面に収めることを必須にせず", prompts["scene-author-camera"])
        self.assertIn("現在Sceneの歌詞・有声句と採用済み演技に合う撮影意図だけ", prompts["scene-author-camera"])
        self.assertIn("候補を全Sceneへ反復する共通命令にしない", prompts["scene-author-camera"])
        profile = Path("profiles/camera/anime_emotional_mv.md").read_text(encoding="utf-8")
        self.assertIn("顔が画面の大部分を占める接写", profile)
        self.assertIn("必要な身体と対象の可視範囲を保つ", profile)

    def test_section_context_reaches_model_without_changing_lyrics_or_timing(self):
        source = (
            "> `シーン` 1\n# シーン 00:00.000 --> 00:01.000\n* `H3長` 22\n"
            "> `セクション` VERSE\n> `歌詞開始` 00:00.000\n> `歌詞終了` 00:00.900\n"
            "> `歌詞` それでも永遠を\n## ショット 00:00.000\n* 未計画\n"
            "> `シーン` 2\n# シーン 00:01.000 --> 00:02.000\n* `H3長` 22\n"
            "> `セクション` VERSE\n> `歌詞開始` 00:01.000\n> `歌詞終了` 00:01.900\n"
            "> `歌詞` 口にする\n## ショット 00:01.000\n* 未計画\n"
        )
        backend = Backend()
        result = plan_timeline(
            backend, template_emd=source, concept_emd=CONCEPT,
            direction=DirectionArtifact(motion_profile_id="anime_scene_author_mv"),
            lip_sync_mode="off", lip_sync_target="サブジェクト1",
            lip_sync_audio_slot=1,
            system_prompts=_system_prompts(), runtime_config=_runtime(),
        )
        self.assertTrue(result.complete)
        for _, payload in backend.calls:
            self.assertEqual([line["text"] for line in payload["section_lyric_context"][0]["lines"]],
                             ["それでも永遠を", "口にする"])
        before = parse_emd(CONCEPT + source)
        after = parse_emd(result.emd.text)
        for original, generated in zip(before.scenes, after.scenes):
            self.assertEqual((original.start_ms, original.end_ms), (generated.start_ms, generated.end_ms))
            self.assertEqual([(x.text, x.start_ms, x.end_ms) for x in original.shots[0].lyric_annotations],
                             [(x.text, x.start_ms, x.end_ms) for x in generated.shots[0].lyric_annotations])

    def test_optional_candidates_reach_all_three_authors_without_global_injection(self):
        backend = Backend()
        template = TEMPLATE.replace(
            "* `演出` 木の根元に苔がある。\n"
            "* `演技` 人物が片手を胸元に置く。\n"
            "* `カメラ` 目と口が見える正面。\n",
            "* 未計画\n",
        )
        result = plan_timeline(
            backend, template_emd=template, concept_emd=CONCEPT,
            direction=DirectionArtifact(
                motion_profile_id="anime_scene_author_mv",
                staging_candidates=("任意の候補。",),
                environment_direction=("広い舞台。",),
                time_lighting_direction=("夜。",),
            ),
            lip_sync_mode="off", lip_sync_target="サブジェクト1",
            lip_sync_audio_slot=1,
            system_prompts=_system_prompts(), runtime_config=_runtime(),
        )
        self.assertTrue(result.complete)
        self.assertEqual(backend.calls[0][0], "scene-author-event")
        self.assertEqual(backend.calls[0][1]["staging_candidates_optional"], ["任意の候補。"])
        self.assertEqual(backend.calls[0][1]["staging_candidate_policy"], "optional")
        self.assertEqual(backend.calls[1][1]["staging_candidates_optional"], ["任意の候補。"])
        self.assertEqual(backend.calls[2][1]["staging_candidates_optional"], ["任意の候補。"])
        self.assertNotIn("任意の候補。", result.emd.text)
        for _, payload in backend.calls:
            self.assertEqual(payload["scene_environment"], ["広い舞台。"])
            self.assertEqual(payload["scene_time_lighting"], ["夜。"])
            self.assertIn("section_lyric_context", payload)
        self.assertIn("`演出` 歌詞に応じて花が揺れる。", result.emd.text)

    def test_event_begins_at_llm_chosen_shot(self):
        class LaterEvent(Backend):
            def complete_planner(self, *, task, payload, **kwargs):
                if task == "scene-author-event":
                    request = json.loads(payload)
                    self.calls.append((task, request))
                    return "EVENT\t1\t狐火が現れる。"
                return super().complete_planner(
                    task=task, payload=payload, **kwargs,
                )

        backend = LaterEvent()
        template = TEMPLATE.replace("* `演出` 木の根元に苔がある。\n", "")
        result = plan_timeline(
            backend, template_emd=template, concept_emd=CONCEPT,
            direction=DirectionArtifact(motion_profile_id="anime_scene_author_mv"),
            lip_sync_mode="off", lip_sync_target="サブジェクト1",
            lip_sync_audio_slot=1,
            system_prompts=_system_prompts(), runtime_config=_runtime(),
        )
        self.assertTrue(result.complete)
        self.assertEqual(result.content.events, ((1, 2, "狐火が現れる。"),))
        self.assertNotIn("`演出`", result.emd.text.split("## ショット 00:00.500")[0])
        self.assertIn("`演出` 狐火が現れる。", result.emd.text.split("## ショット 00:00.500")[1])

    def test_two_lyric_events_survive_one_scene_call(self):
        class TwoEvents(Backend):
            def complete_planner(self, *, task, payload, **kwargs):
                if task == "scene-author-event":
                    request = json.loads(payload)
                    self.calls.append((task, request))
                    return (
                        "EVENT\t1\t石段に紅葉が積もる。｜END_STATE=紅葉は石段にある。\n"
                        "EVENT\t2\t大樹の根元の苔が見える。"
                        "｜END_STATE=苔は大樹の根元にある。"
                    )
                return super().complete_planner(
                    task=task, payload=payload, **kwargs,
                )

        template = TEMPLATE.replace(
            "* `演出` 木の根元に苔がある。\n"
            "* `演技` 人物が片手を胸元に置く。\n"
            "* `カメラ` 目と口が見える正面。\n",
            "* 未計画\n",
        )
        backend = TwoEvents()
        result = plan_timeline(
            backend, template_emd=template, concept_emd=CONCEPT,
            direction=DirectionArtifact(motion_profile_id="anime_scene_author_mv"),
            lip_sync_mode="off", lip_sync_target="サブジェクト1",
            lip_sync_audio_slot=1,
            system_prompts=_system_prompts(), runtime_config=_runtime(),
        )
        self.assertTrue(result.complete)
        self.assertEqual(
            result.content.events,
            ((1, 1, "石段に紅葉が積もる。"),
             (1, 2, "大樹の根元の苔が見える。")),
        )
        self.assertEqual(
            [task for task, _ in backend.calls].count("scene-author-event"), 1,
        )
        for _, payload in backend.calls[1:]:
            self.assertEqual(
                payload["accepted_events_by_shot"],
                {"1": "石段に紅葉が積もる。", "2": "大樹の根元の苔が見える。"},
            )
        self.assertEqual(
            result.content.terminal_states[0][1],
            "苔は大樹の根元にある。",
        )
        self.assertIn("`演出` 大樹の根元の苔が見える。", result.emd.text)

    def test_fixed_event_owns_only_its_shot(self):
        class MissingShotEvent(Backend):
            def complete_planner(self, *, task, payload, **kwargs):
                if task == "scene-author-event":
                    request = json.loads(payload)
                    self.calls.append((task, request))
                    self_request = request["slots"][0]
                    assert self_request["shot"] == 2
                    return "EVENT\t1\t大樹の根元に苔が現れる。"
                return super().complete_planner(
                    task=task, payload=payload, **kwargs,
                )

        backend = MissingShotEvent()
        result = plan_timeline(
            backend, template_emd=TEMPLATE, concept_emd=CONCEPT,
            direction=DirectionArtifact(motion_profile_id="anime_scene_author_mv"),
            lip_sync_mode="off", lip_sync_target="サブジェクト1",
            lip_sync_audio_slot=1,
            system_prompts=_system_prompts(), runtime_config=_runtime(),
        )
        self.assertTrue(result.complete)
        self.assertEqual(
            result.content.events,
            ((1, 2, "大樹の根元に苔が現れる。"),),
        )
        shots = parse_emd(result.emd.text).scenes[0].shots
        self.assertEqual(
            [item.text for item in shots[0].directives if item.kind == "演出"],
            ["木の根元に苔がある。"],
        )
        self.assertEqual(
            [item.text for item in shots[1].directives if item.kind == "演出"],
            ["大樹の根元に苔が現れる。"],
        )

    def test_continuation_receives_only_role_specific_terminal_state(self):
        from planner_fixtures import TEMPLATE as LONG_TEMPLATE
        from planner_fixtures import INSTRUMENTAL_TAIL

        backend = Backend()
        result = plan_timeline(
            backend, template_emd=LONG_TEMPLATE + INSTRUMENTAL_TAIL,
            concept_emd=CONCEPT,
            direction=DirectionArtifact(motion_profile_id="anime_scene_author_mv"),
            lip_sync_mode="off", lip_sync_target="サブジェクト1",
            lip_sync_audio_slot=1,
            system_prompts=_system_prompts(), runtime_config=_runtime(),
        )
        self.assertTrue(result.complete)
        second = [
            payload for _, payload in backend.calls
            if payload["scene_number"] == 2
        ]
        self.assertTrue(second)
        self.assertNotIn("previous_accepted_terminal", second[0])
        for task, payload in backend.calls:
            if payload["scene_number"] != 2:
                continue
            expected = {
                "scene-author-event": "花は風に揺れている。",
                "scene-author-performance": "両足支持、右腕は低く、視線は前。",
                "scene-author-camera": "正面寄り、右回りのArc終点。",
            }[task]
            self.assertEqual(payload["previous_scene_state"], expected)
        self.assertNotIn("END_STATE", result.emd.text)
        self.assertTrue(result.content.terminal_states)
        self.assertTrue(parse_emd(result.emd.text).scenes[1].continuation)

    def test_missing_terminal_state_does_not_restore_prior_prose(self):
        from planner_fixtures import TEMPLATE as LONG_TEMPLATE
        from planner_fixtures import INSTRUMENTAL_TAIL

        class BareBackend(Backend):
            def complete_planner(self, **kwargs):
                return super().complete_planner(**kwargs).replace(
                    "｜END_STATE=花は風に揺れている。", ""
                ).replace(
                    "｜END_STATE=両足支持、右腕は低く、視線は前。", ""
                ).replace(
                    "｜END_STATE=正面寄り、右回りのArc終点。", ""
                )

        backend = BareBackend()
        result = plan_timeline(
            backend, template_emd=LONG_TEMPLATE + INSTRUMENTAL_TAIL,
            concept_emd=CONCEPT,
            direction=DirectionArtifact(motion_profile_id="anime_scene_author_mv"),
            lip_sync_mode="off", lip_sync_target="サブジェクト1",
            lip_sync_audio_slot=1,
            system_prompts=_system_prompts(), runtime_config=_runtime(),
        )
        self.assertTrue(result.complete)
        second = [payload for _, payload in backend.calls if payload["scene_number"] == 2]
        self.assertTrue(second)
        self.assertTrue(all(payload["previous_scene_state"] == "" for payload in second))
        self.assertEqual(result.content.terminal_states[0][1:], ("", "", ""))

    def test_full_author_emd_bypasses_model_selection(self):
        from unittest.mock import patch
        from nodes.node_timeline_planner.node import MVDirectorTimelinePlanner

        source = CONCEPT + TEMPLATE.replace(
            "## ショット 00:00.500\n* 未計画",
            "## ショット 00:00.500\n* `演出` 花が揺れる。\n"
            "* `演技` 人物が視線を上げる。\n* `カメラ` 横から追う。",
        )
        with patch(
            "nodes.node_timeline_planner.node.resolve_comfy_gguf_model",
            side_effect=AssertionError("model must not be resolved"),
        ):
            text, artifact, status = MVDirectorTimelinePlanner().plan(
                template_emd=source, lip_sync_mode="off",
                lip_sync_target="サブジェクト1", lip_sync_audio_slot=1,
                model_name="unused", chat_format="auto", max_tokens=512,
                temperature=0.1, top_p=0.9, repetition_penalty=1.05,
                gpu_layers=-1, n_batch=256, n_ctx=8192, flash_attn=True,
                kv_cache_type="q8_0", op_offload=True,
                keep_model_loaded=False, seed=1,
                cache_mode="disabled",
            )
        self.assertEqual(text, artifact.text)
        self.assertIn("source=author_emd", status)
        self.assertEqual(parse_emd(text).scenes[0].shots[1].directives[0].kind, "演出")

    def test_all_authored_template_with_separate_concept_skips_model(self):
        from unittest.mock import patch
        from nodes.node_timeline_planner.node import MVDirectorTimelinePlanner

        template = TEMPLATE.replace(
            "## ショット 00:00.500\n* 未計画",
            "## ショット 00:00.500\n* `演出` 花が揺れる。\n"
            "* `演技` 人物が視線を上げる。\n* `カメラ` 横から追う。",
        )
        with patch(
            "nodes.node_timeline_planner.node.resolve_comfy_gguf_model",
            side_effect=AssertionError("all authored fields need no model"),
        ):
            text, artifact, status = MVDirectorTimelinePlanner().plan(
                template_emd=template, concept_emd=CONCEPT,
                direction=DirectionArtifact(motion_profile_id="anime_scene_author_mv"),
                lip_sync_mode="off", lip_sync_target="サブジェクト1",
                lip_sync_audio_slot=1, model_name="unused",
                chat_format="auto", max_tokens=512, temperature=0.1,
                top_p=0.9, repetition_penalty=1.05, gpu_layers=-1,
                n_batch=256, n_ctx=8192, flash_attn=True,
                kv_cache_type="q8_0", op_offload=True,
                keep_model_loaded=False, seed=1,
                cache_mode="disabled",
            )
        self.assertEqual(text, artifact.text)
        self.assertIn("source=author_shots", status)


if __name__ == "__main__":
    unittest.main()
