import base64
import json
import unittest
from types import SimpleNamespace

from core.audio import (
    AudioShape,
    SceneAudioWindow,
    align_audio_to_plan_scenes,
    pad_audio_pair,
    plan_delivered_frames,
    target_sample_counts,
)
from core.h3_contract import CONTRACT_ID
from core.namespaces import PUBLIC_NODE_TYPES
from core.utilities import (
    decode_embedded_text,
    parse_connected_candidates,
    parse_string_combo,
    text_file_fingerprint,
)
from nodes import NODE_CLASS_MAPPINGS
from nodes.node_audio_pad_pair import MVDirectorAudioPadPair
from nodes.node_h3_timing_profile import MVDirectorH3TimingProfile
from nodes.node_seed32 import MVDirectorSeed32
from nodes.node_scene_debug_splitter import MVDirectorSceneDebugSplitter


class FakeWaveform:
    def __init__(self, shape, data=None):
        self.shape = tuple(shape)
        self.data = list(data) if data is not None else [0] * self.shape[-1]
        self.copy_writes = []

    def new_zeros(self, shape):
        return FakeWaveform(shape)

    def __getitem__(self, key):
        sample_key = key[-1] if isinstance(key, tuple) else key
        values = self.data[sample_key]
        if not isinstance(values, list):
            return values
        return FakeWaveform((*self.shape[:-1], len(values)), values)

    def __setitem__(self, key, value):
        sample_key = key[-1] if isinstance(key, tuple) else key
        self.data[sample_key] = value.data
        self.copy_writes.append((key, value))


