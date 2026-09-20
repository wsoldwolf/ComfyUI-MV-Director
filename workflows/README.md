# MV Director workflows

基準環境:

- ComfyUI v0.36.0 commit `ee71d5c4993f29086b27fde1629a945ae48425bf`
- Context Loop 0.6.9 commit `9860a063784c8c23b58e00107f2180e0df3c43d9`

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

- `image001_mikofox.jpg`: `<Picture 1>`用の人物参照画像
- `image002_keinai.jpg`: 前段では背景Visionから場所・空間構成、建築、植生、時刻、天候及び環境照明をDirectionへ渡し、動画生成時には`<Picture 2>`の環境専用参照としてH3へ渡す
- `bgm_millennium_torii.mp3`: 完成動画へ使うfull mix
- `bgm_millennium_torii_vocal.mp3`: 整列・口形駆動用vocal stem
- `bgm_millennium_torii_lyrics.txt`: plain lyrics（Plan/Compiler WFとAudio Reference動画WF）
- Vision GGUF、Text GGUF、ローカルWhisper `.pt`（Plan/Compiler WFとAudio Reference動画WF）
- MiniMax H3 FL2VA diffusion model、text encoder、video VAE、audio VAE、Turbo LoRA

本プロジェクトでは、キャラクターモーションとカメラワークの検証結果から、現時点の動画生成既定モデルとしてFL2VAを推奨する。各ファイルの取得元、配置先及びSHA-256は[導入マニュアル](../docs/installation.md#02_video_context_loopjsonの既定h3モデル)を参照する。

同梱検証素材を既定値にしているが、ComfyUIの`input`へ存在しない場合は各Loadノードで選択し直す。Context Loop方式とLyrics方式の動画WFは、コンパイル済みPlanから最終frame尺と歌詞directiveを得るためLyric Segmentationを再実行しない。Audio Reference方式だけは元音声のScene区間をPlan位置へ並べ直すため、Plan/Compiler側と同じ歌詞、vocal、Whisper及びtiming profileでLyric Segmentationを実行し、成功cacheを再利用する。

同梱検証素材はソースコードのGPLとは別に`CC BY-NC 4.0`で提供する。対象ファイル、出自及び適用範囲は[`ASSET_LICENSES.md`](../ASSET_LICENSES.md)を参照する。

人物Visionは`subject_only / person`で`emd_fragment`へ`# サブジェクト`を生成し、背景Visionは`scene_only / location / picture_reference_mode=manual / picture_index=2`で同じ`emd_fragment`へ`# シーン設定`だけを決定的に生成する。Direction Enhancerの`concept_emd`には人物Vision、`scene_emd`には背景Visionの`emd_fragment`を接続し、Plannerにも同じ断片を接続する。`observations_json`はdebug出力であり、Direction Enhancerへは接続しない。人物と背景を分ける理由と運用上の注意は[TIPS](../docs/tips/separate-subject-and-background-references.md)を参照する。

Plannerは`scene_emd`を完成EMDへAS ISで統合し、Compilerが`<Picture 2>`の環境専用定義、保持契約及びrequired referenceをPlanへ生成する。動画生成WFは同じ背景画像を`ref_images.ref_image_1`へ直接渡す。人物`<Picture 1>`と環境`<Picture 2>`を独立条件にすることで背景の再現率を高める。Picture 2は建築、植生、地形、材質及び空間同一性だけを部分保持し、人物、pose、文字、分割構図、camera angle及び照明はコピーしない。ユーザーがDirection又は共通プロンプトで指定した環境、時刻及び照明を背景画像より優先する。これは画素単位の背景複製を保証しない。

Plan/Compiler workflowのDirection EnhancerはStyle、Motion及びCameraの三項とも`anime_emotional_mv`を既定値とする。`anime_story_mv`は比較又は手動選択用profileとして残す。

## 方式ごとの音声経路

### Context Loop

`MiniMaxH3AudioTracks`へfull mixとvocalを分離して渡す。`MiniMaxH3LipSyncOptions`はvocalを受け、optionsをGeneration Profileへ、同じvoiceをChain Contextへ渡す。Generation Profileは`Lip-sync to source audio`で、最終動画にはsource full mixを使用する。Audio Pad PairはCompilerと同じPlan JSONから最終delivered frame尺を取得するため、Plain Lyrics、Whisper及びLyric Segmentationは動画WFに置かない。

これはContext Loop標準方式であり、8GB VRAM環境でモデル初期化停止が起きるかを他方式と分離して検証する。

### Audio Reference

Audio Pad Pairは`reference_alignment=source_scenes_to_plan`で、元vocalの各source SceneをPlan delivered-frame位置へ配置し、量子化余剰だけをPCM無音にする。整列済みtrackはComfyUI標準`Trim Audio Duration`でCurrent Sceneの`audio_start`と`audio_duration`へ切り出し、stock `MiniMaxH3ReferenceToVideo.ref_audios.ref_audio_0`へ渡す。

Compilerが出す`<Audio 1>`を変更せず、Context Loop Lip-Sync Optionsを読み込まない。Generation Profileは`Use source soundtrack only`とし、最終動画には別経路のfull mixを使用する。

### Lyrics

CompilerがShotへ展開した歌詞directiveだけで口形を誘導する。`MiniMaxH3LipSyncOptions`と`ref_audio_0`は接続せず、動画WFではLyric Segmentationも再実行しない。Generation Profileは`Use source soundtrack only`で、最終動画にはfull mixを使用する。これは音素単位の完全同期を保証する方式ではない。

## SRT

Lyric SegmentationのSRT本文は前段workflowで同じcanonical segment列から生成する。ComfyUI標準Save Textは`.srt`拡張子を持たないため、workflowではUTF-8 `.txt`として保存する。外部利用時は内容を変更せず拡張子だけ`.srt`へ変更する。

## 再生成

6本は次で決定論的に再生成できる。

```powershell
python tools/generate_workflows.py
```

動画workflowの再帰sampling、checkpoint、review及びassembly部分は、固定したContext Loop checkoutの`Ref2V Basic - MiniMax H3 0.6.json`を基礎にする。
