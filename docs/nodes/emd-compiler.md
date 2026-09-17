# EMD Compiler (Ref2VA)

完成EMDをparseし、日本語promptだけを英訳して、Context Loop / MiniMax H3 Ref2VA用Plan JSONへ変換します。演出の補強、要約、順序変更は行いません。

## 入力

| 入力 | 既定 | 説明 |
|---|---|---|
| `emd_text` | 必須 | Planner出力または手書きの完全EMD |
| `translation_mode` | `ja_to_en` | `ja_to_en` / `already_english` |
| `model_name` | 自動列挙 | 日本語英訳用Text GGUF。8B級推奨 |
| `chat_format` | `auto` | `auto` / `qwen` / `gemma` |
| `steps` | `20` | Plan JSONの既定steps |
| `max_tokens` | `4096` | 英訳protocolの応答上限 |
| `temperature` | `0.0` | 英訳は決定的な低温度を使う |
| `n_ctx` | `32768` | 長いEMD向け既定context |
| `cache_mode` | `reuse` | 成功Plan JSONの再利用方針 |
| `h3_timing_profile` | 任意 | H3時間契約。未接続時も固定既定値 |

他の推論値は[GGUF共通設定](gguf-settings.md)を参照してください。

## 出力

| 出力 | 用途 |
|---|---|
| `plan_json` | Unicode非escape、2 space indent、LF、末尾LFのJSON |
| `required_references` | 実際にEMDへ書かれたPicture/Video/Audio参照 |
| `status` | Scene数、参照数、cache等 |

## 動作境界

- Subjectは`# サブジェクト`直下のlist item順で`<Subject 1..4>`へ割り当てます。
- ``画像1``、``動画1``、``音声1``等を`<Picture 1>`、`<Video 1>`、`<Audio 1>`へ変換します。
- `<d>...</d>`と予約directiveは翻訳LLMへ渡しません。
- 英語だけの行は完全pass-throughします。
- `already_english`ではmodelの選択が古くてもGGUFをresolve/loadしません。
- 必須Ref2VA六セクションは固定templateで組み立てます。
- EMD文法、翻訳slotの欠落・重複・未知行はretryで推測せず停止します。

JSONは機械入力ですが、レビューしやすいようpretty-printが仕様です。T2VA/I2VAはこのCompilerの対象外です。
