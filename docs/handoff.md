# 設計引き継ぎ

作成日: 2026-09-15<br>
状態: Phase 0～8公開ノード層を実装済み。実モデル推論とH3レンダリング完了を意味しない。

## 1. 作業境界

新プロジェクト`E:\ComfyUI\projects\ComfyUI-MV-Director`内へ仕様、コア実装、公開ノード、fixture及びテストを配置しています。実行環境では`C:\Software\ComfyUI\custom_nodes\ComfyUI-MV-Director`を同リポジトリへのdirectory junctionとし、変更を自動反映します。次は実施していません。

- 旧プロジェクトの変更、stash適用、checkout、commit、push
- commit、push、tagの作成
- ローカルLLM実推論、H3レンダリング

調査開始時は空でしたが、2026-09-15にユーザーがGitリポジトリを初期化し、`origin`を`D:\Git\ComfyUI-MV-Director.git`へ設定しました。本プロジェクトでCodexが今後commitを作成した場合は、同じ作業内でそのcommitを`origin`へpushします。

## 2. 読み取った先行資料

旧プロジェクト: `E:\ComfyUI\projects\ComfyUI-cl-japanese2json`

調査時の不変IDは次のとおりです。

| 対象 | 調査時の値 |
|---|---|
| 現在ブランチ | `v0.3.0` |
| 現在HEAD | `6bd80ec8e2db2bde26722f93193606621f0cf1f8` |
| `v0.4.0` | `1fce488b6f23ea2248f395a21f2ad8f5e08edf9d` |
| 対象stash | 調査時`stash@{0}`、`On v0.4.0: v0.4.0 design documents before v0.3.x hotfix` |
| stash object | `76786911cce85182238dc3f118a470ec403fd26d` |
| stashの未追跡ファイル親 | `0ebf6031950d13e9a6c2d5534e3a2afad5f3c996` |

確認した主要資料は次です。

1. 作業ツリーの`docs/report/v0.4.0-artistic-output-policy.md`
2. `v0.4.0`の`docs/report/v0.4.0-planner-review-report.md`
3. 対象stashにある同レポートへの8GB/16K追記
4. stash第3親の`docs/report/v0.4.0-local-llm-design-discussion.md`
5. stash第3親の`docs/spec/planner_context_budget_spec.md`
6. 旧Enhancer、Planner、Compiler、Vision、Vocal、GGUF、cache、utilityの仕様・コード・テスト・同梱workflow
7. 現在インストール済みContext Loop 0.6.9、commit `9860a063784c8c23b58e00107f2180e0df3c43d9`の`docs/AUDIO_AND_CONTINUITY.md`、`H3_CHAIN_FORMAT_GUIDE.md`、Plan parser及び`web/h3_prompt_schema_core.mjs`

stash番号は将来変わり得るため、後続調査では上記object IDを使うことを推奨します。

## 3. 所在を再確認した資料と実ログ

次は2026-09-15時点で存在しました。

| 種類 | 現在位置 |
|---|---|
| 旧統合workflow | `E:\ComfyUI\projects\ComfyUI-cl-japanese2json\workflows\minimax_h3_ref2va_integrated_mv_generator.json` |
| 旧短尺workflow | `E:\ComfyUI\projects\ComfyUI-cl-japanese2json\workflows\minimax_h3_ref2va_integrated_mv_generator_short.json` |
| ComfyUI側統合workflow | `C:\Software\ComfyUI\user\default\workflows\minimax_h3_ref2va_integrated_mv_generator.json` |
| ComfyUI側短尺workflow | `C:\Software\ComfyUI\user\default\workflows\minimax_h3_ref2va_integrated_mv_generator_short.json` |
| Planner debug | `C:\Software\ComfyUI\output\cl_mv_prompt_planner_debug` |
| 比較出力 | `C:\Software\ComfyUI\output\v2p_plan_prompt_00006.txt`、`v2p_plan_prompt_00007.txt` |
| Context Loop | `C:\Software\ComfyUI\custom_nodes\ComfyUI-MiniMaxH3-Contex-Loop` |

