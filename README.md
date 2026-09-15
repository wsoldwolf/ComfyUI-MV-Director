# ComfyUI-MV-Director

画像、歌詞、ボーカルステム、フルミックスと短い希望から、MiniMax H3 / Context Loopで試写できるMV計画を作るためのフロントエンドです。利用者に詳細な演出文の作成を要求せず、生成された表現の最終評価と採用は人間が行います。

EMDは**Easy MarkDown**の略です。Extended Markdownではありません。人が読み書きできる`# サブジェクト`、`# 保持分析`、`# 共通プロンプト`、`# シーン`の四部構造を持ち、`# 共通プロンプト`はContext Loop Planの`prompt_prefix`へ写します。

## 現在の状態

2026-09-15時点では**設計引き継ぎと初期仕様の段階**です。新コアノード、実モデル推論、H3レンダリングはまだ実装・実施していません。旧プロジェクトやComfyUIの実行側も変更していません。

開発方針は「互換性ではなく、必要な実装資産だけを再利用する」です。旧workflow、node ID、入力形式、出力schema及び修復経路との互換性は持たせません。一方、PCM padding、GGUF探索、model lifecycle、音声区間処理など、新仕様でも責務が変わらない有限な処理は選別して再利用します。旧実装に存在するという理由だけで、flag、fallback、validator又は補助nodeを新プロジェクトへ持ち込みません。

## 選定した最小パイプライン

![選定した最小パイプライン。画像、演出、歌詞と音声からEMDを計画・コンパイルし、Context LoopとH3 Ref2VAへ渡す流れ](docs/assets/minimal-pipeline.svg)

コアはImage to Subject EMD、Enhancer、Planner、Compilerの4ノードを新設します。公開support nodeとして`MV Director - Lyric Segmentation`とAudio Pad Pair、公開utility nodeとしてH3 Timing Profile、32-bit Seed、String Combo、Connected Combo、Load Text Fileを置きます。Load Text Fileはローカルの歌詞、LRC、SRT又は通常テキストをブラウザで選択/D&Dし、workflowへ埋め込まれたUTF-8本文をSTRINGとして返します。Lyric Segmentationは歌詞とボーカルだけからTemplate EMD、SRT、typed timelineを返し、PlannerやH3を使わない字幕作成にも利用できます。Image to Subject EMDの主成果は編集可能なEMDサブジェクト断片であり、Ref2VAで使う場合だけ同じIMAGEと`<Picture N>`の関係を出力します。旧Prompt Mergerは独立ノードとして移植せず、ユーザー指示を最優先に統合する責務をEnhancerへ含めます。

## ComfyUI名前空間

本プロジェクトのノードは既存の`MiniMax H3/...`カテゴリ及び`CL...` node typeを使用しません。workflowへ保存される機械向けIDは`MVDirector...`、表示カテゴリは`MV Director/...`、内部socket型は`MV_DIRECTOR_...`で統一します。4コアのtype IDは`MVDirectorImageToSubjectEMD`、`MVDirectorDirectionEnhancer`、`MVDirectorTimelinePlanner`、`MVDirectorEMDCompiler`、support nodeは`MVDirectorLyricSegmentation`と`MVDirectorAudioPadPair`、utility nodeは`MVDirectorH3TimingProfile`、`MVDirectorSeed32`、`MVDirectorStringCombo`、`MVDirectorConnectedCombo`、`MVDirectorLoadTextFile`です。旧IDの互換aliasは登録しません。

初期方式は次のとおりです。

