# Planner責務分離とEMD 00006改善レポート

## 対象

- 評価対象: `C:\Software\ComfyUI\output\mv_director\context_loop_emd_00006.md`
- Profile: `anime_emotional_mv`
- 実施日: 2026-09-19

## EMD評価

対象EMDは16 Scene、52 Shotで、CUT 4、CONTINUE 12だった。CONTINUE率75%はProfileの連続演技方針と一致し、Plannerを停止させずCompilerへ渡せる構造になっている。一方、CameraはArc Shot 43、Zoom In 8、Push In 1で、Arc比率は82.7%に達した。Arcの開始・終了視点も少数の定型経路へ集中し、Cameraの勢いより軌道反復が目立つ状態だった。

Actionにも次の偏りがあった。

- 胸の位置を使う表現: 21 Shot
- 左手を腰へ置く表現: 18 Shot
- 手を上げる又は下げる表現: 23 Shot
- 歩行又は前進: 18 Shot
- 狐火: 26 Shot
- 胸の古傷: 15 Shot

苔は2 Shot、灯籠への接触は0 Shotまで抑制できていたが、狐火及び古傷は元歌詞のSceneを越えて反復していた。Camera文が確定Actionにない人物動作を追加する例も多く、Cameraから足元13件、左手を腰へ置く表現9件、手を上げる表現9件、手を下げる表現8件、背中を丸める表現13件が再導入されていた。ActionとCameraで手の上下が直接矛盾するShotも4件確認した。

## 原因

1. `anime_emotional_mv`のArc選択が、適格な非顔slotの約3分の2を長尺Arcへ割り当てていた。
2. 未割当slotでもCamera LLMがArcを選べ、bounded retry後は品質違反をAS IS採用できた。
3. Camera taskへMotion profile全体を渡していたため、Camera LLMが人物演技の語彙を読み、確定Actionを言い換え又は補足した。
4. Song DirectionをActionとCameraへ直接渡し、全曲の関係やmotifが現在Sceneの具体物認可として誤利用され得た。
5. Song Direction prompt自身が、場所又は物との物理的関係を全曲arcとして作るよう要求していた。
6. 長尺Arc選択にShot尺の下限がなく、約1.4秒のShotにも70～90%の大きなArcを要求し得た。
7. Camera品質検査はMotion Type、速度、個数及び足元detailを検査したが、確定Actionとの意味的一致はCamera入力契約だけに依存していた。

## 採用した改善

### 1. LLM入力の責務分離

- Visual BeatとActionにはCamera profileを渡さない。
- ActionにはSong Directionを渡さず、現在Sceneの歌詞、作者本文及びVisual Beatだけで具体対象を認可する。
- CameraにはMotion profileとSong Directionを渡さず、Camera用Direction、Visual Beat、確定Action及び構造roleだけを渡す。
- Shot Layoutだけは全曲の感情・編集arcを必要とするため、抽象化したSong Directionを引き続き使用する。

これにより、ActionがCamera語彙へ引かれる経路と、CameraがMotion profileから別の人物演技を再生成する経路を分離した。

### 2. Scene Cue Card

Visual BeatのTEXTを次の行内形式にした。

```text
感情=...｜対象=...｜接触=...｜現象=...｜身体主導=...｜終端=...
```

対象は現在Sceneの原文歌詞又は作者本文だけが認可する。名詞だけなら`接触=禁止`、外部effectは既定で`現象=外部自律`とする。Pythonは自然文から対象を抽出又は置換せず、LLMが出したCue CardをそのSceneだけへ渡す。

### 3. Song Directionの抽象化

Song Directionは次だけを所有する。

- 感情曲線
- section energy
- 静止と加速
- 編集連続性
- 終盤の状態変化

具体物、固定設備、傷、接触対象、effect又は人物動作は認可しない。これにより、狐火、古傷又は背景設備を全曲motifとしてActionへ漏らす経路を閉じた。

### 4. Arc割当

- 長尺Arc候補を適格な非顔slotの約半数へ変更した。
- 2.5秒未満のShotは任意の長尺Arc候補から除外した。
- 顔遷移に使う隣接Shotも2.5秒未満なら選ばない。
- `anime_emotional_mv`の各通常Camera slotへ`arc_permission=required|forbidden`を付けた。
- 未割当slotがArcを返した場合は`unassigned_arc`として一度だけ品質retryする。
- retry後も品質違反が残る場合は停止せず、既存方針どおり最小違反候補をAS IS採用してログへ残す。

52 Shotと同程度の構成では、構造的Arcの目安は24～29 Shotである。顔固定Cameraや短尺Shotの数によって実値は変動する。

### 5. Camera専用契約

Camera文の所有範囲を次へ限定した。

- MiniMax H3 Motion Type
- 画角とscale
- 開始・終了視点
- camera pathとparallax
- 確定Actionの実行に必要な身体範囲

Cameraは姿勢、手足の動作、接触、歩行、視線変化又は終端silhouetteを新規追加せず、確定Actionを言い換えない。Action自然文及びCamera自然文は従来どおりAS ISでEMDへ渡し、Pythonによる語句置換は行わない。

## 性能への影響

新しいLLM task又は監査呼び出しは追加していない。既存のVisual Beat、Song Direction、Action、Action Audit及びCamera呼び出し数は維持される。ActionとCameraへ渡す共通contextは減るため、入力token数と8Bモデルの指示競合は減少する見込みである。

## 検証

ComfyUIのPython環境で全326件のunit testを実行し、skipなしで成功した。追加した回帰試験は、ActionとCameraのDirection分離、Song Directionの非伝播、約半数のArc割当、2.5秒未満の長尺Arc除外、slot単位の`arc_permission`及び未割当Arcの検出を対象とする。

## 次回生成の評価基準

次のEMDでは以下を比較する。

1. Arc Shotが全Cameraの45～60%に収まる。
2. 2.5秒未満のShotに長尺Arcがない。
3. `arc_permission=forbidden`由来のCamera quality warningが常態化しない。
4. CameraがActionにない手、腰、足、前傾又は接触を追加しない。
5. ActionとCameraの上げる／下げる等の直接矛盾が0件になる。
6. 狐火、苔、花、傷又は固定設備が、その対象を認可したScene外へ漏れない。
7. 同一Action、同一終端pose及び同一Arc経路の反復が減る。
8. 顔Zoomは短いaccentとして残り、両目、両眉、鼻及び完全な歌唱口を同時に保持する。
9. Plannerは品質警告を記録しても、必須record欠落又はprotocol回復失敗以外では停止しない。

## 残る限界

Cue Cardは行指向LLM出力であり、対象の意味をPythonが再判定しない。8BがCue Card自体で過去対象を再利用した場合はVisual Beatのbounded diversity retryと後段Action Auditが検出するが、最終的にはAS IS採用される可能性がある。今回の改修は意味を書き換える機械規則を増やすのではなく、誤った情報を後段へ渡さないことと、有限の構造roleを明示することで発生率を下げる設計である。
