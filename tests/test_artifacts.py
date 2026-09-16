from __future__ import annotations

import json
import unittest
from dataclasses import replace
from pathlib import Path

from core.artifacts import (
    ArtifactValidationError,
    DirectionArtifact,
    EMDTextArtifact,
    LyricSegment,
    ObservationsArtifact,
    ReferenceBinding,
    ReferenceBindingsArtifact,
    RequiredReference,
    RequiredReferencesArtifact,
    SubjectFeature,
    TimelineArtifact,
    TimelineScene,
    TimelineShot,
    canonical_json,
)


FIXTURES = Path(__file__).parent / "fixtures"


def valid_timeline() -> TimelineArtifact:
    return TimelineArtifact(
        vad_analysis_hop_ms=20,
        boundary_resolution_ms=1,
        boundary_method="energy_vad_sample_refined",
        source_audio_duration_ms=20_000,
        plan_duration_ms=20_042,
        timing_profile=(
            "context-loop-0.6.9@"
            "9860a063784c8c23b58e00107f2180e0df3c43d9"
        ),
        lyrics=(
            LyricSegment(
                segment_id="lyric_0001",
                text="千年鳥居をくぐるそなたよ",
                section="VERSE1",
                source_line=2,
                source_start=0,
                source_end=12,
                start_ms=12_300,
                end_ms=15_800,
                scene_number=2,
                shot_index=2,
            ),
        ),
        scenes=(
            TimelineScene(
                scene_number=1,
                start_ms=0,
                end_ms=10_125,
                source_start_ms=0,
                source_end_ms=10_000,
                raw_length=243,
                delivered_frames=243,
                context_length=0,
                shots=(TimelineShot(0, 10_125),),
            ),
            TimelineScene(
                scene_number=2,
                start_ms=10_125,
                end_ms=20_042,
                source_start_ms=10_000,
                source_end_ms=20_000,
                raw_length=260,
                delivered_frames=238,
                context_length=22,
                shots=(
                    TimelineShot(10_125, 12_300),
                    TimelineShot(12_300, 20_042),
                ),
            ),
        ),
    )


class ArtifactTests(unittest.TestCase):
    def test_emd_text_normalizes_newlines_and_hashes_normalized_text(self) -> None:
        artifact = EMDTextArtifact.create(
            "MVD_EMD_FRAGMENT_V1", "# サブジェクト\r\n* 主人公。\r"
        )
        self.assertEqual(artifact.text, "# サブジェクト\n* 主人公。\n")
        self.assertEqual(len(artifact.sha256), 64)
        self.assertEqual(
            EMDTextArtifact.from_dict(artifact.to_dict()).to_json(),
            artifact.to_json(),
        )

    def test_emd_hash_mismatch_is_rejected(self) -> None:
        artifact = EMDTextArtifact.create("MVD_EMD_V1", "# サブジェクト")
        with self.assertRaises(ArtifactValidationError):
            replace(artifact, sha256="0" * 64).validate()

    def test_direction_fixture_round_trips_canonically(self) -> None:
        payload = json.loads(
            (FIXTURES / "artifacts" / "direction_v2.json").read_text(
                encoding="utf-8"
            )
        )
        artifact = DirectionArtifact.from_dict(payload)
        self.assertEqual(json.loads(artifact.to_json()), payload)
        self.assertEqual(artifact.to_json(), canonical_json(payload))

    def test_duplicate_provenance_id_is_rejected(self) -> None:
        payload = json.loads(
            (FIXTURES / "artifacts" / "direction_v2.json").read_text(
                encoding="utf-8"
            )
        )
        payload["provenance"][1]["record_id"] = "src_0001"
        with self.assertRaises(ArtifactValidationError):
            DirectionArtifact.from_dict(payload)

    def test_empty_required_references_is_valid(self) -> None:
        artifact = RequiredReferencesArtifact()
        self.assertEqual(
            artifact.to_dict(),
            {"schema": "MVD_REQUIRED_REFERENCES_V1", "references": []},
        )

    def test_reference_slots_must_match_tags(self) -> None:
        reference = RequiredReference(
            concept_id="サブジェクト1",
            subject_ref="<Subject 1>",
            h3_ref="<Picture 1>",
            required_input="ref_images.ref_image_0",
            purpose="visual_identity",
        )
        self.assertEqual(
            RequiredReferencesArtifact((reference,)).to_dict()["references"][0][
                "h3_ref"
            ],
            "<Picture 1>",
        )
        with self.assertRaises(ArtifactValidationError):
            replace(reference, required_input="ref_images.ref_image_1").validate()

    def test_reference_binding_round_trip(self) -> None:
        binding = ReferenceBinding(
            concept_id="サブジェクト1",
            subject_ref="<Subject 1>",
            picture_ref="<Picture 1>",
            target_node_id="42",
            target_class_type="MiniMaxH3ReferenceToVideo",
            target_input="ref_images.ref_image_0",
            image_sha256="a" * 64,
            binding_sha256="b" * 64,
        )
        artifact = ReferenceBindingsArtifact((binding,))
        self.assertEqual(
            ReferenceBindingsArtifact.from_dict(artifact.to_dict()).to_json(),
            artifact.to_json(),
        )

    def test_observations_round_trip(self) -> None:
        artifact = ObservationsArtifact(
            overview="人物が立っている。",
            primary_subject="黒髪の人物",
            hint_status="consistent",
            hint_reason="眉の特徴が確認できる。",
            subject_features=(
                SubjectFeature("hair", "長い黒髪", "clear"),
                SubjectFeature("eyebrows", "淡い金色の短い眉", "partial"),
            ),
            subject_pose="正面向き",
            scene_setting="夜の神社",
            scene_elements=("鳥居", "石畳"),
            lighting="月光",
            time_weather="夜",
            shot_size="full",
            viewpoint="front",
            subject_placement="center",
            depth="deep",
            style_medium="illustration",
            style_rendering="cel shading",
            style_palette="red and white",
            visible_text=(),
            uncertainties=("背面は不可視",),
        )
        restored = ObservationsArtifact.from_dict(artifact.to_dict())
        self.assertEqual(restored.to_json(), artifact.to_json())

    def test_timeline_round_trip_and_structural_assignment(self) -> None:
        artifact = valid_timeline()
        restored = TimelineArtifact.from_dict(artifact.to_dict())
        self.assertEqual(restored.to_json(), artifact.to_json())
        self.assertEqual(restored.lyrics[0].scene_number, 2)
        self.assertEqual(restored.lyrics[0].shot_index, 2)

    def test_timeline_rejects_plan_gap(self) -> None:
        artifact = valid_timeline()
        second = replace(artifact.scenes[1], start_ms=10_126)
        with self.assertRaises(ArtifactValidationError):
            replace(artifact, scenes=(artifact.scenes[0], second)).validate()

    def test_unknown_artifact_key_is_rejected(self) -> None:
        payload = RequiredReferencesArtifact().to_dict()
        payload["legacy"] = True
        with self.assertRaises(ArtifactValidationError):
            RequiredReferencesArtifact.from_dict(payload)


if __name__ == "__main__":
    unittest.main()
