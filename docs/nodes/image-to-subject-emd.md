# Image to Subject EMD

画像の可視事実をVision GGUFで観察し、編集可能な`# サブジェクト` EMD断片を返します。同じIMAGE出力をH3の`ref_image_N`へ直接接続すると、対応する`<Picture N+1>`を自動束縛できます。

## 主な入力

| 入力 | 既定 | 説明 |
|---|---:|---|
| `image` | 必須 | 1枚または同一キャラクターの複数viewを持つIMAGE batch |
| `model_name` | 自動列挙 | 同じディレクトリの本体GGUF+`mmproj` pair |
| `analysis_profile` | `general` | `general` / `subject_only` / `scene_only` |
| `subject_hint` | 空 | 画像に写らない、または誤認しやすい識別情報を自然文で補う |
| `additional_instruction` | 空 | 今回の観察方針を自然文で追加する |
| `hint_mode` | `lock_identity` | `observe_only` / `assist` / `lock_identity` |
| `hint_conflict` | `warn` | hintと観察の矛盾を警告にするか`strict`停止するか |
| `picture_reference_mode` | `auto_h3` | `auto_h3` / `manual` / `none` |
| `concept_type` | `person` | `person` / `location` / `object` |
| `picture_index` | `1` | `manual`時のPicture番号、1～9 |
| `analysis_max_edge` | `1024` | Visionへ渡す最大辺。元IMAGE出力は変更しない |
| `cache_mode` | `reuse` | 成功結果の再利用方針 |

残りの推論値は[GGUF共通設定](gguf-settings.md)を参照してください。

## 出力

| 出力 | 用途 |
|---|---|
| `emd_fragment` | EnhancerまたはPlannerの`concept_emd`へ渡す編集可能なSubject EMD |
| `reference_bindings` | 解決したPicture参照を持つtyped artifact |
| `image` | H3の`ref_image_N`へ渡す元IMAGE pass-through |
| `observations_json` | Enhancerへ渡す可視観察とprovenance |

## 使い方

1. キャラクター立ち絵、顔、側面、背面等を同じIMAGE batchへまとめます。
2. Vision model pairを選びます。
3. 画像から判断できない特徴だけを`subject_hint`へ自然文で書きます。`subject_hint:`等のprefixは不要です。
4. `image`出力をH3の対象`ref_image_N`へ直接接続します。
5. 実行後にノード内の読み取り専用表示が`<Picture N>`になったことを確認します。

複数viewは明らかに別人でない限り、一人のキャラクターとして統合します。左右に並べた画像の画面分割や背景は識別特徴ではありませんが、H3へ同じ合成画像を参照として渡すと分割構図を継承することがあります。可能ならH3用参照は一枚の自然な構図にし、Visionの複数view分析とは分けて検証してください。

`lock_identity`では`subject_hint`を「優先して保持する識別特徴」としてSubject文の前方へ一度だけ置き、Visionの外見推定より高い文章上の優先度を与えます。Visionの`SUBJECT_FEATURE`はhintにない追加の可視識別情報だけを、一record一事実で返します。hintの事実を要約、言い換え又は詳述して再掲せず、助詞を省いた短縮tag、同義語又はhint文から分割した断片も重複として省略します。追加特徴は対象部位や物品を本文内で明記した自己完結する自然な日本語に限定し、`丸く横に線が伸びない、髪と同じ色`のように参照先をhintへ依存する断片を出しません。locked factと新規factが混ざる候補は新規factだけへ分離します。hintだけで可視identityを網羅する場合は`SUBJECT_FEATURE`を0件にし、重複候補より省略を優先します。Python rendererはユーザー文の意味を書き換えず、このLLM契約に従った追加factだけを後置します。

誤認しやすい特徴は、例えば`短く小さな丸い眉で横長ではない。白い足袋と、赤い鼻緒の黒い木下駄を着用する。`のように、形・色・材質・構造を分けて指定してください。Visionにも丸眉と横長眉、白足袋と裸足又はタイツ、木下駄本体と鼻緒を区別し、locked hintと競合又は重複する推定特徴を併記しないよう要求します。

`auto_h3`で異なるPicture番号へ同時分岐した場合は曖昧として停止します。H3へ未接続でもEMD生成は成功し、bindingは`unbound`になります。

`scene_only`は人物のいない背景画像を対象にできます。全profileで、protocol上「値又は空」と定義された単値record（`PRIMARY_SUBJECT`、`SUBJECT_POSE`、構図・背景・style各fieldなど）の行自体を小型modelが省略した場合は、本文を生成せず空値へ復元してwarningを残します。名前が既知のrecordの順序入替えや応答再開による重複も正規順へ決定論的に復旧します。意味payloadのない冗長な`protocol_id` labelは除外します。`SUBJECT_FEATURE`でcategoryだけが欠けた場合は、本文を一切変更せず汎用category `distinctive_feature`と保守的なvisibility `partial`へ収容してwarningを残します。本文欠落、意味payloadを持つ未知record、`HINT_STATUS`などの必須値欠落及び不正なfield値は推測せず、format retry又は明示エラーにします。
