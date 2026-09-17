# 32-bit Seed

GGUFとH3の複数分岐へ同じ`1..2147483647`のseedを渡すutilityです。

| 入力 | 既定 | 説明 |
|---|---:|---|
| `mode` | `fixed` | `fixed`は保存値、`random`は実行ごとに生成 |
| `seed` | `-1` | `-1`は一度ランダム生成、正数はその値を使用。`0`は禁止 |

出力`seed`をVision、Enhancer、Planner、Compiler、H3へ分岐できます。比較試験では`fixed`と正数を使い、変更対象以外の生成条件を固定します。
