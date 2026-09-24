# 作者演出候補とPython動作補完の2×2比較（P7）

2026-09-25。8Bに全ての振付を創作させる代わりに、ユーザーが`# 演出候補`へ具体的な身体動作を書いた場合の効果を調べた。過去の[手書きの短いH3映像仕様の成功](audio-reference-compact-tree-fire-stability-2026-09-24.md)を出発点とするが、今回H3動画は生成していない。本番コード・prompt・profile・EMD・ワークフローは変更していない。

## 条件

保存済みScene 5（古傷）とScene 9（狐火）のScene Author Performance入力を使用。各SceneでPython動作補完なし／あり、作者候補なし／ありの2×2をseed 1・2で比較した。Qwen3-8B-Abliterated Q4_K_M、temperature 0.1、top_p 0.9、n_ctx 8192、本番Performance prompt・grammar・parserを共通にした。Python補完のon/off保存入力は`scheduled_motion_composition`以外が同値である。作者候補は[Directionの既存構文パーサ](../../core/direction/enhancer.py)で`# 演出候補`一行として読み取り、`staging_candidates_optional`へ追加した。

候補は二種類。最初は過去にユーザーが書いた[古傷側の長い振付](../assets/research/audio-reference-body-isolation-2026-09-24/p7-scene5-user-request.md)と[狐火側の具体演出](../assets/research/audio-reference-body-isolation-2026-09-24/p7-scene9-user-request.md)を使用。長文が負担かを分けるため、次にCodexが[古傷の短文](../assets/research/audio-reference-body-isolation-2026-09-24/p7-scene5-user-request-compact.md)と[狐火の短文](../assets/research/audio-reference-body-isolation-2026-09-24/p7-scene9-user-request-compact.md)を作り、同じseedの候補あり条件だけ8件再実行した。短文条件は候補原文だけでなく意味の絞り方も違うため、差を**文字数だけの因果効果**とは呼ばない。

これはPerformance段階への局所注入であり、Direction→Event→候補選択→Scene spine→Camera→CompilerのE2Eを通していない。候補が本番で自動選択される確率やH3品質を示す試験ではない。

## 結果

| 条件 | 構造 | 観察 |
| --- | --- | --- |
| 候補なし、Pythonなし | 4/4完了 | Scene 5は手・口・短い脚動作。Scene 9は一方のseedで2 Shot同文。全身振付は限定的 |
| 長い候補あり、Pythonなし | 3/4完了 | Scene 5では脚・荷重・腕が増える例がある一方、別seedは候補を左右反転して両Shotへほぼ複写。Scene 9 seed 1は同じ文を生成上限まで反復し、Shot 2欠落 |
| 候補なし、Pythonあり | 4/4完了 | 大きい移動は明示されるが、Scene 9の2 seedとも2 Shotの本文が同文。人物の自転も出る |
| 長い候補あり、Pythonあり | 4/4完了 | Scene 5は一部で腕・脚の変化が増えた。Scene 9は2 seedとも補完移動と上げた手を両Shotへ複写し、候補の両手の受け渡し・狐火との連携は現れない |
| 短文候補あり、Pythonなし／あり | 8/8完了 | Scene 5のPythonありseed 2では胸の手を解き体幹を起こすShot進行が出た。他は手・足の左右反転や同文反復が残る。Scene 9には候補の円弧→受け渡し→解放が安定して現れない |

構造の`完了`は本番パーサでrequired slotが揃った件数であり、意味の合格ではない。長文のScene 9欠落はgrammar下でも起きた。grammarは各行の開始を縛れるが、本文の反復ループを防げない。短文化でその条件の欠落は消えたものの、人物演技の質は安定しなかった。作者候補が本文に存在しても、各Shotへ丸ごと複写されるなら振付ではない。

## 判断

「固定Python動作だけが成功要因」とも「作者候補を渡せば8Bが振付できる」とも結論しない。前者は移動を確実に出すが、二つのShotへ同じ演技を複写する。後者は局所的に身体語彙を増やすが、任意の着想として渡す現在の契約では、作者の時間進行を保護できない。特に狐火の成功済みH3映像と今回の弱い8B文を比べると、**H3の能力ではなく、作者の短い映像文をPlannerが保持・配置する境界**が次の対象である。

次の小さい検証は、同じScene 9・同じH3入力条件で二経路だけ比較すること。(A) 現行の`# 演出候補`を任意着想として8Bに再生成させる経路、(B) 作者が採用を明示した**Scene限定の短い演技文を原文保持**してH3へ渡す経路。BのScene選択とShot位置は歌詞時刻を使って明示・検査し、Pythonが作者文を「良さそうに」書き換えない。まずEMD/Plan上の差を提示し、人の中間判定で有望な場合だけ短区間H3に進む。これならモデル交換時も任意候補と作者固定を混同しない。新しい全曲LLM段階、無制限retry、全曲自動パッチは導入しない。

## 証跡

- [比較スクリプト](../assets/research/audio-reference-body-isolation-2026-09-24/probe_p7_author_candidate_vs_composition.py)
- [長文候補の16応答](../assets/research/audio-reference-body-isolation-2026-09-24/p7-candidate-vs-composition-abliterated-seed1-2.json)
- [短文候補の8応答](../assets/research/audio-reference-body-isolation-2026-09-24/p7-compact-candidate-vs-composition-abliterated-seed1-2.json)
- 過去の[Python補完オン・オフ試験](motion-composition-2026-09-23.md)および[短文PlanのH3比較](audio-reference-compact-tree-fire-stability-2026-09-24.md)
