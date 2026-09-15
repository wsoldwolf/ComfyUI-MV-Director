# 実装前仕様漏れ監査

調査日: 2026-09-16<br>
対象: `draft-0.33`最小コア仕様、`draft-0.10` EMD仕様、Context Loop 0.6.6 commit `136db5dbbf25405063a96e898ae880e8785b7f29`

## 1. 今回確定した事項

- 歌詞annotationは口形modeに依存しないcanonical metadataとして完成EMDへ常に保持する。
- 選択歌詞は全modeで人物動作・演出の入力に使える。
- Plannerのコンボは口形の実行方式だけを切り替える。
- `lyrics`だけがShotへ``リップシンク 歌詞``をmaterializeする。その他のmodeではmaterializeしないが、歌詞を物理削除しない。
- Compilerは歌詞annotationからlip-syncを推測せず、明示directiveだけを機械変換する。
- mode又はAudio slotだけの変更では人物動作・カメラを再推論しない。
- P0-3はLyric Segmentationで解決する。空白・改行でatomic segmentへ分け、Template EMD、timeline、SRTの同一ソースとして一個のSceneとShotへ確定する。

## 2. 実装開始前に確定が必要な事項

### P0-1. Context Loop標準リップシンクと最終音声方針の分離（解決済み）

基準Context Loopでは、Sceneの`source_audio_target: "locked"`はgeneration-timeのsource音声ターゲットであり、完成動画の最終音声選択ではない。最終音声の`source` / `generated` / `none`はPlan-wideのChain Policyが所有する。また標準リップシンクは、Source Timeline又はH3 Audio Tracksのvocal入力、Generation Profileのaudio profile、必要に応じた`H3_LIP_SYNC_OPTIONS`配線を含む外部workflow契約である。

「最終音声として保持」は人間がEMDへ書く条件ではなく、Plannerの口形modeでもない。完成動画の音声選択は、下流の動画生成WFにあるChain Policyへ固定する。EMDとPlannerは口を何で駆動するかだけを表し、`ソース音声固定`及び`lock_source_audio`は仕様から除去した。

1. Plannerは`lip_sync_mode`の`off`、`context_loop`、`audio_reference`、`lyrics`だけを切り替える。
2. EMDは``リップシンク Context Loop``、``リップシンク Audio参照``、``リップシンク 歌詞``の統一語彙を使う。`off`ではdirectiveを出さない。
3. CompilerはContext Loop方式の時だけSceneのgeneration-time値`source_reference=off`、`generated_continuity=off`、`source_audio_target=locked`と固定promptを出す。これは最終soundtrack保持を意味しない。
4. 標準配布は三方式ごとのPlan/Compiler WFと動画生成WFを一対一にした計6 WFとする。後者がvocal、Audio参照、Generation Profile、任意Lip-Sync Options及び最終音声Chain Policyを方式別に所有する。

外部配線の不足はCompiler errorではなく、対応する動画生成WFのpreflight statusにする。新規projectなので旧音響directiveのaliasは設けず、旧語は文法エラーとする。

### P0-2. Planner単独利用とCompiler-ready EMDの境界（解決済み）

Picture関連がない場合もRef2VA Compilerを動作させる。人間又はPlannerは`# サブジェクト`で``人物N``等の内部IDと`<Subject N>`を必ず定義し、`参照画像`行だけを省略できる。省略したSubjectは文章定義によるH3内蔵概念として扱う。

Pictureの有無で`compiler_ready`を分けず、一件以上の正しいSubject定義と完成SceneがあればCompiler-readyとする。Picture関連があれば使用分だけ`required_references`へ出し、PictureもAudioもなければ空配列を返す。Pictureを捏造せず、T2VAへfallbackしない。基準Context LoopのRef2VA schemaはPicture必須数を0としており、参照なしSceneも有効である。

### P0-3. 歌詞がShot又はScene境界をまたぐ場合（解決済み）

