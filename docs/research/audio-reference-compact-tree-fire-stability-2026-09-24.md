# 簡潔な映像仕様の安定性：御神木・狐火（2026-09-24）

## 目的

[苔・花SceneのA/B](audio-reference-compact-visual-spec-ab-2026-09-24.md)では、同一Scene 2 Guideから簡潔版を生成すると、花を手前に置き人物を見上げる構図と意味のある散華が得られ、足元の極端な接写も避けられた。これは一つの区間の成功であり、他の歌詞対象へ外挿できない。特に狐火は既に良い演出が得られているため、簡潔化で見せ場が退行しないことを確認する。

## 比較条件

- 元Planは`C:\Software\ComfyUI\output\mv_director\audio_reference_plan_00001.txt`（SHA-256 `3dce5133ab8f42aa12e2762439793fb4ed08863c99ce48689f8d3eeb1035eda9`）。[比較Plan](../assets/research/audio-reference-body-isolation-2026-09-24/compact-visual-scene6-9-plan.json)は[生成スクリプト](../assets/research/audio-reference-body-isolation-2026-09-24/build_compact_scene6_9_plan.py)で作成し、Scene 6・9の概要・Shot固有文のみ変更した（SHA-256 `02813a3fffb2d53e2af501f8f09ffe2197cc867a2693e00ae412bc4a2fb993c2`）。
- 御神木はScene 5–6、狐火はScene 8–9をそれぞれ連続生成する。両条件で最初のSceneは変更せず、同一映像Guideを生成する。元Plan・seed・音声・人物／背景参照・全域prompt・モデル・H3グラフは同じ。
- Scene 6は6,627→5,795文字、Scene 9は6,808→5,944文字。御神木の紅葉の旋回、狐火の人物周囲の旋回、人物の手・表情、Arc ShotとRollは残し、過度な軌道・構図の逐語指定を縮める。これは手書きPlanによるH3段階の試験であり、8B Plannerの改善を意味しない。
- GPU検証はユーザーの許可を得て実行する。本番profile・Planner・Compilerは変更しない。

## 変更したH3文

元EMDは`C:\Software\ComfyUI\output\mv_director\audio_reference_emd_00001.md`で、**今回はEMDを作り直していない**。下記は保存済み英語Planの局所行を手で置換した正確な文である。元のScene 6のShot文は約1,000文字、Scene 9のShot 2は約805文字で、開始・終端の画角、Arc軌道、視差、Roll角度などを逐語的に指定していた。短縮版では出来事、手と表情、主要Camera motionを残し、軌道の微細な指定を省いた。

```text
Scene 6 [reference generation] <Subject 1> stands on the approach path beside the sacred tree. She raises her hands and briefly closes her eyes as red leaves spiral upward around the tree.
Scene 6 [Shot 1] The sacred tree sways and red leaves spiral above it while <Subject 1> raises her hands, briefly closes her eyes, and responds. Arc Shot with large amplitude at fast speed around her and the tree; blend in Roll Counterclockwise with small amplitude, then level the horizon. Show the tree, leaves, hands, and face together.

Scene 9 [reference generation] Foxfire appears around <Subject 1> on the stone path. She raises her right hand and moves her left at chest height.
Scene 9 [Shot 1] Foxfire appears before <Subject 1> as she raises her right hand and waves her left at chest height. Push In at fast speed; show the fire, both hands, and her singing face.
Scene 9 [Shot 2] At 00:04.958, foxfire circles around her and red light moves with it. She lifts her right hand near her head and lowers her left toward her waist. Arc Shot with large amplitude at fast speed around her and the fire; blend in Roll Counterclockwise with small amplitude, then level the horizon. Keep the fire, hands, and face in view.
```

## 採否の観点

御神木では大樹の存在感、紅葉と人物の身体演技、Arc/Rollの自然さを見る。狐火では周回する外部エフェクト、人物の手との関係、表情とカメラワークを重視する。簡潔版が足元接写を避けても、現在の狐火の魅力を失うなら不採用。逆に狐火が改善しても、御神木や苔・花以外のSceneまで自動適用する根拠にはしない。評価は連続再生を優先し、フレーム一致度は同じGuideで始まったかの検査にだけ使う。

## 結果

### 狐火（Scene 8–9）

前Scene 8は両条件で同一映像Guide（243フレーム、SSIM 1.000）となった。[基準版の狐火Scene](<C:/Software/ComfyUI/output/h3_chains/audio_ref_fire_s8_9_base_20260924/segments/clip_0002.94563a301a484b0a91c72e30509f9686.mp4>)と[簡潔版の狐火Scene](<C:/Software/ComfyUI/output/h3_chains/audio_ref_fire_s8_9_compact_20260924/segments/clip_0002.910212a916ba4f67b68e5d9ce2aef6da.mp4>)を生成した。両方に人物の周囲を回る狐火とArc/Rollが現れ、簡潔化でeffect自体が消える退行はなかった。

