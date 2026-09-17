import json
from pathlib import Path
import unittest

from core.lyrics import parse_plain_lyrics
from core.utilities import decode_embedded_text


ROOT = Path(__file__).resolve().parents[1]
WORKFLOWS = ROOT / "workflows"
CONTRACT_ID = "context-loop-0.6.9@9860a063784c8c23b58e00107f2180e0df3c43d9"

FILES = {
    "context_loop": (
        "01_plan_compiler_context_loop.json",
        "02_video_context_loop.json",
    ),
    "audio_reference": (
        "03_plan_compiler_audio_reference.json",
        "04_video_audio_reference.json",
    ),
    "lyrics": (
        "05_plan_compiler_lyrics.json",
        "06_video_lyrics.json",
    ),
}


def load(name: str) -> dict:
    return json.loads((WORKFLOWS / name).read_text(encoding="utf-8"))


def nodes_by_id(workflow: dict) -> dict[int, dict]:
    return {int(node["id"]): node for node in workflow["nodes"]}


def only_type(workflow: dict, type_name: str) -> dict:
    values = [node for node in workflow["nodes"] if node["type"] == type_name]
    if len(values) != 1:
        raise AssertionError(f"expected one {type_name}; got {len(values)}")
    return values[0]


def input_link(workflow: dict, node: dict, input_name: str) -> list:
    item = next(value for value in node["inputs"] if value["name"] == input_name)
    link_id = item["link"]
    if link_id is None:
        raise AssertionError(f"{node['type']}.{input_name} is disconnected")
    return next(link for link in workflow["links"] if int(link[0]) == int(link_id))


