# EMD 00002：御神木シーンの身体演技反復（2026-09-23）

## 対象と結論

- EMD: `C:\Software\ComfyUI\output\mv_director\context_loop_emd_00002.md`
- 同じ生成のPlan: `C:\Software\ComfyUI\output\mv_director\context_loop_plan_00002.txt`
- 映像: `C:\Software\ComfyUI\output\h3_chains\mv_director_context_loop\segments\clip_0006.855b242674754186a1a5ce6925ae6246.mp4`（Scene 6、7.79秒、24 fps、864×480、seed `15405368195017881266`）

**主因はH3だけではない。** Scene 6の確定Actionが「肩を振る・胸郭を左右に動かす・肘を上下する」という小動作を指定し、身体の始点、支持と重心の移行、左右の腕の異なる軌道、感情の転換点、終端姿勢を指定していない。Compiler後のPlanもほぼ同じ意味を英訳してH3へ渡している。H3はその小動作を、両腕を外へ開いて戻す反復として具体化している。したがって、まずPlannerのActionとScene内の演技進行を改善し、同一seedの短区間でH3側の残余を測るべきである。

## 映像・EMD・Planの照合

| 根拠 | 観察 | 判断 |
|---|---|---|
| 映像0–約1秒 | 顔アップで歌唱口と目を見せる。 | 表情の導入はあるが、身体フレーズの始点にはならない。 |
| 映像約1.5–7.5秒 | 全身へ引いた後、人物は概ね同じ地点で立ち、両腕を外へ開き、肘・手を上下させる姿勢へ複数回戻る。御神木に向かう距離、支持脚、骨盤・体幹、片腕ずつの軌道には明瞭な段階差が少ない。 | 画角と背景の移動に対し人物の演技進行が弱い。木は画面右に見えるが、人物との関係は主に視線と背景配置へ委ねられる。 |
| Scene 6 EMD、00:48.375–00:56.167 | 5行の歌詞を単一Shotに収める。確定Actionは「肩を軽く振って胸郭を左右に動かし、目線を遠くへ向け、肘を上下…御神木が風に揺れて葉を鳴らす」。 | 動詞が肩・胸・肘に集中し、約7.8秒の時間内で異なるキーポーズへ進む指示がない。`肘を上下御神木`の連結も日本語として破綻している。 |
| Scene 4・7 EMD | Scene 4も「肩を軽く振って…手を上げ、胸郭を左右」、直後のScene 7も「肩を軽く振って胸郭を左右…肘を上下」。 | Scene 6固有の偶然ではなく、前後Sceneにわたって同系統の身体テンプレートが選ばれている。Scene 6→7は`継続`なのに、変化ではなく同じ運動語彙から再開する。 |
| Scene 6 Plan | `[reference generation]`と`[Shot 1]`は肩、胸、肘の動きをそのまま英語で保持する。`continuation_mode=guide`、`context_length=22`。 | Compilerが豊かな身体フレーズを削った証拠はない。先行映像のガイドはあるが、次の身体状態を進める新しい終端指示はない。 |
| Camera指示と映像 | EMDは速い大振幅の左Arc＋小Roll、`head-and-shoulders`から`medium`を指示する。映像は序盤に顔アップ、その後かなり広い全身構図になる。 | カメラ移動は強い一方、Actionの身体進行とは同期していない。最終画角は指定の`medium`より広く、H3側の構図解釈にもずれがある。 |

映像の時刻は0.5秒間隔の抽出フレームによる概数であり、関節角度の定量計測ではない。PlanにはPlanner内部のCue Card、Scene Spine原文、候補選択結果が保存されないため、それらの個別の成否は断定しない。

## 現行経路で弱くなる理由

1. `anime_emotional_mv`は`performance_mode=dance_phrase`だが、強い`body_phrase_accent`を予約する`body_accent_policy=sparse_chorus`は`CHORUS`/`FINAL_CHORUS`だけを対象にする。Scene 6は`PRE-CHORUS`なので、この経路では選ばれない。単一Shotには通常の`lyric_driven_full_body_performance`が付くが、それだけで支持脚から終端姿勢までの連鎖が保証されるわけではない（`core/planner/engine.py`の`_performance_role`、`_sparse_body_accent_keys`）。
2. Scene 6は単一Shotであり、Scene Spineが走った場合でも準備・アクセント・解放を**別Shotへ**分配できない。Scene Spine自体も、単一Shotかつ外部現象扱いでないCueならスキップされる。御神木の風揺れがどのCue種別として採用されたかは成果物だけでは分からない。
3. 御神木は最後の歌詞行（00:54.120–00:55.500）に現れるが、Shotは00:48.375から始まる。対象の出現と人物の反応をどの秒で転換するかは確定Actionにない。H3は長い一文の単純な運動を全尺へ引き延ばしやすい。
4. モーションプロファイルには「肩や胸を発端へ固定しない」「開腕を反復しない」と書かれている。しかし最終Actionは逆の具体動詞を持つ。H3には一般的な共通指示とShot固有の具体指示が同時に届き、具体的な小動作が実映像の主導権を取っている。Camera側に`Arc Shot`やRollを増やしても、欠けた身体フレーズは作れない。

