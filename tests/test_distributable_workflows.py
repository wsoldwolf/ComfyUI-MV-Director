import json
from pathlib import Path
import unittest

from core.lyrics import parse_plain_lyrics
from core.utilities import decode_embedded_text


ROOT = Path(__file__).resolve().parents[1]
WORKFLOWS = ROOT / "workflows"
DEVELOPMENT_WORKFLOWS = WORKFLOWS / "development"
CONTRACT_ID = "context-loop-0.6.9@9860a063784c8c23b58e00107f2180e0df3c43d9"
H3_DIFFUSION_MODEL = (
    "MiniMaxH3\\minimax_h3_ref2va_pruned_int8_convrot.safetensors"
)
H3_TEXT_ENCODER = (
    "MiniMaxH3\\qwen3vl_32b_minimax_h3_nvfp4_awq.safetensors"
)

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


def titled_node(workflow: dict, title: str) -> dict:
    values = [node for node in workflow["nodes"] if node.get("title") == title]
    if len(values) != 1:
        raise AssertionError(f"expected one node titled {title}; got {len(values)}")
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
            character_vision = titled_node(
                workflow, "Character Vision / Subject EMD"
            )
            background_vision = titled_node(
                workflow, "Background Vision (Scene Only)"
            )
            self.assertEqual(character_vision["widgets_values"][1], "subject_only")
            self.assertEqual(character_vision["widgets_values"][6], "manual")
            self.assertEqual(background_vision["widgets_values"][1], "scene_only")
            self.assertEqual(background_vision["widgets_values"][4], "lock_identity")
            self.assertEqual(background_vision["widgets_values"][6], "none")
            self.assertEqual(background_vision["widgets_values"][7], "location")
            direction = only_type(workflow, "MVDirectorDirectionEnhancer")
            self.assertEqual(
                input_link(workflow, direction, "concept_emd")[1:3],
                [character_vision["id"], 0],
            )
            self.assertEqual(
                input_link(workflow, direction, "observations_json")[1:3],
                [background_vision["id"], 3],
            )
            compiler = only_type(workflow, "MVDirectorEMDCompiler")
            self.assertEqual(
                compiler["widgets_values"],
                [
                    "ja_to_en",
                    "Qwen3-4B-abliterated/Qwen3-4B-abliterated-q5_k_m.gguf",
                    "auto",
                    8,
                    4096,
                    0.0,
                    0.9,
                    1.05,
                    -1,
                    256,
                    16384,
                    True,
                    "q8_0",
                    True,
                    False,
                    1,
                    "fixed",
                    "reuse",
                ],
            )
            seed_controls = {
                "MVDirectorDirectionEnhancer": (18, 19),
                "MVDirectorTimelinePlanner": (16, 17),
            }
            for node_type, (seed_index, control_index) in seed_controls.items():
                values = only_type(workflow, node_type)["widgets_values"]
                self.assertEqual(values[seed_index], 1)
                self.assertEqual(values[control_index], "fixed")
            for vision in (character_vision, background_vision):
                self.assertEqual(vision["widgets_values"][21], 1)
                self.assertEqual(vision["widgets_values"][22], "fixed")
                self.assertEqual(vision["widgets_values"][16], 16384)
            self.assertEqual(planner["widgets_values"][1], "サブジェクト1")
            self.assertEqual(planner["widgets_values"][5], 1536)
            self.assertEqual(planner["widgets_values"][11], 16384)
            self.assertEqual(direction["widgets_values"][2:5], ["anime_story_mv"] * 3)
            self.assertEqual(direction["widgets_values"][13], 16384)
            self.assertIn("眉毛は丸く", character_vision["widgets_values"][2])
            self.assertIn("木製台全体は黒色", character_vision["widgets_values"][2])
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
            self.assertEqual(lyric_segments[0].section, "INTRO")
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

    def test_context_loop_debug_workflow_separates_character_and_background_vision(self) -> None:
        workflow = json.loads(
            (DEVELOPMENT_WORKFLOWS / "01_plan_compiler_context_loop_debug.json")
            .read_text(encoding="utf-8")
        )
        character_vision = titled_node(
            workflow, "Character Vision / Subject EMD"
        )
        background_vision = titled_node(
            workflow, "Background Vision (Scene Only)"
        )
        direction = only_type(workflow, "MVDirectorDirectionEnhancer")
        self.assertEqual(character_vision["widgets_values"][1], "subject_only")
        self.assertIn("赤い鼻緒の黒い木下駄", character_vision["widgets_values"][2])
        self.assertIn("木製台全体は黒色", character_vision["widgets_values"][2])
        self.assertEqual(background_vision["widgets_values"][1], "scene_only")
        self.assertEqual(background_vision["widgets_values"][4], "lock_identity")
        self.assertEqual(background_vision["widgets_values"][2], "")
        self.assertEqual(background_vision["widgets_values"][6:8], ["none", "location"])
        self.assertEqual(
            only_type(workflow, "MVDirectorTimelinePlanner")["widgets_values"][3],
            "Qwen3-4B-abliterated/Qwen3-4B-abliterated-q5_k_m.gguf",
        )
        self.assertEqual(
            only_type(workflow, "MVDirectorTimelinePlanner")["widgets_values"][11],
            16384,
        )
        self.assertEqual(
            only_type(workflow, "MVDirectorEMDCompiler")["widgets_values"][10],
            16384,
        )
        for node_type in (
            "MVDirectorImageToSubjectEMD",
            "MVDirectorDirectionEnhancer",
            "MVDirectorTimelinePlanner",
            "MVDirectorEMDCompiler",
        ):
            for node in [value for value in workflow["nodes"] if value["type"] == node_type]:
                named = node.get("widgets_values_named", {})
                self.assertEqual(named.get("cache_mode"), "reuse")
                self.assertEqual(named.get("randomize"), "fixed")
        self.assertEqual(
            input_link(workflow, direction, "concept_emd")[1:3],
            [character_vision["id"], 0],
        )
        self.assertEqual(
            input_link(workflow, direction, "observations_json")[1:3],
            [background_vision["id"], 3],
        )
        video = json.loads(
            (DEVELOPMENT_WORKFLOWS / "02_video_context_loop_debug.json")
            .read_text(encoding="utf-8")
        )
        binder = only_type(video, "MVDirectorH3BackgroundReference")
        background_image = titled_node(
            video, "Background Reference • <Picture 2>"
        )
        ref2va = only_type(video, "MiniMaxH3ReferenceToVideo")
        self.assertEqual(binder["widgets_values"], [2])
        self.assertEqual(
            input_link(video, binder, "background_image")[1:3],
            [background_image["id"], 0],
        )
        self.assertEqual(
            input_link(video, ref2va, "ref_images.ref_image_1")[1:3],
            [binder["id"], 1],
        )
        self.assertEqual(ref2va["widgets_values"][4], "max")
        self.assertFalse(only_type(video, "MiniMaxH3ChainReview")["widgets_values"][0])
        self.assertEqual(
            only_type(video, "UNETLoader")["widgets_values"][0],
            H3_DIFFUSION_MODEL,
        )
        self.assertEqual(
            only_type(video, "CLIPLoader")["widgets_values"][0],
            H3_TEXT_ENCODER,
        )
        self.assertEqual(
            only_type(video, "ModelAttentionBackend")["widgets_values"],
            ["comfy kitchen attention"],
        )
        resolution = only_type(video, "ResolutionSelector")
        plan = only_type(video, "MiniMaxH3ChainPlanModern")
        self.assertEqual(
            resolution["widgets_values"],
            ["16:9 (Widescreen)", 0.4, 32],
        )
        self.assertEqual(
            input_link(video, plan, "width")[1:3],
            [resolution["id"], 0],
        )
        self.assertEqual(
            input_link(video, plan, "height")[1:3],
            [resolution["id"], 1],
        )

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
            background_binder = only_type(
                workflow, "MVDirectorH3BackgroundReference"
            )
            background_image = titled_node(
                workflow, "Background Reference • <Picture 2>"
            )
            ref2va = only_type(workflow, "MiniMaxH3ReferenceToVideo")
            character_image = titled_node(
                workflow, "Reference Image • <Picture 1>"
            )
            full_mix = titled_node(workflow, "Full Mix")
            vocal = titled_node(workflow, "Vocal Stem")
            fallback_plan = json.loads(plan["widgets_values"][0])
            self.assertEqual(fallback_plan["defaults"]["steps"], 8)
            self.assertEqual(plan["widgets_values"][8], 8)
            self.assertEqual(
                input_link(workflow, plan, "plan_json_input")[1:3],
                [background_binder["id"], 0],
            )
            self.assertEqual(
                input_link(workflow, background_binder, "plan_json")[1:3],
                [plan_loader["id"], 0],
            )
            self.assertEqual(
                input_link(
                    workflow, background_binder, "background_image"
                )[1:3],
                [background_image["id"], 0],
            )
            self.assertEqual(background_binder["widgets_values"], [2])
            self.assertEqual(
                character_image["widgets_values"][0],
                "image001_mikofox (2).jpg",
            )
            self.assertEqual(background_image["widgets_values"][0], "image002_keinai.jpg")
            self.assertEqual(full_mix["widgets_values"][0], "autumn_fox_shrine.mp3")
            self.assertEqual(vocal["widgets_values"][0], "autumn_fox_shrine_vocal.mp3")
            self.assertEqual(
                input_link(
                    workflow, ref2va, "ref_images.ref_image_1"
                )[1:3],
                [background_binder["id"], 1],
            )

            profile = only_type(workflow, "MiniMaxH3GenerationProfile")
            self.assertEqual(profile["widgets_values"][1], profiles[mode])
            pad = only_type(workflow, "MVDirectorAudioPadPair")
            self.assertEqual(pad["widgets_values"][3], alignments[mode])
            self.assertEqual(
                input_link(workflow, pad, "plan_json")[1:3],
                [background_binder["id"], 0],
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

            lora = only_type(workflow, "LoraLoaderModelOnly")
            shifts = [
                node
                for node in workflow["nodes"]
                if node["type"] == "MiniMaxH3SigmaShift"
            ]
            self.assertEqual(len(shifts), 1)
            sigma_shift = shifts[0]
            attention = only_type(workflow, "ModelAttentionBackend")
            unet = only_type(workflow, "UNETLoader")
            text_encoder = only_type(workflow, "CLIPLoader")
            video_vae = titled_node(workflow, "Video VAE")
            audio_vae = titled_node(workflow, "Audio VAE")
            review = only_type(workflow, "MiniMaxH3ChainReview")
            resolution = only_type(workflow, "ResolutionSelector")
            self.assertEqual(
                input_link(workflow, lora, "model")[1:3], [unet["id"], 0]
            )
            self.assertEqual(unet["widgets_values"][0], H3_DIFFUSION_MODEL)
            self.assertEqual(text_encoder["widgets_values"][0], H3_TEXT_ENCODER)
            self.assertEqual(
                video_vae["widgets_values"][0],
                "MiniMaxH3\\minimax_h3_video_vae_fp16.safetensors",
            )
            self.assertEqual(
                audio_vae["widgets_values"][0],
                "MiniMaxH3\\minimax_h3_audio_vae_fp32.safetensors",
            )
            self.assertEqual(
                lora["widgets_values"][0],
                "MiniMaxH3\\minimax_h3_ref2v_turbo_4step_v0.1_comfyui_bf16.safetensors",
            )
            self.assertEqual(attention["widgets_values"], ["comfy kitchen attention"])
            self.assertFalse(review["widgets_values"][0])
            self.assertEqual(ref2va["widgets_values"][4], "max")
            self.assertEqual(
                resolution["widgets_values"],
                ["16:9 (Widescreen)", 0.4, 32],
            )
            self.assertEqual(
                input_link(workflow, plan, "width")[1:3],
                [resolution["id"], 0],
            )
            self.assertEqual(
                input_link(workflow, plan, "height")[1:3],
                [resolution["id"], 1],
            )
            self.assertEqual(
                input_link(workflow, attention, "model")[1:3],
                [lora["id"], 0],
            )
            self.assertEqual(
                input_link(workflow, sigma_shift, "model")[1:3],
                [attention["id"], 0],
            )
            self.assertEqual(sigma_shift["widgets_values"], [12, 3])
            scheduler = only_type(workflow, "BasicScheduler")
            self.assertEqual(scheduler["widgets_values"][1], 8)

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
