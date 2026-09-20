# ComfyUI-MV-Director

[![【MV】千里の秋を駆ける - MiniMax H3+Context Loop+MV Director Demo](https://img.youtube.com/vi/OLffZGlcZOs/maxresdefault.jpg)](https://youtu.be/OLffZGlcZOs)
※本作品は東方Projectの二次創作であり、公式作品ではありません。

画像、歌詞、ボーカルステム、フルミックスから、MiniMax H3 / Context Loop用のMV計画を作るComfyUIカスタムノードです。VisionによるSubject EMD、演出方針、歌詞タイムライン、Shot計画を分離し、最後にRef2VA Plan JSONへコンパイルします。

EMDは **Easy MarkDown** の略です。Extended Markdownではありません。

![人物参照と背景参照を分離し、Plan Compiler段階と動画生成段階の間に再利用可能なPlan JSON保存境界を置くプロジェクト概要](docs/assets/minimal-pipeline.png)

## はじめに

1. [導入マニュアル](docs/installation.md)に従ってカスタムノード、`llama-cpp-python`、Whisper、各モデルを準備します。
2. [配布workflow](workflows/README.md)から、Context Loop標準、Audio参照、歌詞のいずれか一組を選びます。
3. [ノードマニュアル](docs/nodes/README.md)で各入力、出力、既定値、接続方法を確認します。
4. EMDを直接編集する場合は[EMD仕様書](docs/spec/emd-spec.md)を参照します。

基準環境はComfyUI v0.36.0 commit `ee71d5c4993f29086b27fde1629a945ae48425bf`、Context Loop 0.6.9 commit `9860a063784c8c23b58e00107f2180e0df3c43d9`です。

## 重要: LLM出力と再実行

本プロジェクトはプロンプト生成にLLMの確率的な出力を使用するため、行protocol、必須slot又は出力規約への違反が発生する可能性があります。特に既定のQwen 8B級モデルは性能とinstruction追従性に制約があり、system prompt及びprofileで規約を明示しても、未知record、欠落・重複slot、field数違反又は余分な自然文を返す場合があります。

Python側は一意に判断できる構造だけを有限範囲で検証・復元します。欠落又は破損したcreative textの意味を決定論的に推測して合成することはできないため、AS IS原則を維持したまま全てのprotocol不整合を必ず成功へ変換する決定論的な仕組みを構築することは不可能です。復元不能な場合は、不完全なPlanを後段へ流さず停止します。

protocol不整合が発生した場合は、32-bit Seedノードを`random`にするか別の言語生成`seed`へ変更し、対象ノードを`cache_mode=refresh`で再実行してください。これは別のLLM出力パターンから規約適合応答を得るための運用上の回避策であり、成功を保証する修復ではありません。原因調査では失敗したseedを記録し、繰り返し失敗する場合はinstruction追従性の高いGGUFへの変更又はPlannerのbatch縮小を検討してください。詳しくは[トラブルシューティング](docs/troubleshooting.md#llmの行protocol不整合が発生する)を参照してください。

## 文書索引

| 場所 | 内容 |
|---|---|
| [`docs/`](docs/README.md) | 利用者向け・開発者向け文書の総合索引 |
| [`docs/tips/`](docs/tips/README.md) | 参照画像の分離、再現率、配線など実運用のTIPS |
| [`docs/nodes/`](docs/nodes/README.md) | 公開12ノードの操作マニュアル |
| [`docs/spec/`](docs/spec/README.md) | EMD、protocol、最小コアの規範仕様 |
| [`docs/implementation/`](docs/implementation/README.md) | 内部構造、公開surface、実装順序 |
| [`docs/research/`](docs/research/README.md) | Context Loop調査と仕様監査の記録 |
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

### プロトタイプ（ComfyUI-cl-japanese2json）からの主な変更

- LLMの推論結果をAS ISで採用する設計へ変更しました。Python側での意味的な改変や再構築を避け、意味制約に起因するコンパイルエラーを削減しています。
- 参照画像を人物用と背景用に分離しました。人物の識別特徴に背景情報が圧迫されることを防ぎ、舞台、建築、植生及び空間構造をより正確に反映できます。
- MiniMax H3の参照画像解像度を`match`から`max`へ変更しました。丸い眉毛など、キャラクター固有の細かな形状を保持しやすくしています。
- VRAM 8 GB、メインメモリ16 GBの検証環境では、Context Loop標準リップシンクが停止する場合があることを確認しました。代替としてAudio Reference方式と歌詞方式のリップシンクworkflowを用意していますが、これらは現在も動作検証中です。

## ライセンス

Copyright © 2026 `wsoldwolf`

ソースコードと文書は、別途明記された場合を除き[GNU General Public License v3.0 only](LICENSE)（`GPL-3.0-only`）です。

`assets/`の検証用楽曲、歌詞、ボーカルステム及び参照画像はソフトウェアライセンスの対象外です。対象素材と条件は[ASSET_LICENSES.md](ASSET_LICENSES.md)を参照してください。
