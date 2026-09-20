# MV Director プロトコル仕様

版: `protocol-0.2`<br>
作成日: 2026-09-16<br>
状態: Phase 0実装基準

## 1. 適用範囲

本書はPython module間及びComfyUI custom socketで渡すversioned artifactと、LLMからPythonへ返す行protocolを定義する。EMDは人間が編集する文書形式なので、文法は`emd-spec.md`を正本とする。

V1は後方互換を要求しない。未知schema、旧`CL...` schema又はversionの異なるprotocolを自動変換しない。

## 2. 共通JSON規則

- rootはobjectとし、必須`schema`は完全一致するASCII文字列とする。
- keyは本書で定義したものだけを受理する。各artifactが明記した場合を除き未知keyはエラーとする。
- required fieldの欠落と型違いはエラーとする。
- integer fieldへJSON booleanを受理しない。
- 時刻単位は整数msとし、表示用`MM:SS.mmm`をJSONへ二重保存しない。
- canonical JSONはUTF-8、key昇順、compact separator、非ASCII文字をescapeしない。

## 3. schema registry

| schema | Python型 | 用途 |
|---|---|---|
| `MVD_OBSERVATIONS_V1` | `ObservationsArtifact` | Visionの検証済み観察 |
| `MVD_EMD_FRAGMENT_V1` | `EMDTextArtifact` | Subjectだけの編集可能EMD |
| `MVD_SCENE_EMD_FRAGMENT_V1` | `EMDTextArtifact` | Scene環境だけの編集可能EMD |
| `MVD_REFERENCE_BINDINGS_V1` | `ReferenceBindingsArtifact` | IMAGEとPictureの物理束縛 |
| `MVD_DIRECTION_V3` | `DirectionArtifact` | 六方向、profile ID、保持方針とprovenance |
| `MVD_TIMELINE_V1` | `TimelineArtifact` | source音声、歌詞、Scene、Shot |
| `MVD_EMD_TEMPLATE_V1` | `EMDTextArtifact` | 時間枠と歌詞annotation |
| `MVD_EMD_V1` | `EMDTextArtifact` | 完成EMD |
| `MVD_REQUIRED_REFERENCES_V2` | `RequiredReferencesArtifact` | Compilerが要求するSubject・環境・音声入力 |

## 4. EMD text artifact

```json
{"schema":"MVD_EMD_V1","text":"# サブジェクト\n...","sha256":"..."}
```

`schema`は四つのEMD schemaのいずれか、`text`はLFへ正規化した文字列、`sha256`は正規化後textのUTF-8 SHA-256とする。hash不一致を修復しない。`MVD_SCENE_EMD_FRAGMENT_V1`は`# シーン設定`だけを持ち、文法はEMD仕様を正本とする。

## 5. Direction artifact

```json
{
  "schema": "MVD_DIRECTION_V3",
  "style_direction": ["..."],
  "environment_direction": ["..."],
  "time_lighting_direction": ["..."],
  "motion_direction": ["..."],
  "camera_direction": ["..."],
  "other_direction": [],
  "style_profile_id": "reference_cinematic",
  "motion_profile_id": "natural_performance",
  "camera_profile_id": "readable_depth",
  "retention_policy": "compiler_default",
  "retention_lines": [],
  "provenance": []
}
```

六方向は空文字列を含まない文字列配列で、順序を保持する。`environment_direction`は物理的な場所、構造、地形及び接触可能な物体、`time_lighting_direction`は完成映像の時刻・照明を表す。明示的なユーザー指定は参照画像で観測した昼夜又は照明より上位である。`retention_policy`は`profile` / `compiler_default` / `passthrough`のいずれかとする。`retention_lines`は`passthrough`時だけ非空で、各要素は先頭の`* `を除いたEMD保持record `` `サブジェクトN`: `fully_preserved|partially_preserved` 説明``である。三profile IDはPlannerがテキスト一致推測をせず機械policyを適用するために保存する。provenance recordは次の固定shapeを使う。

標準workflowでは人物identityのConcept EMDと背景環境の`MVD_SCENE_EMD_FRAGMENT_V1`を別入力としてDirection Enhancerへ渡す。Plannerにも同じScene EMDを渡し、完成EMDへAS ISで構造統合する。`MVD_OBSERVATIONS_V1`はVisionのdebug・provenance出力でありDirection Enhancerへ接続しない。動画生成時も人物`<Picture 1>`と環境`<Picture 2>`を別H3参照slotへ束縛する。同一Pictureへ人物と背景の保持責務を集中させると人物identityが参照条件を占有し、環境特徴が希薄化又は欠落しやすいためである。環境専用Pictureは背景再現率を改善するための証拠であり、構図、時刻、照明又は画素一致のauthorityではない。

```json
{
  "record_id": "src_0001",
  "record_kind": "input",
  "source": "user",
  "source_ref": "user_request",
  "source_position": 0,
  "target": null,
  "disposition": "supplied",
  "reason": "direct_input",
  "sha256": "64文字hex"
}
```

値域:

