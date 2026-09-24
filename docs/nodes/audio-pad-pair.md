# Audio Pad Pair (PCM Silence)

full mixとvocal stemを混合せず、必要な末尾だけPCM値ゼロでpaddingします。promptではなく音声データで無音を保証します。

## 入力

| 入力 | 既定 | 説明 |
|---|---:|---|
| `audio_a` | 必須 | 通常は完成動画用full mix |
| `audio_b` | 必須 | 通常はvocal stem |
| `extra_padding_ms` | `0` | 目標尺へ追加する任意余白 |
| `target_h3_frames` | `0` | 明示frame目標。Timelineより短ければTimelineを優先 |
| `pad_position` | `end` | 初期版は末尾のみ |
| `reference_alignment` | `off` | `off` / `source_scenes_to_plan` |
| `timeline` | 任意 | Lyric Segmentationのtyped timeline |
| `h3_timing_profile` | 任意 | frame換算に使う固定profile |
| `plan_json` | 任意 | Compiler出力。Plannerがカット／継続を変更した後の最終delivered frame尺を自動取得 |

## 出力

| 出力 | 用途 |
|---|---|
| `padded_audio_a` | 末尾padding済みfull mix |
| `padded_audio_b` | 末尾padding済みvocal |
| `status` | sample数、Plan ms、frame、alignment情報 |
| `reference_audio_b` | Audio参照方式用のScene配置済みvocal |

`reference_alignment=source_scenes_to_plan`ではTimelineが必須です。H3の累積frame量子化では、単独Sceneの元音声が対応するPlan区間より長くても、それ以前に確保された余白と合わせれば累積境界までに収まる場合があります。このとき無音挿入を後ろへ繰り延べ、前Sceneの未使用末尾から次Sceneの元音声を配置します。元vocalの全サンプルと順序を保持し、切断・伸縮・重複は行いません。参照音声のScene開始がPlan境界より早くなる場合があります。累積境界でも収まらない場合はエラーです。この処理は`reference_audio_b`だけへ適用し、通常の二つのpadded出力は末尾paddingのままです。

`source_scenes_to_plan`を使うAudio Reference方式では、Lyric Segmentationへpadding前の元vocalを接続してください。Context Loop方式とLyrics方式の動画WFでは`timeline`は不要です。

Plannerがカット／継続を変更すると、H3の合法なframe格子に合わせるため、最終Plan尺がLyric Segmentationの初期timelineより長くなる場合があります。動画生成WFではCompilerから受け渡した同じ`plan_json`を接続してください。Audio Pad Pairは各Sceneの`length - context_length`を合計し、timeline、明示`target_h3_frames`、実音声尺と比較した最大値までPCM無音を追加します。
