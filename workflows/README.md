# MV Director workflows

基準環境:

- ComfyUI v0.37.2 commit `830232b856045ca2892833212d7771078a13edd5`
- Context Loop 0.7.0 commit `d80304f05ecc2f504e64cbfb636e2a21d4409909`

## Notes
2026/09/20 現在、Context Loop標準リップシンクワークフロー以外は動作検証していませんのでご了承下さい。
上手く動かない・リップシンクしないとバグ報告されても、他の箇所が重要で修正に着手できません。

## 6本の構成

| 順番 | ファイル | 役割 |
|---|---|---|
| 1 | `01_plan_compiler_context_loop.json` | Context Loop標準リップシンク用のEMDとPlanを生成 |
| 2 | `02_video_context_loop.json` | Source vocal lockとLip-Sync Optionsで動画生成 |
| 3 | `03_plan_compiler_audio_reference.json` | 固定`<Audio 1>`参照用のEMDとPlanを生成 |
| 4 | `04_video_audio_reference.json` | Scene-local vocal sliceを`ref_audio_0`へ渡して動画生成 |
| 5 | `05_plan_compiler_lyrics.json` | 歌詞directive用のEMDとPlanを生成 |
| 6 | `06_video_lyrics.json` | 追加lip-sync経路なしで歌詞promptから動画生成 |

三つの動画生成WFは共通して`UNET → LIGHTX2V TurboLoRA → Model Attention Backend → Sigma Shift`のMODEL経路を使い、既存のSigma ShiftをVideo/Audio Shiftとして一段だけ適用する。既定denoising stepsは8とする。

各方式はPlan/Compilerと動画生成を一対一に分離している。前段をQueueするとComfyUI `output/mv_director`へPlan JSON本文を持つ`.txt`が保存される。対応する動画workflowの`Compiled Plan JSON (.txt handoff)`へ、そのファイルを選択又はD&Dする。

この保存境界は、同じPlanを固定したままVideo段階だけを再Queueし、H3の生成結果を比較するために設けている。統合workflowにすると、動画生成、Review、連結又は任意の後段停止によって、Vision、Whisper、Direction、複数のPlanner task及び翻訳の重い処理まで再実行しやすい。二段階化は再開範囲、cache、モデルのVRAM占有及び失敗原因を分離する。どの変更で前段から作り直すべきかは[Plan / Videoを分離する理由](../docs/tips/two-stage-workflow.md)を参照する。

三つの動画生成WFは、`Audio Pad Pair`の直後に`Scene Debug Splitter`を接続済みである。既定の`enable=false`ではPlan JSON、vocal及びfull mixをそのまま後段へ渡す。部分生成時だけ`enable=true`へ切り替え、1ベースの`scene_start`と連続数`scene_length`を指定する。SplitterのPlan出力は`Production Plan`へ、二つのPCM出力は`H3 Audio Tracks`及び使用中のlip-sync経路へ同時に渡るため、映像範囲と音声範囲を個別に配線し直す必要はない。詳細は[Scene Debug Splitter](../docs/nodes/scene-debug-splitter.md)を参照する。

## 共通入力

Plan/Compilerのテキスト推論3ノード（Direction Enhancer・Timeline Planner・EMD Compiler）と人物・背景Visionは、`gemma-4-31b-it-heretic-ara-GGUF/gemma-4-31b-it-heretic-ara.Q4_K_S.gguf`を既定とする。ComfyUIの`models/LLM/GGUF`以下へ配置し、Vision用の`gemma-4-31b-it-heretic-ara.mmproj-f16.gguf`も同じフォルダへ置く。この31B設定は大容量VRAMの開発環境向けであり、旧RTX 5060向け8B設定は配布対象から外している。

| ノード | n_ctx | max_tokens | temperature | n_batch |
| --- | ---: | ---: | ---: | ---: |
| Direction Enhancer（31B検証用） | 24576 | 4096 | 0.2 | 256 |
| Timeline Planner | 24576 | 4096 | 0.2 | 256 |
| EMD Compiler | 16384 | 4096 | 0.0 | 256 |
| 人物・背景Vision | 16384 | 1024 | 0.1 | 512 |

`max_tokens`は要求上限であり、各backendのタスク別予算で調整される。Direction Enhancerは現行実装で1回の応答を最大1024 tokenに制限しているため、UIに4096を指定しても4096 tokenを毎回生成するわけではない。

共通設定は`top_p=0.9`、`repetition_penalty=1.05`、`gpu_layers=-1`、Flash Attention有効、KV cache `q8_0`、`keep_model_loaded=false`。チャット形式は自動（Enhancerでは空欄）でGGUF内のテンプレートを使い、旧`gemma`フォーマッタは強制しない。Planner・Compilerの数値と量子化は既存31B検証に合わせているが、過去の成功映像はUnsloth版Gemma4 31B Q4_K_Sによるものであり、このhereticモデルの同等性を保証しない。Enhancerの31B設定も検証対象である。

