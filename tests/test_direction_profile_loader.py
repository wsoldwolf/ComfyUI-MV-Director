from pathlib import Path
import tempfile
import unittest

from core.direction.profile_loader import (
    DirectionProfileError,
    load_direction_profile,
    load_direction_profiles,
)


class DirectionProfileLoaderTests(unittest.TestCase):
    def test_bundled_profiles_do_not_inject_material_specific_identity(self) -> None:
        catalog = load_direction_profiles(Path(__file__).parents[1] / "profiles")
        for kind, profiles in (
            ("style", catalog.style), ("motion", catalog.motion),
            ("camera", catalog.camera),
        ):
            for name, text in profiles.items():
                with self.subTest(kind=kind, profile=name):
                    for example in (
                        "動物耳", "耳内部", "split-toe足袋", "黒い木下駄",
                        "Animal ears and tails", "typical human eye proportions",
                    ):
                        self.assertNotIn(example, text)
        self.assertNotIn("アニメMV", catalog.camera["cinema_mv"])
        self.assertIn("映画的なMV", catalog.camera["cinema_mv"])

    def test_photoreal_metadata_preserves_defined_surfaces(self) -> None:
        catalog = load_direction_profiles(Path(__file__).parents[1] / "profiles")
        retention = catalog.style_retention["illust_to_photoreal"]
        self.assertTrue(retention.startswith("`partially_preserved` "))
        self.assertIn("facial surface, body covering", retention)
        self.assertIn("defined shape and covering", catalog.style_scene_reinforcement["illust_to_photoreal"])
        self.assertIn("各Shotの演技に従い", catalog.render_prompts["motion"]["anime_emotional_mv"])
        self.assertIn("被覆された顔面はその形状と素材を保つ",
                      catalog.render_prompts["camera"]["anime_emotional_mv"])

    def test_emotional_motion_file_is_composed_copy_and_retired_profiles_are_absent(self):
        root = Path(__file__).parents[1] / "profiles"
        self.assertEqual((root / "motion/anime_emotional_mv.md").read_text(encoding="utf-8"),
                         (root / "motion/anime_scene_composed_mv.md").read_text(encoding="utf-8"))
        catalog = load_direction_profiles(root)
        for profiles in (catalog.style, catalog.motion, catalog.camera):
            for retired in ("anime_scene_author_mv", "anime_story_mv", "limited_animation"):
                self.assertNotIn(retired, profiles)

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
                "* `arc_roll_policy` selective_arc\n"
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
            self.assertEqual(catalog.camera_arc_roll_policy["custom_camera"], "selective_arc")

    def test_retired_strategy_metadata_requires_migration(self) -> None:
        for key in ("performance_mode", "body_accent_policy", "choreography_policy",
                    "planner_policy", "lyric_cue_mode", "lyric_interpretation",
                    "priority_lyric_cues", "camera_render_style", "arc_tilt_policy"):
            with self.subTest(key=key), tempfile.TemporaryDirectory() as directory:
                path = Path(directory) / "custom.md"
                path.write_text(
                    f"# プロファイル\n* `{key}` old\n"
                    "# 共通プロンプト\n## モーション\n* 歌詞に応じて動く。\n",
                    encoding="utf-8",
                )
                with self.assertRaisesRegex(DirectionProfileError, "retired metadata"):
                    load_direction_profile(path, "motion")

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