ユーザーの映像評価は「簡潔版の方がキャラモーションとカメラワークが良く、総合でも簡潔版が好み」。effectについては一長一短で、基準版は静止に近いCameraにより狐火の旋回を強調し、簡潔版はCameraも旋回するため狐火自体の勢いは落ちて見える、とのこと。したがって「Cameraもeffectも最大速度にすれば良い」という結論にはしない。既存の基準版の狐火の良さも保護すべきであり、対象の旋回を主役にする時間にはCameraを落ち着かせる余地がある。

### 御神木（Scene 5–6）

前Scene 5は両条件で243フレーム一致（SSIM 1.000）。[基準版の御神木Scene](<C:/Software/ComfyUI/output/h3_chains/audio_ref_tree_s5_6_base_20260924/segments/clip_0002.4293b91780604c14809ff17a72b36edc.mp4>)と[簡潔版の御神木Scene](<C:/Software/ComfyUI/output/h3_chains/audio_ref_tree_s5_6_compact_20260924/segments/clip_0002.6d692a4ba3df4f74866ca1c544208b71.mp4>)を生成した。ユーザーの連続視聴評価は「簡潔版が良い」。

一秒間隔のフレーム観察では、基準版は大きな紅葉の木を背景に人物の背面を長く見せ、手を上げた姿勢が続く。簡潔版は正面寄りの人物、両腕、顔と舞う紅葉の同時描写が多く、Cameraの傾きも見える。ユーザーはさらに、簡潔版では「御神木を前に人物が正面を向き、腕を広げると一気に葉が舞う」と、**人物動作をきっかけに環境が変化する時間関係**を高く評価した。木そのものの大きさだけでなく、この動作と結果のつながりが映像の説得力になった。ただし静止フレーム観察は補助的なものであり、連続映像の採否はユーザーの評価を優先した。

## 暫定結論とパイプライン化

同じ前Scene Guide・seed・音声・参照・モデルを保った二対象のA/Bで、ユーザーは狐火と御神木の両方で簡潔版を総合的に選んだ。苔・花での改善とも方向は合う。したがって、H3に渡す文を「対象の可視変化―人物の反応―Cameraの役割」が読める短い仕様へ整える方針は、局所的には有望。ただし狐火の基準版は旋回するeffect自体を強く見せるため、最終設計でCamera motionとeffect motionを常に同時最大化しないこと。二Sceneの結果を全曲・全profileへそのまま外挿しない。

現行のCameraはPlannerが有限選択し、`core/planner/engine.py`の`_render_camera_plan`が長い英文へ展開する。Compilerは`core/compiler/ref2va.py`でScene概要・Action・Cameraを組み立てて英訳Planへ渡す。したがってJSONの事後パッチではなく、profile指定の**簡潔なCamera展開**から段階的に試せる。今回の手作業はScene概要・Actionも短縮しているため、まずCameraだけを変えたオフラインPlan差分と短区間H3を比較し、その後必要ならScene/Event/Action側へ進む。ユーザーがEMDで直接指定した文を無断で短縮せず、既存の長文方式へ戻せる形で実装する。追加LLM段や自由文の正規表現修復は初手にしない。

## 共通の前Scene 5に残る足運びの曖昧さ

ユーザーは、御神木Sceneの前に人物が「歩いているのか足のポーズを変えているのか分からない」と指摘した。これは両条件に共通するScene 5であり、生成された243フレームはSSIM 1.000で一致する。今回の簡潔化によって生じた差ではない。

元EMDのScene 5のShot固有Actionは「右手を軽く触る」「胸を軽く触る」のみ。対象、始点・終点の足位置、移動経路、接地の変化は指定されない。Cameraは全身silhouetteを見せるArcからPush Inへ移るが、Trackingではなく、人物の場所移動も要求していない。一方、全域のMotion render promptには「全身演技を指定されたShotでは、支持脚の踏み替えと重心移動から……」とある。全身が見えるShotで局所Actionに下半身の目的が無い場合、H3が踏み替えを即興で補うことが、この曖昧な映像の有力な説明である。ただしrender prompt単独の因果効果を分離した実験ではない。

対策を試すなら、このSceneだけで「同じ位置で両足を接地し、上半身と表情で歌う」又は「明確な目的地へ二歩移り、そこで止まる」の**どちらか一つを肯定形で指定**し、同じCamera・seed・音声で比較する。足を映さない、全Sceneで歩かない、といった全域禁止にはしない。御神木・狐火の成功した対象Sceneの文も変更しない。
