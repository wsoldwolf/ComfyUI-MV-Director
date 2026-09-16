from pathlib import Path
import unittest

from core.protocols import VisionProtocolError, parse_vision_observations
from core.vision import SubjectEMDError, render_subject_emd


FIXTURE = Path(__file__).parent / "fixtures" / "protocol" / "vision_observation_valid.txt"


class VisionLineProtocolTests(unittest.TestCase):
    def test_redundant_bare_protocol_id_after_header_is_ignored(self) -> None:
        source = FIXTURE.read_text(encoding="utf-8").replace(
            "MVD_VISION_OBSERVATION_LINES_V2\n",
            "MVD_VISION_OBSERVATION_LINES_V2\nprotocol_id\n",
            1,
        )
        result = parse_vision_observations(source)
        self.assertEqual(result.observations.primary_subject, "長い黒髪の人物")
        self.assertIn(
            "ignored redundant bare protocol_id after Vision protocol ID",
            result.warnings,
        )

    def test_canonical_fixture_builds_observations(self) -> None:
        result = parse_vision_observations(FIXTURE.read_text(encoding="utf-8"))
        observations = result.observations
        self.assertEqual(observations.primary_subject, "長い黒髪の人物")
        self.assertEqual(len(observations.subject_features), 2)
        self.assertEqual(observations.subject_features[1].visibility, "partial")
        self.assertEqual(observations.scene_elements, ("朱塗りの鳥居",))
        self.assertEqual(result.warnings, ())

    def test_system_prompt_keeps_subject_class_physical_and_features_stable(self) -> None:
        prompt = (
            Path(__file__).parents[1]
            / "prompts"
            / "vision_observation_system_prompt.txt"
        ).read_text(encoding="utf-8")
        self.assertIn("physical-entity class", prompt)
        self.assertIn("the word キャラクター", prompt)
        self.assertIn("stable visible design feature", prompt)
        self.assertIn("Do not repeat an eyes feature", prompt)

    def test_small_unambiguous_normalizations_do_not_retry(self) -> None:
        source = FIXTURE.read_text(encoding="utf-8").replace(
            "腰まで届く長い黒髪\tclear", "腰まで届く\t長い黒髪\tvisible"
        ).replace("END_MVD_VISION_OBSERVATION\n", "")
        result = parse_vision_observations(source)
        feature = result.observations.subject_features[0]
        self.assertEqual(feature.text, "腰まで届く、長い黒髪")
        self.assertEqual(feature.visibility, "clear")
        self.assertTrue(any("missing END" in item for item in result.warnings))

    def test_missing_protocol_header_is_restored_only_before_overview(self) -> None:
        source = FIXTURE.read_text(encoding="utf-8").replace(
            "MVD_VISION_OBSERVATION_LINES_V2\n", "", 1
        )
        result = parse_vision_observations(source)
        self.assertEqual(result.observations.primary_subject, "長い黒髪の人物")
        self.assertTrue(any("normalized missing" in item for item in result.warnings))

    def test_missing_protocol_and_overview_are_restored_before_primary_subject(self) -> None:
        source = (
            FIXTURE.read_text(encoding="utf-8")
            .replace("MVD_VISION_OBSERVATION_LINES_V2\n", "", 1)
            .replace("OVERVIEW\t夜の神社に人物が立っている。\n", "", 1)
        )
        result = parse_vision_observations(source)
        self.assertEqual(result.observations.overview, "長い黒髪の人物の参照画像。")
        self.assertEqual(result.observations.primary_subject, "長い黒髪の人物")
        self.assertTrue(
            any("MVD_VISION_OBSERVATION_LINES_V2" in item for item in result.warnings)
        )
        self.assertTrue(
            any("missing OVERVIEW" in item for item in result.warnings)
        )

    def test_missing_protocol_before_colon_overview_is_restored(self) -> None:
        source = (
            FIXTURE.read_text(encoding="utf-8")
            .replace("MVD_VISION_OBSERVATION_LINES_V2\n", "", 1)
            .replace(
                "OVERVIEW\t夜の神社に人物が立っている。",
                "Overview: 夜の神社に人物が立っている。",
                1,
            )
        )
        result = parse_vision_observations(source)
        self.assertEqual(result.observations.overview, "夜の神社に人物が立っている。")
        self.assertTrue(any("colon-form OVERVIEW" in item for item in result.warnings))

    def test_leading_closed_think_block_is_removed(self) -> None:
        source = (
            "<think>画像を分析する。</think>\n"
            + FIXTURE.read_text(encoding="utf-8")
        )
        result = parse_vision_observations(source)
        self.assertEqual(result.observations.primary_subject, "長い黒髪の人物")
        self.assertTrue(any("think block" in item for item in result.warnings))

    def test_unknown_leading_commentary_reports_bounded_prefix(self) -> None:
        with self.assertRaisesRegex(
            VisionProtocolError, "found 'Here are the records:'"
        ):
            parse_vision_observations(
                "Here are the records:\n"
                + FIXTURE.read_text(encoding="utf-8")
            )

    def test_bare_overview_is_labelled_when_primary_subject_follows(self) -> None:
        source = FIXTURE.read_text(encoding="utf-8").replace(
            "OVERVIEW\t夜の神社に人物が立っている。",
            "夜の神社に人物が立っている。",
            1,
        )
        result = parse_vision_observations(source)
        self.assertEqual(result.observations.overview, "夜の神社に人物が立っている。")
        self.assertTrue(any("bare OVERVIEW" in item for item in result.warnings))

    def test_bare_primary_subject_without_overview_is_labelled_by_position(self) -> None:
        source = (
            FIXTURE.read_text(encoding="utf-8")
            .replace("OVERVIEW\t夜の神社に人物が立っている。\n", "", 1)
            .replace("PRIMARY_SUBJECT\t長い黒髪の人物", "人物", 1)
        )
        result = parse_vision_observations(source)
        self.assertEqual(result.observations.overview, "人物の参照画像。")
        self.assertEqual(result.observations.primary_subject, "人物")
        self.assertTrue(
            any("bare PRIMARY_SUBJECT" in item for item in result.warnings)
        )

    def test_bare_unknown_line_is_not_labelled_without_structural_lookahead(self) -> None:
        source = FIXTURE.read_text(encoding="utf-8").replace(
            "OVERVIEW\t夜の神社に人物が立っている。",
            "任意の説明文",
            1,
        ).replace(
            "PRIMARY_SUBJECT\t長い黒髪の人物",
            "SUBJECT_POSE\t正面",
            1,
        )
        with self.assertRaises(VisionProtocolError):
            parse_vision_observations(source)

    def test_colon_form_overview_is_normalized_without_relaxing_other_records(self) -> None:
        source = FIXTURE.read_text(encoding="utf-8").replace(
            "OVERVIEW\t夜の神社に人物が立っている。",
            "Overview: 夜の神社に人物が立っている。",
        )
        result = parse_vision_observations(source)
        self.assertEqual(result.observations.overview, "夜の神社に人物が立っている。")
        self.assertTrue(any("colon-form OVERVIEW" in item for item in result.warnings))

    def test_missing_overview_before_primary_subject_gets_neutral_summary(self) -> None:
        source = FIXTURE.read_text(encoding="utf-8").replace(
            "OVERVIEW\t夜の神社に人物が立っている。\n",
            "",
            1,
        )
        result = parse_vision_observations(source)
        self.assertEqual(result.observations.overview, "長い黒髪の人物の参照画像。")
        self.assertEqual(result.observations.primary_subject, "長い黒髪の人物")
        self.assertTrue(
            any("normalized missing OVERVIEW" in item for item in result.warnings)
        )

    def test_fixed_record_names_accept_case_and_separator_normalization(self) -> None:
        source = (
            FIXTURE.read_text(encoding="utf-8")
            .replace("OVERVIEW\t", "Overview\t", 1)
            .replace("PRIMARY_SUBJECT\t", "Primary Subject\t", 1)
            .replace("STYLE_MEDIUM\t", "Style-Medium\t", 1)
        )
        result = parse_vision_observations(source)
        self.assertEqual(result.observations.primary_subject, "長い黒髪の人物")
        self.assertGreaterEqual(
            len([item for item in result.warnings if "normalized record name" in item]),
            3,
        )

    def test_missing_visibility_defaults_to_partial(self) -> None:
        source = FIXTURE.read_text(encoding="utf-8").replace(
            "短く丸い淡い金色の眉\tpartial", "短く丸い淡い金色の眉"
        )
        result = parse_vision_observations(source)
        self.assertEqual(result.observations.subject_features[1].visibility, "partial")

    def test_empty_optional_visible_text_is_ignored_with_warning(self) -> None:
        source = FIXTURE.read_text(encoding="utf-8").replace(
            "VISIBLE_TEXT\t奉納", "VISIBLE_TEXT\t"
        )
        result = parse_vision_observations(source)
        self.assertEqual(result.observations.visible_text, ())
        self.assertTrue(
            any(
                "ignored empty optional VISIBLE_TEXT" in item
                for item in result.warnings
            )
        )

    def test_empty_optional_scene_element_and_uncertainty_are_ignored(self) -> None:
        source = (
            FIXTURE.read_text(encoding="utf-8")
            .replace("SCENE_ELEMENT\t朱塗りの鳥居", "SCENE_ELEMENT\t")
            .replace("UNCERTAINTY\t人物の背面は見えない。", "UNCERTAINTY\t")
        )
        result = parse_vision_observations(source)
        self.assertEqual(result.observations.scene_elements, ())
        self.assertEqual(result.observations.uncertainties, ())
        self.assertEqual(
            len(
                [
                    item
                    for item in result.warnings
                    if "ignored empty optional" in item
                ]
            ),
            2,
        )

    def test_unknown_or_reordered_record_is_rejected(self) -> None:
        source = FIXTURE.read_text(encoding="utf-8").replace(
            "OVERVIEW\t夜の神社に人物が立っている。",
            "PRIMARY_SUBJECT\t人物",
        )
        with self.assertRaises(VisionProtocolError):
            parse_vision_observations(source)

    def test_subject_renderer_excludes_transient_visual_state(self) -> None:
        observations = parse_vision_observations(
            FIXTURE.read_text(encoding="utf-8")
        ).observations
        result = render_subject_emd(
            observations,
            concept_type="person",
            picture_index=4,
            subject_hint="狐の尾は一本です。",
        )
        self.assertIn("* `画像4` 長い黒髪の人物", result.emd_fragment)
        self.assertNotIn("<Subject", result.emd_fragment)
        self.assertNotIn("<Picture", result.emd_fragment)
        self.assertIn("狐の尾は一本です。", result.emd_fragment)
        for excluded in ("正面を向いて", "全身", "イラスト", "奉納", "青白い月光"):
            self.assertNotIn(excluded, result.emd_fragment)

    def test_location_renderer_uses_setting_and_elements(self) -> None:
        observations = parse_vision_observations(
            FIXTURE.read_text(encoding="utf-8")
        ).observations
        result = render_subject_emd(
            observations,
            concept_type="location",
            hint_mode="observe_only",
        )
        self.assertTrue(result.emd_fragment.startswith("# サブジェクト\n* "))
        self.assertIn("夜の神社の参道", result.emd_fragment)
        self.assertIn("朱塗りの鳥居", result.emd_fragment)
        self.assertNotIn("<Picture", result.emd_fragment)

    def test_strict_hint_conflict_stops_rendering(self) -> None:
        observations = parse_vision_observations(
            FIXTURE.read_text(encoding="utf-8").replace(
                "HINT_STATUS\tconsistent", "HINT_STATUS\tconflict"
            )
        ).observations
        with self.assertRaisesRegex(SubjectEMDError, "conflict"):
            render_subject_emd(
                observations,
                concept_type="person",
                hint_conflict="strict",
            )


if __name__ == "__main__":
    unittest.main()
