# ComfyUI-MV-Director

画像、歌詞、ボーカルステム、フルミックスと、空又は短い希望から、MiniMax H3 / Context Loopで試写できるMV計画を作るためのフロントエンドです。利用者にプロンプト記述を要求せず、生成された表現の最終評価と採用は人間が行います。

EMDは**Easy MarkDown**の略です。Extended Markdownではありません。人が読み書きできる`# サブジェクト`、`# 保持分析`、任意の`# 共通プロンプト`、`# シーン`を持ちます。共通プロンプトは任意の`## スタイル`、`## モーション`、`## カメラ`、`## その他`へ分け、存在する本文だけをこの順でContext Loop Planの`prompt_prefix`へ写します。

## 現在の状態

2026-09-16時点で**Phase 0～4をFake backendで実装済み**です。ComfyUI非依存のartifact型、canonical JSON、LLM/Vision行protocol、厳密EMD parser、翻訳保護span、Ref2VA六セクションrenderer、Context Loop Plan serializer、versioned H3 Timing Profile、GGUF scanner・ComfyUI `folder_paths` adapter・lifecycle・context予算・成功専用cacheを検証しています。Phase 3のImage to Subject EMDに加え、Phase 4では固定Style／Motion／Camera profile、権限順付き統合payload、欠落slotだけの一回局所retry、Direction artifact、provenance、EMD preview及び`MVDirectorDirectionEnhancer` wrapperを追加しました。実GGUF/Vision推論、Whisper解析及びH3レンダリングはまだ実施していません。旧プロジェクトやComfyUIの実行側は変更していません。

開発方針は「互換性ではなく、必要な実装資産だけを再利用する」です。旧workflow、node ID、入力形式、出力schema及び修復経路との互換性は持たせません。一方、PCM padding、GGUF探索、model lifecycle、音声区間処理など、新仕様でも責務が変わらない有限な処理は選別して再利用します。旧実装に存在するという理由だけで、flag、fallback、validator又は補助nodeを新プロジェクトへ持ち込みません。

## 選定した最小パイプライン

![選定した最小パイプライン。画像、演出、歌詞と音声からEMDを計画・コンパイルし、Context LoopとH3 Ref2VAへ渡す流れ](docs/assets/minimal-pipeline.svg)

コアはImage to Subject EMD、Enhancer、Planner、Compilerの4ノードを新設します。公開support nodeとして`MV Director - Lyric Segmentation`とAudio Pad Pair、公開utility nodeとしてH3 Timing Profile、32-bit Seed、String Combo、Connected Combo、Load Text Fileを置きます。Load Text Fileは`[VERSE1]`等のsectionを持つplain lyrics `.txt`をブラウザで選択/D&Dし、workflowへ埋め込まれたUTF-8本文をSTRINGとして返します。LRC又はSRTは入力せず、SRTはLyric Segmentationの出力専用です。Lyric Segmentationは歌詞とボーカルだけからTemplate EMD、SRT、typed timelineを返し、PlannerやH3を使わない字幕作成にも利用できます。Image to Subject EMDの主成果は編集可能なEMDサブジェクト断片であり、同じIMAGEをH3の`ref_image_N`へ接続した時だけ対応する`<Picture N+1>`を自動束縛し、解決結果をノード内の読み取り専用テキストへ表示します。初期自動MV経路のEnhancerとPlannerは一個のImage to Subject EMDだけを受け取り、複数断片を統合しません。旧Prompt Mergerは独立ノードとして移植せず、ユーザー指示を最優先に統合する責務をEnhancerへ含めます。

## ComfyUI名前空間

本プロジェクトのノードは既存の`MiniMax H3/...`カテゴリ及び`CL...` node typeを使用しません。workflowへ保存される機械向けIDは`MVDirector...`、表示カテゴリは`MV Director/...`、内部socket型は`MV_DIRECTOR_...`で統一します。4コアのtype IDは`MVDirectorImageToSubjectEMD`、`MVDirectorDirectionEnhancer`、`MVDirectorTimelinePlanner`、`MVDirectorEMDCompiler`、support nodeは`MVDirectorLyricSegmentation`と`MVDirectorAudioPadPair`、utility nodeは`MVDirectorH3TimingProfile`、`MVDirectorSeed32`、`MVDirectorStringCombo`、`MVDirectorConnectedCombo`、`MVDirectorLoadTextFile`です。旧IDの互換aliasは登録しません。

初期方式は次のとおりです。

