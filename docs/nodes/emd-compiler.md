# EMD Compiler (Ref2VA)

完成EMDをparseし、日本語promptだけを英訳して、Context Loop / MiniMax H3 Ref2VA用Plan JSONへ変換します。演出の補強、要約、順序変更は行いません。

## 入力

| 入力 | 既定 | 説明 |
|---|---|---|
| `emd_text` | 必須 | Planner出力または手書きの完全EMD |
| `translation_mode` | `ja_to_en` | `ja_to_en` / `already_english` |
| `model_name` | 自動列挙 | 日本語英訳用Text GGUF。8B級推奨 |
| `chat_format` | `auto` | `auto` / `qwen` / `gemma` |
| `steps` | `8` | TurboLoRA動画生成用Plan JSONの既定denoising steps |
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
- `<d>...</d>`、参照ID及びMiniMax H3正式Camera Motion Typeは自由文から分離し、翻訳LLMへ渡しません。前後の日本語fragmentだけを翻訳して原位置へ再結合するため、`Arc Shot`、`Tracking Shot`、`with large amplitude`、`at fast speed`等はLLMのplaceholder出力に依存せず完全一致でPlanへ残ります。
- 英語だけの行は完全pass-throughします。
- `already_english`ではmodelの選択が古くてもGGUFをresolve/loadしません。
- 必須Ref2VA六セクションは固定templateで組み立てます。
- 全Subjectへ一つの頭と一つの身体からなる物理instanceを一体だけ描き、duplicate、twin、clone、reflection、background lookalike、inset view、split-screen copy及びsecond representationを禁止する固定文を付けます。参照付きSubjectではPicture/Videoの全panelとalternate viewを同じ一体のidentity資料としてだけ扱い、参照ポーズ、画角、構図、左右panel及び背景を現在Shotへ複製しません。
- Scene見出し末尾に`継続`がある場合だけtiming profileのvisual/audio contextと`continuation_mode=guide`を出します。省略Sceneは`context_length=0`、`audio_context_length=0`のカットです。
- `H3長`はPlanner又は作者が境界modeに合わせて確定したraw lengthを無変換で`length`へ写します。
- 翻訳slotの欠落又は日本語echoは、該当unitを一度だけ隔離再翻訳します。全必須slotが揃った後の非record行及び未知record型は翻訳行から分離し、同一slotの完全一致重複は一件として扱います。異なる本文を持つ重複slotは一方を選ばず、そのunitだけを一度隔離再翻訳します。不正slot、未知slot、空本文、再翻訳後の競合又は欠落、protected token破損は停止します。

JSONは機械入力ですが、レビューしやすいようpretty-printが仕様です。T2VA/I2VAはこのCompilerの対象外です。
