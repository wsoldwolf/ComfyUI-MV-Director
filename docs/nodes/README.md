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
| [H3 Background Reference](h3-background-reference.md) | 動画生成時に背景画像を環境専用PictureとしてPlanとH3へ束縛する |

## Utilities

| ノード | 役割 |
|---|---|
| [H3 Timing Profile](h3-timing-profile.md) | 固定Context Loop時間契約を共有する |
| [32-bit Seed](seed32.md) | GGUFとH3へ同じ正の32-bit seedを渡す |
| [String Combo](string-combo.md) | 任意の有限文字列候補をcombo化する |
| [Connected Combo](connected-combo.md) | 接続先のcombo候補をサブグラフ外へ引き出す |
| [Load Text File](load-text-file.md) | UTF-8 `.txt`をworkflowへ埋め込んでSTRING化する |

LLMを使うノードの共通調整値は[GGUF共通設定](gguf-settings.md)を参照してください。