- Whisperが歌詞の語句・行の位置候補を検出し、20msの粗いVAD区間から波形上の開始・終了をsample-domainで再探索します。確定sample indexを整数msへ変換してtimelineへ保持し、整数秒へ丸めません。これは1ms単位の決定値ですが、音響的な正解はVAD thresholdと入力品質に依存します。
- EMDの各Sceneはデバッグ用の``> `シーン` N``を直前に必須とし、`# シーン 00:10.000 --> 00:20.000`、Shotは`## ショット 00:15.000`のように、H3 delivered frame累積から得たPlan基準の絶対時刻で記述します。「秒」表記と省略時刻は使いません。歌詞とSRTだけは元音源基準の絶対msを保持し、MV経路のTemplate EMDでは各SceneへContext Loop互換の`` `H3長` ``も記録します。
- Lyric Segmentationは歌詞の物理改行と空白区切りをatomic segmentとしてWhisper/VADで整列し、その同じsegment列からTemplate EMD、typed timeline、SRTを作ります。各segmentの所属Scene／Shotもここで確定し、歌詞annotationを対応Shot見出しの直前へ置きます。歌詞時刻は元音源基準、Shot見出しはH3 Plan基準なので、PlannerとCompilerは数値包含で再対応付けせず、歌詞も再分割しません。CompilerはH3へ出す時だけScene開始を引いてShot相対時刻へ変換し、EMDの絶対msは変更しません。
- 人物動作とカメラは別のLLMタスクにし、同じShot枠へPythonが合成します。人物動作の固定文をカメラ生成に再出力させません。
- Timeline Plannerは`n_ctx`、`n_batch`、GPU layer、Flash Attention、KV cache等のllama.cpp調整値を旧ノード同様に公開します。Direction artifactはEnhancerから四方向を型付きで渡す任意の内部socket値で、利用者向けには同内容のEMD previewも出力します。
- EnhancerとPlannerのLLMにはJSONやEMDを返させません。応答は`TYPE<TAB>SLOT<TAB>TEXT`の一行一recordに限定し、短いslotと実Scene/Shot ID・時刻の対応、typed artifact、EMD及び最終JSONはPythonが組み立てます。4Bが括弧、引用符又はJSON escapeを維持することへ依存しません。
- Plannerへ渡る作者由来の`「...」`と明示`<d>...</d>`は先にplaceholderへ退避します。LLMが新しい引用台詞を生成してもretryせず、そのspanを機械削除してから既知placeholderだけを原文復元します。歌詞リップシンクはfilter後にPythonが挿入します。
- EMDは人間が読める日本語のEasy MarkDown中間言語です。`# サブジェクト`で作品内IDの`` `人物N` ``、`` `場所N` ``、`` `物品N` ``を定義し、Ref2VAの意味上の`<Subject N>`と物理画像の`<Picture N>`を明示的に関連付けます。`<Subject N>`自体を画像入力slotとして扱いません。任意の`# 共通プロンプト`はスタイル、モーション、カメラ、その他を構造的に分離し、Compilerは見出しを除いた存在する本文をこの固定順でPlanの`prompt_prefix`へ出力します。スタイルがあれば必ず先頭です。
- CompilerはEMD parser、限定翻訳orchestrator、JSON serializerです。H3へ渡す日本語の描写文だけを英訳し、補強・要約・並べ替えはしません。
- 翻訳処理はCompiler内部の交換可能な`PromptTranslator` adapterとし、初期比較候補は4Bと8Bを想定します。既に英語のEMDは明示的なpass-through modeで処理できます。
- Compilerでは従来どおり、ComfyUIの`models/LLM/GGUF`と追加`LLM` pathで見つかった任意のGGUFを`model_name` comboから選択できます。特定modelを組込みません。
- CompilerはRef2VA専用です。完全EMD文字列と選択GGUFだけで単独コンパイルでき、Vision、Enhancer、Plannerのcustom socketや画像・音声tensorを必須入力にしません。`人物N`等の内部IDと`<Subject N>`は必須ですが、`<Picture N>`関連は任意です。Pictureなしでは文章定義だけのH3内蔵概念としてRef2VAを出力し、`required_references`は実際に記述されたPicture/Audioだけ、又は空配列になります。T2VA、I2VA等は同じCompilerへmode追加せず、必要になった時に別Compilerとして設計します。
- Lyric SegmentationはMV用Template EMDを作る段階で、基準Context Loop profileに合わせて24fpsとH3の`17k+5`格子へSceneを割り当て、raw `length`を`` `H3長` ``として確定します。Compilerはその整数を再計算・補正せず、Plan JSONの`length`へそのまま写します。SRTと歌詞alignmentは元音源の絶対msを保持します。
- Compilerは各SceneにContext Loop 0.6.6互換の完全なRef2VA六セクションを英語で出力します。Shotは先頭を`[Shot 1]`、2番目以降を`[Shot N] At MM:SS.mmm,`とします。EMDの構造、Scene/Shot順、情報量、binding、directiveはas-isで保持し、必須欄はLLMではなく固定テンプレートで機械的に満たします。
- 音響は説明文を解釈せず、予約directiveだけをCompilerが固定変換します。リップシンクは`lip_sync_mode`の`使用しない`、`Context Loop`、`Audio参照`、`歌詞`をPlannerのコンボで切り替え、EMDでは``リップシンク <方式>``へ統一します。歌詞annotationは全方式で完成EMDに保持し、人物動作の材料として使います。`歌詞`の時だけ対応Shotへ対象と原文を持つdirectiveを機械挿入します。`Context Loop`と`Audio参照`は歌詞annotationのあるSceneだけを有効化し、`Audio参照`動画生成WFはLyric Segmentationのsource Scene境界で元vocalを連続sliceして一個の`<Audio 1>`へ渡します。Compilerはannotationをpromptへ出さず、PCMも扱わず、明示directiveだけを固定promptへ写して翻訳LLMへ渡しません。完成動画へ残す音声はEMDやPlannerではなく、対応する動画生成WFのChain Policyが決定します。歌詞方式はH3へShot区間内の歌唱口形を促す粗い時間誘導であり、音素単位の完全同期は保証しません。`無音`は非MV利用のための将来互換directiveとしてoff値とsilence prompt要素だけを出し、PCMゲートは初期MVスコープへ含めません。
- `「...」`の内容は変更せず`<d>[Japanese]...</d>`へ包みます。作者がShot本文へ直接書いた`<d>...</d>`又は`<d>[English]...</d>`は翻訳・言語推定・二重包装をせず、そのままH3へ渡します。追加発声禁止は`明示台詞のみ`が書かれた場合だけ出力します。
- LLM生成の成功結果は入力・モデル・生成条件・プロンプト版で固定できます。固定後はContext Loop/H3側のseedだけを変えて比較できます。

