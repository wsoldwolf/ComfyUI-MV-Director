"""Model-specific Planner transport fast paths, without loading a model."""

import json
import unittest

from core.inference import LlamaRuntimeConfig, TokenCount
from core.planner.requests import request_entities
from core.planner.types import PlannerEntity
from nodes.node_timeline_planner.node import (
    _LlamaPlannerBackend,
    _PLANNER_TRANSPORT_26B_FAST,
    _PLANNER_TRANSPORT_31B_FAST,
    _PLANNER_TRANSPORT_CONSTRAINED,
    _planner_transport_policy,
)


class ScriptedLifecycle:
    effective_n_ctx = 16384

    def __init__(self, outputs):
        self.outputs = iter(outputs)
        self.calls = []

    def count_serialized_prompt(self, prompt):
        return TokenCount(100, False)

    def complete_chat(self, messages, config, **kwargs):
        self.calls.append((messages, config, kwargs))
        return next(self.outputs)


def _backend(outputs, policy=_PLANNER_TRANSPORT_26B_FAST):
    lifecycle = ScriptedLifecycle(outputs)
    backend = _LlamaPlannerBackend(lifecycle)
    backend.transport_policy = policy
    return backend, lifecycle


def _payload(*slots, task="scene-author-event", **extra):
    return json.dumps({
        "protocol": "MVD_LLM_RECORDS_V1",
        "task": task,
        "slots": [{"slot": slot, "scene_number": 1} for slot in slots],
        **extra,
    })


def _complete(backend, payload, task="scene-author-event"):
    return backend.complete_planner(
        task=task, system_prompt="system", payload=payload,
        config=LlamaRuntimeConfig(max_tokens=1024),
    )


