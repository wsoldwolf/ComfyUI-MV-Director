"""Context recovery regressions using token preflight, without a GPU."""
import json
import unittest

from core.artifacts import canonical_json
from core.inference import ContextBudgetError, LlamaRuntimeConfig, TokenCount
from core.planner.engine import _Entity, _request_entities
from core.planner.request_budget import complete_with_context_recovery
from nodes.node_timeline_planner.node import _LlamaPlannerBackend


class CountingLifecycle:
    effective_n_ctx = 16384

    def __init__(self, count):
        self.count = count
        self.calls = []

    def count_serialized_prompt(self, prompt):
        request = json.loads(prompt.split("/no_think\n", 1)[1])
        return TokenCount(self.count(request), False)

    def complete_chat(self, messages, config, **kwargs):
        request = json.loads(messages[1]["content"].removeprefix("/no_think\n"))
        self.calls.append((messages, config, request))
        return "\n".join(f"CAMERA\t{s['slot']}\t{s.get('locked_action', 'kept')}"
                         for s in request["slots"])


def request(slots=4, **extra):
    return {"protocol": "MVD_LLM_RECORDS_V1", "task": "cameras",
            "direction": {"camera": ["explicit camera direction"]},
            "slots": [{"slot": i, "scene_number": 9, "locked_action": f"動作{i}",
                       "previous_arc_path": "arc_left_60_120_70_90"}
                      for i in range(1, slots + 1)], **extra}