- Whisperが歌詞の語句・行の位置候補を検出し、20msの粗いVAD区間から波形上の開始・終了をsample-domainで再探索します。確定sample indexを整数msへ変換してtimelineへ保持し、整数秒へ丸めません。これは1ms単位の決定値ですが、音響的な正解はVAD thresholdと入力品質に依存します。
- EMDのSceneは`# シーン 00:10.000 --> 00:20.000`、Shotは`## ショット 00:15.000`のように、H3 delivered frame累積から得たPlan基準の絶対時刻で記述します。「秒」表記と省略時刻は使いません。歌詞とSRTだけは元音源基準の絶対msを保持し、MV経路のTemplate EMDでは各SceneへContext Loop互換の`` `H3長` ``も記録します。
- Shot境界はScene内の整列済み歌詞開始時刻からPythonが有限規則で作ります。CompilerはH3へ出す時だけScene開始を引いて相対時刻へ変換し、EMDの絶対msは変更しません。
- 人物動作とカメラは別のLLMタスクにし、同じShot枠へPythonが合成します。人物動作の固定文をカメラ生成に再出力させません。
- EMDは人間が読める日本語のEasy MarkDown中間言語です。`# サブジェクト`で作品内IDの`` `人物N` ``、`` `場所N` ``、`` `物品N` ``を定義し、Ref2VAの意味上の`<Subject N>`と物理画像の`<Picture N>`を明示的に関連付けます。`<Subject N>`自体を画像入力slotとして扱いません。`# 共通プロンプト`の先頭には作品全体の目標画風を置き、Compilerは順序を変えずPlanの`prompt_prefix`へ出力します。
- CompilerはEMD parser、限定翻訳orchestrator、JSON serializerです。H3へ渡す日本語の描写文だけを英訳し、補強・要約・並べ替えはしません。
- 翻訳処理はCompiler内部の交換可能な`PromptTranslator` adapterとし、初期比較候補は4Bと8Bを想定します。既に英語のEMDは明示的なpass-through modeで処理できます。
- Compilerでは従来どおり、ComfyUIの`models/LLM/GGUF`と追加`LLM` pathで見つかった任意のGGUFを`model_name` comboから選択できます。特定modelを組込みません。
- CompilerはRef2VA専用です。完全EMD文字列と選択GGUFだけで単独コンパイルでき、Vision、Enhancer、Plannerのcustom socketや画像・音声tensorを必須入力にしませんが、出力する`required_references`にはRef2VAで必要な`<Picture N>`を必ず列挙します。T2VA、I2VA等は同じCompilerへmode追加せず、必要になった時に別Compilerとして設計します。
- Lyric SegmentationはMV用Template EMDを作る段階で、基準Context Loop profileに合わせて24fpsとH3の`17k+5`格子へSceneを割り当て、raw `length`を`` `H3長` ``として確定します。Compilerはその整数を再計算・補正せず、Plan JSONの`length`へそのまま写します。SRTと歌詞alignmentは元音源の絶対msを保持します。
- Compilerは各SceneにContext Loop 0.6.6互換の完全なRef2VA六セクションを英語で出力します。Shotは先頭を`[Shot 1]`、2番目以降を`[Shot N] At MM:SS.mmm,`とします。EMDの構造、Scene/Shot順、情報量、binding、directiveはas-isで保持します。
- 音響は説明文を解釈せず、予約directiveだけをCompilerが固定変換します。リップシンクは現行の`ソースボーカル同期`に加え、LipSyncOptions経路の追加モデルを使わない`音声参照駆動`とShot単位の`リップシンク歌詞`を実装します。Plannerが歌詞annotationと時刻を読み、対応Shotへ対象と原文を明記します。Compilerはannotationを参照せず、明示されたShot directiveを時間付き固定promptへ写し、翻訳LLMへ渡しません。これはH3へ区間内の歌唱口形を促す粗い時間誘導であり、音素単位の完全同期は保証しません。`無音`は非MV利用のための将来互換directiveとしてoff値とsilence prompt要素だけを出し、PCMゲートは初期MVスコープへ含めません。
- `「...」`の内容は変更せず`<d>[Japanese]...</d>`へ包みます。追加発声禁止は`明示台詞のみ`が書かれた場合だけ出力します。
- LLM生成の成功結果は入力・モデル・生成条件・プロンプト版で固定できます。固定後はContext Loop/H3側のseedだけを変えて比較できます。

## 入力と利用者の負担

自動MV経路の必須入力は歌詞、ボーカルステム、フルミックスと、Ref2VAへ渡す一枚以上の参照画像です。Image to Subject EMDは`picture_reference_mode=none`でも単独利用できますが、現在のRef2VA専用Compilerへ渡す完全EMDでは`# サブジェクト`に`<Picture N>`の関連付けが必要です。画像なしの概念生成、T2VA、I2VA等は現在のCompilerの責務外です。ユーザー希望は空でも構いません。

画像に写っていない重要特徴をVisionへ推測させません。Image to Subject EMDには`subject_hint`と`additional_instruction`の独立STRING socketを設け、`analysis_profile`、`hint_mode`、`hint_conflict`、`picture_reference_mode`、`concept_type`、概念番号、Subject番号、Picture番号も外部接続可能にします。名前付きプレフィクスは不要で、`淡い金色の短い丸眉で、狐の尾は一本です。`のような日本語自然文をそのまま入力します。旧`subject_hint:`形式を検出・除去する互換parserは設けません。顔や衣装の重要条件を利用者が明示した場合は、観察結果とprovenanceを分けて全体方針へ統合します。

## 対象環境

- 8GB VRAM
- 8B級ローカルGGUFモデル
- 実効コンテキスト約16K
- クラウドLLMやVRAM増設を前提にしない

16Kは保証値ではありません。各タスクで最終的にシリアライズされる入力、出力予約、安全余裕を合算し、実効上限を超える前に有限分割又は明示停止します。分割で呼び出し数や総時間が増える可能性は実測します。

## 文書

- [設計引き継ぎ](docs/handoff.md)
- [最小コア仕様](docs/spec/minimal-core-spec.md)
- [既存部品の移植可否と実装順序](docs/implementation/components-and-order.md)
- [公開ノード一覧と配置](docs/implementation/public-nodes-and-layout.md)
- [`prompt_prefix`調査](docs/research/context-loop-prompt-prefix.md)

## ライセンス

Copyright © 2026 `wsoldwolf`

ソースコードと文書は、別途明記された場合を除き[GNU General Public License v3.0 only](LICENSE)（`GPL-3.0-only`）で公開します。

`assets/`に収録した検証用楽曲、歌詞、ボーカルステム及び参照画像はソフトウェアライセンスの対象外です。現在収録している素材は[CC BY-NC 4.0](ASSET_LICENSES.md)で公開し、対象ファイル、生成元及び帰属条件は同文書に明記します。将来追加される素材へこの条件は自動適用されません。

## 次の作業

次の実装回では、まず`nodes/`配下の独自node type、`# サブジェクト`と`<Picture N>`関連を読むEMDパーサー、Ref2VA六セクションrenderer、PromptTranslator interface、`` `H3長` ``を無変換で渡す単独CompilerをFake backendで通します。実装基準は現在動作確認に使うContext Loop 0.6.6のcommit `136db5dbbf25405063a96e898ae880e8785b7f29`とし、実装後に当該commitとの互換性テストを行います。その後に4B/8Bの英訳品質とImage to Subject EMDを接続し、8GB VRAM環境で全体の成立性を測ります。
