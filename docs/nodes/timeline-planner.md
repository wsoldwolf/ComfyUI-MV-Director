# Timeline Planner

確定済みTemplate EMDから、Sceneの出来事、人物演技、撮影を順に生成し、完成EMDを返します。現行devはGemma4 31Bを既定とし、Scene Authorだけを使います。旧8B向けPlanner／監査経路はありません。

## 処理と作者所有

1. Eventが出来事・対象・外部effectを計画します。
2. PerformanceがEventと現在歌詞に対応する身体・表情の演技を計画します。
3. CameraがEventと演技を読んで撮影を計画します。

自動演技を生成する場合、Subjectから携行物の一覧をLLMが一度抽出します。携行物があるSceneでは、Eventの後・Performanceの前に、各Shotの所在、左右の手の占有、移行と両立する演技を計画します。PerformanceとCamera、後段補完の候補再選択へ同じ保持計画を渡します。剣・盾などの名詞辞書や、Pythonによる収納・持ち替え文の合成は使いません。

この計画は作者固定の演技・Cameraを変更しません。保持計画の終端は継続Sceneだけに渡し、映像の観測済み状態とは区別します。携行物のない入力ではSceneごとの保持推論を省略し、全ての演技が作者固定なら一覧抽出も省略します。

一覧抽出と保持計画はそれぞれ最大2回の形式回復に限定します。取得できなければWARNINGを残して既存の演技生成へ戻り、新しい意味監査や停止条件にはしません。コンテキストに追加情報が収まらない場合も保持計画を省略でき、作者固定指示と現在Shotの必須内容は残します。構造検査は全携行物IDの受け渡しを確認するもので、H3映像の物理的一致を保証するものではありません。新経路の反映にはPlannerの再実行が必要です。

各要求はScene内の対象Shotをまとめて扱います。元TemplateのScene/Shot時刻と継続指定を保持し、歌詞sectionを読み取り文脈として渡します。歌詞区間全体を現在Sceneへ描写する義務は作りません。

Shotへ直接書いた`演出`、`演技`、`カメラ`は固定し、そのfieldの生成を省略します。ラベルなし作者本文も保持します。完成`# サブジェクト`から始まる全文EMDは検証後に生成を省略できます。Compilerへの直接接続も可能です。

`END_STATE`は本文から分離した輸送metadataです。継続Sceneへだけ引き継ぎ、CUTでは引き継ぎません。映像上の完全な接続を保証する機能ではありません。

Templateの任意`# 音声活動`は、現在Sceneの有声候補・ボーカル不在候補・未確定区間・追加paddingへ切り出して三担当へ渡します。歌詞のないSceneには近接する前後歌詞を各最大4行の読み取り文脈として渡します。イントロ・間奏の身体候補も任意に選べますが、後続歌詞の対象を全部先出しする共通命令や、新しい品質停止条件にはしません。作者固定fieldは変更しません。Audio参照では実PCM再配置表を使い、Context Loopでは末尾paddingを除いて元音声の時刻を使います。検出結果は歌唱の禁止又はH3の時刻指定マスクではありません。

Arcの明示的な周回方向はCamera本文から別途読み取り、Zoom、Pull Out、昇降、Staticを挟んでも継続Sceneまで保持します。CUTでリセットします。時計回り／反時計回りが生成Shot間で矛盾する場合、該当Cameraだけをまとめて一度LLMへ再要求します。PythonはCamera自然文を書き換えず、作者固定Cameraの方向変更を優先します。Rollの時計回り／反時計回りはArc方向と区別します。方向が曖昧な自然文から無理に推定することはありません。

修復成功はINFO、未解消はWARNINGへ記録します。修復要求はSceneごとに1回（行プロトコル欠落回復は既存の有限経路）とし、未解消のCameraは元のLLM文を保持して処理を止めません。H3映像上の旋回を保証するものではありません。既存の完成Planは自動変更されないため、反映にはPlannerからの再生成が必要です。

`arc_roll_policy=selective_arc`のRollは、Arcの大振幅指定から独立した文で`Roll Clockwise with small amplitude`又は`Roll Counterclockwise with small amplitude`を記し、画面の水平0度→約10度→水平0度の短い一往復を計画します。人物を回転させる動作やArcの周回とは別です。これは生成指示であり、H3の傾斜角を数値制御する機能ではありません。作者固定Cameraはそのまま保持します。

## 接続

| 入力 | 内容 |
|---|---|
| template_emd | Lyric Segmentationの時間枠と歌詞、又は作者EMD |
| concept_emd | 人物Visionのemd_fragment |
| concept_emd_2 / concept_emd_3 / concept_emd_4 | 追加のSubject断片。未接続可、統合後の合計は4 Subjectまで |
| scene_emd | 背景Visionのemd_fragment |
| direction | Enhancerのtyped Direction。preview本文は接続しない |
| model_name_override | モデル選択を文字列で上書きする任意socket |

