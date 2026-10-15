# MV Director workflows

配布するワークフローは、Context Loop標準リップシンクを使う次の2本です。どちらも最大4Subjectに対応します。

| ファイル | 役割 |
|---|---|
| [01_plan_compiler.json](01_plan_compiler.json) | 参照画像・歌詞・ボーカルからSubject EMD、演出、Scene構成を計画し、EMD・Plan JSON・SRT・LRCを保存 |
| [02_video_generator.json](02_video_generator.json) | 保存済みPlanからH3動画を生成。Plan StudioのALT編集と、生成せず全編を再連結する経路を切り替え可能 |

Audio参照方式と歌詞方式は**保留中**です。旧方式のWF、単独Subject版、モデル別派生WFは同梱・通常再生成の対象外です。内部の方式選択やCompiler機能を廃止したという意味ではありません。再検証事項は[TODO](../docs/tips/TODO.md)で管理します。

## 基本的な使い方

1. 01_を開き、人物・背景の参照画像、歌詞テキスト、ボーカルステムを設定します。歌詞は別途用意したテキストを使えます。
2. 各Image to Subject EMDの`subject_hint`と`additional_instruction`、Enhancerへ渡すユーザープロンプトを作品に合わせて変更します。保存済みの狐耳・尻尾・衣装・小道具や演出候補を、別作品へ残さないでください。
3. 使用しないSubjectは、参照画像ローダーと接続されたImage to Subject EMDの**両方をバイパス**します。例えば二人の場合はSubject 3・4の組をバイパスします。背景ノードは別枠です。
4. Plannerの`lip_sync_target`へ歌唱者を指定します。`サブジェクト1,サブジェクト2`のように複数指定できますが、全員が同じ入力ボーカルを共有します。
5. 01_を実行し、SaveTextの保存先でPlan JSON本文の`.txt`、完成EMD、SRT・LRC本文を確認します。現在の保存先は`output/mv_director/4subject`です。字幕・歌詞ファイルとして使う場合は拡張子を`.srt`・`.lrc`へ変更します。
6. 02_を開き、Planの`.txt`を「Compiled Plan JSON」へ読み込みます。01_と同じ人物・背景画像、同じボーカルステム、およびフルミックスを設定して実行します。

画像とSubjectの対応は固定です。

| 入力 | H3参照 |
|---|---|
| Subject 1 | `<Picture 1>` |
| 背景 | `<Picture 2>` |
| Subject 2 | `<Picture 3>` |
| Subject 3 | `<Picture 4>` |
| Subject 4 | `<Picture 5>` |

EnhancerがSubject入力を統合し、その出力をPlannerへ渡します。Plannerへ追加Subjectを重ねて接続する必要はありません。人物数・順序・ヒントを変更した時は01_から再生成し、EMDのSubject定義を確認してから02_へ渡してください。

演出候補の作成には[歌詞・シーン・キャラクターから演出候補を作るTIPS](../docs/tips/staging-candidate-authoring-prompt.md)を利用できます。

## 生成設定と部分検証

- 言語・VisionモデルはGemma4 31B Q4_K_Sです。Visionには対応mmprojも必要です。[導入手順](../docs/installation.md)を参照してください。
- denoising stepsは動画側のProduction Planの`default_steps`で指定します。保存済み設定は20stepです。Compilerからstep数は出力しません。
- 02_の保存済み解像度は0.9MPです。局所デバッグには0.4MPも使えます。既存Runを継続する場合は解像度などの互換性条件を維持してください。
- Turbo LoRAはバイパスされています。その他の高速化設定や保存済みseed・バイパス状態は、ジェネレーターで通常同期しても維持します。[高速化と安定性](../docs/tips/h3-acceleration-and-stability.md)も参照してください。
- Scene Debug Splitterは通常`enable=false`です。独立した部分検証だけを行う場合に有効にし、連続Scene範囲を指定します。[操作方法](../docs/nodes/scene-debug-splitter.md)を参照してください。

H3 Timing Profileの契約IDは生成時刻・フレーム数の互換性設定で、導入済みContext Loopのバージョンそのものではありません。モデル・音声・参照画像・解像度を変更した結果を、保存済みチェックポイントと無検証で混在させないでください。

## Plan Studioで一つのSceneを差し替える

02_ではProduction Planの後段にPlan Studioを接続しています。JSON入力を使いながら、生成済みSceneのALTを作成できます。

1. 元Runと同じPlan・素材・生成条件を使い、Scene Debug Splitterは無効にします。
2. Studioで対象Sceneの**ALT**を開き、Alternate final-cut takeを有効にしてプロンプト・seedを編集します。
3. 採否を目視確認する場合はReview Gateを有効にしてQueueします。**ALTが有効でなければ通常の生成範囲が実行されます。**
4. ALTはSceneのID・尺を維持し、映像だけを差し替えます。元音声と後続Sceneの継続元チェックポイントは維持されます。次Sceneへ入るblendは0にします。

