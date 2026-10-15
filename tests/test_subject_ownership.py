"""Multi-Subject transport, supplements and ownership; CPU-only fake inference."""
from copy import deepcopy
import json
from pathlib import Path
import unittest

from core.artifacts import DirectionArtifact, canonical_json
from core.compiler.ref2va import compile_ref2va
from core.compiler.translator import IdentityTranslator
from core.planner import PlannerContent, plan_timeline
from core.planner.prop_decision import (
    ACTOR_FIELDS, parse_prop_decisions, request_prop_decisions,
)
from core.planner.prop_inventory import parse_prop_inventory, request_prop_inventory
from core.planner.scene_author import _split_terminal_state
from core.planner.subject_ownership import (
    bind_motion_composition, performer_states, split_performer_metadata,
    subject_ids_from_emd,
)
from nodes.node_timeline_planner.node import _system_prompts
from scene_author_fixtures import Backend, _runtime


SUBJECTS = "# サブジェクト\n* `画像1` 杖を持つ歌手。\n* `画像3` 杖を持つ踊り手。\n* 大樹。\n* 舞台。\n"
IDS = tuple(f"サブジェクト{i}" for i in range(1, 5))
TEMPLATE = (
    "> `シーン` 1\n# シーン 00:00.000 --> 00:08.000\n* `H3長` 192\n"
    "## ショット 00:00.000\n* 未計画\n"
    "## ショット 00:04.000\n* 未計画\n"
)
PROPS = [
    {"id": f"P{i}", "subject": f"サブジェクト{i}", "label": "杖",
     "evidence": "杖を持つ", "initial_state": "右手"}
    for i in (1, 2)
]
DECISION = {
    "prop_locations": {"P1": "サブジェクト1の右手", "P2": "サブジェクト2の右手"},
    "end_state": {"P1": "サブジェクト1の右手", "P2": "サブジェクト2の右手"},
    **{field: {identifier: "自身の杖を保持する" for identifier in IDS[:2]}
       for field in ACTOR_FIELDS},
}


def metadata(prose="身体を斜めへ向ける。", performer="サブジェクト2", states=None):
    suffix = "" if states is None else "｜END_STATE=" + canonical_json(states)
    return f"{prose}｜PERFORMER={performer}{suffix}"


class MultiBackend(Backend):
    def __init__(self, performance=None, inventory=None):
        super().__init__()
        self.performance = performance or (
            lambda request, slot: metadata(states={"サブジェクト2": "斜め向き。"}))
        self.inventory = inventory or []

    def complete_planner(self, *, task, payload, **kwargs):
        request = json.loads(payload)
        if task == "subject-prop-inventory":
            self.calls.append((task, request))
            return "PROP_INVENTORY\t1\t" + canonical_json({"props": self.inventory})
        if task in {"scene-author-performance", "scene-author-prop-decision"}:
            self.calls.append((task, request))
            record = "PERFORMANCE" if task == "scene-author-performance" else "PROP_DECISION"
            return "\n".join(
                f"{record}\t{slot['slot']}\t" + (
                    self.performance(request, slot) if record == "PERFORMANCE"
                    else canonical_json(DECISION)) for slot in request["slots"])
        return super().complete_planner(task=task, payload=payload, **kwargs)


def plan(backend, *, template=TEMPLATE, direction=None, props=False):
    return plan_timeline(
        backend, template_emd=template, concept_emd=SUBJECTS,
        direction=direction or DirectionArtifact(), lip_sync_mode="context_loop",
        lip_sync_target="サブジェクト1", lip_sync_audio_slot=1,
        system_prompts=_system_prompts(prop_holding=props), runtime_config=_runtime())


