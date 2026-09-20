from pathlib import Path
import tempfile
import unittest

from core.direction.profile_loader import (
    DirectionProfileError,
    load_direction_profile,
    load_direction_profiles,
)


class DirectionProfileLoaderTests(unittest.TestCase):
    def test_loads_user_profiles_from_three_external_directories(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            for kind in ("style", "motion", "camera"):
                (root / kind).mkdir()
            (root / "style" / "custom_style.md").write_text(
                "# プロファイル\n"
                "* `locked` true\n"
                "* `retention` `partially_preserved` 識別要素を保持する。\n"
                "* `scene_reinforcement` 各Sceneでも媒体を維持する。\n\n"
                "# 共通プロンプト\n"
                "## スタイル\n"
                "* 第一条件。\n"
                "* 第二条件。\n",
                encoding="utf-8",
            )
            (root / "motion" / "custom_motion.md").write_text(
                "# 共通プロンプト\n## モーション\n* 素早く動く。\n",
                encoding="utf-8",
            )
            (root / "camera" / "custom_camera.md").write_text(
                "# プロファイル\n"
                "* `planner_policy` emotional_test\n"
                "* `lyric_cue_mode` automatic\n"
                "* `lyric_interpretation` bounded\n"
                "* `priority_lyric_cues` 苔:object,花:symbolic_motif,"
                "狐火:external_effect\n\n"
                "# 共通プロンプト\n## カメラ\n* arcで回り込む。\n",
                encoding="utf-8",
            )

            catalog = load_direction_profiles(root)

            self.assertEqual(
                catalog.style["custom_style"], "第一条件。 第二条件。"
            )
            self.assertEqual(catalog.motion["custom_motion"], "素早く動く。")
            self.assertEqual(catalog.camera["custom_camera"], "arcで回り込む。")
            self.assertEqual(catalog.locked_style, frozenset({"custom_style"}))
            self.assertIn("custom_style", catalog.style_retention)
            self.assertEqual(
                catalog.style_scene_reinforcement["custom_style"],
                "各Sceneでも媒体を維持する。",
            )
            self.assertEqual(
                catalog.camera_planner_policy["custom_camera"],
                "emotional_test",
            )
            self.assertEqual(
                catalog.camera_lyric_cue_mode["custom_camera"],
                "automatic",
            )
            self.assertEqual(
                catalog.camera_lyric_interpretation["custom_camera"], "bounded"
            )
            self.assertEqual(
                catalog.camera_priority_lyric_cues["custom_camera"],
                (
                    ("苔", "object"),
                    ("花", "symbolic_motif"),
                    ("狐火", "external_effect"),
                ),
            )

    def test_rejects_invalid_priority_lyric_cue_kind(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "bad_camera.md"
            path.write_text(
                "# プロファイル\n"
                "* `planner_policy` emotional_test\n"
                "* `priority_lyric_cues` 狐火:handheld_effect\n"
                "# 共通プロンプト\n## カメラ\n* arc。\n",
                encoding="utf-8",
            )
            with self.assertRaisesRegex(
                DirectionProfileError, "priority_lyric_cues kind"
            ):
                load_direction_profile(path, "camera")

    def test_rejects_invalid_lyric_cue_mode(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "bad_camera.md"
            path.write_text(
                "# プロファイル\n"
                "* `planner_policy` emotional_test\n"
                "* `lyric_cue_mode` dictionary\n"
                "# 共通プロンプト\n## カメラ\n* arc。\n",
                encoding="utf-8",
            )
            with self.assertRaisesRegex(
                DirectionProfileError, "lyric_cue_mode"
            ):
                load_direction_profile(path, "camera")

    def test_interpretation_is_strict_and_defaults_to_literal(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "camera.md"
            body = "# 共通プロンプト\n## カメラ\n* arc。\n"
            path.write_text(body, encoding="utf-8")
            self.assertEqual(
                load_direction_profile(path, "camera").lyric_interpretation, "literal"
            )
            for value in ("unlimited", "Bounded", "bounded extra"):
                path.write_text(
                    "# プロファイル\n"
                    f"* `lyric_interpretation` {value}\n" + body,
                    encoding="utf-8",
                )
                with self.assertRaisesRegex(DirectionProfileError, "lyric_interpretation"):
                    load_direction_profile(path, "camera")
            path.write_text(
                "# プロファイル\n* `lyric_interpretation` bounded\n"
                "# 共通プロンプト\n## スタイル\n* anime。\n",
                encoding="utf-8",
            )
            with self.assertRaisesRegex(DirectionProfileError, "not supported by style"):
                load_direction_profile(path, "style")

    def test_filename_is_the_profile_id(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "my_anime.md"
            path.write_text(
                "# 共通プロンプト\n## スタイル\n* 手描きアニメ。\n",
                encoding="utf-8",
            )
            profile = load_direction_profile(path, "style")
            self.assertEqual(profile.profile_id, "my_anime")
            self.assertEqual(profile.kind, "style")

    def test_rejects_wrong_subsection_for_directory(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "bad.md"
            path.write_text(
                "# 共通プロンプト\n## カメラ\n* arc。\n",
                encoding="utf-8",
            )
            with self.assertRaisesRegex(DirectionProfileError, "## スタイル"):
                load_direction_profile(path, "style")

    def test_rejects_metadata_on_motion_and_reserved_filename(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            motion = Path(temp) / "custom.md"
            motion.write_text(
                "# プロファイル\n* `locked` true\n"
                "# 共通プロンプト\n## モーション\n* 動く。\n",
                encoding="utf-8",
            )
            with self.assertRaisesRegex(
                DirectionProfileError, "not supported by motion"
            ):
                load_direction_profile(motion, "motion")

            reserved = Path(temp) / "passthrough.md"
            reserved.write_text(
                "# 共通プロンプト\n## スタイル\n* 任意。\n",
                encoding="utf-8",
            )
            with self.assertRaisesRegex(DirectionProfileError, "must not be passthrough"):
                load_direction_profile(reserved, "style")


if __name__ == "__main__":
    unittest.main()
