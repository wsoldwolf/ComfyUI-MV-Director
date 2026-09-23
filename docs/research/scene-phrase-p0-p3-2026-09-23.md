# Scene身体フレーズ P0–P3：実装と品質ゲート

2026-09-23。対象は保存EMDのScene 5（39.167–48.375秒）とScene 9（74.792–84.708秒）。人物の振付をScene全体で一度設計し、対象の出来事とCameraに接続する実験。Pythonは自然文Actionを合成・書換えしない。

## 結論

> 同日の[経路再調査](scene-choreography-architecture-redesign-2026-09-23.md)で解釈を補足した。固定Cue試験と実Planner試験は同条件ではなく、実PlannerではScene Spineの時点ですでに身体演技が弱かった。「良い振付がAction段だけで失われた」とは証明していない。専用promptへ入る対象有無の分岐、Motion本文の直接入力不足、後段の再作文を分けて検証する。

P0–P2の構造実装と試験は完了した。ただし**実Plannerの完成EMDでは身体演技の改善を確認できなかった**。Scene Spine単独の8B応答は改善した一方、前段Cueが別の出来事を選ぶと身体経路がActionに残らない。P3のH3短区間レンダリングは品質ゲートで保留した。GPU使用許可は得ているが、現段階の映像比較では上流原因を切り分けられない。

実験は新Motion profile `anime_scene_phrase_mv`を選んだ時だけ有効にした。既定の`anime_emotional_mv`と付属WFは従来の`body_accent_policy=sparse_chorus_prechorus_verse_contact`を維持する。新profileの本文は既定profileと同一で、metadataだけ異なる。

| 段階 | 対応 | 判定 |
|---|---|---|
| P0 Scene身体経路 | 対象のないSceneにも既存Scene Spineを使い、短い専用system promptと有限SHOW文法を適用。対象を新設せず、身体eventを`whole_body`で見せる | Scene Spine単独では有効 |
| P1 Action・Camera接続 | Sceneあたり最大一つの身体accentをevent又は接触前後へ配る。Cameraの全身scaleと対象coverageを検証し、顔Arcとの矛盾を避ける | 構造契約は通過 |
| P2 低コスト比較 | 固定Scene・seedで8BのScene Spine六応答、実Planner二Scene、全502件の回帰試験 | 単独応答5/6件は構造有効。完成Actionの品質は未達 |
| P3 H3短区間 | 改善したEMDのみを同条件のH3へ渡す | 未実施。前段の品質ゲートで停止 |

## 8B実測

モデルは現在のWFと同じQwen3-8B-Abliterated Q4_K_M。Scene Spine単独試験は本repoのsystem prompt、line grammar、固定歌詞・Shot時刻を使用し、seed 1–3でScene 5と9を各一回生成した。Scene 5の三応答はすべて構造有効で、旧Actionの二Shotが「胸の前で手を重ねる／目を伏せる」だったのに対し、専用prompt後のeventは踏み出し又は支持移動と胸郭の動きを含んだ。Scene 9は二応答が有効、seed 1は同じADVANCEの反復で失格。三応答とも狐火の位置又は移動をEFFECT_TOに記したが、内容の適切さは別問題である。

これは**Cueを固定したScene Spine単独の結果**である。元の中間Cue Cardは保存されていないため、試験用Cueは保存EMDと歌詞から再構成した。原Cueとの一致や実Planner全体での効果は証明しない。[固定fixtureと六応答](../assets/research/scene-phrase-2026-09-23/evidence.json)に入力、出力、モデル及びprompt hashを保存した。

実Plannerを同じ8Bで各Scene一回動かすと、二件とも構造的には完成したが、結果は異なった。Scene 5では前段Visual Beatが比喩「胸の古傷」を可視対象・外部現象に選び、Actionは「胸を左右に傾ける」「手を胸へ触れる」に縮んだ。Scene 9では狐火は残るものの、Actionは「肩を振る／手を上げる」に縮み、対象へ触れる指示まで出た。Cameraに全身画角があっても、身体の変化を記したActionがない。[Scene 5の採用結果](../assets/research/scene-phrase-2026-09-23/plan-scene5/summary.json)、[Scene 9の採用結果](../assets/research/scene-phrase-2026-09-23/plan-scene9/summary.json)を保存した。

実Plannerの短区間試験ではScene時刻を零へ戻し、元の全曲履歴、実Vision fragment及び歌詞音声は再投入していない。Style/Motion/Camera profile本文は使用した。発生率の定量評価ではなく、**段間で身体経路が失われ得る反例**である。

## 原因と次の小改修

Scene Spineの文法だけでは、Visual Beatが選んだ対象eventとActionの記述量の競合を解消できない。比喩的名詞が可視対象へ変わると、その位置・可視展開が短いAction本文を占め、身体経路が消える。狐火では外部現象の軌道が残っても人物は手と肩へ縮む。

次は新しい全曲LLM段階を増やす前に、対象eventとScene Spineの人物身体経路を、Actionへ**別々の責務として同時に渡す**小範囲実験を行う。現在Shotの身体FROM→ADVANCE→TOと対象の一回の出来事が両方Actionに現れるか、実Plannerの採用文で確認する。比喩の物理化は一般的な解釈方針としてLLMに判断させ、語彙辞書やPython自然文修復を増やさない。

次のH3着手条件は、実Planner短区間EMDでScene 5に異なる始点・終点と重心／体幹／両腕の時間順変化、Scene 9に人物動作と独立した狐火軌道、Cameraにその可視区間を同時に確認できること。ここを満たすまで全編又は短区間のH3再生成は行わない。
