# 文書案内

トップREADMEは入口だけを扱い、操作、仕様、実装、調査をここから分離しています。

## 利用する人向け

| 文書 | 用途 |
|---|---|
| [プロジェクト概要](overview.md) | パイプライン、EMD、音声方式、設計上の境界を理解する |
| [導入マニュアル](installation.md) | Windows版ComfyUIへ本体と依存環境を導入する |
| [ノードマニュアル](nodes/README.md) | 公開11ノードの入力、出力、使い方を確認する |
| [workflowマニュアル](../workflows/README.md) | 三つのリップシンク方式に対応する6 workflowを使う |
| [トラブルシューティング](troubleshooting.md) | モデル未検出、protocol、歌詞整列等の停止原因を調べる |

## 形式を実装・編集する人向け

| ディレクトリ | 用途 |
|---|---|
| [`spec/`](spec/README.md) | EMD、行protocol、Ref2VA変換等の規範仕様 |
| [`implementation/`](implementation/README.md) | repository構造、公開node surface、実装判断 |
| [`research/`](research/README.md) | Context Loopの挙動調査、仕様漏れ監査 |
| [`assets/`](assets/README.md) | 文書へ埋め込むPNG/SVG図版 |

利用方法はノードマニュアル、厳密な文法・機械契約は`spec/`、内部責務は`implementation/`を正本として参照してください。
