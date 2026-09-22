# キャラ振り付け改善案：Scene連鎖・Camera連携の実装前検証

2026-09-22

## 対象と判定

[復旧プロトタイプEMDのレポート](restored-prototype-emd-choreography-2026-09-22.md)にある「キャラ振り付けの改善案」のうち、Shot内の身体連鎖、Scene間終端の引き継ぎ、身体とCameraの連携を対象にした。Qwen3 8B Q4_K_Mで短いSceneをGPU推論し、元歌詞・Shot境界・seedを条件内で固定した。H3生成と全曲Plannerは行っていない。

**判定：本番の新規LLM段階やMotion profile変更はまだ採用しない。** 単純なScene別motion familyやScene Spineの再指示はCue Cardの身体文を写すだけ、身体文を外すと汎用歩行へ戻った。一方、質の高いScene固有の身体briefが入力済みなら8Bはその演技をShotとCameraの見せ方へ比較的忠実に展開できた。欠けているのは主にそのbriefを自動で作る手順であり、既存のActionプロンプトを強めるだけではない。

## 比較結果

| 条件 | 実際の出力と採否 | 証拠 |
| --- | --- | --- |
| Scene Spine既定Cue vs Scene別motion family | Cueの`身体主導`と`終端`をほぼそのまま`ADVANCE/TO`へコピー。familyを渡しても新しい身体経路にならない。採用しない | [12応答](../assets/research/scene-spine-motion-family-2026-09-22/evidence.json) |
| Cueの身体二fieldだけをScene Spine入力から外す | 「社へ歩く」「鳥居の下へ進む」へ縮退。さらにfamilyを与えても歩行と抽象的な決意に戻る。採用しない | [身体fieldなし](../assets/research/scene-spine-cue-without-body-2026-09-22/evidence.json)、[family併用](../assets/research/scene-spine-unlocked-family-2026-09-22/evidence.json) |
| Cueを再掲せず新しい身体段階にする追加指示 | 6応答ともCueの手足・終端の言い直しが残る。採用しない | [再解釈指示](../assets/research/scene-spine-cue-reinterpret-2026-09-22/evidence.json) |
| 実Planner相当の継続／顔／上半身の編集役割を固定 | 18応答中1件は同じ`ADVANCE`反復でScene Spine構造不正。残りもCueコピー又は歩行中心で、Cameraの役割だけでは身体動作が豊かにならない | [編集役割比較](../assets/research/scene-spine-editorial-roles-2026-09-22/evidence.json) |
| Visual BeatのMotion共通文を短縮 | 身体主導は歩行・手をかざす程度。`接触=許可`の過剰付与、歌詞にない「社の鳥居」の創作、Cue項目順の乱れが出た。採用しない | [Cue比較](../assets/research/visual-beat-compact-motion-2026-09-22/evidence.json) |
| 歌詞から8B自身に短い身体briefを書かせる | 6応答ともTAB指定の行形式に従わず、全角読点区切り。内容も胸前の手、目を閉じる、前傾、腰・太ももへの手の定型。形式修復だけでは品質を救えないため後段へ渡さず終了 | [自動brief](../assets/research/generated-performance-brief-gpu-2026-09-22/evidence.json) |
| 人手で書いた短い感情brief＋Camera coverage | 3 seedでScene 11の腕を差し出す動きとScene 12の収まりがつながる。ただし支持・体幹変化は乏しく、手を腰へ戻す定型も残る | [短いbrief](../assets/research/scene-body-chain-brief-camera-gpu-2026-09-22/evidence.json) |
| 人手で支持脚・骨盤／胸郭の遅れ・腕の経路・終端を明示したbrief＋Camera coverage | 3 seedともScene 11の二ShotとScene 12が連続し、支持脚・体幹・腕・顔を保持した。ただし多くは詳しいbriefの言い換えであり、8Bが自発的に振り付けを発明した証拠ではない | [詳細briefと出力](../assets/research/scene-body-chain-strong-brief-gpu-2026-09-22/evidence.json) |

Scene Spine比較のScene 11–12は実歌詞と実EMDのShot長を使用したが、編集役割は保存EMDから再構成した近似であり、元Plannerの内部requestを完全再現したものではない。brief比較は[別の固定fixture](../assets/research/scene-body-chain-2026-09-22/fixture.json)に記録した代理Cueを使用するため、両群の文章品質を直接比較しない。生応答と入力を保存し、元Actionはモデル入力へ含めていない。

## 旧プロトタイプとの差の具体化

旧実装にはScene別の`subject_motion_contract.suggested_motion_family`、Cameraの始点・経路・終点の契約、先行生成した`locked_lyric_action_blueprint`があり、後段Scene LLMのActionをPythonがそのBlueprintで置換・Shotへ配分していた。現行Cue Cardの`身体主導/終端`は上流で一度決まり、Scene SpineとActionがそれを強く踏襲する。Cueを空にするだけでは8Bに演技の設計図が残らない。この二点は、旧・現行の出力差を説明する有力な**実装上の要因**である。ただし過去動画の見え方はH3モデル・seed・入力画像にも左右され、テキスト経路だけを唯一の原因とは断定しない。

Actionの`unrequested_lower_body_primary_action_maximum=0`は一見ダンスを妨げそうだが、現行の`dance_phrase`では下半身主体違反の機械検査から除外され、全身の踏み替えもプロンプト上許されている。ここを緩めるだけでは今回の反復問題は解けない。

## 改善案への対応と次の設計

1. **Shot内の身体連鎖**：Scene Spineと独立Actionの文言追加だけでは不合格。支持・体幹・腕・顔を含む、Scene固有の短い演技設計があれば8Bは展開できると確認した。
2. **前Shot／前Sceneの終端**：Planner v73で、採用済みScene Spineの最終`TO`を次の`CONTINUE` SceneへAS ISで渡す実装済み。今回のオフライン強briefでも、明示された終端から次Sceneへつながることを確認した。実H3効果は未検証。
3. **身体とCameraの連携**：同じShot枠のCamera coverageを渡す経路では顔Shotに見えない脚動作を始めず、全身Shotに支持・体幹を配置できた。ただしそれは詳細briefが存在する場合に限る。
4. **歌詞の具体物**：今回のScene 11–12の身体演技試験とは独立の課題。苔・花・狐火の位置／接触／解放について、今回の結果から新たな成功を主張しない。
5. **次の最小実装候補**：Motion profile内に複数の撮影可能な身体フレーズを定義し、Sceneごとに歌詞・前Scene終端・Camera coverageに合う一つをLLMに選択・具体化させる、**開発用の任意機能**として設計する。単一の全曲共通briefは同じ動作の反復を招くため避ける。最終ActionはLLM出力をAS ISで採用し、Pythonが自然文を置換しない。候補の選択・具体化を8Bが少なくとも二つの異なる歌詞Sceneで安全に行えることをオフラインで確認するまでは、profile既定にも全曲Plannerにも接続しない。

今回の短区間比較では、GPUを使う全編生成へ進めるだけの**自動生成**候補は得られなかった。次に試すべきなのは、Actionへ禁止語を足すことではなく、Scene固有の身体briefをどの情報源から、どの計算費で、安全に得るかという契約である。