class AudioPadPairTests(unittest.TestCase):
    def test_plan_delivered_frames_subtracts_visual_context(self) -> None:
        plan = json.dumps(
            {
                "shots": [
                    {"id": "scene_0001", "length": 209, "context_length": 0},
                    {"id": "scene_0002", "length": 209, "context_length": 22},
                ]
            }
        )
        self.assertEqual(plan_delivered_frames(plan), 396)

    def test_common_duration_uses_exact_rate_conversion(self) -> None:
        targets = target_sample_counts(
            AudioShape(48000, 48000),
            AudioShape(44100, 22050),
            plan_duration_ms=1101,
            extra_padding_ms=1,
        )
        self.assertEqual(targets, (52896, 48599))

    def test_pair_pads_only_short_inputs_and_preserves_metadata(self) -> None:
        wave_a = FakeWaveform((1, 2, 48000))
        wave_b = FakeWaveform((1, 1, 22050))
        audio_a = {"waveform": wave_a, "sample_rate": 48000, "tag": "mix"}
        audio_b = {"waveform": wave_b, "sample_rate": 44100, "tag": "vocal"}
        padded_a, padded_b, targets = pad_audio_pair(audio_a, audio_b)
        self.assertEqual(targets, (48000, 44100))
        self.assertIs(padded_a["waveform"], wave_a)
        self.assertEqual(padded_b["waveform"].shape, (1, 1, 44100))
        self.assertEqual(padded_a["tag"], "mix")
        self.assertEqual(padded_b["tag"], "vocal")

    def test_frame_target_never_truncates_longer_audio(self) -> None:
        targets = target_sample_counts(
            AudioShape(1000, 2000),
            AudioShape(1000, 1000),
            target_h3_frames=24,
            fps=24,
        )
        self.assertEqual(targets, (2000, 2000))

    def test_node_uses_exact_timeline_frames_instead_of_rounded_milliseconds(self) -> None:
        class TimelineStub:
            plan_duration_ms = 29_958
            scenes = (
                SimpleNamespace(delivered_frames=226),
                SimpleNamespace(delivered_frames=243),
                SimpleNamespace(delivered_frames=211),
                SimpleNamespace(delivered_frames=39),
            )

            def validate(self) -> None:
                return None

        audio_a = {
            "waveform": FakeWaveform((1, 2, 1_436_000)),
            "sample_rate": 48_000,
        }
        audio_b = {
            "waveform": FakeWaveform((1, 1, 1_436_000)),
            "sample_rate": 48_000,
        }
        padded_a, padded_b, status, _reference = MVDirectorAudioPadPair().pad_pair(
            audio_a,
            audio_b,
            extra_padding_ms=0,
            target_h3_frames=0,
            pad_position="end",
            reference_alignment="off",
            timeline=TimelineStub(),
        )
        self.assertEqual(padded_a["waveform"].shape[-1], 1_438_000)
        self.assertEqual(padded_b["waveform"].shape[-1], 1_438_000)
        self.assertIn("timeline_frames=719", status)
        self.assertIn("target_frames=719", status)

    def test_node_uses_compiled_plan_when_planner_retimes_scene_modes(self) -> None:
        class TimelineStub:
            plan_duration_ms = 192_167
            scenes = (SimpleNamespace(delivered_frames=4_612),)

            def validate(self) -> None:
                return None

        audio_a = {
            "waveform": FakeWaveform((1, 2, 192_167)),
            "sample_rate": 1_000,
        }
        audio_b = {
            "waveform": FakeWaveform((1, 1, 192_167)),
            "sample_rate": 1_000,
        }
        plan_json = json.dumps(
            {
                "shots": [
                    {"length": 4_400, "context_length": 0},
                    {"length": 243, "context_length": 22},
                ]
            }
        )
        padded_a, padded_b, status, _reference = MVDirectorAudioPadPair().pad_pair(
            audio_a,
            audio_b,
            extra_padding_ms=0,
            target_h3_frames=0,
            pad_position="end",
            reference_alignment="off",
            timeline=TimelineStub(),
            plan_json=plan_json,
        )
        self.assertEqual(padded_a["waveform"].shape[-1], 192_542)
        self.assertEqual(padded_b["waveform"].shape[-1], 192_542)
        self.assertIn("timeline_frames=4612", status)
        self.assertIn("plan_frames=4621", status)
        self.assertIn("target_frames=4621", status)

    def test_reference_alignment_places_source_scenes_on_plan_frames(self) -> None:
        waveform = FakeWaveform((1, 1, 800), range(1, 801))
        aligned, gaps = align_audio_to_plan_scenes(
            {"waveform": waveform, "sample_rate": 1000, "tag": "vocal"},
            (
                SceneAudioWindow(0, 400, 5),
                SceneAudioWindow(400, 800, 5),
            ),
            target_samples=1000,
            fps=10,
        )
        values = aligned["waveform"].data
        self.assertEqual(gaps, (100, 100))
        self.assertEqual(values[:400], list(range(1, 401)))
        self.assertEqual(values[400:500], [0] * 100)
        self.assertEqual(values[500:900], list(range(401, 801)))
        self.assertEqual(values[900:], [0] * 100)
        self.assertEqual(aligned["tag"], "vocal")

    def test_reference_alignment_refuses_to_truncate_a_source_scene(self) -> None:
        waveform = FakeWaveform((1, 1, 600), range(600))
        with self.assertRaisesRegex(ValueError, "not truncated"):
            align_audio_to_plan_scenes(
                {"waveform": waveform, "sample_rate": 1000},
                (SceneAudioWindow(0, 600, 5),),
                target_samples=600,
                fps=10,
            )

    def test_reference_output_is_appended_without_moving_existing_outputs(self) -> None:
        self.assertEqual(
            MVDirectorAudioPadPair.RETURN_NAMES,
            ("padded_audio_a", "padded_audio_b", "status", "reference_audio_b"),
        )
        alignment = MVDirectorAudioPadPair.INPUT_TYPES()["required"][
            "reference_alignment"
        ][0]
        self.assertEqual(alignment, ["off", "source_scenes_to_plan"])
        self.assertTrue(
            MVDirectorAudioPadPair.INPUT_TYPES()["optional"]["plan_json"][1][
                "forceInput"
            ]
        )


