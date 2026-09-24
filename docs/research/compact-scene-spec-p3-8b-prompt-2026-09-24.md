# 簡潔Scene仕様 P3：8Bのsystem promptだけで演技・Cameraを回復できるか

2026-09-24。[P2](compact-scene-spec-p2-model-boundary-2026-09-24.md)ではEvent対象の変化だけを渡すと、御神木・狐火は残ったが人物の振付とCamera coverageは弱かった。14Bは8GB VRAMの運用条件を満たさず、27Bは速度と今回の行プロトコルの問題から比較対象にしない。本試験は**8Bのみ**で、歌詞・Scene・Event・seedを固定し、system promptの表現と出力行の分担だけを変える。H3動画、本番Planner、EMD及びCompilerは変更しない。

## 固定した入力

Qwen3-8B-Abliterated Q4_K_M、`n_ctx=8192`、temperature 0.2、seed 1・2、Scene 6（御神木、1 Shot）とScene 9（狐火、2 Shot）。[Event-only fixture](../assets/research/audio-reference-body-isolation-2026-09-24/p2-event-only-fixture.json)は保存済みEMDから対象の変化だけを手で抽出したもので、人物姿勢とCameraの答えは含めない。各条件は同じ[研究スクリプト](../assets/research/audio-reference-body-isolation-2026-09-24/probe_p2_scene_spec.py)から1 Sceneにつき1回呼ぶ。既存Actionの再要約ではない。対象歌詞と背景は同一である。

| system prompt／形式 | 8B生出力 | 行形式 | 人物・Cameraの観察 |
| --- | --- | --- | --- |
| `linked`：一つのScene出来事を`SHOT`一文へ | [4件](../assets/research/audio-reference-body-isolation-2026-09-24/p2-linked-event-only-seed1-2.json) | 4/4合格 | 御神木の葉・狐火の旋回は保持。御神木では人物の反応がShotから消え、狐火では静観・微笑む程度。 |
| `body_camera`：一つの`SHOT`文に始点→身体変化→表情→終点、Cameraも要求 | [4件](../assets/research/audio-reference-body-isolation-2026-09-24/p2-8b-body-camera-event-seed1-2.json) | 4/4合格 | 重心、手、目、表情が増えた。しかし4件とも具体的なCameraの動き・画角を記さず、御神木には歩行・足運びが残る。 |
| `separate_roles`：同じ1回の応答を`BODY`と`CAMERA`の別行へ | [4件](../assets/research/audio-reference-body-isolation-2026-09-24/p2-8b-separate-roles-event-seed1-2.json) | 4/4合格 | Camera行は出る。御神木の2件では`BODY`行に人物ではなく**木と葉の運動**を記し、主語を混同。狐火は身体を記すが前傾・足元が再出現。 |
| `performer_camera`：`BODY`を`PERFORMER`へ改称し人物を主語と明示 | [4件](../assets/research/audio-reference-body-isolation-2026-09-24/p2-8b-performer-camera-event-seed1-2.json) | **2/4合格** | 御神木でも人物の姿勢・目線を記せる。ただし余分なShotを作る、素の`Shot`見出しを挟む違反が各1件。狐火には足元・前傾やCameraの物理動作が曖昧な文が残る。 |

採点は形式と映像に必要な情報の有無を分けた。`SCENE|6`のように文としては弱くてもtransport上の形式は合格に数えた。逆に`PERFORMER`の本文が有用でも余分なShotを含めたものは形式不合格である。どの条件もH3映像品質は未評価。`/no_think`の後に閉じたthinkブロックが付く問題は[P1の共通境界修正](compact-visual-spec-pipeline-p1-2026-09-24.md)で除去され、ここでの違反は別種の出力である。

## 結論

**system promptだけでも8Bの出力内容は変わるが、要求した演技・Cameraの同期を安定して得るところまでは達しなかった。** 一文形式ではCameraが落ち、分離形式では`BODY`の主語が対象物へ移り、主語を明示すると形式破綻が増える。これは「8Bには演技文を書く能力がない」という証明ではない。1回の短い推論に、対象変化・人物の時間的身体経路・Camera coverage・正確な行transportを同時に課すと、どこかが脱落するという、この入力条件での観察である。

現時点で付属profileや本番system promptは変更しない。次に進むなら、既存の構造化Scene Eventと人物を別フィールドで渡し、`PERFORMER`の主語を入力側でも明示する。輸送形式には既存の有限slot/grammarの仕組みを使い、自然文の意味はPythonで修復しない。作者の`演出`・`演技`は優先する。先に御神木・狐火で**人物と対象が同時に見えるShot文を安定して得られるか**を判定し、それが満たされるまでH3生成を増やさない。14B/27Bへのモデル大型化を8GB運用の解決策にはしない。
