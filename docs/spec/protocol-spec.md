# MV Director プロトコル仕様

更新日: 2026-09-27<br>
対象: 現行dev、Gemma4 31B / Scene Author

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

| schema | 用途 |
|---|---|
| MVD_OBSERVATIONS_V1 | 検証済みVision観察 |
| MVD_EMD_FRAGMENT_V1 | Subject断片 |
| MVD_SCENE_EMD_FRAGMENT_V1 | Scene設定断片 |
| MVD_REFERENCE_BINDINGS_V1 | IMAGEとPictureの束縛 |
| MVD_DIRECTION_V4 | 共通方針、profile、演出候補、モーション補完、provenance |
| MVD_TIMELINE_V1 | source音声、歌詞、Scene/Shot |
| MVD_EMD_TEMPLATE_V1 | 確定時間枠と歌詞annotation |
| MVD_EMD_V1 | 完成EMD |
| MVD_REQUIRED_REFERENCES_V2 | Compilerが要求する参照 |
| MVD_SCENE_AUTHOR_CONTENT_V1 | Planner成功cacheの内部内容 |

Planner内容cacheはactions、cameras、events、motion_compositions、terminal_statesと計数を持つ。
自然文はLLM原文と別責務の補完を分けて保持する。旧engineのcache形状は読み替えない。

## 4. EMD text artifact

```json
{"schema":"MVD_EMD_V1","text":"# サブジェクト\n...","sha256":"..."}
```

`schema`は四つのEMD schemaのいずれか、`text`はLFへ正規化した文字列、`sha256`は正規化後textのUTF-8 SHA-256とする。hash不一致を修復しない。`MVD_SCENE_EMD_FRAGMENT_V1`は`# シーン設定`だけを持ち、文法はEMD仕様を正本とする。

## 5. Direction artifact