class DistributableWorkflowTests(unittest.TestCase):
    def test_exact_six_workflows_are_present(self) -> None:
        actual = {
            path.name
            for path in WORKFLOWS.glob("*.json")
        }
        expected = {name for pair in FILES.values() for name in pair}
        self.assertEqual(actual, expected)

    def test_every_link_has_consistent_node_metadata(self) -> None:
        for pair in FILES.values():
            for name in pair:
                workflow = load(name)
                nodes = nodes_by_id(workflow)
                links = {int(link[0]): link for link in workflow["links"]}
                self.assertEqual(len(nodes), len(workflow["nodes"]), name)
                self.assertEqual(len(links), len(workflow["links"]), name)
                for link_id, link in links.items():
                    origin = nodes[int(link[1])]
                    target = nodes[int(link[3])]
                    output = origin["outputs"][int(link[2])]
                    target_input = target["inputs"][int(link[4])]
                    self.assertEqual(output["type"], link[5], (name, link_id))
                    self.assertIn(link_id, output["links"], (name, link_id))
                    self.assertEqual(target_input["link"], link_id, (name, link_id))

    def test_plan_compiler_workflows_fix_only_the_selected_mode(self) -> None:
        for mode, (name, _video) in FILES.items():
            workflow = load(name)
            self.assertEqual(
                workflow["extra"]["mv_director"],
                {
                    "kind": "plan_compiler",
                    "lip_sync_mode": mode,
                    "contract": CONTRACT_ID,
                },
            )
            planner = only_type(workflow, "MVDirectorTimelinePlanner")
            self.assertEqual(planner["widgets_values"][0], mode)
            self.assertEqual(
                only_type(workflow, "MVDirectorImageToSubjectEMD")[
                    "widgets_values"
                ][6],
                "manual",
            )
            compiler = only_type(workflow, "MVDirectorEMDCompiler")
            self.assertEqual(
                compiler["widgets_values"],
                [
                    "ja_to_en",
                    "Qwen3-4B-abliterated/Qwen3-4B-abliterated-q5_k_m.gguf",
                    "auto",
                    4,
                    4096,
                    0.0,
                    0.9,
                    1.05,
                    -1,
                    256,
                    32768,
                    True,
                    "q8_0",
                    True,
                    False,
                    1,
                    "randomize",
                    "reuse",
                ],
            )
            seed_controls = {
                "MVDirectorImageToSubjectEMD": (23, 24),
                "MVDirectorDirectionEnhancer": (17, 18),
                "MVDirectorTimelinePlanner": (16, 17),
            }
            for node_type, (seed_index, control_index) in seed_controls.items():
                values = only_type(workflow, node_type)["widgets_values"]
                self.assertEqual(values[seed_index], 1)
                self.assertEqual(values[control_index], "randomize")
            self.assertEqual(planner["widgets_values"][19], "reuse")
            lyrics = next(
                node
                for node in workflow["nodes"]
                if node["type"] == "MVDirectorLoadTextFile"
                and node.get("title") == "Plain Lyrics"
            )
            self.assertEqual(lyrics["size"], [380, 180])
            embedded_lyrics = decode_embedded_text(*lyrics["widgets_values"][:3])
            lyric_segments = parse_plain_lyrics(embedded_lyrics)
            self.assertTrue(lyric_segments)
            self.assertEqual(lyric_segments[0].section, "CHORUS")
            self.assertEqual(
                len([n for n in workflow["nodes"] if n["type"] == "SaveText"]),
                3,
            )
            plan_save = next(
                node
                for node in workflow["nodes"]
                if node["type"] == "SaveText"
                and node["widgets_values"][0].endswith("_plan")
            )
            link = input_link(workflow, plan_save, "text")
            self.assertEqual(link[1:3], [compiler["id"], 0])

    def test_video_workflows_share_plan_handoff_and_full_mix_timeline(self) -> None:
        profiles = {
            "context_loop": "Lip-sync to source audio",
            "audio_reference": "Use source soundtrack only",
            "lyrics": "Use source soundtrack only",
        }
        alignments = {
            "context_loop": "off",
            "audio_reference": "source_scenes_to_plan",
            "lyrics": "off",
        }
        for mode, (_plan, name) in FILES.items():
            workflow = load(name)
            metadata = workflow["extra"]["mv_director"]
            self.assertEqual(metadata["kind"], "video_generation")
            self.assertEqual(metadata["lip_sync_mode"], mode)
            self.assertEqual(metadata["contract"], CONTRACT_ID)

            plan_loader = next(
                node
                for node in workflow["nodes"]
                if node["type"] == "MVDirectorLoadTextFile"
                and "Compiled Plan" in node.get("title", "")
            )
            plan = only_type(workflow, "MiniMaxH3ChainPlanModern")
            self.assertEqual(
                input_link(workflow, plan, "plan_json_input")[1:3],
                [plan_loader["id"], 0],
            )

            profile = only_type(workflow, "MiniMaxH3GenerationProfile")
            self.assertEqual(profile["widgets_values"][1], profiles[mode])
            pad = only_type(workflow, "MVDirectorAudioPadPair")
            self.assertEqual(pad["widgets_values"][3], alignments[mode])
            self.assertEqual(
                input_link(workflow, pad, "plan_json")[1:3],
                [plan_loader["id"], 0],
            )
            lyric_nodes = [
                node
                for node in workflow["nodes"]
                if node["type"] == "MVDirectorLyricSegmentation"
            ]
            plain_lyrics = [
                node
                for node in workflow["nodes"]
                if node.get("title") == "Plain Lyrics"
            ]
            expected_count = 1 if mode == "audio_reference" else 0
            self.assertEqual(len(lyric_nodes), expected_count)
            self.assertEqual(len(plain_lyrics), expected_count)
            tracks = only_type(workflow, "MiniMaxH3AudioTracks")
            loop = only_type(workflow, "MiniMaxH3ChainLoopStart")
            self.assertEqual(
                input_link(workflow, loop, "source_timeline")[1:3],
                [tracks["id"], 0],
            )

    def test_context_loop_video_wires_options_voice_and_audio_vae(self) -> None:
        workflow = load(FILES["context_loop"][1])
        lip = only_type(workflow, "MiniMaxH3LipSyncOptions")
        pad = only_type(workflow, "MVDirectorAudioPadPair")
        profile = only_type(workflow, "MiniMaxH3GenerationProfile")
        context = only_type(workflow, "MiniMaxH3ChainContext")
        audio_vae = next(
            node
            for node in workflow["nodes"]
            if node["type"] == "VAELoader" and node.get("title") == "Audio VAE"
        )
        self.assertEqual(
            input_link(workflow, lip, "voice")[1:3], [pad["id"], 1]
        )
        self.assertEqual(
            input_link(workflow, profile, "lip_sync_options")[1:3],
            [lip["id"], 0],
        )
        self.assertEqual(
            input_link(workflow, context, "lip_sync_voice")[1:3],
            [lip["id"], 1],
        )
        self.assertEqual(
            input_link(workflow, context, "audio_vae")[1:3],
            [audio_vae["id"], 0],
        )

    def test_audio_reference_video_slices_aligned_vocal_into_audio_one(self) -> None:
        workflow = load(FILES["audio_reference"][1])
        pad = only_type(workflow, "MVDirectorAudioPadPair")
        current = only_type(workflow, "MiniMaxH3ChainCurrent")
        trim = only_type(workflow, "TrimAudioDuration")
        ref2va = only_type(workflow, "MiniMaxH3ReferenceToVideo")
        self.assertEqual(
            input_link(workflow, trim, "audio")[1:3], [pad["id"], 3]
        )
        self.assertEqual(
            input_link(workflow, trim, "start_index")[1:3],
            [current["id"], 10],
        )
        self.assertEqual(
            input_link(workflow, trim, "duration")[1:3],
            [current["id"], 11],
        )
        self.assertEqual(
            input_link(workflow, ref2va, "ref_audios.ref_audio_0")[1:3],
            [trim["id"], 0],
        )

    def test_lyrics_video_has_no_extra_lip_sync_or_audio_reference_path(self) -> None:
        workflow = load(FILES["lyrics"][1])
        types = {node["type"] for node in workflow["nodes"]}
        self.assertNotIn("MiniMaxH3LipSyncOptions", types)
        self.assertNotIn("TrimAudioDuration", types)
        ref2va = only_type(workflow, "MiniMaxH3ReferenceToVideo")
        audio_input = next(
            value
            for value in ref2va["inputs"]
            if value["name"] == "ref_audios.ref_audio_0"
        )
        self.assertIsNone(audio_input["link"])


if __name__ == "__main__":
    unittest.main()
