# 明示モーション合成：実装と短区間8B検証

2026-09-23。ユーザーの合成許可に基づくAS ISの限定的例外。
同日の[全編EMD評価と次の計画](scene-composition-full-sequence-review-2026-09-23.md)で、
単独Scene試験では確認できなかった演技の持ち越しと補完の累積が判明した。
以下は短区間試験時点の結果であり、全編での自然さを保証するものではない。
考察と使用例は[TIPS](../tips/mechanical-motion-and-perceived-performance.md)、
開発過程の教訓は[別TIPS](../tips/prototype-discovery-and-reproducibility.md)へ記載した。

## 実装

- [補完選択](../../core/planner/motion_composition.py)：明示候補だけをScene番号で巡回し、一Scene一Shotへ追加。
- [入力解析](../../core/emd/motion_templates.py)：ユーザーとprofileで同じ `# モーション補完` 文法を使用。
- [開発profile](../../profiles/motion/anime_scene_composed_mv.md)：旧三文を外部ファイルへ置く。語彙をコードへハードコードしない。
- `# 演出候補` は従来どおりLLMの任意選択。補完sectionとは混同しない。
- 手書きの演技・一般Shot本文を保護。ユーザー共通Motionはprofile補完より優先。
- `PlannerContent.actions` にはLLM原文、`motion_compositions` には出所と補完全文を別保存。
- 演技担当へ補完予定を先に渡し、Cameraへ合成後の全文を渡す。全曲共通promptに補完一覧は入れない。
- EMDでは別々の演技行と出所注釈。Compilerは本文だけを翻訳・出力し、注釈を映像promptへ渡さない。
- Direction artifactはV4へ更新。V3の互換読み替えはせず、Enhancerを再実行する。
- 既存profile・WFの既定選択、Compilerの演出非生成は変更しない。

Scene番号による選択は意味判断ではない。4秒以上という適格条件も、自然さが実証された閾値ではなく、
短いShotへ全身フレーズを過密に入れないための初期設計である。
Camera固定Shotは対象外。複数人物も今回は対象外。

## 実8B試験

保存済みScene 5・9をローカルScene 1へリベースし、同じprofileで合成off/onを比較した。
そのため、今回の各on試験で選ばれるのは三候補のうち第1候補であり、第2・第3候補の映像効果は未試験。
歌詞・時刻・Concept・Style・Camera設定は対ごとに共通。
Qwen3-8B-Abliterated Q4_K_M、n_ctx=16384、max_tokens=3072、temperature=0.2、top_p=0.9、
repeat_penalty=1.05、GPU=-1、KV=q8_0、n_batch=512。動画生成・追加監査は実行しない。

最初の4試験はbase seed=2だが、通常backendはpayloadから実効seedを導く。
合成payloadの違いがseedにも影響するため、これは探索結果として保存した。
次に全呼出しの実効seed=2を固定して4試験を再実行した。
計8試験、各Event・Performance・Camera一回ずつで **24呼出し、全8試験が形式上完了**。

実効seed固定の比較：

| Scene | off | on | 評価 |
|---|---|---|---|
| 5 | 胸・顔横の手、軽い後傾と視線 | Shot 1本文は「身体は静止」、補完は斜め前方移動。Shot 2本文は大きい移動を反復 | 意味競合と反復が残る。不合格を隠していない |
| 9 | 前後に足を開いたポーズから腕を上げ、軽く踏み出す | 前傾して歩き出し、次Shotも足を前進させ腕・体幹を動かす | 全身移動は強まるが、豊かな振付・自然な映像を実証したわけではない |

Cameraもonでは合成後の全文を受け取り、Scene 5にTruck/Arc、Scene 9にArc/Zoom Outを返した。
ただしCameraに届いたことと、映像上で同期していることは別の判定である。
Scene 5 onの静止競合は残したまま記録し、Pythonで削除・意味修復していない。

証跡：

- [Scene 5 off](../assets/research/motion-composition-2026-09-23/fixed-seed/scene5-off/summary.json) /
  [on](../assets/research/motion-composition-2026-09-23/fixed-seed/scene5-on/summary.json) /
  [on EMD](../assets/research/motion-composition-2026-09-23/fixed-seed/scene5-on/planned.md)
- [Scene 9 off](../assets/research/motion-composition-2026-09-23/fixed-seed/scene9-off/summary.json) /
  [on](../assets/research/motion-composition-2026-09-23/fixed-seed/scene9-on/summary.json) /
  [on EMD](../assets/research/motion-composition-2026-09-23/fixed-seed/scene9-on/planned.md)
- 初回探索は同じ証跡directory直下の `scene5-off/on`、`scene9-off/on` に保存。
  初回Scene 5 offではエスケープされたprotocol行の本文混入も発生した。これは合成の成功として数えない。

今回の比較は合成文の出力だけでなく、それを演技LLMへ通知する入力も変わる。
固定したLLM原文に対する「補完有無だけ」のH3因果比較ではない。
profileの既定昇格、全編生成、旧版より自然という結論は行わない。

## 検証と次の判断

CPU回帰 **541件すべて成功、skipなし**。
新規11件は構文分離、継承／無効／上書き、profile非漏洩、原文保持、
Camera伝達、cache往復、Compiler非漏洩、作者保護、短尺除外、
巡回、共通Motion優先、再入力時の二重合成防止を確認する。

GPU試験は完了しモデルを解放した。ユーザーのComfyUIは起動・停止していない。
既存未コミット変更は保持し、今回もコミット・リリースは行っていない。

次は意味競合があるScene 5をそのまま全編レンダリングせず、
補完をShot終盤の動作として扱う等の**時間上の合成契約**を小さく比較するのが妥当。
静止を検出して勝手に削るのではなく、原演技と補完の順序を明示する。
身体移動の確実な伝達はできたが、その自然さは未達・未検証のまま区別する。