```json
{
  "schema": "MVD_DIRECTION_V4",
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

Direction Enhancerだけは、既知の輸送形式の表記揺れをparser投入前に機械正規化する。独立行の`<think>` / `</think>`を除去し、TABの直後へ連結された既知の`STYLE` / `ENVIRONMENT` / `TIME_LIGHTING` / `MOTION` / `CAMERA` / `OTHER` recordを物理行へ分離する。また同taskでは各typeの有効slotが常に1だけなので、既知typeの正のslot番号を1へ正規化する。nodeはuser messageの先頭へ`/no_think`も付与する。本文の意味修復や欠落recordの合成は行わない。

Plannerはstrict parserの後に全task共通のwrapper recoveryを持つ。`TYPE slot: TEXT`、`slot N - TEXT`及び番号付きlistのようにslotが一意に明示された行は、typeとslot wrapperだけを正規recordへ戻す。複数の未解決slotに対して、fenceと空行を除く非空物理行数が完全一致する場合だけ、request side table順へ位置対応させる。Markdown bullet以外の`TEXT`は変更しない。単一の無番号行、余分な説明行、行数不一致又は重複slotは推測しない。機械復元数はPlanner artifactの`protocol_recovered_count`とnode statusの`protocol_recovered`へ残す。共通parser、未知slot拒否及びcreative textのAS IS規則は変更しない。

Compiler翻訳では360文字を超え、安全な句点・読点境界を持つunitを初回推論前に120文字以下を目標として分割する。通常batchの欠落、日本語echo又は競合重複slotは一件だけで隔離再試行し、隔離後も日本語echoとなる長文には同じ分割回復を適用する。ほぼ完成した英文に少数の日本語だけが残る場合は、英文候補全体を再翻訳せず、連続する残存日本語spanだけを出現順に一意化して同じprotocolへ渡し、英訳を元のspan位置へ機械置換する。同じspanの反復は一度だけ翻訳し、既存英文は変更しない。各chunk又はspanを同じprotocolで翻訳し、全件成功後だけ元の順序又は位置で再結合する。原文内容、slot順及びprotected spanは変更しない。短文、境界なし又はspan cleanup・chunk失敗は停止する。回復過程はtrigger及びspan数を含めINFOへ、成功件数は`segmented_recovered`及び`cleanup_recovered`へ残す。

### 9.1 parse結果

```json
{
  "protocol": "MVD_LLM_RECORDS_V1",
  "records": [
    {"record_type":"PERFORMANCE","slot":1,"text":"...","line_number":1}
  ],
  "issues": [
    {"line_number":2,"reason":"unknown_type","raw_sha256":"..."}
  ],
  "missing": [["PERFORMANCE",2]]
}
```

issue reasonは`field_count`、`unknown_type`、`invalid_slot`、`unknown_slot`、`empty_text`、`duplicate`に限定する。raw本文は通常artifactへ保存せずhashだけを残す。

### 9.2 現行task

| task | record type | slot |
|---|---|---|
| Direction | STYLE / ENVIRONMENT / TIME_LIGHTING / MOTION / CAMERA / OTHER | 区分ごとに1 |
| scene-author-event | EVENT | 現在要求のShot side table |
| scene-author-performance | PERFORMANCE | 現在要求のShot side table |
| scene-author-camera | CAMERA | 現在要求のShot side table |
| scene-author-composition-choice | CHOICE | 常に1。本文は既存候補の番号 |
| translation-ja-en | TRANSLATION | 翻訳unit side table |

Scene Authorは各Sceneの固定境界、原歌詞、section文脈、人物・背景、Directionと作者固定fieldを入力とする。
Event、Performance、Cameraを順に生成し、採用済み前段fieldを後段へ渡す。
作者がfieldを所有する場合は該当生成を省略する。grammarは行type・slot・制御文字だけを拘束する。
END_STATE suffixは本文から輸送metadataへ分離し、継続Sceneだけへ渡す。

必須slotの不足は同じSceneの不足slotだけ局所retryし、未回復slotは一件隔離して再要求する。
回復不能なら不完全EMDをCompilerへ渡さない。旧Cue、Actions/Audit、有限Cameraはこのprotocolに含めない。

モーション補完はDirection V4の任意motion_templates又はprofileから取得する。
省略は継承、空配列は無効、非空は置換。最大12件、各1〜500文字の単一行。
pre_authorは予定補完をPerformance前に提示し、post_authorは三段生成後に合成する。
guarded_no_dropのCHOICEは候補を再選択するだけで、作者確定fieldやLLM原文を変更しない。
不正CHOICEを一度再試行しても回復不能なら元の候補を保持する。

### 9.3 Compiler翻訳保護token

Compilerが翻訳backendへ自由描写を渡す前に、内部ID、`<Subject 1..4>`、`<Picture 1..9>`、`<Video 1..3>`、`<Audio 1..3>`、`「...」`、明示`<d>...</d>`、MiniMax H3正式Camera directive並びに履物語彙`足袋`、`下駄`及び`鼻緒`をopaque spanとして分離する。履物語彙はそれぞれ`tabi`、`geta`及び`hanao strap`として復元し、その他のopaque spanは原文を保持する。opaque spanはplaceholderを含め翻訳backendへ一切渡さず、その前後にある翻訳対象fragmentだけを翻訳する。Pythonは翻訳後のfragment間へspanを元の順序と位置で機械的に再結合する。境界両側が英数字で密着する時は一個の空白だけを挿入する。このため翻訳backendのtoken欠落、変形、並べ替え又は`足袋`から`geta`への誤訳に依存しない。

`<Video N>`は翻訳保護だけを受けるopaque tokenである。`MVD_REQUIRED_REFERENCES_V2`はSubject Picture、環境Picture及びlip-sync Audioを対象とし、CompilerはVideo接続要求を生成又は検証しない。

## 10. Vision行protocol

IDはMVD_VISION_OBSERVATION_LINES_V2。LLMのShot行protocolとは別parserを使用する。

正規順はOVERVIEW、PRIMARY_SUBJECT、HINT_STATUS、HINT_REASON、SUBJECT_FEATURE、
SUBJECT_POSE、SCENE_SETTING、SCENE_ELEMENT、LIGHTING、TIME_WEATHER、SHOT_SIZE、
VIEWPOINT、SUBJECT_PLACEMENT、DEPTH、STYLE_MEDIUM、STYLE_RENDERING、STYLE_PALETTE、
VISIBLE_TEXT、UNCERTAINTY、END_MVD_VISION_OBSERVATIONである。

通常scalarはTYPEと値、SUBJECT_FEATUREはTYPE、category、本文、visibilityをTABで区切る。
categoryはface / hair / eyes / eyebrows / ears / body / clothing / footwear / accessory / tail / distinctive_feature。
visibilityはclear / partial / uncertain、HINT_STATUSはnot_used / consistent / ambiguous / conflict。

SUBJECT_FEATURE、SCENE_ELEMENT、VISIBLE_TEXT、UNCERTAINTYは繰返し可能。
既知recordの順序揺れ・応答再開による重複を正規化し、protocol_id wrapperはmetadataとして除外する。
本文一列だけのSUBJECT_FEATUREはdistinctive_feature / partialへ収容する。
未知categoryも本文を保ってdistinctive_featureへ収容する。本文欠落・未知recordは拒否する。

OVERVIEW、HINT_STATUS以外の空許可scalarは行欠落を空値へ復元してwarningを残せる。
観察本文をPythonで創作しない。HINT_REASONの許容空値とprofile別の必要情報はparser・artifact検証に従う。
scene_onlyはScene設定、subject_onlyはSubject、generalは各用途を観察し、共通emd_fragment出力で切り替える。

## 11. 変更と保存

公開schemaを暗黙変換しない。Plannerの内部cacheは新algorithm ID
`mvd-scene-author-v1-gemma31b`と内容schemaで旧経路から分離する。
旧performance_mode等のprofile keyは移行エラーとし、scenes_per_batchはAPI/UIから削除する。

context回復は必須指示と現在slotを保持する。旧意味監査・反復分類へ戻さない。
Compilerの翻訳は全要求slotが揃う場合に限り非参照余剰行を破棄でき、欠落・競合は有限隔離retryする。
H3の演技・effect・lip-syncの成否はprotocolの成立とは別に人間が評価する。
