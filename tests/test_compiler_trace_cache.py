"""Exercise the real strict cache writer, not just json.dumps diagnostics."""
import json
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from core.inference import SuccessCache
from nodes import NODE_CLASS_MAPPINGS
from test_emd_compiler_node import ENGLISH_EMD, FakeLifecycle


class CompilerTraceCacheTests(unittest.TestCase):
    def test_pre_vocal_contract_cache_is_not_reused(self):
        source = ENGLISH_EMD + "## 音響\n* `リップシンク` `Context Loop` `サブジェクト1`\n"
        model = SimpleNamespace(path=Path("test.gguf"), selection_id="test.gguf",
                                fingerprint="f" * 64, size=123, mtime_ns=456)
        for mode in ("already_english", "ja_to_en"):
            with self.subTest(mode=mode), TemporaryDirectory() as directory:
                cache = SuccessCache(directory)
                node = NODE_CLASS_MAPPINGS["MVDirectorEMDCompiler"]()
                node._lifecycle = FakeLifecycle()
                kwargs = dict(emd_text=source, translation_mode=mode, model_name="test.gguf",
                              chat_format="auto", steps=8, max_tokens=64, temperature=0.0,
                              top_p=0.9, repetition_penalty=1.05, gpu_layers=-1, n_batch=256,
                              n_ctx=1100, flash_attn=True, kv_cache_type="q8_0", op_offload=True,
                              keep_model_loaded=False, seed=1, cache_mode="reuse")
                with patch("nodes.node_emd_compiler.node._cache", return_value=cache), patch(
                    "nodes.node_emd_compiler.node.resolve_comfy_gguf_model", return_value=model
                ):
                    with patch("nodes.node_emd_compiler.node._COMPILER_CACHE_VERSION",
                               "mvd-ref2va-compiler-cache-v17"):
                        node.compile_emd(**kwargs)
                    old_file = next(Path(directory).glob("*/*.json"))
                    old_payload = cache.get(old_file.stem)
                    legacy_plan = json.loads(old_payload["plan_json"])
                    legacy_plan["legacy_cache_marker"] = True
                    old_payload["plan_json"] = json.dumps(legacy_plan)
                    cache.put_success(old_file.stem, old_payload)

                    fresh = node.compile_emd(**kwargs)
                    self.assertIn("cache=miss", fresh[2])
                    self.assertNotIn("legacy_cache_marker", fresh[0])
                    self.assertIn("visibly sings", fresh[0])
                    reused = node.compile_emd(**kwargs)
                    self.assertIn("cache=hit", reused[2])
                    self.assertEqual(fresh[:2], reused[:2])
                    self.assertEqual(len(list(Path(directory).glob("*/*.json"))), 2)

    def test_translated_trace_saves_and_reuses_without_loading_model(self):
        source = ENGLISH_EMD.replace("A person wearing a white coat.", "白い衣装の人物。")
        source = source.replace("The person walks forward.", "左手を伸ばし、Arc Shot の間も歌う。")
        model = SimpleNamespace(path=Path("test.gguf"), selection_id="test.gguf",
                                fingerprint="f" * 64, size=123, mtime_ns=456)
        for mode in ("reuse", "refresh"):
            with self.subTest(mode=mode), TemporaryDirectory() as directory:
                cache = SuccessCache(directory)
                node = NODE_CLASS_MAPPINGS["MVDirectorEMDCompiler"]()
                lifecycle = FakeLifecycle()
                node._lifecycle = lifecycle
                kwargs = dict(emd_text=source, translation_mode="ja_to_en", model_name="test.gguf",
                              chat_format="auto", steps=8, max_tokens=64, temperature=0.0,
                              top_p=0.9, repetition_penalty=1.05, gpu_layers=-1, n_batch=256,
                              n_ctx=1100, flash_attn=True, kv_cache_type="q8_0", op_offload=True,
                              keep_model_loaded=False, seed=1, cache_mode=mode)
                with patch("nodes.node_emd_compiler.node._cache", return_value=cache), patch(
                    "nodes.node_emd_compiler.node.resolve_comfy_gguf_model", return_value=model
                ):
                    first = node.compile_emd(**kwargs)
                    files = list(Path(directory).glob("*/*.json"))
                    self.assertEqual(len(files), 1)
                    saved = cache.get(files[0].stem)
                    trace = saved["translation_trace"]
                    self.assertEqual(len(trace), 2)
                    for row in trace:
                        for field in ("fragment_indices", "fragments", "translated"):
                            self.assertIsInstance(row[field], list)
                        self.assertEqual(len(row["fragments"]), len(row["translated"]))
                    self.assertEqual(len(trace[1]["translated"]), 2)
                    self.assertIn("Arc Shot", trace[1]["restored"])
                    self.assertEqual(saved["plan_json"], first[0])
                    self.assertTrue(json.loads(first[0])["shots"])
                    inference_calls = len(lifecycle.chat_calls)
                    loads = lifecycle.ensure_calls
                    second = node.compile_emd(**{**kwargs, "cache_mode": "reuse"})
                    self.assertEqual(first[:2], second[:2])
                    self.assertIn("cache=hit", second[2])
                    self.assertEqual(len(lifecycle.chat_calls), inference_calls)
                    self.assertEqual(lifecycle.ensure_calls, loads)
