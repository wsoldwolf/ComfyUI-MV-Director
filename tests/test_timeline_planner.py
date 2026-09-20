from __future__ import annotations

import json
import unittest
from pathlib import Path

from core.artifacts import DirectionArtifact
from core.compiler import compile_ref2va
from core.direction import STYLE_PROFILES
from core.emd import parse_emd
from core.emd.ast import Scene
from core.inference import LlamaRuntimeConfig
from core.h3_contract import (
    ANIME_EMOTIONAL_FACE_PERFORMANCE_CUT_CAMERA,
    FACE_PERFORMANCE_CUT_ACTION,
    FACE_PERFORMANCE_CUT_CAMERA,
)
from core.planner import (
    DialogueProtector,
    PlannerContent,
    filter_generated_dialogue,
    normalize_concept_emd,
    parse_template_emd,
    plan_timeline,
    render_planner_content,
)
from core.planner.layout import (
    apply_scene_continuations,
    apply_shot_layouts,
    build_layout_candidates,
    parse_layout_selection,
    parse_scene_layout_selection,
    repair_scene_layout_selection,
)
from core.planner.engine import (
    _Entity,
    _anime_emotional_mv_camera_emphasis,
    _anime_story_mv_face_zoom_key,
    _anime_story_mv_long_arc_keys,
    _action_audit_failures,
    _action_budget_violations,
    _camera_budget_violations,
    _camera_editorial_role,
    _camera_plan_contract_violations,
    _face_arc_transitions,
    _fallback_camera_plan,
    _performance_role,
    _priority_cue_card_violations,
    _priority_cue_phase,
    _priority_lyric_cues_from_sources,
    _scene_batches_with_isolated_priority_cues,
    _strip_redundant_record_envelope,
    _unexpected_priority_cues,
    _with_grounding_transfer_requirements,
    _parse_cue_card,
    _parse_camera_plan,
    _recover_unframed_records,
    _repair_boundary_contract,
    _render_camera_plan,
    _satisfies_boundary_contract,
)
from core.planner.template import PlannerTemplate


TEMPLATE = """> `シーン` 1
# シーン 00:00.000 --> 00:10.125
* `H3長` 243
> `セクション` VERSE1
> `歌詞開始` 00:02.300
> `歌詞終了` 00:05.800
> `歌詞` 千年鳥居をくぐるそなたよ
## ショット 00:00.000
* 未計画
## ショット 00:05.000
* 未計画
"""

CONCEPT = """# サブジェクト
* `画像1` 主人公。長い黒髪と白い衣装を持つ人物。
"""

INSTRUMENTAL_TAIL = """
> `シーン` 2
# シーン 00:10.125 --> 00:11.833 継続
* `H3長` 56
## ショット 00:10.125
* 未計画
"""

LATE_SECTION_TEMPLATE = """> `シーン` 1
# シーン 00:00.000 --> 00:06.000
* `H3長` 158
## ショット 00:00.000
* 未計画
## ショット 00:02.000
* 未計画
> `セクション` VERSE2
> `歌詞開始` 00:02.200
> `歌詞終了` 00:04.500
> `歌詞` 新しい節を歌う
## ショット 00:04.000
* 未計画
"""


class FakePlannerBackend:
    def __init__(self, *, miss_action_slot_two: int = 0) -> None:
        self.calls: list[tuple[str, dict[str, object]]] = []
        self.miss_action_slot_two = miss_action_slot_two

    def complete_planner(self, *, task, system_prompt, payload, config, interrupt_callback=None):
        value = json.loads(payload)
        self.calls.append((task, value))
        if task == "lyric-cues":
            return "\n".join(f"DISCOVERY\t{item['slot']}\tnone|なし" for item in value["slots"])
        record_type = {
            "visual-beats": "BEAT",
            "song-direction": "DIRECTION",
            "shot-layout": "LAYOUT",
            "actions": "ACTION",
            "action-audit": "AUDIT",
            "cameras": "CAMERA",
        }[task]
        rows = []
        for item in value["slots"]:
            slot = item["slot"]
            if (
                task == "actions"
                and item.get("shot_index") == 2
                and self.miss_action_slot_two > 0
            ):
                self.miss_action_slot_two -= 1
                continue
            if task == "shot-layout":
                text = ("CUT" if item["scene_number"] == 1 else "CONTINUE") + "," + ",".join(
                    candidate["id"]
                    for candidate in item["candidates"]
                    if candidate["source"] in {"scene_start", "existing_shot"}
                )
            else:
                identity = (
                    f"{item.get('scene_number', 0)}-"
                    f"{item.get('shot_index', 0)}"
                )
                text = {
                    "visual-beats": (
                        (
                            "感情=決意｜根拠=千年鳥居｜対象=千年鳥居｜"
                            "接触=禁止｜現象=なし｜配置=参道奥の鳥居｜"
                            "可視展開=鳥居の輪郭が夜空に浮かぶ｜身体主導=胸郭と肩の反転｜"
                            "終端=鳥居へ正対して静止"
                        )
                        if item.get("lyrics")
                        else (
                            "感情=余韻｜根拠=なし｜対象=なし｜接触=禁止｜"
                            "現象=なし｜配置=なし｜可視展開=なし｜身体主導=呼吸と重心移動｜終端=静止"
                        )
                    ),
                    "song-direction": "夜から朝へ進み、鳥居を反復する。",
                    "actions": (
                        _grounded_fixture_action(
                            item,
                            "サブジェクト1が重心を移しながら歩く。"
                            f"{identity} 「生成台詞」",
                        )
                    ),
                    "action-audit": "PASS",
                    "cameras": (
                        (
                            "Arc Shot with large amplitude at fast speed "
                            "で顔から人物の側面を回り全身と鳥居を開示する。"
                            if item.get("face_arc_transition")
                            or item.get("long_arc_emphasis")
                            else (
                                "Zoom In with large amplitude at fast speed "
                                "で両目と歌唱口を保ちながら顔へ寄る。"
                                if item.get("face_zoom_emphasis")
                                else "カメラは前景の鳥居から人物へ緩やかに寄る。"
                            )
                        )
                        + identity
                    ),
                }[task]
                if task == "cameras" and item.get("camera_protocol") == "finite_v1":
                    relation = item.get("face_arc_transition")
                    if item.get("long_arc_emphasis") or relation:
                        text = (
                            "MOTION=Arc Shot with large amplitude at fast speed｜"
                            + (
                                "START_SCALE=head_and_shoulders｜END_SCALE=full_body｜"
                                "START_VIEW=front_three_quarter｜END_VIEW=side｜"
                                "PATH=arc_right_60_120_70_90｜COVERAGE=whole_body_emotion"
                                if relation == "arc_out_of_previous_face_cut"
                                else "START_SCALE=full_body｜END_SCALE=head_and_shoulders｜"
                                "START_VIEW=low_front_three_quarter｜END_VIEW=front_three_quarter｜"
                                "PATH=arc_left_60_120_70_90｜COVERAGE=face_eyes_mouth"
                            )
                        )
                    elif item.get("face_zoom_emphasis"):
                        text = (
                            "MOTION=Zoom In with large amplitude at fast speed｜"
                            "START_SCALE=head_and_shoulders｜END_SCALE=face_closeup｜"
                            "START_VIEW=front_three_quarter｜END_VIEW=front_three_quarter｜"
                            "PATH=zoom_in_35_55｜COVERAGE=face_eyes_mouth"
                        )
                    else:
                        text = (
                            "MOTION=Push In at fast speed｜START_SCALE=wide｜"
                            "END_SCALE=medium｜START_VIEW=front_three_quarter｜"
                            "END_VIEW=front_three_quarter｜PATH=push_in｜"
                            "COVERAGE=environment_relation"
                        )
                if task == "cameras" and (
                    value.get("diversity_retry")
                    or value.get("camera_quality_retry")
                ) and item.get("camera_protocol") != "finite_v1":
                    text = (
                        "Truck Right at fast speed で人物の肩越しに鳥居を横切る。"
                        + identity
                    )
            rows.append(f"{record_type}\t{slot}\t{text}")
        return "\n".join(rows)


def _grounded_fixture_action(
    item: dict[str, object], body: str
) -> str:
    fragments = [
        str(item.get("required_spatial_anchor", "")).strip(),
        str(item.get("required_visible_development", "")).strip(),
    ]
    grounding = item.get("visual_beat_grounding")
    if isinstance(grounding, dict) and grounding.get("valid"):
        target = str(grounding.get("target", "")).strip()
        if target and target not in {"なし", "無し", "none", "NONE"}:
            fragments.append(f"{target}へ注意を向ける")
    fragments.append(body)
    return "。".join(fragment.rstrip("。") for fragment in fragments if fragment)


class DialogueOnlyPlannerBackend(FakePlannerBackend):
    def complete_planner(self, *, task, system_prompt, payload, config, interrupt_callback=None):
        value = json.loads(payload)
        self.calls.append((task, value))
        record_type = {
            "visual-beats": "BEAT",
            "song-direction": "DIRECTION",
            "shot-layout": "LAYOUT",
            "actions": "ACTION",
            "action-audit": "AUDIT",
            "cameras": "CAMERA",
        }[task]
        if task == "shot-layout":
            return "\n".join(
                f"LAYOUT\t{item['slot']}\t"
                f"{'CUT' if item['scene_number'] == 1 else 'CONTINUE'},"
                + ",".join(
                    candidate["id"]
                    for candidate in item["candidates"]
                    if candidate["source"] in {"scene_start", "existing_shot"}
                )
                for item in value["slots"]
            )
        if task not in {"actions", "cameras", "action-audit"}:
            text = "有効な視覚計画"
            return "\n".join(
                f"{record_type}\t{item['slot']}\t{text}" for item in value["slots"]
            )
        if task == "action-audit":
            return "\n".join(
                f"AUDIT\t{item['slot']}\tPASS" for item in value["slots"]
            )
        return "\n".join(
            f"{record_type}\t{item['slot']}\t「生成台詞だけ」" for item in value["slots"]
        )


class NewCutPlannerBackend(FakePlannerBackend):
    def complete_planner(self, *, task, system_prompt, payload, config, interrupt_callback=None):
        if task != "shot-layout":
            return super().complete_planner(
                task=task,
                system_prompt=system_prompt,
                payload=payload,
                config=config,
                interrupt_callback=interrupt_callback,
            )
        value = json.loads(payload)
        self.calls.append((task, value))
        rows = []
        for item in value["slots"]:
            balanced = [
                candidate["id"]
                for candidate in item["candidates"]
                if candidate["source"] == "balanced"
            ]
            selected = ["B0", balanced[0], balanced[-1]]
            rows.append(f"LAYOUT\t{item['slot']}\tCUT,{','.join(selected)}")
        return "\n".join(rows)


class PassthroughTranslator:
    def translate(self, units):
        return tuple(units)


class SmallModelFormattingBackend(FakePlannerBackend):
    def complete_planner(self, *, task, system_prompt, payload, config, interrupt_callback=None):
        value = json.loads(payload)
        self.calls.append((task, value))
        record_type = {
            "visual-beats": "BEAT",
            "song-direction": "DIRECTION",
            "shot-layout": "LAYOUT",
            "actions": "ACTION",
            "action-audit": "AUDIT",
            "cameras": "CAMERA",
        }[task]
        if task == "visual-beats":
            return "<think>protocolを確認する。</think>\n歌詞本文\tTAB\t1\tTAB\t有効な記述1"
        if task == "song-direction":
            return "<think></think>\nDIRECTION\tTAB\tslot1\tTAB\t有効な全曲方針"
        if task == "shot-layout":
            selected = ",".join(
                candidate["id"]
                for candidate in value["slots"][0]["candidates"]
                if candidate["source"] in {"scene_start", "existing_shot"}
            )
            return f"<think></think>\nLAYOUT\tTAB\tslot1\tTAB\tCUT,{selected}"
        records = [
            f"{record_type}<TAB>{item['slot']}<TAB>"
            + f"有効な記述{item['slot']}"
            for item in value["slots"]
        ]
        return "<think>protocolを確認する。</think>\n" + "<TAB>".join(records)


def runtime() -> LlamaRuntimeConfig:
    return LlamaRuntimeConfig(max_tokens=512, n_ctx=4096)


def prompts() -> dict[str, str]:
    return {
        "visual-beats": "beats",
        "song-direction": "direction",
        "shot-layout": "layout",
        "actions": "actions",
        "action-audit": "action-audit",
        "cameras": "cameras",
    }


