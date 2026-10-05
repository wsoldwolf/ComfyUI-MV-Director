# TIPS

ノード仕様ではなく、実際のMV生成で再現率と編集性を保つための運用ノウハウをまとめます。厳密なsocket、artifact及び文法契約は[ノードマニュアル](../nodes/README.md)と[仕様書](../spec/README.md)を正本とします。

| TIPS | 内容 |
|---|---|
| [プロジェクトのコード規模](project-code-scale.md) | 本体・テスト・開発ツール・シスプロ・プロファイル・WFの規模、集計範囲と保守負荷の考察 |
| [RTX 5080でGemma4 31B IQ3 XSを使う設定](rtx5080-gemma31b-iq3-xs.md) | VRAM 16GB向けVision・Enhancer・Planner・Compilerのcontext目安、KV概算、SWA設定とmmproj CPU配置の注意点 |
| [H3高速化設定と安定性](h3-acceleration-and-stability.md) | Comfy Kitchen・SLA・Spectrum・FP16 accumulationの設定、Spectrum更新と全編完走の記録、低速化の切り分け |
| [演出候補が採用される条件](staging-candidate-selection.md) | 三つのLLM担当の判断、optional / prefer_matchedの違い、確定指示とモーション補完との区別 |
| [「演技するLLM」と三行補完・状態機械という思考実験](llm-acting-and-three-line-automaton-hypothesis.md) | 旧Python三行の事実と未証明の因果、有限状態の仮説、作者指示とLLM演技の境界を整理。FSMは採用案ではない |
| [H3へ渡す文と映像の因果関係](compact-h3-visual-spec.md) | 対象・可視変化・人物の反応・Cameraの関係を簡潔に示す考え方と、短区間A/Bで確認すべきこと |
| [ビート検出と身体演技の間にある隔たり](beat-detection-and-performance.md) | 拍検出・LLMの時刻解釈・H3の映像化を分け、細かな拍情報が振付の改善へ結び付かなかった検証と考察 |
| [機械的な補完文が演技に見えること](mechanical-motion-and-perceived-performance.md) | 旧版の固定文補完の発見、確認事実と仮説、AS ISの限定的見直し、比較用profileとユーザー指定方法 |
| [試行錯誤で生まれた良さを仕様化する難しさ](prototype-discovery-and-reproducibility.md) | バイブコーディングのプロトタイプから良い表現を移す費用と、後から再現できるよう残すべき証跡 |
| [人物参照と背景参照を分ける](separate-subject-and-background-references.md) | 人物identityと環境条件の競合を避け、計画時と動画生成時に別Pictureとして扱う方法 |
| [Plan / Videoを分離する理由](two-stage-workflow.md) | 計画を固定したseed比較、重い前段処理の再実行回避、再開範囲の判断 |
| [ComfyUI outputの分類と保持](comfyui-output-organization.md) | 動画・短区間比較・Plan/EMDをパスを変えずに索引化し、移動前に確認すること |
| [演出テンプレートという選択肢と検証負荷](direction-templates-and-validation-cost.md) | Motion / Cameraを選択式にする案と、長時間生成を伴う開発で自動化だけでは解消できない負荷についての考察 |
