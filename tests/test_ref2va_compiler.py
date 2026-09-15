from pathlib import Path
import unittest

from core.compiler import CompilerError, compile_ref2va
from core.h3_contract import H3TimingProfile


FIXTURES = Path(__file__).parent / "fixtures" / "emd"


class EchoTranslator:
    def translate(self, units):
        return tuple(f"EN:{unit}" for unit in units)


class ShortTranslator:
    def translate(self, units):
        return tuple(units[:-1])


class ReferenceMutatingTranslator:
    def translate(self, units):
        return tuple(unit.replace("<Video 1>", "<Video 9>") for unit in units)


class Ref2VACompilerTests(unittest.TestCase):
    def test_canonical_document_compiles_to_six_sections(self) -> None:
        source = (FIXTURES / "canonical_ref2va.emd").read_text(encoding="utf-8")
        result = compile_ref2va(source, EchoTranslator())

        plan = result.plan
        self.assertEqual(
            plan["prompt_prefix"],
            [
                "EN:実写映画として描写する。",
                "EN:接地と重心移動が読める連続動作にする。",
                "EN:前景と背景の視差を使う。",
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
            "[Shot 2] At 00:05.000, EN:<Subject 1>は立ち止まり正面を向く。",
            second_shot,
        )
        self.assertIn(
            "<Subject 1> performs visible lip movements to "
            "<d>[Japanese]千年鳥居をくぐるそなたよ</d>.",
            second_shot,
        )
        self.assertNotIn("VERSE1", "\n".join(scene["prompt"]))
        self.assertEqual(result.required_references.references, ())

    def test_picture_and_audio_reference_require_slots(self) -> None:
        source = """# サブジェクト
* `人物1`
* `H3サブジェクト` `<Subject 1>`
* `参照画像` `<Picture 3>`
* 主人公。
> `シーン` 1
# シーン 00:00.000 --> 00:01.000
* `H3長` 22
## ショット 00:00.000
* `人物1`は歌う。
## 音響
* `リップシンク` `Audio参照` `人物1` `H3音声2`
"""
        result = compile_ref2va(source, EchoTranslator())
        references = result.required_references.to_dict()["references"]
        self.assertEqual(
            [item["required_input"] for item in references],
            ["ref_images.ref_image_2", "ref_audios.ref_audio_1"],
        )
        prompt = result.plan["shots"][0]["prompt"]
        self.assertIn(
            "<Subject 1> performs visible lip movements synchronized to <Audio 2>.",
            prompt,
        )
        self.assertNotIn("source_audio_target", result.plan["shots"][0])

    def test_silence_is_an_explicit_flag(self) -> None:
        source = """# サブジェクト
* `人物1`
* `H3サブジェクト` `<Subject 1>`
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
* `人物1`
* `H3サブジェクト` `<Subject 1>`
* 人物。
> `シーン` 1
# シーン 00:00.000 --> 00:01.000
* `H3長` 22
## ショット 00:00.000
* `人物1`は「こんにちは」と言い、<d>[English]Goodbye.</d> と続ける。
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
* `人物1`
* `H3サブジェクト` `<Subject 1>`
* 人物。
> `シーン` 1
# シーン 00:00.000 --> 00:01.000
* `H3長` 22
## ショット 00:00.000
* `人物1`は<Video 1>の動作とカメラ軌道を使う。
"""
        result = compile_ref2va(source, ReferenceMutatingTranslator())
        prompt = "\n".join(result.plan["shots"][0]["prompt"])
        self.assertIn("<Video 1>", prompt)
        self.assertNotIn("<Video 9>", prompt)
        self.assertEqual(result.required_references.references, ())

    def test_context_loop_mode_sets_only_its_fixed_fields(self) -> None:
        source = """# サブジェクト
* `人物1`
* `H3サブジェクト` `<Subject 1>`
* 人物。
# 保持分析
* `人物1`: 顔と衣装を保持する。
> `シーン` 1
# シーン 00:00.000 --> 00:01.000
* `H3長` 22
## ショット 00:00.000
* `人物1`は歌う。
## 音響
* `リップシンク` `Context Loop` `人物1`
* `明示台詞のみ`
"""
        scene = compile_ref2va(source, EchoTranslator()).plan["shots"][0]
        self.assertEqual(scene["source_reference"], "off")
        self.assertEqual(scene["generated_continuity"], "off")
        self.assertEqual(scene["source_audio_target"], "locked")
        prompt_text = "\n".join(scene["prompt"])
        self.assertIn("EN:<Subject 1>: 顔と衣装を保持する。", prompt_text)
        self.assertIn("locked source vocal", prompt_text)
        self.assertIn("explicitly provided with d tags", prompt_text)

    def test_later_scene_uses_configured_context_length(self) -> None:
        source = """# サブジェクト
* `人物1`
* `H3サブジェクト` `<Subject 1>`
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
        self.assertEqual([shot["audio_context_length"] for shot in shots], [3, 3])


if __name__ == "__main__":
    unittest.main()