- `record_kind`: `input` / `output` / `discard`
- `source`: `user` / `vision` / `profile` / `generated`
- `disposition`: `supplied` / `accepted` / `discarded`
- `reason`: `direct_input` / `valid_line_record` / `empty` / `exact_duplicate` / `invalid_line_record` / `profile_enforced` / `profile_overridden` / `passthrough_enforced`
- `source_position`: 0以上の入力item又は物理行index
- `target`: 採用outputだけが`style_direction[N]`又は`retention_lines[N]`等を持ち、それ以外はnull

semanticな採用、上書き又は破棄理由を生成しない。

## 6. Reference binding

`MVD_REFERENCE_BINDINGS_V1`のrootは`bindings`配列を持つ。一件は次を持つ。

```json
{
  "concept_id": "サブジェクト1",
  "subject_ref": "<Subject 1>",
  "picture_ref": "<Picture 1>",
  "target_node_id": "42",
  "target_class_type": "MiniMaxH3ReferenceToVideo",
  "target_input": "ref_images.ref_image_0",
  "image_sha256": "64文字hex",
  "binding_sha256": "64文字hex"
}
```

`picture_ref`以下の物理fieldはbinding成功時だけ存在する。unboundを偽のPicture番号で表現せず、bindingsを空にする。

### 6.1 Observations artifact

`MVD_OBSERVATIONS_V1`は次の固定fieldを持つ。

```json
{
  "schema": "MVD_OBSERVATIONS_V1",
  "protocol": "MVD_VISION_OBSERVATION_LINES_V2",
  "overview": "...",
  "primary_subject": "...",
  "hint_assessment": {"status": "consistent", "reason": "..."},
  "subject_features": [
    {"category": "hair", "text": "...", "visibility": "clear"}
  ],
  "subject_pose": "...",
  "scene": {
    "setting": "...",
    "elements": [],
    "lighting": "...",
    "time_weather": "..."
  },
  "composition": {
    "shot_size": "...",
    "viewpoint": "...",
    "subject_placement": "...",
    "depth": "..."
  },
  "style": {"medium": "...", "rendering": "...", "palette": "..."},
  "visible_text": [],
  "uncertainties": [],
  "provenance": []
}
```

`hint_assessment.status`は`not_used` / `consistent` / `ambiguous` / `conflict`、feature visibilityは`clear` / `partial` / `uncertain`とする。feature categoryはVision行protocolで定義した固定集合だけを受理する。provenanceはPhase 3で入力画像、Vision model、hint mode及びprompt版を記録するJSON object配列で、Phase 0ではJSON互換性だけを検証する。

## 7. Required references

```json
{
  "schema": "MVD_REQUIRED_REFERENCES_V2",
  "references": [
    {
      "concept_id": "サブジェクト1",
      "subject_ref": "<Subject 1>",
      "h3_ref": "<Picture 1>",
      "required_input": "ref_images.ref_image_0",
      "purpose": "visual_identity"
    },
    {
      "h3_ref": "<Picture 2>",
      "required_input": "ref_images.ref_image_1",
      "purpose": "environment_reference"
    }
  ]
}
```

`purpose`は`visual_identity`、`motion_reference`、`subject_audio_reference`、`lip_sync_audio_reference`又は`environment_reference`。環境参照は`concept_id`と`subject_ref`を持たず、Subjectとして数えない。Picture、Video、Audioのいずれも不要なら`references`は空配列であり成功である。

## 8. Timeline

`MVD_TIMELINE_V1`は`timebase=source_audio`、`time_unit=ms`を固定し、少なくとも解析条件、`source_audio_duration_ms`、`plan_duration_ms`、`timing_profile`、`lyrics`、`scenes`、`unplaced_lyrics`を持つ。

`unplaced_lyrics`は診断用にschemaへ保持するが、公開Lyric Segmentation nodeの成功出力では空配列でなければならない。一件以上あれば`complete=no; reason=unplaced_lyrics`としてTemplate EMD、SRT及びtyped timelineをすべて`ExecutionBlocker`へ置換し、不完全artifactを成功cache又はPlannerへ渡さない。

Sceneは`scene_number`、Plan基準`start_ms/end_ms`、source基準`source_start_ms/source_end_ms`、`raw_length`、`delivered_frames`、`context_length`、`shots`を持つ。ShotはPlan基準`start_ms/end_ms`を持つ。

歌詞は`segment_id`、`text`、`section`、source位置、`start_ms/end_ms`、確定済み`scene_number/shot_index`を持つ。Plannerは数値包含で所属先を再計算しない。

## 9. LLM行protocol

protocol IDはrequest metadataの`MVD_LLM_RECORDS_V1`で固定する。model応答自身へheader又はfooterを要求しない。

```text
RECORD_TYPE<TAB>SLOT<TAB>TEXT
```

- 一物理行を一recordとする。
- 最初の二個のTABだけが構造delimiterで、TEXT中の追加TABはASCII spaceへ変換する。
- CRLFとCRをLFへ正規化する。
- 空行と、trim後が````又は```text`のfence行だけを無視する。
- typeは呼出しごとの許可集合に完全一致するASCII大文字。
- slotは1以上のASCII十進整数で、side tableに存在しなければ拒否する。
- TEXTは前後空白を除いた後に空であれば拒否する。それ以外の本文は変更しない。
- 同じ`(type, slot)`は最初の有効recordだけ採用し、後続を`duplicate`として拒否する。
- 壊れた一行のために他の有効recordを捨てない。
- required key不足だけを`missing`へ返す。parserはretryを実行しない。

