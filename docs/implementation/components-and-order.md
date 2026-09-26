# 現行部品と変更手順

更新日: 2026-09-27。旧8B向けPlannerと研究用スクリプトは配布構成から撤去しています。

## 責務の配置

| 場所 | 責務 |
|---|---|
| core/artifacts、protocols | typed artifact、JSON検証、行protocol |
| core/vision | 画像観察とSubject / Scene断片 |
| core/direction | profile、ユーザー指示、候補／補完の構文分離と統合 |
| core/lyrics、audio、timing | 歌詞整列、PCM、source / delivered時間 |
| core/planner/api.py、types.py | 現行API、内容型、完成EMD描画 |
| core/planner/scene_author.py | Event → Performance → Camera、終端と補完 |
| core/planner/requests.py、request_budget.py | 有限protocol回復、context回復 |
| core/compiler | 英訳とRef2VA形式への機械変換 |
| nodes、web | ComfyUI wrapper、UI |
| profiles、prompts | 現行芸術方針とシスプロ |
| tools | WF／図生成、モデルdebug、最小H3投入、metadata抽出、output整理 |

旧engine、Cue、Scene Spine、Action Audit、有限Cameraの実装を再利用して新経路へ戻さない。音声・時間・モデル探索等の責務が変わらない部品は保持する。

## 変更の順序

1. EMD／protocol／profile契約への影響を確認する。
2. coreのCPU試験で作者所有、出所、時刻、cache、回復上限を検証する。
3. nodeのINPUT_TYPESとWF generatorを同時に更新する。
4. 既存WFへの限定migrationを優先し、配置・色・利用者素材・seed・保存Planを保持する。
5. README、操作文書、図面を実装と合わせる。
6. 意味／映像へ影響する変更だけGPU許可を得て短区間を比較する。

研究レポート・再現実験はプロジェクト外のresearchアーカイブへ出力する。過去の知見を説明するTIPSは、現行機能の仕様と混同しない形で保持する。
