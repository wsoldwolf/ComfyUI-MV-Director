# 調査記録

| 文書 | 内容 |
|---|---|
| [cl-japanese2json のプロンプト生成と現行版の比較](japanese2json-prompt-generation-comparison-2026-09-21.md) | 指定された旧8B／27B完成動画の埋め込みPlan・時系列フレーム・9月12日実装を照合し、人物演技とCamera連動の差をShot密度、Scene一体計画、Cue分割、H3条件に分けて結論と検証方法を記録 |
| [Planner v60：P0〜P3実装と短区間検証](planner-v60-scope-phrase-camera-validation-2026-09-20.md) | 翻訳スコープと描画用profileの分離、演技phase・Camera接続、実8B二試行とH3一Scene三条件の比較。創作品質の未達も記録 |
| [滝アセットへの鳥居・灯籠の混入](waterfall-shrine-prompt-leakage-2026-09-20.md) | 新しい人物／滝参照とScene 1を照合。Motionの鳥居禁止例と背景参照の固定文がH3へ実際に届くことを確認し、舞台に依存しない契約への修正を提案 |
| [loop-2完成動画：身体演技の反復とプロトタイプとの差](loop2-performance-regression-review-2026-09-20.md) | 52 Shotと動画・キャッシュを照合。共通Camera文への局所Action混入、Cueでの接触テンプレート化、短い演技とCamera接続の不整合、H3モデル／scheduler差を分け、改善順位と局所検証を提案 |
| [Planner v57：接触・上半身演技・Arc方向](planner-v57-loop10-contact-camera-review-2026-09-20.md) | loop-10動画と採用Planを照合。苔を踏む・鳥居上に立つ指示、旋回反転とCamera候補の矛盾を修正。402件回帰と実映像再検証の条件を記録 |
| [Planner v56：P0・連動する身体演技](planner-p0-dance-phrase-2026-09-20.md) | Motionファイルでの切替、短縮Action prompt、実8Bの五試行と398件回帰。身体演技の部分回復と残存する反復を区別して記録 |
| [完成動画：身体演技とCamera同期の評価](anime-emotional-mv-performance-camera-review-2026-09-20.md) | 9月20日動画・実採用Plan・51Shotを照合。手振り偏重、振付の不足、Cameraの位相表現と継続引継ぎの制限を分析し、既存段階で進める最小改修と局所A/Bを計画 |
| [Planner v54：歌詞行Discoveryと対象保持](planner-v54-lyric-cue-discovery-2026-09-20.md) | 苔・花・狐火・御神木の局所抽出、原文に結び付く生成時制約、実8B比較と残った意味・配置の問題 |
| [EMD 00014：歌詞対象・演技主体・述語の評価](planner-emd-00014-event-role-review-2026-09-20.md) | 花・狐火・御神木の復帰と苔欠落、風に偏る52Shot、人物演技の消失、顔／ArcとActionの不整合を比較評価 |
| [Planner v53 必須文・監査の生成時制約](planner-v53-action-audit-constraints-2026-09-20.md) | scene12の再停止、有限監査文法、Actionの必須fragment制約、候補選択の優先度及び実8B試験 |
| [Planner v52 顔Shotとgroundingの割り当て衝突](planner-v52-face-grounding-conflict-2026-09-20.md) | ACTION_GROUNDING停止の原因、顔以外へのCue fragment配分、進行順の再計算及び回帰テスト |
| [Planner v51 限定解釈の実装・実8B検証](planner-v51-bounded-implementation-2026-09-20.md) | 出力九項目・六taskを維持した限定補完、短い文脈、構文制約と、実8Bで残った抽象語誤認・反復を記録 |
| [プロトタイプ8Bとの演出生成比較・診断の再評価](prototype-8b-creative-regression-analysis-2026-09-20.md) | 動画metadataの狐火・御神木・苔を確認し、接触禁止、意味境界、独立effect、Shot細分化を分析。00013の対策順位を見直し、AS ISを維持する最小改修と実8B検証を提案 |
| [`prompt_prefix`調査](context-loop-prompt-prefix.md) | Context Loop/H3で先頭promptが画風変換へ与える影響 |
| [仕様漏れ監査](spec-gap-audit-2026-09-16.md) | 実装前に確認した未確定事項と採用判断 |
| [プロトタイプ映像のCamera・Motion比較基準](prototype-camera-motion-baseline-2026-09-17.md) | 埋め込みPlan metadataと映像から抽出したScene継続、Arc、Tracking及び身体演技の基準 |
| [`anime_emotional_mv`設計分析](anime-emotional-mv-prototype-analysis-2026-09-19.md) | 27Bプロトタイプの苔、狐火、長尺Arc、顔遷移及びScene継続を現行Plannerへ移す判断根拠 |
| [`anime_emotional_mv`生成結果評価](anime-emotional-mv-output-review-2026-09-19.md) | 現行生成動画の対象接触反復、effect保持、顔寄り過多、目及び全身演技不足を再現し、局所歌詞トリガーへ改訂した記録 |
| [`anime_emotional_mv` Context Loop 6追跡評価](anime-emotional-mv-context-loop-6-review-2026-09-19.md) | 完成動画、Plan及びEMDを時刻対応で調べ、前傾・開腕反復と足袋崩壊が局所Shot指示、fail-openな意味検査及び`足袋`誤訳から生じることを特定 |
| [Planner責務分離とEMD 00006改善](planner-responsibility-isolation-emd-00006-2026-09-19.md) | EMD 00006のArc過多、歌詞cue漏洩及びAction/Camera矛盾を分析し、Cue Card、用途別Direction、半数Arc及び短尺除外へ改訂した記録 |
| [EMD 00007評価と歌詞根拠境界](planner-emd-00007-grounding-review-2026-09-19.md) | Arc配分改善後に残った灯籠偏重、身体テンプレート反復、Action/Camera不整合を定量化し、歌詞引用を必須にするCue Card境界へ改訂した記録 |
| [EMD 00008評価とAction grounding](planner-emd-00008-action-grounding-review-2026-09-20.md) | 灯籠漏洩解消後に発生した胸前の手・胸郭テンプレート、苔／狐火Cue欠落、顔演技不足及びArc軌道反復を分析し、Planner v45へ改訂した記録 |
| [EMD 00009評価と歌詞Cue Scene展開](planner-emd-00009-lyric-cue-scene-review-2026-09-20.md) | Action反復の再悪化と苔・花・狐火の欠落を分析し、対象の確立、関係、反応及び解放を同一Sceneへ作るPlanner v46の合格条件を記録 |
| [EMD 00010評価と優先Cue scope隔離](planner-emd-00010-priority-cue-scope-review-2026-09-20.md) | 苔・狐火のScene外漏洩、前傾とplanning語彙の定型化を定量化し、Cue Scene単独推論、履歴隔離、Scene外Cue検査及びVisual Beatへの空間情報入力を行うPlanner v47を記録 |
| [EMD 00011評価と具体Cue展開](planner-emd-00011-grounded-cue-development-review-2026-09-20.md) | Cue局所化の成功と裸の対象名、身体template反復、内部Action label漏洩を分析し、配置・可視展開field及びv48監査へ改訂した記録 |
| [EMD 00012評価とCue→Action転送](planner-emd-00012-cue-action-transfer-review-2026-09-20.md) | 苔・花・狐火が裸のprefixへ縮退した原因を分析したv49と、固定辞書を廃して御神木等をScene原文から自動認識するv50の記録 |
| [EMD 00013評価と自動Cueの失効経路](planner-emd-00013-automatic-cue-review-2026-09-20.md) | automatic化後に苔・花・狐火・御神木が全欠落し、透明な波紋と身体templateが反復した結果を定量化し、歌詞行単位Cue Discoveryとfail-closed化を提案 |
| [`anime_story_mv`生成結果評価](anime-story-mv-output-review-2026-09-19.md) | EMDと完成動画を時刻対応で比較し、苔・花・狐火の欠落、固定顔Shotによるcue消失、Arc・表情・足袋及び長い固定英文の原因と改修を記録 |

このディレクトリは判断根拠の記録です。現在の規範仕様は[`docs/spec/`](../spec/README.md)を優先します。