同名workflowのほか、`integrated_mv_generator_hd`、`metal_test`、`old_test`等もComfyUI側に残っています。初期回帰基準は名前の明確な統合版と短尺版に限定し、派生テスト版を暗黙の正解にしません。

統合workflowの配線も確認しました。同一のIMAGE出力が`CLImageAnalyzerVisionGGUF`と`MiniMaxH3ReferenceToVideo.ref_image_0`の両方へ接続されており、画像観察とH3参照を同じ入力へ固定できる構成です。新workflowではImage to Subject EMDの`auto_h3`がhidden実行graphを読み、同じIMAGE出力の`ref_image_0..8`接続から`<Picture 1..9>`を確定する。異なるPicture番号への分岐は曖昧エラーとし、解決結果をbinding fingerprintへ含める。これは配線の根拠であり、映像品質の実測結果ではない。

旧Visionの自然言語入力は`subject_hint`と`additional_instruction`であった。前者は人物の意味・同一性を補助又は固定し、後者は眉、瞳、衣装等の観察焦点を指定した。新Image to Subject EMDでは意味のある各項目を外部socket化し、`concept_type`、`concept_index`、意味上の`subject_index`、物理入力の`picture_index`を分離する。Picture制御は`auto_h3`、`manual`、`none`とする。

旧Visionの`cl-vision-observation-line-v2`はJSONではなく、固定順TAB区切りrecordからPythonがtyped observationを作る構造であり、新実装にも適合する。record構成、category、visibility、hint assessmentと一意な列補正だけを`MVD_VISION_OBSERVATION_LINES_V1`／`MVD_OBSERVATIONS_V1`へ改名して抽出する。旧Markdown renderer、画像なしLLM repair、英日翻訳repair、再観測retry及び旧ID互換は移植しない。新rendererはperson/object/location別の`# サブジェクト`だけを作り、pose、構図、照明、source style及びvisible textを恒常条件へ入れない。

## 4. コードから確認した事実

### 4.1 SceneとShotの由来

旧`node_vocal_to_prompt_segments/node.py`の`build_scenes()`はVAD有声区間を秒単位へ外向きに量子化し、無音との連続範囲を作り、既定10秒以下へ均等分割します。歌詞の整列時刻が重なる無音Sceneは有声へ昇格し、`normalize_chainable_scenes()`が継続に短すぎる中間Sceneを調整します。新方式はこの整数秒量子化を破棄し、Whisperで歌詞位置を検出します。20ms VADを粗探索に使った後、開始・終了近傍をsample-domainで再探索し、決定sample indexから`MVD_TIMELINE_V1`の整数msを得ます。1ms値は再現可能な決定値ですが、音響的正解はthresholdと入力品質に依存します。

新プロジェクトではこの有限な時間処理を公開support node `MVDirectorLyricSegmentation`へ抽出します。歌詞とpadding前のボーカルだけから新形式のTemplate EMD、標準SRT、`MVD_TIMELINE_V1`、statusを返し、LLM、Image to Subject EMD、Planner、H3実行なしで字幕用途に単独利用できます。MV用TemplateではH3 Timing Profileに従いContext Loop互換raw `length`を上流で確定し、`` `H3長` ``として書く。Plannerはこれを保持し、Compilerは再計算しません。

旧`node_mv_prompt_planner/timeline_parser.py`はこのSceneのduration、絶対ソース範囲、歌詞、lip-sync、soundscapeを固定します。一方、`PlannedShot.start_ms`は旧PlannerのLLM生成物で、`renderer.py`が`## ショット N秒`として書き出していました。新EMDは旧表記を受理せず、各Sceneの直前へ必須の``> `シーン` N``を置き、Sceneを`# シーン START --> END`、全Shotを`## ショット TIME`として絶対`MM:SS.mmm`で記録します。CompilerはScene番号を`scene_NNNN` IDへ写し、エラーとログでも時刻範囲と併記します。

従って「SceneとShotの時間枠がどちらも既存の音声由来」という扱いは誤りです。新方式では要求SceneをWhisper整列とVAD境界から作った後、Lyric SegmentationがContext Loopのraw格子とcontinuation contextへ合わせてplan Sceneを確定する。Shotは整列済み歌詞時刻からPythonが作る。CompilerはH3 prompt用Shot相対時刻を機械計算するだけで、Scene `length`はEMDの`` `H3長` ``を無変換で使います。

