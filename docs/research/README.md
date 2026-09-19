# 調査記録

| 文書 | 内容 |
|---|---|
| [`prompt_prefix`調査](context-loop-prompt-prefix.md) | Context Loop/H3で先頭promptが画風変換へ与える影響 |
| [仕様漏れ監査](spec-gap-audit-2026-09-16.md) | 実装前に確認した未確定事項と採用判断 |
| [プロトタイプ映像のCamera・Motion比較基準](prototype-camera-motion-baseline-2026-09-17.md) | 埋め込みPlan metadataと映像から抽出したScene継続、Arc、Tracking及び身体演技の基準 |
| [`anime_emotional_mv`設計分析](anime-emotional-mv-prototype-analysis-2026-09-19.md) | 27Bプロトタイプの苔、狐火、長尺Arc、顔遷移及びScene継続を現行Plannerへ移す判断根拠 |
| [`anime_emotional_mv`生成結果評価](anime-emotional-mv-output-review-2026-09-19.md) | 現行生成動画の対象接触反復、effect保持、顔寄り過多、目及び全身演技不足を再現し、局所歌詞トリガーへ改訂した記録 |
| [`anime_story_mv`生成結果評価](anime-story-mv-output-review-2026-09-19.md) | EMDと完成動画を時刻対応で比較し、苔・花・狐火の欠落、固定顔Shotによるcue消失、Arc・表情・足袋及び長い固定英文の原因と改修を記録 |

このディレクトリは判断根拠の記録です。現在の規範仕様は[`docs/spec/`](../spec/README.md)を優先します。