## 改善順位と反証可能な短区間実験

### P0：Scene 6のActionを一回の身体フレーズにする

単一Shotを維持し、Plannerに「前Sceneの終端姿勢→支持・重心の変化→体幹と左右の腕の異なる軌道→歌詞『御神木は』での視線・表情のアクセント→静かな終端」を**一続き**で書かせる。木への接触や新しい小道具を強制しない。日本語Actionに`肘を上下御神木`のような節の衝突が残る場合は成功と見なさない。まずEMDで始点・転換点・終端が読めるかを判定する。

### P1：PRE-CHORUSの単一Shotにも選択的な身体accentを検討する

P0で8Bがなお小動作へ戻る場合、`sparse_chorus`を一律に広げるのではなく、歌詞・尺・Camera coverageが合うSceneだけ、Scene当たり最大一回の`body_phrase_accent`を試す。現在の監査がこのroleにだけ要求する支持と重心の連鎖を利用する。Scene 6→7で前Sceneの終端から新しい変化に進むこともEMDで検証する。全PRE-CHORUSへの強制は、静かな場面まで同じ踊りにするため避ける。

### P2：同一seedのScene Debug Splitter比較でH3の限界を測る

P0/P1のEMDが実際に変わった後、背景参照、モデル、seed、Camera、尺を固定し、Scene 6だけを再生成する。支持脚と骨盤の変化、片腕ずつの軌道、終端姿勢が映像に現れればPlanner主因という判定を支持する。EMDでは明確なのに同じ開腕へ戻るなら、H3のモーション追従、ガイドフレーム、Camera scaleの影響を次に切り分ける。単なるseed変更はこの因果検証にならない。

## P0–P2実施記録

P0として、開発用`anime_emotional_mv`の長尺・単一Shotに対し、Actionへ「開始時の支持→一回の重心・体幹・左右非対称の腕→感情反応→異なる終端姿勢」を時間順に書く指示を追加した。御神木などの歌詞対象がShot後半にある場合は、冒頭からその接触を完了させない。自然文のPythonによる補修は追加していない。

P1として、同Motion profileに`body_accent_policy=sparse_chorus_prechorus`を設定した。PRE-CHORUSだけで構成され、6秒以上、単一Shot、顔専用CutではないSceneに限定して、一回の`body_phrase_accent`を予約する。接触Cueがある場合はScene spineが接触点を確立したShotだけを許す。Camera側には人物全身又は歌詞対象と身体が同時に見えるcoverageを渡し、顔Zoom候補との競合を除く。通常の`anime_story_mv`は変更していない。検証中に見つかった、歌詞注釈がShot 1だけに付く場合のScene単位PRE-CHORUS判定も共通化した。495件の全テストは通過した。

P2ではGPU上のQwen3-8B-Abliterated Q4_K_M、`n_ctx=16384`、`max_tokens=4096`、seed 1を使用して、元Scene 6の歌詞と約8秒の尺を隔離したPlanner試験を行った。ただしこれは前後Sceneの全履歴と元のDirectionを完全には復元しない**診断用プローブ**であり、元の全編生成との厳密なA/Bではない。8Bは隔離入力を2 Shotへ分割し、別の試行では御神木への接触を選んだ。2 Shotへアクセントを広げた試行ではroleはActionへ届いたが、最終本文は「手を差し出す／上げる」中心で、監査も一度`BODY_ACCENT_MISSING`を返した。顔Cutと接触点のcoverageが競合する例もあり、2 Shot拡張は品質上の確証がないため採用しなかった。

したがって、**新しいActionが改善したという証拠はまだない**。同一seedのH3比較を今行うと、Shot Layout、Cue、Cameraまで変わった影響を身体演技の改善と混同する。新プロファイルで全編Planner→Compilerを実行し、実際のScene 6相当が単一Shotのまま、支持脚・重心・左右の腕・終端の異なるフレーズになったことをEMDとPlanで確認してから、`Scene Debug Splitter`で当該Sceneのみ元映像と同じH3 seed・モデル・背景参照・音声・尺で再生成する。EMD上で改善がなければH3へ進まず、Cueの接触選択とScene Spineの`SHOW`が身体演技を覆っていないかを次の診断対象にする。

この実施記録は成果物の分析とオフラインの8Bプローブに基づく。H3による改善実証はまだ行っていない。既存の未コミット変更は保持し、この作業のコミットは行っていない。