Direction Enhancerだけは、Qwen3-4Bで実測した二つの表記揺れをparser投入前に機械正規化する。独立行の`<think>` / `</think>`を除去し、TABの直後へ連結された既知の`STYLE` / `ENVIRONMENT` / `TIME_LIGHTING` / `MOTION` / `CAMERA` / `OTHER` recordを物理行へ分離する。また同taskでは各typeの有効slotが常に1だけなので、既知typeの正のslot番号を1へ正規化する。nodeはuser messageの先頭へ`/no_think`も付与する。本文の意味修復や欠落recordの合成は行わない。

Plannerはstrict parserの後に全task共通のwrapper recoveryを持つ。`TYPE slot: TEXT`、`slot N - TEXT`及び番号付きlistのようにslotが一意に明示された行は、typeとslot wrapperだけを正規recordへ戻す。複数の未解決slotに対して、fenceと空行を除く非空物理行数が完全一致する場合だけ、request side table順へ位置対応させる。Markdown bullet以外の`TEXT`は変更しない。単一の無番号行、余分な説明行、行数不一致又は重複slotは推測しない。機械復元数はPlanner artifactの`protocol_recovered_count`とnode statusの`protocol_recovered`へ残す。共通parser、未知slot拒否及びcreative textのAS IS規則は変更しない。

Compiler翻訳では360文字を超え、安全な句点・読点境界を持つunitを初回推論前に120文字以下を目標として分割する。通常batchの欠落、日本語echo又は競合重複slotは一件だけで隔離再試行し、隔離後も日本語echoとなる長文には同じ分割回復を適用する。ほぼ完成した英文に少数の日本語だけが残る場合は、英文候補全体を再翻訳せず、連続する残存日本語spanだけを出現順に一意化して同じprotocolへ渡し、英訳を元のspan位置へ機械置換する。同じspanの反復は一度だけ翻訳し、既存英文は変更しない。各chunk又はspanを同じprotocolで翻訳し、全件成功後だけ元の順序又は位置で再結合する。原文内容、slot順及びprotected spanは変更しない。短文、境界なし又はspan cleanup・chunk失敗は停止する。回復過程はtrigger及びspan数を含めINFOへ、成功件数は`segmented_recovered`及び`cleanup_recovered`へ残す。

### 9.1 parse結果

```json
{
  "protocol": "MVD_LLM_RECORDS_V1",
  "records": [
    {"record_type":"ACTION","slot":1,"text":"...","line_number":1}
  ],
  "issues": [
    {"line_number":2,"reason":"unknown_type","raw_sha256":"..."}
  ],
  "missing": [["ACTION",2]]
}
```

issue reasonは`field_count`、`unknown_type`、`invalid_slot`、`unknown_slot`、`empty_text`、`duplicate`に限定する。raw本文は通常artifactへ保存せずhashだけを残す。

### 9.2 taskごとのtype

| task | 許可type | required |
|---|---|---|
| Enhancer | 未固定`STYLE`、任意`ENVIRONMENT`、`TIME_LIGHTING`、`OTHER` | 要求typeのslot 1。locked STYLE及び選択Motion/Camera profileはLLMを経由せずPythonが原文採用 |
| visual-beats | `BEAT` | side tableの全Scene slot |
| song-direction | `DIRECTION` | slot 1。最終EMDへ直接配置しない補助文脈であり、限定再試行後も欠落する場合は警告を記録して空文脈へ縮退する |
| shot-layout | `LAYOUT` | side tableの全Scene slot |
| actions | `ACTION` | side tableの全slot |
| action-audit | `AUDIT` | `anime_emotional_mv`のAction batch内の全slot。本文は`PASS`又は有限理由code付き`REJECT` |
| cameras | `CAMERA` | side tableの全slot |
| translation-ja-en | `TRANSLATION` | batch内の全slot |

