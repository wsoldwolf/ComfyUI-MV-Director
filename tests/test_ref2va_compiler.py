from pathlib import Path
import json
import unittest

from core.compiler import CompilerError, compile_ref2va
from core.h3_contract import (
    ANIME_EMOTIONAL_FACE_PERFORMANCE_CUT_CAMERA,
    ANIME_EMOTIONAL_FACE_PERFORMANCE_CUT_CAMERA_H3,
    FACE_PERFORMANCE_CUT_ACTION,
    FACE_PERFORMANCE_CUT_ACTION_H3,
    FACE_PERFORMANCE_CUT_CAMERA,
    FACE_PERFORMANCE_CUT_CAMERA_H3,
    H3TimingProfile,
)


FIXTURES = Path(__file__).parent / "fixtures" / "emd"


class EchoTranslator:
    def translate(self, units):
        return tuple(f"EN:{unit}" for unit in units)


class ShortTranslator:
    def translate(self, units):
        return tuple(units[:-1])


class ReferenceMutatingTranslator:
    def translate(self, units):
        if any("<Video 1>" in unit for unit in units):
            raise AssertionError("protected video reference reached translator")
        return tuple(unit.replace("<Video 1>", "<Video 9>") for unit in units)


class CameraDirectiveMutatingTranslator:
    def translate(self, units):
        if any(
            directive in unit
            for unit in units
            for directive in (
                ANIME_EMOTIONAL_FACE_PERFORMANCE_CUT_CAMERA,
                FACE_PERFORMANCE_CUT_ACTION,
                FACE_PERFORMANCE_CUT_CAMERA,
                "Arc Shot",
                "with large amplitude",
                "at fast speed",
            )
        ):
            raise AssertionError("protected H3 camera directive reached translator")
        return tuple(
            "EN:"
            + unit.replace("Arc Shot", "Orbiting camera")
            .replace("with large amplitude", "widely")
            .replace("at fast speed", "quickly")
            for unit in units
        )


