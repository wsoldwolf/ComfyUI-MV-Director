from pathlib import Path
import unittest

from core.emd import EMDParseError, parse_emd, parse_time_ms


FIXTURES = Path(__file__).parent / "fixtures" / "emd"


class EMDParserTests(unittest.TestCase):
    def test_canonical_ref2va_document(self) -> None:
        document = parse_emd(
            (FIXTURES / "canonical_ref2va.emd").read_text(encoding="utf-8")
        )

        self.assertEqual(len(document.subjects), 1)
        self.assertEqual(document.subjects[0].concept_id, "サブジェクト1")
        self.assertEqual(document.subjects[0].subject_ref, "<Subject 1>")
        self.assertEqual(document.subjects[0].references, ())
        self.assertEqual(
            tuple(name for name, _ in document.common_prompt),
            (
                "スタイル",
                "環境",
                "時間・照明",
                "モーション",
                "カメラ",
                "その他",
            ),
        )
        scene = document.scenes[0]
        self.assertEqual((scene.start_ms, scene.end_ms), (0, 10_125))
        self.assertEqual(scene.h3_length, 243)
        self.assertEqual(tuple(shot.start_ms for shot in scene.shots), (0, 5_000))
        self.assertEqual(scene.shots[0].lyric_annotations[0].section, "VERSE1")
        self.assertEqual(
            scene.shots[1].lyric_lip_sync,
            (("サブジェクト1", "千年鳥居をくぐるそなたよ"),),
        )

    def test_missing_scene_annotation_is_rejected(self) -> None:
        source = (FIXTURES / "invalid_missing_scene_annotation.emd").read_text(
            encoding="utf-8"
        )
        with self.assertRaisesRegex(EMDParseError, "Scene annotation is required"):
            parse_emd(source)

    def test_conflicting_lip_sync_is_rejected(self) -> None:
        source = (FIXTURES / "invalid_conflicting_lip_sync.emd").read_text(
            encoding="utf-8"
        )
        with self.assertRaisesRegex(EMDParseError, "lip-sync modes are exclusive"):
            parse_emd(source)

    def test_picture_reference_is_optional(self) -> None:
        source = """# サブジェクト
* 石造りの回廊。

> `シーン` 1
# シーン 00:00.000 --> 00:01.000
* `H3長` 22
## ショット 00:00.000
* `サブジェクト1`を固定カメラで映す。
"""
        document = parse_emd(source)
        self.assertEqual(document.subjects[0].references, ())
        self.assertEqual(document.subjects[0].description, "石造りの回廊。")

    def test_scene_setting_is_parsed_between_subjects_and_direction(self) -> None:
        source = """# サブジェクト
* `画像1` 狐巫女。
# シーン設定
## 環境
* 森の中の神社境内。
* 赤い鳥居と石畳の参道。
## 時間・照明
* 夜間。月明かりが差す。
## 背景参照
* `画像2`
# 共通プロンプト
## 時間・照明
* 深夜の青い月光を優先する。
> `シーン` 1
# シーン 00:00.000 --> 00:01.000
* `H3長` 22
## ショット 00:00.000
* `サブジェクト1`が鳥居を見上げる。
"""
        setting = parse_emd(source).scene_setting
        self.assertIsNotNone(setting)
        assert setting is not None
        self.assertEqual(
            setting.environment,
            ("森の中の神社境内。", "赤い鳥居と石畳の参道。"),
        )
        self.assertEqual(setting.time_lighting, ("夜間。月明かりが差す。",))
        self.assertEqual(setting.picture_ref, "<Picture 2>")

    def test_scene_setting_requires_environment(self) -> None:
        source = """# サブジェクト
* 人物。
# シーン設定
## 背景参照
* `画像2`
> `シーン` 1
# シーン 00:00.000 --> 00:01.000
* `H3長` 22
## ショット 00:00.000
* 人物が立つ。
"""
        with self.assertRaisesRegex(EMDParseError, "requires ## 環境"):
            parse_emd(source)

    def test_subject_line_order_and_media_tokens_define_bindings(self) -> None:
        source = """# サブジェクト
* `画像3` 狐耳の少女。
* `動画1` `音声2` 石造りの回廊。
> `シーン` 1
# シーン 00:00.000 --> 00:01.000
* `H3長` 22
## ショット 00:00.000
* `サブジェクト1`が歩く。
"""
        document = parse_emd(source)
        self.assertEqual(document.subjects[0].concept_id, "サブジェクト1")
        self.assertEqual(document.subjects[0].references, ("<Picture 3>",))
        self.assertEqual(document.subjects[1].concept_id, "サブジェクト2")
        self.assertEqual(
            document.subjects[1].references,
            ("<Video 1>", "<Audio 2>"),
        )

    def test_legacy_subject_declaration_is_rejected(self) -> None:
        source = """# サブジェクト
* `人物1`
> `シーン` 1
# シーン 00:00.000 --> 00:01.000
* `H3長` 22
## ショット 00:00.000
* 歩く。
"""
        with self.assertRaisesRegex(EMDParseError, "unknown Subject reserved token"):
            parse_emd(source)

    def test_raw_h3_length_must_match_grid(self) -> None:
        source = """# サブジェクト
* 人物。
> `シーン` 1
# シーン 00:00.000 --> 00:01.000
* `H3長` 23
## ショット 00:00.000
* 歩く。
"""
        with self.assertRaisesRegex(EMDParseError, r"17k\+5"):
            parse_emd(source)

    def test_common_prompt_order_is_strict(self) -> None:
        source = """# サブジェクト
* 人物。
# 共通プロンプト
## カメラ
* 固定する。
## スタイル
* 実写。
> `シーン` 1
# シーン 00:00.000 --> 00:01.000
* `H3長` 22
## ショット 00:00.000
* 歩く。
"""
        with self.assertRaisesRegex(EMDParseError, "subsection order"):
            parse_emd(source)

    def test_retention_mode_is_structural_and_description_is_separate(self) -> None:
        source = """# サブジェクト
* `画像1` 人物。
# 保持分析
* `サブジェクト1`: `partially_preserved` 髪型と衣装を維持する。
> `シーン` 1
# シーン 00:00.000 --> 00:01.000
* `H3長` 22
## ショット 00:00.000
* 歩く。
"""
        directive = parse_emd(source).retention[0]
        self.assertEqual(directive.concept_id, "サブジェクト1")
        self.assertEqual(directive.mode, "partially_preserved")
        self.assertEqual(directive.description, "髪型と衣装を維持する。")

    def test_retention_without_fixed_mode_is_rejected(self) -> None:
        source = """# サブジェクト
* 人物。
# 保持分析
* `サブジェクト1`: 髪型と衣装を維持する。
> `シーン` 1
# シーン 00:00.000 --> 00:01.000
* `H3長` 22
## ショット 00:00.000
* 歩く。
"""
        with self.assertRaisesRegex(EMDParseError, "fixed mode"):
            parse_emd(source)

    def test_explicit_dialogue_tags_are_validated(self) -> None:
        valid = """# サブジェクト
* 人物。
> `シーン` 1
# シーン 00:00.000 --> 00:01.000
* `H3長` 22
## ショット 00:00.000
* <d>[English]Hello.</d> と発話する。
"""
        parse_emd(valid)
        with self.assertRaisesRegex(EMDParseError, "unclosed <d> tag"):
            parse_emd(valid.replace("</d>", ""))

    def test_time_parser_returns_integer_milliseconds(self) -> None:
        self.assertEqual(parse_time_ms("02:03.456"), 123_456)
        with self.assertRaises(EMDParseError):
            parse_time_ms("00:60.000")

    def test_scene_annotation_must_be_physically_adjacent(self) -> None:
        source = """# サブジェクト
* 人物。
> `シーン` 1

# シーン 00:00.000 --> 00:01.000
* `H3長` 22
## ショット 00:00.000
* 歩く。
"""
        with self.assertRaisesRegex(EMDParseError, "physical line"):
            parse_emd(source)


    def test_scene_continuation_is_explicit_and_omission_means_cut(self) -> None:
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
* 歩き続ける。
> `シーン` 3
# シーン 00:02.000 --> 00:03.000
* `H3長` 22
## ショット 00:02.000
* 顔のアップへ切り替える。
"""
        document = parse_emd(source)
        self.assertEqual(
            [scene.continuation for scene in document.scenes],
            [False, True, False],
        )

    def test_first_scene_cannot_be_continuation(self) -> None:
        source = """# サブジェクト
* 人物。
> `シーン` 1
# シーン 00:00.000 --> 00:01.000 継続
* `H3長` 22
## ショット 00:00.000
* 歩く。
"""
        with self.assertRaisesRegex(EMDParseError, "first Scene cannot use 継続"):
            parse_emd(source)


if __name__ == "__main__":
    unittest.main()
