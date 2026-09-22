from pathlib import Path
import json
import unittest
from unittest.mock import patch

from core.direction import (
    CAMERA_PROFILES,
    DIRECTION_PRESETS,
    MOTION_PROFILES,
    PASSTHROUGH_PROFILE,
    STYLE_PROFILES,
    DirectionEnhancerError,
    DirectionEnhancerInput,
    build_direction_payload,
    enhance_direction,
    parse_direction_passthrough,
)
from core.inference import LlamaRuntimeConfig
from nodes import NODE_CLASS_MAPPINGS


class FakeDirectionBackend:
    def __init__(self, *responses: str) -> None:
        self.responses = list(responses)
        self.calls = []

    def complete_direction(self, **kwargs):
        self.calls.append(kwargs)
        if not self.responses:
            raise AssertionError("unexpected inference call")
        return self.responses.pop(0)


VALID = "\n".join(
    (
        "STYLE\t1\t実写映画として自然な材質と奥行きで描く。",
        "MOTION\t1\t重心と接地が読める連続動作にする。",
        "CAMERA\t1\t緩やかに接近しながら安定した構図を保つ。",
        "OTHER\t1\t夜間の静かな緊張感を保つ。",
    )
)


class DirectionEnhancerTests(unittest.TestCase):
    def test_llama_backend_caps_oversized_output_reservation(self) -> None:
        from nodes.node_direction_enhancer.node import _LlamaDirectionBackend

        class BudgetLifecycle:
            effective_n_ctx = 8_192
            called_config = None

            @staticmethod
            def count_serialized_prompt(_prompt):
                return type("Count", (), {"count": 3_077, "estimated": False})()

            @classmethod
            def complete_chat(cls, _messages, config, *, interrupt_callback=None):
                cls.called_config = config
                return "STYLE\t1\t画風。"

        lifecycle = BudgetLifecycle()
        backend = _LlamaDirectionBackend(lifecycle)
        with self.assertLogs("mv_director.nodes", level="INFO") as captured:
            response = backend.complete_direction(
                system_prompt="system",
                payload="payload",
                config=LlamaRuntimeConfig(max_tokens=4_096, n_ctx=8_192),
            )
        self.assertEqual(response, "STYLE\t1\t画風。")
        self.assertEqual(lifecycle.called_config.max_tokens, 1_024)
        output = "\n".join(captured.output)
        self.assertIn("requested_max_tokens=4096", output)
        self.assertIn("effective_max_tokens=1024", output)

    def test_empty_user_and_concept_use_profiles(self) -> None:
        backend = FakeDirectionBackend(VALID)
        value = DirectionEnhancerInput()
        result = enhance_direction(
            backend,
            value=value,
            system_prompt="fixed",
            runtime_config=LlamaRuntimeConfig(),
        )
        self.assertEqual(len(backend.calls), 1)
        self.assertEqual(
            result.direction.style_direction,
            (STYLE_PROFILES["anime_emotional_mv"],),
        )
        self.assertEqual(
            result.direction.motion_direction,
            (MOTION_PROFILES["anime_emotional_mv"],),
        )
        self.assertEqual(
            result.direction.camera_direction,
            (CAMERA_PROFILES["anime_emotional_mv"],),
        )
        self.assertEqual(result.direction.style_profile_id, "anime_emotional_mv")
        self.assertEqual(result.direction.motion_profile_id, "anime_emotional_mv")
        self.assertEqual(result.direction.camera_profile_id, "anime_emotional_mv")
        self.assertIn("## スタイル", result.direction_emd_preview)
        self.assertIn("## その他", result.direction_emd_preview)
        input_records = [
            item for item in result.direction.provenance if item.record_kind == "input"
        ]
        self.assertEqual(len(input_records), 3)
        self.assertTrue(all(item.source == "profile" for item in input_records))

    def test_normalizes_observed_qwen4b_record_formatting(self) -> None:
        backend = FakeDirectionBackend(
            "<think>\n</think>\n"
            "STYLE\t1\t画風。\tENVIRONMENT\t2\t森。\tTIME_LIGHTING\t3\t夜。"
        )
        result = enhance_direction(
            backend,
            value=DirectionEnhancerInput(
                style_profile="reference_anime",
                motion_profile="natural_performance",
                camera_profile="readable_depth",
            ),
            system_prompt="fixed",
            runtime_config=LlamaRuntimeConfig(),
        )
        self.assertEqual(len(backend.calls), 1)
        self.assertEqual(result.direction.style_direction, ("画風。",))
        self.assertEqual(
            result.direction.motion_direction,
            (MOTION_PROFILES["natural_performance"],),
        )
        self.assertEqual(
            result.direction.camera_direction,
            (CAMERA_PROFILES["readable_depth"],),
        )
        self.assertEqual(result.direction.environment_direction, ("森。",))
        self.assertEqual(result.direction.time_lighting_direction, ("夜。",))
        self.assertFalse(result.issues)
        self.assertFalse(result.retried_missing)

    def test_payload_keeps_authority_order_and_read_only_concept(self) -> None:
        concept = "# サブジェクト\n* 金色の眉。\n"
        value = DirectionEnhancerInput(
            concept_emd=concept,
            user_request="夜間にする。",
            style_profile="illust_to_photoreal",
            motion_profile="expressive_mv",
            camera_profile="cinematic_depth",
        )
        payload = json.loads(build_direction_payload(value))
        self.assertEqual(
            payload["authority_order"],
            ["user", "scene_emd", "vision_concept", "profile", "generated"],
        )
        self.assertEqual(payload["user_request"], "夜間にする。")
        self.assertEqual(payload["concept_emd"], concept.strip())
        style = payload["profiles"]["style"]["text"]
        self.assertTrue(
            style.startswith(
                "Shoot as a scene from a photorealistic live-action movie."
            )
        )
        self.assertIn("real human actors", style)
        self.assertIn("natural facial bone structure", style)
        self.assertIn("typical human eye proportions", style)
        self.assertIn("skin visible with pores and fine hairs", style)
        self.assertIn("actual physical materials", style)
        self.assertTrue(payload["profiles"]["style"]["locked"])
        for source_medium_term in ("アニメ", "イラスト", "セル影", "線画", "保持しない"):
            self.assertNotIn(source_medium_term, style)

    def test_direction_receives_scene_context_but_not_reference_pose(self) -> None:
        scene_emd = (
            "# シーン設定\n## 環境\n* 森の鳥居。\n* 石段\n* 木々\n\n"
            "## 時間・照明\n* 夜。\n* 月光。\n\n## 背景参照\n* `画像2`\n"
        )
        payload = json.loads(
            build_direction_payload(
                DirectionEnhancerInput(
                    concept_emd="# サブジェクト\n* 狼耳の人物。\n",
                    scene_emd=scene_emd,
                )
            )
        )
        self.assertEqual(
            payload["scene_context"],
            {
                "environment": ["森の鳥居。", "石段", "木々"],
                "time_lighting": ["夜。", "月光。"],
                "background_picture": "<Picture 2>",
                "authority": (
                    "Observed baseline only. Explicit user direction overrides its "
                    "time, lighting, weather, season, and staging."
                ),
            },
        )
        serialized = json.dumps(payload, ensure_ascii=False)
        self.assertNotIn("両手を広げた", serialized)
        self.assertNotIn("shot_size", serialized)
        self.assertNotIn("subject_pose", serialized)

    def test_locked_scene_hint_is_preserved_exactly_in_environment(self) -> None:
        scene_emd = (
            "# シーン設定\n## 環境\n* 赤い鳥居。\n* 森の中の神社境内\n"
            "* 石畳\n\n## 時間・照明\n* 夜\n* 月光\n"
        )
        backend = FakeDirectionBackend(
            "STYLE\t1\t映画的なアニメ映像。\n"
            "ENVIRONMENT\t1\t森の神社境内と石畳を描く。"
        )
        value = DirectionEnhancerInput(
            scene_emd=scene_emd,
        )
        payload = json.loads(build_direction_payload(value))
        self.assertEqual(
            payload["scene_context"]["environment"][0], "赤い鳥居。"
        )
        result = enhance_direction(
            backend,
            value=value,
            system_prompt="fixed",
            runtime_config=LlamaRuntimeConfig(),
        )
        self.assertEqual(
            result.direction.environment_direction,
            ("森の神社境内と石畳を描く。",),
        )
        self.assertTrue(any(item.source_ref == "scene_emd" for item in result.direction.provenance))

    def test_locked_photoreal_conversion_is_not_requested_from_llm(self) -> None:
        backend = FakeDirectionBackend(
            "\n".join(
                (
                    "STYLE\t1\tアニメ風イラストを実写へ変換し、セル影を残さない。",
                    "MOTION\t1\t自然に歩く。",
                    "CAMERA\t1\t正面から追う。",
                )
            )
        )
        result = enhance_direction(
            backend,
            value=DirectionEnhancerInput(style_profile="illust_to_photoreal"),
            system_prompt="fixed",
            runtime_config=LlamaRuntimeConfig(),
        )
        style = result.direction.style_direction[0]
        self.assertEqual(style, STYLE_PROFILES["illust_to_photoreal"])
        self.assertNotIn("アニメ", style)
        self.assertNotIn("イラスト", style)
        payload = json.loads(backend.calls[0]["payload"])
        self.assertEqual(payload["requested_records"], [])
        style_output = next(
            item
            for item in result.direction.provenance
            if item.target == "style_direction[0]"
        )
        self.assertEqual(style_output.source, "profile")
        self.assertEqual(style_output.reason, "profile_enforced")

    def test_motion_and_camera_profiles_own_their_typed_fields(self) -> None:
        backend = FakeDirectionBackend(
            "\n".join(
                (
                    "STYLE\t1\t映画的なセルアニメとして描く。",
                    "MOTION\t1\t足袋を地面へ滑らせる。",
                    "CAMERA\t1\t足袋を固定カメラで拡大する。",
                )
            )
        )
        result = enhance_direction(
            backend,
            value=DirectionEnhancerInput(
                style_profile="anime_story_mv",
                motion_profile="anime_story_mv",
                camera_profile="anime_story_mv",
            ),
            system_prompt="fixed",
            runtime_config=LlamaRuntimeConfig(),
        )
        self.assertEqual(
            result.direction.motion_direction,
            (MOTION_PROFILES["anime_story_mv"],),
        )
        self.assertEqual(
            result.direction.camera_direction,
            (CAMERA_PROFILES["anime_story_mv"],),
        )
        enforced = {
            item.source_ref
            for item in result.direction.provenance
            if item.record_kind == "output"
            and item.reason == "profile_enforced"
        }
        self.assertEqual(enforced, {"anime_story_mv"})
        self.assertEqual(
            json.loads(backend.calls[0]["payload"])["requested_records"],
            [],
        )

    def test_reference_cinematic_keeps_generated_style_and_is_not_locked(self) -> None:
        payload = json.loads(
            build_direction_payload(
                DirectionEnhancerInput(style_profile="reference_cinematic")
            )
        )
        self.assertFalse(payload["profiles"]["style"]["locked"])
        self.assertEqual(
            payload["profiles"]["style"]["text"],
            "参照画像の人物設計を保ち、自然な皮膚・布・材質、映画照明、"
            "レンズによる奥行きで実写映画として描く。",
        )

    def test_system_prompt_keeps_target_treatment_first(self) -> None:
        system_prompt = (
            Path(__file__).parents[1]
            / "prompts"
            / "direction_enhancer_system_prompt.txt"
        ).read_text(encoding="utf-8")
        self.assertIn(
            "STYLE must begin with the target visual medium or rendering treatment.",
            system_prompt,
        )
        self.assertIn("profiles.style.locked is true", system_prompt)
        self.assertIn("Python-owned exact output", system_prompt)
        self.assertIn("Do not emit MOTION or CAMERA", system_prompt)
        self.assertIn("Never put a reference-image", system_prompt)
        self.assertIn("source residue, not scene authority", system_prompt)
        self.assertIn("reference-capture condition", system_prompt)
        self.assertIn("keep ENVIRONMENT free of lighting", system_prompt)
        self.assertNotIn("foxfire", system_prompt)
        self.assertIn("Do not invent scene-specific examples", system_prompt)
        self.assertIn("scene_context.environment", system_prompt)
        self.assertIn("functional spatial topology", system_prompt)
        self.assertIn("never move one onto a route's centerline", system_prompt)
        self.assertIn("explicitly selects that exact object", system_prompt)

    def test_anime_story_mv_is_an_emotional_baseline_copy(self) -> None:
        from core.direction.profiles import (
            CAMERA_PLANNER_POLICIES,
            MOTION_PERFORMANCE_MODES,
            RENDER_PROMPTS,
        )

        for profiles in (STYLE_PROFILES, MOTION_PROFILES, CAMERA_PROFILES):
            self.assertEqual(profiles["anime_story_mv"], profiles["anime_emotional_mv"])
        self.assertEqual(MOTION_PERFORMANCE_MODES["anime_story_mv"], "dance_phrase")
        self.assertEqual(CAMERA_PLANNER_POLICIES["anime_story_mv"], "anime_emotional_mv")
        for kind in ("motion", "camera"):
            self.assertEqual(
                RENDER_PROMPTS[kind]["anime_story_mv"],
                RENDER_PROMPTS[kind]["anime_emotional_mv"],
            )

    def test_all_passthrough_skips_inference_and_keeps_exact_text(self) -> None:
        backend = FakeDirectionBackend()
        source = """# 保持分析
* `サブジェクト1`: `partially_preserved` 髪と衣装だけを保持する。

# 共通プロンプト
## スタイル
* フォトリアルな実写ビデオ。
## モーション
* 小さな自然動作。
## カメラ
* 固定カメラ。
## その他
* 夜明け前。
"""
        value = DirectionEnhancerInput(
            concept_emd="# サブジェクト\n* `画像1` 狐耳の少女。\n",
            style_profile=PASSTHROUGH_PROFILE,
            motion_profile=PASSTHROUGH_PROFILE,
            camera_profile=PASSTHROUGH_PROFILE,
            retention_policy="passthrough",
            direction_emd_passthrough=source,
        )
        result = enhance_direction(
            backend,
            value=value,
            system_prompt="",
            runtime_config=LlamaRuntimeConfig(),
        )
        self.assertFalse(backend.calls)
        self.assertEqual(result.direction.style_direction, ("フォトリアルな実写ビデオ。",))
        self.assertEqual(
            result.direction.retention_lines,
            (
                "`サブジェクト1`: `partially_preserved` "
                "髪と衣装だけを保持する。",
            ),
        )
        self.assertEqual(result.direction.retention_policy, "passthrough")
        self.assertIn("# 保持分析", result.direction_emd_preview)
        self.assertTrue(
            all(
                item.reason == "passthrough_enforced"
                for item in result.direction.provenance
                if item.record_kind == "output"
            )
        )

    def test_mixed_passthrough_requests_only_unowned_records(self) -> None:
        backend = FakeDirectionBackend(
            "MOTION\t1\t自然に歩く。\nCAMERA\t1\t正面から追う。"
        )
        value = DirectionEnhancerInput(
            style_profile=PASSTHROUGH_PROFILE,
            direction_emd_passthrough=(
                "# 共通プロンプト\n## スタイル\n* 手書きの固定文。\n"
            ),
        )
        result = enhance_direction(
            backend,
            value=value,
            system_prompt="fixed",
            runtime_config=LlamaRuntimeConfig(),
        )
        payload = json.loads(backend.calls[0]["payload"])
        self.assertEqual(payload["requested_records"], [])
        self.assertNotIn("style", payload["profiles"])
        self.assertEqual(result.direction.style_direction, ("手書きの固定文。",))

    def test_node_all_passthrough_never_resolves_a_model(self) -> None:
        node = NODE_CLASS_MAPPINGS["MVDirectorDirectionEnhancer"]()
        source = """# 共通プロンプト
## スタイル
* 実写。
## モーション
* 自然な動作。
## カメラ
* 固定。
"""
        with patch(
            "nodes.node_direction_enhancer.node.resolve_comfy_gguf_model",
            side_effect=AssertionError("model resolution must be skipped"),
        ):
            direction, preview, status = node.enhance(
                user_request="",
                style_profile=PASSTHROUGH_PROFILE,
                motion_profile=PASSTHROUGH_PROFILE,
                camera_profile=PASSTHROUGH_PROFILE,
                model_name="missing.gguf",
                chat_format="",
                max_tokens=768,
                temperature=0.2,
                top_p=0.9,
                repetition_penalty=1.05,
                gpu_layers=-1,
                n_batch=512,
                n_ctx=16384,
                flash_attn=True,
                kv_cache_type="q8_0",
                op_offload=True,
                keep_model_loaded=True,
                seed=1,
                cache_mode="reuse",
                retention_policy="compiler_default",
                direction_emd_passthrough=source,
            )
        self.assertEqual(direction.style_direction, ("実写。",))
        self.assertIn("## カメラ", preview)
        self.assertIn("model=not_loaded", status)

    def test_passthrough_rejects_undefined_retention_subject(self) -> None:
        with self.assertRaisesRegex(ValueError, "undefined サブジェクト2"):
            parse_direction_passthrough(
                "# 保持分析\n* `サブジェクト2`: `fully_preserved` 保持する。",
                concept_emd="# サブジェクト\n* 主人公。",
            )

    def test_missing_required_slot_gets_one_local_retry(self) -> None:
        backend = FakeDirectionBackend(
            "CAMERA\t1\tカメラ。",
            "STYLE\t1\t画風。",
        )
        result = enhance_direction(
            backend,
            value=DirectionEnhancerInput(style_profile="reference_cinematic"),
            system_prompt="fixed",
            runtime_config=LlamaRuntimeConfig(),
        )
        self.assertEqual(len(backend.calls), 2)
        retry = json.loads(backend.calls[1]["payload"])
        self.assertEqual(retry["retry"], "missing_slots_only")
        self.assertEqual(retry["missing"], [["STYLE", 1]])
        self.assertEqual(result.retried_missing, (("STYLE", 1),))
        self.assertEqual(result.direction.style_direction, ("画風。",))
        self.assertEqual(len(result.issues), 1)
        self.assertEqual(result.issues[0].reason, "unknown_type")
        self.assertIn("画風。", result.direction_emd_preview)

    def test_missing_after_retry_stops(self) -> None:
        backend = FakeDirectionBackend("CAMERA\t1\tカメラ。", "OTHER\t1\tその他。")
        with self.assertRaisesRegex(DirectionEnhancerError, "STYLE:1"):
            enhance_direction(
                backend,
                value=DirectionEnhancerInput(style_profile="reference_cinematic"),
                system_prompt="fixed",
                runtime_config=LlamaRuntimeConfig(),
            )
        self.assertEqual(len(backend.calls), 2)

    def test_invalid_lines_are_discard_provenance_without_retry(self) -> None:
        backend = FakeDirectionBackend("preamble\n" + VALID + "\nSTYLE\t1\t別案")
        result = enhance_direction(
            backend,
            value=DirectionEnhancerInput(
                user_request="夜間",
                style_profile="reference_anime",
                motion_profile="natural_performance",
                camera_profile="readable_depth",
            ),
            system_prompt="fixed",
            runtime_config=LlamaRuntimeConfig(),
        )
        self.assertEqual(len(backend.calls), 1)
        discarded = [
            item
            for item in result.direction.provenance
            if item.record_kind == "discard"
        ]
        self.assertEqual(
            sum(item.reason == "invalid_line_record" for item in discarded),
            4,
        )
        self.assertEqual(
            sum(item.reason == "profile_overridden" for item in discarded),
            0,
        )
        self.assertNotIn("preamble", result.direction_emd_preview)
        self.assertNotIn("別案", result.direction_emd_preview)

    def test_concept_adapter_rejects_complete_emd(self) -> None:
        value = DirectionEnhancerInput(
            concept_emd="# サブジェクト\n* 主人公。\n# シーン 00:00.000 --> 00:01.000"
        )
        with self.assertRaisesRegex(DirectionEnhancerError, "one # サブジェクト"):
            value.validate()

    def test_profile_surface_is_fixed(self) -> None:
        self.assertEqual(
            set(STYLE_PROFILES),
            {
                "reference_anime",
                "anime_story_mv",
                "anime_emotional_mv",
                "reference_cinematic",
                "illust_to_photoreal",
                "reference_painterly",
            },
        )
        self.assertEqual(
            set(MOTION_PROFILES),
            {
                "natural_performance", "expressive_mv", "limited_animation",
                "cinema_mv", "anime_story_mv",
                "anime_emotional_mv", "anime_choreography_mv",
            },
        )
        self.assertEqual(
            set(CAMERA_PROFILES),
            {
                "readable_depth", "cinematic_depth", "rhythmic_mv",
                "cinema_mv", "anime_story_mv",
                "anime_emotional_mv",
            },
        )
        camera = CAMERA_PROFILES["anime_story_mv"]
        self.assertIn("同じ軌道の反復にせず", camera)
        self.assertIn("60度から120度の経路", camera)
        self.assertIn("顔へのZoom In", camera)
        self.assertIn("Tracking Shot", camera)
        self.assertIn("Pedestal Up", camera)
        self.assertIn("両目、両眉、鼻、口全体", camera)
        self.assertIn("二コマ打ち又は三コマ打ち", MOTION_PROFILES["anime_story_mv"])
        self.assertIn("短いアクセント", MOTION_PROFILES["anime_story_mv"])
        self.assertIn("横への踏み替え", MOTION_PROFILES["anime_story_mv"])
        self.assertIn("時間方向に連続", MOTION_PROFILES["anime_story_mv"])
        self.assertIn("痙攣状motion", MOTION_PROFILES["anime_story_mv"])
        self.assertIn("短いポーズ保持", MOTION_PROFILES["cinema_mv"])
        self.assertIn("移動が不要なら静止構図", CAMERA_PROFILES["cinema_mv"])
        self.assertIn("reference_anime", STYLE_PROFILES)
        self.assertIn("動物耳、耳内部、尾", STYLE_PROFILES["anime_story_mv"])
        self.assertIn("局所的なglow、bloom", STYLE_PROFILES["anime_story_mv"])
        self.assertIn("古傷", STYLE_PROFILES["anime_story_mv"])
        self.assertIn("完成EMDのShotが可視の状態として明示", STYLE_PROFILES["anime_story_mv"])
        self.assertIn("cinema_mv", DIRECTION_PRESETS)
        self.assertIn("概ね半数", CAMERA_PROFILES["anime_emotional_mv"])
        self.assertIn("2.5秒以上", CAMERA_PROFILES["anime_emotional_mv"])
        self.assertIn(
            "Arc Shot with large amplitude at fast speed",
            CAMERA_PROFILES["anime_emotional_mv"],
        )
        from core.direction.profiles import MOTION_PERFORMANCE_MODES
        self.assertEqual(MOTION_PERFORMANCE_MODES["anime_emotional_mv"], "dance_phrase")
        self.assertIn(
            "つま先は親指側と残り四趾側の二つの連続した布形状",
            STYLE_PROFILES["anime_emotional_mv"],
        )
        self.assertIn(
            "滑らかで不透明な白いsplit-toe足袋",
            STYLE_PROFILES["anime_emotional_mv"],
        )
        self.assertIn("単なる歩行", MOTION_PROFILES["anime_emotional_mv"])
        self.assertIn("短い閉眼、半開き、伏し目", MOTION_PROFILES["anime_emotional_mv"])
        self.assertIn("そのSceneの元歌詞", MOTION_PROFILES["anime_emotional_mv"])
        self.assertNotIn("苔", MOTION_PROFILES["anime_emotional_mv"])
        self.assertNotIn("狐火", MOTION_PROFILES["anime_emotional_mv"])
        self.assertNotIn("灯籠", MOTION_PROFILES["anime_emotional_mv"])
        self.assertGreaterEqual(len(DIRECTION_PRESETS), 5)

    def test_environment_and_time_lighting_records_are_separate(self) -> None:
        backend = FakeDirectionBackend(
            VALID
            + "\nENVIRONMENT\t1\t苔むした大樹と石段がある森。"
            + "\nTIME_LIGHTING\t1\t深夜。青白い月光で照らす。"
        )
        result = enhance_direction(
            backend,
            value=DirectionEnhancerInput(user_request="昼の画像を深夜として描く。"),
            system_prompt="fixed",
            runtime_config=LlamaRuntimeConfig(),
        )
        self.assertEqual(result.direction.environment_direction, ("苔むした大樹と石段がある森。",))
        self.assertEqual(result.direction.time_lighting_direction, ("深夜。青白い月光で照らす。",))
        self.assertIn("## 環境", result.direction_emd_preview)
        self.assertIn("## 時間・照明", result.direction_emd_preview)

    def test_public_node_mapping_and_socket_surface(self) -> None:
        self.assertIn("MVDirectorDirectionEnhancer", NODE_CLASS_MAPPINGS)
        inputs = NODE_CLASS_MAPPINGS["MVDirectorDirectionEnhancer"].INPUT_TYPES()
        self.assertEqual(next(iter(inputs["required"])), "retention_policy")
        self.assertIn("style_profile", inputs["required"])
        self.assertIn("n_ctx", inputs["required"])
        self.assertEqual(
            inputs["required"]["seed"][1]["control_after_generate"],
            "randomize",
        )
        self.assertIn("concept_emd", inputs["optional"])
        self.assertIn("scene_emd", inputs["optional"])
        self.assertNotIn("observations_json", inputs["optional"])
        self.assertIn("direction_emd_passthrough", inputs["optional"])
        self.assertTrue(
            inputs["optional"]["direction_emd_passthrough"][1]["forceInput"]
        )
        self.assertIn("retention_policy", inputs["required"])
        self.assertIn(
            PASSTHROUGH_PROFILE, inputs["required"]["style_profile"][0]
        )
        self.assertEqual(
            inputs["required"]["style_profile"][1]["default"],
            "anime_emotional_mv",
        )
        self.assertEqual(
            inputs["required"]["motion_profile"][1]["default"],
            "anime_emotional_mv",
        )
        self.assertEqual(
            inputs["required"]["camera_profile"][1]["default"],
            "anime_emotional_mv",
        )


if __name__ == "__main__":
    unittest.main()
