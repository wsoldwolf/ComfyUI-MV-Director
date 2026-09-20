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
| `n_ctx` | `16384` | 既定context。必要な場合だけ手動で拡張する |
| `cache_mode` | `reuse` | 成功Plan JSONの再利用方針 |
| `h3_timing_profile` | 任意 | H3時間契約。未接続時も固定既定値 |

他の推論値は[GGUF共通設定](gguf-settings.md)を参照してください。

## 出力

| 出力 | 用途 |
|---|---|
| `plan_json` | Unicode非escape、2 space indent、LF、末尾LFのJSON |
| `required_references` | 実際にEMDへ書かれたSubject Picture、環境Picture及びAudio参照 |
| `status` | Scene数、参照数、cache等 |

## 動作境界

- Subjectは`# サブジェクト`直下のlist item順で`<Subject 1..4>`へ割り当てます。
- `# シーン設定`の環境・時間照明を共通Directionより前のbaselineとして`prompt_prefix`へ置きます。後続の明示Directionが優先されます。
- `# シーン設定`の背景PictureはSubjectにせず、環境専用definition、保持契約及び`environment_reference` required inputへ変換します。
- ``画像1``、``動画1``、``音声1``等を`<Picture 1>`、`<Video 1>`、`<Audio 1>`へ変換します。
- `<d>...</d>`、参照ID及びMiniMax H3正式Camera Motion Typeは自由文から分離し、翻訳LLMへ渡しません。前後の日本語fragmentだけを翻訳して原位置へ再結合するため、`Arc Shot`、`Tracking Shot`、`with large amplitude`、`at fast speed`等はLLMのplaceholder出力に依存せず完全一致でPlanへ残ります。
- Camera Motion Typeと翻訳本文の境界では、両側が英数字で密着する場合に一個の空白を機械挿入します。これにより`at fast speedThe...`のような連結を防ぎ、Motion Type自体と翻訳本文は変更しません。
- 履物語彙`足袋`、`下駄`及び`鼻緒`は翻訳fragmentから機械的に分離し、それぞれ`tabi`、`geta`及び`hanao strap`として原位置へ戻します。小型翻訳LLMが`足袋`を`white geta`へ一般化し、二種類の下駄を同時指定することを防ぎます。
- 英語だけの行は完全pass-throughします。
- `already_english`ではmodelの選択が古くてもGGUFをresolve/loadしません。
- 必須Ref2VA六セクションは固定templateで組み立てます。
- 翻訳では識別上重要な局所形状、個数、配置、大きさ、色、材質及び否定条件を具体的な物理形状として保持し、特殊な特徴を一般的な解剖・衣装・装飾形状へ丸めません。例えば「丸く横へ線が伸びない」形状は単なる`round`ではなく、長い線を形成しない小さな円形又は楕円形のmarkとして英訳します。
- Subject定義と既定`fully_preserved`保持文には、記述済みの局所形状を全Shotで文字どおり維持し、通常形へ置換しない固定契約を付けます。
- 全Subjectへ一つの頭と一つの身体からなる物理instanceを一体だけ描き、duplicate、twin、clone、reflection、background lookalike、inset view、split-screen copy及びsecond representationを禁止する固定文を付けます。Picture/Video参照付きSubjectでは、全panelとalternate viewを同じ一体のidentity資料としてだけ扱い、参照ポーズ、画角、構図、左右panel及び背景を現在Shotへ複製しません。さらに各frameを画面全体に広がる一つの連続したcamera viewとし、内部境界、split screen、picture-in-picture又は複数角度の同時表示を禁止します。画角と視点の変更は時間方向のcamera motion又はscene cutで表します。現在Sceneの環境・時刻・照明を唯一の完成映像世界として参照背景と参照照明を完全に置換し、白背景、無地背景、昼光、撮影用backdrop又はpanel固有背景を入力資料の残滓として描画対象から除外します。各Shotは先頭frameから現在のActionとCameraに基づく新規stagingを使用し、参照画像そのもの又は参照構図を開始画面、静止画、plate、poster、inset若しくは背景として表示せず、参照ポーズからの遷移も行いません。
- Picture/Video参照付きSubjectでは、`<d>`内の歌詞を口形用の発話内容としてだけ扱う固定文も付けます。作者のShotが可視の身体状態を明示しない限り、傷、古傷、痛み、血又は心の損傷という比喩を、傷跡、切創、痣、出血、包帯、病変、染み、刺青状の印、皮膚又は衣装の損傷へ変換せず、皮膚と衣装を清潔で損傷のない状態に保ちます。
- Scene見出し末尾に`継続`がある場合だけtiming profileのvisual/audio contextと`continuation_mode=guide`を出します。省略Sceneは`context_length=0`、`audio_context_length=0`のカットです。
- `H3長`はPlanner又は作者が境界modeに合わせて確定したraw lengthを無変換で`length`へ写します。
- 360文字を超える翻訳unitは、既存の句点・読点境界で120文字以下を目標に機械分割できる場合、初回推論前から短いunitとして翻訳して文書順に再結合します。ほぼ完成した英文に少数の日本語だけが残った場合は、英文候補全体を再翻訳せず、連続する残存日本語spanだけを一意化して同じ翻訳protocolへ渡し、得た英訳を元のspan位置へ機械置換します。同じspanの反復は一度だけ翻訳し、既存英文の語順と内容は保持します。それ以外の翻訳slotで欠落、日本語echo又は競合重複となった場合は、該当unitを一度だけ隔離再翻訳し、長文が隔離後も日本語echoなら同じ分割回復を使います。隔離再試行は入力が一件だけなので、異なる`TRANSLATION 1`が複数返っても対応先は一意です。この場合は日本語echoと空候補を除き、応答順で最初の有効な英訳を無改変で採用し、候補数と選択規則をINFOへ記録します。分割は原文文字列を書き換えず、protected tokenは従来どおり翻訳入力から除外します。隔離、分割及び残存日本語cleanupの開始、batch、完了又は失敗はslot番号、trigger、文字数、span数及びchunk数とともにINFOへ記録し、正常完了statusへ`protocol_recovered`、`segmented_recovered`及び`cleanup_recovered`を出します。全必須slotが揃った後の非record行及び未知record型は翻訳行から分離し、同一slotの完全一致重複は一件として扱います。不正slot、未知slot、空本文、有効な英訳候補のない短文日本語echo、span cleanup又は分割後も残る日本語、再翻訳後の欠落、protected token破損は停止します。

JSONは機械入力ですが、レビューしやすいようpretty-printが仕様です。T2VA/I2VAはこのCompilerの対象外です。
