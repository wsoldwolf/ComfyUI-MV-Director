"""Production carryable planning contracts; no GPU or semantic certification."""
import json
import unittest
from unittest.mock import patch

from core.artifacts import DirectionArtifact
from core.inference import ContextBudgetError, LlamaRuntimeConfig, TokenCount
from core.planner import plan_timeline
from core.planner.prop_inventory import request_prop_inventory
from core.planner.prop_decision import request_prop_decisions
from nodes.node_timeline_planner.node import (
    _LlamaPlannerBackend, _PLANNER_TRANSPORT_31B_FAST, _system_prompts,
)
from scene_author_fixtures import Backend, TEMPLATE, _runtime

PROPS = [
    {"id": "P1", "subject": "人物1", "label": "道具A", "evidence": "道具A",
     "initial_state": "右手"},
    {"id": "P2", "subject": "人物1", "label": "道具B", "evidence": "道具B",
     "initial_state": "未確定"},
]
DECISION = {
    "prop_locations": {"P1": "右手の道具A", "P2": "左手の道具B"},
    "right_hand": "道具Aを握る", "left_hand": "道具Bを握る",
    "transition": "なし", "performance_scope": "体幹と肘を動かす",
    "end_state": {"P1": "右手の道具A", "P2": "左手の道具B"},
}
CONCEPT = "# サブジェクト\n* 道具Aと道具Bを持つ人物。\n"


class HoldingBackend(Backend):
    def __init__(self, inventory=PROPS, fail_task=None):
        super().__init__()
        self.inventory = inventory
        self.fail_task = fail_task
        self.prompts = []
        self.progress_counts = []

    def configure_prop_progress(self, count):
        self.progress_counts.append(count)

    def complete_planner(self, *, task, payload, system_prompt, **kwargs):
        self.prompts.append((task, system_prompt))
        if task in {"subject-prop-inventory", "scene-author-prop-decision"}:
            request = json.loads(payload)
            self.calls.append((task, request))
            if self.fail_task == task:
                return "invalid"
            if task == "subject-prop-inventory":
                return "PROP_INVENTORY\t1\t" + json.dumps({"props": self.inventory})
            return "\n".join(
                f"PROP_DECISION\t{s['slot']}\t{json.dumps(DECISION)}"
                for s in request["slots"]
            )
        return super().complete_planner(task=task, payload=payload, **kwargs)


def plan(backend, template=TEMPLATE, direction=None):
    return plan_timeline(
        backend, template_emd=template, concept_emd=CONCEPT,
        direction=direction or DirectionArtifact(), lip_sync_mode="off",
        lip_sync_target="サブジェクト1", lip_sync_audio_slot=1,
        system_prompts=_system_prompts(prop_holding=True), runtime_config=_runtime(),
    )


