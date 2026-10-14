"""CPU transport/prompt regressions, not claims of LLM or H3 compliance."""

from dataclasses import replace
import json
from pathlib import Path
import unittest

from core.artifacts import DirectionArtifact, SubjectFeature
from core.direction import DirectionEnhancerInput, build_direction_payload
from core.compiler import IdentityTranslator, compile_ref2va
from core.emd import merge_subject_emd, parse_emd
from core.planner import plan_timeline
from core.protocols import parse_vision_observations
from core.vision import render_subject_emd
from core.vision.image_to_subject import VISION_PROMPT_VERSION
from nodes.node_timeline_planner.node import _system_prompts
from scene_author_fixtures import Backend, TEMPLATE, _runtime


SUBJECT_DESCRIPTIONS = (
    "顔面全体は滑らかな赤い布で覆われ、胸だけに黒い模様がある。",
    "通常の顔を持ち、丸い眉と左耳だけの青い耳飾りがある。",
    "左目だけを眼帯で覆い、右目は露出している。",
    "表示面を持つ機械で、右手だけに白い手袋がある。",
)


class ScopedBackend(Backend):
    def __init__(self):
        super().__init__()
        self.prompts = {}

    def complete_planner(self, *, task, payload, system_prompt, **kwargs):
        self.prompts[task] = system_prompt
        if task != "scene-author-performance":
            return super().complete_planner(task=task, payload=payload, **kwargs)
        request = json.loads(payload)
        self.calls.append((task, request))
        return "\n".join(
            f"PERFORMANCE\t{slot['slot']}\t"
            "`サブジェクト1`は頭を相手へ向け、`サブジェクト2`は目を細める。"
            '｜PERFORMER=サブジェクト2｜END_STATE={"サブジェクト1":"相手へ向いた頭部。",'
            '"サブジェクト2":"目を細めた表情。"}'
            for slot in request["slots"]
        )


def subject_text(count=4):
    return merge_subject_emd(*(
        f"# サブジェクト\n* `画像{i}` {description}\n"
        for i, description in enumerate(SUBJECT_DESCRIPTIONS[:count], 1)
    )).text


