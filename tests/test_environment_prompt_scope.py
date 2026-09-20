"""Fixed renderer rules must not introduce a previous asset's setting."""

from pathlib import Path
import unittest

from core.compiler import compile_ref2va
from core.h3_contract.environment_reference import build_environment_definition


class EnvironmentPromptScopeTests(unittest.TestCase):
    def test_background_rules_do_not_invent_location_but_preserve_author_description(self):
        for description in ("Autumn waterfall", "Empty indoor studio", ""):
            text = build_environment_definition("<Picture 2>", description)
            self.assertIn(description, text)
            for invented in ("torii", "shrine", "lantern"):
                self.assertNotIn(invented, text.lower())
        authored = "A shrine with a red torii and stone lanterns."
        self.assertIn(authored, build_environment_definition("<Picture 2>", authored))

    def test_entire_compiled_waterfall_plan_does_not_gain_shrine(self):
        from test_ref2va_compiler import FIXTURES, EchoTranslator
        source = (FIXTURES / "canonical_ref2va.emd").read_text(encoding="utf-8")
        # The author-owned setting stays intact; neutral renderer rules cannot
        # add their own proper scene inventory anywhere in the output.
        source = source.replace("深い森の神社", "紅葉した滝")
        result = compile_ref2va(source, EchoTranslator()).plan_json()
        for invented in ("torii", "shrine", "lantern"):
            self.assertNotIn(invented, result.lower())

    def test_runtime_instruction_files_do_not_seed_the_old_shrine_asset(self):
        root = Path(__file__).resolve().parents[1]
        for directory, glob in (("prompts", "*.txt"), ("profiles", "*.md")):
            for path in (root / directory).rglob(glob):
                if path.name == "README.md":
                    continue
                text = path.read_text(encoding="utf-8").lower()
                for word in ("torii", "shrine", "lantern", "神社", "鳥居", "灯籠"):
                    with self.subTest(path=path, word=word):
                        self.assertNotIn(word, text)
