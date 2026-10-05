import unittest

from core.emd import parse_emd
from core.lyrics import format_emd_time
from tools.debug_instrumental_chain import chain_input, clock_from_text, connected_plan, USER_REQUEST, TARGETS, EVENT
from tools.debug_momentum_pipeline import production_inputs


EMD = "# サブジェクト\n* `画像1` 袴を着て剣を持つ人物。\n\n# シーン設定\n## 環境\n* 滝と紅葉。\n\n# 共通プロンプト\n## モーション\n* 演技を行う。\n\n"
for i in range(1, 14):
    start = (i - 1) * 89458 // 10 if i <= 10 else {11: 89458, 12: 99375, 13: 110000}[i]
    end = i * 89458 // 10 if i <= 10 else {11: 99375, 12: 110000, 13: 119208}[i]
    raw = 226 if i <= 10 else {11: 260, 12: 277, 13: 243}[i]
    EMD += (f"> `シーン` {i}\n# シーン {format_emd_time(start)} --> {format_emd_time(end)}"
            + (" 継続" if i in (12, 13) else "") + f"\n* `H3長` {raw}\n"
            + f"## ショット {format_emd_time(start)}\n* `演技` 元演技。\n* `カメラ` 元Camera。\n")
    if i == 13:
        EMD += ("> `セクション` VERSE_2\n> `歌詞開始` 01:56.046\n> `歌詞終了` 01:59.060\n"
                "> `歌詞` 天高く響く\n## ショット 01:56.667\n* `演技` 歌う。\n* `カメラ` 顔。\n")
    EMD += "\n"


class InstrumentalChainProbeTests(unittest.TestCase):
    def test_four_performances_open_with_continuation_preserved(self):
        text = chain_input(EMD)
        template, _, _, _ = production_inputs(text, USER_REQUEST, target_scenes=TARGETS, preserve_continuation=True)
        self.assertEqual([s.continuation for s in template.scenes[10:13]], [False, True, True])
        self.assertEqual(sum(len(s.shots) for s in template.scenes[10:13]), 4)
        for s in template.scenes[10:13]:
            for q in s.shots:
                self.assertEqual([d.kind for d in q.directives], ["演出", "カメラ"])
        self.assertEqual(template.scenes[0].shots[0].directives[0].text, "元演技。")

    def test_authored_water_event_and_lyrics_preserved(self):
        document = parse_emd(chain_input(EMD))
        self.assertEqual(document.scenes[11].shots[0].directives[0].text, EVENT)
        annotation = document.scenes[12].shots[1].lyric_annotations[0]
        self.assertEqual((annotation.text, annotation.start_ms, annotation.end_ms), ("天高く響く", 116046, 119060))

    def test_actual_source_preroll_without_silence_padding(self):
        clock = clock_from_text(EMD)
        self.assertEqual(clock["source_start_sample"], 4250000)
        self.assertEqual(clock["source_end_sample"], 5722000)
        self.assertEqual(clock["render_frames"], 736)
        self.assertEqual(clock["tail_silence_samples"], 0)
        self.assertEqual(clock["preroll_frames"], 22)

    def test_plan_scope_and_dependency_clocks(self):
        full = {"shots": [{"id": f"scene_{i:04d}", "length": 226, "context_length": 0,
                           "audio_context_length": 0, "prompt": []} for i in range(1, 14)],
                "mv_director_audio_activity": {"clock": "whole_song"}}
        for index, raw, context in ((10, 260, 0), (11, 277, 22), (12, 243, 22)):
            full["shots"][index].update(length=raw, context_length=context, audio_context_length=context)
        plan = connected_plan(full)
        self.assertEqual(len(plan["shots"]), 3)
        self.assertNotIn("mv_director_audio_activity", plan)
        self.assertIn("mv_director_audio_activity", full)
        full["shots"][11]["audio_context_length"] = 0
        with self.assertRaises(ValueError):
            connected_plan(full)


if __name__ == "__main__":
    unittest.main()
