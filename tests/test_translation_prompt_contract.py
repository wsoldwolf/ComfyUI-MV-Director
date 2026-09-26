"""The translation prompt must describe the actual split/restore contract."""
from pathlib import Path
import unittest

from core.compiler.protection import protect_unit

ROOT = Path(__file__).resolve().parents[1]


class TranslationPromptContractTests(unittest.TestCase):
    def test_prompt_does_not_seed_retired_placeholder_examples(self):
        prompt = (ROOT / "prompts/prompt_translation_ja_en_system_prompt.txt").read_text(encoding="utf-8")
        self.assertNotIn("MVD_PROTECTED_", prompt)
        self.assertIn("No placeholder is substituted", prompt)
        self.assertIn("middle of a clause", prompt)
        self.assertIn("any literal tokens actually present", prompt)

    def test_protected_camera_is_absent_from_translation_fragments(self):
        unit = protect_unit("Push Inで開始し、祈る手へ寄る。", ())
        self.assertNotIn("Push In", "".join(unit.fragments))
        self.assertNotIn("MVD_PROTECTED_", "".join(unit.fragments))
        self.assertIn("で開始し", "".join(unit.fragments))
        self.assertIn("Push In", unit.values)

    def test_mapped_terms_are_restored_by_caller_not_placeholder_model(self):
        unit = protect_unit("足袋と下駄を着用し、鼻緒は赤い。", ())
        self.assertEqual(unit.values, ("tabi", "geta", "hanao strap"))
        self.assertNotIn("MVD_PROTECTED_", "".join(unit.fragments))
        self.assertIn("tabi", unit.restore())


if __name__ == "__main__":
    unittest.main()
