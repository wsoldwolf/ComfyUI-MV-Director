# Timeline Planner

Lyric Segmentationが確定したScene/Shot枠へ、歌詞解釈、人物動作、カメラ、リップシンクdirectiveを展開して完成EMDを作ります。人物動作とカメラは別のLLMタスクで生成し、Pythonが同じShotへ合成します。

## 主な入力

| 入力 | 既定 | 説明 |
|---|---|---|
| `template_emd` | 必須 | Lyric Segmentationの出力 |
| `concept_emd` | 任意 | Subject等の概念EMD。Picture参照なしでもよい |
| `direction` | 任意 | Direction Enhancerのtyped出力 |
| `lip_sync_mode` | `lyrics` | `off` / `context_loop` / `audio_reference` / `lyrics` |
| `lip_sync_target` | `サブジェクト1` | リップシンク対象。`サブジェクト1..4` |
| `lip_sync_audio_slot` | `1` | Audio参照時の1～3 |
| `model_name` | 自動列挙 | Text GGUF。8B級推奨 |
| `model_name_override` | 空 | 外部STRINGでmodel選択を上書き |
| `scenes_per_batch` | `3` | 一回に計画するScene数 |
| `cache_mode` | `reuse` | 成功結果の再利用方針 |
| `save_debug_output` | `false` | 一時ディレクトリへLLM traceを保存 |

既定の`max_tokens=4096`、`temperature=0.1`、`n_ctx=16384`等は[GGUF共通設定](gguf-settings.md)を参照してください。

## 出力

| 出力 | 用途 |
|---|---|
| `emd_text` | 編集可能な完成EMD。Compilerへ接続する |
| `emd` | 内部typed EMD artifact |
| `status` | Scene/Shot数、issue、retry、fallback、cache等 |

## 計画方針

Plannerは歌詞内の具体物、場所、感情をvisual beatへ変換し、触れる、振り返る、視線を移す、環境へ反応する等の動作候補を作ります。CameraはShotの目的に合わせてstatic、pan、tilt、push、pull、truck、tracking、arc、close-up、detail等を選び、同じ動きを連続反復しないよう計画します。

歌詞annotationは全modeでEMDへ残ります。mode変更は機械的なlip-sync directiveだけを変えるため、成功cacheがあれば人物動作とカメラを再生成しません。

必要なslotが欠落した場合は不完全EMDをCompilerへ流さずExecutionBlockerで停止します。`save_debug_output=true`は問題調査時だけ使い、通常は無効にします。