Visual BeatはSceneごとの原文歌詞、opening/middle/closing位置、歌詞解決有無、Subjectの`concept_id`と`<Subject N>`だけからなるroster及び直近12件の採用beatから、`感情=...｜根拠=...｜対象=...｜接触=...｜現象=...｜身体主導=...｜終端=...`のScene Cue Cardを一行へ固定する。対象は現在Sceneの原文歌詞又は作者本文だけが認可し、名詞だけなら接触は禁止、外部effectは既定で人物から独立した現象とする。Concept EMDの外見・身体・衣装・材質detailはVisual Beat及びAction requestへ含めず、最終EMDのSubject定義として保持する。Song DirectionはVisual Beat列から感情曲線、section energy、静止と加速及び編集連続性だけを作り、具体物、接触、effect又は人物動作を認可しない。`LAYOUT`のTEXTは`CUT,B0,...`又は`CONTINUE,B0,...`とし、先頭Sceneは`CUT`固定、後続は新しい編集構図なら`CUT`、直前の画像状態とカメラ経路を引き継ぐ時だけ`CONTINUE`とする。各Scene slotへ直前Sceneの歌詞とvisual beat、`first_section_appearance`、`new_sections`及び`section_entry_shot_index`を渡し、同じ物理動作又は接触の次段階なら`CONTINUE`、実行可能な範囲で新section初出Sceneを`CUT`とする。4 Scene以上でCUT/CONTINUEの最低数、同一mode最大3連続又はmode遷移数上限を満たさない場合は、隣接関係を再評価する境界mix requestを一度追加する。完全なCUT/CONTINUE交互列も不合格である。再応答も違反する時はmode列だけを最小変更で構造修復し、自然文は変更しない。残りはPythonが提示した境界IDだけを時系列順に持つ。LLMは時刻を生成しない。Pythonは候補同士も1500 ms以上離れた相互互換集合を作り、選択IDを絶対msへ機械変換し、mode変更後のraw H3 lengthとPlan時刻を累積格子へ再配分する。1 Sceneあたり最大4 Shot、通常は2～3 Shotとし、4 ShotはSceneが8秒以上で各intervalを2秒以上確保できる場合だけ選び、複数Shot時は各Shot 1500 ms以上とする。Scene全体が1500 ms未満の場合は`B0`だけの一Shotを許す。候補数超過、区切り差、重複、順序違反又は未知候補を含む応答は、既知IDの抽出、時系列順整列、重複除去及び最大4 Shotへの切り詰めだけで機械修復し、statusへScene番号を残す。境界mode自体を認識できない場合だけ`CUT,B0`へ機械fallbackする。ActionはMotionを含みCameraを除くDirection、現在SceneのCue Card、Shot終了・長さ・Scene内Shot数、Subject rosterと直近18件の採用actionを受ける。CameraはMotionを除きCameraを含むDirection、確定action、Sceneのcut/continue modeと直近12件の採用cameraを受ける。Song DirectionはAction及びCameraへ直接渡さない。これらの履歴は反復回避用で、LLM応答へ再出力しない。通常profileのAction及びCamera creative textはslot対応後に意味修復せずEMDへ置く。`anime_emotional_mv`のActionだけは、同じLLMを分類専用promptへ切り替えた`action-audit`を通過したTEXTをAS ISで置く。

Visual Beat、Action及びCameraの長いTEXTが、同じrequest内の先行採用TEXT又は直近履歴と完全一致若しくは高い表層類似度を持つ場合、対応するSceneの該当slotだけを最大二回再要求する。retryには`rejected_output`、`must_differ_from`、`diversity_retry_attempt`、`diversity_retry`及び直近と同一batchの採用候補最大12件からなる`forbidden_recent_outputs`を付ける。Pythonは自然文を置換・合成しない。通常profileでは二回の再応答後も類似するslotを品質警告として段階別に数え、`repetition_warnings=total(beat=B,action=A,camera=C)`をWARNINGログとstatusへ記録してCompilerを実行できる。Actionは`action_batch_contract`を持ち、slow、単純な手の上下、作者未指定のlower-body主体及び作者・歌詞未指定の走行に違反したslotだけを`action_quality_budget`として一度再要求する。Cameraは`camera_batch_contract`を持ち、Arc、Tracking、同一Motion Type、slow及び作者未指定のlower-body detailを超過したslotだけを`camera_quality_budget`として一度再要求する。`anime_emotional_mv`は2.5秒以上の適格な非顔slotのおよそ半数だけを長尺Arcへ割り当て、各slotへ`arc_permission=required|forbidden`を付ける。未割当Arcは`unassigned_arc`として同じ一回の品質retry対象にする。`action-audit`は`PASS`又は`REJECT:CODE[,CODE...]`だけを返し、codeを`SEMANTIC_REPETITION`、`PROFILE_CONFLICT`、`INCIDENTAL_FIXTURE`、`UNREQUESTED_LOWER_BODY`、`UNREQUESTED_CONTACT`、`REFERENCE_POSE`、`MISSING_GROUNDED_CUE`及び`FACE_PERFORMANCE_MISSING`へ限定する。`anime_emotional_mv`のActionではaudit reject、残存構造違反及び表層反復を統合して該当slotだけを一回生成taskへ戻し、その後に最終auditを一回行う。初回と最終を合わせてauditは最大二回であり、各roundで最小違反候補を保持する。予算枯渇又はaudit/repair protocol欠落時は最良候補をAS IS採用してWARNINGを記録する。Cameraも一回の品質retry後に初回候補と再生成候補の違反数を比較し、最小違反候補をAS IS採用してINFOを記録する。Cameraの必須slot欠落又はprotocol回復失敗だけは停止する。

Compilerの`translation-ja-en`は描写文の一対一翻訳だけを返す。識別上重要な局所形状、個数、配置、大きさ、色、材質及び否定条件を具体的な物理形状として訳し、特殊形状を一般的な解剖・衣装・装飾名称へ丸めない。slotは各有限batch内で1から振り直し、Pythonが元のtranslation unit順へ戻す。入力JSONはPython所有であり、各slotの原文fieldは`japanese_text`、固定instructionはそのfieldを英訳することを明記する。LLMへJSON出力を要求しない。Qwen3系へはuser message先頭で`/no_think`を指定する。Compiler翻訳に限り、閉じた`<think>...</think>`、文字列`<TAB>`又はTABで囲まれた`TAB`ラベル、`slot N`表記、及び一物理行へ連結された既知`TRANSLATION` recordをparser前に決定論的に正規化する。実測形式の先頭に英訳文が複製されていても、数値slot後の英訳文だけを採用する。必須`TRANSLATION` slotが全て揃う応答に付随した非record行及び未知record型は捨て、同じslotの重複が完全一致する時は一件として扱う。重複本文が異なるslotは一方を選択せず、そのslotだけを一回単独再翻訳する。不正slot、未知slot、空本文、単独再翻訳後の競合又は欠落は停止する。

