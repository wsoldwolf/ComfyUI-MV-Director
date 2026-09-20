import json
import unittest

from core.artifacts import DirectionArtifact
from core.emd import parse_emd
from core.planner import parse_template_emd
from core.planner.engine import _Entity, _request_entities
from core.planner.renderer import render_completed_emd
from core.planner.text_normalization import strip_generated_line_continuation
from test_timeline_planner import CONCEPT, TEMPLATE, runtime


class GeneratedTextNormalizationTests(unittest.TestCase):
    def test_observed_single_trailing_marker_only(self):
        for source in ("鳥居の上空を風が抜けて行く", "風が鳥居を抜けて行く", "風が去った"):
            for spacing in (" ", "\t", "\u3000\u3000"):
                with self.subTest(source=source, spacing=spacing):
                    self.assertEqual(strip_generated_line_continuation(source + spacing + "\\"), source)
                    self.assertEqual(strip_generated_line_continuation(source + spacing + "\\ \t"), source)

    def test_meaningful_or_ambiguous_backslashes_are_preserved(self):
        for text in ("C:" + chr(92) + "video" + chr(92),
                     "path C:" + chr(92) + "my folder" + chr(92), r"one \ two",
                     "「\\」を見る", "`\\`", "末尾" + "\\", "末尾 " + "\\\\",
                     " \\", "\\", "正常な本文", "本文  ", "a\nb"):
            with self.subTest(text=text):
                self.assertEqual(strip_generated_line_continuation(text), text)

    def test_cleanup_is_idempotent(self):
        once = strip_generated_line_continuation("風が去った　　\\")
        self.assertEqual(strip_generated_line_continuation(once), once)

    def test_adapter_normalizes_action_and_camera_before_audit_but_not_other_records(self):
        class Backend:
            def complete_planner(self, *, task, payload, **kwargs):
                record = {"actions": "ACTION", "cameras": "CAMERA", "visual-beats": "BEAT"}[task]
                return f"{record}\t1\t風が去った　　\\"
        for task, record in (("actions", "ACTION"), ("cameras", "CAMERA"), ("visual-beats", "BEAT")):
            result = _request_entities(Backend(), task=task, record_type=record,
                       entities=[_Entity(2, (2, 1), {})], shared={}, system_prompt="test",
                       runtime_config=runtime(), interrupt_callback=None)
            self.assertEqual(result[0][(2, 1)], "風が去った　　\\" if record == "BEAT" else "風が去った")
            self.assertEqual(result[3], ())

    def test_isolated_protocol_retry_also_cleans_suffix(self):
        class Backend:
            def complete_planner(self, *, payload, **kwargs):
                request = json.loads(payload)
                return "ACTION\t1\t風が去った　　\\" if request.get("retry") else ""
        result = _request_entities(Backend(), task="actions", record_type="ACTION",
                    entities=[_Entity(2, (2, 1), {})], shared={}, system_prompt="test",
                    runtime_config=runtime(), interrupt_callback=None)
        self.assertEqual(result[0][(2, 1)], "風が去った")

    def test_renderer_cleans_cached_generated_text_and_keeps_author_and_direction(self):
        author = "作者指定　　\\"
        template = parse_template_emd(TEMPLATE.replace("* 未計画", "* " + author))
        actions = {(1, 1): "風が去った　　\\", (1, 2): "「\\」を見る"}
        cameras = {(1, 1): "Static Shot \\"}
        with self.assertLogs("mv_director.nodes", level="INFO") as logs:
            result = render_completed_emd(concept_emd=CONCEPT, template=template,
                      direction=DirectionArtifact(other_direction=(author,)), actions=actions,
                      cameras=cameras, lip_sync_mode="off", lip_sync_target="サブジェクト1",
                      lip_sync_audio_slot=1)
        document = parse_emd(result.text)
        self.assertEqual(document.scenes[0].shots[0].body, (author, "風が去った", "Static Shot"))
        self.assertIn(author, document.common_prompt_dict()["その他"])
        self.assertEqual(actions[(1, 1)], "風が去った　　\\")
        self.assertIn("lines=2", " ".join(logs.output))


if __name__ == "__main__":
    unittest.main()
