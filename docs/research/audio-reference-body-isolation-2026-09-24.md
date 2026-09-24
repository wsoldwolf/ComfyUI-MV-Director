# Audio参照版：人物演技の上流／下流切り分け（2026-09-24）

## 目的

Audio参照版の完成動画では、苔への接触、花と狐火の情景は成立した一方、人物の全身を使う演技は弱かった。原因を、Plannerが短い演技文しか出さなかった上流側と、H3が演技文を受けても映像化しない下流側に分ける。元動画とEMDの観察は[別レポート](audio-reference-motion-review-2026-09-24.md)を参照する。

## P0：比較入力

- 元EMDを[`baseline.md`](../assets/research/audio-reference-body-isolation-2026-09-24/baseline.md)に保存し、[`body-variant.md`](../assets/research/audio-reference-body-isolation-2026-09-24/body-variant.md)ではScene 3（苔）の2 Shot、Scene 4（花）の3 Shot、Scene 9（狐火）の2 Shotだけに、支持脚・体幹・左右の腕・終端姿勢の進行を追記した。歌詞対象、接触回数、狐火の軌道、カメラ、時刻は変更しない。
- [`validate_experiment.py`](../assets/research/audio-reference-body-isolation-2026-09-24/validate_experiment.py)でEMD差分を7行に限定して検査した。IdentityTranslatorによるCPU構造コンパイルでも全16 Scene・30 Shotを保ち、差分は対象Scene内のShotと先頭Shotを反復する参照生成文のみだった。
- H3の比較では翻訳LLMの揺らぎを混ぜないため、保存済み英語Planから[`build_plan_variant.py`](../assets/research/audio-reference-body-isolation-2026-09-24/build_plan_variant.py)で[`variant-plan.json`](../assets/research/audio-reference-body-isolation-2026-09-24/variant-plan.json)を作った。元の英語Plan、event文、カメラ文、音声参照、モデル、シード、stepsはそのままで、身体演技の英語文だけを追記した。これは実験用Planであり、通常のEMD Compiler出力ではない。
- 元PlanのSHA-256は`3dce5133ab8f42aa12e2762439793fb4ed08863c99ce48689f8d3eeb1035eda9`、比較Planは`06a65f35a849a912c0108c8cc389ddccabd3fd61efaa0dfad9212498a2e79f05`。

## 判定基準

まずScene 9を単独でA/B生成する。二つともScene Debug Splitterで同じScene 9、同じ元動画のseedを使う。元動画のScene 9そのものは前Sceneからの視覚的履歴を持つため、単独版Aの代用にはしない。狐火の旋回が保たれ、人物に支持脚・体幹・両腕の対応が出るかを比較する。身体演技が改善すれば上流演技文の情報量が主因、変わらなければH3での優先度・可視範囲・音声参照との競合を次に疑う。ただし単一seed・単一Sceneでは一般化しない。

## P1：Scene 9単独のH3比較

同じScene 9、音声、seed、Hybrid H3モデル、steps、カメラ文で、各10.833秒を生成した。ComfyUI提出グラフの差はPlan入力と出力名だけで、他のノード入力は一致した。基準入力を同じseedで再生成すると映像フレームが完全一致した（SSIM 1.000）。したがって今回観察した差は、少なくとも同一入力の実行揺らぎではない。

| 条件 | Scene 9のPlan文字数 | 人物と狐火の観察 |
| --- | ---: | --- |
| 基準 | 6,808 | 片腕を上げる姿勢が中心。狐火は人物の周囲を大きく帯状に周回する。 |
| 詳細追記 | 7,464（+656） | 足運び・上半身は変化するが、大きな周回は主に単独の炎へ後退。赤い鳥居の柱が前景に現れるなど構図も大幅に変化。 |
| 短文追記 | 7,119（+311） | 狐火を手で扱い、身体で応答している感触が強い。大きな帯状の周回とは異なるが、ユーザーの連続視聴ではこちらも良い演技と評価された。 |
| 動作文の置換 | 6,869（+61） | 序盤の手・上半身・視線の変化が増え、後半の狐火の大きな周回も残る。連続視聴で人物アクション・狐火表現の双方が前回を上回ると評価された。 |

比較動画は以下に保存した。

- 基準：`C:\Software\ComfyUI\output\h3_chains\audio_ref_body_s9_base_20260924\final\audio_ref_body_s9_base_20260924.mp4`
- 詳細追記：`C:\Software\ComfyUI\output\h3_chains\audio_ref_body_s9_variant_20260924\final\audio_ref_body_s9_variant_20260924.mp4`
- 短文追記：`C:\Software\ComfyUI\output\h3_chains\audio_ref_body_s9_compact_20260924\final\audio_ref_body_s9_compact_20260924.mp4`
- 動作文の置換：`C:\Software\ComfyUI\output\h3_chains\audio_ref_body_s9_replacement_20260924\final\audio_ref_body_s9_replacement_20260924.mp4`
- 基準再生成：`C:\Software\ComfyUI\output\h3_chains\audio_ref_body_s9_base_repeat_20260924\final\audio_ref_body_s9_base_repeat_20260924.mp4`

フレームSSIM Allは基準対詳細追記0.573、対短文追記0.600、対置換0.629。これは画面全体の変化量であり、人物演技や狐火の品質スコアではない。定性的判定は1秒間隔の時系列フレームによる。速度や滑らかさの最終判定には連続再生も必要である。

## チェックポイント：Scene 9動作文の置換

