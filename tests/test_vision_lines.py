from pathlib import Path
import unittest

from core.protocols import VisionProtocolError, parse_vision_observations
from core.vision import SubjectEMDError, render_subject_emd


FIXTURE = Path(__file__).parent / "fixtures" / "protocol" / "vision_observation_valid.txt"


class VisionLineProtocolTests(unittest.TestCase):
    def test_canonical_fixture_builds_observations(self) -> None:
        result = parse_vision_observations(FIXTURE.read_text(encoding="utf-8"))
        observations = result.observations
        self.assertEqual(observations.primary_subject, "長い黒髪の人物")
        self.assertEqual(len(observations.subject_features), 2)
        self.assertEqual(observations.subject_features[1].visibility, "partial")
        self.assertEqual(observations.scene_elements, ("朱塗りの鳥居",))
        self.assertEqual(result.warnings, ())

    def test_small_unambiguous_normalizations_do_not_retry(self) -> None:
        source = FIXTURE.read_text(encoding="utf-8").replace(
            "腰まで届く長い黒髪\tclear", "腰まで届く\t長い黒髪\tvisible"
        ).replace("END_MVD_VISION_OBSERVATION\n", "")
        result = parse_vision_observations(source)
        feature = result.observations.subject_features[0]
        self.assertEqual(feature.text, "腰まで届く、長い黒髪")
        self.assertEqual(feature.visibility, "clear")
        self.assertTrue(any("missing END" in item for item in result.warnings))

    def test_missing_visibility_defaults_to_partial(self) -> None:
        source = FIXTURE.read_text(encoding="utf-8").replace(
            "短く丸い淡い金色の眉\tpartial", "短く丸い淡い金色の眉"
        )
        result = parse_vision_observations(source)
        self.assertEqual(result.observations.subject_features[1].visibility, "partial")

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
            concept_index=1,
            subject_index=2,
            picture_index=4,
            subject_hint="狐の尾は一本です。",
        )
        self.assertIn("* `人物1`", result.emd_fragment)
        self.assertIn("<Subject 2>", result.emd_fragment)
        self.assertIn("<Picture 4>", result.emd_fragment)
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
            concept_index=3,
            subject_index=1,
            hint_mode="observe_only",
        )
        self.assertIn("* `場所3`", result.emd_fragment)
        self.assertIn("夜の神社の参道", result.emd_fragment)
        self.assertIn("朱塗りの鳥居", result.emd_fragment)
        self.assertNotIn("<Picture", result.emd_fragment)

    def test_strict_hint_conflict_stops_rendering(self) -> None:
        observations = parse_vision_observations(
            FIXTURE.read_text(encoding="utf-8").replace(
                "HINT_ASSESSMENT\tconsistent", "HINT_ASSESSMENT\tconflict"
            )
        ).observations
        with self.assertRaisesRegex(SubjectEMDError, "conflict"):
            render_subject_emd(
                observations,
                concept_type="person",
                concept_index=1,
                subject_index=1,
                hint_conflict="strict",
            )


if __name__ == "__main__":
    unittest.main()
