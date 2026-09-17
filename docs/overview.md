# プロジェクト概要

ComfyUI-MV-Directorは、利用者が完成promptを手書きしなくても、画像、歌詞、ボーカル、楽曲からMiniMax H3 / Context Loop用のMV計画を組み立てるフロントエンドです。生成結果の美術的な採否は人間が判断します。

![MV Directorの最小パイプライン](assets/minimal-pipeline.svg)

## 四つのコア

1. Image to Subject EMDが参照画像の可視情報をSubjectとして記述します。
2. Direction Enhancerがスタイル、環境、時間・照明、モーション、カメラ、その他の全体方針を作ります。
3. Timeline Plannerが確定済みScene/Shot枠へ歌詞解釈、人物動作、カメラ、リップシンク方式を展開します。
4. EMD Compilerが日本語promptだけを英訳し、Ref2VA用Context Loop Plan JSONへ機械的に変換します。

Lyric Segmentationはこの経路と独立して歌詞、SRT、typed timelineを生成できます。Audio Pad Pairはfull mixとvocalを混合せず、PCM無音で必要尺へそろえます。

## EMD

EMDは **Easy MarkDown** です。人が確認・編集できる中間表現で、主に次を持ちます。

- `# サブジェクト`: 1 list itemを文書順に`<Subject 1..4>`へ割り当てます。行頭の``画像N``、``動画N``、``音声N``は任意のH3参照です。
- `# 保持分析`: Subjectのどの識別要素を保持するかを記述します。
- `# 共通プロンプト`: 任意の`## スタイル`、`## 背景`、`## 時間・照明`、`## モーション`、`## カメラ`、`## その他`を持ちます。
- `# シーン`: `00:00.000`形式の絶対ms timeline、Shot、歌詞annotation、予約directiveを持ちます。

厳密な構文は[EMD仕様書](spec/emd-spec.md)を参照してください。

## LLMへ任せる範囲

Vision、演出、Shot計画、英訳にはローカルGGUFを使いますが、JSONやEMDそのものをLLMへ生成させません。LLM応答は短い行指向protocolで受け、typed artifact、EMD、最終JSONはPythonが組み立てます。

Compilerは補強、要約、並べ替えをせず、EMD文法と予約directiveを機械的に処理します。作者が書いた`<d>...</d>`は翻訳せず、そのままH3へ渡します。

## リップシンク方式

- `context_loop`: Context Loop標準のsource vocal駆動。
- `audio_reference`: Sceneに対応する`<Audio N>`参照による駆動。
- `lyrics`: Shotの歌詞directiveによる粗い時間誘導。音素単位の完全同期は保証しません。
- `off`: リップシンクdirectiveを出力しません。

歌詞annotationは全方式でEMDに残り、人物動作の材料になります。最終音声を何にするかはPlannerやEMDではなく、動画生成workflowのChain Policyが決定します。

## 時間と無音

EMDは`00:00.000`表記、内部timelineは整数msを使います。H3 Scene長は固定Timing Profileに従うframe数が正本です。音源がframe境界より短い場合はAudio Pad PairがPCM無音を追加します。promptに「無音」と書くことだけでは真の無音を保証しません。

## 対象環境と方針

- 主対象は8GB VRAM、4Bまたは8B級のローカルGGUFです。Vision以外の生成・英訳は8Bを推奨します。
- CompilerはRef2VA専用です。T2VAやI2VAは別Compilerの責務です。
- 旧workflow、node ID、schemaとの互換性は持ちません。PCM処理、GGUF探索等、責務が変わらない実装資産だけを再利用します。
- 基準はComfyUI `ee71d5c4993f29086b27fde1629a945ae48425bf`、Context Loop `9860a063784c8c23b58e00107f2180e0df3c43d9`です。