**この区間では明確な改善と判定する。** 当初の「最も有望」という記述は1秒間隔の静止画確認に基づく控えめな判定だった。ユーザーが[置換版の動画](<C:/Software/ComfyUI/output/h3_chains/audio_ref_body_s9_replacement_20260924/final/audio_ref_body_s9_replacement_20260924.mp4>)を連続視聴し、人物アクションと狐火の回転表現の両方が前回を上回ると評価した。動きのつながりを確認できる連続視聴を、この区間の主要な品質判定として採用する。自動SSIMはこの主観的な品質差を示す指標ではない。

- 検証ID：`audio_ref_body_s9_replacement_20260924`。Scene 9のみ、864×480、24 fps、260 frames、10.833333秒。元動画から抽出した同一WF・音声・seed `1945693048366462725`、H3 Hybrid（FL2VAベース＋Ref2VAオーバーレイ）、8 stepsを使用した。基準入力の再生成映像はフレーム完全一致。
- 元Plan：`C:\Software\ComfyUI\output\mv_director\audio_reference_plan_00001.txt`、SHA-256 `3dce5133ab8f42aa12e2762439793fb4ed08863c99ce48689f8d3eeb1035eda9`。再現に用いた元動画は`C:\Software\ComfyUI\output\h3_chains\mv_director_audio_reference\final\t2v_normal_2026-09-24.mp4`。
- [置換Plan](../assets/research/audio-reference-body-isolation-2026-09-24/replacement-scene9-plan.json)のSHA-256：`b8dbadc2b03a0c3f379d9400cc30e92c29e0de7a02fe195d12aaf133931aa302`。[生成動画](<C:/Software/ComfyUI/output/h3_chains/audio_ref_body_s9_replacement_20260924/final/audio_ref_body_s9_replacement_20260924.mp4>)のSHA-256：`d75027fb589ea12e33c5b30c8be47ac3b2e52c59f42abc0fb4f40036fa7e210e`。動画本体はリポジトリへ複製しない。
- 差分は保存済み英語PlanのScene 9の人物動作文だけで、[生成スクリプト](../assets/research/audio-reference-body-isolation-2026-09-24/build_replacement_scene9_plan.py)が元文の一致回数と他Sceneの不変性を検査する。ComfyUI提出グラフの差はPlanと出力名のみ。これは**人手によるPlanレベルの実験**であり、8B PlannerやCompilerの改善を示す成果ではない。

この結果を以後の苔・花の比較で守るべき品質チェックポイントとする。ただしScene 9の単一seedでの成功であり、全編や別アセットでの再現性はまだ判定していない。

### compact版も別の成功系

ユーザーの連続視聴では[短文追記のcompact版](<C:/Software/ComfyUI/output/h3_chains/audio_ref_body_s9_compact_20260924/final/audio_ref_body_s9_compact_20260924.mp4>)も、人物が狐火を扱うように見える点を高く評価した。私の初期判定は狐火の「大きな周回を維持するか」に寄り過ぎており、MVとしての人物とeffectの相互作用・楽しさを取り逃していた。置換版は周回と身体演技の両立、compact版は人物が狐火を扱う感触という**異なる成功**として残す。今後は周回の規模だけで採否を決めず、連続視聴した人間の演技評価を併記する。

compact版は同じScene 9、同じseed・音声・モデル・カメラ・8 stepsで、元Planへの短い身体文追記だけを行った。[compact Plan](../assets/research/audio-reference-body-isolation-2026-09-24/compact-scene9-plan.json)のSHA-256は`ecf950d99af598cf5c1d8dbc99d5d590ce97218b93e4edfe61445d3d98ad3602`、生成動画のSHA-256は`f4e1e92012d5064294c37e28010e247a4ba49a19aeaa768813c2fb77ad42d3c4`。

## 判定と限界

H3は人物動作を全く出せないわけではない。元の短い「片手を上げる」中心の文を、支持脚・体幹・両腕の時間順がある文へ置き換えると、身体と表情が変化し、狐火の大きな周回も維持できた。短文追記も、周回の形は変わるが、人物が狐火を扱う演技として成立した。一方、詳細な追記は効果と構図を強く揺らした。**追記と置換の単純な優劣ではなく、人物とeffectの関係がどの方向へ変わるか**を評価する必要がある。文字数の増加だけが原因とも断定できない。

これは保存済みの英語Planを人手で編集したH3側の比較であり、8B Plannerが同じ身体文を生成できることは示していない。基準の英訳とScene構造は固定しているため、8B、Compiler、H3のどこに残るボトルネックがあるかのうち、**H3には短い身体文を映像化する余地がある**ところまでを確認した。Scene 9の単一seedなので他の歌詞・情景への一般化もしない。今回の実験Planをそのまま本番出力へ採用しない。

## 次の小実験

苔・花のSceneにも、対象・位置・接触回数・カメラを保ったまま、まず同程度の長さで元の手だけの動作文を置き換える。対象の大きさや配置だけで即座に失敗とせず、人物との相互作用、身体演技、連続した画面の説得力を人間が確認する。情景と演技の両立が見えた場合に、8B PlannerがShot本文をその形で生成できるよう、プロンプト上の責務と文量を調整する。大幅なPython合成や全編レンダリングはその後とする。

構文検証は[`validate_experiment.py`](../assets/research/audio-reference-body-isolation-2026-09-24/validate_experiment.py)で7 EMD行・16 Scene・30 Shotを確認し、既存Parser 18件、Compiler 20件も通過した。置換版は保存済み英語Planから[`build_replacement_scene9_plan.py`](../assets/research/audio-reference-body-isolation-2026-09-24/build_replacement_scene9_plan.py)で作った別のPlanレベル実験であり、EMD差分7行の通常Compiler結果ではない。
