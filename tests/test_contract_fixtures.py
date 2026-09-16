from __future__ import annotations

import json
import re
import unittest
from pathlib import Path

from core.namespaces import (
    CUSTOM_SOCKET_TYPES,
    PUBLIC_CATEGORIES,
    PUBLIC_NODE_TYPES,
    validate_namespace_contract,
)
from core.protocols import (
    VISION_COMPOSITION_KEYS,
    VISION_END_MARKER,
    VISION_PROTOCOL_ID,
    VISION_STYLE_KEYS,
)


FIXTURES = Path(__file__).parent / "fixtures"
SECTION_ORDER = (
    "subject_definitions:",
    "summary:",
    "retention_analysis:",
    "detailed_description:",
    "overall_soundscape:",
    "non_diegetic_music:",
)


class NamespaceContractTests(unittest.TestCase):
    def test_public_namespace_is_new_project_only(self) -> None:
        validate_namespace_contract()
        self.assertEqual(len(PUBLIC_NODE_TYPES), 11)
        self.assertTrue(all(value.startswith("MVDirector") for value in PUBLIC_NODE_TYPES))
        self.assertTrue(
            all(value.startswith("MV_DIRECTOR_") for value in CUSTOM_SOCKET_TYPES)
        )
        self.assertTrue(
            all(value.startswith("MV Director/") for value in PUBLIC_CATEGORIES)
        )


class ContractFixtureTests(unittest.TestCase):
    def test_vision_fixture_uses_new_protocol_and_fixed_subkeys(self) -> None:
        lines = (
            FIXTURES / "protocol" / "vision_observation_valid.txt"
        ).read_text(encoding="utf-8").splitlines()
        self.assertEqual(lines[0], VISION_PROTOCOL_ID)
        self.assertEqual(lines[-1], VISION_END_MARKER)
        record_types = tuple(line.split("\t", 1)[0] for line in lines)
        self.assertEqual(
            tuple(key for key in VISION_COMPOSITION_KEYS if key.upper() in record_types),
            VISION_COMPOSITION_KEYS,
        )
        self.assertEqual(
            tuple(
                key
                for key in VISION_STYLE_KEYS
                if f"STYLE_{key.upper()}" in record_types
            ),
            VISION_STYLE_KEYS,
        )
        self.assertFalse(any("cl-vision" in line for line in lines))

    def test_canonical_emd_has_required_scene_annotation_and_absolute_times(self) -> None:
        source = (FIXTURES / "emd" / "canonical_ref2va.emd").read_text(
            encoding="utf-8"
        )
        self.assertIn("> `シーン` 1\n# シーン 00:00.000 --> 00:10.125", source)
        self.assertRegex(source, r"## ショット [0-9]{2}:[0-5][0-9]\.[0-9]{3}")
        self.assertNotIn("`画像", source)

    def test_invalid_emd_fixtures_express_single_contract_failures(self) -> None:
        missing = (
            FIXTURES / "emd" / "invalid_missing_scene_annotation.emd"
        ).read_text(encoding="utf-8")
        conflict = (
            FIXTURES / "emd" / "invalid_conflicting_lip_sync.emd"
        ).read_text(encoding="utf-8")
        self.assertNotIn("> `シーン`", missing)
        self.assertIn("`Audio参照`", conflict)
        self.assertIn("`歌詞` `サブジェクト1`", conflict)

    def test_context_loop_fixture_has_six_sections_and_raw_length_only(self) -> None:
        payload = json.loads(
            (
                FIXTURES / "h3" / "context_loop_0_6_9_minimal_plan.json"
            ).read_text(encoding="utf-8")
        )
        self.assertIn("prompt_prefix", payload)
        scene = payload["shots"][0]
        self.assertEqual(scene["id"], "scene_0001")
        self.assertEqual(scene["length"], 243)
        self.assertNotIn("duration_seconds", scene)
        self.assertNotIn("duration_ms", scene)
        positions = [scene["prompt"].index(section) for section in SECTION_ORDER]
        self.assertEqual(positions, sorted(positions))
        self.assertRegex(
            "\n".join(scene["prompt"]),
            re.compile(r"\[Shot 2\] At 00:05\.000,"),
        )


if __name__ == "__main__":
    unittest.main()