class SceneDebugSplitterTests(unittest.TestCase):
    @staticmethod
    def _plan() -> str:
        return json.dumps(
            {
                "defaults": {"steps": 8},
                "prompt_prefix": ["keep"],
                "shots": [
                    {"id": "scene_0001", "length": 10, "context_length": 0},
                    {"id": "scene_0002", "length": 12, "context_length": 2},
                    {"id": "scene_0003", "length": 15, "context_length": 3},
                    {"id": "scene_0004", "length": 8, "context_length": 0},
                ],
            },
            ensure_ascii=False,
        )

    def test_public_surface_uses_one_based_scene_widgets(self) -> None:
        self.assertEqual(
            MVDirectorSceneDebugSplitter.RETURN_NAMES,
            ("plan_json", "vocal_audio", "full_mix_audio"),
        )
        inputs = MVDirectorSceneDebugSplitter.INPUT_TYPES()["required"]
        self.assertTrue(inputs["plan_json"][1]["forceInput"])
        self.assertTrue(inputs["enable"][1]["default"])
        self.assertEqual(inputs["scene_start"][1]["default"], 1)
        self.assertEqual(inputs["scene_start"][1]["min"], 1)
        self.assertEqual(inputs["scene_length"][1]["default"], 1)

    def test_disabled_node_returns_all_three_inputs_by_identity(self) -> None:
        vocal = {"waveform": object(), "sample_rate": 1}
        mix = {"waveform": object(), "sample_rate": 1}

        output = MVDirectorSceneDebugSplitter().split_scenes(
            "not JSON",
            vocal,
            mix,
            False,
            999,
            999,
        )

        self.assertEqual(output["result"][0], "not JSON")
        self.assertIs(output["result"][1], vocal)
        self.assertIs(output["result"][2], mix)
        self.assertEqual(output["ui"]["status"], ["enabled=no; passthrough=yes"])

    def test_selected_scenes_use_prior_delivered_frames_as_pcm_skip(self) -> None:
        vocal_wave = FakeWaveform((1, 1, 2800), range(2800))
        mix_wave = FakeWaveform((1, 2, 4000), range(4000))
        output = MVDirectorSceneDebugSplitter().split_scenes(
            self._plan(),
            {"waveform": vocal_wave, "sample_rate": 2400, "tag": "vocal"},
            {"waveform": mix_wave, "sample_rate": 2400, "tag": "mix"},
            True,
            2,
            2,
        )

        sliced_plan, vocal, mix = output["result"]
        parsed = json.loads(sliced_plan)
        self.assertEqual(
            [shot["id"] for shot in parsed["shots"]],
            ["scene_0002", "scene_0003"],
        )
        self.assertEqual(parsed["defaults"], {"steps": 8})
        self.assertEqual(parsed["prompt_prefix"], ["keep"])
        # Scene 1 delivers 10 frames, so 1000 samples are skipped at 24 fps.
        # Scenes 2 and 3 deliver (12-2)+(15-3)=22 frames = 2200 samples.
        self.assertEqual(vocal["waveform"].shape[-1], 2200)
        self.assertEqual(vocal["waveform"].data[:1800], list(range(1000, 2800)))
        self.assertEqual(vocal["waveform"].data[1800:], [0] * 400)
        self.assertEqual(mix["waveform"].shape[-1], 2200)
        self.assertEqual(mix["waveform"].data, list(range(1000, 3200)))
        self.assertEqual(vocal["tag"], "vocal")
        self.assertEqual(mix["tag"], "mix")
        status = output["ui"]["status"][0]
        self.assertIn("scenes=2..3", status)
        self.assertIn("skip_frames=10", status)
        self.assertIn("output_frames=22", status)
        self.assertIn("vocal_end_padding_samples=400", status)

    def test_scene_range_must_fit_the_plan(self) -> None:
        audio = {
            "waveform": FakeWaveform((1, 1, 1000)),
            "sample_rate": 2400,
        }
        with self.assertRaisesRegex(ValueError, "scene_start 5 exceeds"):
            MVDirectorSceneDebugSplitter().split_scenes(
                self._plan(), audio, audio, True, 5, 1
            )
        with self.assertRaisesRegex(ValueError, "scene range 4..5 exceeds"):
            MVDirectorSceneDebugSplitter().split_scenes(
                self._plan(), audio, audio, True, 4, 2
            )

    def test_invalid_delivered_frame_count_is_rejected(self) -> None:
        plan = json.dumps(
            {"shots": [{"length": 22, "context_length": 22}]}
        )
        audio = {
            "waveform": FakeWaveform((1, 1, 1000)),
            "sample_rate": 2400,
        }
        with self.assertRaisesRegex(ValueError, "deliver at least one frame"):
            MVDirectorSceneDebugSplitter().split_scenes(
                plan, audio, audio, True, 1, 1
            )