class SubjectOwnershipParserTests(unittest.TestCase):
    def test_structural_ids_include_places_without_assigning_them_hands(self):
        self.assertEqual(subject_ids_from_emd(SUBJECTS), IDS)

    def test_metadata_is_removed_without_rewriting_prose(self):
        value = metadata(states={"サブジェクト2": "斜め向き。"})
        prose, state = _split_terminal_state(value, max_state_length=1200)
        result = split_performer_metadata(prose, state, IDS)
        self.assertEqual(result, ("身体を斜めへ向ける。", "サブジェクト2",
                                  canonical_json({"サブジェクト2": "斜め向き。"})))

    def test_oversized_state_is_discarded_but_suffix_does_not_leak(self):
        value = metadata(states={"サブジェクト2": "姿" * 1400})
        self.assertEqual(split_performer_metadata(*_split_terminal_state(value), IDS),
                         ("身体を斜めへ向ける。", "サブジェクト2", ""))

    def test_missing_or_invalid_focus_never_defaults_to_subject_one(self):
        for prose in ("身体を動かす。", metadata(performer="サブジェクト9"),
                      "`サブジェクト1`と`サブジェクト2`が向き合う。"):
            with self.subTest(prose=prose):
                result = split_performer_metadata(prose, "", IDS)
                self.assertEqual(result[1], "")
                self.assertNotIn("PERFORMER=", result[0])

    def test_unique_explicit_identity_is_an_advisory_fallback(self):
        self.assertEqual(split_performer_metadata(
            "`サブジェクト2`が動く。", "", IDS)[1], "サブジェクト2")

    def test_invalid_state_maps_are_not_interpreted_as_pose_prose(self):
        for state in ('{"サブジェクト9":"立つ"}', '{"サブジェクト2":""}',
                      '{"サブジェクト2":"立つ","サブジェクト2":"座る"}',
                      '{"サブジェクト2":3}', '"立つ"',
                      '{"サブジェクト2":"立つ\\n座る"}'):
            with self.subTest(state=state):
                self.assertEqual(performer_states(state, IDS), {})

    def test_anonymous_composition_is_scoped_to_selected_actor_only(self):
        row = (1, 1, "user", 1, "踏み替える。")
        self.assertEqual(bind_motion_composition(row, IDS[1], IDS)[4],
                         "`サブジェクト2` 踏み替える。")
        self.assertIsNone(bind_motion_composition(row, "", IDS))

    def test_explicit_author_target_and_duet_keep_priority(self):
        for text in ("`サブジェクト1`が動く。",
                     "`サブジェクト1`と`サブジェクト2`が踊る。"):
            row = (1, 1, "user", 1, text)
            self.assertEqual(bind_motion_composition(row, IDS[1], IDS), row)
        self.assertIsNone(bind_motion_composition(
            (1, 1, "user", 1, "`サブジェクト4`が動く。"), IDS[1], IDS[:2]))
        self.assertIsNone(bind_motion_composition(
            (1, 1, "user", 1, "`サブジェクト5`が動く。"), IDS[1], IDS))

    def test_out_of_range_actor_tokens_do_not_become_a_focus_fallback(self):
        for identifier in ("サブジェクト0", "サブジェクト5", "サブジェクト01"):
            self.assertEqual(split_performer_metadata(f"`{identifier}`が動く。", "", IDS)[1], "")


class MultiSubjectPropsTests(unittest.TestCase):
    def test_same_label_different_owners_are_preserved(self):
        value = "PROP_INVENTORY\t1\t" + canonical_json({"props": PROPS})
        self.assertEqual(parse_prop_inventory(value, subject_ids=IDS), tuple(PROPS))
        self.assertIsNone(parse_prop_inventory(value, subject_ids=IDS[1:]))

    def test_invalid_inventory_owner_retries_twice_then_falls_back(self):
        backend = MultiBackend(inventory=[{**PROPS[0], "subject": "人物1"}])
        result = request_prop_inventory(
            backend, subject_emd=SUBJECTS, fixed_boundary={}, scene_number=1,
            system_prompt="fixed", runtime_config=_runtime(), subject_ids=IDS)
        self.assertEqual((result.attempts, result.status, result.props),
                         (2, "invalid_transport", ()))
        self.assertTrue(all(p["subject_ids"] == list(IDS) for _, p in backend.calls))

    def test_hands_are_per_owner_not_global_and_no_hands_for_places(self):
        value = "PROP_DECISION\t1\t" + canonical_json(DECISION)
        result = parse_prop_decisions(value, (2,), prop_ids=frozenset({"P1", "P2"}),
                                      owner_ids=frozenset(IDS[:2]))
        self.assertEqual(result, {2: DECISION})
        self.assertEqual(set(result[2]["right_hand"]), set(IDS[:2]))

    def test_missing_extra_or_unscoped_owner_and_partial_prop_map_are_invalid(self):
        bad_entries = [{IDS[0]: "保持"}, {**DECISION["right_hand"], IDS[2]: "保持"}, "保持"]
        for entry in bad_entries:
            bad = {**DECISION, "right_hand": entry}
            with self.subTest(entry=entry):
                self.assertIsNone(parse_prop_decisions(
                    "PROP_DECISION\t1\t" + canonical_json(bad), (1,),
                    prop_ids=frozenset({"P1", "P2"}), owner_ids=frozenset(IDS[:2])))
        bad = {**DECISION, "end_state": {"P1": "右手"}}
        self.assertIsNone(parse_prop_decisions(
            "PROP_DECISION\t1\t" + canonical_json(bad), (1,),
            prop_ids=frozenset({"P1", "P2"}), owner_ids=frozenset(IDS[:2])))

    def test_request_does_not_mutate_input_and_preserves_prop_id_coverage(self):
        shared = {"scene_number": 1, "shot_positions": [{"shot": 1}],
                  "subject_ids": list(IDS), "prop_inventory": PROPS}
        original = deepcopy(shared)
        backend = MultiBackend()
        result = request_prop_decisions(backend, shared=shared, system_prompt="fixed",
                                       runtime_config=_runtime())
        self.assertEqual(shared, original)
        self.assertEqual(result.status, "transport_valid")
        self.assertEqual(backend.calls[0][1]["hand_owner_ids"], list(IDS[:2]))