ALTを採用した後は、同じ02_の切替パネルで`再連結に切替 / REASSEMBLE`を押し、通常のQueueを実行してください。通常生成側がMuteになり、配線済みの再連結パスだけが実行されます。別WFの作成や配線のつなぎ替え、H3での再生成は不要です。生成作業へ戻る時は`通常生成に切替 / GENERATE`を押します。

再連結はALT生成直後のLoop End出力ではなく、保存済みRun全体を読み直し、選択中のALT／Originalを反映します。元の全編Plan・Run名・生成条件・音源を維持し、Scene Debug Splitterは無効にしてください。未生成のSceneが残っている場合は、連続して保存されたSceneまでの部分動画になることがあります。切り替え対象と互換性に関する注意は次項を参照してください。

### 通常生成と再連結の切り替え

02_には二つの`EXECUTION`グループと切替パネルがあります。現在の配置では、通常生成はReview周辺、再連結はPlan Studioの下、切替パネルは入力素材欄の下にあります。通常生成だけを有効にした状態で配布します。

| 操作 | 有効になる経路 | 無効になる経路 |
|---|---|---|
| `通常生成に切替 / GENERATE` | Save Segment・Review・Loop End・通常Assemble | Load Manifest・再連結用Assemble |
| `再連結に切替 / REASSEMBLE` | Load Manifest・再連結用Assemble | Save Segment・Review・Loop End・通常Assemble |

切替後に通常のQueueで実行します。再連結ではSamplerやモデル読込へ依存する生成出力が無効になるため、H3を再推論しません。共通のPlan・音声ノードは残し、Turbo LoRAや未使用Subject等の既存バイパスは変更しません。再連結用ファイル名には`_reassembled`を付け、再連結側のチェックポイント自動削除は無効です。

Fast Groups Muterの`toggleRestriction=always one`でも二つのグループを切り替えられます。ただし新しいフロントエンドには排他制御が効かなくなる報告があり、上流の[rgthree修正PR #770](https://github.com/rgthree/rgthree-comfy/pull/770)で修正されています。ComfyUI v0.40.0という本体バージョンだけでは判定できず、フロントエンドとrgthreeの組み合わせにも依存します。

このためMV Director独自の明示ボタンは、rgthreeとは別のNoteパネルに置き、対象ノードの標準Mute状態を直接切り替えます。rgthreeパネルの右クリックメニューからも同じ切替を利用できます。更新後はComfyUI画面を再読み込みしてください。ボタンが見えない場合は、本体を再起動してブラウザを再読み込みします。

本WFには両経路の出力を含むブラウザ送信を拒否するチェックもあります。rgthreeの表示状態ではなく、実際に送るAPI用グラフを確認します。ただしMV Directorの追加JSが読み込まれている場合の保護であり、外部スクリプトからの直接API送信は対象外です。標準操作で手動切替する場合も、二つの`EXECUTION`グループの片方だけを有効、もう片方をMuteにしてください。入力を通過させるBypassではありません。

外部JSON入力を変更する場合はStudioの表示内容も確認してください。Studioでの通常Plan欄の編集を、接続された外部JSONへ自動保存する機能とは扱いません。元JSON・WFの控えを残して編集してください。

## ジェネレーター

保存済み2本を正本として同期します。入力素材、埋め込み歌詞・Plan、モデル設定、配置、配色、バイパス、Plan Studioを保持し、旧6本やモデル別WFを自動復元しません。外部Context LoopのサンプルWFは通常再生成に不要です。

ブラウザでレイアウトを変更した場合は、対応する`workflows/01_plan_compiler.json`・`workflows/02_video_generator.json`へ保存してください。そのファイル自体が次の生成元になります。ノードとグループの位置・サイズ、画面の表示位置、再連結パネルの配置も保持し、初回追加用の固定配置には戻しません。

```cmd
python tools/generate_workflows.py
```

別フォルダへ同じ2本を出力する場合:

```cmd
python tools/generate_workflows.py --output-dir E:\\ComfyUI\\workflows
```

`--source-dir`で、編集済み2本がある別フォルダを正本に指定できます。両方の読込・検証を終えてから書き込み、欠落や不正な配線を検出した場合は片方だけを更新しません。

`tools/generate_4subject_workflows.py`も同じ2本を扱う互換入口です。旧ファイル名の4subject版を作り直すものではありません。

既存ファイルへの明示的な移行には、`--sync-lyric-outputs`、`--sync-subject-inputs`、`--sync-planner-schema`、`--sync-step-ownership`、`--sync-context-loop-runtime`等を使えます。対象は現在の2ファイル名だけで、欠けているWFや旧方式は復元しません。`--sync-direction-settings`は演出候補を、`--sync-model-runtime`や`--sync-video-acceleration`は該当設定を変更するため、独自設定がある場合は先に控えを保存してください。モデル別派生WFの生成オプションは無効です。

再連結経路がない旧02_へ追加する場合は`python tools/generate_workflows.py --sync-reassembly-path`を使います。素材・モデル・Plan本文を保持して、一度だけ専用経路とグループを追加します。追加済みなら、保存した切替状態や配置をリセットしません。

PlanとVideoを分ける理由や再生成の範囲は[二段階WFのTIPS](../docs/tips/two-stage-workflow.md)を参照してください。