class PropHoldingPipelineTests(unittest.TestCase):
    def test_inventory_decision_performance_camera_and_author_priority(self):
        backend = HoldingBackend()
        result = plan(backend)
        self.assertTrue(result.complete)
        self.assertEqual([task for task, _ in backend.calls], [
            "subject-prop-inventory", "scene-author-event", "scene-author-prop-decision",
            "scene-author-performance", "scene-author-camera",
        ])
        inventory = backend.calls[0][1]
        self.assertEqual(inventory["subject_emd"], CONCEPT)
        self.assertEqual(inventory["fixed_boundary_performances"],
                         {"1": "人物が片手を胸元に置く。"})
        for task, payload in backend.calls[2:]:
            self.assertEqual(payload["prop_inventory"], PROPS)
            if task != "scene-author-prop-decision":
                self.assertEqual(payload["accepted_prop_decisions"],
                                 {"1": DECISION, "2": DECISION})
                self.assertEqual([s["shot"] for s in payload["slots"]], [2])
        self.assertIn("* `演技` 人物が片手を胸元に置く。", result.emd.text)
        self.assertIn("* `カメラ` 目と口が見える正面。", result.emd.text)
        self.assertNotIn("PROP_DECISION", result.emd.text)
        self.assertNotIn("prop_locations", result.emd.text)
        performance_prompt = next(p for task, p in backend.prompts
                                  if task == "scene-author-performance")
        self.assertIn("accepted_prop_decisions", performance_prompt)
        self.assertEqual(backend.progress_counts, [1])

    def test_empty_inventory_skips_scene_decisions_and_addendum(self):
        backend = HoldingBackend(inventory=[])
        self.assertTrue(plan(backend).complete)
        self.assertEqual(len(backend.calls), 4)
        self.assertNotIn("scene-author-prop-decision", [t for t, _ in backend.calls])
        for task, payload in backend.calls[1:]:
            self.assertNotIn("prop_inventory", payload)
        self.assertEqual(next(p for task, p in backend.prompts
                              if task == "scene-author-performance"),
                         _system_prompts()["scene-author-performance"])
        self.assertEqual(backend.progress_counts, [0])

    def test_invalid_inventory_or_decision_falls_back_after_two_attempts(self):
        for task in ("subject-prop-inventory", "scene-author-prop-decision"):
            with self.subTest(task=task):
                backend = HoldingBackend(fail_task=task)
                with self.assertLogs("mv_director.nodes", level="WARNING"):
                    self.assertTrue(plan(backend).complete)
                self.assertEqual(sum(t == task for t, _ in backend.calls), 2)
                for stage, payload in backend.calls:
                    if stage in {"scene-author-performance", "scene-author-camera"}:
                        self.assertNotIn("accepted_prop_decisions", payload)

    def test_fully_authored_input_skips_all_inference(self):
        source = TEMPLATE.replace("* 未計画", "* `演技` 固定の動き。\n* `カメラ` 固定の画角。")
        backend = HoldingBackend()
        self.assertTrue(plan(backend, source).complete)
        self.assertEqual(backend.calls, [])

    def test_inventory_once_continuous_state_then_cut_reset(self):
        source = TEMPLATE + (
            "> `シーン` 2\n# シーン 00:01.000 --> 00:02.000 継続\n"
            "* `H3長` 22\n## ショット 00:01.000\n* 未計画\n"
            "> `シーン` 3\n# シーン 00:02.000 --> 00:03.000\n"
            "* `H3長` 22\n## ショット 00:02.000\n* 未計画\n"
        )
        backend = HoldingBackend()
        self.assertTrue(plan(backend, source).complete)
        decisions = [p for t, p in backend.calls if t == "scene-author-prop-decision"]
        self.assertEqual(decisions[0]["previous_prop_state"], "")
        self.assertEqual(decisions[1]["previous_prop_state"], DECISION["end_state"])
        self.assertEqual(decisions[2]["previous_prop_state"], "")
        self.assertEqual(sum(t == "subject-prop-inventory" for t, _ in backend.calls), 1)

    def test_existing_pre_author_composition_is_visible_without_changing_text(self):
        source = "> `シーン` 1\n# シーン 00:00.000 --> 00:06.583\n* `H3長` 158\n## ショット 00:00.000\n* 未計画\n"
        backend = HoldingBackend()
        result = plan(backend, source, DirectionArtifact(motion_templates=("補完の動き。",)))
        self.assertTrue(result.complete)
        decision = next(p for t, p in backend.calls if t == "scene-author-prop-decision")
        self.assertEqual(decision["planned_motion_composition"]["text"], "補完の動き。")
        self.assertIn("補完の動き。", result.emd.text)

    def test_post_author_choice_receives_plan_without_moving_composition(self):
        source = "> `シーン` 1\n# シーン 00:00.000 --> 00:06.583\n* `H3長` 158\n## ショット 00:00.000\n* 未計画\n"
        backend = HoldingBackend()
        result = plan(backend, source, DirectionArtifact(
            motion_profile_id="anime_scene_composed_mv",
            motion_templates=("補完A。", "補完B。"),
        ))
        self.assertTrue(result.complete)
        choice = next(p for t, p in backend.calls if t == "scene-author-composition-choice")
        performance = next(p for t, p in backend.calls if t == "scene-author-performance")
        camera = next(p for t, p in backend.calls if t == "scene-author-camera")
        self.assertEqual(choice["accepted_prop_decisions"], {"1": DECISION})
        self.assertNotIn("scheduled_motion_composition", performance)
        self.assertNotIn("補完A。", camera["accepted_performances"]["1"])
        self.assertIn("補完A。", result.emd.text)

    def test_normal_prompt_bundle_opt_in_is_explicit(self):
        prompts = _system_prompts(prop_holding=True)
        self.assertTrue({"subject-prop-inventory", "scene-author-prop-decision",
                         "prop-performance-addendum"}.issubset(prompts))

    def test_new_tasks_stay_grammar_constrained_on_fast_transport(self):
        class Lifecycle:
            effective_n_ctx = 16384
            calls = []
            def count_serialized_prompt(self, text):
                return TokenCount(100, False)
            def complete_chat(self, messages, config, **kwargs):
                self.calls.append((messages, config, kwargs))
                return "response"
        lifecycle = Lifecycle()
        backend = _LlamaPlannerBackend(lifecycle)
        backend.transport_policy = _PLANNER_TRANSPORT_31B_FAST
        for task, label in (("subject-prop-inventory", "PROP_INVENTORY"),
                            ("scene-author-prop-decision", "PROP_DECISION")):
            backend.complete_planner(task=task, system_prompt="test",
                payload=json.dumps({"slots": [{"slot": 1, "scene_number": 1}]}),
                config=LlamaRuntimeConfig(max_tokens=4096))
            self.assertIn(label, lifecycle.calls[-1][2]["grammar"])
            self.assertEqual(lifecycle.calls[-1][1].max_tokens, 1536)

    def test_optional_context_overflow_drops_only_advisory_data_before_inference(self):
        class Lifecycle:
            effective_n_ctx = 16384
            def count_serialized_prompt(self, text):
                return TokenCount(20000 if "accepted_prop_decisions" in text else 100, False)
            def complete_chat(self, messages, config, **kwargs):
                self.messages = messages
                return "PERFORMANCE\t1\t通常の演技。"
        lifecycle = Lifecycle()
        backend = _LlamaPlannerBackend(lifecycle)
        prompts = _system_prompts(prop_holding=True)
        payload = {"slots": [{"slot": 1}], "prop_inventory": PROPS,
                   "accepted_prop_decisions": {"1": DECISION},
                   "fixed_performances": {"2": "作者指定を保持する。"}}
        with self.assertLogs("mv_director.nodes", level="WARNING"):
            backend.complete_planner(task="scene-author-performance",
                system_prompt=prompts["scene-author-performance"] + "\n" + prompts["prop-performance-addendum"],
                payload=json.dumps(payload), config=_runtime())
        actual = json.loads(lifecycle.messages[1]["content"].removeprefix("/no_think\n"))
        self.assertEqual(actual["fixed_performances"], payload["fixed_performances"])
        self.assertNotIn("prop_inventory", actual)
        self.assertNotIn("accepted_prop_decisions", lifecycle.messages[0]["content"])
        self.assertEqual(backend.trace[0]["prop_context_fallback"], "context_budget")
        self.assertEqual(json.loads(backend.trace[0]["requested_payload"]), payload)

    def test_prop_context_budget_skips_but_cancellation_propagates(self):
        class FailingBackend:
            def __init__(self, exc):
                self.exc = exc
                self.calls = 0
            def complete_planner(self, **kwargs):
                self.calls += 1
                raise self.exc
        for exc in (ContextBudgetError("budget"), RuntimeError("interrupted")):
            for task in ("inventory", "decision"):
                with self.subTest(exc=type(exc), task=task):
                    backend = FailingBackend(exc)
                    if task == "inventory":
                        run = lambda: request_prop_inventory(backend, subject_emd=CONCEPT,
                            fixed_boundary={}, scene_number=1, system_prompt="p", runtime_config=_runtime())
                    else:
                        run = lambda: request_prop_decisions(backend, shared={"scene_number": 1,
                            "shot_positions": [{"shot": 1}], "prop_inventory": PROPS},
                            system_prompt="p", runtime_config=_runtime())
                    if isinstance(exc, ContextBudgetError):
                        with self.assertLogs("mv_director.nodes", level="WARNING"):
                            self.assertEqual(run().status, "context_budget")
                    else:
                        with self.assertRaisesRegex(RuntimeError, "interrupted"):
                            run()
                    self.assertEqual(backend.calls, 1)

    def test_progress_total_refines_after_empty_inventory(self):
        backend = _LlamaPlannerBackend(None)
        counts = {"subject-prop-inventory": 1, "scene-author-prop-decision": 3,
                  "scene-author-performance": 3, "scene-author-camera": 3}
        with patch("nodes.node_timeline_planner.node.configure_node_progress") as progress:
            backend.configure_progress(3, scene_author_counts=counts)
            backend.configure_prop_progress(0)
            self.assertEqual(progress.call_args.args, (8,))


if __name__ == "__main__":
    unittest.main()
