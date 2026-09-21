# Scene内進行・全身演技・外部effectの改修記録

作成日: 2026-09-22
対象: `dev`、Planner algorithm `mvd-timeline-planner-v64`
判定: 構造・回帰試験は通過。最新の全曲8B推論とH3映像による品質判定は未了。

## 目的と発端

[プロトタイプ比較](japanese2json-prompt-generation-comparison-2026-09-21.md)では、旧版が同じScene内で出来事、時間順の人物動作、対象の変化、Cameraの開始・経路・終点を一緒に設計したのに対し、現行版は短いslotへ分離するため演技と撮影の結び付きが弱いと整理した。今回の改修は旧版全体の移植ではなく、Scene単位の一回の出来事と、撮影に必要な可視範囲を現行契約へ追加するもの。LLMが書いたAction・Cameraの自然文をPythonで創作・置換しないAS IS原則は維持する。

加えて、`anime_emotional_mv`が実際には上半身中心を優先していたこと、2026-09-21生成の狐火Sceneでは歌詞対象が人物の手足の動作へ置き換わり、映像に炎が現れなかったことを個別に追跡した。

## 実装した変更

1. **P0: 比較基準を固定。** Qwen3 8Bの三Scene合成診断を保存し、追加taskを外したseed 2では苔の接触が二Shotで反復し、Cameraにも対象と手の同時可視指定がないことを確認した。比較条件・証跡・限界は[P0〜P2詳細](scene-event-spine-p0-p2-2026-09-21.md)に記録した。
2. **P1: Scene内進行。** 有効なCueを持つ複数Shotの`dance_phrase` Sceneだけ、全Shotを一括で読む短い`scene-spine` taskを追加。各Shotの`PHASE / FROM / ADVANCE / TO / SHOW`をLLMに書かせ、準備→一回のevent→反応をActionとCameraへ共有する。有限文法で行数、順序、event数、接触時の対象＋手のcoverageを制約し、不正なら一回の再要求後に当該Sceneだけ従来経路へ戻してWARNINGを残す。EMDとCompilerの外部形式は変更しない。
3. **P2: Camera coverage。** `lyric_target`、`lyric_target_and_hands`、`face_eyes_mouth`などを既存Camera taskの有限選択へ追加。接触や外部現象の転換を顔だけの寄りで隠す候補を排除する。Camera推論の新段階は増やさない。Plannerの完了ログにはScene進行の採用・スキップ数を含める。
4. **全身演技。** `anime_emotional_mv`のPlanner契約とAction promptにあった「上半身だけで完結する演技を積極的に選ぶ」という誘導を廃止。拍や感情が動くSceneでは、一つ以上の通常Shotで支持脚の踏み替え、膝の弾み又は重心の受け渡しを体幹・腕・表情の軌道へつなげる。顔Shotや静かなSceneへ脚動作を毎回強制せず、H3向け`render_prompt`も全身演技を指定したShotに限定した。人物自身の連続回転や足元接写は要求しない。
5. **外部effectの型と可視展開。** 自動歌詞認識が`effect`と判定した対象を、後段で単なる`automatic`へ潰していた経路を修正。Cue生成文法で`接触=禁止｜現象=外部自律`を保持し、型に反するCueは一回再要求する。Actionへ分類を伝え、Scene進行採用時もCueのLLM原文による現象自身の`可視展開`をevent Shotへ必須転送する。語を列挙する狐火専用辞書やPythonによるAction文の補作は追加していない。Planner cacheのalgorithm versionをv64へ更新した。

## 狐火が消えた実例の証拠

対象は `C:/Software/ComfyUI/output/mv_director-4/context_loop_emd_00001.md` と `E:/OutputCollection/MiniMaxH3 Assets/千年鳥居-v0.1.2/t2v_normal_2026-09-21.mp4`。EMDのScene 9には歌詞「狐火へ問う」があるがActionは「狐火の上へ上がるため、足を踏み出し、前腕を左右に振る」と手首の揺れだけ。Scene 14も「狐火は祈り」に対し「狐火の上部に手を置き、肘を曲げて腕を上げる」だった。Compiler Planでも前者は`To ascend onto the fox fire`、後者は`Foot the hand on top of the fox fire`となり、炎の数、出現、空間軌道、環境への光の結果がH3へ明示されていない。動画の約77秒、82秒、122秒、127秒の診断フレームにも狐火は見えなかった。これは少なくともPlanner→Compilerの指示欠落がある証拠であり、H3だけ又はseedだけを原因とは判定できない。

## 検証と未判定事項

| 対象 | 結果 | 言える範囲 |
|---|---|---|
| P0基準・実8B seed 2 | Planner 53.62秒、30 LLM呼出し、EMD・Compiler完了 | 苔の二重接触と対象＋手coverage不足を確認 |
| P1/P2・実8B seed 2 / 3 | 各50.29秒 / 50.02秒、各32呼出し、6/6 ShotでScene進行採用 | seed 3では苔の準備→一回の接触とcoverageが成立。seed 2はsetup末尾でも触れ、意味上の一回性は未達 |
| v64の型保持・Cue→Action転送 | 430件のunit test成功、1件skip。effect Cueの実GBNFをComfyUI環境のllama.cppが解析 | 構造契約とfake-backend経路の確認。8Bの意味分類や映像出現の保証ではない |
| v64の実8B・H3再生成 | 未実施 | 改修時GPUは約31/32GB使用、稼働率100%。新しいEMD・Plan・短区間動画の効果判定が必要 |

三Scene診断は合成歌詞であり、約6分の全曲やRTX 5060の性能へ外挿しない。プロンプトに元からある参照画像・背景・時刻等の問題も今回の評価対象ではない。狐火の配置を全Scene共通のユーザープロンプトで指定すると、歌詞より前に出現する危険があるため、今回その種の共通指示は追加していない。seed変更は候補の探索には使えるが、場所や出現タイミングの契約にはならない。

## 次の最小検証

1. ComfyUI再起動後、同じ歌詞・参照・モデルでプロンプト生成WFを再実行し、新EMDとPlanを保存する。旧Planへ動画seedだけ変えてもv64は反映されない。
2. 新EMDで狐火SceneのCue由来Actionに、現象自身の出現・軌道・環境への可視結果があり、人物が狐火へ登る・手を置く動作になっていないか確認する。同時に通常Shotの支持脚・重心・体幹・腕がつながる演技の比率を比較する。
3. 上記を満たしたSceneだけをScene Debug Splitterで切り出し、同一H3設定・seedの短区間動画を比較する。P3の別候補Scene 9は[P0〜P2詳細](scene-event-spine-p0-p2-2026-09-21.md)に記録した落葉反復の比較であり、今回の狐火Scene 9とは別のPlanなので混同しない。

アセットの追加・変更はなく、ライセンス更新は不要。コミット時点では実映像の改善を合格判定しない。
