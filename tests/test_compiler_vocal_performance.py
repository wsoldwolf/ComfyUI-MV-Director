"""Keep explicit vocal performance separate from authored Action/Camera."""
import unittest

from core.compiler import IdentityTranslator, compile_ref2va


SOURCE = """# サブジェクト
* `画像1` A performer wearing a white coat.
* `画像2` A second performer wearing a blue coat.
# 共通プロンプト
## カメラ
* Keep a frontal view of the singing mouth.
> `シーン` 1
# シーン 00:00.000 --> 00:10.125
* `H3長` 243
## ショット 00:00.000
* `演技` The performer extends one arm and looks toward the light.
* `カメラ` Arc Shot from the side toward a three-quarter front view.
## ショット 00:05.000
* `演技` The performer lowers the hand and smiles.
* `カメラ` Pull Out to show the upper body.
"""


def compile_audio(directive=""):
    source = SOURCE + ("## 音響\n" + directive + "\n" if directive else "")
    return compile_ref2va(source, IdentityTranslator()).plan


class CompilerVocalPerformanceTests(unittest.TestCase):
    def test_context_loop_keeps_authored_shots_and_binds_only_target_subject(self):
        original = compile_audio()
        plan = compile_audio("* `リップシンク` `Context Loop` `サブジェクト2`")
        scene = plan["shots"][0]
        prompt = scene["prompt"]
        expected = (
            "Use the locked source vocal as the lip-sync timing target for <Subject 2>. "
            "<Subject 2> visibly sings the supplied vocal throughout its voiced "
            "phrases, with continuous syllable-by-syllable lip and jaw "
            "movements synchronized to that vocal, while performing the "
            "specified body actions."
        )
        self.assertEqual(prompt[prompt.index("overall_soundscape:") + 1], expected)
        self.assertEqual("\n".join(prompt).count("visibly sings"), 1)
        self.assertNotIn("<Subject 1> visibly sings", "\n".join(prompt))
        self.assertEqual(
            [line for line in prompt if line.startswith("[Shot")],
            [line for line in original["shots"][0]["prompt"] if line.startswith("[Shot")],
        )
        # The general camera must still yield to each authored camera.
        self.assertNotIn("Keep a frontal view", "\n".join(prompt))
        self.assertEqual(plan.get("prompt_prefix"), original.get("prompt_prefix"))
        self.assertEqual(scene["source_audio_target"], "locked")
        self.assertEqual(scene["source_reference"], "off")
        self.assertEqual(scene["generated_continuity"], "off")
        self.assertEqual(scene["length"], original["shots"][0]["length"])

    def test_other_audio_modes_never_request_source_vocal_singing(self):
        for directive in (
            "", "* `無音`", "* `明示台詞のみ`",
            "* `リップシンク` `Audio参照` `サブジェクト2` `音声1`",
        ):
            with self.subTest(directive=directive):
                scene = compile_audio(directive)["shots"][0]
                self.assertNotIn("visibly sings", "\n".join(scene["prompt"]))
                self.assertNotEqual(scene.get("source_audio_target"), "locked")

    def test_lyrics_mode_preserves_its_own_binding(self):
        source = SOURCE + '* `リップシンク` `歌詞` `サブジェクト2` 「歌を届ける」\n'
        text = "\n".join(compile_ref2va(source, IdentityTranslator()).plan["shots"][0]["prompt"])
        self.assertIn("<Subject 2> performs visible lip movements to <d>[Japanese]歌を届ける</d>.", text)
        self.assertNotIn("visibly sings", text)

    def test_context_loop_instruction_does_not_leak_into_next_silent_scene(self):
        source = SOURCE + """## 音響
* `リップシンク` `Context Loop` `サブジェクト1`
> `シーン` 2
# シーン 00:10.125 --> 00:20.250
* `H3長` 243
## ショット 00:10.125
* `演技` The performer pauses.
## 音響
* `無音`
"""
        scenes = compile_ref2va(source, IdentityTranslator()).plan["shots"]
        self.assertIn("visibly sings", "\n".join(scenes[0]["prompt"]))
        self.assertNotIn("visibly sings", "\n".join(scenes[1]["prompt"]))
        self.assertEqual(scenes[1]["source_audio_target"], "off")

    def test_visual_reference_boilerplate_never_opens_a_dialogue_span(self):
        for reference in ("`画像1`", "`動画1`", "`音声1`", ""):
            with self.subTest(reference=reference):
                source = SOURCE.replace("`画像1`", reference)
                prompt = compile_ref2va(source, IdentityTranslator()).plan["shots"][0]["prompt"]
                self.assertNotIn("<d>", "\n".join(prompt))
                self.assertNotIn("</d>", "\n".join(prompt))

    def test_actual_dialogue_spans_are_preserved_and_balanced(self):
        source = SOURCE.replace(
            "The performer lowers the hand and smiles.",
            "The performer says <d>[English]Good evening.</d> and 「こんばんは」.",
        )
        prompt = compile_ref2va(source, IdentityTranslator()).plan["shots"][0]["prompt"]
        text = "\n".join(prompt)
        self.assertEqual(text.count("<d>"), 2)
        self.assertEqual(text.count("</d>"), 2)
        self.assertIn("<d>[English]Good evening.</d>", text)
        self.assertIn("<d>[Japanese]こんばんは</d>", text)


if __name__ == "__main__":
    unittest.main()