分割責務をPlanner又はCompilerへ置かず、Lyric Segmentationへ固定した。入力歌詞の物理改行と一個以上のASCII空白、tab、全角空白を明示境界としてatomic segmentを作り、Whisper/VADで各片の絶対msを確定する。重なるsegmentは同じShotへ割り当てる。一個のsegmentがScene上限を越す場合だけ整列済みword境界で派生segmentへ分割する。Template EMD、timeline、SRTは同じ確定segment列から作るため、PlannerとCompilerは分割を行わない。歌詞時刻とScene/Shot時刻は異なるtimebaseなので、Template EMDでは対応Shotの直前へannotationを置き、下流は数値包含で所属先を再判定しない。

### P0-4. `vocal evidence`の判定規則（解決済み）

`vocal evidence`という独立判定を廃止する。`context_loop`又は`audio_reference`では、Lyric Segmentationが一個以上の`歌詞`annotationを構造配置したSceneだけを`lip_sync_active=true`とみなし、対応するリップシンクdirectiveを出す。歌詞文字列、音量又はVAD区間をPlannerが再評価しない。

VADとWhisperはLyric Segmentation内部でatomic lyric segmentのsource開始・終了msを確定するためだけに使う。annotationのない間奏Sceneへはdirectiveを出さない。歌詞にないアドリブも同期対象にしたい場合はplain lyricsへその音節を追加するか、人間が完成EMDへdirectiveを明示する。これによりthreshold依存の二重判定とPlanner側の再対応付けを避ける。

## 3. Phase 1～6までに固定すべき契約

### P1-1. Timeline Plannerの完全なsocket表（解決済み）

最小コア仕様7.4に入力24項目と三出力の型、必須性、既定値、範囲及び表示順を固定した。旧Plannerからllama.cppの`chat_format`、`max_tokens`、`temperature`、`top_p`、`repetition_penalty`、`gpu_layers`、`n_batch`、`n_ctx`、`flash_attn`、`kv_cache_type`、`op_offload`、`keep_model_loaded`及び`seed`を維持する。`n_ctx`は0～131072を選べ、既定16384、4B/32K試験は32768とする。

Direction artifactはユーザーが記述する別形式ではなく、Enhancerの四方向とprovenanceをPlannerへ渡す任意`MV_DIRECTOR_DIRECTION`値である。Enhancerは人間向けEMD previewも返すがPlannerは再parseしない。未接続時は四方向を空として動作する。旧camera/vocal guard、visual enrichment profile、semantic repair及び可変retry回数は移植しない。

### P1-2. Lyric Segmentationの入力文法とbackend（解決済み）

入力はUTF-8 plain lyrics `.txt`だけとし、最初の非空行から`[VERSE1]`等の大文字ASCII section見出しを要求する。空行を無視し、本文行を空白runでatomic segmentへ分割する。LRC、SRT、VTT又はinline timestampを受理せず、SRTは出力専用とする。初期backendは旧実装の`openai-whisper`とローカル`.pt` discovery/runtimeを抽出し、lazy import、word timestamp、no-downloadを維持する。VADは元sample rate・全channel最大RMS、Whisperだけfloat32平均mono・16kHzとする。

### P1-3. Vision出力の最小protocol（解決済み）

旧`cl-vision-observation-line-v2`のrecord構成とtyped observationを、新ID `MVD_VISION_OBSERVATION_LINES_V1`と`MVD_OBSERVATIONS_V1`へ改名して引き継ぐ。旧category、visibility、hint assessment及び一意な決定論的列補正は再利用する。旧ID、旧Markdown renderer、画像なしLLM repair、英日翻訳repair、再観測retry及び互換hint parserは移植しない。新Python rendererだけがconcept typeとPicture/Subject bindingからEMDを作る。

### P1-4. provenance record（解決済み）

`MVD_DIRECTION_V1.provenance`はPythonが作る入力・機械処理履歴に限定する。固定fieldは`record_id`、`record_kind`、`source`、`source_ref`、`source_position`、`target`、`disposition`、`reason`、`sha256`とする。原文は複製しない。

