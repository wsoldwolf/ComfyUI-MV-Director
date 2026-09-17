# H3 Timing Profile

Lyric Segmentation、Audio Pad Pair、EMD Compilerへ同じContext Loop時間契約を渡します。

## 入出力

| 種別 | 名前 | 説明 |
|---|---|---|
| 入力 | `contract` | 対応する固定contractを一つだけ選択 |
| 出力 | `timing_profile` | 下流へ渡すtyped profile |
| 出力 | `profile_json` | 人が確認できるcanonical JSON |
| 出力 | `status` | contract IDとfps |

現在の基準はContext Loop 0.6.9 commit `9860a063784c8c23b58e00107f2180e0df3c43d9`、24fpsです。各下流ノードは未接続でも同じ既定profileを使いますが、workflow上で明示接続すると時間契約を確認しやすくなります。