設定だけを同期するときは`python tools/generate_workflows.py --sync-model-runtime`を使う。保存済みの動画Plan、レイアウト、配色、非LLMパラメータ及びComfyUIの入力メタデータを保持し、前段3WFのテキスト推論設定とVisionモデル選択を更新する。

Visionは既存MTMD backendで人物・背景それぞれのEMD出力を確認済みで、モデル固有の追加シスプロや自然文修復は導入していない。各ノードの`keep_model_loaded=false`で実行後にモデルを解放する。同一GGUFへの統一は、別ノード間で同じロード済みインスタンスを共有することを意味しない。WhisperとH3本体・TE・VAEは用途が異なるため、引き続き別モデルを使用する。

- `image001_mikofox_ref.jpg`: `<Picture 1>`用の人物リファレンスシート（足袋の拡大を含む）
- `image002_keinai.jpg`: 前段では背景Visionから場所・空間構成、建築、植生、時刻、天候及び環境照明をDirectionへ渡し、動画生成時には`<Picture 2>`の環境専用参照としてH3へ渡す
- `bgm_millennium_torii.mp3`: 完成動画へ使うfull mix
- `bgm_millennium_torii_vocal.mp3`: 整列・口形駆動用vocal stem
- `bgm_millennium_torii_lyrics.txt`: plain lyrics（Plan/Compiler WFとAudio Reference動画WF）
- Vision GGUF、Text GGUF、ローカルWhisper `.pt`（Plan/Compiler WFとAudio Reference動画WF）
- MiniMax H3 FL2VA（base）及びRef2VA（overlay）diffusion model、text encoder、video VAE、audio VAE、Turbo LoRA
- [ComfyUI_MinimaxH3HybridLoader](https://github.com/scottmudge/ComfyUI_MinimaxH3HybridLoader)カスタムノード

動画WFは`MiniMaxH3HybridLoader`でFL2VAをベースにRef2VAのAdaLN block 25–49を重ね、その出力にTurbo LoRAを適用する。モデル、カスタムノードの導入手順、取得元及びSHA-256は[導入マニュアル](../docs/installation.md#動画workflowの既定h3-hybrid-loader)を参照する。

同梱検証素材を既定値にしているが、ComfyUIの`input`へ存在しない場合は各Loadノードで選択し直す。Context Loop方式とLyrics方式の動画WFは、コンパイル済みPlanから最終frame尺と歌詞directiveを得るためLyric Segmentationを再実行しない。Audio Reference方式だけは元音声のScene区間をPlan位置へ並べ直すため、Plan/Compiler側と同じ歌詞、vocal、Whisper及びtiming profileでLyric Segmentationを実行し、成功cacheを再利用する。

同梱検証素材はソースコードのGPLとは別に`CC BY-NC 4.0`で提供する。対象ファイル、出自及び適用範囲は[`ASSET_LICENSES.md`](../ASSET_LICENSES.md)を参照する。

人物Visionは`subject_only / person`で`emd_fragment`へ`# サブジェクト`を生成し、背景Visionは`scene_only / location / picture_reference_mode=manual / picture_index=2`で同じ`emd_fragment`へ`# シーン設定`だけを決定的に生成する。Direction Enhancerの`concept_emd`には人物Vision、`scene_emd`には背景Visionの`emd_fragment`を接続し、Plannerにも同じ断片を接続する。`observations_json`はdebug出力であり、Direction Enhancerへは接続しない。人物と背景を分ける理由と運用上の注意は[TIPS](../docs/tips/separate-subject-and-background-references.md)を参照する。

Plannerは`scene_emd`を完成EMDへAS ISで統合し、Compilerが`<Picture 2>`の環境専用定義、保持契約及びrequired referenceをPlanへ生成する。動画生成WFは同じ背景画像を`ref_images.ref_image_1`へ直接渡す。人物`<Picture 1>`と環境`<Picture 2>`を独立条件にすることで背景の再現率を高める。Picture 2は建築、植生、地形、材質及び空間同一性だけを部分保持し、人物、pose、文字、分割構図、camera angle及び照明はコピーしない。ユーザーがDirection又は共通プロンプトで指定した環境、時刻及び照明を背景画像より優先する。これは画素単位の背景複製を保証しない。

Plan/Compiler workflowのDirection EnhancerはStyleとCameraを`anime_emotional_mv`、Motionを`anime_scene_composed_mv`とする。`anime_story_mv`は比較又は手動選択用profileとして残す。

三つのPlan/Compiler workflowには空欄可の「ユーザープロンプト」を置き、Direction Enhancerの`user_request`へ接続している。ここは自由文の全Scene共通方針用であり、Sceneごとの局所演出を予約する欄ではない。`direction_emd_passthrough`は厳格なEMD構文を要求し、選択中のprofileとも整合させる別の入力なので、この自由文ノードは接続しない。

## 方式ごとの音声経路

### Context Loop

`MiniMaxH3AudioTracks`へfull mixとvocalを分離して渡す。`MiniMaxH3LipSyncOptions`はvocalを受け、optionsをGeneration Profileへ、同じvoiceをChain Contextへ渡す。Generation Profileは`Lip-sync to source audio`で、最終動画にはsource full mixを使用する。Audio Pad PairはCompilerと同じPlan JSONから最終delivered frame尺を取得するため、Plain Lyrics、Whisper及びLyric Segmentationは動画WFに置かない。

これはContext Loop標準方式であり、現在の推奨構成である。VRAM 8 GB向けの代替を目的とした検証は行わない。

### Audio Reference

Audio Pad Pairは`reference_alignment=source_scenes_to_plan`で、元vocalの各source SceneをPlan delivered-frame位置へ配置し、量子化余剰だけをPCM無音にする。整列済みtrackはComfyUI標準`Trim Audio Duration`でCurrent Sceneの`audio_start`と`audio_duration`へ切り出し、stock `MiniMaxH3ReferenceToVideo.ref_audios.ref_audio_0`へ渡す。

Compilerが出す`<Audio 1>`を変更せず、Context Loop Lip-Sync Optionsを読み込まない。Generation Profileは`Use source soundtrack only`とし、最終動画には別経路のfull mixを使用する。

### Lyrics

CompilerがShotへ展開した歌詞directiveだけで口形を誘導する。`MiniMaxH3LipSyncOptions`と`ref_audio_0`は接続せず、動画WFではLyric Segmentationも再実行しない。Generation Profileは`Use source soundtrack only`で、最終動画にはfull mixを使用する。これは音素単位の完全同期を保証する方式ではない。

## SRT

Lyric SegmentationのSRT本文は前段workflowで同じcanonical segment列から生成する。ComfyUI標準Save Textは`.srt`拡張子を持たないため、workflowではUTF-8 `.txt`として保存する。外部利用時は内容を変更せず拡張子だけ`.srt`へ変更する。

## 再生成

Context Loop 0.7.0のLoop Trim入力定義へ移行する場合は、
`python tools/generate_workflows.py --sync-context-loop-runtime`を実行します。
旧`retain_overlap_frames`を除去し、MVの音画同期を維持する
`audio_trim_mode=sync_with_video`を設定します。動画3WFの保存済みPlan、
素材、seed及びレイアウトは保持します。更新後はWFを開き直してください。

現在のTiming contractだけを6本へ同期する場合は、次を使います。素材、seed、
保存済みPlan、配線、レイアウト及び配色を保持し、H3 Timing Profileの既定値、
contract表記とgeneration fingerprintを更新します。旧0.6.9契約はノードで選択可能です。

```cmd
python tools/generate_workflows.py --sync-timing-contract
```

Plannerの`staging_candidate_policy`は通常`optional`です。Scene Author経路で
歌詞に適合する演出候補を優先して検討させる局所試験では`prefer_matched`を選べます。
全Sceneに候補を強制する設定ではありません。既存のレイアウトや入力を保ったまま
このUI項目だけを追加するには`python tools/generate_workflows.py --sync-candidate-policy`
を実行します。既存の選択値は保持します。

現在の31B検証用前段WFは、StyleとCameraが`anime_emotional_mv`、Motionが
`anime_scene_composed_mv`です。Event→人物演技→CameraのScene Author経路を使い、
既存の題材・身体演技候補に短い歌唱顔接写の候補を1件追加しています。
顔接写の候補は任意であり、全Sceneへの強制指示ではありません。
手動検証ではComfyUIを再起動して01を開き直し、新しいEMD・Planを生成してから
02のPlan入力へ渡してください。02に保存済みのPlanは自動で差し替えません。

レイアウト・配色・動画Planを維持して、前段3WFのMotionとユーザープロンプトだけを
現在のジェネレーター既定値へ同期する場合は次を使います。このコマンドは
前段WFのユーザープロンプトを置き換えるため、独自入力は先に保存してください。

```cmd
python tools/generate_workflows.py --sync-direction-settings
```

6本は次で決定論的に再生成できる。

```cmd
python tools/generate_workflows.py
```

動画workflowの再帰sampling、checkpoint、review及びassembly部分は、固定したContext Loop checkoutの`Ref2V Basic - MiniMax H3 0.6.json`を基礎にする。

## 31B専用構成への移行

Plannerは全profileでScene Authorを使用する。`scenes_per_batch`は廃止した。
既存の前段3WFへschema変更だけを適用するには次を使う。

```cmd
python tools/generate_workflows.py --sync-planner-schema
```

配置・配色・素材・seed・ユーザープロンプトを保持し、廃止widgetだけを除去する。
動画3WFとその保存Planは変更しない。旧widgetを外部配線している場合は手動移行が必要。
ComfyUI再起動後に更新WFを開き直す。profileとcacheの変更は
[移行ガイド](../docs/implementation/gemma31b-migration.md)を参照する。
