import unittest

from core.h3_contract import (
    COMFYUI_BASELINE_COMMIT,
    COMFYUI_BASELINE_VERSION,
    CONTEXT_LOOP_BASELINE_COMMIT,
    CONTEXT_LOOP_BASELINE_VERSION,
    CONTRACT_ID,
    LEGACY_CONTRACT_ID,
    H3TimingProfile,
)


class H3TimingProfileTests(unittest.TestCase):
    def test_runtime_baselines_are_pinned(self) -> None:
        self.assertEqual(COMFYUI_BASELINE_VERSION, "0.37.2")
        self.assertEqual(
            COMFYUI_BASELINE_COMMIT,
            "830232b856045ca2892833212d7771078a13edd5",
        )
        self.assertEqual(CONTEXT_LOOP_BASELINE_VERSION, "0.7.0")
        self.assertEqual(
            CONTEXT_LOOP_BASELINE_COMMIT,
            "d80304f05ecc2f504e64cbfb636e2a21d4409909",
        )
        self.assertEqual(
            CONTRACT_ID,
            "context-loop-0.7.0@d80304f05ecc2f504e64cbfb636e2a21d4409909",
        )

    def test_default_profile_matches_pinned_context_loop_contract(self) -> None:
        profile = H3TimingProfile()
        self.assertEqual(profile.contract, CONTRACT_ID)
        self.assertEqual(profile.to_dict()["length_modulus"], 17)
        profile.validate_raw_length(5)
        profile.validate_raw_length(22)
        profile.validate_raw_length(3592)

    def test_node_default_and_legacy_choice_preserve_identical_timing(self) -> None:
        from nodes.node_h3_timing_profile.node import MVDirectorH3TimingProfile
        choices, metadata = MVDirectorH3TimingProfile.INPUT_TYPES()["required"]["contract"]
        self.assertEqual(metadata["default"], CONTRACT_ID)
        self.assertEqual(choices, [CONTRACT_ID, LEGACY_CONTRACT_ID])
        node = MVDirectorH3TimingProfile()
        current, _, _ = node.build_profile(CONTRACT_ID)
        legacy, text, status = node.build_profile(LEGACY_CONTRACT_ID)
        self.assertIn(LEGACY_CONTRACT_ID, text)
        self.assertIn(LEGACY_CONTRACT_ID, status)
        for frames in (1, 240, 3000):
            for first in (True, False):
                self.assertEqual(current.quantize_delivered_frames(frames, first_scene=first),
                                 legacy.quantize_delivered_frames(frames, first_scene=first))

    def test_wrong_grid_and_out_of_range_are_rejected(self) -> None:
        profile = H3TimingProfile()
        with self.assertRaisesRegex(ValueError, r"17k\+5"):
            profile.validate_raw_length(23)
        with self.assertRaisesRegex(ValueError, r"5\.\.3592"):
            profile.validate_raw_length(3609)

    def test_unknown_context_loop_contract_is_not_guessed(self) -> None:
        with self.assertRaisesRegex(ValueError, "unsupported"):
            H3TimingProfile(contract="context-loop-latest").validate()


if __name__ == "__main__":
    unittest.main()