class UtilityProtocolTests(unittest.TestCase):
    def test_string_combo_pipe_escape(self) -> None:
        self.assertEqual(parse_string_combo("alpha|beta||gamma|delta"), ("alpha", "beta|gamma", "delta"))
        with self.assertRaisesRegex(ValueError, "unique"):
            parse_string_combo("same|same")

    def test_connected_combo_requires_json_string_array(self) -> None:
        self.assertEqual(parse_connected_candidates('["one","two"]'), ("one", "two"))
        with self.assertRaisesRegex(ValueError, "array of strings"):
            parse_connected_candidates('{"one":1}')

    def test_text_file_is_strict_utf8_and_normalizes_newlines(self) -> None:
        raw = "\ufeff[VERSE1]\r\nline one\rline two\n".encode("utf-8")
        encoded = base64.b64encode(raw).decode("ascii")
        metadata = json.dumps({"size": len(raw), "type": "text/plain"})
        text = decode_embedded_text(encoded, "lyrics.txt", metadata)
        self.assertEqual(text, "[VERSE1]\nline one\nline two\n")
        first = text_file_fingerprint(encoded, "lyrics.txt", metadata)
        second = text_file_fingerprint(encoded, "other.txt", metadata)
        self.assertNotEqual(first, second)

    def test_text_file_rejects_path_nul_and_non_txt(self) -> None:
        encoded = base64.b64encode(b"a\x00b").decode("ascii")
        with self.assertRaisesRegex(ValueError, "NUL"):
            decode_embedded_text(encoded, "lyrics.txt", "{}")
        clean = base64.b64encode(b"plain").decode("ascii")
        with self.assertRaisesRegex(ValueError, r"\.txt"):
            decode_embedded_text(clean, "lyrics.md", "{}")
        with self.assertRaisesRegex(ValueError, "path"):
            decode_embedded_text(clean, "folder/lyrics.txt", "{}")


class PublicNodeTests(unittest.TestCase):
    def test_all_and_only_public_node_ids_are_registered(self) -> None:
        self.assertEqual(set(NODE_CLASS_MAPPINGS), set(PUBLIC_NODE_TYPES))
        self.assertNotIn("MVDirectorAudioPad", NODE_CLASS_MAPPINGS)
        self.assertFalse(any(name.startswith(("CL", "MiniMaxH3")) for name in NODE_CLASS_MAPPINGS))

    def test_timing_profile_node_returns_pinned_object_and_json(self) -> None:
        profile, profile_json, status = MVDirectorH3TimingProfile().build_profile(CONTRACT_ID)
        self.assertEqual(profile.contract, CONTRACT_ID)
        self.assertEqual(json.loads(profile_json)["fps"], 24)
        self.assertIn("fps=24", status)

    def test_seed32_modes_stay_in_shared_range(self) -> None:
        node = MVDirectorSeed32()
        self.assertFalse(
            node.INPUT_TYPES()["required"]["seed"][1]["control_after_generate"]
        )
        self.assertEqual(node.make_seed("fixed", 123), (123,))
        generated = node.make_seed("random", -1)[0]
        self.assertGreaterEqual(generated, 1)
        self.assertLessEqual(generated, 2147483647)
        self.assertTrue(MVDirectorSeed32.IS_CHANGED("random", 1) != MVDirectorSeed32.IS_CHANGED("random", 1))


if __name__ == "__main__":
    unittest.main()
