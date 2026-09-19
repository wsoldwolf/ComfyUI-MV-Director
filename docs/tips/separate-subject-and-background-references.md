# 人物参照と背景参照を分ける

人物の立ち絵と背景を一枚又は一つのPicture参照へ同居させると、H3の参照条件が人物identity、顔、髪、衣装及びposeへ強く使われ、背景の建築、植生、地形、材質及び空間構成が希薄化又は消失しやすくなります。人物を`<Picture 1>`、背景を環境専用の`<Picture 2>`として別々に与える構成を推奨します。背景の条件信号を人物identityから独立させることで、一つの人物参照へ背景も担わせる場合より背景再現率を高められます。ただし、参照画像の画素単位の複製を保証するものではありません。

## 推奨配線

1. 人物側のImage to Subject EMDを`subject_only / person / picture_reference_mode=manual / picture_index=1`にします。
2. 背景側のImage to Subject EMDを`scene_only / location / picture_reference_mode=manual / picture_index=2`にします。
3. 人物Visionの`emd_fragment`をDirection EnhancerとTimeline Plannerの`concept_emd`へ分岐します。
4. 背景Visionの同じ`emd_fragment`をDirection EnhancerとTimeline Plannerの`scene_emd`へ分岐します。`scene_only`ではこのsocketが`MVD_SCENE_EMD_FRAGMENT_V1`の`# シーン設定`を返します。
5. 動画生成workflowでは人物画像をH3の`ref_image_0`、同じ背景画像を`ref_images.ref_image_1`へ渡します。

`observations_json`はVisionの検証・debug用です。Direction Enhancer又はPlannerの入力には使いません。Plannerは背景IMAGE tensorを直接受け取らず、検証済みのScene EMD断片を完成EMDへAS ISで統合します。Compilerはそこから`<Picture 2>`の環境専用定義、保持契約及び必要参照を生成します。

## 何を背景から保持するか

背景Pictureは建築、植生、地形、材質及び空間同一性のために使います。参照画像に含まれる人物、pose、文字、分割構図、camera angle及び撮影時の照明は、目標Sceneへコピーする条件ではありません。Direction又は共通プロンプトで指定した環境、時刻及び照明を背景画像の撮影条件より優先します。

背景画像に人物を含めると、背景専用Pictureでも人物や構図を継承する確率が上がります。可能なら人物のいない背景画像を使い、人物の顔や衣装の追加viewは人物側のIMAGE batchへまとめてください。

## 一枚にまとめる場合

入力資産を一枚にまとめる必要がある場合、Visionは複数viewを同一人物として観察できますが、H3へ合成画像をそのまま渡すと左右分割、白背景、設定画pose又は複数人物の構図を継承することがあります。Vision解析用の複数view画像とH3生成用の自然な単一構図画像を分けると、この影響を減らせます。

