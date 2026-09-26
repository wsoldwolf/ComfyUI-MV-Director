# 最小コア仕様

更新日: 2026-09-27
対象: 現行dev、Gemma4 31B構成

## 1. 目的と範囲

参照画像・歌詞・音声・ユーザー指示から、編集可能なEMDとMiniMax H3 / Context Loop用Planを作る。動画生成は保存済みPlanを受け取る別WFの責務である。VRAM 8 GB対応と旧小規模モデル向けPlanner経路は対象外とする。

文法の正本は[EMD仕様](emd-spec.md)、通信・artifactの正本は[プロトコル仕様](protocol-spec.md)、操作は[ノードマニュアル](../nodes/README.md)を参照する。

## 2. 責務

| 部品 | 入力と責務 | 出力 |
|---|---|---|
| Image to Subject EMD | 画像の観察。subject_only / scene_only / generalを切替 | emd_fragment、観測JSON、参照binding |
| Direction Enhancer | 人物・背景断片、profile、利用者指示の統合 | MVD_DIRECTION_V4、preview |
| Lyric Segmentation | 歌詞と元vocalをWhisper/VADで整列。H3時間枠を確定 | Template EMD、SRT、typed timeline |
| Timeline Planner | 各SceneのEvent → Performance → Camera。未指定fieldだけ生成 | 完成EMD |
| EMD Compiler | 自由描写の英訳、予約directive、時間格子と参照の機械処理 | Plan JSON、required references |
| Video WF | H3への画像・音声入力、生成、Review、連結 | segments / final |

人物画像と背景画像は別authorityとし、Visionの共通出力`emd_fragment`をそれぞれ`concept_emd`と`scene_emd`へ接続する。観測JSONはデバッグ用であり、Enhancerの入力ではない。

## 3. ユーザー所有と生成

- 完成EMDを直接Compilerへ渡せる。Plannerへ完成全文を渡した場合も検証後に生成を省略できる。
- TemplateのScene/Shot境界、歌詞時刻、継続指定はPlannerが再設計しない。
- Shotの`演出`、`演技`、`カメラ`は確定指示。そのfieldの生成を省略し、次段へ原文を渡す。
- `# 共通プロンプト`は共通描画方針。`# 演出候補`は局所計画の任意の着想であり、全Scene共通prefixへ混ぜない。
- `# モーション補完`は別責務の機械的合成を明示許可する。LLM演技原文と補完の出所を区別する。
- 採用自然文の意味的修復はしない。構造wrapper、不要なthink区間、行継続記号の狭い正規化はprotocol処理とする。

## 4. Planner

全Motion profileでScene Authorを使う。旧Cue Discovery、Visual Beat、Song Direction、Shot Layout、Scene Spine、Actions/Audit、有限Cameraは実行しない。

各Sceneの歌詞とsection文脈、人物・背景、Direction、固定Shot指示を渡し、出来事・人物演技・撮影を順に生成する。終端状態は継続Sceneへ渡す。必須slotは有限回復後も欠ければ停止する。美術的品質だけを理由に旧監査経路へ戻さない。

profileは芸術方針と明示補完metadataを所有する。`performance_mode`等の旧strategy selectorは廃止した。現行metadataは[profile仕様](../../profiles/README.md)を参照する。`scenes_per_batch`は廃止し、Scene単位で要求する。

## 5. モデル・runtime

配布WFはVision（mmproj併用）、Enhancer、Planner、CompilerをGemma4 31B Q4_K_Sへ統一する。モデル一覧・取得元・ハッシュは[導入マニュアル](../installation.md)を正本とする。別モデルの互換性や最低VRAMを推測保証しない。

配布WFのcontextはVision / Enhancer / Plannerが24,576、Compilerが16,384、出力上限は各4,096。各要求はtask固有の出力予約量と実効contextに基づき事前検査する。必須指示を黙って切り捨てず、履歴縮小・slot分割等の有限回復後も収まらなければContextBudgetErrorとする。

ノード型・範囲は`INPUT_TYPES`、WF既定値は`tools/generate_workflows.py`が実装正本。モデルは利用時だけロードし、`keep_model_loaded=false`なら後段へ解放する。

## 6. 時間・音声・参照

EMDは絶対時刻`MM:SS.mmm`、内部は整数ms、H3はTiming Profileのframe格子を使用する。source音声とdelivered時間は区別する。Audio Pad PairはPCMを混合・切詰めず、必要な無音padding又は明示されたScene再配置を行う。Scene Debug SplitterはPlanと二つのPCMを同じ範囲へ切り出す。

lip-sync modeは`off` / `context_loop` / `audio_reference` / `lyrics`。歌詞annotationは全modeで保持する。生成指示・配線が成立してもH3の完全な同期は保証しない。

CompilerはRef2VA形式のPlanを出力する。動画側でFL2VAをベースにRef2VA参照層をoverlayする構成とは別責務である。基準contractと必要Picture/Audioは生成側で一致させる。

## 7. 保存と停止

成功artifactだけをcacheする。入力、profile、モデルfingerprint、runtime、seed、prompt hash、algorithm版をcache identityへ含める。旧Planner cache形状を推測変換しない。

必須歌詞未整列、必須生成slot未回復、構文不正、model load失敗、OOM、中断を空の成功出力へ変換しない。進捗とINFOは処理単位の目安であり、残り秒数の保証ではない。

## 8. 受入条件

CPU試験でartifact・protocol・時間・参照・作者所有・補完・cache・WF配線を検証する。生成文と実動画の品質は別に判定し、変更が映像へ影響する場合はGPU許可を得て短区間比較を行う。研究用試験資産は配布リポジトリに含めない。
