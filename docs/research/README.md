# 調査記録

| 文書 | 内容 |
|---|---|
| [Gemma 4 31B：実8B入力の再生と苔・花Scene短区間映像](gemma4-31b-scene-author-s2-4-2026-09-25.md) | 保存済み8BのScene 2–4推論入力を31Bへ渡し、人物演技5行のみ差し替えたH3動画・無音上下比較・両EMDを出典付きで記録 |
| [作者演出候補とPython動作補完の2×2比較](author-candidate-vs-python-motion-p7-2026-09-25.md) | 保存済みScene 5・9で候補・補完・seedを切り分け。候補は身体語彙を増やすが採用・Shot進行は不安定で、作者短文の原文保持を次の検証対象にした |
| [簡潔Scene仕様 P6：公式8Bと現行8Bの形式・本文・推論設定](compact-scene-spec-p6-official-8b-protocol-sampling-2026-09-25.md) | 保存Sceneを本番grammarで再生し、両モデルの形式4/4と、反復・自転など本文の未解決を分離。公式推奨寄りsamplingも小範囲で比較 |
| [簡潔Scene仕様 P5：8Bの意味ラベル比較](compact-scene-spec-p5-semantic-field-labels-2026-09-25.md) | `SCENE_EVENT`は主題の焦点を改善したが、`PERFORMER_BODY_ACTION`は振付を増やさず、`PERFORMER_POSE_CHANGE`は主語混同。欄名単独の本番採用を見送った |
| [簡潔Scene仕様 P4：不透明ラベルだけの対照比較](compact-scene-spec-p4-opaque-label-control-2026-09-25.md) | 8BのScene 6・9×2 seedで出力ラベルのみ変更。両条件4/4形式合格だが不透明ラベルは本文の意味が消え、一律導入を見送った |
| [Shot接続・全身演技の全編H3検証](shot-linkage-body-full-validation-2026-09-24.md) | Scene 3・4・9の手作業候補を同seed・同尺で全編比較。全身演技と狐火の改善、花の配置、16 Scene再開とScene間メモリ解放、途中動画での人による判定を記録 |
| [Scene Event：Shot連続句・境界句の焦点選択判定](scene-phrase-focus-validation-2026-09-24.md) | Scene 3〜6・9×2 seedで句の束ね方を検証。候補は正しいが後半Shotの選択とEventへの対象維持に失敗し、追加二段経路を不採用と判定 |
| [簡潔Scene仕様 P2：8Bの能力と情報受け渡しの境界](compact-scene-spec-p2-model-boundary-2026-09-24.md) | 御神木・狐火を実8B/14Bで局所比較。Eventだけでは対象は保てても人物演技・Camera連携が戻らないことを確認 |
| [簡潔Scene仕様 P3：8B system promptの役割分担](compact-scene-spec-p3-8b-prompt-2026-09-24.md) | Eventを固定し、一文／BODY＋CAMERA／PERFORMER＋CAMERAを比較。表現は部分改善したが8Bの意味・形式安定性は不足 |
| [Scene Event：歌詞だけの焦点選択→出来事生成の短区間試験](scene-lyric-focus-two-stage-2026-09-24.md) | 背景・候補を伏せた選択を5 Scene×2 seedで検証。苔は改善したが花・御神木は欠落、狐火は退行し、grammar順の影響も切り分けて本番採用を見送った |
| [Scene Event根拠宣言 P0–P2：固定入力と8B判定](scene-event-source-p0-p2-validation-2026-09-24.md) | Scene 3–6・9の歌詞出典を固定し、現行EventとSOURCE付きEventを20回比較。形式は成立したが花・御神木の採用は改善せず、P2伝播を品質ゲートで停止 |
| [Scene Eventの対象選択：任意候補と作者固定指示の間](scene-event-source-selection-design-2026-09-24.md) | 花の過去成功例と現在の落葉選択を比較。作者固定・歌詞・任意候補・背景の優先境界を追跡し、追加呼出しなしの根拠宣言と小範囲8B評価を設計 |
| [Shot接続器 P1：演出候補の寄与と歌詞Shotの位置](shot-linkage-p1-candidate-comparison-2026-09-24.md) | 苔・狐火の候補あり/なし、花の完結句3条件と花のユーザー演出候補追加を実8Bで比較。歌詞Shotへの配置改善と対象欠落を分離し、補完の単純なShot移動では不足する根拠を整理 |
| [Shot接続器 P0：採用Plan・EMD・H3映像の出典と時間軸](shot-linkage-p0-provenance-2026-09-24.md) | MP4内Planのハッシュで正しいEMD系列を特定。苔・花・狐火の歌詞より早い配置をEMD→Compiler→H3→映像で追い、未取得のLLM生出力と候補採否を分離したP1の固定条件 |
| [旧8B三要素の現行統合を踏まえた改善計画](legacy-8b-integration-next-plan-2026-09-23.md) | 歌詞単位・非thinking開始・身体補完が既に映像へ届く前提で、ユーザー演出候補とモーション原文合成の寄与を分け、短区間の出典追跡からH3比較までの採用条件を計画 |
| [全編EMD 00002：演技の持ち越し・補完の累積と次の改修計画](scene-composition-full-sequence-review-2026-09-23.md) | 34 Shotと採用キャッシュを照合。31 Shotの同一基礎演技、補完のLLM原文への混入、歌詞対象の欠落を分析し、担当別の終端状態と連続Scene比較によるP0〜P3を計画 |
| [明示モーション合成の実装・8B検証](motion-composition-2026-09-23.md) | 原文保持と外部template合成、作者優先、541件回帰、実効seed固定を含む24呼出し。残る静止・移動競合を記録 |
| [旧8B動作生成の再現実験](legacy-action-replay-2026-09-23.md) | 旧prompt・人物入力・非thinking経路で32回比較。歌詞単位と尺を分けて評価し、旧Pythonの全身motion補完も追跡。単純移植を見送り、作者の身体フレーズ候補を使う次の判断を記録 |
| [セクション文脈と演技指示：P0〜P2実行結果](section-performance-p0-p2-2026-09-23.md) | 入力経路・候補伝達を実装し526件回帰。四条件8回、別seed4回、共同設計2回を比較したが振付改善は未達。P3保留と当時の実prompt再現の優先度を記録 |
| [第一次判定の再分析：8Bへ演技意図と歌詞文脈を戻す](scene-author-8b-input-recovery-plan-2026-09-23.md) | 旧8Bのprompt 13ファイルをmetadata hashと照合。局所歌詞の分断、演技候補の伝達、外部出来事への従属を分析し、prompt×セクション全文の8回比較と段階的な改善計画を提案 |
| [Scene author経路：実装と8B短区間の第一次判定](scene-author-pilot-2026-09-23.md) | 作者EMD優先、三段Scene経路、構造grammar、実8B Scene 5・9の成功と創作上の未達を証跡付きで整理。既定昇格とH3比較を保留した理由 |
| [8B振付生成の再設計：原文保持と短い統合経路](scene-choreography-architecture-redesign-2026-09-23.md) | Motion入力の欠落と旧8Bの直接採用経路を追跡。Scene単位の原文保持・撮影計画・限定監査に加え、ユーザーEMD優先の共通解析、部分手書き・補完、Compilerまでの優先解決を図付きで提案 |
| [Scene身体フレーズ P0–P3：実装と品質ゲート](scene-phrase-p0-p3-2026-09-23.md) | Opt-in profile、502件回帰、8B六応答及び実Planner二Sceneを比較。完成Actionで未達のためH3実行を保留した判断を記録 |
| [9月23日完成動画：人物の振付・身体演技不足](emd-video-2026-09-23-body-performance-gap.md) | 30 Shotと完成動画の身体動作を照合。前半20 Shotの脚・重心指示欠落、全身画角不足、疎なaccent割当を分析し、Scene身体フレーズとCamera coverageの改善計画を記録 |
| [9月23日完成動画：苔→花の継続と身体演技](emd-video-2026-09-23-continuity-performance-plan.md) | EMD・Plan・動画を照合し、継続中の構図急変と身体演技不足を分析。空間・振付・歌詞時刻の改善計画 |
| [9月23日完成動画：苔・花の尺と振付不足](emd-2026-09-23-moss-flower-choreography-review.md) | 約23秒続く植物への片手接触、Verseで全身accentが選ばれない条件、4秒Shot下限、歌詞開始より早い接触を整理し、限定改修と検証条件を記録 |
| [Scene内進行・全身演技・外部effectの統合改修](planner-scene-spine-motion-effect-integration-2026-09-22.md) | P0〜P2、上半身偏重の是正、狐火欠落のPlanner→Compiler追跡、v64の型保持・可視展開転送と未検証事項を整理 |
| [Scene内進行：P0〜P2実装と8B評価](scene-event-spine-p0-p2-2026-09-21.md) | Scene一括の進行とCamera coverageを実装。二seedの8B評価、残る意味上の接触反復、P3用PlanとScene 9の選定 |
| [Scene内進行の検証計画](scene-event-spine-validation-plan-2026-09-21.md) | Sceneの出来事、演技、Camera coverageを短区間で検証する計画 |
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
