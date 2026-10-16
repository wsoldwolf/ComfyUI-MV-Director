"""Metadata-only scoping and production Scene Author regression tests."""
from copy import deepcopy
import json
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from core.artifacts import DirectionArtifact
from core.emd.audio_activity import ActivityRange, AudioActivity
from core.planner import plan_timeline
from core.planner.candidate_policy import performance_candidate_preference_enabled
from nodes.node_timeline_planner.node import _system_prompts
from scene_author_fixtures import Backend, CONCEPT, _runtime


class PreferenceScopeTests(unittest.TestCase):
    def enabled(self, intervals, *, policy="prefer_matched", candidates=("伴奏では踊る。",),
                positions=None):
        return performance_candidate_preference_enabled(policy, candidates,
            {"intervals": intervals}, positions if positions is not None else [
                {"start_ms": 0, "end_ms": 6000, "fixed_performance": ""},
            ])

    def test_known_long_rests_and_boundary(self):
        for state in ("no_vocal_candidate", "instrumental_candidate"):
            for end, expected in ((1999, False), (2000, True)):
                with self.subTest(state=state, end=end):
                    self.assertEqual(self.enabled([dict(state=state, start_ms=0, end_ms=end)]), expected)

    def test_optional_empty_candidates_and_missing_activity_unchanged(self):
        rows = [dict(state="no_vocal_candidate", start_ms=0, end_ms=6000)]
        self.assertFalse(self.enabled(rows, policy="optional"))
        for candidates in ((), (" ",)):
            self.assertFalse(self.enabled(rows, candidates=candidates))
        self.assertFalse(performance_candidate_preference_enabled("prefer_matched", ("候補",), None, []))

    def test_voice_unknown_padding_and_fullmix_silence_excluded(self):
        for state in ("vocal_candidate", "unknown", "padding", "fullmix_silence_candidate"):
            with self.subTest(state=state):
                self.assertFalse(self.enabled([dict(state=state, start_ms=0, end_ms=6000)]))

    def test_contiguous_known_rest_fragments_merge_but_gaps_do_not(self):
        rows = [dict(state="no_vocal_candidate", start_ms=0, end_ms=1100),
                dict(state="instrumental_candidate", start_ms=1100, end_ms=2200)]
        self.assertTrue(self.enabled(rows))
        rows[1].update(start_ms=1200, end_ms=2300)
        self.assertFalse(self.enabled(rows))

    def test_intervening_voice_or_padding_is_not_summed(self):
        for state in ("vocal_candidate", "unknown", "padding"):
            self.assertFalse(self.enabled([
                dict(state="no_vocal_candidate", start_ms=0, end_ms=1200),
                dict(state=state, start_ms=1200, end_ms=2000),
                dict(state="no_vocal_candidate", start_ms=2000, end_ms=3200),
            ]))

    def test_unowned_shot_overlap_only(self):
        rows = [dict(state="no_vocal_candidate", start_ms=0, end_ms=3000),
                dict(state="vocal_candidate", start_ms=3000, end_ms=6000)]
        self.assertFalse(self.enabled(rows, positions=[dict(start_ms=3000, end_ms=6000)]))
        self.assertFalse(self.enabled(rows, positions=[dict(start_ms=2000, end_ms=6000)]))
        self.assertFalse(self.enabled(rows, positions=[dict(start_ms=0, end_ms=6000, fixed_performance="作者演技")]))
        self.assertFalse(self.enabled(rows, positions=[]))

    def test_invalid_metadata_does_not_enable_or_mutate(self):
        for start, end in ((True, 6000), (0, float("nan")), (0, float("inf")),
                           ("0", 6000), (-1, 6000), (6000, 0)):
            self.assertFalse(self.enabled([dict(state="no_vocal_candidate", start_ms=start, end_ms=end)]))
        rows = [dict(state="no_vocal_candidate", start_ms=0, end_ms=6000)]
        before = deepcopy(rows)
        self.assertTrue(self.enabled(rows))
        self.assertEqual(rows, before)
        self.assertFalse(performance_candidate_preference_enabled("prefer_matched", ("候補",), {"intervals": {}}, []))


