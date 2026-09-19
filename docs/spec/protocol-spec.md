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
| `MVD_REFERENCE_BINDINGS_V1` | `ReferenceBindingsArtifact` | IMAGEとPictureの物理束縛 |
| `MVD_DIRECTION_V3` | `DirectionArtifact` | 六方向、profile ID、保持方針とprovenance |
| `MVD_TIMELINE_V1` | `TimelineArtifact` | source音声、歌詞、Scene、Shot |
| `MVD_EMD_TEMPLATE_V1` | `EMDTextArtifact` | 時間枠と歌詞annotation |
| `MVD_EMD_V1` | `EMDTextArtifact` | 完成EMD |
| `MVD_REQUIRED_REFERENCES_V1` | `RequiredReferencesArtifact` | Compilerが要求するH3入力 |

## 4. EMD text artifact

```json
{"schema":"MVD_EMD_V1","text":"# サブジェクト\n...","sha256":"..."}
```

`schema`は三つのEMD schemaのいずれか、`text`はLFへ正規化した文字列、`sha256`は正規化後textのUTF-8 SHA-256とする。hash不一致を修復しない。

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

標準workflowでは人物identityのConcept EMDと背景環境の`MVD_OBSERVATIONS_V1`を別入力としてDirection Enhancerへ渡す。背景観察を人物Subjectへ結合しない。動画生成時も人物`<Picture 1>`と環境`<Picture 2>`を別H3参照slotへ束縛する。同一Pictureへ人物と背景の保持責務を集中させると人物identityが参照条件を占有し、環境特徴が希薄化又は欠落しやすいためである。環境専用Pictureは背景再現率を改善するための証拠であり、構図、時刻、照明又は画素一致のauthorityではない。

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
  "schema": "MVD_REQUIRED_REFERENCES_V1",
  "references": [
    {
      "concept_id": "サブジェクト1",
      "subject_ref": "<Subject 1>",
      "h3_ref": "<Picture 1>",
      "required_input": "ref_images.ref_image_0",
      "purpose": "visual_identity"
    }
  ]
}
```

`purpose`は`visual_identity`、`motion_reference`、`subject_audio_reference`又は`lip_sync_audio_reference`。Picture、Video、Audioのいずれも不要なら`references`は空配列であり成功である。

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
| cameras | `CAMERA` | side tableの全slot |
| translation-ja-en | `TRANSLATION` | batch内の全slot |

Visual BeatはSceneごとの原文歌詞、opening/middle/closing位置、歌詞解決有無、Subjectの`concept_id`と`<Subject N>`だけからなるroster及び直近12件の採用beatから具体名詞、物理動詞、接触対象、可視結果及び感情変化を一行へ固定する。Concept EMDの外見・身体・衣装・材質detailはVisual Beat及びAction requestへ含めず、最終EMDのSubject定義として保持する。`LAYOUT`のTEXTは`CUT,B0,...`又は`CONTINUE,B0,...`とし、先頭Sceneは`CUT`固定、後続は新しい編集構図なら`CUT`、直前の画像状態とカメラ経路を引き継ぐ時だけ`CONTINUE`とする。各Scene slotへ直前Sceneの歌詞とvisual beat、`first_section_appearance`、`new_sections`及び`section_entry_shot_index`を渡し、同じ物理動作又は接触の次段階なら`CONTINUE`、実行可能な範囲で新section初出Sceneを`CUT`とする。4 Scene以上でCUT/CONTINUEの最低数、同一mode最大3連続又はmode遷移数上限を満たさない場合は、隣接関係を再評価する境界mix requestを一度追加する。完全なCUT/CONTINUE交互列も不合格である。再応答も違反する時はmode列だけを最小変更で構造修復し、自然文は変更しない。残りはPythonが提示した境界IDだけを時系列順に持つ。LLMは時刻を生成しない。Pythonは候補同士も1500 ms以上離れた相互互換集合を作り、選択IDを絶対msへ機械変換し、mode変更後のraw H3 lengthとPlan時刻を累積格子へ再配分する。1 Sceneあたり最大4 Shot、通常は2～3 Shotとし、4 ShotはSceneが8秒以上で各intervalを2秒以上確保できる場合だけ選び、複数Shot時は各Shot 1500 ms以上とする。Scene全体が1500 ms未満の場合は`B0`だけの一Shotを許す。候補数超過、区切り差、重複、順序違反又は未知候補を含む応答は、既知IDの抽出、時系列順整列、重複除去及び最大4 Shotへの切り詰めだけで機械修復し、statusへScene番号を残す。境界mode自体を認識できない場合だけ`CUT,B0`へ機械fallbackする。ActionはShot終了・長さ・Scene内Shot数、Subject rosterと直近18件の採用action、Cameraは確定action、Sceneのcut/continue modeと直近12件の採用cameraをrequest side tableから受ける。これらの履歴は反復回避用で、LLM応答へ再出力しない。Action及びCameraのcreative textはslot対応後に意味修復せずEMDへ置く。

Visual Beat、Action及びCameraの長いTEXTが、同じrequest内の先行採用TEXT又は直近履歴と完全一致若しくは高い表層類似度を持つ場合、対応するSceneの該当slotだけを最大二回再要求する。retryには`rejected_output`、`must_differ_from`、`diversity_retry_attempt`、`diversity_retry`及び直近と同一batchの採用候補最大12件からなる`forbidden_recent_outputs`を付ける。Pythonは自然文を置換・合成せず、再応答をAS ISで採用する。二回の再応答後も類似するslotは品質警告として段階別に数え、`repetition_warnings=total(beat=B,action=A,camera=C)`をWARNINGログとstatusへ記録するが、未解決slotにはせずCompilerを実行する。Actionは`action_batch_contract`を持ち、slow、単純な手の上下、作者未指定のlower-body主体及び作者・歌詞未指定の走行に違反したslotだけを`action_quality_budget`として一度再要求する。Cameraは`camera_batch_contract`を持ち、Arc、Tracking、同一Motion Type、slow及び作者未指定のlower-body detailを超過したslotだけを`camera_quality_budget`として一度再要求する。

Compilerの`translation-ja-en`は描写文の一対一翻訳だけを返す。識別上重要な局所形状、個数、配置、大きさ、色、材質及び否定条件を具体的な物理形状として訳し、特殊形状を一般的な解剖・衣装・装飾名称へ丸めない。slotは各有限batch内で1から振り直し、Pythonが元のtranslation unit順へ戻す。入力JSONはPython所有であり、各slotの原文fieldは`japanese_text`、固定instructionはそのfieldを英訳することを明記する。LLMへJSON出力を要求しない。Qwen3系へはuser message先頭で`/no_think`を指定する。Compiler翻訳に限り、閉じた`<think>...</think>`、文字列`<TAB>`又はTABで囲まれた`TAB`ラベル、`slot N`表記、及び一物理行へ連結された既知`TRANSLATION` recordをparser前に決定論的に正規化する。実測形式の先頭に英訳文が複製されていても、数値slot後の英訳文だけを採用する。必須`TRANSLATION` slotが全て揃う応答に付随した非record行及び未知record型は捨て、同じslotの重複が完全一致する時は一件として扱う。重複本文が異なるslotは一方を選択せず、そのslotだけを一回単独再翻訳する。不正slot、未知slot、空本文、単独再翻訳後の競合又は欠落は停止する。

欠落slot、採用本文に日本語scriptが残るslot又は異なる本文が重複するslotは、正常slotを保持したまま、該当原文だけを`slot 1`として一度だけ隔離再翻訳し元位置へ戻す。隔離再翻訳は入力が一つだけなので、strict parserの問題が`field_count`だけであり、非空英訳候補を一つだけ決定できる場合に限り、裸の一物理行、明示的な単一slot wrapper又は単一translation fieldを持つJSON wrapperから本文をAS ISで復元できる。複数行・複数候補・未知record型・不正slot・競合・日本語script残存は停止する。slot番号、protected token又は英訳本文の意味は推測修復しない。本文がslot番号そのものの場合も日本語script残存と同じ機械条件で一度だけ隔離再翻訳し、再発すれば停止する。

### 9.3 Compiler翻訳保護token

Compilerが翻訳backendへ自由描写を渡す前に、内部ID、`<Subject 1..4>`、`<Picture 1..9>`、`<Video 1..3>`、`<Audio 1..3>`、`「...」`、明示`<d>...</d>`及びMiniMax H3正式Camera directiveをopaque spanとして分離する。opaque spanはplaceholderを含め翻訳backendへ一切渡さず、その前後にある翻訳対象fragmentだけを翻訳する。Pythonは翻訳後のfragment間へ原文spanを元の順序と位置で機械的に再結合する。このため翻訳backendのtoken欠落、変形又は並べ替えに依存しない。

`<Video N>`は翻訳保護だけを受けるopaque tokenである。`MVD_REQUIRED_REFERENCES_V1`は現行どおりPictureとlip-sync Audioだけを対象とし、V1 CompilerはVideo接続要求を生成又は検証しない。

## 10. Vision行protocol

protocol IDは`MVD_VISION_OBSERVATION_LINES_V2`。正規record順、category、visibility、空を許すfield及び終端warningは最小コア仕様5.2を正本とする。parserは既知の名前付きrecordの順序入替えと応答再開による重複を決定論的に正規化する。modelがschema wrapperとして生成する`protocol_id`はpayloadの有無や位置にかかわらずtransport metadataとして除外する。`SUBJECT_FEATURE`が本文一列だけを持つ場合は本文を保持して`distinctive_feature`及び`partial`を割り当てる。未知categoryも本文を保持して`distinctive_feature`へ収容するが、本文欠落及びその他のunknown recordは拒否する。Phase 0ではIDとfixtureだけを固定し、parser実装はPhase 3で行う。

LLM行protocolとVision行protocolを同じparserへ無理に統合しない。前者は部分回収、後者は固定順の完全な観察recordを要求する。

Plannerの`ACTION`要求slotは`performance_role`、`CAMERA`要求slotは`editorial_role`を持つ。これらは出力行へ追加するfieldではなく、既存の`TYPE<TAB>SLOT<TAB>TEXT`を生成するための構造的制約である。複数Shot Sceneでは顔・上半身accent、腕・手主体の演技、環境相互作用又は身体方向転換、終端silhouetteを別Shotへ配分する。通常slotではPythonは自然文を合成又は置換せず、LLMが返したTEXTをAS ISでRendererへ渡す。

例外として、リップシンク有効かつ歌詞sectionが初登場するCUT Sceneでは、新section名を持つ最初の歌詞annotationが属するShotを`face_performance_cut`とする。Scene開始と歌詞開始が異なる場合もScene先頭へ前倒ししない。このslotは有限個のRenderer所有構造出力であり、ACTION/CAMERA LLM要求へ含めない。Actionは顔演技中も記述済み眉の個数、compactness、形、配置及び色を維持し、特殊な眉markを通常の長い線状又は弓状眉へ置換しない固定英語文とする。Cameraは`Zoom In with large amplitude at fast speed`で正面又は斜め正面の頭肩構図から極端な顔close-upへ進み、全行程で両目、両眉、鼻、完全な歌唱口及び顔輪郭を同時に残す固定英語文とする。Compilerは両方をopaque spanとして翻訳backendから隔離し、H3 promptへ完全一致で再結合する。これにより通常slotへの固定phrase漏洩と、顔close-upに対する歩行又は全身Actionの競合を防ぐ。固定顔インサートには同一Scene内の隣接通常slot一個を`face_arc_transition`として対応付け、顔へ入るArc又は顔から全身・環境へ抜けるArcをLLMへ必須要求する。`anime_mv`では離れた最大二slotを`long_arc_emphasis`とし、60～120度のArcをShot尺の70～90%にわたり継続させる。

Plannerの初回応答でslotが欠落した場合、同一Sceneの欠落slotだけを一度再要求する。そこでも欠落したslotは一件ずつ`isolated_missing_slot`として一度再要求する。通常batchでは単一の無番号行を推測しないが、この隔離要求はrequest side tableに候補が一件しかないため、応答が説明行を含まない単一の非空物理行ならそのTEXTを一文字も変更せず当該slotへ対応付けられる。複数行、空行だけ又は明らかなJSON／Markdown見出しは推測回収しない。隔離再要求後も欠落する場合だけPlannerを不完全として停止する。

`HINT_STATUS`が`consistent`、`ambiguous`又は`conflict`で、固定行`HINT_REASON`の値だけが空の場合は、statusを保持したままwarningとして受理する。理由本文をPythonで合成せず、この欠落だけをformat retry条件にしない。`not_used`は空理由だけを受理する。

全profileで、protocol上「値又は空」と定義された単値recordの行自体が省略された場合は、そのfieldを空文字として復元しwarningを残す。対象は`PRIMARY_SUBJECT`、`HINT_REASON`、`SUBJECT_POSE`、`SCENE_SETTING`、`LIGHTING`、`TIME_WEATHER`、`SHOT_SIZE`、`VIEWPOINT`、`SUBJECT_PLACEMENT`、`DEPTH`及び三つのstyle fieldに限定する。これは空値の構造的正規化だけであり、観察本文を生成又は書換えない。全profileで既知recordの逆順は正規化するが、未知record、必須`HINT_STATUS`欠落又は不正値は推測せず拒否する。

## 11. protocol変更

field追加、値域追加、時刻意味の変更又は未知key受理はversion変更である。V1 parserへ互換分岐を積み上げない。表示文、tooltip又はdebug出力だけの変更はprotocol versionを変更しない。
