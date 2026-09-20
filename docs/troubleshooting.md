# トラブルシューティング

## GGUFが表示されない

- Text GGUFは`models/LLM/GGUF`または登録済み`LLM` root以下へ置きます。
- Visionは本体GGUFと`mmproj` GGUFを同じディレクトリへ置きます。
- 配置後はComfyUIを再起動します。保存済みworkflowの古い選択値はstale扱いになるため、comboを選び直します。

## `llama-cpp-python is unavailable`

ComfyUIが使用するPythonへwheelをインストールしたか確認します。システムPythonへ入れてもComfyUIからは見えません。

```powershell
C:\Software\ComfyUI\venv\Scripts\python.exe -m pip show llama-cpp-python
```

Visionで`MTMDChatHandler`がない場合は[導入マニュアル](installation.md)の検証コマンドを実行し、Vision対応buildへ入れ替えます。

## 歌詞が`unplaced`で停止する

Lyric Segmentationは、入力した全atomic lyric segmentが音源内に歌われていることを要求します。Suno等が後半の歌詞を歌わず終了した音源では、未歌唱分を正しく停止として報告します。対応音声を用意するか、歌われていない歌詞を入力から除きます。

入力はUTF-8 plain lyricsです。`[VERSE]`、`[CHORUS]`、`[BRIDGE]`等、任意のASCII section名を使えます。LRC、SRT、VTT、timestampは入力できません。

## LLMの行protocol不整合が発生する

本プロジェクトは、プロンプト生成にLLMの確率的な出力を使用するため、行protocol、必須slot又は出力規約への違反を完全には排除できません。特に既定のQwen 8B級モデルは性能とinstruction追従性に制約があり、system prompt及びprofileで規約を明示しても、未知record、欠落slot、重複slot、field数違反又は自然文の混入を返す場合があります。

parserによる一意なwrapper復元、局所retry及び監査は既知の表記揺れを有限範囲で回復しますが、欠落又は破損したcreative textの意味を決定論的に推測して合成することはできません。AS IS原則を保ったまま、あらゆるLLM出力を必ず成功へ変換する決定論的な仕組みを構築することは不可能です。復元できない応答を黙って採用せず、該当ノードは停止します。

同じ入力でprotocol不整合が発生した場合は、32-bit Seedノードを`random`にするか別の`seed`へ変更し、対象ノードを`cache_mode=refresh`で再実行してください。これは別の生成パターンから規約適合応答を得るための運用上の回避策であり、成功を保証する修復ではありません。比較、原因調査又は再現試験では、問題が出たseedも記録してから固定値へ戻してください。繰り返し失敗する場合は、instruction追従性の高いGGUFへの変更又は対象batchの縮小を検討します。

## Vision行protocolで停止する

4B Visionモデルはまれに行protocolを崩します。まず`seed`を固定して再現性を確保し、`cache_mode=refresh`で一度だけ再生成します。恒常的に崩れるモデルでは、instruction追従性の高いVision GGUFへ変更してください。protocol不正を自然文として黙って採用するfallbackはありません。

## 翻訳行protocolで停止する

Compilerの日本語→英語翻訳には8B級Text GGUFを推奨します。`temperature=0`、`cache_mode=refresh`で確認してください。すでに全promptが英語なら`translation_mode=already_english`にするとGGUFをloadしません。

## Context Loopが音声長不足で停止する

H3はframe境界を正本にするため、表示上ほぼ同じ長さでも不足する場合があります。さらにPlannerがカット／継続を変更すると、合法なH3格子への再配分によりLyric Segmentationの初期timelineより最終Planが長くなることがあります。Audio Pad PairへTimeline、H3 Timing Profile及びCompiler出力と同じ`plan_json`を接続し、full mixとvocalの両方を最終Planの正確なdelivered frame尺まで末尾PCM無音でそろえます。

## workflowのwidget値がずれている

ノードsocket追加後の古いworkflowでは、ComfyUIの保存済みwidget配列が別項目へずれることがあります。配布workflowを最新版へ更新するか、問題ノードを削除して作り直します。