TEMPLATE = """> `シーン` 1
# シーン 00:00.000 --> 00:06.000
* `H3長` 158
## ショット 00:00.000
* `演出` 作者の場所。
* `演技` 作者の確定演技。
* `カメラ` 作者の確定Camera。
## ショット 00:03.000
* 未計画
"""


class RecordingBackend(Backend):
    def __init__(self):
        super().__init__()
        self.prompts = []

    def complete_planner(self, *, task, payload, system_prompt, **kwargs):
        self.prompts.append((task, system_prompt, json.loads(payload)))
        return super().complete_planner(task=task, payload=payload, **kwargs)


class ProductionPreferenceTests(unittest.TestCase):
    def plan(self, *, policy="prefer_matched", candidates=("伴奏では踊り続ける。",),
             state="no_vocal_candidate", split_fixed_rest=False, props=False):
        backend = RecordingBackend()
        intervals = (ActivityRange(0, 6000, state),) if not split_fixed_rest else (
            ActivityRange(0, 3000, "no_vocal_candidate"), ActivityRange(3000, 6000, "vocal_candidate"))
        activity = AudioActivity(1000, 6000, "a" * 64, intervals)
        template = "\n".join(activity.render_lines()) + "\n" + TEMPLATE
        result = plan_timeline(backend, template_emd=template, concept_emd=CONCEPT,
            direction=DirectionArtifact(motion_profile_id="natural_performance", staging_candidates=candidates),
            lip_sync_mode="context_loop", lip_sync_target="サブジェクト1", lip_sync_audio_slot=1,
            system_prompts=_system_prompts(prop_holding=props, performance_candidates=True),
            runtime_config=_runtime(), staging_candidate_policy=policy)
        self.assertTrue(result.complete)
        return backend, result

    def test_addendum_only_reaches_pending_performance_and_keeps_author_fields(self):
        backend, result = self.plan()
        prompts = _system_prompts(performance_candidates=True)
        self.assertEqual(len(backend.calls), 3)
        for task, prompt, payload in backend.prompts:
            if task == "scene-author-performance":
                self.assertEqual(prompt, prompts[task] + "\n" + prompts["performance-candidate-addendum"])
                self.assertEqual(payload["fixed_performances"], {"1": "作者の確定演技。"})
                self.assertIn("mouth_performance", payload)
            else:
                self.assertEqual(prompt, prompts[task])
        for fixed in ("作者の場所。", "作者の確定演技。", "作者の確定Camera。"):
            self.assertIn(fixed, result.emd.text)
        self.assertNotIn("伴奏では踊り続ける。", result.emd.text)

    def test_disabled_cases_keep_exact_base_performance_prompt(self):
        for options in (dict(policy="optional"), dict(candidates=()), dict(state="vocal_candidate"),
                        dict(state="unknown"), dict(state="fullmix_silence_candidate"), dict(split_fixed_rest=True)):
            with self.subTest(options=options):
                backend, _ = self.plan(**options)
                performance = [p for task, p, _ in backend.prompts if task == "scene-author-performance"]
                self.assertEqual(performance, [_system_prompts()["scene-author-performance"]])

    def test_prop_addendum_stays_last_for_existing_context_recovery(self):
        with patch("core.planner.scene_author.request_prop_inventory", return_value=SimpleNamespace(
            props=({"id": "P1", "owner": "サブジェクト1", "name": "杖"},),
            status="transport_valid", attempts=1)), patch(
                "core.planner.scene_author.request_prop_decisions", return_value=SimpleNamespace(
                    decisions={2: {"end_state": "杖を右手で保持"}}, status="transport_valid", attempts=1)):
            backend, _ = self.plan(props=True)
        prompts = _system_prompts(prop_holding=True, performance_candidates=True)
        performance = next(prompt for task, prompt, _ in backend.prompts if task == "scene-author-performance")
        self.assertEqual(performance, prompts["scene-author-performance"] + "\n"
            + prompts["performance-candidate-addendum"] + "\n" + prompts["prop-performance-addendum"])


if __name__ == "__main__":
    unittest.main()