### 4.2 不安定化した経路

先行ログと旧コードは次を示します。

- 動作語句の正規表現と段階数は、自然な動作を未計上し、不自然な反復を合格させた。
- Scene生成、診断、固定ACTION再出力、修復、上位Scene再生成が連動し、局所失敗が全体停止へ広がった。
- 旧Enhancerは時刻語彙の文字一致、source分類、固定profile行追加、正規化重複除去、Prompt Merger、任意の意味レビューを重ねる。
- 旧Compilerは翻訳、参照保護、辞書、意味監査、修正案、変更判定、再監査を同系統LLMへ要求する。監査・修正側も誤るため、推論段数の増加が独立な正しさを保証しない。
- 旧Plannerの8B profileは正確なShot数、ACTION段階、AUX_VISUAL数、固定camera sequence等を同時に要求し、出力契約自体が大きい。

これらを削る目的は検証放棄ではありません。Planner等の生成nodeは各自の出力schemaを検証しますが、CompilerはEMD文法のparse、prompt本文だけの英訳、固定JSON写像に限定します。意味、作品品質、実音声、実参照接続はCompilerの責務にしません。

### 4.3 16K予算

旧PlannerにはSceneバッチ分割がありますが、Song Bibleへsection別歌詞を一括投入する経路は別に存在しました。Sceneバッチを1へ下げるだけでは長尺歌詞の上流入力は縮みません。旧共通GGUF backendの`count_input_tokens()`もチャットテンプレート込みの厳密値ではなく、固定余裕を加えた推定です。

新方式はファイルサイズや本文だけでなく、system、profile、payload、出力予約、chat template、安全余裕を含む最終要求全体を予算化します。測定不能時は「予算確認済み」と報告しません。

### 4.4 Context Loopの音声契約

基準Context Loop 0.6.9では、最終音声`source` / `generated` / `none`はChain Policy全体の一択です。Sceneごとに上書きできるのはgeneration-timeの`source_reference`、`generated_continuity`、`source_audio_target`です。Sceneでlip-syncをoffにしても、global final audioがsourceなら完成動画のフルミックスは残ります。

Context LoopのScene overrideだけではglobal final audioを変えられませんが、Compilerにその整合性を背負わせません。`## 音響`を省略したSceneでは音声keyを出さずChain Policyを継承します。`無音`と明記した場合だけ、generation-timeの3軸を`off`にし、silence prompt要素を出します。MV用途では即時の真の無音を要件にせず、PCM gateは初期スコープへ含めません。

Context LoopのH3 Audio Tracksはfull mixがあればそれを最終音声に使い、vocal stemを重ねません。vocalはlocked generation target / lip-sync駆動用です。両者は`MVDirectorAudioPadPair`へ同時入力し、同起点・同尺にします。単体Audio Padは使用しません。Planner解析とLip-Sync Optionsにはpadding前の元vocalを渡します。

EMDはEasy MarkDownの略であり、Extended Markdownではありません。文書順は`# サブジェクト`、任意の`# 保持分析`、任意の`# 共通プロンプト`、1個以上の`# シーン`です。共通プロンプト直下の`## スタイル`、`## モーション`、`## カメラ`、`## その他`もすべて任意です。Context Loop 0.6.9ではPlan `prompt_prefix`が各Scene promptより前へ空行二つで機械連結されるため、Compilerは見出しを捨て、存在する本文をStyle、Motion、Camera、Otherの固定順で平坦化して`prompt_prefix`へ一回だけ写します。Styleが存在すれば先頭で、全区分がなければfieldを出しません。Enhancerは四方向を分離して返し、入力Subjectを読み取り専用contextとして扱います。concept EMDとuser requestが同時に空でも既定profileだけで動作します。Subject定義には参照画像の元媒体を固定条件として書きません。prefixだけで十分かScene内にもStyle文を反復するかはH3実出力のA/B試験で決め、Compilerの意味推測で複製しません。

