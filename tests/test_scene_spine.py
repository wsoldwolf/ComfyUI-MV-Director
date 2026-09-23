from __future__ import annotations

import json
import unittest

from core.artifacts import DirectionArtifact
from core.planner import build_scene_spine_grammar, plan_timeline
from core.planner.engine import (
    _CameraPlan,
    _CueCard,
    _Entity,
    _camera_plan_contract_violations,
    _continuation_body_state,
    _continuation_effect_state,
    _fallback_camera_plan,
    _render_camera_plan,
    _sparse_body_accent_keys,
)
from core.planner.scene_spine import (
    parse_scene_spine_step,
    validate_contact_coverage,
    validate_scene_spine,
)
from test_timeline_planner import (
    CONCEPT, INSTRUMENTAL_TAIL, TEMPLATE, FakePlannerBackend, prompts, runtime,
)


class SceneSpineTests(unittest.TestCase):
    def test_continuation_uses_accepted_spine_end_before_cue_fallback(self) -> None:
        step = parse_scene_spine_step(
            "PHASE=response｜FROM=腕を伸ばす｜ADVANCE=腕を戻す"
            "｜TO=左手を胸に置いて立つ｜SHOW=upper_body_hands"
        )
        arguments = {
            "last_shot_by_scene": {1: 2},
            "cue_cards": {(1,): _CueCard(final_state="前のCue終端")},
            "scene_spine_steps": {(1, 2): step},
        }
        self.assertEqual(
            _continuation_body_state(1, continuation=True, **arguments),
            "左手を胸に置いて立つ",
        )
        self.assertEqual(
            _continuation_body_state(
                1, continuation=True, **{**arguments, "scene_spine_steps": {}}
            ),
            "前のCue終端",
        )
        self.assertEqual(
            _continuation_body_state(1, continuation=False, **arguments), ""
        )
        self.assertEqual(
            _continuation_body_state(None, continuation=True, **arguments), ""
        )

    def test_spine_protocol_and_scene_order(self) -> None:
        first = parse_scene_spine_step(
            "PHASE=event｜FROM=手を下ろす｜ADVANCE=指先で苔に一度触れる"
            "｜TO=指を離す｜SHOW=lyric_target_hands"
        )
        second = parse_scene_spine_step(
            "PHASE=response｜FROM=指を離す｜ADVANCE=顔に安堵が広がる"
            "｜TO=苔を見つめる｜SHOW=face_eyes_mouth"
        )
        validate_scene_spine((first, second))
        self.assertEqual(first.required_coverage, "lyric_target_and_hands")
        with self.assertRaisesRegex(ValueError, "exactly one event"):
            validate_scene_spine((first, first))
        repeated = parse_scene_spine_step(
            "PHASE=response｜FROM=指を離す｜ADVANCE=指先で苔に一度触れる"
            "｜TO=苔を見つめる｜SHOW=face_eyes_mouth"
        )
        with self.assertRaisesRegex(ValueError, "identical Shot advance"):
            validate_scene_spine((first, repeated))
        with self.assertRaisesRegex(ValueError, "five or six fields"):
            parse_scene_spine_step("PHASE=event｜FROM=立つ")
        validate_contact_coverage((first, second), contact_allowed=True)
        premature = parse_scene_spine_step(
            "PHASE=setup｜FROM=離れて立つ｜ADVANCE=苔へ近づく"
            "｜TO=苔の前で止まる｜SHOW=lyric_target_hands"
        )
        with self.assertRaisesRegex(ValueError, "only in its event"):
            validate_contact_coverage((premature, first), contact_allowed=True)
        with self.assertRaisesRegex(ValueError, "non-contact"):
            validate_contact_coverage((first, second), contact_allowed=False)
        grammar = build_scene_spine_grammar([1, 2])
        self.assertIn('"SPINE\\t1\\tPHASE=event"', grammar)
        self.assertIn('"SPINE\\t1\\tPHASE=setup"', grammar)
        self.assertIn('"lyric_target_hands"', grammar)
        self.assertNotIn('"SPINE\\t2\\tPHASE=setup"', grammar)
        non_contact = build_scene_spine_grammar([1, 2], allow_target_hands=False)
        self.assertNotIn('"lyric_target_hands"', non_contact)
        self.assertNotIn('"lyric_target_body"', non_contact)
        effect_grammar = build_scene_spine_grammar(
            [1], allow_target_hands=False, track_external_effect=True
        )
        self.assertIn('"｜EFFECT_TO="', effect_grammar)
        self.assertIn('"lyric_target_body"', effect_grammar)
        effect = parse_scene_spine_step(
            "PHASE=event｜FROM=火が低く浮かぶ｜ADVANCE=火が樹間へ移る"
            "｜TO=人物が見上げる｜SHOW=lyric_target_body"
            "｜EFFECT_TO=二つの火が樹間を上昇中"
        )
        validate_scene_spine((effect,))
        self.assertEqual(effect.required_coverage, "lyric_target_and_body")
        self.assertEqual(effect.to_dict()["effect_to"], "二つの火が樹間を上昇中")
        self.assertEqual(
            _continuation_effect_state(
                1, continuation=True, last_shot_by_scene={1: 1},
                scene_spine_steps={(1, 1): effect},
            ),
            "二つの火が樹間を上昇中",
        )
        self.assertEqual(
            _continuation_effect_state(
                1, continuation=False, last_shot_by_scene={1: 1},
                scene_spine_steps={(1, 1): effect},
            ), "",
        )
        self.assertEqual(
            _sparse_body_accent_keys(
                {(1, 1): {"lyrics": [{"section": "CHORUS"}],
                           "shot_index": 1, "scene_shot_count": 1,
                           "scene_continuation": False}},
                {(1, 1): effect}, lip_sync_active=False,
                cue_cards={(1,): _CueCard(phenomenon="外部自律", valid=True)},
            ),
            {(1, 1)},
        )
        with self.assertRaisesRegex(ValueError, "no valid event position"):
            build_scene_spine_grammar([
                {"slot": 1, "editorial_role": "face_performance_cut"},
                {"slot": 2, "editorial_role": "face_performance_cut"},
            ])

    def test_camera_requires_spine_focus_and_keeps_target_readable(self) -> None:
        entity = _Entity(1, (1, 1), {
            "shot_duration_ms": 5000,
            "required_spine_coverage": "lyric_target_and_hands",
            "arc_permission": "forbidden",
        })
        hidden = _CameraPlan(
            "Push In at fast speed", "wide", "face_closeup",
            "front", "front", "push_in", "face_eyes_mouth",
        )
        self.assertIn(
            "required_spine_coverage",
            _camera_plan_contract_violations(entity, hidden),
        )
        self.assertIn(
            "spine_target_occluded",
            _camera_plan_contract_violations(entity, hidden),
        )
        fallback = _fallback_camera_plan(entity, 0)
        self.assertEqual(fallback.coverage, "lyric_target_and_hands")
        self.assertNotIn(
            fallback.end_scale, {"head_and_shoulders", "face_closeup"}
        )

    def test_external_effect_body_coverage_preserves_both_in_fallback(self) -> None:
        entity = _Entity(9, (9, 1), {
            "shot_duration_ms": 5000,
            "required_spine_coverage": "lyric_target_and_body",
            "arc_permission": "required",
        })
        fallback = _fallback_camera_plan(entity, 0)
        self.assertEqual(fallback.coverage, "lyric_target_and_body")
        self.assertEqual(_camera_plan_contract_violations(entity, fallback), ())
        rendered = _render_camera_plan(fallback)
        self.assertIn("lyric-selected target or external phenomenon", rendered)
        self.assertIn("weight shift, torso, and both arms", rendered)
        hidden = _CameraPlan(
            "Push In at fast speed", "medium", "face_closeup",
            "front", "front", "push_in", "lyric_target_and_body",
        )
        self.assertIn(
            "spine_target_occluded",
            _camera_plan_contract_violations(entity, hidden),
        )

    def test_external_effect_accent_prefers_event_over_setup(self) -> None:
        setup = parse_scene_spine_step(
            "PHASE=setup｜FROM=立つ｜ADVANCE=重心を預ける｜"
            "TO=片足支持｜SHOW=upper_body_hands｜EFFECT_TO=狐火は人物の前方"
        )
        event = parse_scene_spine_step(
            "PHASE=event｜FROM=片足支持｜ADVANCE=狐火と腕が弧を描く｜"
            "TO=胸を開く｜SHOW=lyric_target_body｜EFFECT_TO=狐火は樹間へ移動中"
        )
        context = {
            (1, index): {
                "lyrics": [{"section": "CHORUS"}],
                "shot_index": index, "scene_shot_count": 2,
                "scene_continuation": False,
            }
            for index in (1, 2)
        }
        self.assertEqual(
            _sparse_body_accent_keys(
                context, {(1, 1): setup, (1, 2): event},
                lip_sync_active=False,
                cue_cards={(1,): _CueCard(phenomenon="外部自律", valid=True)},
            ),
            {(1, 2)},
        )

    def test_scene_task_is_one_call_for_two_shots_and_shared_with_camera(self) -> None:
        class Backend(FakePlannerBackend):
            def complete_planner(self, *, task, system_prompt, payload, config, interrupt_callback=None):
                if task == "scene-spine":
                    value = json.loads(payload)
                    self.calls.append((task, value))
                    return "\n".join(
                        f"SPINE\t{item['slot']}\t"
                        + (
                            "PHASE=event｜FROM=手を下ろす｜ADVANCE=鳥居へ手を伸ばす"
                            "｜TO=手を戻す｜SHOW=lyric_target"
                            if index == 0 else
                            "PHASE=response｜FROM=手を戻す｜ADVANCE=表情を緩める"
                            "｜TO=正面を見る｜SHOW=face_eyes_mouth"
                        )
                        for index, item in enumerate(value["slots"])
                    )
                return super().complete_planner(
                    task=task, system_prompt=system_prompt, payload=payload,
                    config=config, interrupt_callback=interrupt_callback,
                )

        backend = Backend()
        system_prompts = {**prompts(), "scene-spine": "scene-spine"}
        result = plan_timeline(
            backend, template_emd=TEMPLATE + INSTRUMENTAL_TAIL, concept_emd=CONCEPT,
            direction=DirectionArtifact(
                motion_profile_id="anime_emotional_mv",
                camera_profile_id="anime_emotional_mv",
            ),
            lip_sync_mode="off", lip_sync_target="サブジェクト1",
            lip_sync_audio_slot=1, scenes_per_batch=1,
            system_prompts=system_prompts, runtime_config=runtime(),
        )
        self.assertTrue(result.complete)
        spine_calls = [payload for task, payload in backend.calls if task == "scene-spine"]
        self.assertEqual(len(spine_calls), 1)
        self.assertEqual(len(spine_calls[0]["slots"]), 2)
        self.assertEqual(len(result.content.scene_spine_steps), 2)
        action_payload = next(payload for task, payload in backend.calls if task == "actions")
        self.assertEqual(
            action_payload["slots"][0]["scene_spine_step"]["advance"],
            "鳥居へ手を伸ばす",
        )
        second_action_payload = next(
            payload for task, payload in backend.calls
            if task == "actions" and payload["slots"][0]["scene_number"] == 2
        )
        self.assertEqual(
            second_action_payload["slots"][0]["entry_body_state"],
            "正面を見る",
        )
        camera_payload = next(payload for task, payload in backend.calls if task == "cameras")
        self.assertEqual(
            camera_payload["slots"][0]["required_spine_coverage"],
            "lyric_target",
        )

    def test_external_effect_endpoint_reaches_continuation_and_camera(self) -> None:
        class Backend(FakePlannerBackend):
            def complete_planner(self, *, task, system_prompt, payload, config,
                                 interrupt_callback=None):
                value = json.loads(payload)
                if task == "visual-beats":
                    self.calls.append((task, value))
                    return "\n".join(
                        f"BEAT\t{item['slot']}\t感情=高揚｜根拠=狐火へ問う｜対象=狐火｜"
                        "接触=禁止｜現象=外部自律｜配置=人物の前方の空間｜"
                        "可視展開=二つの狐火が人物の周囲から樹間へ移る｜"
                        "身体主導=左右の腕と重心が呼応｜終端=狐火を見上げる"
                        for item in value["slots"]
                    )
                if task == "scene-spine":
                    self.calls.append((task, value))
                    assert value["track_external_effect"]
                    return "\n".join(
                        f"SPINE\t{item['slot']}\t" + (
                            "PHASE=event｜FROM=狐火が人物の前に浮かぶ｜"
                            "ADVANCE=二つの狐火が腕の弧を追って樹間へ旋回する｜"
                            "TO=人物は重心を移して見上げる｜SHOW=lyric_target_body｜"
                            "EFFECT_TO=二つの狐火が樹間を上昇中"
                            if index == 0 else
                            "PHASE=response｜FROM=人物は狐火を見上げる｜"
                            "ADVANCE=視線と腕を静める｜TO=人物は正面に立つ｜"
                            "SHOW=face_eyes_mouth｜EFFECT_TO=二つの狐火が樹間の高所へ進む"
                        ) for index, item in enumerate(value["slots"])
                    )
                return super().complete_planner(
                    task=task, system_prompt=system_prompt, payload=payload,
                    config=config, interrupt_callback=interrupt_callback,
                )

        backend = Backend()
        template = (TEMPLATE + INSTRUMENTAL_TAIL).replace(
            "千年鳥居をくぐるそなたよ", "狐火へ問う"
        ).replace("VERSE1", "CHORUS")
        result = plan_timeline(
            backend, template_emd=template, concept_emd=CONCEPT,
            direction=DirectionArtifact(
                motion_profile_id="anime_emotional_mv",
                camera_profile_id="anime_emotional_mv",
            ),
            lip_sync_mode="off", lip_sync_target="サブジェクト1",
            lip_sync_audio_slot=1, scenes_per_batch=1,
            system_prompts={**prompts(), "scene-spine": "scene-spine"},
            runtime_config=runtime(),
        )
        self.assertTrue(result.complete)
        continuation = next(
            payload for task, payload in backend.calls
            if task == "actions" and payload["slots"][0]["scene_number"] == 2
        )
        self.assertEqual(
            continuation["slots"][0]["entry_effect_state"],
            "二つの狐火が樹間の高所へ進む",
        )
        camera = next(payload for task, payload in backend.calls if task == "cameras")
        self.assertEqual(
            camera["slots"][0]["required_spine_coverage"],
            "lyric_target_and_body",
        )
        self.assertEqual(
            camera["slots"][0]["scene_spine_step"]["effect_to"],
            "二つの狐火が樹間を上昇中",
        )

        # A one-Shot external-effect Scene must still produce an endpoint for
        # the next CONTINUE Scene (the original failure included such a Scene).
        one_shot_backend = Backend()
        one_shot_template = template.replace(
            "## ショット 00:05.000\n* 未計画\n", ""
        )
        one_shot_result = plan_timeline(
            one_shot_backend, template_emd=one_shot_template,
            concept_emd=CONCEPT,
            direction=DirectionArtifact(
                motion_profile_id="anime_emotional_mv",
                camera_profile_id="anime_emotional_mv",
            ),
            lip_sync_mode="off", lip_sync_target="サブジェクト1",
            lip_sync_audio_slot=1, scenes_per_batch=1,
            system_prompts={**prompts(), "scene-spine": "scene-spine"},
            runtime_config=runtime(),
        )
        self.assertTrue(one_shot_result.complete)
        one_shot_spine = next(
            payload for task, payload in one_shot_backend.calls
            if task == "scene-spine"
        )
        self.assertEqual(len(one_shot_spine["slots"]), 1)
        next_actions = next(
            payload for task, payload in one_shot_backend.calls
            if task == "actions" and payload["slots"][0]["scene_number"] == 2
        )
        self.assertEqual(
            next_actions["slots"][0]["entry_effect_state"],
            "二つの狐火が樹間を上昇中",
        )


if __name__ == "__main__":
    unittest.main()
