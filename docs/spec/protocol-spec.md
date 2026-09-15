# MV Director プロトコル仕様

版: `protocol-0.1`<br>
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
| `MVD_DIRECTION_V1` | `DirectionArtifact` | 四方向とprovenance |
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
  "schema": "MVD_DIRECTION_V1",
  "style_direction": ["..."],
  "motion_direction": ["..."],
  "camera_direction": ["..."],
  "other_direction": [],
  "provenance": []
}
```

四方向は空文字列を含まない文字列配列で、順序を保持する。provenance recordは次の固定shapeを使う。

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
- `reason`: `direct_input` / `valid_line_record` / `empty` / `exact_duplicate` / `invalid_line_record`
- `source_position`: 0以上の入力item又は物理行index
- `target`: 採用outputだけが`style_direction[N]`等を持ち、それ以外はnull

semanticな採用、上書き又は破棄理由を生成しない。

## 6. Reference binding

`MVD_REFERENCE_BINDINGS_V1`のrootは`bindings`配列を持つ。一件は次を持つ。

```json
{
  "concept_id": "人物1",
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
  "protocol": "MVD_VISION_OBSERVATION_LINES_V1",
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
      "concept_id": "人物1",
      "subject_ref": "<Subject 1>",
      "h3_ref": "<Picture 1>",
      "required_input": "ref_images.ref_image_0",
      "purpose": "visual_identity"
    }
  ]
}
```

`purpose`は`visual_identity`又は`lip_sync_audio_reference`。Audio参照では`subject_ref`を省略できる。PictureもAudioも不要なら`references`は空配列であり成功である。

## 8. Timeline

`MVD_TIMELINE_V1`は`timebase=source_audio`、`time_unit=ms`を固定し、少なくとも解析条件、`source_audio_duration_ms`、`plan_duration_ms`、`timing_profile`、`lyrics`、`scenes`、`unplaced_lyrics`を持つ。

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
| Enhancer | `STYLE`、`MOTION`、`CAMERA`、任意`OTHER` | 先頭三typeのslot 1 |
| lyric-notes | `NOTE` | side tableの全slot |
| song-direction | `DIRECTION` | slot 1 |
| actions | `ACTION` | side tableの全slot |
| cameras | `CAMERA` | side tableの全slot |

### 9.3 Compiler翻訳保護token

Compilerが翻訳backendへ自由描写を渡す前に、内部ID、`<Subject 1..4>`、`<Picture 1..9>`、`<Video 1..9>`、`<Audio 1..3>`、`「...」`及び明示`<d>...</d>`を順序付きplaceholderへ置換する。backend応答では既知placeholderが同じunit内に同数・同順で存在する場合だけ原文tokenへ復元し、欠落、重複又は並べ替えがあればretryせず停止する。

`<Video N>`は翻訳保護だけを受けるopaque tokenである。`MVD_REQUIRED_REFERENCES_V1`は現行どおりPictureとlip-sync Audioだけを対象とし、V1 CompilerはVideo接続要求を生成又は検証しない。

## 10. Vision行protocol

protocol IDは`MVD_VISION_OBSERVATION_LINES_V1`。record順、category、visibility、空を許すfield及び終端warningは最小コア仕様5.2を正本とする。Phase 0ではIDとfixtureだけを固定し、parser実装はPhase 3で行う。

LLM行protocolとVision行protocolを同じparserへ無理に統合しない。前者は部分回収、後者は固定順の完全な観察recordを要求する。

## 11. protocol変更

field追加、値域追加、時刻意味の変更又は未知key受理はversion変更である。V1 parserへ互換分岐を積み上げない。表示文、tooltip又はdebug出力だけの変更はprotocol versionを変更しない。
