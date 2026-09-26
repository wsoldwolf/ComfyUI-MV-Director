# 文書用図版

| ファイル | 用途 |
|---|---|
| [`minimal-pipeline.svg`](minimal-pipeline.svg) | 人物`<Picture 1>`と背景`<Picture 2>`、演出候補の分離、保存Plan境界及びH3 Hybrid Loaderを示す概要図の編集用原本 |
| [`minimal-pipeline.png`](minimal-pipeline.png) | READMEと概要へ埋め込むPNG版 |
| [`direction-planner-flow.svg`](direction-planner-flow.svg) | Gemma4によるDirection、Scene Author（Event→Performance→Camera）、任意の補完と原文保持の境界を示す編集用原本 |
| [`direction-planner-flow.png`](direction-planner-flow.png) | Direction / Planner文書へ埋め込むPNG版 |

ブロック図はMarkdown文字図ではなくPNG/SVGとして文書へ埋め込みます。

処理フローSVGは`python tools/generate_runtime_flow_diagram.py`で再生成します。
更新時はSVGからPNGも再描画し、表示と原本を一致させます。
