# Scene Event根拠宣言 P0–P2：固定入力と8B判定

2026-09-24。[設計案](scene-event-source-selection-design-2026-09-24.md)を、保存済みScene入力とQwen3-8B-Abliterated Q4_K_Mで検証した。これは**Eventのみ**のオフライン比較であり、Planner本番・Compiler・H3動画は変更していない。結論は、**行形式は安定したが、対象採用は改善せず、P2の演技・Camera伝播は品質ゲートで停止**である。花の表現能力そのものを否定する結果ではない。

## P0：比較入力と出典を固定

[Scene 3–6のP0 manifest](../assets/research/scene-event-source-2026-09-24/p0/manifest.json)は、P1b v2の保存済み`scene-author-event`生入力から元歌詞、Shot、`source_line`、候補数、payload hashを固定した。[Scene 9のP0 manifest](../assets/research/scene-event-source-2026-09-24/p0-foxfire/manifest.json)は別の保存系列なので、元の生成結果同士は直接比較しない。P1では両系列とも同じ現行実験用Event system promptと同じ根拠付き変種を使い、**同一Scene・同seed内**で比較した。候補原文、歌詞の時刻、Shot境界、背景は条件間で変えない。作者固定`演出`がある場合はScene Eventの呼出し自体を省く既存契約であり、今回の5 Sceneはいずれも固定Eventなし。

| Scene | 現在Sceneの原歌詞と対象位置 | 既存候補との関係 | 対照に選んだ理由 |
|---|---|---|---|
| 3 | 「苔へと還る」が後半Shot | 大樹の根元の苔候補あり | 候補があっても前半の石段・落葉へ焦点が戻るか |
| 4 | 「人は花より」「短く咲いて」がShot 2 | 元の7件に花候補なし | 歌詞自体から花を選べるか。花候補追加の別[P1比較](shot-linkage-p1-candidate-comparison-2026-09-24.md)でも欠落 |
| 5 | 「胸の古傷は／増えてゆく」がShot 2 | 人物の振付候補はある | 歌詞の暗示・身体表現を外部Eventとして無理に実体化しないか |
| 6 | 「御神木は」が後半Shot | 御神木の候補なし | 後半の具体物と前半の抽象的な「長さ」の選択 |
| 9 | 「朱の空に舞う」がShot 2、「狐火へ問う」がShot 3 | 狐火の候補あり | 一続きの比喩と、名詞が現れるShotの時差をどう扱うか |

過去の[Planner v54](planner-v54-lyric-cue-discovery-2026-09-20.md)では別の、より直接的な歌詞「参道に咲く花」から花びらと人物反応が出ている。[EMD 00014の評価](planner-emd-00014-event-role-review-2026-09-20.md)には現在と同じ「人は花より／短く咲いて」を含むSceneで花が3 Shotに出た記録がある。ただし00014の生Cue応答・EMD原本は今回のworkspaceに無く、内部判断の再現対照としては使えない。**8Bの能力不足ではなく経路・入力・採択条件の違いを調べる**理由として扱う。

## P1：同じEvent一呼出し内にSOURCEとFOCUSを加える

[実験スクリプト](../../tools/offline_scene_event_source_probe.py)は現行の`EVENT<TAB>1<TAB>SHOT=...`と、`SOURCE=LYRIC:shot#:line# / CANDIDATE:# / NONE`、`FOCUS`、`SHOT`、本文を同じ一行に出す形式を比較する。後者は元のsystem promptの出来事選択文を保持し、末尾の出力指示を根拠宣言へ変更した。grammarは**存在する原歌詞行・候補番号・Shot番号だけ**を列挙し、日本語本文は自由にする。Pythonは自然文を補作・置換しない。実効seed 2/3、`n_ctx=16384`、temperature 0.2、同じモデル・同じScene payloadを使用した。花・苔・御神木の[生応答20件中16件](../assets/research/scene-event-source-2026-09-24/p1-seed2-3/manifest.json)と狐火の[残り4件](../assets/research/scene-event-source-2026-09-24/p1-foxfire-seed2-3/manifest.json)を保存した。

