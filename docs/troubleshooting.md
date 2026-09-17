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

## Vision行protocolで停止する

4B Visionモデルはまれに行protocolを崩します。まず`seed`を固定して再現性を確保し、`cache_mode=refresh`で一度だけ再生成します。恒常的に崩れるモデルでは、instruction追従性の高いVision GGUFへ変更してください。protocol不正を自然文として黙って採用するfallbackはありません。

## 翻訳行protocolで停止する

Compilerの日本語→英語翻訳には8B級Text GGUFを推奨します。`temperature=0`、`cache_mode=refresh`で確認してください。すでに全promptが英語なら`translation_mode=already_english`にするとGGUFをloadしません。

## Context Loopが音声長不足で停止する

H3はframe境界を正本にするため、表示上ほぼ同じ長さでも不足する場合があります。さらにPlannerがカット／継続を変更すると、合法なH3格子への再配分によりLyric Segmentationの初期timelineより最終Planが長くなることがあります。Audio Pad PairへTimeline、H3 Timing Profile及びCompiler出力と同じ`plan_json`を接続し、full mixとvocalの両方を最終Planの正確なdelivered frame尺まで末尾PCM無音でそろえます。

## workflowのwidget値がずれている

ノードsocket追加後の古いworkflowでは、ComfyUIの保存済みwidget配列が別項目へずれることがあります。配布workflowを最新版へ更新するか、問題ノードを削除して作り直します。