class TimelinePlannerCoreTests(unittest.TestCase):
    def test_duplicate_record_envelope_is_removed_without_rewriting_text(self) -> None:
        cases = (
            ("ACTION 1 胸郭を起こす。", "ACTION", 1, "胸郭を起こす。"),
            ("ACTION 14 1 視線を上げる。", "ACTION", 1, "視線を上げる。"),
            ("1 タブ　肩を引く。", "ACTION", 1, "肩を引く。"),
            ("AUDIT 2 PASS", "AUDIT", 2, "PASS"),
        )
        for text, record_type, slot, expected in cases:
            with self.subTest(text=text):
                self.assertEqual(
                    _strip_redundant_record_envelope(text, record_type, slot),
                    (expected, True),
                )
        self.assertEqual(
            _strip_redundant_record_envelope(
                "御神木を見上げ、胸郭を起こす。",
                "ACTION",
                1,
            ),
            ("御神木を見上げ、胸郭を起こす。", False),
        )

    def test_duplicate_action_and_audit_wrappers_are_recovered_in_plan(self) -> None:
        class DuplicateEnvelopeBackend(FakePlannerBackend):
            def complete_planner(
                self,
                *,
                task,
                system_prompt,
                payload,
                config,
                interrupt_callback=None,
            ):
                response = super().complete_planner(
                    task=task,
                    system_prompt=system_prompt,
                    payload=payload,
                    config=config,
                    interrupt_callback=interrupt_callback,
                )
                if task not in {"actions", "action-audit"}:
                    return response
                rows = []
                for line in response.splitlines():
                    record_type, slot, text = line.split("\t", 2)
                    rows.append(
                        f"{record_type}\t{slot}\t"
                        f"{record_type} {slot} {text}"
                    )
                return "\n".join(rows)

        result = plan_timeline(
            DuplicateEnvelopeBackend(),
            template_emd=TEMPLATE,
            concept_emd=CONCEPT,
            direction=DirectionArtifact(camera_profile_id="anime_emotional_mv"),
            lip_sync_mode="off",
            lip_sync_target="サブジェクト1",
            lip_sync_audio_slot=1,
            scenes_per_batch=3,
            system_prompts=prompts(),
            runtime_config=runtime(),
        )
        self.assertTrue(result.complete)
        self.assertFalse(result.missing)
        self.assertGreaterEqual(result.content.protocol_recovered_count, 4)
        self.assertTrue(
            all(
                not text.startswith(("ACTION ", "AUDIT "))
                for _scene, _shot, text in result.content.actions
            )
        )

    def test_unframed_camera_lines_are_recovered_without_rewriting_text(self) -> None:
        response = (
            "Arc Shot with large amplitude at fast speed で側面を通る。\n"
            "Tracking Shot at fast speed で走る人物を追う。"
        )
        self.assertEqual(
            _recover_unframed_records(response, "CAMERA", [4, 5]),
            {
                4: "Arc Shot with large amplitude at fast speed で側面を通る。",
                5: "Tracking Shot at fast speed で走る人物を追う。",
            },
        )

    def test_numbered_protocol_wrapper_is_removed_but_text_is_unchanged(self) -> None:
        response = (
            "1. Arc Shot で人物の右側へ回る。\n"
            "2: Static Shot で顔を保持する。"
        )
        self.assertEqual(
            _recover_unframed_records(response, "CAMERA", [1, 2]),
            {
                1: "Arc Shot で人物の右側へ回る。",
                2: "Static Shot で顔を保持する。",
            },
        )

    def test_single_unlabelled_line_is_not_guessed(self) -> None:
        self.assertEqual(
            _recover_unframed_records(
                "Arc Shot で人物の側面を通る。", "CAMERA", [1]
            ),
            {},
        )

    def test_isolated_single_unlabelled_line_has_unique_side_table_mapping(self) -> None:
        self.assertEqual(
            _recover_unframed_records(
                "Static Shot で両目と口全体を大きく写す。",
                "CAMERA",
                [7],
                allow_single_positional=True,
            ),
            {7: "Static Shot で両目と口全体を大きく写す。"},
        )

    def test_isolated_json_wrapper_recovers_text_without_rewriting_it(self) -> None:
        text = "袖を胸元へ引き寄せ、歌詞の余韻に合わせて視線を上げる。"
        response = json.dumps(
            {"record_type": "ACTION", "slot": 1, "text": text},
            ensure_ascii=False,
        )
        self.assertEqual(
            _recover_unframed_records(
                response,
                "ACTION",
                [1],
                allow_single_positional=True,
            ),
            {1: text},
        )

    def test_isolated_markdown_table_recovers_text_without_rewriting_it(self) -> None:
        text = "肩越しに振り返り、右手を胸の前で静止させる。"
        response = "| ACTION | 1 | " + text + " |"
        self.assertEqual(
            _recover_unframed_records(
                response,
                "ACTION",
                [1],
                allow_single_positional=True,
            ),
            {1: text},
        )

    def test_isolated_label_wrapper_requires_matching_slot(self) -> None:
        response = "type: ACTION\nslot: 2\ntext: この値は別slotである。"
        self.assertEqual(
            _recover_unframed_records(
                response,
                "ACTION",
                [1],
                allow_single_positional=True,
            ),
            {},
        )

    def test_isolated_multiline_prose_uses_unique_side_table_mapping(self) -> None:
        response = (
            "ACTION\nslot: 1\n"
            "袖を胸元へ引き寄せる。\n"
            "続けて視線を鳥居の奥へ移す。"
        )
        self.assertEqual(
            _recover_unframed_records(
                response,
                "ACTION",
                [1],
                allow_single_positional=True,
            ),
            {1: "袖を胸元へ引き寄せる。 続けて視線を鳥居の奥へ移す。"},
        )

    def test_boundary_repair_scales_to_twenty_four_all_cut_scenes(self) -> None:
        template = PlannerTemplate(
            scenes=tuple(
                Scene(
                    scene_number=index,
                    start_ms=(index - 1) * 1000,
                    end_ms=index * 1000,
                    h3_length=22,
                    descriptions=(),
                    shots=(),
                    audio_directives=(),
                    line_number=index,
                    continuation=False,
                )
                for index in range(1, 25)
            )
        )
        repaired, changed = _repair_boundary_contract(
            template,
            {index: False for index in range(1, 25)},
        )
        later = [repaired[index] for index in range(2, 25)]
        self.assertTrue(_satisfies_boundary_contract(template, repaired))
        self.assertGreaterEqual(later.count(False), 5)
        self.assertGreaterEqual(later.count(True), 7)
        self.assertEqual(len(changed), later.count(True))

    def test_exact_boundary_alternation_is_repaired(self) -> None:
        template = PlannerTemplate(
            scenes=tuple(
                Scene(
                    scene_number=index,
                    start_ms=(index - 1) * 1000,
                    end_ms=index * 1000,
                    h3_length=22,
                    descriptions=(),
                    shots=(),
                    audio_directives=(),
                    line_number=index,
                    continuation=False,
                )
                for index in range(1, 9)
            )
        )
        alternating = {
            index: bool(index % 2 == 0) for index in range(1, 9)
        }
        self.assertFalse(_satisfies_boundary_contract(template, alternating))
        repaired, _changed = _repair_boundary_contract(template, alternating)
        self.assertTrue(_satisfies_boundary_contract(template, repaired))
        later = [repaired[index] for index in range(2, 9)]
        transitions = sum(
            left != right for left, right in zip(later, later[1:])
        )
        self.assertLess(transitions, len(later) - 1)

    def test_every_layout_candidate_combination_is_duration_safe(self) -> None:
        scene = parse_template_emd(TEMPLATE).scenes[0]
        candidates = build_layout_candidates(scene)
        starts = [candidate.start_ms for candidate in candidates]
        self.assertTrue(
            all(
                right - left >= 1500
                for left, right in zip(starts, starts[1:])
            )
        )
        self.assertGreaterEqual(scene.end_ms - starts[-1], 1500)

    def test_layout_can_add_python_owned_cut_candidates(self) -> None:
        template = parse_template_emd(TEMPLATE)
        scene = template.scenes[0]
        candidates = build_layout_candidates(scene)
        balanced = next(
            candidate for candidate in candidates if candidate.source == "balanced"
        )
        starts = parse_layout_selection(
            f"B0,{balanced.candidate_id}",
            candidates,
            scene_end_ms=scene.end_ms,
        )
        planned = apply_shot_layouts(template, {1: starts})

        self.assertEqual(
            tuple(shot.start_ms for shot in planned.scenes[0].shots),
            starts,
        )
        self.assertEqual(len(planned.scenes[0].shots), 2)

    def test_single_shot_is_valid_when_scene_is_shorter_than_cut_minimum(self) -> None:
        template = parse_template_emd(
            """> `シーン` 1
# シーン 00:00.000 --> 00:01.000
* `H3長` 22
## ショット 00:00.000
* 未計画
"""
        )
        scene = template.scenes[0]
        candidates = build_layout_candidates(scene)
        starts = parse_layout_selection(
            "B0",
            candidates,
            scene_end_ms=scene.end_ms,
        )
        planned = apply_shot_layouts(template, {1: starts})
        self.assertEqual(len(planned.scenes[0].shots), 1)

    def test_planner_expands_selected_cut_candidates_before_action_and_camera(self) -> None:
        backend = NewCutPlannerBackend()
        result = plan_timeline(
            backend,
            template_emd=TEMPLATE,
            concept_emd=CONCEPT,
            direction=None,
            lip_sync_mode="off",
            lip_sync_target="サブジェクト1",
            lip_sync_audio_slot=1,
            scenes_per_batch=3,
            system_prompts=prompts(),
            runtime_config=runtime(),
        )

        self.assertTrue(result.complete)
        document = parse_emd(result.emd.text)
        self.assertEqual(len(document.scenes[0].shots), 3)
        layout_payload = next(
            payload for task, payload in backend.calls if task == "shot-layout"
        )
        self.assertTrue(
            all(
                "current_boundary_mode" not in slot
                for slot in layout_payload["slots"]
            )
        )
        action_payload = next(
            payload for task, payload in backend.calls if task == "actions"
        )
        camera_payload = next(
            payload for task, payload in backend.calls if task == "cameras"
        )
        self.assertEqual(len(action_payload["slots"]), 3)
        self.assertEqual(len(camera_payload["slots"]), 3)

    def test_invalid_layout_falls_back_to_one_shot_without_blocking(self) -> None:
        class InvalidLayoutBackend(FakePlannerBackend):
            def complete_planner(
                self,
                *,
                task,
                system_prompt,
                payload,
                config,
                interrupt_callback=None,
            ):
                if task != "shot-layout":
                    return super().complete_planner(
                        task=task,
                        system_prompt=system_prompt,
                        payload=payload,
                        config=config,
                        interrupt_callback=interrupt_callback,
                    )
                value = json.loads(payload)
                self.calls.append((task, value))
                return "\n".join(
                    f"LAYOUT\t{item['slot']}\tBROKEN"
                    for item in value["slots"]
                )

        result = plan_timeline(
            InvalidLayoutBackend(),
            template_emd=TEMPLATE + INSTRUMENTAL_TAIL,
            concept_emd=CONCEPT,
            direction=None,
            lip_sync_mode="off",
            lip_sync_target="サブジェクト1",
            lip_sync_audio_slot=1,
            scenes_per_batch=3,
            system_prompts=prompts(),
            runtime_config=runtime(),
        )

        self.assertTrue(result.complete)
        self.assertEqual(result.content.layout_fallback_scenes, (1, 2))
        document = parse_emd(result.emd.text)
        self.assertEqual(len(document.scenes[0].shots), 1)
        self.assertEqual(
            [scene.continuation for scene in document.scenes],
            [False, False],
        )

    def test_scene_layout_protocol_selects_cut_or_continuation(self) -> None:
        template = parse_template_emd(TEMPLATE + INSTRUMENTAL_TAIL)
        second = template.scenes[1]
        candidates = build_layout_candidates(second)
        continuation, starts = parse_scene_layout_selection(
            "CONTINUE,B0",
            candidates,
            scene_end_ms=second.end_ms,
            first_scene=False,
        )
        self.assertTrue(continuation)
        self.assertEqual(starts, (second.start_ms,))
        with self.assertRaisesRegex(Exception, "first Scene cannot continue"):
            parse_scene_layout_selection(
                "CONTINUE,B0",
                build_layout_candidates(template.scenes[0]),
                scene_end_ms=template.scenes[0].end_ms,
                first_scene=True,
            )

    def test_layout_repair_normalizes_separators_unknown_ids_and_excess(self) -> None:
        scene = parse_template_emd(TEMPLATE).scenes[0]
        candidates = build_layout_candidates(scene)
        continuation, starts = repair_scene_layout_selection(
            "CUT B0 B1 B2 B3 B4 B999",
            candidates,
            scene_end_ms=scene.end_ms,
            first_scene=True,
        )
        self.assertFalse(continuation)
        self.assertGreaterEqual(len(starts), 1)
        self.assertLessEqual(len(starts), 4)
        self.assertEqual(starts[0], scene.start_ms)

    def test_cut_retimes_h3_length_and_removes_continuation_suffix(self) -> None:
        second_scene = """
> `シーン` 2
# シーン 00:10.125 --> 00:20.042 継続
* `H3長` 260
## ショット 00:10.125
* 未計画
"""
        template = parse_template_emd(TEMPLATE + second_scene)
        retimed = apply_scene_continuations(template, {1: False, 2: False})
        self.assertFalse(retimed.scenes[1].continuation)
        self.assertEqual(retimed.scenes[1].start_ms, retimed.scenes[0].end_ms)
        self.assertEqual(retimed.scenes[1].h3_length % 17, 5)
        self.assertEqual(retimed.scenes[1].h3_length, 243)

    def test_action_prompt_does_not_animate_appearance_attributes(self) -> None:
        prompt = (
            Path(__file__).parents[1]
            / "prompts"
            / "timeline_planner_actions_system_prompt.txt"
        ).read_text(encoding="utf-8")
        self.assertIn("Never turn a stable appearance attribute into an action", prompt)
        self.assertIn("eye color", prompt)
        self.assertIn("readable acceleration", prompt)
        self.assertIn("subject_instance_policy", prompt)
        self.assertIn("animal ears, ear interiors", prompt)
        self.assertIn("do not make an ear or patch of fur", prompt)
        self.assertIn("highest-priority immutable common constraint set", prompt)
        self.assertIn("omit any conflicting", prompt)
        self.assertIn("subject_roster identifies performers only", prompt)
        self.assertIn("detailed Subject appearance remains renderer-owned", prompt)
        self.assertIn("feet, toes, fabric sliding over terrain", prompt)
        self.assertIn("A lyric transcript is vocal content", prompt)
        self.assertIn("do not write\nwound, scar, cut, bruise", prompt)
        self.assertIn("unrequested_running_maximum", prompt)
        self.assertIn("Never invent running to\nfill an instrumental Shot", prompt)
        self.assertIn("Fit the performance to shot_duration_ms", prompt)
        self.assertIn("preserve open\ncirculation space", prompt)
        self.assertIn("never turn one into the\nAction's contact target", prompt)
        self.assertIn("planner_policy_contract.policy_id is anime_emotional_mv", prompt)
        self.assertIn("half-lidded hold", prompt)
        self.assertIn("Use only the eyes or body parts needed", prompt)
        self.assertIn("keep the effect autonomous", prompt)
        self.assertIn("current Scene's original lyric", prompt)
        self.assertIn("named without an explicit verb", prompt)
        self.assertIn("autonomous state, motion, transformation", prompt)
        self.assertIn("not another complete replay", prompt)

    def test_visual_beat_prompt_treats_complete_direction_as_immutable(self) -> None:
        prompt = (
            Path(__file__).parents[1]
            / "prompts"
            / "timeline_planner_visual_beats_system_prompt.txt"
        ).read_text(encoding="utf-8")
        self.assertIn("performance-scoped direction", prompt)
        self.assertIn("immutable common constraint set", prompt)
        self.assertIn("must not shine, glow, radiate, bloom", prompt)
        self.assertIn("subject_roster", prompt)
        self.assertIn("generic_locomotion_is_support_only", prompt)
        self.assertIn("not creative source material", prompt)
        self.assertIn("footwear", prompt)
        self.assertIn("replace every background and lighting", prompt)
        self.assertIn("Keep the directed environment continuous", prompt)
        self.assertIn("figurative lyric language about a wound", prompt)
        self.assertIn("visible skin and clothing clean and intact", prompt)
        self.assertIn("twelve-Scene negative motif ledger", prompt)
        self.assertIn("especially strict\nfor an instrumental Scene", prompt)
        self.assertIn("functional spatial topology", prompt)
        self.assertIn(
            "never use one\nas the Beat's contact target", prompt
        )
        self.assertIn("current Scene's original lyric", prompt)
        self.assertIn("lyric-selected target is consumed", prompt)
        self.assertIn("not a checklist of compulsory body mechanics", prompt)
        self.assertIn("moves independently through", prompt)
        self.assertIn("place it in the Subject's hand", prompt)
        self.assertIn("Read every lyric line", prompt)
        self.assertIn("Do not ignore a lyric noun", prompt)
        self.assertIn("a lyric-selected effect with a", prompt)
        self.assertIn("現象=...｜配置=...｜可視展開=...｜身体主導=...", prompt)
        self.assertIn("exact contiguous excerpt", prompt)
        self.assertIn("bounded may select one compatible non-destructive contact", prompt)
        self.assertIn("literal requires a", prompt)

    def test_camera_prompt_keeps_arc_and_closeup_shot_local(self) -> None:
        prompt = (
            Path(__file__).parents[1]
            / "prompts"
            / "timeline_planner_cameras_system_prompt.txt"
        ).read_text(encoding="utf-8")
        self.assertIn("recent_camera_history", prompt)
        self.assertIn("Use an arc only when", prompt)
        self.assertIn("use a close-up only", prompt)
        self.assertIn("Never impose either choice on the whole Scene", prompt)
        self.assertIn("does not force every CUT Scene into a close-up", prompt)
        self.assertIn("both eyes, both eyebrows", prompt)
        self.assertIn("arc_required", prompt)
        self.assertIn("camera contract, not a suggestion", prompt)
        self.assertIn("must begin with Arc Shot", prompt)
        self.assertIn(
            "begin with exactly one literal MiniMax H3 Motion Type",
            prompt,
        )
        self.assertIn("Never start the physical line directly with the Motion Type", prompt)
        self.assertIn("Tracking Shot", prompt)
        self.assertIn("exactly one performer", prompt)
        self.assertIn("one unified continuous camera image", prompt)
        self.assertIn("never as simultaneous spatial views", prompt)
        self.assertIn("picture-in-picture", prompt)
        self.assertIn("Stage every Shot as a newly photographed composition", prompt)
        self.assertIn("first output frame must already use", prompt)
        self.assertIn("Do not restate or modify environment", prompt)
        self.assertIn("must remain non-emissive", prompt)
        self.assertIn("translucent lamp effect", prompt)
        self.assertIn("highest-priority immutable common constraint set", prompt)
        self.assertNotIn("every Scene represented by the", prompt)
        self.assertIn("does not require a close-up or", prompt)
        self.assertIn("complete mouth", prompt)
        self.assertIn("incompatible body-part detail", prompt)
        self.assertIn("every essential body part and", prompt)
        self.assertIn("support leg, free leg", prompt)
        self.assertIn("35-to-55", prompt)
        self.assertIn("face_zoom_duration_fraction", prompt)
        self.assertIn("70-90%", prompt)
        self.assertIn("half-open gaze", prompt)
        self.assertIn("Static Shot keeps camera position", prompt)
        self.assertIn("label-versus-prose consistency", prompt)
        self.assertIn("face_arc_transition", prompt)
        self.assertIn("arc_out_of_previous_face_cut", prompt)

    def test_layout_prompt_balances_boundaries_and_uses_lyrics_for_face_edits(self) -> None:
        prompt = (
            Path(__file__).parents[1]
            / "prompts"
            / "timeline_planner_shot_layout_system_prompt.txt"
        ).read_text(encoding="utf-8")
        self.assertIn("previous_visual_beat and previous_lyrics", prompt)
        self.assertIn("must contain both later CUT and", prompt)
        self.assertIn("first appearance of a new lyric section", prompt)
        self.assertIn("renderer-owned", prompt)
        self.assertNotIn("must begin a new CUT", prompt)
        self.assertIn("boundary_mix_retry_reason", prompt)
        self.assertIn("later_continue_minimum", prompt)
        self.assertIn("The retry is invalid", prompt)
        self.assertIn("Normally select two or three Shots", prompt)
        self.assertIn("every selected interval remains\nat least two seconds", prompt)
        self.assertIn("do not let the\nface insert consume the only Shot", prompt)
        self.assertIn("add an adjacent normal Shot", prompt)

    def test_degenerate_all_cut_layout_is_replanned_once(self) -> None:
        class DegenerateThenMixedBackend(FakePlannerBackend):
            def complete_planner(
                self,
                *,
                task,
                system_prompt,
                payload,
                config,
                interrupt_callback=None,
            ):
                if task != "shot-layout":
                    return super().complete_planner(
                        task=task,
                        system_prompt=system_prompt,
                        payload=payload,
                        config=config,
                        interrupt_callback=interrupt_callback,
                    )
                value = json.loads(payload)
                self.calls.append((task, value))
                retry = "boundary_mix_retry_reason" in value
                rows = []
                for item in value["slots"]:
                    mode = (
                        "CONTINUE"
                        if retry and item["scene_number"] in {2, 4}
                        else "CUT"
                    )
                    rows.append(f"LAYOUT\t{item['slot']}\t{mode},B0")
                return "\n".join(rows)

        four_scenes = """> `シーン` 1
# シーン 00:00.000 --> 00:02.000
* `H3長` 56
## ショット 00:00.000
* 未計画
> `シーン` 2
# シーン 00:02.000 --> 00:04.000 継続
* `H3長` 56
## ショット 00:02.000
* 未計画
> `シーン` 3
# シーン 00:04.000 --> 00:06.000 継続
* `H3長` 56
## ショット 00:04.000
* 未計画
> `シーン` 4
# シーン 00:06.000 --> 00:08.000 継続
* `H3長` 56
## ショット 00:06.000
* 未計画
"""
        backend = DegenerateThenMixedBackend()
        result = plan_timeline(
            backend,
            template_emd=four_scenes,
            concept_emd=CONCEPT,
            direction=None,
            lip_sync_mode="lyrics",
            lip_sync_target="サブジェクト1",
            lip_sync_audio_slot=1,
            scenes_per_batch=3,
            system_prompts=prompts(),
            runtime_config=runtime(),
        )
        self.assertTrue(result.complete)
        self.assertTrue(result.content.layout_mix_retry)
        self.assertEqual(
            result.content.scene_continuations,
            ((1, False), (2, True), (3, False), (4, True)),
        )
        layout_calls = [
            payload for task, payload in backend.calls if task == "shot-layout"
        ]
        primary_layout_calls = [
            payload
            for payload in layout_calls
            if "boundary_mix_retry_reason" not in payload
        ]
        retry_layout_calls = [
            payload
            for payload in layout_calls
            if "boundary_mix_retry_reason" in payload
        ]
        self.assertEqual(len(primary_layout_calls), 2)
        self.assertEqual(
            [len(payload["slots"]) for payload in primary_layout_calls],
            [3, 1],
        )
        self.assertEqual(len(retry_layout_calls), 2)
        self.assertEqual(
            retry_layout_calls[0]["boundary_contract"]["later_continue_minimum"],
            2,
        )
        self.assertEqual(
            retry_layout_calls[0]["boundary_contract"]["later_cut_minimum"],
            1,
        )
        self.assertIn(
            "previous_visual_beat", primary_layout_calls[0]["slots"][1]
        )
        self.assertIn("previous_lyrics", primary_layout_calls[0]["slots"][1])

    def test_degenerate_retry_that_remains_all_cut_is_structurally_repaired(self) -> None:
        class AlwaysCutBackend(FakePlannerBackend):
            def complete_planner(
                self,
                *,
                task,
                system_prompt,
                payload,
                config,
                interrupt_callback=None,
            ):
                if task != "shot-layout":
                    return super().complete_planner(
                        task=task,
                        system_prompt=system_prompt,
                        payload=payload,
                        config=config,
                        interrupt_callback=interrupt_callback,
                    )
                value = json.loads(payload)
                self.calls.append((task, value))
                return "\n".join(
                    f"LAYOUT\t{item['slot']}\tCUT,B0"
                    for item in value["slots"]
                )

        four_scenes = """> `シーン` 1
# シーン 00:00.000 --> 00:02.000
* `H3長` 56
## ショット 00:00.000
* 未計画
> `シーン` 2
# シーン 00:02.000 --> 00:04.000 継続
* `H3長` 56
## ショット 00:02.000
* 未計画
> `シーン` 3
# シーン 00:04.000 --> 00:06.000 継続
* `H3長` 56
## ショット 00:04.000
* 未計画
> `シーン` 4
# シーン 00:06.000 --> 00:08.000 継続
* `H3長` 56
## ショット 00:06.000
* 未計画
"""
        result = plan_timeline(
            AlwaysCutBackend(),
            template_emd=four_scenes,
            concept_emd=CONCEPT,
            direction=None,
            lip_sync_mode="lyrics",
            lip_sync_target="サブジェクト1",
            lip_sync_audio_slot=1,
            scenes_per_batch=3,
            system_prompts=prompts(),
            runtime_config=runtime(),
        )
        self.assertTrue(result.complete)
        self.assertIsNotNone(result.content)
        continuations = [
            value for _scene, value in result.content.scene_continuations
        ]
        self.assertFalse(continuations[0])
        self.assertTrue(any(continuations[1:]))
        self.assertTrue(any(not value for value in continuations[1:]))
        self.assertTrue(result.content.layout_repaired_scenes)
        self.assertEqual(result.missing, ())

    def test_passthrough_retention_is_rendered_exactly(self) -> None:
        template = parse_template_emd(TEMPLATE)
        content = PlannerContent(
            visual_beats=(),
            song_direction="",
            shot_layouts=((1, (0, 5000)),),
            actions=((1, 1, "動作1"), (1, 2, "動作2")),
            cameras=((1, 1, "カメラ1"), (1, 2, "カメラ2")),
            issue_count=0,
            retried_scenes=(),
            removed_generated_dialogue_count=0,
            unused_protected_dialogue_ids=(),
        )
        retention = (
            "`サブジェクト1`: `partially_preserved` "
            "髪型と衣装だけを保持する。"
        )
        emd = render_planner_content(
            content=content,
            concept_emd=normalize_concept_emd(CONCEPT),
            template=template,
            direction=DirectionArtifact(
                retention_policy="passthrough",
                retention_lines=(retention,),
            ),
            lip_sync_mode="off",
            lip_sync_target="サブジェクト1",
            lip_sync_audio_slot=1,
        ).text
        self.assertIn(f"# 保持分析\n* {retention}", emd)
        parsed = parse_emd(emd).retention[0]
        self.assertEqual(parsed.concept_id, "サブジェクト1")
        self.assertEqual(parsed.mode, "partially_preserved")
        self.assertEqual(parsed.description, "髪型と衣装だけを保持する。")

    def test_cinematic_profile_emits_partial_retention_and_scene_reinforcement(self) -> None:
        template = parse_template_emd(TEMPLATE + INSTRUMENTAL_TAIL)
        concept = normalize_concept_emd(CONCEPT)
        content = PlannerContent(
            visual_beats=((1, "note"),),
            song_direction="direction",
            shot_layouts=((1, (0, 5000)), (2, (10125,))),
            actions=((1, 1, "動作1"), (1, 2, "動作2"), (2, 1, "余韻の動作")),
            cameras=((1, 1, "カメラ1"), (1, 2, "カメラ2"), (2, 1, "余韻のカメラ")),
            issue_count=0,
            retried_scenes=(),
            removed_generated_dialogue_count=0,
            unused_protected_dialogue_ids=(),
        )
        emd = render_planner_content(
            content=content,
            concept_emd=concept,
            template=template,
            direction=DirectionArtifact(
                style_direction=(STYLE_PROFILES["illust_to_photoreal"],),
                style_profile_id="illust_to_photoreal",
                retention_policy="profile",
            ),
            lip_sync_mode="off",
            lip_sync_target="サブジェクト1",
            lip_sync_audio_slot=1,
        ).text
        self.assertIn("# 保持分析", emd)
        self.assertIn(
            "* `サブジェクト1`: `partially_preserved` "
            "Maintain described identifying elements. For characters, maintain "
            "hairstyle, hair color, eye color, outfit, color scheme, and accessories, "
            "and embody them as a physical realistic portrayal in a common prompt.",
            emd,
        )
        reinforcement = (
            "Shoot as a photorealistic live-action video, depicting the characters "
            "as real human actors."
        )
        self.assertEqual(emd.count(reinforcement), 2)
        document = parse_emd(emd)
        self.assertEqual(document.retention[0].mode, "partially_preserved")

        plan = compile_ref2va(emd, PassthroughTranslator()).plan
        self.assertTrue(
            plan["prompt_prefix"][0].startswith(
                "Shoot as a scene from a photorealistic live-action movie."
            )
        )
        for scene in plan["shots"]:
            prompt = "\n".join(scene["prompt"])
            self.assertIn("<Subject 1>: partially_preserved -", prompt)
            self.assertIn(reinforcement, prompt)
            self.assertNotIn("fully_preserved", prompt)

    def test_qwen4b_thinking_literal_tabs_and_joined_records_are_normalized(self) -> None:
        result = plan_timeline(
            SmallModelFormattingBackend(),
            template_emd=TEMPLATE,
            concept_emd=CONCEPT,
            direction=None,
            lip_sync_mode="off",
            lip_sync_target="サブジェクト1",
            lip_sync_audio_slot=1,
            scenes_per_batch=3,
            system_prompts=prompts(),
            runtime_config=runtime(),
        )
        self.assertTrue(result.complete)
        self.assertEqual(result.emd.schema, "MVD_EMD_V1")
        self.assertFalse(result.missing)
        self.assertIn("有効な記述2", result.emd.text)

    def test_five_tasks_render_valid_emd_and_filter_generated_dialogue(self) -> None:
        backend = FakePlannerBackend()
        result = plan_timeline(
            backend,
            template_emd=TEMPLATE,
            concept_emd=CONCEPT,
            direction=DirectionArtifact(
                style_direction=("実写映画として描写する。",),
                motion_direction=("接地を明瞭にする。",),
                camera_direction=("奥行きを保つ。",),
                camera_profile_id="anime_story_mv",
            ),
            lip_sync_mode="lyrics",
            lip_sync_target="サブジェクト1",
            lip_sync_audio_slot=1,
            scenes_per_batch=3,
            system_prompts=prompts(),
            runtime_config=runtime(),
        )
        self.assertTrue(result.complete)
        self.assertEqual(result.emd.schema, "MVD_EMD_V1")
        self.assertEqual([task for task, _ in backend.calls], [
            "visual-beats", "song-direction", "shot-layout", "actions", "cameras"
        ])
        text = result.emd.text
        self.assertNotIn("生成台詞", text)
        self.assertIn("* `リップシンク` `歌詞` `サブジェクト1` 「千年鳥居をくぐるそなたよ」", text)
        self.assertLess(text.index("サブジェクト1が重心"), text.index("Arc Shot"))
        document = parse_emd(text)
        self.assertEqual(document.scenes[0].h3_length, 243)
        self.assertEqual(document.scenes[0].shots[0].lyric_annotations[0].text, "千年鳥居をくぐるそなたよ")
        song_payload = backend.calls[1][1]
        self.assertNotIn('"lyrics"', json.dumps(song_payload, ensure_ascii=False))
        layout_payload = backend.calls[2][1]
        self.assertEqual(layout_payload["slots"][0]["candidates"][0]["id"], "B0")
        self.assertEqual(
            layout_payload["slots"][0]["lyric_groups"][0]["lyrics"][0]["text"],
            "千年鳥居をくぐるそなたよ",
        )
        camera_payload = backend.calls[4][1]
        self.assertIn("locked_action", camera_payload["slots"][0])
        self.assertTrue(camera_payload["slots"][0]["lip_sync_active"])
        self.assertEqual(
            camera_payload["slots"][0]["lip_sync_target"],
            "サブジェクト1",
        )
        self.assertIn("recent_camera_history", camera_payload)
        self.assertFalse(camera_payload["arc_required"])
        self.assertEqual(
            camera_payload["slots"][0]["face_arc_transition"],
            "arc_out_of_previous_face_cut",
        )
        self.assertEqual(
            camera_payload["camera_batch_contract"][
                "face_arc_transition_count"
            ],
            1,
        )
        self.assertTrue(camera_payload["slots"][0]["long_arc_emphasis"])
        self.assertEqual(
            camera_payload["slots"][0]["long_arc_duration_fraction"],
            "70-90%",
        )
        self.assertEqual(
            camera_payload["camera_batch_contract"]["camera_profile_id"],
            "anime_story_mv",
        )
        self.assertEqual(
            camera_payload["subject_instance_policy"],
            "single_subject_exactly_one_visible_instance",
        )
        action_payload = backend.calls[3][1]
        self.assertIn("visual_beat", action_payload["slots"][0])
        self.assertEqual(
            action_payload["slots"][0]["performance_role"],
            "expressive_hand_arm_performance",
        )
        self.assertEqual(
            camera_payload["slots"][0]["editorial_role"],
            "upper_body_performance_coverage",
        )
        self.assertEqual(result.content.actions[0][2], FACE_PERFORMANCE_CUT_ACTION)
        self.assertEqual(result.content.cameras[0][2], FACE_PERFORMANCE_CUT_CAMERA)
        self.assertIn("眉の個数、短さ、形、配置及び色", FACE_PERFORMANCE_CUT_ACTION)
        self.assertIn("通常の長い線状又は弓状眉", FACE_PERFORMANCE_CUT_ACTION)
        visual_payload = backend.calls[0][1]
        expected_roster = [
            {"concept_id": "サブジェクト1", "subject_ref": "<Subject 1>"}
        ]
        self.assertEqual(visual_payload["subject_roster"], expected_roster)
        self.assertEqual(action_payload["subject_roster"], expected_roster)
        self.assertNotIn("concept_emd", visual_payload)
        self.assertNotIn("concept_emd", action_payload)
        self.assertNotIn("長い黒髪", json.dumps(visual_payload, ensure_ascii=False))
        self.assertNotIn("長い黒髪", json.dumps(action_payload, ensure_ascii=False))
        self.assertNotIn("lip_sync_mode", action_payload)
        self.assertNotIn("lip_sync_audio_slot", action_payload)
        self.assertEqual(action_payload["primary_action_concept"], "サブジェクト1")
        self.assertEqual(
            action_payload["subject_instance_policy"],
            "single_subject_exactly_one_visible_instance",
        )
        self.assertEqual(
            action_payload["slots"][0]["previous_shot"],
            {"scene_number": 1, "shot_index": 1},
        )

    def test_anime_emotional_mv_metadata_reaches_every_planning_stage(self) -> None:
        backend = FakePlannerBackend()
        result = plan_timeline(
            backend,
            template_emd=TEMPLATE,
            concept_emd=CONCEPT,
            direction=DirectionArtifact(
                style_direction=("手描きセルアニメ。",),
                motion_direction=("感情的な身体演技。",),
                camera_direction=("長尺Arcと顔Zoomを接続する。",),
                style_profile_id="anime_emotional_mv",
                motion_profile_id="anime_emotional_mv",
                camera_profile_id="anime_emotional_mv",
            ),
            lip_sync_mode="lyrics",
            lip_sync_target="サブジェクト1",
            lip_sync_audio_slot=1,
            scenes_per_batch=3,
            system_prompts=prompts(),
            runtime_config=runtime(),
        )
        self.assertTrue(result.complete)
        self.assertNotEqual(
            result.content.actions[0][2],
            FACE_PERFORMANCE_CUT_ACTION,
        )
        self.assertEqual(
            result.content.cameras[0][2],
            ANIME_EMOTIONAL_FACE_PERFORMANCE_CUT_CAMERA,
        )
        self.assertTrue(
            result.content.cameras[1][2].startswith(
                "Arc Shot with large amplitude at fast speed."
            )
        )
        payloads = {task: payload for task, payload in backend.calls}
        for task in ("visual-beats", "shot-layout", "actions", "cameras"):
            self.assertEqual(
                payloads[task]["planner_policy_contract"]["policy_id"],
                "anime_emotional_mv",
            )
        camera_contract = payloads["cameras"]["camera_batch_contract"]
        self.assertEqual(
            payloads["cameras"]["camera_protocol_contract"]["id"],
            "finite_v1",
        )
        self.assertEqual(
            payloads["cameras"]["slots"][0]["camera_protocol"],
            "finite_v1",
        )
        self.assertLessEqual(camera_contract["face_zoom_emphasis_count"], 1)
        self.assertGreaterEqual(camera_contract["arc_shot_maximum"], 0)
        self.assertNotIn("song_direction", payloads["actions"])
        self.assertNotIn("song_direction", payloads["cameras"])
        self.assertIn("motion", payloads["actions"]["direction"])
        self.assertNotIn("camera", payloads["actions"]["direction"])
        self.assertIn("camera", payloads["cameras"]["direction"])
        self.assertNotIn("motion", payloads["cameras"]["direction"])
        self.assertIn(
            payloads["cameras"]["slots"][0]["arc_permission"],
            {"required", "forbidden"},
        )
        policy = payloads["cameras"]["planner_policy_contract"]
        self.assertEqual(
            policy["lyric_trigger_scope"],
            "current_scene_original_lyrics_only",
        )
        self.assertTrue(policy["environment_inventory_is_not_action_source"])
        self.assertEqual(
            policy["eye_expression_mode"],
            "vary_eyelids_with_lyric_phase",
        )
        self.assertEqual(
            policy["emotional_amplitude"],
            "exaggerated_readable_upper_body",
        )
        self.assertEqual(
            policy["arc_density"],
            "approximately_half_of_eligible_non_face_slots",
        )
        self.assertEqual(
            policy["noun_only_lyric_visualization"],
            "same_scene_autonomous_visual_predicate",
        )

    def test_missing_action_retries_only_affected_scene_once(self) -> None:
        backend = FakePlannerBackend(miss_action_slot_two=1)
        result = plan_timeline(
            backend,
            template_emd=TEMPLATE,
            concept_emd=CONCEPT,
            direction=None,
            lip_sync_mode="off",
            lip_sync_target="サブジェクト1",
            lip_sync_audio_slot=1,
            scenes_per_batch=3,
            system_prompts=prompts(),
            runtime_config=runtime(),
        )
        self.assertTrue(result.complete)
        self.assertEqual([task for task, _ in backend.calls].count("actions"), 2)
        self.assertEqual(result.content.retried_scenes, (1,))

    def test_missing_advisory_direction_does_not_block_completed_emd(self) -> None:
        class MissingDirectionBackend(FakePlannerBackend):
            def complete_planner(
                self,
                *,
                task,
                system_prompt,
                payload,
                config,
                interrupt_callback=None,
            ):
                if task == "song-direction":
                    value = json.loads(payload)
                    self.calls.append((task, value))
                    return ""
                return super().complete_planner(
                    task=task,
                    system_prompt=system_prompt,
                    payload=payload,
                    config=config,
                    interrupt_callback=interrupt_callback,
                )

        backend = MissingDirectionBackend()
        result = plan_timeline(
            backend,
            template_emd=TEMPLATE,
            concept_emd=CONCEPT,
            direction=None,
            lip_sync_mode="off",
            lip_sync_target="サブジェクト1",
            lip_sync_audio_slot=1,
            scenes_per_batch=3,
            system_prompts=prompts(),
            runtime_config=runtime(),
        )

        self.assertTrue(result.complete)
        self.assertFalse(result.missing)
        self.assertEqual(result.content.song_direction, "")
        self.assertTrue(result.content.song_direction_fallback)
        self.assertEqual(
            [task for task, _ in backend.calls].count("song-direction"),
            3,
        )
        self.assertGreaterEqual(result.content.issue_count, 1)

    def test_missing_camera_records_are_retried_as_is_one_slot_at_a_time(self) -> None:
        class IsolatedCameraRetryBackend(FakePlannerBackend):
            def complete_planner(
                self,
                *,
                task,
                system_prompt,
                payload,
                config,
                interrupt_callback=None,
            ):
                value = json.loads(payload)
                if task != "cameras":
                    return super().complete_planner(
                        task=task,
                        system_prompt=system_prompt,
                        payload=payload,
                        config=config,
                        interrupt_callback=interrupt_callback,
                    )
                self.calls.append((task, value))
                retry = value.get("retry")
                if retry is None:
                    return ""
                if retry == "missing_slots_only":
                    return "protocol wrapper failed"
                if retry == "camera_quality_budget":
                    slot = value["slots"][0]["slot"]
                    return (
                        f"CAMERA\t{slot}\tArc Shot with large amplitude "
                        "at fast speed で顔から全身と鳥居を開示する。"
                    )
                self.assert_single_slot(value)
                slot = value["slots"][0]["slot"]
                return f"Static Shot 顔の演技を保持する。slot{slot}"

            @staticmethod
            def assert_single_slot(value):
                if len(value["slots"]) != 1:
                    raise AssertionError("isolated retry must contain one slot")

        backend = IsolatedCameraRetryBackend()
        result = plan_timeline(
            backend,
            template_emd=TEMPLATE,
            concept_emd=CONCEPT,
            direction=None,
            lip_sync_mode="lyrics",
            lip_sync_target="サブジェクト1",
            lip_sync_audio_slot=1,
            scenes_per_batch=3,
            system_prompts=prompts(),
            runtime_config=runtime(),
        )
        self.assertTrue(result.complete)
        self.assertFalse(result.missing)
        camera_calls = [
            payload for task, payload in backend.calls if task == "cameras"
        ]
        self.assertEqual(len(camera_calls), 4)
        self.assertEqual(camera_calls[1]["retry"], "missing_slots_only")
        self.assertEqual(
            [payload["retry"] for payload in camera_calls[2:]],
            ["isolated_missing_slot", "camera_quality_budget"],
        )
        self.assertEqual(result.content.protocol_recovered_count, 1)

    def test_face_insert_is_structurally_owned_and_not_sent_to_llm(self) -> None:
        backend = FakePlannerBackend()
        result = plan_timeline(
            backend,
            template_emd=TEMPLATE,
            concept_emd=CONCEPT,
            direction=None,
            lip_sync_mode="lyrics",
            lip_sync_target="サブジェクト1",
            lip_sync_audio_slot=1,
            scenes_per_batch=3,
            system_prompts=prompts(),
            runtime_config=runtime(),
        )
        self.assertTrue(result.complete)
        self.assertEqual(result.content.actions[0][2], FACE_PERFORMANCE_CUT_ACTION)
        self.assertEqual(result.content.cameras[0][2], FACE_PERFORMANCE_CUT_CAMERA)
        action_payload = next(
            payload for task, payload in backend.calls if task == "actions"
        )
        camera_payload = next(
            payload for task, payload in backend.calls if task == "cameras"
        )
        self.assertEqual(
            [item["shot_index"] for item in action_payload["slots"]], [2]
        )
        self.assertEqual(
            [item["shot_index"] for item in camera_payload["slots"]], [2]
        )
        payload_text = json.dumps(
            [action_payload, camera_payload], ensure_ascii=False
        )
        self.assertNotIn(FACE_PERFORMANCE_CUT_ACTION, payload_text)
        self.assertNotIn(FACE_PERFORMANCE_CUT_CAMERA, payload_text)

    def test_face_insert_role_requires_first_appearance_of_section_in_cut(self) -> None:
        base = {
            "shot_index": 1,
            "scene_shot_count": 2,
            "scene_continuation": False,
            "section_entry": True,
        }
        self.assertEqual(
            _performance_role(base, lip_sync_active=True),
            "face_and_upper_body_accent",
        )
        self.assertEqual(
            _camera_editorial_role(base, lip_sync_active=True),
            "face_performance_cut",
        )

        repeated_section_cut = {**base, "section_entry": False}
        self.assertEqual(
            _performance_role(repeated_section_cut, lip_sync_active=True),
            "new_scene_physical_hook",
        )
        self.assertEqual(
            _camera_editorial_role(repeated_section_cut, lip_sync_active=True),
            "new_scene_establishing_edit",
        )

        continued_new_section = {**base, "scene_continuation": True}
        self.assertEqual(
            _performance_role(continued_new_section, lip_sync_active=True),
            "continuity_transformation",
        )
        self.assertEqual(
            _camera_editorial_role(continued_new_section, lip_sync_active=True),
            "continuity_bridge",
        )

    def test_face_insert_is_paired_with_one_same_scene_arc_transition(self) -> None:
        self.assertEqual(
            _face_arc_transitions(
                [(1, 1), (1, 2), (1, 3), (2, 1)], {(1, 1)}
            ),
            {(1, 2): "arc_out_of_previous_face_cut"},
        )
        self.assertEqual(
            _face_arc_transitions(
                [(1, 1), (1, 2), (1, 3), (2, 1)], {(1, 3)}
            ),
            {(1, 2): "arc_into_next_face_cut"},
        )

    def test_anime_story_mv_selects_one_third_spaced_long_arc_slots(self) -> None:
        entities = [
            type("Entity", (), {
                "key": (1, index + 1),
                "value": {
                    "editorial_role": "spatial_reveal_or_interaction_coverage",
                    "face_arc_transition": "",
                    "shot_duration_ms": (1000, 5000, 4000, 3000, 2000)[index],
                },
            })()
            for index in range(5)
        ]
        selected = _anime_story_mv_long_arc_keys(entities)
        self.assertEqual(selected, {(1, 2), (1, 4)})
        selected_indices = sorted(key[1] for key in selected)
        self.assertGreater(selected_indices[1] - selected_indices[0], 1)

        larger = [
            type("Entity", (), {
                "key": (2, index + 1),
                "value": {
                    "editorial_role": "spatial_reveal_or_interaction_coverage",
                    "face_arc_transition": "",
                    "shot_duration_ms": 9000 - index * 200,
                },
            })()
            for index in range(9)
        ]
        self.assertEqual(len(_anime_story_mv_long_arc_keys(larger)), 3)

    def test_anime_story_mv_face_zoom_avoids_long_arc_and_prefers_expression(self) -> None:
        entities = [
            type("Entity", (), {
                "key": (1, 1),
                "value": {
                    "editorial_role": "upper_body_performance_coverage",
                    "shot_duration_ms": 5000,
                },
            })(),
            type("Entity", (), {
                "key": (1, 2),
                "value": {
                    "editorial_role": "expressive_result_coverage",
                    "shot_duration_ms": 3000,
                },
            })(),
        ]
        self.assertEqual(
            _anime_story_mv_face_zoom_key(entities, {(1, 1)}),
            (1, 2),
        )

    def test_anime_emotional_mv_selects_balanced_arc_and_requested_face_phrases(self) -> None:
        entities = [
            type("Entity", (), {
                "scene_number": 1 + index // 3,
                "key": (1 + index // 3, 1 + index % 3),
                "value": {
                    "editorial_role": (
                        "expressive_result_coverage"
                        if index % 3 == 2
                        else "upper_body_performance_coverage"
                    ),
                    "shot_duration_ms": 3000 + index * 100,
                },
            })()
            for index in range(12)
        ]
        arc_keys, face_keys, transitions = (
            _anime_emotional_mv_camera_emphasis(entities, face_target=2)
        )
        self.assertEqual(len(arc_keys), 5)
        self.assertEqual(len(face_keys), 2)
        self.assertTrue(transitions)
        self.assertTrue(set(transitions).issubset(arc_keys))
        self.assertFalse(arc_keys & face_keys)

        _, sparse_face_keys, _ = _anime_emotional_mv_camera_emphasis(entities)
        self.assertEqual(len(sparse_face_keys), 1)

    def test_anime_emotional_mv_does_not_assign_long_arc_to_short_shot(self) -> None:
        entities = [
            type("Entity", (), {
                "scene_number": 1,
                "key": (1, index + 1),
                "value": {
                    "editorial_role": "upper_body_performance_coverage",
                    "shot_duration_ms": duration,
                },
            })()
            for index, duration in enumerate((1400, 2600, 3200, 1800))
        ]
        arc_keys, _, _ = _anime_emotional_mv_camera_emphasis(
            entities,
            face_target=0,
        )
        self.assertNotIn((1, 1), arc_keys)
        self.assertNotIn((1, 4), arc_keys)
        self.assertTrue(arc_keys.issubset({(1, 2), (1, 3)}))

    def test_long_arc_emphasis_requires_large_fast_h3_phrase(self) -> None:
        entity = type("Entity", (), {
            "key": (1, 1),
            "value": {
                "long_arc_emphasis": True,
                "lyrics": [],
                "author_body": [],
            },
        })()
        weak = _camera_budget_violations(
            [entity],
            {(1, 1): "Arc Shot with small amplitude at slow speed 正面を回る。"},
            arc_maximum=1,
        )
        self.assertIn("required_long_arc_energy", weak[(1, 1)])
        strong = _camera_budget_violations(
            [entity],
            {(1, 1): "Arc Shot with large amplitude at fast speed 側面を抜ける。"},
            arc_maximum=1,
        )
        self.assertEqual(strong, {})

    def test_camera_quality_rejects_missing_h3_type_and_speed_conflict(self) -> None:
        entities = [
            type("Entity", (), {
                "key": (1, index),
                "value": {"lyrics": [], "author_body": []},
            })()
            for index in (1, 2)
        ]
        violations = _camera_budget_violations(
            entities,
            {
                (1, 1): "頭肩構図から顔へ近づく。",
                (1, 2): "Tilt Down at fast speed ゆっくり下へ傾ける。",
            },
            arc_maximum=1,
        )
        self.assertIn("required_h3_motion_type", violations[(1, 1)])
        self.assertIn("conflicting_camera_speed", violations[(1, 2)])

    def test_camera_quality_rejects_arc_on_profile_forbidden_slot(self) -> None:
        entity = type("Entity", (), {
            "key": (1, 1),
            "value": {
                "arc_permission": "forbidden",
                "lyrics": [],
                "author_body": [],
            },
        })()
        violations = _camera_budget_violations(
            [entity],
            {(1, 1): "Arc Shot at fast speed で人物の側面へ回る。"},
            arc_maximum=1,
        )
        self.assertIn("unassigned_arc", violations[(1, 1)])

    def test_camera_quality_requires_exactly_one_boundary_safe_h3_type(self) -> None:
        entities = [
            type("Entity", (), {
                "key": (1, 1),
                "value": {"lyrics": [], "author_body": []},
            })()
        ]
        malformed = _camera_budget_violations(
            entities,
            {(1, 1): "Arc ShotTracking Shot at fast speed で人物を追う。"},
            arc_maximum=1,
        )
        self.assertIn("required_h3_motion_type", malformed[(1, 1)])
        multiple = _camera_budget_violations(
            entities,
            {(1, 1): "Arc Shot at fast speed で回り、Tracking Shotへ移る。"},
            arc_maximum=1,
        )
        self.assertIn("exactly_one_h3_motion_type", multiple[(1, 1)])

    def test_finite_camera_plan_parses_and_serializes_without_action_prose(self) -> None:
        text = (
            "MOTION=Arc Shot with large amplitude at fast speed｜"
            "START_SCALE=full_body｜END_SCALE=head_and_shoulders｜"
            "START_VIEW=low_front_three_quarter｜"
            "END_VIEW=front_three_quarter｜"
            "PATH=arc_left_60_120_70_90｜COVERAGE=face_eyes_mouth"
        )
        plan, violations = _parse_camera_plan(text)
        self.assertEqual(violations, ())
        self.assertIsNotNone(plan)
        rendered = _render_camera_plan(plan)
        self.assertTrue(
            rendered.startswith("Arc Shot with large amplitude at fast speed.")
        )
        self.assertIn("60-to-120-degree left arc", rendered)
        self.assertIn("complete singing mouth", rendered)
        self.assertNotIn("石灯籠", rendered)

    def test_finite_camera_plan_rejects_short_arc_and_path_mismatch(self) -> None:
        plan, violations = _parse_camera_plan(
            "MOTION=Arc Shot with large amplitude at fast speed｜"
            "START_SCALE=full_body｜END_SCALE=medium｜"
            "START_VIEW=front｜END_VIEW=side｜PATH=push_in｜"
            "COVERAGE=whole_body_emotion"
        )
        self.assertEqual(violations, ())
        entity = _Entity(
            1,
            (1, 1),
            {
                "shot_duration_ms": 1800,
                "arc_permission": "forbidden",
            },
        )
        contract = _camera_plan_contract_violations(entity, plan)
        self.assertIn("camera_plan_motion_path_mismatch", contract)
        self.assertIn("camera_plan_short_arc", contract)
        self.assertIn("unassigned_arc", contract)

    def test_anime_emotional_mv_boundary_contract_allows_long_continue_run(self) -> None:
        scenes = tuple(
            Scene(
                scene_number=index,
                start_ms=(index - 1) * 2000,
                end_ms=index * 2000,
                h3_length=56,
                descriptions=(),
                shots=(),
                audio_directives=(),
                line_number=index,
                continuation=False,
            )
            for index in range(1, 9)
        )
        template = PlannerTemplate(scenes)
        all_continue = {1: False, **{index: True for index in range(2, 9)}}
        self.assertTrue(
            _satisfies_boundary_contract(
                template,
                all_continue,
                planner_policy="anime_emotional_mv",
            )
        )
        repaired, _ = _repair_boundary_contract(
            template,
            {index: False for index in range(1, 9)},
            planner_policy="anime_emotional_mv",
        )
        self.assertGreaterEqual(
            sum(repaired[index] for index in range(2, 9)),
            6,
        )

    def test_face_insert_moves_to_shot_that_contains_new_section_lyric(self) -> None:
        backend = FakePlannerBackend()
        result = plan_timeline(
            backend,
            template_emd=LATE_SECTION_TEMPLATE,
            concept_emd=CONCEPT,
            direction=None,
            lip_sync_mode="lyrics",
            lip_sync_target="サブジェクト1",
            lip_sync_audio_slot=1,
            scenes_per_batch=3,
            system_prompts=prompts(),
            runtime_config=runtime(),
        )
        self.assertTrue(result.complete)
        self.assertEqual(
            [(scene, shot) for scene, shot, text in result.content.actions
             if text == FACE_PERFORMANCE_CUT_ACTION],
            [(1, 3)],
        )
        self.assertEqual(
            [(scene, shot) for scene, shot, text in result.content.cameras
             if text == FACE_PERFORMANCE_CUT_CAMERA],
            [(1, 3)],
        )

    def test_unrequested_foot_camera_is_retried_without_rewriting(self) -> None:
        class FootCameraBackend(FakePlannerBackend):
            def complete_planner(
                self,
                *,
                task,
                system_prompt,
                payload,
                config,
                interrupt_callback=None,
            ):
                value = json.loads(payload)
                if task != "cameras":
                    return super().complete_planner(
                        task=task,
                        system_prompt=system_prompt,
                        payload=payload,
                        config=config,
                        interrupt_callback=interrupt_callback,
                    )
                self.calls.append((task, value))
                if value.get("retry") == "camera_quality_budget":
                    return "CAMERA\t1\tStatic Shot 正面から顔と両手の演技を捉える。"
                return (
                    "CAMERA\t1\tTracking Shot at slow speed "
                    "人物の足元と履物だけを追う。"
                )

        backend = FootCameraBackend()
        result = plan_timeline(
            backend,
            template_emd=TEMPLATE,
            concept_emd=CONCEPT,
            direction=None,
            lip_sync_mode="lyrics",
            lip_sync_target="サブジェクト1",
            lip_sync_audio_slot=1,
            scenes_per_batch=3,
            system_prompts=prompts(),
            runtime_config=runtime(),
        )
        self.assertTrue(result.complete)
        camera_calls = [
            payload for task, payload in backend.calls if task == "cameras"
        ]
        self.assertEqual(len(camera_calls), 2)
        self.assertEqual(camera_calls[1]["retry"], "camera_quality_budget")
        self.assertIn(
            "Static Shot 正面から顔と両手の演技を捉える。",
            [text for _scene, _shot, text in result.content.cameras],
        )

    def test_generic_hand_action_is_retried_without_rewriting(self) -> None:
        class GenericHandBackend(FakePlannerBackend):
            def complete_planner(
                self,
                *,
                task,
                system_prompt,
                payload,
                config,
                interrupt_callback=None,
            ):
                value = json.loads(payload)
                if task != "actions":
                    return super().complete_planner(
                        task=task,
                        system_prompt=system_prompt,
                        payload=payload,
                        config=config,
                        interrupt_callback=interrupt_callback,
                    )
                self.calls.append((task, value))
                if value.get("retry") == "action_quality_budget":
                    return "ACTION\t1\t主人公は鳥居へ身体を返し、肩越しに見据えて袖を払う。"
                return "\n".join(
                    (
                        f"ACTION\t{item['slot']}\t主人公は両手を上げる。"
                        if index == 0
                        else f"ACTION\t{item['slot']}\t主人公は身を翻して鳥居へ踏み込む。{index}"
                    )
                    for index, item in enumerate(value["slots"])
                )

        backend = GenericHandBackend()
        result = plan_timeline(
            backend,
            template_emd=TEMPLATE,
            concept_emd=CONCEPT,
            direction=None,
            lip_sync_mode="off",
            lip_sync_target="サブジェクト1",
            lip_sync_audio_slot=1,
            scenes_per_batch=3,
            system_prompts=prompts(),
            runtime_config=runtime(),
        )
        self.assertTrue(result.complete)
        action_calls = [
            payload for task, payload in backend.calls if task == "actions"
        ]
        self.assertEqual(len(action_calls), 2)
        self.assertEqual(action_calls[1]["retry"], "action_quality_budget")
        self.assertEqual(
            action_calls[1]["slots"][0]["action_quality_violations"],
            ["generic_hand_raise_or_lower"],
        )
        self.assertIn(
            "主人公は鳥居へ身体を返し、肩越しに見据えて袖を払う。",
            [text for _scene, _shot, text in result.content.actions],
        )

    def test_anime_emotional_camera_quality_exhaustion_is_advisory(self) -> None:
        class PersistentCameraQualityBackend(FakePlannerBackend):
            def complete_planner(
                self,
                *,
                task,
                system_prompt,
                payload,
                config,
                interrupt_callback=None,
            ):
                value = json.loads(payload)
                if task == "cameras":
                    self.calls.append((task, value))
                    return "\n".join(
                        f"CAMERA\t{item['slot']}\t"
                        f"Static Shot 正面の構図を保持する。{item['slot']}"
                        for item in value["slots"]
                    )
                return super().complete_planner(
                    task=task,
                    system_prompt=system_prompt,
                    payload=payload,
                    config=config,
                    interrupt_callback=interrupt_callback,
                )

        backend = PersistentCameraQualityBackend()
        result = plan_timeline(
            backend,
            template_emd=TEMPLATE,
            concept_emd=CONCEPT,
            direction=DirectionArtifact(camera_profile_id="anime_emotional_mv"),
            lip_sync_mode="off",
            lip_sync_target="サブジェクト1",
            lip_sync_audio_slot=1,
            scenes_per_batch=3,
            system_prompts=prompts(),
            runtime_config=runtime(),
        )
        self.assertTrue(result.complete)
        self.assertEqual(result.missing, ())
        self.assertIsNotNone(result.content)
        self.assertGreater(result.content.camera_repetition_warning_count, 0)
        camera_calls = [
            payload for task, payload in backend.calls if task == "cameras"
        ]
        self.assertTrue(
            any(
                payload.get("retry") == "camera_quality_budget"
                for payload in camera_calls
            )
        )
        camera_texts = [
            text for _scene, _shot, text in result.content.cameras
        ]
        self.assertTrue(all("Start with " in text for text in camera_texts))
        self.assertTrue(all("正面の構図" not in text for text in camera_texts))

    def test_anime_emotional_action_audit_retries_only_rejected_slots(self) -> None:
        class SemanticAuditBackend(FakePlannerBackend):
            def complete_planner(
                self,
                *,
                task,
                system_prompt,
                payload,
                config,
                interrupt_callback=None,
            ):
                value = json.loads(payload)
                if task == "action-audit":
                    self.calls.append((task, value))
                    return "\n".join(
                        f"AUDIT\t{item['slot']}\t"
                        + (
                            "PASS"
                            if "肩越し" in item["candidate_action"]
                            or item["shot_index"] != 1
                            else "REJECT:REFERENCE_POSE,SEMANTIC_REPETITION"
                        )
                        for item in value["slots"]
                    )
                if (
                    task == "actions"
                    and value.get("retry") == "action_quality_budget"
                ):
                    self.calls.append((task, value))
                    return "\n".join(
                        f"ACTION\t{item['slot']}\t"
                        + _grounded_fixture_action(
                            item,
                            "主人公は千年鳥居を見据え、身体を引いて静止する。",
                        )
                        for item in value["slots"]
                    )
                if (
                    task == "actions"
                    and value.get("retry") == "semantic_audit_rejected_slots"
                ):
                    self.calls.append((task, value))
                    return "\n".join(
                        f"ACTION\t{item['slot']}\t"
                        + _grounded_fixture_action(
                            item,
                            "主人公は肩越しに振り返り、袖を引いて鋭く静止する。",
                        )
                        for item in value["slots"]
                    )
                return super().complete_planner(
                    task=task,
                    system_prompt=system_prompt,
                    payload=payload,
                    config=config,
                    interrupt_callback=interrupt_callback,
                )

        backend = SemanticAuditBackend()
        result = plan_timeline(
            backend,
            template_emd=TEMPLATE,
            concept_emd=CONCEPT,
            direction=DirectionArtifact(camera_profile_id="anime_emotional_mv"),
            lip_sync_mode="off",
            lip_sync_target="サブジェクト1",
            lip_sync_audio_slot=1,
            scenes_per_batch=3,
            system_prompts=prompts(),
            runtime_config=runtime(),
        )
        self.assertTrue(result.complete)
        audit_calls = [payload for task, payload in backend.calls if task == "action-audit"]
        self.assertEqual(len(audit_calls), 2)
        self.assertIn(
            "REJECT:MISSING_GROUNDED_CUE",
            audit_calls[0]["audit_contract"]["verdicts"],
        )
        self.assertIn(
            "REJECT:FACE_PERFORMANCE_MISSING",
            audit_calls[0]["audit_contract"]["verdicts"],
        )
        repair_calls = [
            payload
            for task, payload in backend.calls
            if task == "actions"
            and payload.get("retry") == "semantic_audit_rejected_slots"
        ]
        self.assertEqual(len(repair_calls), 1)
        self.assertEqual(len(repair_calls[0]["slots"]), 1)
        self.assertEqual(
            repair_calls[0]["slots"][0]["semantic_audit_reasons"],
            ["REFERENCE_POSE", "SEMANTIC_REPETITION"],
        )

    def test_anime_emotional_action_audit_exhaustion_retains_best_candidate(self) -> None:
        class RejectingAuditBackend(FakePlannerBackend):
            def complete_planner(
                self,
                *,
                task,
                system_prompt,
                payload,
                config,
                interrupt_callback=None,
            ):
                value = json.loads(payload)
                if task == "action-audit":
                    self.calls.append((task, value))
                    return "\n".join(
                        f"AUDIT\t{item['slot']}\tREJECT:PROFILE_CONFLICT"
                        for item in value["slots"]
                    )
                if (
                    task == "actions"
                    and value.get("retry") == "semantic_audit_rejected_slots"
                ):
                    self.calls.append((task, value))
                    return "\n".join(
                        f"ACTION\t{item['slot']}\t"
                        + _grounded_fixture_action(
                            item,
                            f"人物は両腕を広げて前傾する。{item['slot']}",
                        )
                        for item in value["slots"]
                    )
                return super().complete_planner(
                    task=task,
                    system_prompt=system_prompt,
                    payload=payload,
                    config=config,
                    interrupt_callback=interrupt_callback,
                )

        backend = RejectingAuditBackend()
        result = plan_timeline(
            backend,
            template_emd=TEMPLATE,
            concept_emd=CONCEPT,
            direction=DirectionArtifact(camera_profile_id="anime_emotional_mv"),
            lip_sync_mode="off",
            lip_sync_target="サブジェクト1",
            lip_sync_audio_slot=1,
            scenes_per_batch=3,
            system_prompts=prompts(),
            runtime_config=runtime(),
        )
        self.assertTrue(result.complete)
        self.assertEqual(result.missing, ())
        self.assertIsNotNone(result.content)
        self.assertGreater(result.content.action_repetition_warning_count, 0)
        self.assertEqual(
            len([payload for task, payload in backend.calls if task == "action-audit"]),
            2,
        )
        self.assertEqual(
            len(
                [
                    payload
                    for task, payload in backend.calls
                    if task == "actions"
                    and payload.get("retry") == "semantic_audit_rejected_slots"
                ]
            ),
            1,
        )
        self.assertIn("cameras", [task for task, _payload in backend.calls])

    def test_anime_emotional_quality_failure_reaches_audit_repair(self) -> None:
        class PersistentQualityBackend(FakePlannerBackend):
            def complete_planner(
                self,
                *,
                task,
                system_prompt,
                payload,
                config,
                interrupt_callback=None,
            ):
                value = json.loads(payload)
                if task == "action-audit":
                    self.calls.append((task, value))
                    return "\n".join(
                        f"AUDIT\t{item['slot']}\tPASS"
                        for item in value["slots"]
                    )
                if task == "actions":
                    self.calls.append((task, value))
                    if value.get("retry") == "semantic_audit_rejected_slots":
                        return "\n".join(
                            f"ACTION\t{item['slot']}\t"
                            + _grounded_fixture_action(
                                item,
                                "主人公は肩越しに振り返り、袖を鋭く払って静止する。",
                            )
                            for item in value["slots"]
                        )
                    if value.get("retry") == "action_quality_budget":
                        return "\n".join(
                            f"ACTION\t{item['slot']}\t"
                            + _grounded_fixture_action(
                                item, "主人公は両手を上げる。"
                            )
                            for item in value["slots"]
                        )
                    return "\n".join(
                        (
                            f"ACTION\t{item['slot']}\t"
                            + _grounded_fixture_action(
                                item, "主人公は両手を上げる。"
                            )
                            if index == 0
                            else f"ACTION\t{item['slot']}\t"
                            + _grounded_fixture_action(
                                item,
                                f"主人公は肩を返して視線を切り替える。{index}",
                            )
                        )
                        for index, item in enumerate(value["slots"])
                    )
                return super().complete_planner(
                    task=task,
                    system_prompt=system_prompt,
                    payload=payload,
                    config=config,
                    interrupt_callback=interrupt_callback,
                )

        backend = PersistentQualityBackend()
        result = plan_timeline(
            backend,
            template_emd=TEMPLATE,
            concept_emd=CONCEPT,
            direction=DirectionArtifact(camera_profile_id="anime_emotional_mv"),
            lip_sync_mode="off",
            lip_sync_target="サブジェクト1",
            lip_sync_audio_slot=1,
            scenes_per_batch=3,
            system_prompts=prompts(),
            runtime_config=runtime(),
        )
        self.assertTrue(result.complete)
        self.assertGreaterEqual(
            len([payload for task, payload in backend.calls if task == "action-audit"]),
            2,
        )
        repair_calls = [
            payload
            for task, payload in backend.calls
            if task == "actions"
            and payload.get("retry") == "semantic_audit_rejected_slots"
        ]
        self.assertEqual(len(repair_calls), 1)
        self.assertEqual(
            repair_calls[0]["slots"][0]["action_quality_violations"],
            ["generic_hand_raise_or_lower"],
        )
        self.assertEqual(
            repair_calls[0]["slots"][0]["semantic_audit_reasons"],
            [],
        )

    def test_action_audit_prompt_is_finite_and_does_not_rewrite(self) -> None:
        prompt = (
            Path(__file__).parents[1]
            / "prompts"
            / "timeline_planner_action_audit_system_prompt.txt"
        ).read_text(encoding="utf-8")
        self.assertIn("classification only", prompt)
        self.assertIn("Never rewrite", prompt)
        self.assertIn("SEMANTIC_REPETITION", prompt)
        self.assertIn("INCIDENTAL_FIXTURE", prompt)
        self.assertIn("UNREQUESTED_LOWER_BODY", prompt)
        self.assertIn("REFERENCE_POSE", prompt)
        self.assertIn("MISSING_GROUNDED_CUE", prompt)
        self.assertIn("FACE_PERFORMANCE_MISSING", prompt)

    def test_unrequested_running_is_retried_without_rewriting(self) -> None:
        class RunningBackend(FakePlannerBackend):
            def complete_planner(
                self,
                *,
                task,
                system_prompt,
                payload,
                config,
                interrupt_callback=None,
            ):
                value = json.loads(payload)
                if task != "actions":
                    return super().complete_planner(
                        task=task,
                        system_prompt=system_prompt,
                        payload=payload,
                        config=config,
                        interrupt_callback=interrupt_callback,
                    )
                self.calls.append((task, value))
                if value.get("retry") == "action_quality_budget":
                    return (
                        "ACTION\t1\t主人公は上体を反転し、肩越しに鳥居を見据えて静止する。"
                    )
                return "\n".join(
                    (
                        f"ACTION\t{item['slot']}\t主人公は参道を全力で走り抜ける。"
                        if index == 0
                        else f"ACTION\t{item['slot']}\t主人公は鳥居へ向き直る。{index}"
                    )
                    for index, item in enumerate(value["slots"])
                )

        backend = RunningBackend()
        result = plan_timeline(
            backend,
            template_emd=TEMPLATE,
            concept_emd=CONCEPT,
            direction=None,
            lip_sync_mode="off",
            lip_sync_target="サブジェクト1",
            lip_sync_audio_slot=1,
            scenes_per_batch=3,
            system_prompts=prompts(),
            runtime_config=runtime(),
        )
        self.assertTrue(result.complete)
        action_calls = [
            payload for task, payload in backend.calls if task == "actions"
        ]
        self.assertEqual(action_calls[1]["retry"], "action_quality_budget")
        self.assertEqual(
            action_calls[1]["slots"][0]["action_quality_violations"],
            ["unrequested_running"],
        )
        self.assertNotIn(
            "走り抜ける",
            " ".join(text for _scene, _shot, text in result.content.actions),
        )

    def test_repeated_action_is_retried_as_is_for_only_affected_scene(self) -> None:
        repeated = (
            "主人公は鳥居の前で両手を広げたまま正面を向き、"
            "同じ姿勢を保ってその場に立ち続ける。"
        )

        class RepetitionBackend(FakePlannerBackend):
            def complete_planner(
                self,
                *,
                task,
                system_prompt,
                payload,
                config,
                interrupt_callback=None,
            ):
                value = json.loads(payload)
                if task != "actions":
                    return super().complete_planner(
                        task=task,
                        system_prompt=system_prompt,
                        payload=payload,
                        config=config,
                        interrupt_callback=interrupt_callback,
                    )
                self.calls.append((task, value))
                if "diversity_retry" in value:
                    return (
                        "ACTION\t1\t主人公は鳥居へ背を向けて踏み出し、"
                        "肩越しに振り返って片手を狐火へ伸ばす。"
                    )
                return "\n".join(
                    f"ACTION\t{item['slot']}\t{repeated}"
                    for item in value["slots"]
                )

        backend = RepetitionBackend()
        result = plan_timeline(
            backend,
            template_emd=TEMPLATE,
            concept_emd=CONCEPT,
            direction=None,
            lip_sync_mode="off",
            lip_sync_target="サブジェクト1",
            lip_sync_audio_slot=1,
            scenes_per_batch=3,
            system_prompts=prompts(),
            runtime_config=runtime(),
        )
        self.assertTrue(result.complete)
        action_calls = [
            payload for task, payload in backend.calls if task == "actions"
        ]
        self.assertEqual(len(action_calls), 2)
        self.assertNotIn("diversity_retry", action_calls[0])
        self.assertIn("diversity_retry", action_calls[1])
        self.assertEqual(len(action_calls[1]["slots"]), 1)
        self.assertEqual(action_calls[1]["slots"][0]["rejected_output"], repeated)
        self.assertIn(repeated, action_calls[1]["forbidden_recent_outputs"])
        actions = [text for _scene, _shot, text in result.content.actions]
        self.assertEqual(actions[0], repeated)
        self.assertIn("肩越しに振り返って", actions[1])
        self.assertEqual(result.content.retried_scenes, (1,))
        self.assertEqual(result.content.repetition_warning_count, 0)
        self.assertEqual(result.content.action_repetition_warning_count, 0)

    def test_repetition_after_quality_retry_is_warning_not_blocker(self) -> None:
        repeated = (
            "主人公は鳥居の前で両手を広げたまま正面を向き、"
            "同じ姿勢を保ってその場に立ち続ける。"
        )

        class PersistentRepetitionBackend(FakePlannerBackend):
            def complete_planner(
                self,
                *,
                task,
                system_prompt,
                payload,
                config,
                interrupt_callback=None,
            ):
                value = json.loads(payload)
                if task != "actions":
                    return super().complete_planner(
                        task=task,
                        system_prompt=system_prompt,
                        payload=payload,
                        config=config,
                        interrupt_callback=interrupt_callback,
                    )
                self.calls.append((task, value))
                return "\n".join(
                    f"ACTION\t{item['slot']}\t{repeated}"
                    for item in value["slots"]
                )

        result = plan_timeline(
            PersistentRepetitionBackend(),
            template_emd=TEMPLATE,
            concept_emd=CONCEPT,
            direction=None,
            lip_sync_mode="off",
            lip_sync_target="サブジェクト1",
            lip_sync_audio_slot=1,
            scenes_per_batch=3,
            system_prompts=prompts(),
            runtime_config=runtime(),
        )
        self.assertTrue(result.complete)
        self.assertFalse(result.missing)
        self.assertEqual(result.content.repetition_warning_count, 1)
        self.assertEqual(result.content.beat_repetition_warning_count, 0)
        self.assertEqual(result.content.action_repetition_warning_count, 1)
        self.assertEqual(result.content.camera_repetition_warning_count, 0)
        self.assertEqual(
            [text for _scene, _shot, text in result.content.actions],
            [repeated, repeated],
        )

    def test_later_batches_receive_recent_history_and_timeline_position(self) -> None:
        backend = FakePlannerBackend()
        result = plan_timeline(
            backend,
            template_emd=TEMPLATE + INSTRUMENTAL_TAIL,
            concept_emd=CONCEPT,
            direction=None,
            lip_sync_mode="off",
            lip_sync_target="サブジェクト1",
            lip_sync_audio_slot=1,
            scenes_per_batch=1,
            system_prompts=prompts(),
            runtime_config=runtime(),
        )
        self.assertTrue(result.complete)

        visual_calls = [
            payload
            for task, payload in backend.calls
            if task == "visual-beats" and "retry" not in payload
        ]
        self.assertEqual(len(visual_calls), 2)
        self.assertEqual(
            visual_calls[0]["slots"][0]["timeline_position"],
            "opening",
        )
        self.assertTrue(
            visual_calls[0]["slots"][0]["has_resolved_lyrics"]
        )
        self.assertEqual(
            visual_calls[1]["slots"][0]["timeline_position"],
            "closing",
        )
        self.assertFalse(
            visual_calls[1]["slots"][0]["has_resolved_lyrics"]
        )
        self.assertEqual(
            visual_calls[1]["recent_visual_beat_history"],
            [
                "感情=決意｜根拠=千年鳥居｜対象=千年鳥居｜接触=禁止｜"
                "現象=なし｜配置=参道奥の鳥居｜"
                "可視展開=鳥居の輪郭が夜空に浮かぶ｜身体主導=胸郭と肩の反転｜終端=鳥居へ正対して静止"
            ],
        )

        action_calls = [
            payload for task, payload in backend.calls if task == "actions"
        ]
        self.assertEqual(len(action_calls), 2)
        self.assertEqual(len(action_calls[1]["recent_action_history"]), 2)
        final_action = action_calls[1]["slots"][0]
        self.assertEqual(final_action["scene_shot_count"], 1)
        self.assertEqual(final_action["shot_end_ms"], 12250)
        self.assertEqual(final_action["shot_duration_ms"], 2125)

        camera_calls = [
            payload
            for task, payload in backend.calls
            if task == "cameras" and "retry" not in payload
        ]
        self.assertEqual(len(camera_calls), 2)
        self.assertEqual(len(camera_calls[1]["recent_camera_history"]), 2)

    def test_camera_profile_is_routed_only_to_camera_stage(self) -> None:
        direction = DirectionArtifact(
            style_direction=("style constraint",),
            environment_direction=("environment constraint",),
            time_lighting_direction=("time lighting constraint",),
            motion_direction=("motion constraint",),
            camera_direction=("camera constraint",),
            other_direction=("other constraint",),
        )
        backend = FakePlannerBackend()
        result = plan_timeline(
            backend,
            template_emd=TEMPLATE,
            concept_emd=CONCEPT,
            scene_emd=(
                "# シーン設定\n## 環境\n* 石灯籠の並ぶ参道\n"
                "## 時間・照明\n* 夜間\n## 背景参照\n* `画像2`\n"
            ),
            direction=direction,
            lip_sync_mode="off",
            lip_sync_target="サブジェクト1",
            lip_sync_audio_slot=1,
            scenes_per_batch=3,
            system_prompts=prompts(),
            runtime_config=runtime(),
        )
        self.assertTrue(result.complete)
        expected = {
            "style": ["style constraint"],
            "environment": ["environment constraint"],
            "time_lighting": ["time lighting constraint"],
            "motion": ["motion constraint"],
            "camera": ["camera constraint"],
            "other": ["other constraint"],
        }
        performance_expected = dict(expected)
        performance_expected.pop("camera")
        performance_expected.pop("environment")
        for task in ("visual-beats", "actions"):
            payloads = [
                payload for called_task, payload in backend.calls
                if called_task == task
            ]
            self.assertTrue(payloads)
            for payload in payloads:
                self.assertEqual(payload["direction"], performance_expected)
                if task == "visual-beats":
                    self.assertIn("scene_context", payload)
                    self.assertEqual(
                        payload["scene_context_usage"],
                        "spatial_support_only_never_activates_an_action_target",
                    )
                else:
                    self.assertNotIn("scene_context", payload)
        camera_payloads = [
            payload for called_task, payload in backend.calls
            if called_task == "cameras"
        ]
        self.assertTrue(camera_payloads)
        camera_expected = dict(expected)
        camera_expected.pop("motion")
        camera_expected.pop("environment")
        for payload in camera_payloads:
            self.assertEqual(payload["direction"], camera_expected)
            self.assertNotIn("scene_context", payload)
        self.assertIn("石灯籠の並ぶ参道", result.emd.text)
        self.assertIn("`画像2`", result.emd.text)

    def test_action_audit_accepts_grounding_and_face_reason_codes(self) -> None:
        entities = [
            _Entity(1, (1, 1), {}),
            _Entity(1, (1, 2), {}),
        ]
        failures = _action_audit_failures(
            entities,
            {
                (1, 1): "REJECT:MISSING_GROUNDED_CUE",
                (1, 2): "REJECT:FACE_PERFORMANCE_MISSING",
            },
        )
        self.assertEqual(failures[(1, 1)], ("MISSING_GROUNDED_CUE",))
        self.assertEqual(failures[(1, 2)], ("FACE_PERFORMANCE_MISSING",))
    def test_action_audit_accepts_v48_reason_codes(self) -> None:
        entities = [
            _Entity(1, (1, 1), {}),
            _Entity(1, (1, 2), {}),
        ]
        failures = _action_audit_failures(
            entities,
            {
                (1, 1): "REJECT:BODY_TEMPLATE_REPETITION",
                (1, 2): "REJECT:INTERNAL_PROTOCOL_LABEL",
            },
        )
        self.assertEqual(failures[(1, 1)], ("BODY_TEMPLATE_REPETITION",))
        self.assertEqual(failures[(1, 2)], ("INTERNAL_PROTOCOL_LABEL",))

    def test_action_quality_rejects_composite_generic_hand_motion(self) -> None:
        entity = _Entity(
            1,
            (1, 1),
            {
                "lyrics": [],
                "author_body": [],
                "performance_role": "expressive_hand_arm_performance",
            },
        )
        violations = _action_budget_violations(
            [entity],
            {
                (1, 1): (
                    "右手を胸の前で急いで上げ、その動きに合わせて頭部を"
                    "右へ向け、胸郭を大きく傾ける。"
                )
            },
        )
        self.assertIn("generic_hand_raise_or_lower", violations[(1, 1)])
    def test_action_quality_rejects_internal_protocol_label(self) -> None:
        entity = _Entity(
            12,
            (12, 3),
            {
                "lyrics": [],
                "author_body": [],
                "performance_role": "expressive_resolution",
            },
        )
        violations = _action_budget_violations(
            [entity],
            {(12, 3): "胸郭を左へ向け、ACTION 14 視線を上げる。"},
        )
        self.assertIn(
            "internal_protocol_label", violations[(12, 3)]
        )
        for malformed in (
            "1 胸郭を左へ向け、視線を上げる。",
            "タブ　胸郭を左へ向け、視線を上げる。",
            "TAB 胸郭を左へ向け、視線を上げる。",
            "ACTION 14 1 胸郭を左へ向け、視線を上げる。",
        ):
            with self.subTest(malformed=malformed):
                prefixed = _action_budget_violations(
                    [entity], {(12, 3): malformed}
                )
                self.assertIn(
                    "internal_protocol_label", prefixed[(12, 3)]
                )

    def test_grounding_transfer_requires_exact_anchor_then_development(self) -> None:
        grounding = {
            "valid": True,
            "target": "苔",
            "spatial_anchor": "大樹の根元",
            "visible_development": "苔が湿った樹皮を覆う",
        }
        entities = _with_grounding_transfer_requirements(
            [
                _Entity(
                    3,
                    (3, 1),
                    {
                        "visual_beat_grounding": grounding,
                        "priority_lyric_cues": [
                            {"token": "苔", "kind": "object"}
                        ],
                    },
                ),
                _Entity(
                    3,
                    (3, 2),
                    {
                        "visual_beat_grounding": grounding,
                        "priority_lyric_cues": [
                            {"token": "苔", "kind": "object"}
                        ],
                    },
                ),
                _Entity(
                    3,
                    (3, 3),
                    {
                        "visual_beat_grounding": grounding,
                        "priority_lyric_cues": [
                            {"token": "苔", "kind": "object"}
                        ],
                    },
                ),
            ]
        )
        self.assertEqual(
            entities[0].value["required_spatial_anchor"], "大樹の根元"
        )
        self.assertNotIn("required_visible_development", entities[0].value)
        self.assertEqual(
            entities[1].value["required_visible_development"],
            "苔が湿った樹皮を覆う",
        )
        self.assertNotIn("required_spatial_anchor", entities[2].value)

        violations = _action_budget_violations(
            entities,
            {
                (3, 1): "苔へ視線を落とし、身体を向ける。",
                (3, 2): "苔を見つめ、肩を引く。",
                (3, 3): "視線を上げて静止する。",
            },
        )
        self.assertIn("missing_spatial_anchor", violations[(3, 1)])
        self.assertIn("missing_visible_development", violations[(3, 2)])
        transferred = _action_budget_violations(
            entities,
            {
                (3, 1): "大樹の根元へ視線を落とし、身体を向ける。",
                (3, 2): "苔が湿った樹皮を覆う様子に肩を引く。",
                (3, 3): "視線を上げて静止する。",
            },
        )
        self.assertNotIn("missing_spatial_anchor", transferred.get((3, 1), ()))
        self.assertNotIn(
            "missing_visible_development", transferred.get((3, 2), ())
        )

    def test_action_quality_requires_valid_grounded_target(self) -> None:
        entity = _Entity(
            3,
            (3, 1),
            {
                "lyrics": [{"section": "VERSE", "text": "苔へと還る"}],
                "author_body": [],
                "performance_role": "environment_interaction_or_body_turn",
                "grounded_cue_required": True,
                "visual_beat_grounding": {
                    "valid": True,
                    "target": "苔",
                    "contact": "禁止",
                    "phenomenon": "なし",
                },
            },
        )
        missing = _action_budget_violations(
            [entity],
            {(3, 1): "肩越しに振り返り、胸郭をひねって静止する。"},
        )
        self.assertIn("missing_grounded_cue_target", missing[(3, 1)])
        grounded = _action_budget_violations(
            [entity],
            {(3, 1): "苔へ視線を落とし、触れずに身体を引いて静止する。"},
        )
        self.assertNotIn((3, 1), grounded)

    def test_priority_lyric_cues_are_exact_current_scene_matches(self) -> None:
        selected = _priority_lyric_cues_from_sources(
            [
                {"section": "VERSE", "text": "苔へと還る"},
                {"section": "VERSE", "text": "狐火へ問う"},
            ],
            [],
            (
                ("苔", "object"),
                ("花", "symbolic_motif"),
                ("狐火", "external_effect"),
            ),
        )
        self.assertEqual(
            selected,
            (
                {"token": "苔", "kind": "object", "evidence": "苔へと還る"},
                {
                    "token": "狐火",
                    "kind": "external_effect",
                    "evidence": "狐火へ問う",
                },
            ),
        )
        self.assertNotIn("花", {item["token"] for item in selected})

    def test_priority_scene_batches_isolate_only_cue_scenes(self) -> None:
        template = parse_template_emd(TEMPLATE + INSTRUMENTAL_TAIL)
        batches = list(
            _scene_batches_with_isolated_priority_cues(
                list(template.scenes),
                {
                    1: (),
                    2: (
                        {
                            "token": "苔",
                            "kind": "object",
                            "evidence": "苔へと還る",
                        },
                    ),
                },
                3,
            )
        )
        self.assertEqual(
            [[scene.scene_number for scene in batch] for batch in batches],
            [[1], [2]],
        )

    def test_priority_scope_detects_only_disallowed_profile_tokens(self) -> None:
        configured = (
            ("苔", "object"),
            ("花", "symbolic_motif"),
            ("狐火", "external_effect"),
        )
        allowed = [
            {"token": "花", "kind": "symbolic_motif", "evidence": "人は花より"}
        ]
        self.assertEqual(
            _unexpected_priority_cues(
                "苔へ視線を落とし、花が散る様子を見送る。",
                allowed,
                configured,
            ),
            ("苔",),
        )

    def test_action_quality_rejects_priority_cue_outside_scene(self) -> None:
        entity = _Entity(
            1,
            (1, 1),
            {
                "lyrics": [{"section": "INTRO", "text": "遠い鈴の音"}],
                "author_body": [],
                "priority_lyric_cues": [],
                "performance_role": "lyric_driven_full_body_performance",
            },
        )
        violations = _action_budget_violations(
            [entity],
            {(1, 1): "苔へ視線を落とし、身体を引いて静止する。"},
            configured_priority_cues=(("苔", "object"),),
        )
        self.assertIn("unexpected_priority_cue", violations[(1, 1)])

    def test_priority_external_effect_requires_autonomous_cue_card(self) -> None:
        entity = _Entity(
            9,
            (9,),
            {
                "lyrics": [{"section": "CHORUS", "text": "狐火へ問う"}],
                "author_body": [],
            },
        )
        autonomous = _parse_cue_card(
            entity,
            "感情=畏れ｜根拠=狐火へ問う｜対象=狐火｜接触=禁止｜"
            "現象=外部自律｜配置=人物前方から頭上を経て参道奥｜"
            "可視展開=狐火が宙を弧状に舞い石畳へ光を落とす｜"
            "身体主導=視線と後退｜終端=火を見送る",
        )
        self.assertEqual(
            _priority_cue_card_violations(
                autonomous,
                {"token": "狐火", "kind": "external_effect"},
            ),
            (),
        )
        handheld = _parse_cue_card(
            entity,
            "感情=畏れ｜根拠=狐火へ問う｜対象=狐火｜接触=許可｜"
            "現象=身体操作｜配置=手の中｜"
            "可視展開=狐火を掲げる｜身体主導=手で持つ｜"
            "終端=火を掲げる",
        )
        violations = _priority_cue_card_violations(
            handheld,
            {"token": "狐火", "kind": "external_effect"},
        )
        self.assertIn("priority_effect_not_autonomous", violations)
        self.assertIn("priority_effect_contact_not_forbidden", violations)

    def test_priority_target_is_required_even_when_cue_card_is_invalid(self) -> None:
        entities = [
            _Entity(
                4,
                (4, slot),
                {
                    "lyrics": [
                        {"section": "VERSE", "text": "人は花より短く咲いて"}
                    ],
                    "author_body": [],
                    "performance_role": (
                        "environment_interaction_or_body_turn"
                        if slot == 1
                        else "expressive_resolution"
                    ),
                    "grounded_cue_required": True,
                    "visual_beat_grounding": {"valid": False, "target": "なし"},
                    "priority_lyric_cues": [
                        {
                            "token": "花",
                            "kind": "symbolic_motif",
                            "evidence": "人は花より短く咲いて",
                        }
                    ],
                },
            )
            for slot in (1, 2)
        ]
        missing = _action_budget_violations(
            entities,
            {
                (4, 1): "肩を引いて横を向く。",
                (4, 2): "視線を落として身体を沈める。",
            },
        )
        self.assertIn("missing_grounded_cue_target", missing[(4, 1)])
        present = _action_budget_violations(
            entities,
            {
                (4, 1): "散る花へ向き直り、視線で行方を追う。",
                (4, 2): "視線を落として身体を沈める。",
            },
        )
        self.assertNotIn((4, 1), present)

    def test_priority_cue_phase_distributes_scene_arc(self) -> None:
        self.assertEqual(_priority_cue_phase(1, 1), "establish_relation_reaction_release")
        self.assertEqual(_priority_cue_phase(1, 3), "establish_and_relation")
        self.assertEqual(_priority_cue_phase(2, 3), "event_and_reaction")
        self.assertEqual(_priority_cue_phase(3, 3), "release")
        self.assertEqual(_priority_cue_phase(4, 4), "release")

    def test_automatic_cue_reaches_actions_without_profile_dictionary(self) -> None:
        class AutomaticCueBackend(FakePlannerBackend):
            def complete_planner(
                self,
                *,
                task,
                system_prompt,
                payload,
                config,
                interrupt_callback=None,
            ):
                value = json.loads(payload)
                if task == "visual-beats":
                    self.calls.append((task, value))
                    rows = []
                    for item in value["slots"]:
                        source = json.dumps(
                            item.get("lyrics", []), ensure_ascii=False
                        )
                        if "御神木" in source:
                            text = (
                                "感情=畏敬｜根拠=御神木の影に立つ｜対象=御神木｜"
                                "接触=禁止｜現象=なし｜配置=参道奥の御神木｜"
                                "可視展開=御神木の枝葉が月明かりを受けて揺れる｜"
                                "身体主導=視線と胸郭｜終端=御神木を仰ぐ"
                            )
                        else:
                            text = (
                                "感情=懐旧｜根拠=なし｜対象=なし｜接触=禁止｜"
                                "現象=なし｜配置=なし｜可視展開=なし｜身体主導=肩と胸郭｜終端=静止"
                            )
                        rows.append(f"BEAT\t{item['slot']}\t{text}")
                    return "\n".join(rows)
                if task == "actions":
                    self.calls.append((task, value))
                    return "\n".join(
                        f"ACTION\t{item['slot']}\t"
                        + (
                            "参道奥の御神木へ視線を上げ、身体を向ける。"
                            if item["shot_index"] == 1
                            else (
                                "御神木の枝葉が月明かりを受けて揺れる"
                                "様子を見届け、胸郭を開いて立ち止まる。"
                            )
                        )
                        for item in value["slots"]
                    )
                return super().complete_planner(
                    task=task,
                    system_prompt=system_prompt,
                    payload=payload,
                    config=config,
                    interrupt_callback=interrupt_callback,
                )

        backend = AutomaticCueBackend()
        result = plan_timeline(
            backend,
            template_emd=TEMPLATE.replace(
                "千年鳥居をくぐるそなたよ", "御神木の影に立つ"
            ),
            concept_emd=CONCEPT,
            direction=DirectionArtifact(camera_profile_id="anime_emotional_mv"),
            lip_sync_mode="off",
            lip_sync_target="サブジェクト1",
            lip_sync_audio_slot=1,
            scenes_per_batch=3,
            system_prompts=prompts(),
            runtime_config=runtime(),
        )
        self.assertTrue(result.complete)
        beat_calls = [
            payload for task, payload in backend.calls if task == "visual-beats"
        ]
        self.assertEqual(len(beat_calls), 1)
        action_call = next(
            payload for task, payload in backend.calls if task == "actions"
        )
        self.assertEqual(action_call["slots"][0]["priority_lyric_cues"], [])
        self.assertEqual(
            action_call["planner_policy_contract"]["lyric_cue_mode"],
            "automatic",
        )
        self.assertEqual(
            [item["grounded_cue_phase"] for item in action_call["slots"]],
            ["establish_and_relation", "reaction_and_release"],
        )
        self.assertEqual(
            [item["priority_cue_phase"] for item in action_call["slots"]],
            ["", ""],
        )
        self.assertEqual(
            action_call["slots"][0]["required_spatial_anchor"],
            "参道奥の御神木",
        )
        self.assertEqual(
            action_call["slots"][1]["required_visible_development"],
            "御神木の枝葉が月明かりを受けて揺れる",
        )
        self.assertIn(
            "御神木",
            " ".join(text for _scene, _shot, text in result.content.actions),
        )

    def test_priority_cue_bare_token_stops_as_action_grounding(self) -> None:
        class BarePriorityCueBackend(FakePlannerBackend):
            def complete_planner(
                self,
                *,
                task,
                system_prompt,
                payload,
                config,
                interrupt_callback=None,
            ):
                value = json.loads(payload)
                if task == "visual-beats":
                    self.calls.append((task, value))
                    return "\n".join(
                        f"BEAT\t{item['slot']}\t"
                        "感情=懐旧｜根拠=苔へと還る｜対象=苔｜"
                        "接触=禁止｜現象=なし｜配置=大樹の根元｜"
                        "可視展開=苔が湿った樹皮を覆う｜"
                        "身体主導=視線と胸郭｜終端=視線を上げる"
                        for item in value["slots"]
                    )
                if task == "actions":
                    self.calls.append((task, value))
                    return "\n".join(
                        f"ACTION\t{item['slot']}\t"
                        "苔 手を胸の前で広げ、体を左右に振る。"
                        for item in value["slots"]
                    )
                return super().complete_planner(
                    task=task,
                    system_prompt=system_prompt,
                    payload=payload,
                    config=config,
                    interrupt_callback=interrupt_callback,
                )

        result = plan_timeline(
            BarePriorityCueBackend(),
            template_emd=TEMPLATE.replace(
                "千年鳥居をくぐるそなたよ", "苔へと還る"
            ),
            concept_emd=CONCEPT,
            direction=DirectionArtifact(camera_profile_id="anime_emotional_mv"),
            lip_sync_mode="off",
            lip_sync_target="サブジェクト1",
            lip_sync_audio_slot=1,
            scenes_per_batch=3,
            system_prompts=prompts(),
            runtime_config=runtime(),
        )
        self.assertFalse(result.complete)
        self.assertTrue(result.missing)
        self.assertTrue(
            all(kind == "ACTION_GROUNDING" for kind, _scene, _slot in result.missing)
        )

    def test_priority_cue_scene_isolation_prevents_batch_and_history_leakage(self) -> None:
        template = """> `シーン` 1
# シーン 00:00.000 --> 00:03.000
* `H3長` 73
> `歌詞` 遠い鈴の音
## ショット 00:00.000
* 未計画
> `シーン` 2
# シーン 00:03.000 --> 00:06.000 継続
* `H3長` 73
> `歌詞` 苔へと還る
## ショット 00:03.000
* 未計画
> `シーン` 3
# シーン 00:06.000 --> 00:09.000 継続
* `H3長` 73
> `歌詞` 暁を裂いて
## ショット 00:06.000
* 未計画
"""

        class CueCopyBackend(FakePlannerBackend):
            def complete_planner(
                self,
                *,
                task,
                system_prompt,
                payload,
                config,
                interrupt_callback=None,
            ):
                value = json.loads(payload)
                if task == "visual-beats":
                    self.calls.append((task, value))
                    rows = []
                    for item in value["slots"]:
                        source = json.dumps(
                            item.get("lyrics", []), ensure_ascii=False
                        )
                        if "苔" in source:
                            text = (
                                "感情=懐旧｜根拠=苔へと還る｜対象=苔｜"
                                "接触=禁止｜現象=なし｜配置=大樹の根元｜"
                                "可視展開=苔が湿った樹皮を覆う｜身体主導=視線と重心｜"
                                "終端=苔から視線を上げる"
                            )
                        else:
                            text = (
                                "感情=決意｜根拠=なし｜対象=なし｜接触=禁止｜"
                                "現象=なし｜配置=なし｜可視展開=なし｜身体主導=視線と重心｜終端=正面へ向く"
                            )
                        rows.append(f"BEAT\t{item['slot']}\t{text}")
                    return "\n".join(rows)
                if task == "actions":
                    self.calls.append((task, value))
                    batch_has_cue = any(
                        item.get("required_spatial_anchor")
                        or item.get("required_visible_development")
                        for item in value["slots"]
                    )
                    return "\n".join(
                        f"ACTION\t{item['slot']}\t"
                        + (
                            "大樹の根元で苔が湿った樹皮を覆う様子へ"
                            "視線を落とし、身体を引いて静止する。"
                            if batch_has_cue
                            else (
                                f"歌詞{item['scene_number']}へ視線を向け、"
                                "重心を移して異なる姿勢で静止する。"
                            )
                        )
                        for item in value["slots"]
                    )
                return super().complete_planner(
                    task=task,
                    system_prompt=system_prompt,
                    payload=payload,
                    config=config,
                    interrupt_callback=interrupt_callback,
                )

        backend = CueCopyBackend()
        result = plan_timeline(
            backend,
            template_emd=template,
            concept_emd=CONCEPT,
            scene_emd=(
                "# シーン設定\n## 環境\n* 夜の森と大樹\n"
                "## 時間・照明\n* 夜間\n"
            ),
            direction=DirectionArtifact(camera_profile_id="anime_emotional_mv"),
            lip_sync_mode="off",
            lip_sync_target="サブジェクト1",
            lip_sync_audio_slot=1,
            scenes_per_batch=3,
            system_prompts=prompts(),
            runtime_config=runtime(),
        )
        self.assertTrue(result.complete)
        visual_calls = [
            payload
            for task, payload in backend.calls
            if task == "visual-beats" and "retry" not in payload
        ]
        action_calls = [
            payload
            for task, payload in backend.calls
            if task == "actions" and "retry" not in payload
        ]
        self.assertEqual(
            [[item["scene_number"] for item in call["slots"]] for call in visual_calls],
            [[1, 2, 3]],
        )
        self.assertEqual(
            [[item["scene_number"] for item in call["slots"]] for call in action_calls],
            [[1], [2], [3]],
        )
        for payload in [*visual_calls, *action_calls]:
            self.assertEqual(
                payload["planner_policy_contract"]["priority_lyric_cues"],
                "entity_local_only",
            )
            self.assertEqual(
                payload["planner_policy_contract"]["lyric_cue_mode"],
                "automatic",
            )
        scene_actions = {
            scene: text for scene, _shot, text in result.content.actions
        }
        self.assertNotIn("苔", scene_actions[1])
        self.assertIn("苔", scene_actions[2])
        self.assertNotIn("苔", scene_actions[3])
        scene_three_call = next(
            call for call in action_calls if call["slots"][0]["scene_number"] == 3
        )
        self.assertNotIn("苔", json.dumps(scene_three_call, ensure_ascii=False))

    def test_action_quality_requires_face_performance_for_face_role(self) -> None:
        entity = _Entity(
            7,
            (7, 2),
            {
                "lyrics": [],
                "author_body": [],
                "performance_role": "face_and_upper_body_accent",
            },
        )
        missing = _action_budget_violations(
            [entity],
            {(7, 2): "肩を引き、胸郭を大きくひねって静止する。"},
        )
        self.assertIn("face_performance_missing", missing[(7, 2)])
        expressive = _action_budget_violations(
            [entity],
            {(7, 2): "伏し目から視線を上げ、眉を寄せて肩を引く。"},
        )
        self.assertNotIn((7, 2), expressive)

    def test_finite_camera_rejects_repeated_exact_plan(self) -> None:
        entities = [
            _Entity(
                1,
                (1, slot),
                {
                    "camera_protocol": "finite_v1",
                    "shot_duration_ms": 3200,
                    "arc_permission": "required",
                    "long_arc_emphasis": True,
                },
            )
            for slot in (1, 2)
        ]
        plan = (
            "MOTION=Arc Shot with large amplitude at fast speed｜"
            "START_SCALE=full_body｜END_SCALE=medium｜"
            "START_VIEW=low_front_three_quarter｜END_VIEW=side｜"
            "PATH=arc_left_60_120_70_90｜COVERAGE=whole_body_emotion"
        )
        violations = _camera_budget_violations(
            entities,
            {(1, 1): plan, (1, 2): plan},
            arc_maximum=2,
        )
        self.assertNotIn((1, 1), violations)
        self.assertIn("camera_plan_repetition", violations[(1, 2)])

    def test_finite_arc_fallback_varies_geometry_across_slots(self) -> None:
        plans = []
        for ordinal, scene in enumerate(range(1, 7)):
            entity = _Entity(
                scene,
                (scene, 1),
                {
                    "shot_duration_ms": 3200,
                    "arc_permission": "required",
                    "long_arc_emphasis": True,
                },
            )
            plan = _fallback_camera_plan(entity, ordinal)
            self.assertEqual(_camera_plan_contract_violations(entity, plan), ())
            plans.append(_render_camera_plan(plan))
        self.assertGreaterEqual(len(set(plans)), 3)

    def test_cue_card_requires_exact_scene_evidence_and_target(self) -> None:
        entity = _Entity(
            1,
            (1,),
            {
                "lyrics": [{"section": "VERSE", "text": "大樹の根元の苔"}],
                "author_body": [],
            },
        )
        valid = _parse_cue_card(
            entity,
            "感情=懐旧｜根拠=大樹の根元の苔｜対象=苔｜接触=禁止｜"
            "現象=なし｜配置=大樹の根元｜可視展開=湿った苔が樹皮を覆う｜"
            "身体主導=胸郭と視線｜終端=大樹へ向き直る",
        )
        self.assertTrue(valid.valid)
        self.assertEqual(valid.target, "苔")
        self.assertEqual(valid.spatial_anchor, "大樹の根元")
        self.assertIn("湿った苔", valid.visible_development)

        invalid = _parse_cue_card(
            entity,
            "感情=懐旧｜根拠=遠い鐘｜対象=石灯籠｜接触=許可｜"
            "現象=なし｜配置=参道脇｜可視展開=灯籠の輪郭が見える｜"
            "身体主導=腕｜終端=灯籠へ触れる",
        )
        self.assertFalse(invalid.valid)
        self.assertIn("evidence_not_in_scene_source", invalid.violations)
        self.assertIn("target_not_in_evidence", invalid.violations)

    def test_cue_card_rejects_bare_target_without_development(self) -> None:
        entity = _Entity(
            3,
            (3,),
            {
                "lyrics": [{"section": "VERSE", "text": "苔へと還る"}],
                "author_body": [],
            },
        )
        bare = _parse_cue_card(
            entity,
            "感情=懐旧｜根拠=苔へと還る｜対象=苔｜接触=禁止｜"
            "現象=なし｜配置=なし｜可視展開=なし｜"
            "身体主導=視線｜終端=静止",
        )
        self.assertFalse(bare.valid)
        self.assertIn("missing_spatial_anchor", bare.violations)
        self.assertIn("missing_visible_development", bare.violations)

    def test_missing_after_retry_returns_template_artifact(self) -> None:
        backend = FakePlannerBackend(miss_action_slot_two=3)
        result = plan_timeline(
            backend,
            template_emd=TEMPLATE,
            concept_emd=CONCEPT,
            direction=None,
            lip_sync_mode="off",
            lip_sync_target="サブジェクト1",
            lip_sync_audio_slot=1,
            scenes_per_batch=3,
            system_prompts=prompts(),
            runtime_config=runtime(),
        )
        self.assertFalse(result.complete)
        self.assertEqual(result.emd.schema, "MVD_EMD_TEMPLATE_V1")
        self.assertEqual(result.missing, (("ACTION", 1, 2),))
        self.assertNotIn("cameras", [task for task, _ in backend.calls])

    def test_lip_sync_modes_only_change_deterministic_renderer(self) -> None:
        template = parse_template_emd(TEMPLATE + INSTRUMENTAL_TAIL)
        concept = normalize_concept_emd(CONCEPT)
        content = PlannerContent(
            visual_beats=((1, "note"),),
            song_direction="direction",
            shot_layouts=((1, (0, 5000)), (2, (10125,))),
            actions=((1, 1, "動作1"), (1, 2, "動作2"), (2, 1, "余韻の動作")),
            cameras=((1, 1, "カメラ1"), (1, 2, "カメラ2"), (2, 1, "余韻のカメラ")),
            issue_count=0,
            retried_scenes=(),
            removed_generated_dialogue_count=0,
            unused_protected_dialogue_ids=(),
        )
        direction = DirectionArtifact()
        outputs = {
            mode: render_planner_content(
                content=content,
                concept_emd=concept,
                template=template,
                direction=direction,
                lip_sync_mode=mode,
                lip_sync_target="サブジェクト1",
                lip_sync_audio_slot=2,
            ).text
            for mode in ("off", "context_loop", "audio_reference", "lyrics")
        }
        self.assertNotIn("リップシンク", outputs["off"])
        self.assertIn("`Context Loop`", outputs["context_loop"])
        self.assertIn("`Audio参照` `サブジェクト1` `音声2`", outputs["audio_reference"])
        self.assertIn("`歌詞` `サブジェクト1`", outputs["lyrics"])
        for text in outputs.values():
            self.assertIn("> `歌詞` 千年鳥居をくぐるそなたよ", text)

        context_document = parse_emd(outputs["context_loop"])
        self.assertEqual(
            [
                [directive.mode for directive in scene.audio_directives]
                for scene in context_document.scenes
            ],
            [["context_loop"], ["context_loop"]],
        )
        audio_reference_document = parse_emd(outputs["audio_reference"])
        self.assertEqual(
            [
                [directive.mode for directive in scene.audio_directives]
                for scene in audio_reference_document.scenes
            ],
            [["audio_reference"], []],
        )
        plan = compile_ref2va(outputs["context_loop"], PassthroughTranslator()).plan
        for scene in plan["shots"]:
            self.assertEqual(scene["source_reference"], "off")
            self.assertEqual(scene["generated_continuity"], "off")
            self.assertEqual(scene["source_audio_target"], "locked")

    def test_generated_dialogue_and_placeholder_echoes_are_removed(self) -> None:
        protector = DialogueProtector()
        protected = protector.protect(
            "作者は「ここにいて」と書き、<d>[English]Stay.</d>も指定した。",
            source_ref="test",
        )
        first, second = [record.placeholder for record in protector.records]
        filtered = filter_generated_dialogue(
            (
                f"動作 {first} 「捏造」 {second}",
                f"重複 {first} 未知 __MVD_LOCKED_DIALOGUE_9999__ 『捏造』",
            ),
            protector.records,
        )
        self.assertNotIn("「ここにいて」", " ".join(filtered.texts))
        self.assertNotIn("<d>[English]Stay.</d>", " ".join(filtered.texts))
        self.assertNotIn("捏造", " ".join(filtered.texts))
        self.assertNotIn("__MVD", " ".join(filtered.texts))
        self.assertGreaterEqual(filtered.removed_count, 6)

    def test_source_dialogue_echo_is_removed_before_original_body_is_rendered(self) -> None:
        template = TEMPLATE.replace("* 未計画", "* 主人公は「ここにいて」と告げる。", 1)

        class EchoBackend(FakePlannerBackend):
            def complete_planner(self, *, task, system_prompt, payload, config, interrupt_callback=None):
                value = json.loads(payload)
                self.calls.append((task, value))
                record_type = {
                    "visual-beats": "BEAT",
                    "song-direction": "DIRECTION",
                    "shot-layout": "LAYOUT",
                    "actions": "ACTION",
                    "cameras": "CAMERA",
                }[task]
                rows = []
                for item in value["slots"]:
                    if task == "shot-layout":
                        selected = ",".join(
                            candidate["id"]
                            for candidate in item["candidates"]
                            if candidate["source"] in {"scene_start", "existing_shot"}
                        )
                        rows.append(f"LAYOUT\t{item['slot']}\tCUT,{selected}")
                        continue
                    echo = " __MVD_LOCKED_DIALOGUE_0001__" if task == "actions" else ""
                    rows.append(f"{record_type}\t{item['slot']}\t有効な記述{echo}")
                return "\n".join(rows)

        result = plan_timeline(
            EchoBackend(),
            template_emd=template,
            concept_emd=CONCEPT,
            direction=None,
            lip_sync_mode="off",
            lip_sync_target="サブジェクト1",
            lip_sync_audio_slot=1,
            scenes_per_batch=3,
            system_prompts=prompts(),
            runtime_config=runtime(),
        )
        self.assertTrue(result.complete)
        self.assertEqual(result.emd.text.count("「ここにいて」"), 1)
        self.assertNotIn("__MVD_LOCKED_DIALOGUE_", result.emd.text)

    def test_dialogue_only_generated_shot_returns_incomplete_after_camera_quality_retry(self) -> None:
        backend = DialogueOnlyPlannerBackend()
        result = plan_timeline(
            backend,
            template_emd=TEMPLATE,
            concept_emd=CONCEPT,
            direction=None,
            lip_sync_mode="off",
            lip_sync_target="サブジェクト1",
            lip_sync_audio_slot=1,
            scenes_per_batch=3,
            system_prompts=prompts(),
            runtime_config=runtime(),
        )
        self.assertFalse(result.complete)
        self.assertEqual(result.missing, (("FILTERED", 1, 1), ("FILTERED", 1, 2)))
        self.assertEqual([task for task, _ in backend.calls].count("actions"), 1)
        self.assertEqual([task for task, _ in backend.calls].count("cameras"), 2)


class TimelinePlannerNodeTests(unittest.TestCase):
    def test_llama_backend_reports_task_batch_and_timing_progress(self) -> None:
        from nodes.node_timeline_planner.node import _LlamaPlannerBackend

        class ProgressLifecycle:
            effective_n_ctx = 4096

            @staticmethod
            def count_serialized_prompt(_prompt):
                return type("Count", (), {"count": 321, "estimated": False})()

            @staticmethod
            def complete_chat(_messages, _config, *, interrupt_callback=None):
                return "BEAT\t1\tvisual beat"

        backend = _LlamaPlannerBackend(ProgressLifecycle())
        backend.configure_progress(scene_count=6, scenes_per_batch=3)
        payload = json.dumps(
            {
                "slots": [
                    {"slot": 1, "scene_number": 1},
                    {"slot": 2, "scene_number": 2},
                ]
            }
        )
        with self.assertLogs("mv_director.nodes", level="INFO") as captured:
            backend.complete_planner(
                task="visual-beats",
                system_prompt="system",
                payload=payload,
                config=runtime(),
            )
        output = "\n".join(captured.output)
        self.assertIn("inference started; task=visual-beats", output)
        self.assertIn("batch=1/2", output)
        self.assertIn("scenes=1-2; slots=2", output)
        self.assertIn("prompt_tokens=321; max_tokens=512", output)
        self.assertIn("call_seed=", output)
        self.assertIn("inference completed; task=visual-beats", output)
        self.assertIn("response_chars=18", output)

        retry_payload = json.dumps(
            {
                "retry": "missing_slots_only",
                "slots": [{"slot": 1, "scene_number": 1}],
            }
        )
        with self.assertLogs("mv_director.nodes", level="INFO") as captured:
            backend.complete_planner(
                task="visual-beats",
                system_prompt="system",
                payload=retry_payload,
                config=runtime(),
            )
        output = "\n".join(captured.output)
        self.assertIn("batch=retry; call=2; retry=missing_slots", output)
        self.assertNotEqual(
            _LlamaPlannerBackend._call_seed(1, "visual-beats", 1, payload),
            _LlamaPlannerBackend._call_seed(1, "visual-beats", 2, payload),
        )
        self.assertEqual(
            _LlamaPlannerBackend._call_seed(1, "visual-beats", 1, payload),
            _LlamaPlannerBackend._call_seed(1, "visual-beats", 1, payload),
        )

    def test_public_mapping_and_complete_socket_surface(self) -> None:
        from nodes import NODE_CLASS_MAPPINGS, NODE_DISPLAY_NAME_MAPPINGS

        cls = NODE_CLASS_MAPPINGS["MVDirectorTimelinePlanner"]
        self.assertEqual(
            NODE_DISPLAY_NAME_MAPPINGS["MVDirectorTimelinePlanner"],
            "MV Director - Timeline Planner",
        )
        self.assertEqual(cls.RETURN_TYPES, ("STRING", "MV_DIRECTOR_EMD", "STRING"))
        inputs = cls.INPUT_TYPES()
        self.assertTrue(inputs["required"]["template_emd"][1]["forceInput"])
        self.assertEqual(inputs["required"]["lip_sync_mode"][1]["default"], "lyrics")
        self.assertEqual(
            inputs["required"]["cache_mode"],
            (["reuse", "refresh", "disabled"], {"default": "reuse"}),
        )
        self.assertEqual(
            inputs["required"]["seed"][1]["control_after_generate"],
            "randomize",
        )
        self.assertIn("model_name_override", inputs["optional"])
        self.assertIn("direction", inputs["optional"])


if __name__ == "__main__":
    unittest.main()
