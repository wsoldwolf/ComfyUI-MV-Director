# TIPS

ノード仕様ではなく、実際のMV生成で再現率と編集性を保つための運用ノウハウをまとめます。厳密なsocket、artifact及び文法契約は[ノードマニュアル](../nodes/README.md)と[仕様書](../spec/README.md)を正本とします。

| TIPS | 内容 |
|---|---|
| [H3へ渡す文と映像の因果関係](compact-h3-visual-spec.md) | 対象・可視変化・人物の反応・Cameraの関係を簡潔に示す考え方と、短区間A/Bで確認すべきこと |
| [機械的な補完文が演技に見えること](mechanical-motion-and-perceived-performance.md) | 旧版の固定文補完の発見、確認事実と仮説、AS ISの限定的見直し、比較用profileとユーザー指定方法 |
| [試行錯誤で生まれた良さを仕様化する難しさ](prototype-discovery-and-reproducibility.md) | バイブコーディングのプロトタイプから良い表現を移す費用と、後から再現できるよう残すべき証跡 |
| [人物参照と背景参照を分ける](separate-subject-and-background-references.md) | 人物identityと環境条件の競合を避け、計画時と動画生成時に別Pictureとして扱う方法 |
| [Plan / Videoを分離する理由](two-stage-workflow.md) | 計画を固定したseed比較、重い前段処理の再実行回避、再開範囲の判断 |
| [演出テンプレートという選択肢と検証負荷](direction-templates-and-validation-cost.md) | Motion / Cameraを選択式にする案と、長時間生成を伴う開発で自動化だけでは解消できない負荷についての考察 |