class Ref2VACompilerTests(unittest.TestCase):
    def test_plan_json_is_pretty_printed_deterministically(self) -> None:
        source = (FIXTURES / "canonical_ref2va.emd").read_text(encoding="utf-8")
        result = compile_ref2va(source, EchoTranslator())

        rendered = result.plan_json()
        self.assertEqual(result.plan["defaults"]["steps"], 8)
        self.assertTrue(rendered.endswith("\n"))
        self.assertTrue(rendered.startswith('{\n  "defaults": {\n'))
        self.assertIn('\n  "shots": [\n    {\n', rendered)
        self.assertIn("実写映画として描写する。", rendered)
        self.assertNotIn("\\u5b9f", rendered)
        self.assertEqual(json.loads(rendered), result.plan)

    def test_canonical_document_compiles_to_six_sections(self) -> None:
        source = (FIXTURES / "canonical_ref2va.emd").read_text(encoding="utf-8")
        result = compile_ref2va(source, EchoTranslator())

        plan = result.plan
        self.assertEqual(
            plan["prompt_prefix"],
            [
                "EN:実写映画として描写する。",
                "EN:深い森の神社を背景にする。",
                "EN:夜の月光に統一する。",
                "EN:接地と重心移動が読める連続動作にする。",
                "EN:前景と背景の視差を使う。",
                "EN:画面内に文字を出さない。",
            ],
        )
        scene = plan["shots"][0]
        self.assertEqual(scene["id"], "scene_0001")
        self.assertEqual(scene["length"], 243)
        self.assertNotIn("duration_seconds", scene)
        self.assertNotIn("duration_ms", scene)
        self.assertEqual(
            [line for line in scene["prompt"] if line.endswith(":")],
            [
                "subject_definitions:",
                "summary:",
                "retention_analysis:",
                "detailed_description:",
                "overall_soundscape:",
                "non_diegetic_music:",
            ],
        )
        second_shot = next(
            line for line in scene["prompt"] if line.startswith("[Shot 2]")
        )
        self.assertIn(
            "[Shot 2] At 00:05.000, <Subject 1> EN:は立ち止まり正面を向く。",
            second_shot,
        )
        self.assertIn(
            "<Subject 1> performs visible lip movements to "
            "<d>[Japanese]千年鳥居をくぐるそなたよ</d>.",
            second_shot,
        )
        self.assertNotIn("VERSE1", "\n".join(scene["prompt"]))
        self.assertEqual(result.required_references.references, ())

    def test_scene_setting_compiles_environment_picture_without_subject(self) -> None:
        source = """# サブジェクト
* `画像1` 狐巫女。
# シーン設定
## 環境
* 森の中の神社境内。
## 時間・照明
* 昼の自然光。
## 背景参照
* `画像2`
# 共通プロンプト
## 時間・照明
* 夜間の月明かりを優先する。
> `シーン` 1
# シーン 00:00.000 --> 00:01.000
* `H3長` 22
## ショット 00:00.000
* `サブジェクト1`が鳥居を見上げる。
"""
        result = compile_ref2va(source, EchoTranslator())
        self.assertEqual(
            result.plan["prompt_prefix"],
            [
                "EN:森の中の神社境内。",
                "EN:昼の自然光。",
                "EN:夜間の月明かりを優先する。",
            ],
        )
        prompt = result.plan["shots"][0]["prompt"]
        self.assertTrue(
            any(line.startswith("<Picture 2> is the environment reference:") for line in prompt)
        )
        self.assertTrue(
            any(line.startswith("<Picture 2>: environment_partially_preserved") for line in prompt)
        )
        references = result.required_references.to_dict()["references"]
        environment = next(
            item for item in references if item["purpose"] == "environment_reference"
        )
        self.assertEqual(environment["h3_ref"], "<Picture 2>")
        self.assertEqual(environment["required_input"], "ref_images.ref_image_1")
        self.assertNotIn("concept_id", environment)
        self.assertNotIn("subject_ref", environment)

    def test_already_english_prompt_is_passed_through_exactly(self) -> None:
        source = """# サブジェクト
* 人物。
# 共通プロンプト
## スタイル
* photorealistic video.
> `シーン` 1
# シーン 00:00.000 --> 00:01.000
* `H3長` 22
## ショット 00:00.000
* 歩く。
"""
        result = compile_ref2va(source, EchoTranslator())
        self.assertEqual(result.plan["prompt_prefix"][0], "photorealistic video.")
        self.assertNotIn("EN:photorealistic video.", result.plan_json())

    def test_subject_media_and_lip_sync_audio_require_slots(self) -> None:
        source = """# サブジェクト
* `画像3` `動画1` `音声3` 主人公。
> `シーン` 1
# シーン 00:00.000 --> 00:01.000
* `H3長` 22
## ショット 00:00.000
* `サブジェクト1`は歌う。
## 音響
* `リップシンク` `Audio参照` `サブジェクト1` `音声2`
"""
        result = compile_ref2va(source, EchoTranslator())
        references = result.required_references.to_dict()["references"]
        self.assertEqual(
            [item["required_input"] for item in references],
            [
                "ref_images.ref_image_2",
                "ref_videos.ref_video_0",
                "ref_audios.ref_audio_2",
                "ref_audios.ref_audio_1",
            ],
        )
        prompt = result.plan["shots"][0]["prompt"]
        self.assertIn(
            "<Subject 1> performs visible lip movements synchronized to <Audio 2>.",
            prompt,
        )
        self.assertNotIn("source_audio_target", result.plan["shots"][0])

    def test_default_reference_prompt_uses_subject_only_retention(self) -> None:
        source = """# サブジェクト
* `画像1` 狐耳の少女
> `シーン` 1
# シーン 00:00.000 --> 00:01.000
* `H3長` 22
## ショット 00:00.000
* 踊る。
"""
        prompt = compile_ref2va(source, EchoTranslator()).plan["shots"][0]["prompt"]
        self.assertIn(
            "<Subject 1> is described here: EN:狐耳の少女. "
            "Every explicitly described local shape, count, placement, scale, "
            "color, material, and exclusion is a literal identity constraint. "
            "Never normalize an unusual facial, anatomical, garment, or "
            "accessory feature into a conventional default. "
            "Use these connected references only for its visual identity and "
            "design: <Picture 1>. Treat every panel or alternate view as identity "
            "material for the same single physical instance. Render exactly one "
            "physical instance of this Subject, with one head and one body. Never "
            "show a duplicate, twin, clone, reflection, background lookalike, "
            "inset view, split-screen copy, or second representation of this "
            "Subject. "
            "Do not copy a reference pose, framing, composition, panel layout, "
            "or background; follow the current Shot instead. The reference is "
            "identity evidence, not a storyboard, montage, or layout template. "
            "Render one unified full-frame continuous camera view that fills the "
            "entire image. Never create an internal border, seam, divider, panel, "
            "inset, picture-in-picture, side-by-side view, or simultaneous "
            "alternate angle. If the reference contains multiple views, fuse "
            "only compatible identity features into this one view. Camera angle "
            "and framing changes must happen over time or at a scene cut, never "
            "simultaneously within one frame. The current Scene environment and "
            "time-lighting directions are the sole authority for the rendered "
            "world and fully replace every background and illumination visible "
            "inside this identity reference. Treat any blank or white studio field, daylight, "
            "backdrop, panel-specific setting, or other conflicting reference "
            "environment as non-renderable source residue. Continue the specified "
            "Scene environment across the entire frame, including behind and "
            "around the Subject. Generate a newly staged Shot from the current "
            "action and camera instructions. The first output frame must already "
            "use the new Shot-specific body pose, gaze, blocking, framing, "
            "viewpoint, camera height, and camera distance. Never show, "
            "reconstruct, paste, hold, or transition from the reference image "
            "itself as a frame, still, plate, poster, inset, background, or "
            "composition. Keep visible skin and clothing clean and intact "
            "unless an author-written Shot explicitly requires a physical "
            "condition. Lyric text inside <d> is vocal content only: figurative "
            "words about wounds, scars, pain, blood, or a broken heart never "
            "authorize a visible cut, scar, bruise, bleeding, bandage, lesion, "
            "stain, tattoo-like mark, torn skin, or damaged clothing.",
            prompt,
        )
        summary_index = prompt.index("summary:")
        self.assertEqual(prompt[summary_index + 1], "[reference generation] EN:踊る。")
        retention_index = prompt.index("retention_analysis:")
        detailed_index = prompt.index("detailed_description:")
        retention = [line for line in prompt[retention_index + 1:detailed_index] if line]
        self.assertEqual(
            retention,
            [
                "<Subject 1>: fully_preserved - preserve the described identity "
                "and attributes across shots. Preserve every stated local shape, "
                "count, placement, scale, color, material, and exclusion literally; "
                "never replace an unusual feature with a conventional default."
            ],
        )
        self.assertNotIn("<Picture 1>", "\n".join(retention))

    def test_scene_time_lighting_replaces_reference_background(self) -> None:
        source = """# サブジェクト
* `画像1` 狐耳の少女
# 共通プロンプト
## 時間・照明
* シーン全編を通して時刻は夜間である。
* 月明りが照している。
> `シーン` 1
# シーン 00:00.000 --> 00:01.000
* `H3長` 22
## ショット 00:00.000
* 鳥居の前で歌う。
"""
        plan = compile_ref2va(source, EchoTranslator()).plan

        self.assertEqual(
            plan["prompt_prefix"],
            [
                "EN:シーン全編を通して時刻は夜間である。",
                "EN:月明りが照している。",
            ],
        )
        subject_definition = plan["shots"][0]["prompt"][1]
        self.assertIn(
            "time-lighting directions are the sole authority",
            subject_definition,
        )
        self.assertIn(
            "fully replace every background and illumination visible inside this identity reference",
            subject_definition,
        )
        self.assertIn("blank or white studio field", subject_definition)
        self.assertIn("across the entire frame", subject_definition)
        self.assertIn("Generate a newly staged Shot", subject_definition)
        self.assertIn("The first output frame must already use", subject_definition)
        self.assertIn("reference image itself", subject_definition)

    def test_silence_is_an_explicit_flag(self) -> None:
        source = """# サブジェクト
* 人物。
> `シーン` 1
# シーン 00:00.000 --> 00:01.000
* `H3長` 22
## ショット 00:00.000
* 静止する。
## 音響
* `無音`
"""
        scene = compile_ref2va(source, EchoTranslator()).plan["shots"][0]
        self.assertEqual(scene["source_reference"], "off")
        self.assertEqual(scene["generated_continuity"], "off")
        self.assertEqual(scene["source_audio_target"], "off")
        self.assertIn(
            "Complete silence. No speech, music, ambience, or sound effects.",
            scene["prompt"],
        )

    def test_dialogue_and_explicit_d_spans_are_not_translated(self) -> None:
        source = """# サブジェクト
* 人物。
> `シーン` 1
# シーン 00:00.000 --> 00:01.000
* `H3長` 22
## ショット 00:00.000
* `サブジェクト1`は「こんにちは」と言い、<d>[English]Goodbye.</d> と続ける。
"""
        prompt = compile_ref2va(source, EchoTranslator()).plan["shots"][0]["prompt"]
        text = "\n".join(prompt)
        self.assertIn("<d>[Japanese]こんにちは</d>", text)
        self.assertIn("<d>[English]Goodbye.</d>", text)
        self.assertNotIn("EN:<d>", text)

    def test_translator_must_return_one_output_per_unit(self) -> None:
        source = (FIXTURES / "canonical_ref2va.emd").read_text(encoding="utf-8")
        with self.assertRaisesRegex(CompilerError, "returned .* units"):
            compile_ref2va(source, ShortTranslator())

    def test_video_reference_is_an_opaque_translation_span(self) -> None:
        source = """# サブジェクト
* 人物。
> `シーン` 1
# シーン 00:00.000 --> 00:01.000
* `H3長` 22
## ショット 00:00.000
* `サブジェクト1`は`動画1`の動作とカメラ軌道を使う。
"""
        result = compile_ref2va(source, ReferenceMutatingTranslator())
        prompt = "\n".join(result.plan["shots"][0]["prompt"])
        self.assertIn("<Video 1>", prompt)
        self.assertNotIn("<Video 9>", prompt)
        self.assertEqual(result.required_references.references, ())

    def test_h3_camera_directives_are_opaque_translation_spans(self) -> None:
        source = """# サブジェクト
* 人物。
> `シーン` 1
# シーン 00:00.000 --> 00:01.000
* `H3長` 22
## ショット 00:00.000
* Arc Shot with large amplitude at fast speed で人物の側面を通る。
"""
        result = compile_ref2va(source, CameraDirectiveMutatingTranslator())
        prompt = "\n".join(result.plan["shots"][0]["prompt"])
        self.assertIn("Arc Shot with large amplitude at fast speed", prompt)
        self.assertNotIn("Orbiting camera", prompt)
        self.assertNotIn("widely", prompt)
        self.assertNotIn("quickly", prompt)

    def test_face_performance_cut_prompts_are_opaque_translation_spans(self) -> None:
        source = f"""# サブジェクト
* 人物。
> `シーン` 1
# シーン 00:00.000 --> 00:01.000
* `H3長` 22
## ショット 00:00.000
* {FACE_PERFORMANCE_CUT_ACTION}
* {FACE_PERFORMANCE_CUT_CAMERA}
* {ANIME_EMOTIONAL_FACE_PERFORMANCE_CUT_CAMERA}
"""
        result = compile_ref2va(source, CameraDirectiveMutatingTranslator())
        prompt = "\n".join(result.plan["shots"][0]["prompt"])
        self.assertIn(FACE_PERFORMANCE_CUT_ACTION_H3, prompt)
        self.assertIn(FACE_PERFORMANCE_CUT_CAMERA_H3, prompt)
        self.assertIn(ANIME_EMOTIONAL_FACE_PERFORMANCE_CUT_CAMERA_H3, prompt)
        self.assertNotIn(FACE_PERFORMANCE_CUT_ACTION, prompt)

    def test_context_loop_mode_sets_only_its_fixed_fields(self) -> None:
        source = """# サブジェクト
* 人物。
# 保持分析
* `サブジェクト1`: `partially_preserved` 顔と衣装を保持する。
> `シーン` 1
# シーン 00:00.000 --> 00:01.000
* `H3長` 22
## ショット 00:00.000
* `サブジェクト1`は歌う。
## 音響
* `リップシンク` `Context Loop` `サブジェクト1`
* `明示台詞のみ`
"""
        scene = compile_ref2va(source, EchoTranslator()).plan["shots"][0]
        self.assertEqual(scene["source_reference"], "off")
        self.assertEqual(scene["generated_continuity"], "off")
        self.assertEqual(scene["source_audio_target"], "locked")
        prompt_text = "\n".join(scene["prompt"])
        self.assertIn(
            "<Subject 1>: partially_preserved - EN:顔と衣装を保持する。",
            prompt_text,
        )
        self.assertIn("locked source vocal", prompt_text)
        self.assertIn("explicitly provided with d tags", prompt_text)

    def test_later_scene_uses_configured_context_length(self) -> None:
        source = """# サブジェクト
* 人物。
> `シーン` 1
# シーン 00:00.000 --> 00:01.000
* `H3長` 22
## ショット 00:00.000
* 歩く。
> `シーン` 2
# シーン 00:01.000 --> 00:02.000 継続
* `H3長` 22
## ショット 00:01.000
* 止まる。
"""
        shots = compile_ref2va(
            source,
            EchoTranslator(),
            timing_profile=H3TimingProfile(
                continuation_context_length=5,
                audio_context_length=3,
            ),
        ).plan["shots"]
        self.assertEqual(shots[0]["context_length"], 0)
        self.assertEqual(shots[1]["context_length"], 5)
        self.assertEqual([shot["audio_context_length"] for shot in shots], [0, 3])
        self.assertNotIn("continuation_mode", shots[0])
        self.assertEqual(shots[1]["continuation_mode"], "guide")


    def test_later_scene_without_continuation_compiles_as_cut(self) -> None:
        source = """# サブジェクト
* 人物。
> `シーン` 1
# シーン 00:00.000 --> 00:01.000
* `H3長` 22
## ショット 00:00.000
* 歩く。
> `シーン` 2
# シーン 00:01.000 --> 00:02.000
* `H3長` 22
## ショット 00:01.000
* 顔のアップへ切り替える。
"""
        shots = compile_ref2va(source, EchoTranslator()).plan["shots"]
        self.assertEqual(
            [(shot["context_length"], shot["audio_context_length"]) for shot in shots],
            [(0, 0), (0, 0)],
        )
        self.assertNotIn("continuation_mode", shots[1])


if __name__ == "__main__":
    unittest.main()
