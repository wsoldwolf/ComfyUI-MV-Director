from __future__ import annotations

import json
import unittest

from core.h3_contract import bind_h3_background_reference
from nodes import NODE_CLASS_MAPPINGS, NODE_DISPLAY_NAME_MAPPINGS


def _plan() -> str:
    return json.dumps(
        {
            "defaults": {"steps": 8},
            "prompt_prefix": ["The scene takes place at night."],
            "shots": [
                {
                    "id": "scene_0001",
                    "length": 243,
                    "prompt": [
                        "subject_definitions:",
                        "<Subject 1> is described here: a singer.",
                        "",
                        "summary:",
                        "[reference generation] A shrine performance.",
                        "",
                        "retention_analysis:",
                        "<Subject 1>: fully_preserved - preserve identity.",
                        "",
                        "detailed_description:",
                        "[Shot 1] The singer turns toward the torii.",
                        "",
                        "overall_soundscape:",
                        "Night ambience.",
                        "",
                        "non_diegetic_music:",
                        "No additional music.",
                    ],
                },
                {
                    "id": "scene_0002",
                    "length": 243,
                    "prompt": [
                        "subject_definitions:",
                        "<Subject 1> is described here: a singer.",
                        "",
                        "summary:",
                        "[reference generation] The path continues.",
                        "",
                        "retention_analysis:",
                        "<Subject 1>: fully_preserved - preserve identity.",
                        "",
                        "detailed_description:",
                        "[Shot 1] The singer looks back.",
                        "",
                        "overall_soundscape:",
                        "Night ambience.",
                        "",
                        "non_diegetic_music:",
                        "No additional music.",
                    ],
                },
            ],
        },
        ensure_ascii=False,
    )


class H3BackgroundReferenceTests(unittest.TestCase):
    def test_binds_environment_contract_to_every_shot(self) -> None:
        output, count = bind_h3_background_reference(_plan(), picture_index=2)
        plan = json.loads(output)

        self.assertEqual(count, 2)
        self.assertEqual(plan["prompt_prefix"], ["The scene takes place at night."])
        for shot in plan["shots"]:
            prompt = shot["prompt"]
            definition = next(
                line
                for line in prompt
                if line.startswith("<Picture 2> is the environment reference:")
            )
            retention = next(
                line
                for line in prompt
                if line.startswith(
                    "<Picture 2>: environment_partially_preserved -"
                )
            )
            self.assertIn("stable architecture, vegetation", definition)
            self.assertIn("not a Subject, performer", definition)
            self.assertIn("written Scene environment", definition)
            self.assertIn("time-lighting directions are authoritative", definition)
            self.assertIn("keep paths, shrine approaches", definition)
            self.assertIn("remain beside or outside the circulation route", definition)
            self.assertIn("move the Subject toward the fixture", definition)
            self.assertIn("restage framing and lighting", retention)
            self.assertIn("open circulation routes", retention)
            self.assertIn("placement of fixed fixtures", retention)
            self.assertLess(
                prompt.index(definition), prompt.index("summary:")
            )
            self.assertLess(
                prompt.index(retention), prompt.index("detailed_description:")
            )

    def test_binding_is_idempotent_for_same_picture(self) -> None:
        first, _ = bind_h3_background_reference(_plan(), picture_index=2)
        second, _ = bind_h3_background_reference(first, picture_index=2)
        prompt = json.loads(second)["shots"][0]["prompt"]

        self.assertEqual(
            sum(
                line.startswith("<Picture 2> is the environment reference:")
                for line in prompt
            ),
            1,
        )
        self.assertEqual(
            sum(
                line.startswith(
                    "<Picture 2>: environment_partially_preserved -"
                )
                for line in prompt
            ),
            1,
        )

    def test_missing_required_prompt_section_is_rejected(self) -> None:
        plan = json.loads(_plan())
        plan["shots"][0]["prompt"].remove("retention_analysis:")
        with self.assertRaisesRegex(ValueError, "retention_analysis"):
            bind_h3_background_reference(json.dumps(plan), picture_index=2)

    def test_node_passes_image_through_and_registers_public_surface(self) -> None:
        cls = NODE_CLASS_MAPPINGS["MVDirectorH3BackgroundReference"]
        self.assertEqual(
            NODE_DISPLAY_NAME_MAPPINGS["MVDirectorH3BackgroundReference"],
            "MV Director - H3 Background Reference",
        )
        self.assertEqual(cls.RETURN_TYPES, ("STRING", "IMAGE", "STRING"))
        self.assertEqual(
            cls.INPUT_TYPES()["required"]["picture_index"][1],
            {"default": 2, "min": 1, "max": 9},
        )
        image = object()
        output, returned_image, status = cls().bind(_plan(), image, 2)
        self.assertIs(returned_image, image)
        self.assertIn("<Picture 2>", output)
        self.assertEqual(status, "picture=<Picture 2>; shots=2; role=environment")


if __name__ == "__main__":
    unittest.main()