現行の`MiniMaxH3LipSyncOptions`はvoice AUDIOから`H3_LIP_SYNC_OPTIONS`を生成する外部経路です。この経路を使用すると、8GB VRAM環境では下流の追加モデル読み込み・初期化で停止する事例があります。本プロジェクトはこの外部nodeを修正又は移植せず、EMD Compilerの機械変換だけで成立する二つの代替を持ちます。``リップシンク Audio参照``は対象概念と`H3音声N`を固定英文と`<Audio N>`へ変換します。Audio参照動画生成WFは事前分割ファイルを要求せず、Audio Pad Pairの`source_scenes_to_plan` modeがLyric SegmentationのScene source境界から参照専用trackを作ります。各source SceneをH3の累積delivered frame位置へコピーし、量子化余剰だけをScene末尾PCM無音にするため、Context LoopがPlan frame windowで切り出しても区間内の無音を保った一個の`<Audio 1>`を供給できます。歌詞の場合はLyric Segmentationが空白・改行でatomic segmentへ分け、Template EMD、timeline、SRTを同じsegment列から作り、対応Shotの直前へ歌詞annotationを構造配置します。Plannerは時刻包含を再計算せず、そのShotへ対象と原文を持つ``リップシンク 歌詞``を出します。Compilerはannotationを参照せず、所属Shotの開始位置とこの明示directiveだけを対象付き`<d>[Japanese]...</d>`へ変換します。これはH3へShot区間内の歌唱口形を促すもので、音素単位の完全同期ではありません。どちらも翻訳LLMと`H3_LIP_SYNC_OPTIONS`を使いません。

Shot本文の`「...」`は内容を変えず`<d>[Japanese]...</d>`へ包むだけにします。作者が既に書いた`<d>...</d>`又は`<d>[English]...</d>`はopaque spanとして翻訳せず、そのままH3へ渡します。話者やsource audioとの一致は監査しません。追加発声禁止が必要な作者は`明示台詞のみ`を明記し、Compilerはその場合だけ対応prompt要素を出します。歌詞annotationは直接台詞へ変換しません。

EnhancerとPlannerのLLM出力にJSONを使いません。`MVD_LLM_RECORDS_V1`として`TYPE<TAB>SLOT<TAB>TEXT`の一行一recordだけを返させ、短いslotから実Scene/Shot IDと時刻への対応はPython side tableが所有します。LLMはheader、終端marker、JSON escape、実ID又は時刻を生成しません。Pythonがrecordを解析して`MVD_DIRECTION_V1`、完成EMD及び下流JSONを構築します。旧実装から再利用するのは行指向の境界だけで、入れ子blockや意味repairは持ち込みません。

`MVD_DIRECTION_V1`はユーザー記述形式ではなくEnhancerからPlannerへの任意typed artifactです。四方向と、入力・採用行・機械的破棄だけをPythonが記録した最小provenanceを持ちます。LLMの意味判断や上書き理由は推測しません。Enhancerは確認用EMD previewも返しますがPlannerはartifactだけを読み、未接続でも動作します。Plannerは旧llama.cpp調整socketを維持し、完全表は最小コア仕様7.4を正とします。

人物動作を先に生成し、camera taskは確定actionを読み取り専用contextとして受けます。同じShotでは両者を全区間で並行させ、action、cameraの順に出力します。数値sub-timeとmid-shot cutは生成せず、cutはLyric Segmentationが既に確定したShot境界でだけ表現します。

Plannerでは作者由来の`「...」`と明示`<d>...</d>`をLLM前に`__MVD_LOCKED_DIALOGUE_NNNN__`へ置換し、Python side tableへ退避します。採用したLLM行recordの本文に新規の引用台詞、dialogue tag又はplaceholder echoがあればspan全体を無条件削除します。作者原文はSubject、Direction又は作者Shot本文のPython所有位置から一度だけ出力し、引用出現、削除又は未使用placeholderを理由にLLMをretryしません。Plannerが歌詞から作る``リップシンク 歌詞``はこのfilter後にPythonが挿入します。

### 4.5 新ノードの名前空間

