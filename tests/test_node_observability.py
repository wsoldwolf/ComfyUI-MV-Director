from __future__ import annotations

import logging
import sys
from types import ModuleType
import unittest
from unittest.mock import patch

from nodes import NODE_CLASS_MAPPINGS, NODE_DISPLAY_NAME_MAPPINGS
from nodes.common.node_logging import instrument_node_class
from nodes.common.node_progress import advance_progress, configure_progress, current_progress


class NodeObservabilityTests(unittest.TestCase):
    def test_comfy_progress_tracks_work_and_does_not_complete_blocked_nodes(self) -> None:
        bars = []

        class FakeProgressBar:
            def __init__(self, total):
                self.updates = []
                bars.append(self)

            def update_absolute(self, value, total=None, preview=None):
                self.updates.append((value, total))

        comfy = ModuleType("comfy")
        comfy.__path__ = []
        utils = ModuleType("comfy.utils")
        utils.ProgressBar = FakeProgressBar

        class SuccessfulNode:
            FUNCTION = "run"

            def run(self):
                configure_progress(2)
                advance_progress()
                advance_progress()
                advance_progress()  # Retry grows the denominator.
                return "ok"

        class BlockedNode:
            FUNCTION = "run"
            RETURN_NAMES = ("status",)

            def run(self):
                advance_progress()
                return ("complete=no; missing=ACTION:scene1:slot1",)

        class FailedNode:
            FUNCTION = "run"

            def run(self):
                advance_progress()
                raise ValueError("bad")

        with patch.dict(sys.modules, {"comfy": comfy, "comfy.utils": utils}):
            for cls in (SuccessfulNode, BlockedNode, FailedNode):
                instrument_node_class(cls, cls.__name__)
            self.assertEqual(SuccessfulNode().run(), "ok")
            BlockedNode().run()
            with self.assertRaisesRegex(ValueError, "bad"):
                FailedNode().run()

        self.assertEqual(bars[0].updates[-1], (4, 4))
        self.assertEqual(bars[1].updates[-1], (1, 2))
        self.assertEqual(bars[2].updates[-1], (1, 2))
        self.assertIsNone(current_progress())

    def test_every_public_node_has_lifecycle_logging(self) -> None:
        self.assertEqual(
            set(NODE_CLASS_MAPPINGS),
            set(NODE_DISPLAY_NAME_MAPPINGS),
        )
        for node_class in NODE_CLASS_MAPPINGS.values():
            function = getattr(node_class, node_class.FUNCTION)
            self.assertTrue(getattr(function, "__mvd_node_logged__", False))

    def test_lifecycle_log_contains_node_name_status_and_levels(self) -> None:
        class SuccessfulNode:
            FUNCTION = "run"
            RETURN_NAMES = ("value", "status")

            def run(self):
                return "value", "cache=hit"

        instrument_node_class(SuccessfulNode, "MV Director - Test Node")
        with self.assertLogs("mv_director.nodes", level=logging.INFO) as captured:
            self.assertEqual(
                SuccessfulNode().run(),
                ("value", "cache=hit"),
            )
        output = "\n".join(captured.output)
        self.assertIn("[MV Director - Test Node] started", output)
        self.assertIn("[MV Director - Test Node] completed", output)
        self.assertIn("status=cache=hit", output)
        completed_record = next(
            record for record in captured.records if " completed;" in record.getMessage()
        )
        self.assertEqual(completed_record.color, "cyan")
        self.assertNotIn("\x1b[", completed_record.getMessage())
        self.assertEqual(output.count(" completed;"), 1)

        class FailedNode:
            FUNCTION = "run"

            def run(self):
                raise ValueError("invalid input")

        instrument_node_class(FailedNode, "MV Director - Failed Node")
        with self.assertLogs("mv_director.nodes", level=logging.ERROR) as captured:
            with self.assertRaisesRegex(ValueError, "invalid input"):
                FailedNode().run()
        self.assertIn("[MV Director - Failed Node] failed", captured.output[0])

        class BlockedNode:
            FUNCTION = "run"
            RETURN_NAMES = ("value", "status")

            def run(self):
                return "value", "complete=no; missing=ACTION:scene1:slot1"

        instrument_node_class(BlockedNode, "MV Director - Blocked Node")
        with self.assertLogs("mv_director.nodes", level=logging.WARNING) as captured:
            BlockedNode().run()
        self.assertIn("[MV Director - Blocked Node] blocked", captured.output[-1])

if __name__ == "__main__":
    unittest.main()
