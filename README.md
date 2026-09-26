# ComfyUI-MV-Director

[![【MV】千里の秋を駆ける - MiniMax H3+Context Loop+MV Director Demo](https://img.youtube.com/vi/OLffZGlcZOs/maxresdefault.jpg)](https://youtu.be/OLffZGlcZOs)
※本作品は東方Projectの二次創作であり、公式作品ではありません。

人物・背景の参照画像、歌詞、ボーカルステム、フルミックスから、MiniMax H3 / Context Loop用のMV計画を作るComfyUIカスタムノードです。現行の開発workflowはGemma4 31Bで画像認識、演出方針、Sceneごとの出来事・人物演技・カメラ、英訳を処理し、編集可能なEMDと再利用可能なPlan JSONを保存します。動画生成にはFL2VAをベースにRef2VAの参照レイヤーを重ねるHybrid Loaderを使用します。

EMDは **Easy MarkDown** の略です。Extended Markdownではありません。

![人物参照と背景参照を分離し、Plan Compiler段階と動画生成段階の間に再利用可能なPlan JSON保存境界を置くプロジェクト概要](docs/assets/minimal-pipeline.png)

## はじめに

1. [導入マニュアル](docs/installation.md)に従ってカスタムノード、`llama-cpp-python`、Whisper、各モデルを準備します。
2. [配布workflow](workflows/README.md)のPlan / CompilerとVideoを一組で使います。現在の検証はContext Loop標準リップシンク方式を中心に行っています。Audio参照方式と歌詞方式もありますが、同等の同期精度は保証しません。
3. [ノードマニュアル](docs/nodes/README.md)で各入力、出力、既定値、接続方法を確認します。
4. EMDを直接編集する場合は[EMD仕様書](docs/spec/emd-spec.md)を参照します。

現行の開発構成は`dev`ブランチです。既存のリリースタグとはモデル・パイプラインが異なります。基準環境はComfyUI v0.37.2 commit `830232b856045ca2892833212d7771078a13edd5`、Context Loop 0.7.0 commit `d80304f05ecc2f504e64cbfb636e2a21d4409909`です。

Gemma4 31B構成はRTX 5090環境で検証しています。VRAM 8 GB環境は現在の対象外です。必要なVRAM・メインメモリは量子化、context、オフロード設定で変わるため、未検証環境の最低容量は断定していません。

`# 共通プロンプト`は全体方針、`# 演出候補`は歌詞に応じた局所演出として記述できます。候補は全Sceneへ一律に適用されません。人物の再現性、演技、リップシンクなどの最終的な採否は、生成映像を見て判断してください。

LLMの出力は確率的で、行protocol違反や必須出力の欠落が起きる場合があります。構造検証と有限回の再試行を行いますが、必ず成功することは保証しません。再試行時のseed・cacheの扱いは[トラブルシューティング](docs/troubleshooting.md#llmの行protocol不整合が発生する)を参照してください。

## 簡単な利用方法

1. `01_plan_compiler_context_loop.json`をComfyUIで開き、参照画像・歌詞・音源を設定して実行します。Plan JSONは、ComfyUIの`output/mv_director`以下へ`.txt`形式で保存されます。
2. `02_video_context_loop.json`を開き、保存した`.txt`を「Compiled Plan JSON (.txt handoff)」へ読み込みます。01と同じ参照画像・音源を指定し、実行すると動画を生成します。

同じPlanで動画を再生成する場合は、02だけを再実行できます。歌詞や演出方針を変更した場合は、01でPlanを作り直し、02へ読み込み直してください。

## 文書索引

| 場所 | 内容 |
|---|---|
| [`docs/`](docs/README.md) | 利用者向け・開発者向け文書の総合索引 |
| [`docs/tips/`](docs/tips/README.md) | 参照画像の分離、再現率、配線など実運用のTIPS |
| [`docs/nodes/`](docs/nodes/README.md) | 公開12ノードの操作マニュアル |
| [`docs/spec/`](docs/spec/README.md) | EMD、protocol、最小コアの規範仕様 |
| [`docs/implementation/`](docs/implementation/README.md) | 内部構造、公開surface、実装順序 |
| 研究記録（リポジトリ外） | 実験ログ・調査レポートはローカルの`ComfyUI-MV-Director-research`へ保存。配布リポジトリには含めない |
| [`docs/assets/`](docs/assets/README.md) | READMEや文書で使うPNG/SVG図版 |
| [`profiles/`](profiles/README.md) | ユーザー拡張可能なStyle、Motion、Camera profile EMD |
| [Direction / Planner処理フロー](docs/architecture/direction-planner-flow.md) | LLM task、Python所有処理、AS IS境界の図解 |
| [`workflows/`](workflows/README.md) | 三つのリップシンク方式に対応する6 workflow |

## 公開ノード

| 区分 | ノード | マニュアル |
|---|---|---|
| Core | Image to Subject EMD | [画像からSubject EMDを作る](docs/nodes/image-to-subject-emd.md) |
| Core | Direction Enhancer | [全体演出を作る](docs/nodes/direction-enhancer.md) |
| Core | Timeline Planner | [歌詞と時間枠へShotを計画する](docs/nodes/timeline-planner.md) |
| Core | EMD Compiler (Ref2VA) | [EMDをPlan JSONへ変換する](docs/nodes/emd-compiler.md) |
| Input | Lyric Segmentation | [歌詞、SRT、timelineを整列する](docs/nodes/lyric-segmentation.md) |
| Audio | Audio Pad Pair | [full mixとvocalをPCM無音で整える](docs/nodes/audio-pad-pair.md) |
| Utilities | H3 Timing Profile | [H3時間契約を共有する](docs/nodes/h3-timing-profile.md) |
| Utilities | 32-bit Seed | [再現可能なseedを分岐する](docs/nodes/seed32.md) |
| Utilities | String Combo | [有限文字列リストを選ぶ](docs/nodes/string-combo.md) |
| Utilities | Connected Combo | [サブグラフ内comboを外へ出す](docs/nodes/connected-combo.md) |
| Utilities | Load Text File | [UTF-8 lyricsファイルを読む](docs/nodes/load-text-file.md) |
| Utilities | Scene Debug Splitter | [PlanとPCMを連続Scene範囲へ切り出す](docs/nodes/scene-debug-splitter.md) |

ノードIDは`MVDirector...`、表示カテゴリは`MV Director/...`、内部socket型は`MV_DIRECTOR_...`です。旧プロトタイプとの互換aliasは登録しません。

## 更新履歴（主要な変更のみ）

詳細はGitのコミットログを参照してください。

### 開発中（dev：次期系列向け）

- 人物演技・感情表現の改善を目的として、人物・背景Vision、Direction Enhancer、Timeline Planner、Compilerの既定モデルをGemma4 31B Q4_K_Sへ統一しました。
- Scene Author経路を導入しました。Scene単位で出来事、人物演技、Cameraを順に計画し、継続Sceneには直前の終端状態を渡します。利用者がShotへ直接記述した確定指示は保持します。
- 明示的に有効化されたモーション補完を、LLM原文と出所を区別して合成できるようにしました。LLM原文の保持と、作者・profileによる補完を別の責務として扱います。
- 開発時の検証対象を大容量VRAM環境へ変更しました。旧小型LLM構成の動作実績を、現在の31B構成の要件とはみなしません。

### v0.1.2 - プロトタイプ（ComfyUI-cl-japanese2json）からの主な変更

- LLMの推論結果をAS ISで採用する設計へ変更しました。Python側での意味的な改変や再構築を避け、意味制約に起因するコンパイルエラーを削減しています。
- 参照画像を人物用と背景用に分離しました。人物の識別特徴に背景情報が圧迫されることを防ぎ、舞台、建築、植生及び空間構造をより正確に反映できます。
- MiniMax H3の参照画像解像度を`match`から`max`へ変更しました。丸い眉毛など、キャラクター固有の細かな形状を保持しやすくしています。
- VRAM 8 GB、メインメモリ16 GBの検証環境では、Context Loop標準リップシンクが停止する場合があることを確認しました。代替としてAudio Reference方式と歌詞方式のリップシンクworkflowを用意していますが、これらは現在も動作検証中です。

## ライセンス

Copyright © 2026 `wsoldwolf`

ソースコードと文書は、別途明記された場合を除き[GNU General Public License v3.0 only](LICENSE)（`GPL-3.0-only`）です。

`assets/`の検証用楽曲、歌詞、ボーカルステム及び参照画像はソフトウェアライセンスの対象外です。対象素材と条件は[ASSET_LICENSES.md](ASSET_LICENSES.md)を参照してください。