class LocalIdentityScopeTests(unittest.TestCase):
    def test_vision_prompt_distinguishes_covering_from_skin_and_temporary_occlusion(self):
        prompt = " ".join((Path(__file__).resolve().parents[1] / "prompts/vision_observation_system_prompt.txt").read_text(encoding="utf-8").split())
        self.assertIn("do not shorten colored fabric into colored skin", prompt)
        self.assertIn("normal visible face remains a normal visible face", prompt)
        self.assertIn("partial covering does not cover its exposed", prompt)
        self.assertIn("A face hidden by pose, cropping, hair, or low resolution", prompt)
        self.assertIn("only to the imaged identity", prompt)
        self.assertEqual(VISION_PROMPT_VERSION, "mvd-vision-observation-v17-local-covering")

    def test_locked_local_hints_survive_vision_enhancer_planner_and_compiler(self):
        original = parse_vision_observations((Path(__file__).parent / "fixtures/protocol/vision_observation_valid.txt").read_text(encoding="utf-8")).observations
        hints = SUBJECT_DESCRIPTIONS[:3]
        fragments = []
        for i, hint in enumerate(hints, 1):
            observations = replace(original, primary_subject="人物", hint_status="consistent",
                                   hint_reason="参照と整合する。", subject_features=())
            fragment = render_subject_emd(observations, concept_type="person", picture_index=i,
                                          subject_hint=hint, hint_mode="lock_identity").emd_fragment
            fragments.append(fragment)
        enhancer_input = DirectionEnhancerInput(concept_emd=fragments[0], concept_emd_2=fragments[1], concept_emd_3=fragments[2])
        merged = enhancer_input.normalized_concept_emd
        self.assertEqual(json.loads(build_direction_payload(enhancer_input))["concept_emd"], merged)
        backend = Backend()
        result = plan_timeline(backend, template_emd=TEMPLATE, concept_emd=merged,
                               direction=DirectionArtifact(), lip_sync_mode="off",
                               lip_sync_target="サブジェクト1", lip_sync_audio_slot=1,
                               system_prompts=_system_prompts(), runtime_config=_runtime())
        self.assertTrue(result.complete)
        for _, payload in backend.calls:
            self.assertEqual(payload["subject_emd"].strip(), merged.strip())
        document = parse_emd(result.emd.text)
        self.assertEqual(tuple(s.description for s in document.subjects),
                         tuple("人物 優先して保持する識別特徴: " + h for h in hints))
        compiled = compile_ref2va(result.emd.text, IdentityTranslator())
        for i, hint in enumerate(hints, 1):
            definition, = [line for line in compiled.plan["shots"][0]["prompt"] if line.startswith(f"<Subject {i}> is described here:")]
            self.assertIn(hint, definition)
            for other in hints:
                if other != hint:
                    self.assertNotIn(other, definition)

    def test_planner_prompts_scope_attributes_without_banning_normal_expression(self):
        prompts = _system_prompts()
        for stage in ("performance", "camera"):
            with self.subTest(stage=stage):
                prompt = prompts[f"scene-author-{stage}"]
                self.assertIn("subject_emd", prompt)
                self.assertIn("他部位・他人物", prompt)
                self.assertIn("左右・範囲", prompt)
                self.assertIn("通常の顔", prompt)
                self.assertIn("目・眉の表情", prompt)
                self.assertIn("目穴や露出した器官を追加しない", prompt)
                self.assertIn("他部位の形状変更", prompt)
                self.assertIn("作者固定", prompt)
        performance = prompts["scene-author-performance"]
        self.assertIn("不明な外見や一時的に見えない部位", performance)
        self.assertIn("頭の向きや身体の反応", performance)
        self.assertNotIn("支持・体幹・腕・視線", performance)
        self.assertNotIn("目・眉・頬・視線と身体", performance)
        camera = prompts["scene-author-camera"]
        self.assertNotIn("両眉・両目・鼻・口全体", camera)
        self.assertNotIn("閉口中は身体・目・眉", camera)
        self.assertIn("顔が画面の大部分を占める", camera)
        self.assertIn("歌唱中の口形が読める時間帯", camera)

    def test_stable_local_facts_survive_vision_rendering_without_extra_anatomy(self):
        fixture = Path(__file__).parent / "fixtures/protocol/vision_observation_valid.txt"
        original = parse_vision_observations(fixture.read_text(encoding="utf-8")).observations
        features = (
            SubjectFeature("face", "顔面は連続した布で覆われる。", "clear"),
            SubjectFeature("clothing", "胸だけに黒い模様がある。", "partial"),
            SubjectFeature("eyes", "右目の形は不明。", "uncertain"),
        )
        observations = replace(original, primary_subject="人物", subject_features=features)
        result = render_subject_emd(observations, concept_type="person", picture_index=3,
                                    subject_hint="左手だけに白い手袋。")
        document = parse_emd(result.emd_fragment + TEMPLATE)
        description = document.subjects[0].description
        for text in (features[0].text, features[1].text, "左手だけに白い手袋。"):
            self.assertIn(text, description)
        self.assertNotIn(features[2].text, description)
        self.assertNotIn("眼球", description)
        self.assertNotIn("目がない", description)
        self.assertEqual(result.omitted_uncertain_features, 1)
        self.assertEqual(document.subjects[0].references, ("<Picture 3>",))

    def test_two_to_four_subjects_keep_local_descriptions_in_own_definitions(self):
        for count in (2, 3, 4):
            with self.subTest(count=count):
                source = subject_text(count) + TEMPLATE
                document = parse_emd(source)
                self.assertEqual(tuple(s.description for s in document.subjects),
                                 SUBJECT_DESCRIPTIONS[:count])
                compiled = compile_ref2va(source, IdentityTranslator())
                lines = compiled.plan["shots"][0]["prompt"]
                for index, description in enumerate(SUBJECT_DESCRIPTIONS[:count], 1):
                    matches = [line for line in lines if description in line]
                    self.assertEqual(len(matches), 1)
                    self.assertTrue(matches[0].startswith(f"<Subject {index}> is described here:"))
                    self.assertIn(f"<Picture {index}>", matches[0])
                    for other in SUBJECT_DESCRIPTIONS[:count]:
                        if other != description:
                            self.assertNotIn(other, matches[0])

    def test_existing_tasks_receive_exact_subjects_and_preserve_fixed_facial_action(self):
        subjects = subject_text()
        template = TEMPLATE.replace("人物が片手を胸元に置く。", "`サブジェクト1`が瞼を開く。")
        backend = ScopedBackend()
        result = plan_timeline(
            backend, template_emd=template, concept_emd=subjects,
            direction=DirectionArtifact(), lip_sync_mode="off",
            lip_sync_target="サブジェクト1", lip_sync_audio_slot=1,
            system_prompts=_system_prompts(), runtime_config=_runtime(),
        )
        self.assertTrue(result.complete)
        self.assertEqual(len(backend.calls), 3)  # no new semantic audit/retry stage
        for task, request in backend.calls:
            self.assertEqual(request["subject_emd"], subjects)
            self.assertEqual(request["subject_ids"], [f"サブジェクト{i}" for i in range(1, 5)])
            if task == "scene-author-performance":
                self.assertEqual(request["fixed_performances"], {"1": "`サブジェクト1`が瞼を開く。"})
            if task == "scene-author-camera":
                self.assertEqual(request["fixed_cameras"], {"1": "目と口が見える正面。"})
        self.assertIn("`演技` `サブジェクト1`が瞼を開く。", result.emd.text)
        self.assertIn("`カメラ` 目と口が見える正面。", result.emd.text)
        self.assertEqual(tuple(s.description for s in parse_emd(result.emd.text).subjects),
                         SUBJECT_DESCRIPTIONS)
        self.assertIn("`サブジェクト2`は目を細める。", result.emd.text)
        self.assertEqual(backend.prompts["scene-author-performance"],
                         _system_prompts()["scene-author-performance"])


if __name__ == "__main__":
    unittest.main()
