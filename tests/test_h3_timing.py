import unittest

from core.h3_contract import (
    COMFYUI_BASELINE_COMMIT,
    COMFYUI_BASELINE_VERSION,
    CONTEXT_LOOP_BASELINE_COMMIT,
    CONTEXT_LOOP_BASELINE_VERSION,
    CONTRACT_ID,
    H3TimingProfile,
)


class H3TimingProfileTests(unittest.TestCase):
    def test_runtime_baselines_are_pinned(self) -> None:
        self.assertEqual(COMFYUI_BASELINE_VERSION, "0.36.0")
        self.assertEqual(
            COMFYUI_BASELINE_COMMIT,
            "ee71d5c4993f29086b27fde1629a945ae48425bf",
        )
        self.assertEqual(CONTEXT_LOOP_BASELINE_VERSION, "0.6.9")
        self.assertEqual(
            CONTEXT_LOOP_BASELINE_COMMIT,
            "9860a063784c8c23b58e00107f2180e0df3c43d9",
        )
        self.assertEqual(
            CONTRACT_ID,
            "context-loop-0.6.9@9860a063784c8c23b58e00107f2180e0df3c43d9",
        )

    def test_default_profile_matches_pinned_context_loop_contract(self) -> None:
        profile = H3TimingProfile()
        self.assertEqual(profile.contract, CONTRACT_ID)
        self.assertEqual(profile.to_dict()["length_modulus"], 17)
        profile.validate_raw_length(5)
        profile.validate_raw_length(22)
        profile.validate_raw_length(3592)

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