V1で記録するのは入力の供給、妥当なLLM行の採用、空・完全一致重複・protocol不正による機械的破棄だけである。意味上の採用、上書き、破棄又はauthority遵守をPythonの文字列比較から推測せず、LLMにも説明文を作らせない。そのため`superseded`や自由文reasonは設けない。これは再現と診断用lineageであり、chain-of-thought又はsemantic auditではない。



### P1-5. Audio参照の区間供給（解決済み）

入力ファイルを事前分割せず、Lyric Segmentationが確定したsource timelineとScene対応を使って実行時に一個のScene-local vocal sliceを作る。同じSceneへ複数のatomic lyric segmentがあっても個別Audio slotへ分けず、最初のsegmentから最後のsegmentだけを詰めるのでもなく、そのSceneに対応する連続source区間を無音の隙間ごと保持して`<Audio 1>`へ供給する。歌詞の相対位置を失わず、H3の最大3 standalone audio slotを消費し続けないためである。

確認した基準実装では、ComfyUI core `MiniMaxH3ReferenceToVideo`の固定`ref_audio_N`は接続されたAUDIO全体をそのままaudio VAEへ渡し、Plan JSONに参照音声の開始・終了offset fieldはない。一方Context LoopのTagged Audio `source_timeline`はフルtrackを一度接続し、Current Shot stateから現Sceneの正確なsliceを内部生成して最終的にnative `<Audio N>`としてcore Ref2VAへ渡す。従って「事前分割不要」は正しいが、区間選択は`<Audio N>`文字列又はJSON offsetではなくsource timeline adapterが担当する。

初期Audio参照動画生成WFではLyric Segmentationの`MVD_TIMELINE_V1.scenes[].source_start_ms` / `source_end_ms`を正本としてsource timeline adapterへ渡し、固定native `<Audio 1>`へ現Sceneの連続sliceを供給する。歌詞annotationはScene有効化、個々の歌詞区間は整列とSRT、Scene source境界はPCM切出しに使い分ける。複数歌詞segmentの間や歌い出し前の無音は除去しない。CompilerはPCMを切らず、`リップシンク Audio参照`を固定promptと必要Audio slotへ変換するだけとする。入力区間が正確でもH3生成結果の口形が音素単位で完全同期する保証とは区別する。

### P1-6. 人物動作とカメラの時間関係（解決済み）

人物動作を先に生成し、camera taskは確定actionを読み取り専用contextとして受ける。同一Shotの両者は全区間で並行し、rendererはaction、cameraの順に置く。`while`、`as`、`then`又は終端を示す自然な相対表現は許すが、数値sub-timeを生成しない。

Shot枠はLyric Segmentationが所有するため、camera taskは新しい時刻又はShotを作らない。cutは既存Shot境界でだけ表現し、一つのShot内にmid-shot cutを置かない。cameraはactionの内容、開始、終了又は順序を変更しない。

## 4. 実装後の検証事項（仕様未確定ではない）

- 基準commit 0.6.6に対し、`prompt_prefix`、六セクション、Shot時刻、`length`、Scene audio overrideをfixtureで検証する。
- 実装環境のContext Loop checkoutは監査時点で基準commit `136db5dbbf25405063a96e898ae880e8785b7f29`と一致する。試験時にも実commitをpreflight表示する。
- 基準commit合格後、更新が続く現行Context Loopでも同じfixtureを走らせ、差分をadapterへ閉じ込める。
- 8GB VRAMでContext Loop標準、Audio参照、歌詞の三方式を別々に実測し、初期化停止と生成品質を混同しない。
- Styleを`prompt_prefix`先頭だけへ置く場合とScene promptにも明示する場合はH3出力A/Bで決め、Compilerが自動重複しない。

## 5. 実装開始を止めない事項

量子化別の最適context長、H3の画風変換品質、VAD閾値、歌詞口形の精度、カメラ表現の好みは実測で調整する。これらは仕様漏れではなく評価項目であり、初期parser、artifact、Compiler骨格の実装を止めない。

P0-1～P0-4及びP1-1～P1-6は解決済みであり、実装開始を止める仕様漏れはない。第4節は決定済み仕様の互換性・品質検証、第5節は実測による調整値であり、未確定の文法、socket又はartifact契約ではない。