| Scene | 現行Event、seed 2 / 3 | SOURCE付きEvent、seed 2 / 3 | 評価 |
|---|---|---|---|
| 3 苔 | 両方Shot 2で苔を背景・地面として描く | 両方`SOURCE=Shot 1「石段に積もる」`。seed 2は本文に苔が出るが、seed 3は落葉だけ | 苔の出現・開始位置は改善せず、むしろ選択根拠が前半へ戻る |
| 4 花 | 両方Shot 1で落葉 | 両方`SOURCE=Shot 1「色褪せた契り」`、花なし | 花の採用0/2。歌詞Shot 2にも進まない |
| 5 古傷 | 両方Shot 1で落葉 | 両方Shot 2の「胸の古傷は」を選び、胸の傷跡・痛みを描写 | 歌詞との結び付きは増したが、比喩や感情を身体の実傷へ寄せる危険がある。創作上の合格とはしない |
| 6 御神木 | 両方Shot 1で落葉・影 | 両方`SOURCE=Shot 1「長さなのか」`、御神木なし | 後半の御神木の採用0/2 |
| 9 狐火 | seed 2はShot 2、seed 3はShot 1で狐火 | 両方Shot 2で狐火。ただし`SOURCE=Shot 2「朱の空に舞う」`、`FOCUS=朱の空に舞う狐火` | 可視対象はあるが、根拠IDは狐火の語があるShot 3ではない。文脈上の先行表現は可能でも、SOURCEを厳密な証明とは呼べない |

形式上のparse errorは**0/20**。10組の現行Event推論時間合計13.07秒に対し、SOURCE付きは24.01秒（モデル読込を除く）。平均入力tokenも2686→2826。追加LLM呼出しはないが、出力欄と指示による計算費は増えた。数値はこのGPU・5 Sceneの測定であり、5060全曲への外挿はしない。

**解釈**：構造化された根拠欄だけでは、8Bが「現在Sceneでどの歌詞を主題にすべきか」を正しく選ぶとは限らない。Scene 3・4・6では前半Shotの語に偏り、花・御神木を選ばなかった。`SOURCE`が実在する行を指すという機械検査は通っても、`FOCUS`と本文がその行からどう導かれたかの意味的一致を保証しない。狐火の例では、隣接する歌詞を人間なら一続きに読める一方、単一行IDではその関係を表現し切れない。原歌詞行の採用を強制したり対象語の部分文字列で合否を決めたりすると、MVの比喩や先行演出を過剰に拒否する。

## P2：品質ゲートによる停止

[P2判定](../assets/research/scene-event-source-2026-09-24/p2-gate.json)は`no_go`。事前条件の「花など歌詞対象の採用と開始位置が改善する」を満たさなかったため、このEventをPerformance・Cameraへ渡してEMDを生成する推論は**実行しなかった**。ここで伝播だけを成功させても、落葉や「色褪せた契り」を花のSceneの中心に固定するだけで、評価したい問題の改善にならない。作者固定`演出`の優先と未指定分だけを生成する経路は既存の`tests/test_scene_author.py`で引き続き確認できる。本番profile・Planner・Compiler・Workflowは未変更。

## 次に試すべき小さい変更

同一Event応答へ`SOURCE`を足すだけの案は採用しない。次に比較するなら、**背景や演出候補を見せない短い「歌詞内の焦点候補選択」**を先に行い、その結果と原歌詞を固定してEventへ渡す二段構成が合理的である。前段はSceneの歌詞行ID又は`NONE`を選ぶだけにし、PythonはID存在性のみ確認する。後段は候補原文と背景を配置・発展の材料として読む。これは新たなLLM呼出しになるため、Scene 3・4・6・9の固定seed試験で花と御神木の選択改善、狐火の先行表現、`なし`と比喩の扱い、追加時間・16k contextを測るまでは実装しない。歌詞対象を毎回画面へ強制する仕様にも、作者の固定文を任意候補へ格下げする仕様にもしない。