class PlannerContextBudgetTests(unittest.TestCase):
    def test_reported_26_token_overflow_fits_output_and_preserves_input(self):
        lifecycle = CountingLifecycle(lambda _: 13563)
        backend = _LlamaPlannerBackend(lifecycle)
        config = LlamaRuntimeConfig(max_tokens=1536)
        payload = canonical_json(request(retry="camera_quality_budget"))
        with self.assertLogs("mv_director.nodes", level="INFO") as logs:
            response = complete_with_context_recovery(
                backend, task="cameras", system_prompt="system",
                payload=payload, config=config)
        self.assertEqual(len(lifecycle.calls), 1)
        messages, actual_config, _ = lifecycle.calls[0]
        self.assertEqual(actual_config.max_tokens, 1510)
        self.assertEqual(config.max_tokens, 1536)
        self.assertEqual(messages[1]["content"], "/no_think\n" + payload)
        self.assertEqual(13563 + actual_config.max_tokens + 1311, 16384)
        self.assertIn("動作4", response)
        self.assertIn("context output fitted", "\n".join(logs.output))
        self.assertIn("retry=camera_quality_budget", "\n".join(logs.output))
        self.assertIn("max_tokens=1510", "\n".join(logs.output))

    def test_normal_request_keeps_requested_output(self):
        lifecycle = CountingLifecycle(lambda _: 1000)
        complete_with_context_recovery(
            _LlamaPlannerBackend(lifecycle), task="cameras", system_prompt="system",
            payload=canonical_json(request()), config=LlamaRuntimeConfig(max_tokens=1536))
        self.assertEqual(len(lifecycle.calls), 1)
        self.assertEqual(lifecycle.calls[0][1].max_tokens, 1536)

    def test_large_initial_and_quality_requests_split_without_repeating_successes(self):
        for retry in ("no", "camera_quality_budget", "repeated_slots_only"):
            with self.subTest(retry=retry):
                lifecycle = CountingLifecycle(lambda r: 12600 + 400 * len(r["slots"]))
                backend = _LlamaPlannerBackend(lifecycle)
                entities = [_Entity(9, (9, i), s)
                            for i, s in enumerate(request(8)["slots"], 1)]
                shared = {"retry": retry, "direction": {"camera": ["author text"]}}
                values, _, _, missing, _ = _request_entities(
                    backend, task="cameras", record_type="CAMERA", entities=entities,
                    shared=shared, system_prompt="system",
                    runtime_config=LlamaRuntimeConfig(max_tokens=1536),
                    interrupt_callback=None)
                self.assertFalse(missing)
                self.assertEqual(values, {(9, i): f"動作{i}" for i in range(1, 9)})
                self.assertEqual(len(lifecycle.calls), 4)
                seen = []
                for _, config, part in lifecycle.calls:
                    self.assertEqual(part["direction"], shared["direction"])
                    self.assertEqual(part["retry"], retry)
                    self.assertLessEqual(12600 + 400 * len(part["slots"]) + config.max_tokens + 1311, 16384)
                    seen.extend(s["slot"] for s in part["slots"])
                self.assertEqual(seen, list(range(1, 9)))
                self.assertEqual(len(backend.trace), 4)

    def test_missing_and_isolated_retries_keep_non_contiguous_slot_mapping(self):
        class Backend:
            def __init__(self):
                self.seen = []
            def complete_planner(self, *, payload, **kwargs):
                r = json.loads(payload)
                retry = r.get("retry")
                slots = [s["slot"] for s in r["slots"]]
                self.seen.append((retry, slots))
                if not retry:
                    return "CAMERA\t1\tone\nCAMERA\t3\tthree"
                if len(slots) > 1:
                    raise ContextBudgetError("oversized retry")
                if retry == "missing_slots_only" and slots == [4]:
                    return ""
                return f"CAMERA\t{slots[0]}\tkept{slots[0]}"
        backend = Backend()
        values, _, _, missing, _ = _request_entities(
            backend, task="cameras", record_type="CAMERA",
            entities=[_Entity(9, (9, i), {}) for i in range(1, 5)],
            shared={}, system_prompt="system",
            runtime_config=LlamaRuntimeConfig(), interrupt_callback=None)
        self.assertFalse(missing)
        self.assertEqual(values, {(9, 1): "one", (9, 2): "kept2", (9, 3): "three", (9, 4): "kept4"})
        self.assertIn(("missing_slots_only", [2, 4]), backend.seen)
        self.assertIn(("isolated_missing_slot", [4]), backend.seen)
        self.assertEqual(sum(slots == [1] for _, slots in backend.seen), 0)

    def test_singleton_reduces_old_history_but_keeps_current_constraints(self):
        original = request(1, retry="camera_quality_budget",
                           recent_camera_history=["old", "middle", "new"],
                           recent_action_history=["old action", "new action"])
        original["slots"][0]["rejected_output"] = "original rejected text"
        original["slots"][0]["camera_quality_violations"] = ["direction reversal"]
        lifecycle = CountingLifecycle(lambda r: 13200 + 600 * (
            len(r["recent_camera_history"]) + len(r["recent_action_history"])))
        with self.assertLogs("mv_director.nodes", level="INFO") as logs:
            complete_with_context_recovery(
                _LlamaPlannerBackend(lifecycle), task="cameras", system_prompt="system",
                payload=canonical_json(original), config=LlamaRuntimeConfig(max_tokens=1536))
        self.assertEqual(len(lifecycle.calls), 1)
        actual = lifecycle.calls[0][2]
        self.assertEqual(actual["slots"], original["slots"])
        self.assertEqual(actual["direction"], original["direction"])
        for name in ("recent_camera_history", "recent_action_history"):
            self.assertTrue(not actual[name] or actual[name] == original[name][-len(actual[name]):])
        self.assertEqual(len(original["recent_camera_history"]), 3)
        self.assertIn("context history reduced", "\n".join(logs.output))

    def test_required_singleton_too_large_fails_before_any_inference(self):
        lifecycle = CountingLifecycle(lambda _: 16000)
        backend = _LlamaPlannerBackend(lifecycle)
        with self.assertRaisesRegex(ContextBudgetError, "task=cameras; retry=no; slots=\\[1\\]"):
            complete_with_context_recovery(
                backend, task="cameras", system_prompt="system",
                payload=canonical_json(request(1)), config=LlamaRuntimeConfig(max_tokens=1536))
        self.assertFalse(lifecycle.calls)
        self.assertFalse(backend._task_calls)

    def test_interrupt_and_non_budget_error_do_not_trigger_recovery(self):
        class Backend:
            def complete_planner(self, **kwargs):
                raise RuntimeError("model failed")
        with self.assertRaisesRegex(RuntimeError, "model failed"):
            complete_with_context_recovery(
                Backend(), task="cameras", system_prompt="system",
                payload=canonical_json(request()), config=LlamaRuntimeConfig())
        def interrupt():
            raise InterruptedError("stop")
        with self.assertRaises(InterruptedError):
            complete_with_context_recovery(
                Backend(), task="cameras", system_prompt="system",
                payload=canonical_json(request()), config=LlamaRuntimeConfig(),
                interrupt_callback=interrupt)


if __name__ == "__main__":
    unittest.main()
