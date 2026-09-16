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
        self.assertEqual(result.direction.style_direction[0], "実写映画として自然な材質と奥行きで描く。")
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
            "STYLE\t1\t画風。\tMOTION\t2\t動作。\tCAMERA\t3\tカメラ。"
        )
        result = enhance_direction(
            backend,
            value=DirectionEnhancerInput(),
            system_prompt="fixed",
            runtime_config=LlamaRuntimeConfig(),
        )
        self.assertEqual(len(backend.calls), 1)
        self.assertEqual(result.direction.style_direction, ("画風。",))
        self.assertEqual(result.direction.motion_direction, ("動作。",))
        self.assertEqual(result.direction.camera_direction, ("カメラ。",))
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
            ["user", "vision_concept", "profile", "generated"],
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

    def test_locked_photoreal_conversion_mechanically_overrides_llm_paraphrase(self) -> None:
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
        self.assertTrue(
            any(
                item.record_kind == "discard"
                and item.reason == "profile_overridden"
                for item in result.direction.provenance
            )
        )
        style_output = next(
            item
            for item in result.direction.provenance
            if item.target == "style_direction[0]"
        )
        self.assertEqual(style_output.source, "profile")
        self.assertEqual(style_output.reason, "profile_enforced")

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
        self.assertEqual(payload["requested_records"], ["MOTION", "CAMERA"])
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
            "STYLE\t1\t画風。\nCAMERA\t1\tカメラ。",
            "STYLE\t1\t再掲しない。\nMOTION\t1\t動作。",
        )
        result = enhance_direction(
            backend,
            value=DirectionEnhancerInput(),
            system_prompt="fixed",
            runtime_config=LlamaRuntimeConfig(),
        )
        self.assertEqual(len(backend.calls), 2)
        retry = json.loads(backend.calls[1]["payload"])
        self.assertEqual(retry["retry"], "missing_slots_only")
        self.assertEqual(retry["missing"], [["MOTION", 1]])
        self.assertEqual(result.retried_missing, (("MOTION", 1),))
        self.assertEqual(result.direction.motion_direction, ("動作。",))
        self.assertEqual(len(result.issues), 1)
        self.assertEqual(result.issues[0].reason, "unknown_type")
        self.assertNotIn("再掲しない", result.direction_emd_preview)

    def test_missing_after_retry_stops(self) -> None:
        backend = FakeDirectionBackend("STYLE\t1\t画風。", "CAMERA\t1\tカメラ。")
        with self.assertRaisesRegex(DirectionEnhancerError, "MOTION:1"):
            enhance_direction(
                backend,
                value=DirectionEnhancerInput(),
                system_prompt="fixed",
                runtime_config=LlamaRuntimeConfig(),
            )
        self.assertEqual(len(backend.calls), 2)

    def test_invalid_lines_are_discard_provenance_without_retry(self) -> None:
        backend = FakeDirectionBackend("preamble\n" + VALID + "\nSTYLE\t1\t別案")
        result = enhance_direction(
            backend,
            value=DirectionEnhancerInput(user_request="夜間"),
            system_prompt="fixed",
            runtime_config=LlamaRuntimeConfig(),
        )
        self.assertEqual(len(backend.calls), 1)
        discarded = [
            item
            for item in result.direction.provenance
            if item.record_kind == "discard"
        ]
        self.assertEqual(len(discarded), 2)
        self.assertTrue(all(item.reason == "invalid_line_record" for item in discarded))
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
                "reference_cinematic",
                "illust_to_photoreal",
                "reference_painterly",
            },
        )
        self.assertEqual(
            set(MOTION_PROFILES),
            {"natural_performance", "expressive_mv", "limited_animation"},
        )
        self.assertEqual(
            set(CAMERA_PROFILES),
            {"readable_depth", "cinematic_depth", "rhythmic_mv", "arc_closeup"},
        )
        arc = CAMERA_PROFILES["arc_closeup"]
        self.assertIn("arc", arc)
        self.assertIn("close-up", arc)
        self.assertIn("時計回り・反時計回り", arc)
        self.assertEqual(len(DIRECTION_PRESETS), 3)

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
        self.assertIn("observations_json", inputs["optional"])
        self.assertIn("direction_emd_passthrough", inputs["optional"])
        self.assertTrue(
            inputs["optional"]["direction_emd_passthrough"][1]["forceInput"]
        )
        self.assertIn("retention_policy", inputs["required"])
        self.assertIn(
            PASSTHROUGH_PROFILE, inputs["required"]["style_profile"][0]
        )


if __name__ == "__main__":
    unittest.main()
