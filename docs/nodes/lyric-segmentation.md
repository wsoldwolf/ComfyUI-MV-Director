# Lyric Segmentation

UTF-8 plain lyricsとvocal stemをOpenAI Whisper、VAD、文字列照合で整列し、同じcanonical segment列からTemplate EMD、SRT、typed timelineを作ります。PlannerやH3へ接続せず、SRT生成だけにも使えます。

長尺音源は前文脈を引き継がない全体認識を行い、未解決部分だけを前後の確定歌詞で囲んだ12秒以下の短窓として再認識します。短窓の歌詞誘導結果は、誘導なし認識の実在word timestampと後続アンカーで確認できた場合だけ採用します。したがって、入力音声に存在しない歌詞へ推測時刻を付けることはありません。

## 入力

| 入力 | 既定 | 説明 |
|---|---:|---|
| `vocal_audio` | 必須 | padding前のvocal stem |
| `lyrics_text` | 必須 | `[SECTION]`を持つplain lyrics |
| `whisper_model` | 自動列挙 | `models/whisper`以下のローカル`.pt` |
| `language` | `ja` | 初期版は日本語のみ |
| `max_scene_duration_ms` | `10000` | H3 Scene分割の最大目安 |
| `srt_time_offset_ms` | `0` | SRT出力だけへ加えるoffset |
| `cache_mode` | `reuse` | 成功結果の再利用方針 |
| `keep_whisper_loaded` | `false` | 8GB VRAMではfalse推奨 |
| `h3_timing_profile` | 任意 | 未接続時も固定既定profileを使う |

## lyrics形式

```text
[VERSE1]
最初の歌詞 次の歌詞

[CHORUS]
サビの歌詞
```

角括弧内は`VERSE`に限定されません。ASCIIのsection名であれば`CHORUS`、`BRIDGE`、`OUTRO`等も受け付け、大文字へ正規化します。見出し内側の前後空白は許容します。本文の物理行と空白runからatomic segmentを作ります。

LRC、SRT、VTT、timestamp、コメント、本文行の不必要な前後空白は入力しません。

## 出力

| 出力 | 用途 |
|---|---|
| `template_emd` | Timeline Plannerの確定済みScene/Shot枠 |
| `srt_text` | 外部字幕として保存可能なSRT本文 |
| `timeline` | Audio Pad Pair等へ渡す元音源ms/H3 frame対応 |
| `status` | resolved、unplaced、音源尺、Plan尺、Scene数、cache |

Template EMDは先頭Sceneをカット、2件目以降を初期値`継続`として明示します。これはPlannerへ渡す暫定境界modeです。PlannerがMV編集上のカットを選ぶと、そのSceneから`継続`を外し、H3格子上の`H3長`とPlan時刻を再配分します。

全歌詞が配置できない場合は赤いERRORを出し、Template EMD、SRT、timelineをExecutionBlockerで停止します。これは音源が歌詞後半を歌っていない場合を黙って成功にしないためです。

INFOログの`targeted retries completed`には、再探索した未解決run数、回収segment数、残数が表示されます。`remaining=0`なら全歌詞が実timestampへ配置されています。