旧プロジェクトはworkflow保存用type IDに`CL...`、表示カテゴリに`MiniMax H3/...`を使っていました。新プロジェクトでは`MVDirectorImageToSubjectEMD`を含む4コア、support 2個、utilityのH3 Timing Profile、32-bit Seed、String Combo、Connected Combo、Load Text Fileを機械向け`MVDirector...`、custom socketを`MV_DIRECTOR_...`、表示カテゴリを`MV Director/...`へ固定します。旧名の互換aliasは登録しません。全Python node packageは`nodes/node_*/`へ集約します。

### 4.6 4コアと疎結合境界

画像認識から編集可能な`# サブジェクト`断片を出す`MVDirectorImageToSubjectEMD`を第4コアとする。Subject recordは`# サブジェクト`直下の単独内部ID directiveから開始し、内部IDを`##`見出しにしない。`<Subject N>`は人物に限らない意味上の主体、`<Picture N>`は物理画像slotとして同じrecordで関連付ける。`人物N`、`場所N`、`物品N`はそれぞれperson、environment、objectの固定文型へ写す。`auto_h3`は同一IMAGE pass-throughを通常Ref2VAの`ref_image_N`へ直接接続したgraphからPicture番号を取得し、ノード内へ`<Picture N+1>`を読み取り専用表示する。`manual`と`none`も持つ。初期の自動MV経路は一個のImage to Subject EMDだけをEnhancerとPlannerへ分岐し、両ノードとも複数断片を統合しない。

初期H3 adapterは通常Ref2VAへの固定番号直接接続だけを対象とし、`ref_images.ref_image_N`を`<Picture N+1>`、`ref_audios.ref_audio_N`を`<Audio N+1>`へ写す。Tagged Referenceの`@tag`再番号付けは扱わず、必要なら将来のversioned adapterとする。

Compilerは完全Ref2VA EMD文字列、H3 Timing Profile、翻訳mode、選択GGUFとruntime設定だけで単独実行できるものとする。日本語prompt本文だけを英訳し、各Sceneへ正規Ref2VA六セクションを出す。EMDにない六セクション必須欄はLLMに補わせず、Scene本文の一行コピーと固定の保持・音響no-op文で機械的に満たす。先頭Shotは`[Shot 1]`、後続は`[Shot N] At MM:SS.mmm,`とする。IMAGE、AUDIO又はworkflow graphは要求しない。`人物N`等と`<Subject N>`は必須だがPicture関連は任意で、なければ文章定義だけのH3内蔵概念としてRef2VAを出力し、T2VAへfallbackしない。

Timeline PlannerはMV専用とし、外部接続可能な`lip_sync_mode`（`off`、`context_loop`、`audio_reference`、`lyrics`。既定`lyrics`）で口形方式だけを切り替える。EMDは``リップシンク Context Loop``、``リップシンク Audio参照``、``リップシンク 歌詞``へ統一し、`off`ではdirectiveを出さない。歌詞annotationは全modeで完成EMDへ保持し、人物動作・演出にも使う。mode切替は口形directiveのmaterializeだけを変え、歌詞を物理削除しない。

「最終音声として保持」は人間がEMDへ書く条件ではない。標準構成は三方式ごとのPlan/Compiler WFと動画生成WFを一対一にした計6 WFとし、完成動画のsoundtrackは後者のContext Loop Chain Policyが所有する。Plannerに`lock_source_audio`を設けず、EMDに`ソース音声固定`を設けない。Context Loop方式のCompiler出力にある`source_audio_target: "locked"`はgeneration-timeのsource音声ターゲットであり、最終音声選択ではない。実装前に監査した境界と解決内容は`docs/research/spec-gap-audit-2026-09-16.md`にまとめた。

### 4.7 GGUF選択と4B baseline

PromptTranslatorを第5の公開nodeにはせず、Compiler内部adapterとして扱う。旧実装と同じくComfyUIの`models/LLM/GGUF`と追加`LLM` rootから利用可能なGGUFを列挙し、Compilerの`model_name` comboで選択する。modelはハードコードせず、実GGUF比較では選択pathのfingerprintとruntime設定を試験記録へ含める。Compiler wrapper自身には独立cacheを設けない。