## 入力と利用者の負担

初期自動MV経路の必須入力は歌詞、ボーカルステム、フルミックスです。参照画像は任意ですが、使わない場合も人間が`# サブジェクト`で`人物N`等と`<Subject N>`を定義します。PlannerはMV専用で、既定では`lip_sync_mode=lyrics`として歌詞方式のリップシンクdirectiveを出します。標準配布は三方式ごとのPlan/Compiler WFと動画生成WFを一対一にした計6 WFで、最終音声方針は後者が所有します。Image to Subject EMDは`picture_reference_mode=none`でも利用でき、Pictureあり又はH3内蔵概念だけの複数Subjectを手書きした完全EMDもCompiler単独経路で処理できます。T2VA、I2VA等は現在のCompilerの責務外です。ユーザー希望は空でも構いません。

画像に写っていない重要特徴をVisionへ推測させません。Image to Subject EMDには`subject_hint`と`additional_instruction`の独立STRING socketを設け、`analysis_profile`、`hint_mode`、`hint_conflict`、`picture_reference_mode`、`concept_type`、概念番号、Subject番号、Picture番号も外部接続可能にします。名前付きプレフィクスは不要で、`淡い金色の短い丸眉で、狐の尾は一本です。`のような日本語自然文をそのまま入力します。旧`subject_hint:`形式を検出・除去する互換parserは設けません。顔や衣装の重要条件を利用者が明示した場合は、観察結果とprovenanceを分けて全体方針へ統合します。

## 対象環境

- 8GB VRAM
- 4B又は8B級ローカルGGUFモデル
- 4Bでは32Kを初期比較値、8Bでは16Kを基準とする実効コンテキスト
- クラウドLLMやVRAM増設を前提にしない

これらのcontext値は保証ではありません。各タスクで最終的にシリアライズされる入力、出力予約、安全余裕を合算し、実効上限を超える前に有限分割又は明示停止します。分割で呼び出し数や総時間が増える可能性は実測します。

## 文書

- [設計引き継ぎ](docs/handoff.md)
- [最小コア仕様](docs/spec/minimal-core-spec.md)
- [EMD（Easy MarkDown）仕様書](docs/spec/emd-spec.md)
- [プロトコル仕様](docs/spec/protocol-spec.md)
- [実装仕様](docs/implementation/implementation-spec.md)
- [既存部品の移植可否と実装順序](docs/implementation/components-and-order.md)
- [公開ノード一覧と配置](docs/implementation/public-nodes-and-layout.md)
- [`prompt_prefix`調査](docs/research/context-loop-prompt-prefix.md)
- [実装前仕様漏れ監査](docs/research/spec-gap-audit-2026-09-16.md)

## ライセンス

Copyright © 2026 `wsoldwolf`

ソースコードと文書は、別途明記された場合を除き[GNU General Public License v3.0 only](LICENSE)（`GPL-3.0-only`）で公開します。

`assets/`に収録した検証用楽曲、歌詞、ボーカルステム及び参照画像はソフトウェアライセンスの対象外です。現在収録している素材は[CC BY-NC 4.0](ASSET_LICENSES.md)で公開し、対象ファイル、生成元及び帰属条件は同文書に明記します。将来追加される素材へこの条件は自動適用されません。

## 次の作業

次はPhase 5のLyric Segmentationを、plain lyricsのatomic分割、Whisper alignment境界、20ms VADとsample-domain refinement、H3 timing量子化、Template EMD及びSRT serializerの順で実装します。その後にPlannerへ進み、Context Loop 0.6.6のcommit `136db5dbbf25405063a96e898ae880e8785b7f29`との互換試験、4B/8Bの英訳品質及び8GB VRAM環境での全体成立性を測ります。
