# MV Director workflows

基準環境:

- ComfyUI v0.36.0 commit `ee71d5c4993f29086b27fde1629a945ae48425bf`
- Context Loop 0.6.9 commit `9860a063784c8c23b58e00107f2180e0df3c43d9`

## 6本の構成

| 順番 | ファイル | 役割 |
|---|---|---|
| 1 | `01_plan_compiler_context_loop.json` | Context Loop標準リップシンク用のEMDとPlanを生成 |
| 2 | `02_video_context_loop.json` | Source vocal lockとLip-Sync Optionsで動画生成 |
| 3 | `03_plan_compiler_audio_reference.json` | 固定`<Audio 1>`参照用のEMDとPlanを生成 |
| 4 | `04_video_audio_reference.json` | Scene-local vocal sliceを`ref_audio_0`へ渡して動画生成 |
| 5 | `05_plan_compiler_lyrics.json` | 歌詞directive用のEMDとPlanを生成 |
| 6 | `06_video_lyrics.json` | 追加lip-sync経路なしで歌詞promptから動画生成 |

各方式はPlan/Compilerと動画生成を一対一に分離している。前段をQueueするとComfyUI `output/mv_director`へPlan JSON本文を持つ`.txt`が保存される。対応する動画workflowの`Compiled Plan JSON (.txt handoff)`へ、そのファイルを選択又はD&Dする。

## 共通入力

- `image00002.jpg`: `<Picture 1>`用の参照画像
- `short_bgm_millennium_torii.mp3`: 完成動画へ使うfull mix
- `short_bgm_millennium_torii_vocal.mp3`: 整列・口形駆動用vocal stem
- plain lyrics `.txt`（Plan/Compiler WFとAudio Reference動画WF）
- Vision GGUF、Text GGUF、ローカルWhisper `.pt`（Plan/Compiler WFとAudio Reference動画WF）
- MiniMax H3 diffusion model、text encoder、video VAE、audio VAE

同梱検証素材を既定値にしているが、ComfyUIの`input`へ存在しない場合は各Loadノードで選択し直す。Context Loop方式とLyrics方式の動画WFは、コンパイル済みPlanから最終frame尺と歌詞directiveを得るためLyric Segmentationを再実行しない。Audio Reference方式だけは元音声のScene区間をPlan位置へ並べ直すため、Plan/Compiler側と同じ歌詞、vocal、Whisper及びtiming profileでLyric Segmentationを実行し、成功cacheを再利用する。

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