class PlannerFastTransportTests(unittest.TestCase):
    def test_policy_is_exact_model_opt_in(self):
        name = "Gemma4-26B-A4B-Uncensored-HauhauCS-Balanced-IQ2_M.gguf"
        self.assertEqual(_planner_transport_policy("folder/" + name),
                         _PLANNER_TRANSPORT_26B_FAST)
        name = "gemma-4-31b-it-heretic-ara.Q4_K_S.gguf"
        self.assertEqual(_planner_transport_policy("folder\\" + name),
                         _PLANNER_TRANSPORT_31B_FAST)
        for other in ("gemma-4-31b-it-heretic-ara.Q6_K.gguf",
                      "Gemma4-26B-A4B-Uncensored-HauhauCS-Balanced-IQ3_M.gguf",
                      "Gemma4-12B-QAT-Uncensored-HauhauCS-Balanced.gguf"):
            self.assertEqual(_planner_transport_policy(other),
                             _PLANNER_TRANSPORT_CONSTRAINED)

    def test_31b_performance_and_camera_use_no_grammar(self):
        for task, record_type in (
            ("scene-author-performance", "PERFORMANCE"),
            ("scene-author-camera", "CAMERA"),
        ):
            with self.subTest(task=task):
                response = f"{record_type}\t1\t人物を捉える。"
                backend, lifecycle = _backend([response],
                                              _PLANNER_TRANSPORT_31B_FAST)
                self.assertEqual(_complete(backend, _payload(1, task=task), task),
                                 response)
                self.assertEqual(len(lifecycle.calls), 1)
                self.assertNotIn("grammar", lifecycle.calls[0][2])

    def test_31b_event_remains_constrained(self):
        backend, lifecycle = _backend(["EVENT\t1\t苔が光る。"],
                                      _PLANNER_TRANSPORT_31B_FAST)
        self.assertEqual(_complete(backend, _payload(1)), "EVENT\t1\t苔が光る。")
        self.assertIn("grammar", lifecycle.calls[0][2])

    def test_31b_protocol_issue_falls_back_to_grammar(self):
        backend, lifecycle = _backend([
            "PERFORMANCE\t1\t一。\nPERFORMANCE\t1\t重複。",
            "PERFORMANCE\t1\t二。",
        ], _PLANNER_TRANSPORT_31B_FAST)
        task = "scene-author-performance"
        self.assertEqual(_complete(backend, _payload(1, task=task), task),
                         "PERFORMANCE\t1\t二。")
        self.assertEqual(len(lifecycle.calls), 2)
        self.assertNotIn("grammar", lifecycle.calls[0][2])
        self.assertIn("grammar", lifecycle.calls[1][2])

    def test_valid_initial_response_uses_no_grammar(self):
        response = "EVENT\t1\t苔が光る。\nEVENT\t2\t人物が見つめる。"
        backend, lifecycle = _backend([response])
        with self.assertLogs("mv_director.nodes", level="INFO") as logs:
            self.assertEqual(_complete(backend, _payload(1, 2)), response)
        self.assertEqual(len(lifecycle.calls), 1)
        self.assertNotIn("grammar", lifecycle.calls[0][2])
        self.assertIn("unconstrained protocol accepted", "\n".join(logs.output))
        self.assertEqual(backend.trace[0]["response"], response)

    def test_missing_slot_is_retried_with_grammar_without_replacing_valid_text(self):
        backend, lifecycle = _backend([
            "EVENT\t1\t最初の表現。",
            "EVENT\t2\t補われた表現。",
        ])
        entities = [PlannerEntity(1, (1, i), {"scene_number": 1})
                    for i in (1, 2)]
        with self.assertLogs("mv_director.nodes", level="INFO") as logs:
            values, _, _, missing, _ = request_entities(
                backend, task="scene-author-event", record_type="EVENT",
                entities=entities, shared={}, system_prompt="system",
                runtime_config=LlamaRuntimeConfig(max_tokens=1024),
                interrupt_callback=None,
            )
        self.assertEqual(values, {(1, 1): "最初の表現。", (1, 2): "補われた表現。"})
        self.assertFalse(missing)
        self.assertEqual(len(lifecycle.calls), 2)
        self.assertNotIn("grammar", lifecycle.calls[0][2])
        self.assertIn("grammar", lifecycle.calls[1][2])
        retry = json.loads(lifecycle.calls[1][0][1]["content"].removeprefix("/no_think\n"))
        self.assertEqual([slot["slot"] for slot in retry["slots"]], [2])
        self.assertIn("fallback=targeted_grammar_retry", "\n".join(logs.output))

    def test_protocol_issue_falls_back_to_grammar(self):
        backend, lifecycle = _backend([
            "EVENT\t1\t一。\nEVENT\t1\t重複。",
            "EVENT\t1\t二。",
        ])
        with self.assertLogs("mv_director.nodes", level="WARNING") as logs:
            self.assertEqual(_complete(backend, _payload(1)), "EVENT\t1\t二。")
        self.assertEqual(len(lifecycle.calls), 2)
        self.assertNotIn("grammar", lifecycle.calls[0][2])
        self.assertIn("grammar", lifecycle.calls[1][2])
        self.assertNotEqual(lifecycle.calls[0][1].seed, lifecycle.calls[1][1].seed)
        self.assertIn("fallback=grammar_full_batch", "\n".join(logs.output))
        self.assertEqual(
            backend.trace[0]["unconstrained_response"],
            "EVENT\t1\t一。\nEVENT\t1\t重複。",
        )
        self.assertIn('"reason": "duplicate"', backend.trace[0]["unconstrained_issues"])

    def test_warning_reports_shape_without_prose(self):
        backend, _ = _backend([
            "event\t1\t歌詞の本文。",
            "EVENT\t1\t採用する本文。",
        ])
        with self.assertLogs("mv_director.nodes", level="WARNING") as logs:
            _complete(backend, _payload(1))
        warning = "\n".join(logs.output)
        self.assertIn("line1:unknown_type:type=event:tabs=2", warning)
        self.assertNotIn("歌詞の本文", warning)
        self.assertEqual(backend.trace[0]["unconstrained_response"],
                         "event\t1\t歌詞の本文。")

    def test_retries_and_other_models_remain_constrained(self):
        for policy, payload in (
            (_PLANNER_TRANSPORT_26B_FAST, _payload(1, retry="missing_slots_only")),
            (_PLANNER_TRANSPORT_31B_FAST, _payload(1, retry="missing_slots_only")),
            (_PLANNER_TRANSPORT_CONSTRAINED, _payload(1)),
        ):
            with self.subTest(policy=policy):
                backend, lifecycle = _backend(["EVENT\t1\t一。"], policy)
                self.assertEqual(_complete(backend, payload), "EVENT\t1\t一。")
                self.assertIn("grammar", lifecycle.calls[0][2])


if __name__ == "__main__":
    unittest.main()
