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

`auto_h3`で異なるPicture番号へ同時分岐した場合は曖昧として停止します。H3へ未接続でもEMD生成は成功し、bindingは`unbound`になります。