出力は`emd_text`、typed `emd`、`status`です。背景IMAGEをPlannerへ直接渡しません。同じ背景画像は動画WFのPicture 2へ渡します。

Subjectの入力統合はEnhancerと共通の構造処理を使います。通常はEnhancerの`subjects_emd`を`concept_emd`へ接続することで、両ノードが同じSubject定義を参照できます。Plannerへ最大4断片を直接接続する方法も可能です。空入力を除き、入力順・行順で番号を確定し、説明とメディア参照番号は書き換えません。`lip_sync_target`は統合後の番号を指定してください。対応はINFO／statusの`subject_map`と、`save_debug_output=true`のdebug JSONで確認できます。

全文の作者EMDを`template_emd`へ渡した場合は、そのSubject定義が優先されます。別途接続したSubject入力は追記せず、無視した旨をWARNING／statusへ記録します。入力統合と下記の人物別処理はCPU検証済みです。2026-10-13にはGemma4 31B Q4_K_Sで4 Subject・2 Sceneの実推論と単一Subjectの対照推論も完了しました。人物別の演技対象・手の計画・継続状態を取得し、Compilerでは複数Subject関係文の全文英訳を追加しました。配布Plan WFはEnhancerの統合出力を受ける接続へ同期済みです。人物四人の同時演技や、英文の意味・映像品質全体を保証する検証ではありません。

### 演技対象と人物別の状態

Subjectが複数の場合、既存のPerformance要求へ定義済みIDを渡します。応答の任意輸送metadata `PERFORMER=サブジェクトN`は各Shotの主な演技者を示し、`END_STATE`は状態が変わった人物をキーにした短いJSONになります。複数人物の同時演技を禁止する指定ではなく、主役と相手の動きを本文で区別するための情報です。物体・場所を一律に人物として踊らせず、全Subjectの同時登場も要求しません。

CameraへはShot別の演技者IDと演技本文を渡します。対象IDが本文にない生成演技には、PythonがそのIDだけを前置します。動作の意味は書き換えません。metadataは完成EMDの演技本文へ流さず、`save_debug_output=true`の生成内容では`performance_subjects`として確認できます。口元・リップシンク対象は独立したIDのままで、主な演技者へ自動変更しません。

人物別の終端状態は継続Sceneへだけ渡し、CUTでは消去します。新しい演技や作者固定の境界から有効な終端状態を取得できなければ、古い姿勢を確定情報として残しません。演技者metadataが不明でも本文生成は停止せず、本文中に一意の明示Subject IDがある場合だけ構造的に補います。名前や名詞の辞書による人物推定、新しい人物別LLM段階は追加しません。

携行物の一覧は各物の初期所有者をSubject IDで区別します。同じ名前でも所有者が異なれば別の携行物IDです。複数Subjectでは左右の手・移行・演技範囲を初期所有者ID別のJSONで受け取り、所在・終端は引き続き携行物ID別に保持します。場所などのSubjectへ自動で手の計画を作りません。受け渡しはLLMが双方と順序を本文に明記する方式で、Pythonが映像や意味を検証するものではありません。形式が回復できなければ保持計画だけを省略し、通常の演技生成へ戻ります。

## 演出候補と補完

Enhancerの`user_request`に`# 演出候補`を記述します。最大12件、各500文字。候補は現在Sceneの計画に渡す着想で、H3の全Scene共通prefixへ複製しません。

`staging_candidate_policy`は次の二種類です。

- `optional`: 任意の着想として扱う。
- `prefer_matched`: Eventでは現在歌詞に適合する候補を優先検討する。Performanceでは、未固定Shotに2秒以上の連続した無声候補区間があり候補がある場合、そこに合う作者の身体演技候補を優先検討する。強制採用ではない。

無声の伴奏で踊らせたい場合は、演出候補へ「ボーカルのないイントロや間奏で踊り続ける」等の適用条件と動作を明記します。無声を静かな伴奏と同一視せず、口元計画と作者確定Shotは維持します。候補なし、活動情報なし、短い息継ぎ、unknown、padding、フルミックスの完全無音ではPerformanceの追加指示を使いません。Cameraの候補方針は変更しません。新しいソケットやLLM段階は不要です。

採用条件と運用上の注意は[TIPS：演出候補が採用される条件](../tips/staging-candidate-selection.md)を参照してください。

