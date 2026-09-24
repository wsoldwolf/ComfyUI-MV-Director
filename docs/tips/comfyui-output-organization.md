# ComfyUI outputの分類と保持

動画の全編生成・短区間比較・Plan/EMDの保存が同じ`C:\Software\ComfyUI\output`下に増えると、実験結果を探しにくくなる。このプロジェクトには、**既存パスを変えずに分類表を作る**[索引スクリプト](../../tools/index_comfyui_output.ps1)を用意した。

```powershell
& .\tools\index_comfyui_output.ps1 -OutputRoot 'C:\Software\ComfyUI\output'
```

出力先の`_INDEX.md`には、通常の完成動画、研究用全編動画、短区間比較、Plan・EMD・歌詞、未分類のフォルダと、ファイル数・概算容量・最終更新時刻を記録する。繰り返し実行して最新化できる。生成済み映像、checkpoint、WFのパスは**移動・削除しない**。既に人が作成した`_INDEX.md`は上書きしない。

この分類はフォルダ名による便宜的な索引であり、完成度や削除可能性の判定ではない。レポートやWFは`output`下の絶対パスを参照しているため、整理の第二段階で物理的に移動する前に、生成キューの停止、参照先、再開用checkpointの扱いを個別に確認する。
