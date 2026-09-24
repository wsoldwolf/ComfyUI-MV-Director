# 簡潔Scene仕様 P6：公式8Bと現行8Bの形式・本文・推論設定

2026-09-25。公式Qwen3-8Bへの切替を、推論品質と規約遵守を混同せずに小範囲で評価した。本番モデル・prompt・profile・EMD・H3出力は変更していない。公式GGUFは研究用のモデル置場にあり、リポジトリには含めない。

## 比較条件

- 現行：Qwen3-8B-Abliterated Q4_K_M、SHA256 `8625E48DA4C4BE9BCBA2414FD8CAD4095FF3A538D5B0111C2B26B5F6209538B9`。
- 公式：[Qwen3-8B-GGUF](https://huggingface.co/Qwen/Qwen3-8B-GGUF) Q4_K_M、SHA256 `D98CDCBD03E17CE47681435B5150E34C1417F50B5C0019DD560E4882C5745785`。
- 保存済みScene 5（胸の古傷）とScene 9（狐火）の `scene-author-performance` payloadを再生。保存物ではScene番号を局所1へ振り直しているため、sourceで区別する。
- 現行の[Performance prompt](../../prompts/timeline_planner_scene_author_performance_system_prompt.txt)、[本番の構造grammar](../../core/planner/scene_author.py)、[同じレコードパーサ](../../core/protocols/llm_records.py)を使用。`/no_think`、`enable_thinking=False`、seed 1・2、n_ctx 8192、max_tokens 1536。
- 自由形式の先行対照は同じEvent fixtureでScene 6・9、seed 1–4、temperature 0.2、top_p 0.9。本番grammar無しなので本番の失敗率に換算しない。

## 観測

| 条件 | 自由形式のラベル・区切り遵守 | 本番Scene AuthorのTAB・slot遵守 | 本文の傾向 |
| --- | ---: | ---: | --- |
| 現行8B、temperature 0.2 | 自然ラベル7/8、長い説明ラベル7/8 | — | 一部に手・表情の動き。2 Shotで同文反復もある |
| 公式8B、temperature 0.2 | 自然ラベル8/8、長い説明ラベル4/8 | — | 長い説明ラベルではScene 6の4/4で複数行が一つの散文に潰れた |
| 現行8B、本番grammar、temperature 0.1 / top_p 0.9 | — | 4/4、欠落0、問題行0 | Scene 9の2/2で二つのShotが実質同じ動作。指定の合成動作を本文へ複写 |
| 公式8B、本番grammar、temperature 0.1 / top_p 0.9 | — | 4/4、欠落0、問題行0 | Scene 5は脚・肩・腕を動かす例が出たが、Scene 9には全身自転や鏡写しの開腕反復が残る |
| 公式8B、本番grammar、temperature 0.7 / top_p 0.8 | — | 4/4、欠落0、問題行0 | Scene 9で後方への逆移動、左右反転した同型動作。安定した振付改善は見えない |

自由形式の現行8Bの一件はASCII `|`が全角`｜`になっただけで、tokenと本文は一意に読める。これは輸送形式の正規化候補。別の一件は`CAMERA_2`が不明なtokenへ変化し、slotを推測する必要があった。公式8Bの長い説明ラベルの4件は、行・役割・slotの境界自体が失われ、機械的修復では本文の帰属を創作してしまう。本番grammarでは、このサンプルの両モデルともラベル・slotは揃った。

本番grammarは`PERFORMANCE<TAB>slot<TAB>`と順番を保証するが、人物主語、Shot間の姿勢継続、`END_STATE`の実体、合成動作との整合、反復回避までは保証しない。パーサ合格を「振付が良い」と数えてはいけない。実際、公式8BのScene 9 seed 1は人物の全身回転を書き、現行8Bは確定合成動作を二度本文へ繰り返した。

## 判断とコード側の責務

公式8Bへの既定切替も、長い説明ラベルへのプロトコル改称も採用しない。「公式なら規約を守る」「温度を上げれば演技が豊かになる」は、この小サンプルでは支持されない。一方、本番の有限grammarはこの範囲の**形式**を両モデルで保った。

1. **輸送層**：生成前grammarでラベル・slot・行順を固定する。制約できない段階では区切りの全角化など対応が一意な差だけを正規化し、元応答と操作をログに残す。
2. **構造層**：未知slot、重複、欠落、役割結合の本文を勝手に割り振らない。既存の局所再試行と欠落報告を使う。
3. **演出層**：主語、身体の時間的進行、前後Shotの接続、作者指定との整合を別に評価する。Pythonで自然文を捏造せず、入力・prompt・候補選択の小範囲A/Bと人による映像判定を行う。

次は二モデル×同一seedでEvent・Performance・Cameraをまとめた短い実Planner経路を走らせ、各段の形式失敗と最終EMDの人物演技を記録する。今回の保存済みPerformance入力には旧モデルが選んだEventが入るため、モデル切替の全経路品質は未判定。H3比較はEMDに意味のある差が出た場合だけ行う。英語prompt経路は独立した実験軸とし、モデル差・sampling差へ同時に混ぜない。

## 再現資料

- [研究スクリプト](../assets/research/audio-reference-body-isolation-2026-09-24/probe_p6_scene_author_protocol.py)
- 自由形式：[現行8B](../assets/research/audio-reference-body-isolation-2026-09-24/p6-model-ab-abliterated-seed1-4.json)、[公式8B](../assets/research/audio-reference-body-isolation-2026-09-24/p6-model-ab-official-seed1-4.json)
- 本番形式：[現行8B](../assets/research/audio-reference-body-isolation-2026-09-24/p6-production-protocol-abliterated-seed1-2.json)、[公式8B・現行設定](../assets/research/audio-reference-body-isolation-2026-09-24/p6-production-protocol-official-seed1-2.json)、[公式8B・推奨寄り設定](../assets/research/audio-reference-body-isolation-2026-09-24/p6-production-protocol-official-recommended-seed1-2.json)
- 非thinking samplingの目安は[Qwen3 quickstart](https://github.com/QwenLM/Qwen3/blob/main/docs/source/getting_started/quickstart.md)。0.7/0.8は二パラメータ同時変更なので、差を単一パラメータの効果とは呼ばない。
