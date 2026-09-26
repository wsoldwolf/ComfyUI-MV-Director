# H3 Timing Profile

Lyric Segmentation、Audio Pad Pair、EMD Compilerへ同じContext Loop時間契約を渡します。

## 入出力

| 種別 | 名前 | 説明 |
|---|---|---|
| 入力 | `contract` | 対応する固定contractから選択。現在の検証commitが既定 |
| 出力 | `timing_profile` | 下流へ渡すtyped profile |
| 出力 | `profile_json` | 人が確認できるcanonical JSON |
| 出力 | `status` | contract IDとfps |

現在の基準はContext Loop 0.7.0 commit `d80304f05ecc2f504e64cbfb636e2a21d4409909`、24fpsです。各下流ノードは未接続でも同じ既定profileを使いますが、workflow上で明示接続すると時間契約を確認しやすくなります。

旧0.6.9 commit `9860a063784c8c23b58e00107f2180e0df3c43d9`も選択できます。
両contractは17k+5のraw frame長、継続context 22frames、audio context 22framesを共有します。
選択したcommitはprofile JSON・statusと下流のキャッシュキーに残ります。
実行時にGitのHEADを自動追跡する機能ではなく、検証済みcommitを明示的に選ぶ仕組みです。
