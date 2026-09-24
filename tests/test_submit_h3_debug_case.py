"""CPU-only check for checkpoint resume submission wiring."""

import io
import json
from contextlib import redirect_stdout
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

from tools.submit_h3_debug_case import main


class SubmitH3DebugCaseTests(unittest.TestCase):
    def test_full_resume_preserves_seeds_and_sets_cleanup(self):
        kinds = {
            "48": "MVDirectorSceneDebugSplitter",
            "24": "MiniMaxH3ChainPlanModern",
            "37": "MVDirectorAudioPadPair", "15": "BasicScheduler",
            "7": "MiniMaxH3ChainLoopStart", "29": "MiniMaxH3ChainPreflight",
            "23": "MiniMaxH3ChainLoopEnd", "28": "MiniMaxH3ChainReview",
            "21": "MiniMaxH3ChainAssemble",
        }
        graph = {key: {"class_type": kind, "inputs": {}} for key, kind in kinds.items()}
        graph["21"]["inputs"] = {"manifest": ["28", 0]}
        graph["28"]["inputs"] = {"segment": ["23", 0]}
        graph["23"]["inputs"] = {"state": ["29", 0]}
        graph["29"]["inputs"] = {"plan": ["7", 0]}
        graph["7"]["inputs"] = {"plan": ["24", 0]}
        metadata = {"prompt": graph, "h3_plan": {"shots": [{"seed": seed} for seed in (11, 22, 33, 44)]}}
        plan = {"shots": [{"id": f"scene_{index}"} for index in range(1, 5)]}
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            metadata_path, plan_path, evidence_path = (root / name for name in
                ("metadata.json", "plan.json", "evidence.json"))
            metadata_path.write_text(json.dumps(metadata), encoding="utf-8")
            plan_path.write_text(json.dumps(plan), encoding="utf-8")
            argv = ["submit_h3_debug_case.py", "--metadata", str(metadata_path),
                    "--plan", str(plan_path), "--case", "resume-test", "--full",
                    "--start-clip", "4", "--between-scene-cleanup", "fresh_scene",
                    "--evidence", str(evidence_path)]
            with patch.object(sys, "argv", argv), patch("urllib.request.urlopen",
                    return_value=io.BytesIO(b'{"prompt_id":"test"}')) as send, redirect_stdout(io.StringIO()):
                main()
            request = send.call_args.args[0]
            submitted = json.loads(request.data)["prompt"]
            self.assertEqual(submitted["7"]["inputs"]["start_clip"], 4)
            self.assertEqual(submitted["29"]["inputs"]["start_clip"], 4)
            self.assertEqual(submitted["23"]["inputs"]["between_scene_cleanup"], "fresh_scene")
            self.assertEqual(json.loads(submitted["24"]["inputs"]["plan_json"])["shots"][-1]["seed"], 44)
            self.assertEqual(json.loads(evidence_path.read_text(encoding="utf-8"))["start_clip"], 4)


if __name__ == "__main__":
    unittest.main()