欠落slot、採用本文に日本語scriptが残るslot又は異なる本文が重複するslotは、正常slotを保持したまま、該当原文だけを`slot 1`として一度だけ隔離再翻訳し元位置へ戻す。隔離再翻訳は入力が一つだけなので、strict parserの問題が`field_count`だけであり、非空英訳候補を一つだけ決定できる場合に限り、裸の一物理行、明示的な単一slot wrapper又は単一translation fieldを持つJSON wrapperから本文をAS ISで復元できる。複数行・複数候補・未知record型・不正slot・競合・日本語script残存は停止する。slot番号、protected token又は英訳本文の意味は推測修復しない。本文がslot番号そのものの場合も日本語script残存と同じ機械条件で一度だけ隔離再翻訳し、再発すれば停止する。

`anime_emotional_mv`のActionでは、一度目の`action_quality_budget`後に残る構造違反や表層反復をaudit前の即時停止条件にはしない。`action-audit`のrejectと統合した有限修復集合を作り、該当slotだけを一回再生成して最終auditを一回行う。最終roundでも残る場合は、slotごとの最小違反候補をAS IS採用し、監査理由をWARNINGへ残す。

`anime_emotional_mv`のVisual Beatは`感情=...｜根拠=...｜対象=...｜接触=...｜現象=...｜身体主導=...｜終端=...`の固定順とする。`根拠`は現在Sceneの原文歌詞又は作者本文からの完全一致引用、`対象`はその引用内の完全一致部分文字列、`接触`は`禁止|許可`、`現象`は`なし|外部自律|身体操作`だけを許す。Pythonはfield順、列挙値及び原文包含だけを検証してLLM本文を書き換えない。無効なCue CardはAction/Cameraへcreative sourceとして渡さず、Scene番号と理由をWARNINGへ出す。 有効Cue Cardが具体対象を持つ場合、`anime_emotional_mv`のActionはScene内の少なくとも一Shotで完全一致対象名と認可済み関係を保持する。全Shotへの反復は要求せず、欠落時はrole優先度で選んだ一slotだけを再要求する。Cue Cardの有効数、無効数及び有効対象はINFOへ出す。scene EMDはVisual Beatだけへ空間supportとして渡し、現在歌詞で認可済みの対象の配置にだけ使う。scene EMD単独では対象、接触又はeffectを活性化できない。Action及びCameraへscene EMDを渡さず、背景PictureとEnvironment inventoryは最終EMD rendererだけが合成する。

Planner v48以降、直前のVisual Beat七field規則は九field規則
`感情｜根拠｜対象｜接触｜現象｜配置｜可視展開｜身体主導｜終端`へ置換する。
対象があるCue Cardは`配置`と`可視展開`を必須とし、対象がないCue Cardは両方を
`なし`とする。`配置`はscene contextを新しい対象の認可に使わず、既に歌詞で
認可された対象の空間anchorだけを固定する。`可視展開`は対象自身の状態、変化、
軌道又は環境結果を固定する。Action Auditの有限reasonへ
`BODY_TEMPLATE_REPETITION`と`INTERNAL_PROTOCOL_LABEL`を追加する。

Planner v49以降、`anime_emotional_mv`のprofile優先Cueでは、検証済みCue Cardの
`配置`を最初の適格な生成Action slot、`可視展開`を次の適格なslotへ割り当てる。
v52以降は、通常coverageがあるSceneでは`face_and_upper_body_accent`を
割り当て対象から除外する。顔ActionがLLM生成であってもこの除外を適用し、
通常coverageだけの順番で`grounded_cue_phase`と`priority_cue_phase`を再配分する。
顔slotのphaseは空とし、顔表情の要求は維持する。適格な通常slotが一つなら
両方のfragmentをそのslotへ割り当てる。全slotが顔の場合は従来の割り当てを
維持し、grounding必須契約を黙って解除しない。Action requestは
`required_spatial_anchor`及び`required_visible_development`を持ち、対応する
LLM生成文字列の完全一致を要求する。Pythonは一致を検査するだけで自然文を
合成しない。有限retry後も欠落する場合は`ACTION_GROUNDING`、内部record label、
裸の番号又はTAB表記が本文へ残る場合は`ACTION_PROTOCOL`として未完了artifactに
する。その他の意味品質は従来どおり最小違反のLLM候補をAS ISで保持できる。

Planner v50以降、Camera profileの`lyric_cue_mode`は`automatic`、
`priority_only`又は`off`を取る。`automatic`では既存Visual Beat requestが
現在Sceneの原文から最も具体的な可視名詞句又は独立effectを選び、検証済み
Cue Cardの対象、`配置`及び`可視展開`をv49と同じ完全一致契約でActionへ渡す。
例えば原文の`御神木`を`木`へ短縮してはならない。Pythonは名詞辞書を持たず、
対象を生成又はAction本文へ挿入しない。`priority_lyric_cues`は任意の回帰
overrideとして残り、`priority_only`で明示一覧だけを使用できる。