`# モーション補完`は候補とは別の明示合成です。リスト省略はprofileを継承、空リストは無効、非空リストは全候補置換となります。作者演技／一般本文なし、Camera未固定、4秒以上等の適格条件を満たすShotだけを対象にします。複数Subjectの場合、匿名の補完はPerformanceで特定できた演技者一人へだけ適用し、全員へ複製しません。補完本文に作者が`サブジェクトN`を明記した場合は、その対象を優先します。対象が曖昧又は未定義ならWARNINGを残し、その補完だけを見送ります。

`pre_author`では予定補完を演技生成前に示し、Cameraへ合成済み演技を渡します。`post_author`では三段生成後に合成します。`guarded_no_drop`は生成結果を見て既存候補をLLMが再選択します。不正選択は一度再試行し、回復不能なら元の候補を保持します。ただし複数Subjectで適用対象を特定できない補完は前述のとおり見送ります。作者確定演技・Cameraを変更する監査ではありません。

補完の適用理由・出所と選択番号はINFO／debugへ残ります。LLMの演技原文は書き換えず、完成EMDでは別行として合成します。

## runtimeと再実行

配布WFはGemma4 31B Q4_K_S、chat_format=auto、n_ctx=24576、max_tokens=4096、temperature=0.2、top_p=0.9、repetition_penalty=1.05、n_batch=256、flash_attn=true、KV=q8_0です。UIにはモデル、出力長、sampling、GPU層、context、保持、seed、cache等の調整値を残します。型・範囲はnodeのINPUT_TYPESが正本です。

`scenes_per_batch`はScene Authorでは使われないため削除しました。旧WFはジェネレーターの`--sync-planner-schema`で更新します。配線済みの旧widgetは黙って消さず、手動移行を要求します。

cache_modeはreuse / refresh / disabled。生成条件を変えないlip-sync mode切替は生成済み演技・Cameraを再利用し、描画directiveを更新します。音声活動付きTemplateではAudio参照とそれ以外で入力PCM時刻が変わるため、この切替のキャッシュは分離します。旧Planner cacheは使用しません。

lip_sync_modeはoff / context_loop / audio_reference / lyrics。対象と音声slotは`lip_sync_target`、`lip_sync_audio_slot`で指定します。標準lip-syncの実音声配線は対応Video WFで設定します。

## エラーと進捗

必須slotの欠落は局所再要求と一件隔離要求で有限回復します。回復不能なら不完全EMDをCompilerへ流しません。grammarは型・slot・行構造を拘束し、自然文の意味を決めません。

26B IQ2_MのScene Author（Event / Performance / Camera）と31B Q4_K_SのPerformance / Cameraは、初回だけgrammarなしで推論し、同じ行プロトコルで検証します。全slotが有効なら原文を採用し、欠落slotは従来の文法付き局所再要求へ回します。重複行や不明な行など、slotへ安全に帰属できないプロトコル違反は文法付きで同じバッチを一度再要求します。31BのEvent、補完候補の選択、12B、その他のモデルは従来どおり文法付きです。20層GPUオフロードの31B短区間試験では、Eventの文法なし出力が2回とも不正で再要求が逆効果となる一方、Performance / Cameraは各2回とも有効でした。31Bの高速化効果は実機・量子化・入力別に検証が必要で、特に12GB VRAMでのCPU部分オフロードを解消するものではありません。この輸送方式はcache keyに含まれ、既存のcacheを誤って再利用しません。初回の採用・再要求理由はINFO／WARNINGに記録します。

警告の`issue_shapes`は行番号、問題種別、先頭の英数字ラベル、タブ数だけを示し、生成本文は通常ログへ出しません。原因調査時は`save_debug_output=true`と`cache_mode=refresh`で再実行すると、statusに示す`planner_debug` JSONの`trace`に、文法なしの元応答`unconstrained_response`と採用した最終応答`response`の両方を保存します。歌詞・プロンプト・生成本文を含むため、このdebug JSONは公開前に確認してください。

contextは実効値と出力予約・安全余白から事前検査します。履歴を縮小し、必要なら同じSceneのslotを分割します。必須の固定指示・現在slot内容を削除して成功扱いにはしません。

進捗は必要なEvent / Performance / Camera / 補完再選択、携行物一覧と保持計画の主呼出し数とモデル準備を基準にします。一覧が空なら保持計画の予定数を減らします。retry、cache、モデルload時間により実時間との比例は保証しません。`save_debug_output=true`ではtask、要求payload、応答等を保存します。一覧と保持計画は文法付きで推論し、形式失敗・コンテキストによる省略もログに残ります。

[EMD仕様](../spec/emd-spec.md)／[処理フロー](../architecture/direction-planner-flow.md)／[profile仕様](../../profiles/README.md)
