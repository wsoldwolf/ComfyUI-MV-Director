"""Development choreography profile must not silently change production planning."""

import tempfile
import json
from pathlib import Path
import unittest

from core.direction.profile_loader import (
    DirectionProfileError,
    load_direction_profile,
    load_direction_profiles,
)
from tools.offline_choreography_profile_probe import (
    choose_phrase_input,
    parse_phrase_id,
)
from core.artifacts import DirectionArtifact
from core.planner import build_choreography_choice_grammar, plan_timeline
from core.planner.choreography import accept_choreography_choice
from test_timeline_planner import CONCEPT, TEMPLATE, FakePlannerBackend, prompts, runtime


ROOT = Path(__file__).resolve().parents[1]
PROFILE = ROOT / "profiles/motion/anime_choreography_mv.md"


class ChoreographyProfileProbeTests(unittest.TestCase):
    def test_motion_profile_no_longer_injects_a_choreography_palette(self):
        profile = load_direction_profile(PROFILE, "motion")
        self.assertEqual(profile.performance_mode, "dance_phrase")
        self.assertEqual(profile.choreography_policy, "off")
        self.assertEqual(profile.choreography_phrases, ())
        self.assertIn(profile.profile_id, load_direction_profiles().motion)

    def test_phrase_section_is_strict_and_motion_only(self):
        body = ("# プロファイル\n* `performance_mode` dance_phrase\n"
                "* `choreography_policy` scene_choice\n\n# 共通プロンプト\n"
                "## モーション\n* 演技。\n\n# 振付候補\n")
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "custom.md"
            for suffix, error in (
                ("* `one` 一つだけ。\n", "at least two"),
                ("* `one` 甲。\n* `one` 乙。\n", "duplicate"),
                ("* one 甲。\n* `two` 乙。\n", "invalid choreography"),
            ):
                path.write_text(body + suffix, encoding="utf-8")
                with self.assertRaisesRegex(DirectionProfileError, error):
                    load_direction_profile(path, "motion")
            path.write_text(body.replace("dance_phrase", "event_based") +
                            "* `one` 甲。\n* `two` 乙。\n", encoding="utf-8")
            with self.assertRaisesRegex(DirectionProfileError, "requires dance_phrase"):
                load_direction_profile(path, "motion")

            path.write_text(body.replace("scene_choice", "scene_palette") +
                            "* `one` 甲。\n* `two` 乙。\n", encoding="utf-8")
            with self.assertRaisesRegex(DirectionProfileError, "must be off or scene_choice"):
                load_direction_profile(path, "motion")

    def test_selector_restricts_to_declared_ids_and_does_not_repeat_previous(self):
        phrases = (("one", "一つ目"), ("two", "二つ目"))
        scene = {"scene_number": 1, "lyrics": ["歌詞"], "cue": "感情",
                 "continuation": True, "shots": [{"start": "0", "end": "1"}]}
        request = choose_phrase_input(scene, ["全身"], phrases, "終端", "one")
        self.assertEqual([entry["id"] for entry in request["candidates"]], ["two"])
        self.assertEqual(parse_phrase_id("<think>\n\n</think>\n\ntwo", phrases), "two")
        with self.assertRaisesRegex(ValueError, "candidate ID"):
            parse_phrase_id("two because it fits", phrases)

    def test_finite_choice_grammar(self):
        grammar = build_choreography_choice_grammar(("quiet_refrain", "joy_rebound"))
        self.assertIn('"CHOICE\\t1\\t"', grammar)
        self.assertIn('"quiet_refrain"', grammar)
        self.assertIn('"joy_rebound"', grammar)
        self.assertIn('"FREEFORM"', grammar)
        self.assertEqual(accept_choreography_choice("FREEFORM", ("quiet_refrain",)),
                         "FREEFORM")
        with self.assertRaises(ValueError):
            build_choreography_choice_grammar(("same", "same"))

    def test_profile_does_not_inject_a_palette_into_actions(self):
        class Backend(FakePlannerBackend):
            def complete_planner(self, *, task, system_prompt, payload, config, interrupt_callback=None):
                if task == "choreography-choice":
                    value = json.loads(payload)
                    self.calls.append((task, value))
                    return "CHOICE\t1\tquiet_refrain"
                if task == "scene-spine":
                    value = json.loads(payload)
                    self.calls.append((task, value))
                    return "\n".join(
                        f"SPINE\t{item['slot']}\t" + (
                            "PHASE=event｜FROM=立つ｜ADVANCE=鳥居へ向けて腕を伸ばす"
                            "｜TO=腕を伸ばす｜SHOW=lyric_target" if index == 0 else
                            "PHASE=response｜FROM=腕を伸ばす｜ADVANCE=表情を緩める"
                            "｜TO=正面を見る｜SHOW=face_eyes_mouth"
                        ) for index, item in enumerate(value["slots"])
                    )
                return super().complete_planner(
                    task=task, system_prompt=system_prompt, payload=payload,
                    config=config, interrupt_callback=interrupt_callback,
                )

        backend = Backend()
        result = plan_timeline(
            backend, template_emd=TEMPLATE, concept_emd=CONCEPT,
            direction=DirectionArtifact(
                motion_profile_id="anime_choreography_mv",
                camera_profile_id="anime_emotional_mv",
            ),
            lip_sync_mode="off", lip_sync_target="サブジェクト1",
            lip_sync_audio_slot=1, scenes_per_batch=1,
            system_prompts={**prompts(), "scene-spine": "spine",
                            "choreography-choice": "choice"},
            runtime_config=runtime(),
        )
        self.assertTrue(result.complete)
        self.assertNotIn("choreography-choice", [task for task, _ in backend.calls])
        action = next(value for task, value in backend.calls if task == "actions")
        self.assertNotIn("choreography_palette", action)
        self.assertNotIn("selected_choreography_phrase", action["slots"][0])
        spine = next(value for task, value in backend.calls if task == "scene-spine")
        self.assertEqual(spine["scene_start_ms"], 0)
        self.assertEqual(spine["slots"][0]["shot_start_ms"], 0)
        self.assertEqual(spine["slots"][0]["lyrics"][0]["start_ms"], 2300)
        self.assertEqual(action["slots"][0]["lyrics"][0]["end_ms"], 5800)


if __name__ == "__main__":
    unittest.main()
