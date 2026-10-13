"""Grouped Subject references across Planner, EMD parsing and compilation."""

import unittest

from core.artifacts import DirectionArtifact
from core.compiler import compile_ref2va
from core.compiler.protection import protect_unit
from core.emd import EMDParseError, parse_emd
from core.emd.subject_references import normalize_subject_references
from core.planner import parse_template_emd
from core.planner.renderer import render_completed_emd
from core.planner.subject_ownership import bind_motion_composition, explicit_subjects
from planner_fixtures import TEMPLATE


SUBJECTS = "# サブジェクト\n* 赤い衣装の人物。\n* 黄色い衣装の人物。\n* 青い衣装の人物。\n"
SCENE = (
    "> `シーン` 1\n# シーン 00:00.000 --> 00:10.125\n"
    "* `H3長` 243\n## ショット 00:00.000\n"
)


class GuardedTranslator:
    def translate(self, units):
        if any("サブジェクト" in unit or "<Subject" in unit for unit in units):
            raise AssertionError("Subject reference leaked into ordinary translation")
        return tuple("EN:" + unit for unit in units)


class GroupedSubjectReferenceTests(unittest.TestCase):
    def test_explicit_lists_expand_in_order_and_are_idempotent(self):
        for source, expected in (
            ("`サブジェクト1,2,3`が踊る。", "`サブジェクト1`、`サブジェクト2`、`サブジェクト3`が踊る。"),
            ("`サブジェクト4 、 2, 1`", "`サブジェクト4`、`サブジェクト2`、`サブジェクト1`"),
            ("`サブジェクト2,2`", "`サブジェクト2`、`サブジェクト2`"),
        ):
            with self.subTest(source=source):
                self.assertEqual(normalize_subject_references(source), expected)
                self.assertEqual(normalize_subject_references(expected), expected)

    def test_ambiguous_and_non_reference_text_is_not_guessed(self):
        for source in ("サブジェクト1,2,3", "`サブジェクト1-3`", "`サブジェクト1,5`",
                       "`サブジェクト01,2`", "`サブジェクト１,２`", "`サブジェクト1`",
                       "`画像1,2`", "{\"サブジェクト1,2\":\"立つ\"}"):
            with self.subTest(source=source):
                self.assertEqual(normalize_subject_references(source), source)

    def test_dialogue_and_h3_speech_are_preserved_while_surrounding_prose_expands(self):
        for speech in ("「`サブジェクト1,2,3`」", "<d>[Japanese]`サブジェクト1,2,3`</d>",
                       "<d[00:00.000]>`サブジェクト1,2,3`</d>"):
            with self.subTest(speech=speech):
                source = speech + "と`サブジェクト2,3`を映す。"
                expected = speech + "と`サブジェクト2`、`サブジェクト3`を映す。"
                self.assertEqual(normalize_subject_references(source), expected)

    def test_parser_canonicalizes_typed_and_untyped_shot_prose(self):
        source = SUBJECTS + SCENE + (
            "* `演出` `サブジェクト1,2,3`の輪郭が光る。\n"
            "* `サブジェクト2,3` が踊る。\n"
        )
        shot = parse_emd(source).scenes[0].shots[0]
        self.assertEqual(shot.directives[0].text,
                         "`サブジェクト1`、`サブジェクト2`、`サブジェクト3`の輪郭が光る。")
        self.assertEqual(shot.body[1], "`サブジェクト2`、`サブジェクト3` が踊る。")

    def test_parser_rejects_undefined_member(self):
        with self.assertRaisesRegex(EMDParseError, "undefined concept ID サブジェクト4"):
            parse_emd(SUBJECTS + SCENE + "* `演技` `サブジェクト1,4`が踊る。\n")

    def test_parser_does_not_rewrite_lyric_annotations_or_lipsync_lyrics(self):
        source = SUBJECTS + SCENE.replace("## ショット 00:00.000\n", (
            "> `セクション` VERSE1\n> `歌詞開始` 00:02.000\n"
            "> `歌詞終了` 00:03.000\n> `歌詞` `サブジェクト1,2,3`\n"
            "## ショット 00:00.000\n"
        )) + (
            "* `演技` `サブジェクト1,2,3`が踊る。\n"
            "* `リップシンク` `歌詞` `サブジェクト1` 「`サブジェクト1,2,3`」\n"
        )
        shot = parse_emd(source).scenes[0].shots[0]
        self.assertEqual(shot.lyric_annotations[0].text, "`サブジェクト1,2,3`")
        self.assertEqual(shot.lyric_lip_sync[0][1], "`サブジェクト1,2,3`")

    def test_compiler_protects_every_member_of_legacy_grouped_emd(self):
        document = parse_emd(SUBJECTS + SCENE + "* 人物が踊る。\n")
        unit = protect_unit("`サブジェクト1,2,3`の輪郭が光る。", document.subjects)
        self.assertEqual(unit.values, ("<Subject 1>", "<Subject 2>", "<Subject 3>"))
        source = SUBJECTS + SCENE + (
            "* `演出` `サブジェクト1,2,3`の輪郭が光る。\n"
            "* `カメラ` `サブジェクト1`と`サブジェクト2,3`をPull Outで映す。\n"
        )
        result = compile_ref2va(source, GuardedTranslator())
        prompt = "\n".join(result.plan["shots"][0]["prompt"])
        for identifier in ("<Subject 1>", "<Subject 2>", "<Subject 3>"):
            self.assertGreaterEqual(prompt.count(identifier), 2)
        self.assertNotIn("サブジェクト", prompt)
        self.assertIn("Pull Out", prompt)

    def test_renderer_outputs_individual_ids_and_preserves_lyric_text(self):
        template = parse_template_emd(TEMPLATE.replace(
            "千年鳥居をくぐるそなたよ", "`サブジェクト1,2,3`"))
        result = render_completed_emd(
            concept_emd=SUBJECTS, template=template, direction=DirectionArtifact(),
            actions={(1, 1): "`サブジェクト1,2,3`が踊る。"},
            cameras={(1, 1): "`サブジェクト2,3`を映す。"},
            events={(1, 1): "`サブジェクト1,2,3`の輪郭が光る。"},
            typed_output=True, lip_sync_mode="lyrics", lip_sync_target="サブジェクト1",
            lip_sync_audio_slot=1,
        )
        self.assertIn("* `演技` `サブジェクト1`、`サブジェクト2`、`サブジェクト3`が踊る。", result.text)
        self.assertIn("* `カメラ` `サブジェクト2`、`サブジェクト3`を映す。", result.text)
        self.assertIn("> `歌詞` `サブジェクト1,2,3`", result.text)
        self.assertIn("「`サブジェクト1,2,3`」", result.text)

    def test_ownership_sees_all_members_without_assigning_group_to_one_actor(self):
        text = "`サブジェクト1,2,3`が踊る。"
        self.assertEqual(explicit_subjects(text), frozenset(
            ("サブジェクト1", "サブジェクト2", "サブジェクト3")))
        row = (1, 1, "user", 1, text)
        self.assertEqual(bind_motion_composition(row, "サブジェクト2",
                         ("サブジェクト1", "サブジェクト2", "サブジェクト3")), row)
        self.assertIsNone(bind_motion_composition(row, "サブジェクト2",
                         ("サブジェクト1", "サブジェクト2")))


if __name__ == "__main__":
    unittest.main()
