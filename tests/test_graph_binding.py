import unittest

from core.vision import PictureBindingError, resolve_picture_binding


def h3_node(**inputs):
    return {"class_type": "MiniMaxH3ReferenceToVideo", "inputs": inputs}


class PictureBindingTests(unittest.TestCase):
    def test_auto_resolves_direct_and_nested_h3_input(self) -> None:
        prompt = {
            "20": h3_node(ref_image_0=["10", 2]),
            "21": h3_node(ref_images={"ref_image_0": ["10", 2]}),
        }
        binding = resolve_picture_binding(
            "auto_h3", picture_index=7, prompt=prompt, unique_id="10"
        )
        self.assertEqual(binding.picture_index, 1)
        self.assertEqual(binding.resolved_picture_reference, "<Picture 1>")
        self.assertEqual(len(binding.targets), 2)
        self.assertEqual(len(binding.fingerprint()), 64)

    def test_auto_unbound_is_success(self) -> None:
        binding = resolve_picture_binding(
            "auto_h3", picture_index=1, prompt={}, unique_id="10"
        )
        self.assertIsNone(binding.picture_index)
        self.assertEqual(binding.resolved_picture_reference, "unbound")

    def test_manual_and_none_do_not_inspect_graph(self) -> None:
        prompt = {"20": h3_node(ref_image_8=["10", 2])}
        manual = resolve_picture_binding(
            "manual", picture_index=3, prompt=prompt, unique_id="10"
        )
        none = resolve_picture_binding(
            "none", picture_index=3, prompt=prompt, unique_id="10"
        )
        self.assertEqual(manual.resolved_picture_reference, "<Picture 3>")
        self.assertEqual(none.resolved_picture_reference, "none")

    def test_different_picture_numbers_are_ambiguous(self) -> None:
        prompt = {
            "20": h3_node(ref_image_0=["10", 2]),
            "21": h3_node(ref_image_1=["10", 2]),
        }
        with self.assertRaises(PictureBindingError) as caught:
            resolve_picture_binding(
                "auto_h3", picture_index=1, prompt=prompt, unique_id="10"
            )
        self.assertEqual(caught.exception.status, "ambiguous")

    def test_wrong_source_output_or_unknown_h3_class_is_ignored(self) -> None:
        prompt = {
            "20": h3_node(ref_image_0=["10", 0]),
            "21": {"class_type": "OtherH3", "inputs": {"ref_image_0": ["10", 2]}},
        }
        binding = resolve_picture_binding(
            "auto_h3", picture_index=1, prompt=prompt, unique_id="10"
        )
        self.assertEqual(binding.resolved_picture_reference, "unbound")


if __name__ == "__main__":
    unittest.main()