Planner v51ではCamera profileの任意metadata `lyric_interpretation`を
`literal|bounded`とする。省略時はliteral。boundedは現在原文で選ばれた
物理対象の限定的・非破壊的な接触を、原文に接触動詞がなくても選択できる。
生成側とAction auditは同じ方針を受け、明示的な作者禁止を常に優先する。
外部effectは自律を既定とし、人物の操作や新しい背景対象の活性化を許可しない。
既存の九fieldと列挙値は変更しない。`身体主導`と`終端`は人物以外が
主導する出来事の動き・結果も記述でき、毎Shotの全身演技を要求しない。
通常の顔accentは引き続き目・口等の表情を要求する。

bounded専用の短いVisual Beat/Action promptは既存taskの別本文であり、新しい
LLM taskではない。Visual Beatの生成時だけ、要求slot、九fieldの順序と
接触・現象の列挙値をGBNFで固定する。本文と対象はLLM生成のまま、原文包含は
従来どおり生成後に検証する。文法制約は対象の意味分類を保証しない。
対応するLlamaGrammar又はchat grammar APIがない環境は明示的なエラーとし、
未制約の出力へ黙って切り替えない。出力token上限による打切りは別途起こり得る。

Visual Beatの`lyric_reading_context`は直前・直後Sceneの各二行、各256文字まで。
空Sceneを飛び越えて検索しない。これは主語・述語・比喩の読解専用であり、
Cue引用の原文集合、priority token検出、対象活性化範囲には追加しない。
Actionは選択されたCueだけを受け、隣接歌詞を直接受け取らない。
新規の区間所有権field、複数Cue出力及び追加監査roundは導入しない。
プロファイルmetadataとprompt本文hashをcache keyへ含める。

小型LLMが外側の正規TSV recordに加えてTEXT先頭へ同じrecord type、slot又は
separator placeholderを重複出力した場合、外側recordでtypeとslotが確定している
時だけ、その重複transport wrapperをparser境界で除去する。この正規化は
Action及びAuditの自然文を生成・要約・言い換えせず、除去したslotをINFOへ記録する。
構文上の重複wrapperではない内部labelは従来どおり`ACTION_PROTOCOL`で停止する。

`anime_emotional_mv`の`CAMERA` TEXTは`MOTION=...｜START_SCALE=...｜END_SCALE=...｜START_VIEW=...｜END_VIEW=...｜PATH=...｜COVERAGE=...`の有限protocolとする。非MOTION fieldはrequest内の許可値から選び、自由文、対象名及び人物動作を出力しない。PythonはMotion/PATH一致、Arc尺、Arc割当、顔Zoom可視範囲及び顔Arc handoffを検証し、選択値を固定H3 Camera文へ直列化する。一回の該当slot retry後も不正な場合は、同じ構造slot contractから対象語を含まない決定論的fallbackを選ぶ。 同一七field計画は同一batch及び直近12 Shotで一回だけ許し、fallbackはScene/Shot identityから複数のArc方向、scale、view及び非Arc motionへ分散する。他profileの`CAMERA` TEXTは従来の自由文protocolを維持する。

Camera profileは任意の回帰overrideとして`priority_lyric_cues` metadataを
`TOKEN:object|symbolic_motif|external_effect`のカンマ区切りで持てる。
Timeline Plannerは設定tokenが現在Sceneの原文歌詞又は作者本文に完全一致する
場合だけ優先Cueを作る。Visual Beatがそのtokenを主対象にしなければ該当Sceneを
一回再要求する。再要求後もCue Cardが不正な場合、無効なCue Card本文は隔離した
まま、元歌詞と一致したtoken、kind及びevidenceだけをAction requestへ渡す。
PythonはAction自然文を生成しない。Shot数に応じて`establish`、`relation`、
`reaction`、`release`又はその複合位相を有限値で割り当て、Scene内の少なくとも
一Actionに各tokenを完全一致で要求する。`external_effect`は`接触=禁止`かつ
`現象=外部自律`を必須とし、人物による生成、保持、収集、誘導又は解放を
`MISSING_GROUNDED_CUE`としてrejectする。優先Cueは歌詞triggerの無いSceneへ
持ち越さない。実tokenはsharedな`planner_policy_contract`へ格納せず、現在Sceneの
entityだけへ渡す。優先Cueを持つSceneはVisual Beat及びAction/Auditを単独request
とし、その採用本文を後続Sceneのrecent historyへ積まない。profile設定tokenが
現在Sceneの許可一覧に無いActionへ出た場合は`unexpected_priority_cue`として
該当slotだけを再要求し、不採用本文はretry promptへ再掲しない。

### 9.3 Compiler翻訳保護token

