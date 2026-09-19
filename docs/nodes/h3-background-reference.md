# H3 Background Reference

コンパイル済みPlan JSONへ背景専用の`<Picture N>`契約を決定論的に追加し、同じ背景IMAGEをH3へpass-throughします。背景のVision認識やShot計画は行いません。前段では従来どおり`observations_json → Direction Enhancer`を使い、このノードは動画生成時だけ使用します。

## 分離する理由

人物と背景を同じ参照画像又は同じPicture roleへ押し込むと、人物identity、顔、髪、衣装及びposeの情報が参照条件を占有し、背景の建築、植生、地形、材質及び空間構成が相対的に弱まり、生成時に失われやすくなります。背景を別画像かつ別Pictureへ分離すると、H3へ環境証拠を独立した条件信号として渡せるため、人物参照だけに背景も担わせる場合より背景再現率が上がります。

これは背景画像をそのまま貼り付ける機能ではなく、再現率の向上を目的とする条件分離です。Shot固有の構図、Camera、Action、文章で指定した環境、時刻及び照明は引き続き上位authorityであり、背景画像の画素、撮影構図、昼夜又は照明の完全一致は保証しません。

## 入力

| 入力 | 既定 | 説明 |
|---|---:|---|
| `plan_json` | 必須 | EMD Compilerが生成したH3 Plan JSON |
| `background_image` | 必須 | H3の背景参照slotへ渡す画像 |
| `picture_index` | `2` | 対応するPicture番号、1～9。人物参照がPicture 1なら背景は2を使う |

## 出力

| 出力 | 用途 |
|---|---|
| `plan_json` | 背景参照契約を全Shotへ追加したPlan JSON |
| `background_image` | 入力IMAGEのpass-through。H3の対応する`ref_images.ref_image_N`へ接続する |
| `status` | Picture番号、更新Shot数及び`role=environment` |

## H3 promptへの統合

各Shotの`subject_definitions:`へ、Pictureを人物、演者、storyboard、panel layout、構図template又は照明authorityとして扱わず、建築、植生、地形、材質及び空間同一性だけの背景証拠として使う固定文を追加します。`retention_analysis:`には同じPictureを`environment_partially_preserved`として追加します。

Direction Enhancerからコンパイル済みPlanへ入った環境及び時間・照明の文章が常に上位です。参照画像と競合する季節、天候、時刻、照明、人物、pose、文字、画面分割、camera angle又は構図は継承しません。これにより、昼の背景参照を使いながら文章では夜を指定する、といった使い方ができます。

同じPlanへ同じ`picture_index`で複数回適用しても固定行は一組だけです。Scene、Shot、Action、Camera、時刻、音声及びdenoising設定は変更しません。

## 接続例

1. `Compiled Plan JSON`を`plan_json`へ接続します。
2. 背景Load Imageを`background_image`へ接続します。
3. 出力`plan_json`をProduction PlanとAudio Pad Pairへ接続します。
4. 出力`background_image`をH3 Reference to Videoの`ref_images.ref_image_1`へ接続します。

人物画像は従来どおり`ref_image_0`、背景画像は`ref_image_1`です。Picture番号はH3の0始まりinputより1大きいため、`ref_image_1`は`<Picture 2>`に対応します。

同じ合成画像から人物領域と背景領域を意味上分離するだけでは、H3へ渡るPicture条件は分離されません。背景再現を重視する場合は、人物画像とは別ファイルの背景画像を`background_image`へ接続してください。