8GB VRAM向け初回baselineは4B `Q5_K_M`、`n_ctx=32768`、Q8 KV cache、Flash Attention、実行後unloadとする。提示されたMungert版はQ5_K_Mが約2.89GBだが、model cardに元model、license、評価の記入がないため組込み既定にはしない。利用者が配置したGGUFの一候補として扱い、公式Qwen版と同じ翻訳fixtureで比較する。

## 5. 先行文書から変更した判断

| 先行案 | 本プロジェクトの初期判断 | 理由 |
|---|---|---|
| 歌詞・音声時間解析をPlanner内部だけに置く | `MVDirectorLyricSegmentation`としてTemplate EMD、SRT、typed timelineを単独出力する | SRT生成を本MV pipeline外でも使え、PlannerでWhisperを再実行せずに済む |
| Sceneを整数秒、ShotをScene相対秒で書く | 歌詞・SRTは元音源ms、plan Sceneはdelivered frame累積から`MM:SS.mmm`へ直列化する | 音源解析時刻とH3格子を明示的に分ける |
| Context Loop Planへ`duration_seconds`と`length`を併記する | Lyric Segmentationがraw `length`を`` `H3長` ``として確定し、Compilerは`length`へ無変換で写す | Compilerによる再量子化と時間ずれをなくす |
| 旧プロジェクトとの互換性を維持しながら改修する | 互換性は基本的に破棄し、新仕様に必要な有限処理だけを選別して再利用する | 新規プロジェクトへ旧flag、fallback、repair、validator及び不要nodeを連鎖的に持ち込まない |
| `performance_review=review/extend`を主経路候補にする | 主経路へ入れない | 診断・追加・再診断が再び失敗経路を増やす。作品評価は人間が行う |
| Song Bibleに全セクション方針を持たせる | 局所歌詞解釈と短い全体方針へ分割 | 全歌詞・全出力の反復投入を避ける |
| 8B/27Bを別の演出profileとして扱う | 演出profileとmodel execution profileを分離 | モデル差は分割粒度・予約量の差であり、作品意図ではない |
| 固定ACTIONを修復LLMへ再出力させる | 動作とカメラを別タスクにし、Pythonが同じShot IDへ合成 | 転記失敗をなくし、責務を小さくする |
| 旧6セクションFull-Reference文を削る | Ref2VA専用Compilerが各SceneへContext Loop正規六セクションを出す | 現行H3 prompt schemaへ合わせ、T2VA等を混在させない |
| `<Subject N>`を画像slotとして扱う | `# サブジェクト`で意味上の`<Subject N>`を必須定義し、物理入力`<Picture N>`は任意で関連付ける | PictureなしのH3内蔵概念とPicture付きSubjectを同じRef2VA文法で扱う |
| `//`やC/HTMLコメントでmetadataを運ぶ | 予約ラベル付きMarkdown引用行 | 標準Markdown表示と機械識別を両立する |
| 複雑な`## 音響`組合せと省略fallback | 排他的な``リップシンク Context Loop``／``リップシンク Audio参照``／``リップシンク 歌詞``と基本音響flagだけを固定写像 | 書かれた条件だけをJSON／prompt要素にし、最終soundtrack、音響の意味監査又はLLM変換を持ち込まない |
| `## 音響`省略を無音扱いする | Scene固有keyを出さずChain Policyを継承 | 省略と`無音`フラグを区別する |
| `「...」`又は明示`<d>...</d>`を通常promptと一緒に英訳・source audio検証する | 日本語括弧は`<d>[Japanese]...`へ包み、既存d-tagは言語labelを含めそのまま保護し、周囲の描写文だけを英訳する | H3向け英語promptと作者指定の発話を両立する |
| Vision観察をEnhancerの補助入力に留める | Image to Subject EMDを第4コアにし、サブジェクトEMDをprimary出力にする | 画像認識結果を人間が確認・編集・再利用できるようにする |
| `subject_hint:`形式の文字列を利用者へ要求又は互換解釈する | `subject_hint` socket全体を自然言語データとして扱い、プレフィクスなし日本語だけを正式入力にする | 新規プロジェクトのため旧形式parserを持たず、UIラベルと入力データを分離する |
| EMD内部IDをH3画像番号として扱う | `人物N`等、`<Subject N>`、`<Picture N>`を別fieldとして関連付ける | 作品内ID、意味上の主体、物理入力を混同しない |
| Compilerが上流artifact又はgraphを要求する | 完全EMD文字列と選択GGUFだけで単独compileし、必要参照一覧を返す | 手書き・外部生成EMDを上流nodeなしで利用可能にする |
| 単体Audio PadとAudio Pad Pairを両方移植する | `MVDirectorAudioPadPair`だけを再利用し、単体Audio Padは登録しない | full mixとvocalの二本を一つの基準尺で扱う実workflowに限定する |
| String Combo / Connected Comboを汎用utilityとして削る | 両方を`MVDirector...`名で残す | user-defined候補と、サブグラフ内部comboの外部操作は別々の実用的責務を持つ |
| Load Text Fileを既存汎用nodeへ任せる | `MVDirectorLoadTextFile`として残す | 歌詞ファイルを選択/D&DしてLyric Segmentationへ直接渡せ、workflow単体でも本文を再現できる |
| 32-bit Seedを各nodeの内部変換だけにする | workflow-persistentな`MVDirectorSeed32`を残す | GGUFとH3へ同じ再現可能seedを一つの出力から分岐できる |
| 旧コアを削りながら例外を追加する | 新しい4コアを空から実装し、旧コードは比較資料として残す | 過去の修復経路を新設計へ持ち込まない |

