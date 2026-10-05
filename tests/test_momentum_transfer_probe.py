import unittest

from core.emd import parse_emd
from core.lyrics import format_emd_time
from tools.debug_momentum_pipeline import production_inputs, USER_REQUEST
from tools.debug_momentum_transfer import transfer_input, scene_clock


PREFIX = """# サブジェクト
* `画像1` 袴を着て剣を持つ人物。

# シーン設定
## 環境
* 滝と紅葉。

# 共通プロンプト
## モーション
* 身体演技を行う。

"""
for i in range(1, 11):
    start, end = format_emd_time((i - 1) * 89458 // 10), format_emd_time(i * 89458 // 10)
    PREFIX += (f"> `シーン` {i}\n# シーン {start} --> {end}\n* `H3長` 226\n"
               f"## ショット {start}\n* `演技` 旧演技。\n* `カメラ` 正面。\n\n")
SOURCE = """> `シーン` 11
# シーン 01:29.458 --> 01:39.375
* `H3長` 260
## ショット 01:29.458
* `演出` 紅葉が舞う。
* `カメラ` 正面から引く。
* `演技` 半回転する。

"""
TARGET = """> `シーン` 12
# シーン 01:39.375 --> 01:50.000 継続
* `H3長` 277
## ショット 01:39.375
* `演技` 検証対象外。
* `カメラ` 検証対象外。
"""


class MomentumTransferProbeTests(unittest.TestCase):
    def test_source_unchanged_and_only_target_performance_open(self):
        text = transfer_input(PREFIX + SOURCE + TARGET)
        self.assertTrue(text.startswith(PREFIX + SOURCE))
        document = parse_emd(text)
        self.assertEqual([d.kind for d in document.scenes[11].shots[0].directives], ["演出", "カメラ", "演技"])
        template, _, _, _ = production_inputs(text, USER_REQUEST, target_scene=12)
        self.assertEqual(len(template.scenes[10].shots[0].directives), 3)
        self.assertEqual([d.kind for d in template.scenes[11].shots[0].directives], ["演出", "カメラ"])
        self.assertFalse(template.scenes[11].continuation)

    def test_clock_uses_source_samples_and_tail_padding(self):
        clock = scene_clock(PREFIX + SOURCE + TARGET)
        self.assertEqual(clock["source_start_sample"], 4770000)
        self.assertEqual(clock["source_end_sample"], 5280000)
        self.assertEqual(clock["content_frames"], 255)
        self.assertEqual(clock["render_frames"], 260)
        self.assertEqual(clock["tail_silence_samples"], 10000)

    def test_non_placeholder_target_rejected(self):
        with self.assertRaises(ValueError):
            transfer_input(PREFIX + SOURCE + TARGET.replace("`演技` 検証対象外。", "`演技` 歌う。"))


if __name__ == "__main__":
    unittest.main()
