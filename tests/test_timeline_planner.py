from __future__ import annotations

import json
import unittest

from core.artifacts import DirectionArtifact
from core.emd import parse_emd
from core.inference import LlamaRuntimeConfig
from core.planner import (
    DialogueProtector,
    PlannerContent,
    filter_generated_dialogue,
    normalize_concept_emd,
    parse_template_emd,
    plan_timeline,
    render_planner_content,
)


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


class FakePlannerBackend:
    def __init__(self, *, miss_action_slot_two: int = 0) -> None:
        self.calls: list[tuple[str, dict[str, object]]] = []
        self.miss_action_slot_two = miss_action_slot_two

    def complete_planner(self, *, task, system_prompt, payload, config, interrupt_callback=None):
        value = json.loads(payload)
        self.calls.append((task, value))
        record_type = {
            "lyric-notes": "NOTE",
            "song-direction": "DIRECTION",
            "actions": "ACTION",
            "cameras": "CAMERA",
        }[task]
        rows = []
        for item in value["slots"]:
            slot = item["slot"]
            if task == "actions" and slot == 2 and self.miss_action_slot_two > 0:
                self.miss_action_slot_two -= 1
                continue
            text = {
                "lyric-notes": f"歌詞の感情と鳥居のモチーフ {slot}",
                "song-direction": "夜から朝へ進み、鳥居を反復する。",
                "actions": f"サブジェクト1が重心を移しながら歩く。{slot} 「生成台詞」",
                "cameras": f"カメラは前景の鳥居から人物へ緩やかに寄る。{slot}",
            }[task]
            rows.append(f"{record_type}\t{slot}\t{text}")
        return "\n".join(rows)


class DialogueOnlyPlannerBackend(FakePlannerBackend):
    def complete_planner(self, *, task, system_prompt, payload, config, interrupt_callback=None):
        value = json.loads(payload)
        self.calls.append((task, value))
        record_type = {
            "lyric-notes": "NOTE",
            "song-direction": "DIRECTION",
            "actions": "ACTION",
            "cameras": "CAMERA",
        }[task]
        return "\n".join(
            f"{record_type}\t{item['slot']}\t「生成台詞だけ」" for item in value["slots"]
        )


class SmallModelFormattingBackend(FakePlannerBackend):
    def complete_planner(self, *, task, system_prompt, payload, config, interrupt_callback=None):
        value = json.loads(payload)
        self.calls.append((task, value))
        record_type = {
            "lyric-notes": "NOTE",
            "song-direction": "DIRECTION",
            "actions": "ACTION",
            "cameras": "CAMERA",
        }[task]
        if task == "lyric-notes":
            return "<think>protocolを確認する。</think>\n歌詞本文\tTAB\t1\tTAB\t有効な記述1"
        if task == "song-direction":
            return "<think></think>\nDIRECTION\tTAB\tslot 1\tTAB\t有効な全曲方針"
        records = [
            f"{record_type}<TAB>{item['slot']}<TAB>有効な記述{item['slot']}"
            for item in value["slots"]
        ]
        return "<think>protocolを確認する。</think>\n" + "<TAB>".join(records)


def runtime() -> LlamaRuntimeConfig:
    return LlamaRuntimeConfig(max_tokens=512, n_ctx=4096)


def prompts() -> dict[str, str]:
    return {
        "lyric-notes": "notes",
        "song-direction": "direction",
        "actions": "actions",
        "cameras": "cameras",
    }


class TimelinePlannerCoreTests(unittest.TestCase):
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

    def test_four_tasks_render_valid_emd_and_filter_generated_dialogue(self) -> None:
        backend = FakePlannerBackend()
        result = plan_timeline(
            backend,
            template_emd=TEMPLATE,
            concept_emd=CONCEPT,
            direction=DirectionArtifact(
                style_direction=("実写映画として描写する。",),
                motion_direction=("接地を明瞭にする。",),
                camera_direction=("奥行きを保つ。",),
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
            "lyric-notes", "song-direction", "actions", "cameras"
        ])
        text = result.emd.text
        self.assertNotIn("生成台詞", text)
        self.assertIn("* `リップシンク` `歌詞` `サブジェクト1` 「千年鳥居をくぐるそなたよ」", text)
        self.assertLess(text.index("サブジェクト1が重心"), text.index("カメラは前景"))
        document = parse_emd(text)
        self.assertEqual(document.scenes[0].h3_length, 243)
        self.assertEqual(document.scenes[0].shots[0].lyric_annotations[0].text, "千年鳥居をくぐるそなたよ")
        song_payload = backend.calls[1][1]
        self.assertNotIn("千年鳥居", json.dumps(song_payload, ensure_ascii=False))
        camera_payload = backend.calls[3][1]
        self.assertIn("locked_action", camera_payload["slots"][0])
        action_payload = backend.calls[2][1]
        self.assertNotIn("lip_sync_mode", action_payload)
        self.assertNotIn("lip_sync_audio_slot", action_payload)
        self.assertEqual(action_payload["primary_action_concept"], "サブジェクト1")
        self.assertIsNone(action_payload["slots"][0]["previous_shot"])
        self.assertEqual(
            action_payload["slots"][1]["previous_shot"],
            {"scene_number": 1, "shot_index": 1},
        )
        self.assertEqual(action_payload["slots"][0]["previous_batch_action"], "")

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

    def test_missing_after_retry_returns_template_artifact(self) -> None:
        backend = FakePlannerBackend(miss_action_slot_two=2)
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
        template = parse_template_emd(TEMPLATE)
        concept = normalize_concept_emd(CONCEPT)
        content = PlannerContent(
            lyric_notes=((1, "note"),),
            song_direction="direction",
            actions=((1, 1, "動作1"), (1, 2, "動作2")),
            cameras=((1, 1, "カメラ1"), (1, 2, "カメラ2")),
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
                    "lyric-notes": "NOTE",
                    "song-direction": "DIRECTION",
                    "actions": "ACTION",
                    "cameras": "CAMERA",
                }[task]
                rows = []
                for item in value["slots"]:
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

    def test_dialogue_only_generated_shot_returns_incomplete_without_quality_retry(self) -> None:
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
        self.assertEqual([task for task, _ in backend.calls].count("cameras"), 1)


class TimelinePlannerNodeTests(unittest.TestCase):
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
            inputs["required"]["seed"][1]["control_after_generate"],
            "randomize",
        )
        self.assertIn("model_name_override", inputs["optional"])
        self.assertIn("direction", inputs["optional"])


if __name__ == "__main__":
    unittest.main()