Compilerが翻訳backendへ自由描写を渡す前に、内部ID、`<Subject 1..4>`、`<Picture 1..9>`、`<Video 1..3>`、`<Audio 1..3>`、`「...」`、明示`<d>...</d>`、MiniMax H3正式Camera directive並びに履物語彙`足袋`、`下駄`及び`鼻緒`をopaque spanとして分離する。履物語彙はそれぞれ`tabi`、`geta`及び`hanao strap`として復元し、その他のopaque spanは原文を保持する。opaque spanはplaceholderを含め翻訳backendへ一切渡さず、その前後にある翻訳対象fragmentだけを翻訳する。Pythonは翻訳後のfragment間へspanを元の順序と位置で機械的に再結合する。境界両側が英数字で密着する時は一個の空白だけを挿入する。このため翻訳backendのtoken欠落、変形、並べ替え又は`足袋`から`geta`への誤訳に依存しない。

`<Video N>`は翻訳保護だけを受けるopaque tokenである。`MVD_REQUIRED_REFERENCES_V2`はSubject Picture、環境Picture及びlip-sync Audioを対象とし、CompilerはVideo接続要求を生成又は検証しない。

## 10. Vision行protocol

protocol IDは`MVD_VISION_OBSERVATION_LINES_V2`。正規record順、category、visibility、空を許すfield及び終端warningは最小コア仕様5.2を正本とする。parserは既知の名前付きrecordの順序入替えと応答再開による重複を決定論的に正規化する。modelがschema wrapperとして生成する`protocol_id`はpayloadの有無や位置にかかわらずtransport metadataとして除外する。`SUBJECT_FEATURE`が本文一列だけを持つ場合は本文を保持して`distinctive_feature`及び`partial`を割り当てる。未知categoryも本文を保持して`distinctive_feature`へ収容するが、本文欠落及びその他のunknown recordは拒否する。Phase 0ではIDとfixtureだけを固定し、parser実装はPhase 3で行う。

LLM行protocolとVision行protocolを同じparserへ無理に統合しない。前者は部分回収、後者は固定順の完全な観察recordを要求する。

Plannerの`ACTION`要求slotは`performance_role`、`CAMERA`要求slotは`editorial_role`を持つ。これらは出力行へ追加するfieldではなく、既存の`TYPE<TAB>SLOT<TAB>TEXT`を生成するための構造的制約である。複数Shot Sceneでは顔・上半身accent、腕・手主体の演技、環境相互作用又は身体方向転換、終端silhouetteを別Shotへ配分する。通常slotではPythonは自然文を合成又は置換せず、LLMが返したTEXTをAS ISでRendererへ渡す。

Compiler内部の翻訳protocolは、要求した全slotが一意に揃っている場合に限り、8B級modelが併記したfield数不正行、未知record type、要求外slot及び同一内容の重複行を非参照の余剰出力として破棄し、要求slotの翻訳本文をAS ISで採用する。要求slotが一つでも欠ける場合、要求外slotを要求slotへ読み替えず、単独retry後も欠落又は競合が残ればCompilerErrorとする。

例外として、リップシンク有効かつ歌詞sectionが初登場するCUT Sceneでは、新section名を持つ最初の歌詞annotationが属するShotを`face_performance_cut`とする。Scene開始と歌詞開始が異なる場合もScene先頭へ前倒ししない。このslotは有限個のRenderer所有構造出力であり、ACTION/CAMERA LLM要求へ含めない。Actionは顔演技中も記述済み眉の個数、compactness、形、配置及び色を維持し、特殊な眉markを通常の長い線状又は弓状眉へ置換しない固定文とする。Cameraは`Zoom In with large amplitude at fast speed`で正面又は斜め正面の頭肩構図から極端な顔close-upへ進み、全行程で両目、両眉、鼻、完全な歌唱口及び顔輪郭を同時に残す固定文とする。固定文はEMDで日本語表示し、Compilerが翻訳backendを介さず正規のH3英語文へ決定的に置換する。これによりEMDの可読性を保ちながら通常slotへの固定phrase漏洩、翻訳揺れ及び顔close-upに対する歩行又は全身Actionの競合を防ぐ。固定顔インサートには同一Scene内の隣接通常slot一個を`face_arc_transition`として対応付け、顔へ入るArc又は顔から全身・環境へ抜けるArcをLLMへ必須要求する。歌詞固有の具体物又はeffectを同じSceneが含む場合、顔インサートだけで唯一のShotを占有させず、通常Shotを少なくとも一つ残す。`anime_story_mv`では適格な通常slotのおよそ3分の1を`long_arc_emphasis`とし、`Arc Shot with large amplitude at fast speed`で始まる60～120度のArcをShot尺の70～90%にわたり継続させる。

Plannerの初回応答でslotが欠落した場合、同一Sceneの欠落slotだけを一度再要求する。そこでも欠落したslotは一件ずつ`isolated_missing_slot`として一度再要求する。通常batchでは単一の無番号行を推測しないが、この隔離要求はrequest side tableに候補が一件しかないため、応答が説明行を含まない単一の非空物理行ならそのTEXTを一文字も変更せず当該slotへ対応付けられる。複数行、空行だけ又は明らかなJSON／Markdown見出しは推測回収しない。隔離再要求後も欠落する場合だけPlannerを不完全として停止する。

`HINT_STATUS`が`consistent`、`ambiguous`又は`conflict`で、固定行`HINT_REASON`の値だけが空の場合は、statusを保持したままwarningとして受理する。理由本文をPythonで合成せず、この欠落だけをformat retry条件にしない。`not_used`は空理由だけを受理する。

