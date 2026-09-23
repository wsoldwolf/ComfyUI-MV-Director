# ノードマニュアル

![人物参照と背景参照を分離したMV Directorの最小パイプライン](../assets/minimal-pipeline.png)

## Core

| ノード | 役割 |
|---|---|
| [Image to Subject EMD](image-to-subject-emd.md) | 画像の可視事実と付加情報からSubject EMDを作る |
| [Direction Enhancer](direction-enhancer.md) | 全体のスタイル、環境、時間・照明、動作、カメラを決める |
| [Timeline Planner](timeline-planner.md) | 確定済みScene/Shot枠へ人物動作とカメラを展開する |
| [EMD Compiler (Ref2VA)](emd-compiler.md) | EMDをContext Loop用Plan JSONへコンパイルする |

## Input / Audio

| ノード | 役割 |
|---|---|
| [Lyric Segmentation](lyric-segmentation.md) | plain lyricsとvocalからTemplate EMD、SRT、timelineを作る |
| [Audio Pad Pair](audio-pad-pair.md) | full mixとvocalを同じH3 frame尺へPCM無音paddingする |

## Video

| ノード | 役割 |
|---|---|

## Utilities

| ノード | 役割 |
|---|---|
| [H3 Timing Profile](h3-timing-profile.md) | 固定Context Loop時間契約を共有する |
| [32-bit Seed](seed32.md) | GGUFとH3へ同じ正の32-bit seedを渡す |
| [String Combo](string-combo.md) | 任意の有限文字列候補をcombo化する |
| [Connected Combo](connected-combo.md) | 接続先のcombo候補をサブグラフ外へ引き出す |
| [Load Text File](load-text-file.md) | UTF-8 `.txt`をworkflowへ埋め込んでSTRING化する |
| [Scene Debug Splitter](scene-debug-splitter.md) | Planの連続Scene範囲と対応PCMだけを切り出してデバッグする |

LLMを使うノードの共通調整値は[GGUF共通設定](gguf-settings.md)を参照してください。

## 進捗表示

全ノードはComfyUIの進捗バーに開始と正常完了を通知する。Vision、Direction、Lyric Segmentationは完了した処理工程、Timeline Plannerは完了したLLM呼び出し、EMD Compilerは翻訳済みフィールド数も反映する。キャッシュヒットした場合は途中工程を省略するため、表示が開始から完了へ進むことがある。

パーセンテージは残り時間ではない。Plannerのリトライなどで作業数が増えた場合は総数を拡張する。エラーまたはブロックで停止したノードを100%とは表示しない。