## 6. 維持する価値がある知見

- Visionは見えている形、色、数、衣装、材質を観察し、名前・履歴・画面外を推測しない。
- `auto_h3`では画像観察とH3参照を同じIMAGEテンソルから分岐させ、宣言Pictureが別画像へずれる余地を減らす。`none`ではPicture関連を作らない。
- 画像で不明な顔やキャラクター特徴は短いユーザー指示をauthorityとして使う。
- 顔立ち、頭部構造、体格、衣装層、身体付属物の数と形は、正面・側面・背面・遮蔽後の再登場を通じて同じ設計として記述する。
- 人物動作は接地、重心、手と対象の接触、衣装・髪の追従を具体化する。ただし段階数を合格条件にしない。
- カメラは開始視点、移動経路、終了視点、前景と遠景の視差を具体化し、人物動作をカメラ運動だけで代用しない。
- 旧統合workflowで実際に使われていた重要特徴の記述は、金色の豆粒形眉、目・虹彩の領域分離、顔を判別できる画面サイズ、夜間の月光、鳥居・参道・社殿の位置関係など、H3へ伝わる肯定的で視覚的な条件だった。この具体性は残すが、利用者に同量の長文を書かせずEnhancerが統合する。
- 成功cacheは画像や原文、モデル、推論条件、system prompt版を含むkeyで固定し、失敗結果を成功cacheへ入れない。
- seedは言語生成用とH3用を分離して固定可能にする。同じ32-bit utilityは両方へ接続できるが、H3 seedだけ変える比較では言語生成成果を再実行しない。

## 7. 非目標

- 任意の翻訳意味を機械的に正しいと証明すること
- H3映像品質をプロンプトの語句数で保証すること
- 4B専用の補修辞書を増やすこと
- クラウドLLM、VRAM増設、常時27Bモデルを前提にすること
- 初期版で動作ごとの細かい時刻表、整合性監査、無制限再試行を作ること
- 初期MV版でScene単位のPCM silence gateを実装すること
- 旧EMDと新EMDを内部で混在させること
- 単体Audio Pad nodeを実装又は登録すること

## 8. 未実測として残す事項

- 8B/16Kでの各タスクの実トークン数、VRAM、所要時間
- 分割増加による一貫性低下と総時間の変化
- 新しいShot境界規則が映像のリズムへ与える影響
- 新プロファイルがH3で改善するかどうか
- Source Timeline lock、vocal lip-sync、保護台詞、最終muxの端点精度

これらは仕様上の保証にせず、実装後にテキスト生成とH3映像を分けて測定します。