全profileで、protocol上「値又は空」と定義された単値recordの行自体が省略された場合は、そのfieldを空文字として復元しwarningを残す。対象は`PRIMARY_SUBJECT`、`HINT_REASON`、`SUBJECT_POSE`、`SCENE_SETTING`、`LIGHTING`、`TIME_WEATHER`、`SHOT_SIZE`、`VIEWPOINT`、`SUBJECT_PLACEMENT`、`DEPTH`及び三つのstyle fieldに限定する。これは空値の構造的正規化だけであり、観察本文を生成又は書換えない。全profileで既知recordの逆順は正規化するが、未知record、必須`HINT_STATUS`欠落又は不正値は推測せず拒否する。

`planner_policy=anime_emotional_mv`では`face_performance_cut`のActionだけをRenderer固定文から外し、通常のACTION line protocolでLLMへ要求する。現在歌詞と直近Action履歴に基づく閉眼、半開き、伏し目、細め又は再開眼を含むTEXTをAS ISで採用する。Cameraは専用Renderer固定文とし、35～55%で読み取れる顔scaleへ到達して短い表情accentだけを保持する。この専用Camera文もopaque spanとして翻訳backendから隔離する。他profileの固定Action及び固定Camera protocolは変更しない。

## 11. protocol変更

### Planner v53：Actionと監査の生成時制約

`anime_emotional_mv`のAction生成は初回・再要求ともGBNFを用い、要求された
slotだけを行順に生成する。`required_spatial_anchor`又は
`required_visible_development`があるslotは、そのLLM由来fragmentからTEXTを
開始する。両方ある場合は配置、最大32文字の接続表現、可視展開の順とし、
それ以降の演技本文はLLMが生成する。顔等のfragment未割当slotの本文は自由とする。
Pythonで生成後にfragmentを挿入する処理はない。従来の完全一致検査は残す。

Action AuditにもGBNFを適用し、要求slotごとに`PASS`又は既知の
`REJECT:CODE`一件だけを生成する。主要な違反一件を選び、複数codeの列挙を
生成に要求しない。既存parserは旧形式の既知複数codeも引き続き受理できる。
有限の出力形式を保証するもので、監査判断の意味的な正しさを保証しない。

監査は最大二回、その間のAction修復は一回のまま。候補比較は、必須文欠落や
内部protocol混入の数を最優先し、その後に品質違反数、反復、監査違反数を
比較する。品質違反が少ないという理由だけで構造不正な候補へ戻さない。
トークン上限での途中終了等は別途起こり得るため、構造不正時の停止は維持する。

### Planner v54：歌詞行Discoveryと対象先行Cue

組込み`bounded + automatic`では`lyric-cues`をVisual Beat前に追加する。
入力slotの`text`は現在Sceneの歌詞又は作者本文一行。応答は既存行envelopeの
`DISCOVERY<TAB>SLOT<TAB>KIND|TARGET`とし、KINDは
`motif|effect|place|body|none`、noneのTARGETは`なし`、それ以外は原文中の
非空の連続文字列に限定する。構文と原文一致は意味分類の正しさを保証しない。
全曲で同一行を重複推論せず、16行ずつ、出力上限`min(max_tokens,768)`で要求する。
欠落は共通の有限protocol retryへ渡す。未知kindや原文外targetは採用しない。

Scene内の最後のmotif/effect/place候補一つを選び、body/noneは除外する。
空候補も明示して対象なしに拘束する。作者の明示優先Cueはこの自動選択より上位。
候補kindを接触・現象の許可へ写像しない。

boundedのCueは九fieldのまま、wire順序を`対象、根拠、感情、接触、現象、配置、
可視展開、身体主導、終端`とする。parserはこの明示順序と従来の感情先行順序を
識別し、値を変更せず同じtyped fieldsへ読む。返却されたBEAT本文は並べ替えない。
選択済み候補がある場合、GBNFは対象とその原文行の根拠を同じ分岐に固定し、配置も
対象文字列から開始させる。それ以降の文章はLLMが生成する。隣接歌詞と背景は
対象候補の出典にしない。これは内部Planner v54のwire契約であり、最終EMDと
外部artifact schemaの変更ではない。旧cacheはalgorithm versionで分離する。

### Planner v55：生成Shot文の不要な行継続記号

ユーザーの明示要求により、生成ACTION/CAMERAのTEXT末尾で、ASCII空白・TAB・全角空白
に区切られた単独のバックスラッシュ一文字だけを削除する。直前と直後の区切り空白も除去する。
除去後が空になる場合、文中の記号、二重バックスラッシュ、通常のパス及び引用内の記号は保持する。
これは生成演技の意味修復ではなく、行末の書式残滓に限る正規化である。
共通record adapterで初回・再試行の採用値に適用し、監査前に揃える。
EMD rendererでも生成Action/Cameraにのみ適用して古い生成内容の再描画に対応する。
作者のEMD本文、Concept、Direction、歌詞は自動変更しない。適用時はINFOへ対象slot又は件数を出す。
LLM promptでも末尾記号を禁止し、algorithm versionは`mvd-timeline-planner-v55`とする。

field追加、値域追加、時刻意味の変更又は未知key受理はversion変更である。V1 parserへ互換分岐を積み上げない。表示文、tooltip又はdebug出力だけの変更はprotocol versionを変更しない。