class MultiSubjectPipelineTests(unittest.TestCase):
    def test_default_profiles_do_not_require_only_one_person(self):
        from core.direction.profile_loader import load_direction_profiles
        catalog = load_direction_profiles(Path(__file__).resolve().parents[1] / "profiles")
        self.assertNotIn("一人の人物", catalog.style["anime_emotional_mv"])
        self.assertNotIn("一人の歌唱者", catalog.camera["anime_emotional_mv"])

    def test_object_subjects_have_no_human_anatomy_requirement(self):
        compiled = compile_ref2va(SUBJECTS + TEMPLATE.replace(
            "* 未計画", "* 静かに待つ。"), IdentityTranslator()).plan
        text = json.dumps(compiled, ensure_ascii=False)
        self.assertIn("<Subject 3> is described here: 大樹。", text)
        self.assertIn("<Subject 4> is described here: 舞台。", text)
        self.assertNotIn("with one head and one body", text)
        self.assertIn("preserving its described anatomy or structure", text)

    def test_prompts_distinguish_subject_references_from_prop_metadata(self):
        prompts = _system_prompts(prop_holding=True)
        for task in ("event", "performance", "camera"):
            self.assertIn("ASCIIバッククォート", prompts[f"scene-author-{task}"])
        self.assertIn("PERFORMER", prompts["prop-performance-addendum"])
        self.assertIn("携行物の内部ID（P1等）", prompts["prop-performance-addendum"])

    def test_performer_metadata_reaches_camera_not_emd_or_compiler(self):
        backend = MultiBackend()
        result = plan(backend)
        self.assertTrue(result.complete)
        self.assertEqual([t for t, _ in backend.calls], [
            "scene-author-event", "scene-author-performance", "scene-author-camera"])
        self.assertEqual(result.content.performance_subjects,
                         ((1, 1, IDS[1]), (1, 2, IDS[1])))
        camera = backend.calls[-1][1]
        self.assertEqual(camera["performance_subjects"], {"1": IDS[1], "2": IDS[1]})
        self.assertEqual(camera["subject_ids"], list(IDS))
        self.assertIn("`サブジェクト2` 身体を斜めへ向ける。", result.emd.text)
        self.assertIn("`Context Loop` `サブジェクト1`", result.emd.text)
        compiled = json.dumps(compile_ref2va(result.emd.text, IdentityTranslator()).plan,
                              ensure_ascii=False)
        self.assertIn("<Subject 2>", compiled)
        for label in ("PERFORMER=", "END_STATE=", "performance_subjects"):
            self.assertNotIn(label, result.emd.text)
            self.assertNotIn(label, compiled)
        self.assertEqual(PlannerContent.from_dict(json.loads(
            canonical_json(result.content.to_dict()))), result.content)
        old_cache = result.content.to_dict()
        old_cache.pop("performance_subjects")
        self.assertEqual(PlannerContent.from_dict(old_cache).performance_subjects, ())

    def test_generated_actor_prefix_is_kept_when_target_object_is_explicit(self):
        backend = MultiBackend(performance=lambda r, s: metadata(
            "`サブジェクト3`の幹に手を添える。"))
        result = plan(backend)
        self.assertEqual(result.content.actions[0][2],
                         "`サブジェクト2` `サブジェクト3`の幹に手を添える。")

    def test_pre_author_generic_supplement_is_scoped_before_camera(self):
        backend = MultiBackend()
        result = plan(backend, direction=DirectionArtifact(motion_templates=("踏み替える。",)))
        addition = result.content.motion_compositions[0][4]
        self.assertEqual(addition, "`サブジェクト2` 踏み替える。")
        camera = backend.calls[-1][1]
        self.assertEqual(camera["scheduled_motion_composition"]["target_subject"], IDS[1])
        self.assertTrue(camera["accepted_performances"]["1"].endswith(addition))
        self.assertEqual(result.emd.text.count(addition), 1)

    def test_missing_focus_skips_only_supplement_and_removes_camera_schedule(self):
        backend = MultiBackend(performance=lambda r, s: "身体を動かす。")
        with self.assertLogs("mv_director.nodes", level="WARNING") as logs:
            result = plan(backend, direction=DirectionArtifact(motion_templates=("踏み替える。",)))
        self.assertTrue(result.complete)
        self.assertEqual(result.content.motion_compositions, ())
        self.assertNotIn("scheduled_motion_composition", backend.calls[-1][1])
        self.assertIn("身体を動かす。", result.emd.text)
        self.assertTrue(any("ambiguous_or_undefined_subject" in line for line in logs.output))

    def test_explicit_supplement_target_overrides_main_actor_in_camera_schedule(self):
        backend = MultiBackend()
        text = "`サブジェクト1`が一歩進む。"
        result = plan(backend, direction=DirectionArtifact(motion_templates=(text,)))
        self.assertEqual(result.content.motion_compositions[0][4], text)
        self.assertEqual(backend.calls[-1][1]["scheduled_motion_composition"]["target_subject"], IDS[0])

    def test_post_author_choice_receives_focus_without_extra_actor_inference(self):
        backend = MultiBackend()
        direction = DirectionArtifact(motion_profile_id="anime_scene_composed_mv",
                                      motion_templates=("踏み替える。", "胸を開く。"))
        result = plan(backend, direction=direction)
        self.assertEqual([t for t, _ in backend.calls], [
            "scene-author-event", "scene-author-performance", "scene-author-camera",
            "scene-author-composition-choice"])
        self.assertEqual(backend.calls[-1][1]["performance_subjects"]["1"], IDS[1])
        self.assertNotIn("scheduled_motion_composition", backend.calls[-2][1])
        self.assertEqual(result.content.motion_compositions[0][4], "`サブジェクト2` 踏み替える。")

    def test_post_author_missing_focus_does_not_block_generation(self):
        backend = MultiBackend(performance=lambda r, s: "身体を動かす。")
        with self.assertLogs("mv_director.nodes", level="WARNING"):
            result = plan(backend, direction=DirectionArtifact(
                motion_profile_id="anime_scene_composed_mv", motion_templates=("踏み替える。",)))
        self.assertTrue(result.complete)
        self.assertEqual(result.content.motion_compositions, ())

    def test_two_owners_share_no_global_hand_and_inventory_runs_once(self):
        backend = MultiBackend(inventory=PROPS)
        result = plan(backend, props=True)
        self.assertTrue(result.complete)
        self.assertEqual([t for t, _ in backend.calls], [
            "subject-prop-inventory", "scene-author-event", "scene-author-prop-decision",
            "scene-author-performance", "scene-author-camera"])
        for _, request in backend.calls[-2:]:
            self.assertEqual(request["accepted_prop_decisions"]["1"], DECISION)
            self.assertNotIn(IDS[2], request["accepted_prop_decisions"]["1"]["right_hand"])

    def test_invalid_owner_hands_retry_twice_without_stopping_authorship(self):
        class InvalidHandsBackend(MultiBackend):
            def complete_planner(self, *, task, payload, **kwargs):
                if task == "scene-author-prop-decision":
                    request = json.loads(payload)
                    self.calls.append((task, request))
                    return "\n".join(
                        f"PROP_DECISION\t{s['slot']}\t" + canonical_json(
                            {**DECISION, "right_hand": "人物を区別しない保持"})
                        for s in request["slots"])
                return super().complete_planner(task=task, payload=payload, **kwargs)
        backend = InvalidHandsBackend(inventory=PROPS)
        with self.assertLogs("mv_director.nodes", level="WARNING"):
            result = plan(backend, props=True)
        self.assertTrue(result.complete)
        attempts = [r for t, r in backend.calls if t == "scene-author-prop-decision"]
        self.assertEqual(len(attempts), 2)
        self.assertEqual(attempts[1]["required_owner_ids_in_actor_fields"], list(IDS[:2]))
        self.assertNotIn("accepted_prop_decisions", backend.calls[-1][1])

    def test_mouth_intent_remains_on_singer_while_other_actor_moves(self):
        template = TEMPLATE.replace("## ショット 00:00.000",
            "> `口元` `サブジェクト1` 00:00.000 --> 00:04.000 `閉口`\n"
            "> `口元` `サブジェクト1` 00:04.000 --> 00:08.000 `歌唱`\n"
            "## ショット 00:00.000")
        backend = MultiBackend()
        result = plan(backend, template=template)
        for _, request in backend.calls[-2:]:
            intervals = request["mouth_performance"]["intervals"]
            self.assertEqual([i["subject"] for i in intervals], [IDS[0], IDS[0]])
            self.assertEqual([i["state"] for i in intervals], ["閉口", "歌唱"])
        self.assertTrue(all(row[2] == IDS[1] for row in result.content.performance_subjects))
        self.assertTrue(all(row[1] == IDS[0] for row in result.content.mouth_performances))

    def test_states_follow_continuation_clear_stale_actor_and_reset_at_cut(self):
        template = TEMPLATE + (
            "> `シーン` 2\n# シーン 00:08.000 --> 00:16.000 継続\n* `H3長` 192\n"
            "## ショット 00:08.000\n* 未計画\n"
            "> `シーン` 3\n# シーン 00:16.000 --> 00:24.000 継続\n* `H3長` 192\n"
            "## ショット 00:16.000\n* 未計画\n"
            "> `シーン` 4\n# シーン 00:24.000 --> 00:32.000\n* `H3長` 192\n"
            "## ショット 00:24.000\n* 未計画\n")
        def performance(request, slot):
            if request["scene_number"] == 1:
                actor = IDS[slot["shot"] - 1]
                return metadata(performer=actor, states={actor: "立つ。"})
            return metadata(performer=IDS[1])  # new movement, no fresh state
        backend = MultiBackend(performance=performance)
        result = plan(backend, template=template)
        requests = [r for t, r in backend.calls if t == "scene-author-performance"]
        self.assertEqual(requests[1]["previous_performer_states"],
                         {IDS[0]: "立つ。", IDS[1]: "立つ。"})
        self.assertEqual(requests[2]["previous_performer_states"], {IDS[0]: "立つ。"})
        self.assertEqual(requests[3]["previous_performer_states"], {})
        self.assertEqual(json.loads(result.content.terminal_states[1][2]), {IDS[0]: "立つ。"})

    def test_fixed_author_performance_is_not_rewritten_or_supplemented(self):
        text = "`サブジェクト1`が杖を渡す。"
        template = TEMPLATE.replace("* 未計画", "* `演技` " + text, 1)
        backend = MultiBackend()
        result = plan(backend, template=template, direction=DirectionArtifact(
            motion_templates=("踏み替える。",)))
        self.assertIn("* `演技` " + text, result.emd.text)
        self.assertEqual(result.content.motion_compositions, ())
        self.assertEqual(backend.calls[-1][1]["performance_subjects"]["1"], IDS[0])
        self.assertEqual(backend.calls[1][1]["fixed_performances"]["1"], text)

    def test_fixed_boundary_invalidates_only_its_explicit_actor_state(self):
        template = TEMPLATE + (
            "> `シーン` 2\n# シーン 00:08.000 --> 00:16.000 継続\n* `H3長` 192\n"
            "## ショット 00:08.000\n* `演技` `サブジェクト1`が歩く。\n"
            "## ショット 00:12.000\n* 未計画\n")
        def performance(request, slot):
            return metadata(states={IDS[0]: "立つ。", IDS[1]: "斜め向き。"}
                            if request["scene_number"] == 1 else {IDS[1]: "横向き。"})
        result = plan(MultiBackend(performance=performance), template=template)
        self.assertEqual(json.loads(result.content.terminal_states[1][2]), {IDS[1]: "横向き。"})


if __name__ == "__main__":
    unittest.main()
