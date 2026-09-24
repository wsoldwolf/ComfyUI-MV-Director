# Scene Event：Shot連続句・境界句の焦点選択判定

2026-09-24。[単一歌詞行の二段試験](scene-lyric-focus-two-stage-2026-09-24.md)の次段として、各Shotの連続歌詞と隣接Shotの末尾・先頭を一つの句として8Bへ提示した。Scene 3〜6と9、seed 2・3の計10件を同時条件の現行Eventと比較した。**現行Plannerへの導入は見送る。** 句候補は正しく作れたが、8Bの選択と選択後Eventの両方で対象が失われる。EMD、Compiler、H3、本番Plannerは変更していない。

## 条件と証拠

[オフラインスクリプト](../../tools/offline_scene_phrase_focus_probe.py)は保存済みScene Event入力から、`SHOT:n`（そのShotの全連続歌詞行）と`BRIDGE:n-(n+1)`（前Shot末行＋後Shot初行）を機械的に作る。焦点選択へはScene番号・歌詞・句IDだけを渡し、背景、人物、演出候補、先行Eventは見せない。選択後Eventでは元入力を保持して選択句を付加する。Pythonは名詞を抽出・優先せず、Event自然文を修復しない。原文、hash、token数、時間は[自由理由版Scene 3〜6](../assets/research/scene-phrase-focus-2026-09-24/scene3-6-seed2-3/manifest.json)、[同Scene 9](../assets/research/scene-phrase-focus-2026-09-24/scene9-seed2-3/manifest.json)、[YES/NO版Scene 3〜6](../assets/research/scene-phrase-focus-2026-09-24/binary-scene3-6-seed2-3/manifest.json)、[同Scene 9](../assets/research/scene-phrase-focus-2026-09-24/binary-scene9-seed2-3/manifest.json)に保存した。モデルはQwen3-8B-Abliterated Q4_K_M、temperature 0.2、`n_ctx=16384`、seed 2・3。短区間8Bのみで動画生成はしていない。

最初の「各Shotを短い理由つきで評価」形式では、10件中6件の理由欄に`EVAL`や`SELECT`の文字列を再生する汚染があった。行全体はgrammarを満たしていても理由の信用度が低いため、評価を厳密な`YES/NO`に限定して**同条件を再試験**した。下表は後者を主判定とする。

| Scene | 現行Event（両seed） | Shot評価→句選択（両seed） | 選択後Event（両seed） | 判定 |
|---|---|---|---|---|
| 3 苔 | Shot 2で苔の上の落葉 | `BRIDGE:1-2`。苔のあるShot 2を`NO` | Shot 1で石段への落葉。苔が消失 | 退行 |
| 4 花 | Shot 1の落葉 | `SHOT:1`。花を含むShot 2を`NO` | Shot 1の落葉。花なし | 未改善 |
| 5 古傷 | Shot 1の落葉 | `BRIDGE:1-2`。後半Shotを`NO` | 落葉・石畳の光 | 未改善 |
| 6 御神木 | Shot 1の落葉 | `BRIDGE:1-2`。御神木を含むShot 2を`NO` | Shot 1の落葉。御神木なし | 未改善 |
| 9 狐火 | 両seedで狐火 | `BRIDGE:1-2`。目的の`BRIDGE:2-3`は選ばない | 狐火は残るが、seed 2は落葉が主で狐火は光の付属物 | 改善なし |

Scene 4の`SHOT:2`には「わらわだけ／人は花より／短く咲いて」、Scene 9の`BRIDGE:2-3`には「朱の空に舞う／狐火へ問う」が実際に入っている。[CPUテスト](../../tests/test_offline_scene_phrase_focus_probe.py)で両境界を固定した。**候補の欠落ではなく選択の問題**である。

一方、自由理由版ではScene 4の両seedが`SHOT:2`を選んだにもかかわらず、選択後Eventは花を描かず、歩行中の光又は落葉になった。これは**選択さえ直せば解決するわけではない**反例である。ただし自由理由版には前記の理由欄汚染があるため、形式の安定した条件での花採用成功とみなさない。Scene 9も最初の条件では両seedで狐火がEventから消えた。形式を変えるだけで結果が変わるほど、少数seedの創作結果は不安定である。

YES/NO版は10/10件で焦点・Event形式が成立した。推論時間合計は現行Event 12.81秒に対し、焦点5.52秒＋選択後Event14.10秒＝19.62秒（モデル読込を除く、今回のGPU）。追加約0.68秒/Sceneはこの機材と短区間に限った値で、全曲・5060の所要時間ではない。

## 結論と次の境界

**二段の焦点選択を本番採用しない。** 歌詞をShot連続句に束ねても、8Bは具体語のある後半Shotを`NO`とし、選んだ場合にも後段Eventで背景の落葉へ戻る。したがって「句の切り方だけ」が主因とは言えず、選択とEvent生成の間に情報を落とす境界が残る。この実験は8B一般の能力限界を証明しない。プロトタイプでの花表現、現行の作者演出候補による苔・狐火の成功とも矛盾しない。

次を試すなら、追加LLM段階をさらに重ねる前に、**Sceneの歌詞全体と視覚Eventを同一応答で選択・生成する短い単一呼出し**、又はユーザーの`# 演出候補`をScene局所へ渡した既存経路との比較を優先する。その際も作者固定指示を最優先し、任意候補を必須指令へ昇格させず、花・苔・御神木・狐火を新たなPython辞書で強制しない。採用条件は対象の有無だけでなく、Shot位置、外部effectと人物演技の分離、隣接Sceneの連続性、追加計算量を同時に満たすこととする。
