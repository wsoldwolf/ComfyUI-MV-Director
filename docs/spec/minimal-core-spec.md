# 最小コア仕様

版: `draft-0.20`<br>
作成日: 2026-09-15<br>
状態: 初期実装の基準。現行ノードで利用可能な構文の説明ではない。

## 1. 目的

一枚以上の参照画像、歌詞、ボーカルステム、フルミックスと、空又は短いユーザー希望から、Context Loop / H3 Ref2VAへ渡せる計画を現実的な回数のローカル推論で作る。Image to Subject EMD、Enhancer、Lyric Segmentation及びPlannerは個別利用できるが、本仕様のCompilerはRef2VAだけを出力する。完全なRef2VA EMDがあればCompiler単独でもPlanを作れることを必須境界とする。

本仕様の成功条件は次の二段階に分ける。

1. テキスト成立: 入力予算内で、構造・参照・時刻・音声・保護台詞の対応が有効なPlanを得る。
2. 作品評価: H3映像を人間が比較し、意図、人物一貫性、歌詞への反応、動作、カメラ、手直し量を評価する。

1の合格を2の合格とはみなさない。

### 1.1 旧実装の扱い

本プロジェクトは旧プロジェクトの後継互換版ではない。旧workflow、node type、socket、入力構文、出力schema、cache及び挙動の互換性を要件にしない。

旧実装は部品と知見の参照元としてのみ扱う。新仕様でも責務が同一で、有限かつ単独テスト可能な処理は抽出又は再利用できる。ただし、旧実装に存在すること自体を採用理由にせず、新仕様の必須経路に不要なflag、fallback、repair、validator、prompt、schema及び公開nodeは持ち込まない。再利用部分も`MVDirector...`の契約とテストへ適合させ、旧interfaceを温存しない。

## 2. 構成

### 2.1 新設する4コアノード

| ノード | 主な入力 | 主な出力 | 責務 |
|---|---|---|---|
| `MV Director - Image to Subject EMD` | IMAGE、`subject_hint`、`additional_instruction`、観察・hint・binding制御、Vision model | `MVD_EMD_FRAGMENT_V1`、任意の`MVD_REFERENCE_BINDINGS_V1`、IMAGE pass-through | 可視事実と明示ヒントを区別した編集可能なサブジェクトEMDへし、Ref2VA利用時は同じ画像を`<Picture N>`へ束縛する |
| `MV Director - Direction Enhancer` | 任意の概念EMD、短い希望、演出profile、言語生成seed | `MVD_DIRECTION_V1`、人間向けpreview | 概念・希望・profileを大局的に統合し、短い全体方針へ発展させる。Visionは必須にしない |
| `MV Director - Timeline Planner` | 任意の概念EMD、Template EMD、direction、lip-sync driver、model execution profile | `MVD_EMD_V1`、status | 確定済み時間枠へ概念、歌詞解釈、人物動作、カメラ及び機械的なlip-sync directiveを展開する |
| `MV Director - EMD Compiler` | 完全Ref2VA EMD文字列、H3 timing profile、翻訳mode、選択GGUFとruntime設定 | Context Loop Ref2VA Plan JSON、必要参照一覧、固定artifact | EMD構造を保持し、選択したGGUFでH3 promptへ出す自由文だけを英訳してRef2VA六セクションへ直列化する |

旧Prompt Enhancer、MV Prompt Planner、Japanese to JSONのクラスや実行フローを新ノードの土台にしない。

### 2.2 補助層

- Lyric Segmentation: 歌詞とボーカルからTemplate EMD、SRT、`MVD_TIMELINE_V1`を返す公開support node。MV用TemplateではContext Loop互換のraw `length`も確定する。Planner及びH3実行なしで単独利用できる。
- audio timeline engine: 上記support node内部でVAD、Whisper一回、歌詞整列、Scene/Shot枠生成を行う純粋な層。
- GGUF backend: モデル探索、ロード、token計測、中断、解放を共通化する。
- PromptTranslator: prompt本文の日本語から英語への一方向変換だけを行う交換可能なinterface。初期実装はローカル4B又は8Bを想定するが、LLM固有の契約にはしない。
- Audio Pad Pair: full mixとvocal stemを同じ基準尺へ末尾無音補完する公開support node。単体Audio Padは公開しない。
- H3 Timing Profile: Context Loop基準contract、24fps、anchor mode、visual/audio context lengthを一つの`MV_DIRECTOR_H3_TIMING_PROFILE`へまとめ、Lyric SegmentationとCompilerへ共有する公開utility node。
- 32-bit Seed: GGUF系とH3系へ同じ再現可能な符号付き32-bit正整数seedを分岐する公開utility node。旧実装の有限なrandom/fixed/一回保持処理だけを再利用する。
- String Combo: 文字列候補を通常の接続可能なSTRINGとして選択・出力する公開utility node。
- Connected Combo: サブグラフ内部で頻繁に変更するcomboを外側へ引き出し、接続値を選択肢として扱う公開utility node。
- Load Text File: ローカルの歌詞、LRC、SRT又は通常テキストをブラウザで選択/D&Dし、workflowへ埋め込まれたUTF-8本文をSTRINGとして返す公開utility node。
- Context Loop / H3: 本プロジェクトの下流。変更しない。

### 2.3 独自名前空間

ComfyUIのnode type IDはworkflow互換性を左右するため、初回実装前に次で固定する。

| 用途 | 名前 |
|---|---|
| Image to Subject EMD type / class | `MVDirectorImageToSubjectEMD` |
| Direction Enhancer type / class | `MVDirectorDirectionEnhancer` |
| Timeline Planner type / class | `MVDirectorTimelinePlanner` |
| EMD Compiler type / class | `MVDirectorEMDCompiler` |
| Lyric Segmentation type / class | `MVDirectorLyricSegmentation` |
| Audio Pad Pair type / class | `MVDirectorAudioPadPair` |
| H3 Timing Profile type / class | `MVDirectorH3TimingProfile` |
| 32-bit Seed type / class | `MVDirectorSeed32` |
| String Combo type / class | `MVDirectorStringCombo` |
| Connected Combo type / class | `MVDirectorConnectedCombo` |
| Load Text File type / class | `MVDirectorLoadTextFile` |
| 将来の補助node type | `MVDirector`接頭辞を必須とする |
| 表示カテゴリ | `MV Director/Core`、`MV Director/Input`、`MV Director/Audio`、`MV Director/Utilities` |
| 表示名 | `MV Director - ...` |
| custom socket / data type | `MV_DIRECTOR_...` |
| schema ID | 既存どおり`MVD_..._V1` |
| logger / cache / web extension | `mv_director`、`mv_director/...`、`mv_director.*` |

旧プロジェクトの`CL...` type IDと`MiniMax H3/...`表示カテゴリは登録しない。後方互換aliasも作らない。`MiniMaxH3...`はContext Loopへ接続する外部typeの検出名に限り、自ノードの名前空間には使わない。

### 2.4 疎結合の必須経路

次の3経路を独立した受入対象にする。

1. Ref2VA自動MV: Image to Subject EMDのサブジェクト断片と`<Picture N>`関連をPlannerが完全EMDへ取り込み、Compilerへ渡す。
2. 上流単独利用: Image to Subject EMDの`picture_reference_mode=none`、Enhancer、Lyric Segmentation及びPlannerはRef2VA Compilerを実行せず個別artifactを返せる。特にLyric SegmentationはSRT生成だけにも使える。
3. 単独Compiler: 手書きの完全`MVD_EMD_V1`を通常のSTRINGとして受け、上流artifact、IMAGE、AUDIO又はworkflow graph inspectionなしでRef2VA Plan JSONと必要参照一覧を返す。日本語本文ではCompiler上の`model_name`から利用可能なGGUFを選ぶ。

Compilerはbinding manifest又は実画像tensorを入力に要求しない。ただし完全Ref2VA EMDの`# サブジェクト`には一件以上の`<Subject N>`と`<Picture N>`の関係を必須とし、必要Picture一覧を返す。実tensorとの一致はworkflow接続時の別検証であり、Compilerのparse・serialize処理と結合しない。T2VA、I2VA、FL2VA、L2VAはmodeとして本Compilerへ追加せず、必要になった場合は別Compiler契約を作る。

### 2.5 Context Loop基準contract

初期実装は、2026-09-15時点で利用するContext Loop `0.6.6`、commit `136db5dbbf25405063a96e898ae880e8785b7f29`のPlan parser、Ref2VA prompt schema、参照socket及びtiming規則を基準にする。開発中のContext Loop tipへ追従し続けず、まずこのcommitに対して実装する。実装完了後に同commitとの契約テストを行い、その後の更新はadapter追加又は契約更新として別に検証する。

## 3. 入力のauthority

優先順位は次で固定する。

1. ユーザーが明示した希望
2. 参照画像から直接観察できる事実
3. 選択した演出profile
4. LLMが創作的に補完した詳細

上位と下位が競合するとき、Enhancerが文脈として統合する。Pythonの正規表現、同義語辞書、キーワード一致で意味を削除・反転・矯正しない。Pythonが行ってよい重複除去は、Unicode正規化と前後空白を除いた**全文完全一致**だけとする。

出力には各条件の`source`を`user`、`vision`、`profile`、`generated`のいずれかとして保持する。provenanceは内部JSONに持ち、H3 promptへは漏らさない。

## 4. 演出profileとmodel profile

演出profileは作品の方向、model execution profileは実行容量の制御であり、混在させない。

### 4.1 初期演出profile

候補を増やさず、最初は次の基本セットだけを実装する。

| 軸 | profile | H3へ伝える肯定的な核 |
|---|---|---|
| 画風 | `reference_anime`（既定） | 参照画像の顔・体格・衣装・配色を同じ設計で保ち、整理された線、明瞭な色面、セル影、繊細な光で手描き2Dアニメとして描く |
| 画風 | `reference_cinematic` | 参照画像の人物設計を保ち、自然な皮膚・布・材質、映画照明、レンズによる奥行きで実写映画として描く |
| 画風 | `reference_painterly` | 参照画像の形と配色を保ち、紙目、透明な色層、柔らかな境界を持つ手描き絵画として描く |
| 動作 | `natural_performance`（既定） | 歌詞と音の強弱へ反応する全身動作を、接地、重心、手と対象の接触、髪と衣装の追従が読める連続動作として描く |
| 動作 | `expressive_mv` | 静かな区間は小さな重心と手の動き、強い区間は踏み込み、胴体のひねり、腕の広い軌道へ変化させる |
| 動作 | `limited_animation` | 大きく読めるキーポーズとポーズ間の移行を使い、身体と口形のタイミングを別々に保つ |
| カメラ | `readable_depth`（既定） | 顔、全身動作、接触点を読める距離を保ち、安定した構図、緩やかな接近・後退・横移動を使い分ける |
| カメラ | `cinematic_depth` | 開始視点、被写体の側面を通る経路、終了視点、前景・中景・遠景の視差を明示する |
| カメラ | `rhythmic_mv` | 楽曲強度に合わせて移動量と構図保持を変え、Scene間で角度、高さ、距離、移動方向を展開する |

「禁止リストを増やす」のではなく、実現したい材質、形、動き、軌道を記述する。ただしユーザー自身が否定条件を指定した場合は削除しない。

最初の比較presetは次の3個に限定する。

- `anime_emotional`: `reference_anime` + `expressive_mv` + `cinematic_depth`
- `cinematic_performance`: `reference_cinematic` + `natural_performance` + `readable_depth`
- `painterly_mv`: `reference_painterly` + `natural_performance` + `cinematic_depth`

### 4.2 初期model execution profile

初期実装は次の二つを比較する。model profileは演出を変更せず、contextと実行容量だけを制御する。

- `local_8b_16k`: Enhancer / Plannerの基準。`n_ctx=16384`。
- `local_4b_32k`: Compiler英訳の8GB VRAM向け試験基準。`n_ctx=32768`、`kv_cache_type=q8_0`、`flash_attn=true`、`keep_model_loaded=false`。

- 実効context上限は`min(backend effective_n_ctx, 16384)`。
- lyric noteは1要求あたり最大6 Scene、actionとcameraは最大3 Sceneを、token予算内で貪欲にpackする。
- 収まらなければ1 Sceneまで分割し、それでも収まらなければ必要量と内訳を示して停止する。
- 27Bを選んでもprofile文は同じにし、後続で実測するまで粒度を自動拡大しない。

上の`16384`制限は`local_8b_16k`にだけ適用する。Compilerの翻訳には別の`prompt_translation_ja_en` profileを用い、backend interfaceは`translate_ja_to_en(list[str]) -> list[str]`だけとする。初期比較候補は4Bと8Bだが、モデル名は固定せず、入力unit数と順序を保持できればよい。

### 4.3 GGUFの探索と選択

従来方式を維持し、各GGUF利用nodeはComfyUIの`models/LLM/GGUF`と登録済み`LLM` rootを再帰探索する。拡張子`.gguf`だけを列挙し、`mmproj`を除外する。通常はrootからの相対pathを`model_name` comboへ表示し、同名pathが複数rootにある場合だけroot識別子を付ける。実行時に選択値を再解決し、任意の絶対pathは受け付けない。

CompilerのPromptTranslatorは別node又はmodel socketにせず、Compiler内部の交換可能adapterとする。`model_name`、`n_ctx`、`gpu_layers`、`n_batch`、`flash_attn`、`kv_cache_type`、`op_offload`、`keep_model_loaded`を従来どおり選択可能にする。モデル名からparameter数や適正contextを推測して設定を上書きしない。`already_english`では選択GGUFをresolve又はloadしない。

8GB VRAMでの最初の比較は4B `Q5_K_M`、32K context、Q8 KV cacheとする。Qwen3-4Bの構成からQ8 KV cacheは概算約72 KiB/tokenで、32Kでは約2.25 GiBとなる。これは重み、compute buffer、CUDA context等を含まないため、32K動作は保証ではなく実測対象である。64KはQ8 KV cacheだけで約4.5 GiBとなるため初期既定にしない。

### 4.4 H3 Timing Profile

公開utility nodeは`MVDirectorH3TimingProfile`、表示名は`MV Director - H3 Timing Profile`、カテゴリは`MV Director/Utilities`とする。初期既定profileは次を持つ。

```json
{
  "schema": "MVD_H3_TIMING_PROFILE_V1",
  "contract": "context-loop-0.6.6@136db5dbbf25405063a96e898ae880e8785b7f29",
  "fps": 24,
  "anchor_mode": "head",
  "first_scene_context_length": 0,
  "continuation_context_length": 22,
  "audio_context_length": 22,
  "length_modulus": 17,
  "length_remainder": 5,
  "min_raw_length": 5,
  "max_raw_length": 3592
}
```

nodeはtyped `MV_DIRECTOR_H3_TIMING_PROFILE`、同内容のJSON STRING、statusを返す。Lyric Segmentationがraw `length`を決める時と、CompilerがEMDへ記録済みのprofile IDをPlan既定値へ写す時に同じprofileを使う。fpsと格子は基準contractの固定値であり、自由入力にしない。anchorとcontextを変更できる場合もContext Loop基準contractが許す候補だけをcomboへ出す。

### 4.5 32-bit Seed

公開utility nodeは`MVDirectorSeed32`、表示名は`MV Director - 32-bit Seed`、カテゴリは`MV Director/Utilities`とする。出力を`1..2147483647`の通常INTに限定し、GGUF系とH3系へ同じ値を分岐できるようにする。`seed=-1`、`fixed`、`random`及びrandomボタン直後の一回保持だけを旧実装から再利用する。固定seedは通常cacheを許可し、毎回randomの場合だけ`IS_CHANGED`で再実行させる。64-bitからの剰余変換nodeにはせず、本nodeが最初から両系統で有効な共通seedを生成する。

### 4.6 Combo utilities

`MVDirectorStringCombo`（表示名`MV Director - String Combo`）と`MVDirectorConnectedCombo`（表示名`MV Director - Connected Combo`）を`MV Director/Utilities`へ登録する。String Comboは有限な文字列候補を選び通常STRINGとして出力する。Connected Comboはサブグラフ内部で頻繁に変更するcomboを外側へ引き出し、接続された候補集合から値を選ぶ用途を維持する。旧`CL...` IDとのalias、用途別の派生Combo又は暗黙の文字列修復は追加しない。

### 4.7 Load Text File

公開utility nodeは`MVDirectorLoadTextFile`、表示名は`MV Director - Load Text File`、カテゴリは`MV Director/Utilities`とする。ブラウザのファイル選択又はD&Dでローカルの歌詞ファイルを読み、本文だけを通常STRINGとして返す。選択支援は`text/*`、`.txt`、`.lrc`、`.srt`、`.vtt`、`.md`、`.json`、`.yaml`及び`.prompt`を対象にするが、拡張子を信頼条件にはしない。

ブラウザが原バイト列をBase64としてworkflowへ埋め込み、Pythonは利用者指定pathを開かない。UTF-8及びUTF-8 BOMだけを受け付け、BOMを除去し、CRLF又は単独CRをLFへ正規化する。最大16 MiB、NUL又は不正Base64はエラーとする。本文、表示用basename及びbrowser metadataをcache fingerprintへ含め、内容を再選択した時に再実行する。元ファイルの監視、UTF-8以外の文字コード推測、複数ファイル結合、本文編集及びpreviewは行わない。旧`CLLoadTextFile` aliasは登録しない。

## 5. Image to Subject EMD契約

### 5.1 入力とmode

- `image`: Visionで観察する一枚のIMAGE。
- `subject_hint`: 名前、画面外の重要特徴、保持したい特徴を補う任意のSTRING socket。
- `additional_instruction`: 「眉の形と尾の本数を重点的に確認」のように、観測箇所を指定する任意のSTRING socket。
- `analysis_profile`: `general`（既定）、`subject_only`、`scene_only`を選ぶ外部接続可能な制御socket。
- `hint_mode`: `observe_only`、`assist`、`lock_identity`（既定）を選ぶ外部接続可能な制御socket。
- `hint_conflict`: `warn`（既定）、`strict`を選ぶ外部接続可能な制御socket。
- `picture_reference_mode`: `auto_h3`（既定）、`manual`、`none`を選ぶ外部接続可能な制御socket。
- `concept_type`: EMD内部IDの`person`、`location`、`object`を選ぶ外部接続可能なsocket。
- `concept_index`: EMDの`人物N`、`場所N`又は`物品N`へ使う1～16の外部接続可能な整数socket。
- `subject_index`: Ref2VA prompt内の意味上の`<Subject N>`へ使う1～4の外部接続可能な整数socket。
- `picture_index`: `manual`時だけ物理入力`<Picture N>`へ使う1～9の外部接続可能な整数socket。
- Vision model、projector、seed、生成設定。

旧ノードには上記のほか、画像選択、`image_override`、`cache_mode`、`picture_reference_mode`、`picture_index`、`subject_index`、`analysis_max_edge`とGGUF runtime設定があった。新ノードでは外部IMAGEを`image`へ統一し、概念番号、意味上のSubject番号、物理Picture番号を別socketにする。`cache_mode`、解析解像度、model/runtime設定も外部接続可能にする。

旧`analysis_profile`の`planner_brief`はprimary出力が直接EMD fragmentになったため不要であり、`structured_json`は常時返す`observations_json`へ統合する。旧出力形式を選ぶための二値は新profileへ残さない。

全ての公開入力はworkflow外部から接続可能とする。ローカルwidgetも表示する項目では、接続socketの値を優先する。未接続時だけwidget既定値を使う。

`subject_hint`と`additional_instruction`は日本語の自然文をそのまま受けるデータ欄であり、見出し、名前付きプレフィクス、JSON又はMarkdown directiveを要求しない。例えば`淡い金色の短い丸眉で、狐の尾は一本です。`だけで有効とする。`subject_hint:`等を検出・除去する互換処理は実装せず、socketへ渡された文字列全体を入力本文として扱う。

`subject_hint`は人物設定のauthority、`additional_instruction`は観察の焦点であり、後者を「画像に存在する事実」へ昇格させない。入力原文と正規化後文字列をartifactへ分けて保持し、semantic keyword parserで特徴へ分解しない。

- `observe_only`: `subject_hint`をVision要求又はEMDへ適用せず、入力原文artifactにだけ保持する。
- `assist`: ヒントを画像解釈の仮説として渡すが、可視事実を置換せず、確定した人物設定としては出力しない。
- `lock_identity`: ヒントを`user_hint` provenanceの人物設定としてEMDへ保持する。画像観察由来とは表示しない。
- `hint_conflict=warn`: 明瞭な画像証拠との相違をstatusへ記録して続行する。
- `hint_conflict=strict`: 明瞭な画像証拠との相違が返された場合だけ停止する。曖昧又は不可視をconflictとみなさない。

`picture_reference_mode=auto_h3`ではComfyUIのhidden `PROMPT`と`UNIQUE_ID`を読み、自ノードのIMAGE pass-through出力が接続された、基準Context Loop adapterで認識できるH3 Ref2VA画像入力を探す。`ref_image_0`を`<Picture 1>`、`ref_image_8`を`<Picture 9>`として解決する。nested `ref_images.ref_image_N`も同じ規則で扱う。同じPicture番号への複数分岐は許可し、異なる番号へ同時分岐した場合は勝手に一つを選ばず曖昧エラーにする。認識対象は同一IMAGEの直接linkとComfyUIが実行promptで解決済みのrerouteに限り、画像加工nodeを越えたtensorを同一画像とはみなさない。

`manual`は`picture_index`を使い、グラフを調べない。`none`は画像を観察資料としてだけ使い、`<Picture N>`関連を出さない。`auto_h3`で対応H3入力が見つからない場合も観察は成功させ、bindingを`unbound`として返す。解決したH3 node ID、class type、input名、Picture番号をbinding fingerprintとComfyUIの`IS_CHANGED`へ含め、配線だけを変更した場合に古いEMD断片を再利用しない。

### 5.2 出力

- `emd_fragment`: 通常のSTRINGでも保存・編集できる`MVD_EMD_FRAGMENT_V1`。`# サブジェクト`を持ち、binding成功時は同じ項目内へ`<Subject N>`と`<Picture N>`の関係を書く。
- `reference_bindings`: optional `MV_DIRECTOR_REFERENCE_BINDINGS`。`MVD_REFERENCE_BINDINGS_V1`としてserializeでき、概念ID、`subject_ref`、`picture_ref`、接続先signature、入力image fingerprintを持つ。
- `image`: H3へ分岐できる、入力と同一のIMAGE tensor。modeにかかわらず常にpass-throughする。
- `observations_json`: 可視事実、uncertainty、provenanceを持つdebug/再利用用出力。下流必須にしない。

Image to Subject EMDはScene、Shot、歌詞、音響、カメラ又は物語展開を生成しない。見える形、色、数、衣装、材質、構図だけをサブジェクト定義へし、名前、履歴、画面外を推測しない。`subject_hint`は`user_hint` provenanceを持つauthorityとして保持するが、画像で見えた事実とは偽らない。`additional_instruction`は観察対象を絞るだけで、設定値として本文へ自動追加しない。

### 5.3 bindingなしの単独利用

- Image to Subject EMD自体を接続しない上流編集経路を正式にサポートする。
- `picture_reference_mode=none`又は`auto_h3`の`unbound`は、観察・EMD断片出力として正常である。
- bindingの追加・除去で観察本文やScene演出を再生成する必要はない。
- ただし本仕様のCompilerはRef2VA専用なので、`<Picture N>`関連のない完全EMDはCompiler入力として受理しない。画像なしH3生成は将来の別Compilerが担当する。

## 6. Enhancer契約

### 6.1 入力

- `concept_emd`: Image to Subject EMD出力又は手書きの任意EMDサブジェクト断片。未接続でもよい。
- `observations_json`: provenance確認用の任意入力。接続を要求しない。
- `user_request`: 空又は自由な短文。見出しや定型文を要求しない。
- `style_profile`、`motion_profile`、`camera_profile`
- `model_name`、`seed`、生成設定

概念EMDがなくてもuser requestとprofileからdirectionを作れる。ユーザーが「丸く短い金色の眉」のような重要特徴を明示した場合、その条件をVision由来概念より優先する。

### 6.2 出力

`MVD_DIRECTION_V1`は少なくとも次を持つ。

```json
{
  "schema": "MVD_DIRECTION_V1",
  "concepts": [],
  "retention": [],
  "global_direction": [],
  "motion_direction": [],
  "camera_direction": [],
  "provenance": []
}
```

`global_direction`は短い全体方針とし、Sceneイベント一覧にはしない。背景、時間帯、画風、人物一貫性のような全Scene共通事項を中心にする。

### 6.3 実行規則

- 一回のLLM統合で出力する。schema不正だけ同じ対象を一回再生成できる。
- 意味監査、別LLMによる採点、自動意味修復は行わない。
- user、vision、profileを別々に機械連結した巨大promptのまま下流へ送らず、統合結果とprovenanceを保存する。
- userの原文もartifactへ保持するが、LLMへ同じ文章の厳密な再出力を要求しない。

## 7. Timeline生成とPlanner契約

### 7.1 Lyric Segmentation support node

公開nodeは`MVDirectorLyricSegmentation`、表示名は`MV Director - Lyric Segmentation`、カテゴリは`MV Director/Input`とする。LLM、Vision、Planner又はH3を要求せず、字幕生成だけにも単独利用できる。

主入力:

- `vocal_audio`: padding前のボーカル又は発話AUDIO。
- `lyrics_text`: section見出しを含められる歌詞STRING。
- `whisper_model`: ローカル配置済みWhisper model。
- `h3_timing_profile`: `MV_DIRECTOR_H3_TIMING_PROFILE`。未接続時は4.4の基準profileを使う。SRT時刻の検出には影響せず、Template EMDのScene境界と`` `H3長` ``だけに使う。
- `language`、`max_scene_duration_ms`（既定10000）、`srt_time_offset_ms`、`cache_mode`、`keep_whisper_loaded`。

主出力:

- `template_emd`: `MVD_EMD_TEMPLATE_V1`の編集可能なSTRING。Scene/Shot見出しと歌詞annotationを含むが、演出、action、cameraを生成しない。
- `srt_text`: 解決済み歌詞だけを原文のまま標準SRTへ直列化したSTRING。section見出しは字幕本文へ入れない。SRTだけは規格どおり`HH:MM:SS,mmm --> HH:MM:SS,mmm`を使い、EMDの`MM:SS.mmm`とは混在させない。
- `timeline`: 絶対ms、Scene/Shot、整列結果、`unplaced_lyrics`を持つ`MVD_TIMELINE_V1`。
- `status`: 解決数、未解決数、尺、cache、警告。

`srt_time_offset_ms`は外部字幕調整用で、`srt_text`だけへ適用する。`template_emd`と`timeline`の元音源時刻は変更しない。未解決歌詞へ推測時刻を作らず、SRTから除外して`unplaced_lyrics`とstatusへ残す。

Template EMDはPlannerの標準入力である。Plannerはこの文字列のannotationと確定枠を読み、内容を補完して`MVD_EMD_V1`を作る。Template EMDを受けた場合はWhisperを再実行しない。Template単体は演出本文が未完成なのでCompilerの完成EMD入力とはみなさない。

### 7.2 音声・歌詞時間解析

初期方式を次で固定する。

1. ローカルWhisperを一回実行してword timestampを得て、歌詞中の語句・行が音源上のどこに現れるかを検出する。公式model名による暗黙downloadは行わない。
2. vocal stemを20ms窓のenergy VADで粗く解析する。旧既定値を比較開始点として、threshold `-45 dBFS`、最小有声120ms、最小無音300ms、前後padding 80msを使う。実測前の最適値とは呼ばない。
3. 各粗区間の開始・終了近傍だけを、同じthreshold方針の包絡線とhysteresisでsample-domain再探索する。確定したsample indexを`round(sample_index * 1000 / sample_rate)`で整数msへ一度だけ変換する。同じmsへ潰れる場合も内部順序を壊さず、必要なら次のmsへ押し出した事実をstatusへ残す。
4. 歌詞はsection見出しと本文を分離し、正規化文字列の順序付き整列でWhisper word列へ対応させる。Whisperの位置候補をrefined VAD区間へ束縛し、行の開始・終了境界を整数msで確定する。初期版では未解決箇所だけの追加Whisper retryを行わない。
5. 解決できた歌詞は原文、section、開始・終了絶対msを保持する。未解決歌詞は削除せず`unplaced_lyrics`へ残し、警告する。推測時刻を確定値として作らない。
6. 音源総尺はsample数とsample rateから整数msへ一度だけ変換する。sub-msがある場合は末尾sampleを失わない方向へ丸める。有声境界を整数秒へ量子化せず、refined VADが返した整数msのまま接する有声範囲を結合し、補集合を無音範囲とする。
7. 各連続範囲を`max_scene_duration_ms`以下へなるべく均等に分割し、元音源上の要求Scene境界を作る。歌詞の確定区間と重なるSceneはvoicedへ昇格する。最終Scene以外で2000ms未満になる境界は隣接範囲と調整する。
8. 要求Scene長をH3 timing profileへ通し、先頭Sceneは要求delivered frames以上となる最小の合法raw `17k+5`、`anchor_mode=head`の後続Sceneは要求delivered framesへcontext lengthを加えた値以上となる最小の合法raw `17k+5`を選ぶ。`anchor_mode=head`の後続delivered framesは`raw_length - context_length`、先頭又は`before`は`raw_length`とする。
9. Sceneの機械的な開始・終了はdelivered framesの累積値を正とし、表示用EMD時刻だけを`round(cumulative_frames * 1000 / 24)`で整数msへ一度直列化する。各Sceneへ`raw_length`、`delivered_frames`、`context_length`、要求元範囲、量子化差分及びtiming profile IDを保持する。Compilerへ渡す`` `H3長` ``はここで確定し、下流で再計算しない。

Sceneはplan上の`[start_ms, end_ms)`を半開区間で隙間なく一回だけ覆う。plan終端はH3格子への切り上げにより元音源総尺より長くなり得るため、`source_audio_duration_ms`と`plan_duration_ms`を分けて保持し、Audio Pad Pairは不足分だけを末尾無音補完できる。開始・終了、frame数及びraw `length`はPython所有で、LLMへ再出力させない。歌詞及びSRTの`start_ms` / `end_ms`は元音源上の実測値を保持し、Scene量子化に合わせて移動しない。

ここで「ms単位」はsample-domainで選んだ境界を1ms単位へ直列化することを意味する。1ms値は決定的に再現できるが、歌唱の真の開始・終了という正解そのものを保証する値ではない。threshold、hysteresis、sample rate、入力ノイズ及びWhisper alignmentの影響を受けるため、解析条件をtimelineとstatusへ残す。

`MVD_TIMELINE_V1`の最小時刻shapeは次とする。JSON内部では計算用の整数msを正とし、表示用文字列を正値として二重保持しない。

```json
{
  "schema": "MVD_TIMELINE_V1",
  "timebase": "source_audio",
  "time_unit": "ms",
  "vad_analysis_hop_ms": 20,
  "boundary_resolution_ms": 1,
  "boundary_method": "energy_vad_sample_refined",
  "source_audio_duration_ms": 20000,
  "plan_duration_ms": 20042,
  "timing_profile": "context-loop-0.6.6@136db5dbbf25405063a96e898ae880e8785b7f29",
  "lyrics": [
    {"text": "千年鳥居をくぐるそなたよ", "start_ms": 12300, "end_ms": 15800}
  ],
  "scenes": [
    {
      "start_ms": 0,
      "end_ms": 10125,
      "requested_start_ms": 0,
      "requested_end_ms": 10000,
      "raw_length": 243,
      "delivered_frames": 243,
      "context_length": 0,
      "shots": [
        {"start_ms": 0, "end_ms": 10125}
      ]
    },
    {
      "start_ms": 10125,
      "end_ms": 20042,
      "requested_start_ms": 10000,
      "requested_end_ms": 20000,
      "raw_length": 260,
      "delivered_frames": 238,
      "context_length": 22,
      "shots": [
        {"start_ms": 10125, "end_ms": 12300},
        {"start_ms": 12300, "end_ms": 20042}
      ]
    }
  ]
}
```

`vad_analysis_hop_ms`は粗探索の窓、`boundary_resolution_ms`は音源解析境界の直列化単位である。後者は音響的な正解の保証値ではない。Scene境界はH3 delivered frame累積から別に直列化する。Shotの`end_ms`は次Shotの`start_ms`、最後だけSceneの`end_ms`からPythonが決める。

### 7.3 Shot枠

旧PlannerのShot時刻はLLM判断だったため移植しない。初期Shot枠は整列済み歌詞開始だけからPythonが次の規則で作る。

1. 各Sceneの最初のShotはSceneの`start_ms`と同じ絶対ms。
2. Scene内に開始する歌詞の絶対開始msを昇順候補とする。
3. 直前に採用したShot開始から3000ms以上離れ、Scene終端まで2000ms以上残る候補だけ採用する。
4. 1 Scene最大3 Shotとする。
5. 採用候補がなければ1 Shotのままにする。beatや任意の中点を初期版では追加しない。

これは映像的最適性ではなく、時刻の出典を明確にし、小さすぎるShotとLLMによる時刻破損を避ける初期方式である。閾値はH3評価後に変更可能だが、変更時はalgorithm versionをcache keyへ含める。

### 7.4 LLMタスク分割

Plannerの順序は次で固定する。

1. `lyric-notes`: 対象範囲の原文歌詞とsectionから、局所的な意味、感情変化、視覚モチーフ候補を短く作る。
2. `song-direction`: lyric notesだけから、全曲を通す短い弧、反復してよい要素、変化させる要素を作る。全歌詞を再添付しない。
3. `actions`: direction、対象Scene、該当歌詞、必要な直前状態、Python所有Shot枠から、Shot IDごとの人物動作を生成する。
4. `cameras`: 同じShot枠、確定したaction、camera profileから、Shot IDごとの構図とカメラを生成する。action本文を再出力しない。
5. Pythonが任意のサブジェクトEMD、direction、annotation、action、camera、audio templateを完全EMDへ合成する。`<Subject N>`と`<Picture N>`の関連及び`` `H3長` ``は内容を創作又は再計算せずそのまま保持する。

人物動作へ開始・主動作・終了の必須欄や最低段階数を課さない。区間内同期は一つ以上の自然文でH3へ伝える。カメラ出力に人物動作の置換・削除権限を与えない。

Plannerには外部接続可能な`lip_sync_driver`（`off`、`context_loop`、`audio_reference`、`lyrics`）、`lip_sync_target`（既定`人物1`）、`lip_sync_audio_slot`（1～3、`audio_reference`時だけ使用）を設ける。これらはLLM promptへ渡さず、Python rendererだけが次のように使う。

- `off`: リップシンクdirectiveを出さない。
- `context_loop`: vocal evidenceのあるSceneへ`ソースボーカル同期`を出す。
- `audio_reference`: vocal evidenceのあるSceneへ指定slotの`音声参照駆動`を出す。
- `lyrics`: Plannerが解決済みの`歌詞` annotationと開始時刻を読み、その開始を含むShotへ一行ごとに`リップシンク歌詞`、対象概念、歌詞原文を明記する。歌詞のないShotへは出さない。

`ソース音声固定`などの最終音声方針はlip-sync driverと直交し、driver選択から暗黙に追加しない。

### 7.5 再試行

- 各taskのschema、ID集合、欠落recordだけを検証する。
- batch応答の一Sceneだけが構造不正なら、そのSceneだけ一回再生成する。
- 品質が弱い、表現が好みでない、意味が疑わしいという理由で自動再試行しない。
- 同じ対象を上位taskへ戻す入れ子retryを作らない。
- 一回の局所retryでも有効にならなければ未完了artifactを返し、H3 Planとしては出力しない。

### 7.6 Audio Pad Pair

公開support nodeは`MVDirectorAudioPadPair`、表示名は`MV Director - Audio Pad Pair (PCM Silence)`、カテゴリは`MV Director/Audio`とする。旧`CLAudioPadPair`の有限なPCM処理を再利用するが、単体`CLAudioPad`相当のnode typeは実装又は登録しない。

- `audio_a`へfull mix、`audio_b`へvocal stemを接続する。
- 二入力は同じ時刻原点と再生速度を持つことを前提とし、offset検出、同期推定、resample、mix又はtruncateを行わない。
- 共通基準尺は二入力尺、任意の`MVD_TIMELINE_V1.plan_duration_ms`又は明示H3 frame targetの最大値に`extra_padding_ms`を加えてsample数へ変換する。浮動小数秒を基準値にしない。
- 短い側だけを各sample rateで無音補完し、`pad_position=end`を既定にする。
- `padded_audio_a`と`padded_audio_b`はH3 Audio Tracksへ渡す。Lyric SegmentationのVAD / WhisperとH3 Lip-Sync Optionsにはpadding前の元vocalを渡す。
- 単体Audio Padの公開classは再利用しない。入力検証とPCM paddingに必要な処理だけをPair module内のprivate helperへ抽出する。

## 8. EMD（Easy MarkDown）`MVD_EMD_V1`

EMDは**Easy MarkDown**の略称であり、Extended Markdownの略称ではない。標準Markdownの見出し、list及び引用を使い、人間が編集できる簡潔な中間言語へ予約行だけを追加する。

### 8.1 基本構造

これは新表記であり、旧ノードには未実装である。

```markdown
# サブジェクト
## `人物1`
* `H3サブジェクト` `<Subject 1>`
* `参照画像` `<Picture 1>`
* `名称` 主人公
* 長い黒髪と淡い金色の短く丸い眉を持ち、白と朱色の衣装を着た人物。

# 保持分析
* `人物1`: 顔立ち、髪、衣装、配色、身体付属物の数と形を保持する。

# 共通プロンプト
* 実写映画として描画し、自然な肌、物理的な布、現実的な月光、映画的なレンズの奥行きを保つ。

# シーン 00:00.000 --> 00:10.125
* `H3長` 243
* 夜の神社の石畳の参道。月光が人物と朱塗りの鳥居を照らす。
> `セクション` サビ
> `歌詞開始` 00:02.300
> `歌詞終了` 00:05.800
> `歌詞` 千年鳥居をくぐるそなたよ
## ショット 00:00.000
* `人物1`は石畳を踏みしめ、鳥居の奥へ視線と身体を向ける。
* カメラは低い斜め前方から始まり、石灯籠を前景にして人物の側面へ移動する。
## ショット 00:05.000
* `人物1`は鳥居へ歩み寄り、袖と髪が一歩遅れて追従する。
* カメラは歩行を横から追い、鳥居と社殿の奥行きを広げる。
## 音響
* `ソース音声固定`
* `ソースボーカル同期` `人物1`
```

これはCompilerが受理する最小Ref2VA EMDである。`# サブジェクト`内で意味上の`<Subject N>`と物理入力の`<Picture N>`を関連付け、別の`# H3参照束縛`章は作らない。

文書順は`# サブジェクト`、任意の`# 保持分析`、`# 共通プロンプト`、1個以上のSceneとする。`MVD_EMD_FRAGMENT_V1`は`# サブジェクト`だけを持てるが、Compilerが受理する`MVD_EMD_V1`は一件以上のPicture関連、共通プロンプト及び1個以上のSceneを必須とする。生成EMDでは全Sceneの絶対開始・終了時刻、各Sceneの`` `H3長` ``及び全Shotの絶対開始時刻を必須にする。

`# 共通プロンプト`のlist本文は作品全体で共有するH3 promptであり、Compilerは文書順を保った翻訳結果をContext Loop Planの`prompt_prefix`へ一対一で写す。JSON propertyの記述位置ではなく`prompt_prefix`というkeyが先頭連結を指示する。先頭list itemは目標画風の短い肯定文を推奨し、元参照画像の媒体表現ではなく生成先の媒体を記述する。`subject_definitions:`等のContext Loopセクション見出し、Shot marker又は動的`{A|B}`候補は共通プロンプトへ入れない。

### 8.2 サブジェクトとPicture関連

- EMD内部IDは`` `人物1` ``～`` `人物16` ``、`` `場所1` ``～`` `場所16` ``、`` `物品1` ``～`` `物品16` ``。これは作品内の同一性を表す。
- 各`# サブジェクト`項目は``* `H3サブジェクト` `<Subject N>` ``と``* `参照画像` `<Picture N>` ``を一件ずつ持つ。`<Subject N>`はprompt内の意味上の主体、`<Picture N>`はH3へ接続する物理画像であり、同じslot体系ではない。
- Image to Subject EMDの`auto_h3`はIMAGE出力の接続先`ref_image_0..8`から`<Picture 1..9>`を決める。`subject_index`は接続先から推測せず、独立入力として保持する。
- backtickを含む完全なinline-code tokenだけをEMD内部IDとして認識する。通常本文中の「人物1」はIDではない。
- Compilerは本文中の束縛済み内部IDを対応する`<Subject N>`へ固定変換し、`subject_definitions`内で`<Picture N>`との関係を出す。Picture内容又は実配線を推測しない。
- `<Subject N>`と`<Picture N>`を使用できるのは上記二つの予約行だけとし、自由文へ直接書かれた最終tagは構文エラーにする。旧`` `対象N` ``、`` `画像N` ``、`` `H3対象N` ``、`` `H3画像N` ``のalias又は読み替えは実装しない。
- 番号範囲、予約行の欠落又は重複だけを文法エラーにする。画像の意味、SubjectとPictureの内容的一致は監査しない。
- Compilerは`required_references`として使用Pictureと対応内部IDを返す。`<Subject N>`を`ref_image_N`へ変換しない。実画像tensorとの接続確認は`MVD_REFERENCE_BINDINGS_V1`又はworkflow validatorが行う。

### 8.3 SceneとShot時刻

- Scene見出しは`# シーン START --> END`とし、`START`と`END`はH3 delivered frame累積から直列化したplan絶対時刻を必須とする。任意の`継続`はENDの後へ置く。
- 時刻形式は`MM:SS.mmm`。分は2桁以上、秒は00～59、msは3桁とし、EMD内で「秒」表記、浮動小数秒又は省略時刻を使わない。
- 各Sceneは見出し直後に``* `H3長` RAW_LENGTH``を一件必須とする。Lyric Segmentation又はEMD作者がContext Loop互換値を確定し、Plannerは保持、Compilerは整数をPlan `length`へ無変換で写す。
- Sceneは`[START, END)`で、`END > START`かつ表示長は1～60000ms。先頭Sceneは`00:00.000`から始まり、後続SceneのSTARTは直前SceneのENDと一致し、隙間又は重複を作らない。
- Shot見出しは先頭を含め全て`## ショット TIME`とし、H3 delivered frame累積から得たPlan基準の絶対開始時刻を必須とする。
- 各Sceneの先頭Shot時刻はScene STARTと一致する。後続Shotは前Shotより後、かつScene ENDより前でなければならない。
- `MVD_TIMELINE_V1`、Template EMD、完成EMDは同じ絶対整数msを所有する。PlannerとCompilerはこの値をLLMへ再出力させず、丸め又は補正しない。
- CompilerがScene単位のH3 promptを作る時だけ、`shot_relative_ms = shot_absolute_ms - scene_start_ms`を計算し、`MM:SS.mmm`へ固定整形する。
- `` `H3長` ``の後から最初のShotまでにある通常list itemはScene全体の描写であり、`detailed_description:`のShot marker前へ文書順で出力する。

### 8.4 引用annotation

予約annotationは行頭`> `、inline-code label、ASCII space、値の順で、一物理行ずつ認識する。

| label | scope | 規則 |
|---|---|---|
| `セクション` | 次の`歌詞`一件 | 任意。重複不可 |
| `歌詞開始` | 次の`歌詞`一件 | 元音源の絶対時刻。終了と対で使う |
| `歌詞終了` | 次の`歌詞`一件 | 元音源の絶対時刻。開始より後 |
| `歌詞` | 現在Scene | 原文一行。直前のpending metadataを取り込み、直後にscopeを解除する |

canonical順は`セクション`、`歌詞開始`、`歌詞終了`、`歌詞`とする。時刻形式は`MM:SS.mmm`で、分は2桁以上、秒00～59、msは3桁。開始と終了は両方あるか両方ないかとする。

歌詞開始時刻を含むSceneへ一回だけ配置する。歌詞終了がSceneを越えてもよい。Scene範囲との交差がない場合は構造エラーとする。

値はlabel終端後の一つ目のASCII spaceより後を、Markdown unescape、HTML decode、trimせず保持する。CR/LFだけは文書行区切りとして除く。backslash、backtick、`>`、Markdown記号を値中で特別扱いしない。空の歌詞はエラーとする。複数行歌詞は原文の各物理行を別recordにする。

`> 人間向けコメント`のようにinline-code labelを持たない引用行は人間向けcommentとして保持できる。`> `で始まり未知のinline-code labelを持つ行は、誤記を黙ってcommentにしないため構造エラーにする。pending annotationを残したままShot又は次Sceneへ進む場合もエラーとする。

annotationはPythonが工程間で保持し、必要なPlanner taskだけへ渡す。翻訳LLMへ転記させず、最終H3 promptへ出力しない。

### 8.5 Shot単位の`リップシンク歌詞`

`リップシンク歌詞`はScene末尾の`## 音響`ではなく、対象Shotの本文へ置くlist directiveである。次は全timeline中の`00:10.000`から始まるScene抜粋である。

```markdown
# シーン 00:10.000 --> 00:20.000
> `歌詞開始` 00:12.300
> `歌詞終了` 00:15.800
> `歌詞` 千年鳥居をくぐるそなたよ
## ショット 00:10.000
* `人物1`は鳥居の奥へ視線を向ける。
* `リップシンク歌詞` `人物1` 「千年鳥居をくぐるそなたよ」
## ショット 00:15.000
* `人物1`は石畳を進む。
* `リップシンク歌詞` `人物1` 「月明かりの道を」
## 音響
* `ソース音声固定`
```

Plannerは各解決済み歌詞を、その開始絶対時刻を含む半開区間のShotへ割り当てる。同じShotに複数行が入る場合は一行ずつ文書順に出す。CompilerはShot見出しの絶対開始時刻からScene相対開始時刻を機械算出し、各directive内の対象・歌詞原文だけを固定promptへ展開する。`歌詞` annotationを検索、対応付け又は補完しない。

これはShot区間でH3に歌唱時の可視口形を促す時間付きpromptである。音素、word又はframe単位の口形列は生成せず、元音声との完全同期を保証しない。

### 8.6 `## 音響`

音響は説明文を解析せず、予約済みdirectiveだけを扱う。リップシンク駆動方式はSceneごとに一つだけ選ぶ。現在のContext Loop Lip-Sync Optionsを使う場合は次とする。

```markdown
## 音響
* `ソース音声固定`
* `ソースボーカル同期` `人物1`
```

Lip-Sync Optionsの追加モデルを使わず、H3音声参照で駆動する場合:

```markdown
## 音響
* `ソース音声固定`
* `音声参照駆動` `人物1` `H3音声1`
```

間奏で元の楽曲だけを残す場合:

```markdown
## 音響
* `ソース音声固定`
```

生成条件を無音にする場合:

```markdown
## 音響
* `無音`
```

`## 音響`の省略はエラーでも無音でもなく、Scene固有の音声要素を出力しないことを意味する。下流のChain Policyをそのまま継承する。Compilerは接続音声を調査せず、次の予約directiveだけを機械的に写像する。

- `ソース音声固定`
- `ソースボーカル同期` + 一つの概念ID
- `音声参照駆動` + 一つの概念ID + 一つの`H3音声N`
- `明示台詞のみ`
- `無音`

`ソースボーカル同期`、`音声参照駆動`、同じScene内の一つ以上のShot `リップシンク歌詞`は相互排他とする。Shot `リップシンク歌詞`は同じ方式のlist directiveとして複数行を許す。`音声参照駆動`の`H3音声N`はこのdirective内でだけ直接指定でき、Compilerの`required_references`へ音声slotとして追加する。Compilerは音声tensorを要求せず、接続確認もしない。

未知directive、値の個数が違う行、同一directiveの重複を文法エラーにする。`無音`は同じJSON keyへの相反する値を避けるため、同一Scene内では他の音響directive又はShot `リップシンク歌詞`と併記できない。これは音響内容の意味監査ではなく、直列化を一意にする最小文法である。実際の音声接続、対象人物、区間内容はCompilerが推測又は監査しない。

### 8.7 保護台詞`「...」`

Shot本文中の日本語括弧`「...」`は歌詞annotationと区別し、明示的な直接話法として扱う。Compilerは括弧内の文字列を変更せず、JSON escapeした上で`<d>[Japanese]...</d>`へ包むだけとする。

- 話者推定、source audio照合、翻訳、言換え、発話内容の評価を行わない。
- 直前に概念IDがあれば通常の概念／H3 binding規則で写すが、話者として正しいかは監査しない。
- 追加発声禁止が必要なら、EMD作者又はPlannerが`## 音響`へ`明示台詞のみ`を書く。Compilerはそのときだけ固定の禁止文をprompt要素として出す。
- `歌詞`annotationはPlannerが認識するtimeline metadataである。Compilerは構文上読み飛ばして最終promptへ出力せず、`「...」`又は`リップシンク歌詞`へ自動変換しない。
- `リップシンク歌詞`内の`「...」`はShot directive parserが先に取得し、通常の直接話法として二重処理しない。
- 閉じ括弧のない`「`は文法エラー。台詞内容、個数、話者、音声区間の整合性はエラー条件にしない。

### 8.8 非対応形式

本プロジェクトは新規仕様だけを実装する。旧`// 歌詞:`、`// 検出状態:`、`` `対象N` ``、`` `画像N` ``、`` `H3対象N` ``等を読み替えるparser、importer、alias又は自動変換は設けない。`<Subject N>`と`<Picture N>`は`# サブジェクト`の予約行でだけ受理し、自由文中の旧形式としては受理しない。

## 9. Compiler契約

### 9.1 処理順

CompilerはRef2VA専用のEMD parser、限定翻訳orchestrator、H3 prompt renderer、JSON serializerとする。通常入力はSTRING `emd_text`、H3 timing profile、`translation_mode`、`model_name`とruntime設定である。`translation_mode=ja_to_en`では選択GGUFを内部PromptTranslator adapterで使う。初期比較候補は4Bと8Bだが特定modelへ固定しない。Image to Subject EMD、Enhancer、Planner、IMAGE、AUDIO又はworkflow graphは要求しない。

1. EMDの`# サブジェクト`、Scene、Shot、`` `H3長` ``及び予約directiveを構文解析する。
2. Subject/Picture関連、概念ID、`「...」`、annotation、音響directive、Shot `リップシンク歌詞`を翻訳対象から分離する。
3. `# サブジェクト`の説明、`# 共通プロンプト`、`# 保持分析`及びShot本文だけを文書順のtranslation unitとして英訳する。
4. EMD内部IDを対応する`<Subject N>`へ固定変換し、`<Picture N>`と`<Audio N>`の必要slot一覧を作る。
5. 各Shotの`リップシンク歌詞`を、そのShot開始位置、対象token、原文`<d>[Japanese]...</d>`を持つ固定prompt要素へ写す。
6. 通常の`「...」`の内容を変えず`<d>[Japanese]...</d>`へ包む。
7. 明示された音響directiveだけを固定対応表でScene JSON要素と固定prompt要素へ写す。音声参照tagと歌詞原文は翻訳unitへ入れない。
8. 各Sceneの`` `H3長` ``を整数のままPlan `length`へ写す。Scene時刻からlengthを再計算、丸め又は補正しない。
9. `# 共通プロンプト`の翻訳済みlistを文書順のままPlan `prompt_prefix`へ一回だけ出力する。
10. 各Scene固有promptを`subject_definitions`、`summary`、`retention_analysis`、`detailed_description`、`overall_soundscape`、`non_diegetic_music`の正規順で構成する。
11. 標準JSON serializerでescapeし、Ref2VA Plan JSONを返す。

### 9.2 翻訳境界と`as is`の定義

`as is`は「日本語をそのまま残す」ではなく、EMDの構造、情報量、文書順、Scene/Shot対応を変えないという意味で使う。H3自体が日本語を受理できる場合でも、本Compilerのtarget contractでは純粋な生成promptを英語で出力する。PromptTranslatorは日本語の描写文を英語へ翻訳するが、要約、補強、創作、並べ替え、重複除去、禁止文追加又は演出修正を行わない。

翻訳へ渡す前に保護spanを一時tokenへ置換し、翻訳後に完全一致で復元する。保護対象はH3 binding、概念ID、`「...」`、予約annotation、音響directive、Shot `リップシンク歌詞`である。日本語台詞と明示されたリップシンク歌詞は英訳せず、`<d>[Japanese]...</d>`として残す。概念IDは自然名を生成せず、束縛又は固定英語tokenへ変換する。

`translation_mode`は`ja_to_en`を既定とし、入力本文が既に英語の場合だけ利用者が`already_english`を明示できる。自動言語判定は行わない。annotationはPlanへ出さず原文artifactに保持する。Compiler自身には翻訳品質を理由とするretry経路を置かない。

### 9.3 Context Loop出力

基準Context Loopの標準Plan shapeを使う。次は`00:00.000 --> 00:10.125`、`` `H3長` 243``の先頭Sceneについて、日本語本文を英訳し、`ソース音声固定`だけを機械変換した例である。

```json
{
  "prompt_prefix": [
    "Render every scene as photorealistic live-action cinema with natural skin, physical fabrics, realistic moonlight, and cinematic lens depth."
  ],
  "defaults": {"steps": 20},
  "shots": [
    {
      "id": "scene_0001",
      "length": 243,
      "prompt": [
        "subject_definitions:",
        "<Picture 1> is the connected visual reference for the protagonist.",
        "<Subject 1> is the protagonist defined by <Picture 1>, with long black hair, short rounded pale-gold eyebrows, and white-and-vermilion clothing.",
        "",
        "summary:",
        "[reference generation] The target video shows <Subject 1> walking through a moonlit shrine.",
        "",
        "retention_analysis:",
        "<Picture 1>: fully_preserved - use the connected image as the visual identity reference.",
        "<Subject 1> (appears in [Shot 1] and [Shot 2]): fully_preserved - preserve the face, hair, clothing, colors, and number and shape of body appendages from <Picture 1>.",
        "",
        "detailed_description:",
        "A moonlit shrine approach with stone pavement and vermilion torii gates.",
        "[Shot 1] <Subject 1> steps firmly on the stone pavement.",
        "[Shot 2] At 00:05.000, <Subject 1> walks toward the torii gate.",
        "",
        "overall_soundscape:",
        "The connected source vocal and environmental sound follow the scene.",
        "",
        "non_diegetic_music:",
        "The connected source music is retained."
      ],
      "context_length": 0,
      "audio_context_length": 0,
      "source_reference": "off",
      "generated_continuity": "off",
      "source_audio_target": "locked"
    }
  ]
}
```

Context Loop Plan JSONにはScene長として`length`だけを出し、`duration_seconds`又は`duration_ms`は出力しない。値はLyric Segmentation又はEMD作者が確定した`` `H3長` ``をそのまま使う。Compiler artifactにはコピー元の行、値及びtiming profile IDを残すが、量子化計算を再実行しない。

この例の`00:05.000`は、EMDの絶対Shot時刻からScene STARTを引いた値である。先頭Shotは時刻句を付けず`[Shot 1]`、2番目以降だけ`[Shot N] At MM:SS.mmm,`とする。これはContext Loop 0.6.6のRef2VA prompt構文であり、Planのms scheduling fieldではない。

Plan `prompt_prefix`には`# 共通プロンプト`だけを一回出し、各Sceneの`prompt`には完全なRef2VA六セクションを出す。Context Loop 0.6.6は実行時に`prompt_prefix`、空行二つ、Scene promptの順で機械連結する。`subject_definitions`では使用する各`<Picture N>`と`<Subject N>`をそれぞれ行頭から一回ずつ定義し、`retention_analysis`にも両方のmarkerを出す。Subject定義と保持分析は各Sceneへ決定的に再掲するが、共通プロンプト本文をScene promptへ暗黙複製しない。annotationとprovenanceは含めない。

`prompt_prefix`は文字列又は文字列配列をContext Loopが受理するが、本Compilerは編集差分を読みやすくするため文字列配列だけを出力する。Context Loopの動的`{A|B}`解決はScene promptへだけ適用され、prefixには適用されないため、本Compilerもprefixへ動的候補を生成しない。prefix変更は全Sceneの完全prompt hashを変え、異なるprefixで生成したcheckpoint revision同士は一つの出力へ混在できない。

Context Loopのstrict Ref2VA analyzerは、prefix内の通常Style文を六セクション外のerrorにはしない。一方、`detailed_description:`内で`[Shot 1]`より前に求める1～2個のStyle文をprefixだけでは充足したと判定しない。H3実出力にprefix単独で十分か、Scene側にも短いStyle文を明示するかは実装後のA/B試験項目とし、Compilerが意味推測で自動複製しない。

`# サブジェクト`のPicture関連と、任意の`音声参照駆動`から次の独立出力を返す。

```json
{
  "schema": "MVD_REQUIRED_REFERENCES_V1",
  "references": [
    {"concept_id": "人物1", "subject_ref": "<Subject 1>", "h3_ref": "<Picture 1>", "required_input": "ref_image_0", "purpose": "visual_identity"},
    {"concept_id": "人物1", "h3_ref": "<Audio 1>", "required_input": "ref_audio_0", "purpose": "lip_sync_audio_reference"}
  ]
}
```

この一覧は接続要求であり、画像又は音声の内容をCompilerが認識したという主張ではない。同じ概念が視覚参照と音声参照を持つ場合は`purpose`で区別する。

### 9.4 音響・リップシンクdirectiveの固定写像

Compilerは音響又は歌詞の意味を推測しない。EMDに書かれた予約directiveだけを次へ写す。

| EMD | Scene JSON / promptへの出力 |
|---|---|
| `## 音響`なし | Scene固有の音声keyと音響prompt要素を出さない。Chain Policyを継承 |
| ``* `ソース音声固定` `` | `source_reference: "off"`、`generated_continuity: "off"`、`source_audio_target: "locked"` |
| ``* `ソースボーカル同期` `人物1` `` | 対象tokenを通常規則で写し、現行`H3_LIP_SYNC_OPTIONS`経路用の固定lip-sync prompt要素を一つ追加。外部Lip-Sync Options接続はCompilerの責務外 |
| ``* `音声参照駆動` `人物1` `H3音声1` `` | 対象tokenと`<Audio 1>`を固定写像し、`{TARGET} performs visible lip movements synchronized to {AUDIO_TAG}.`を一つ追加。音声slotを`required_references`へ追加 |
| Shot内の``* `リップシンク歌詞` `人物1` 「千年鳥居をくぐるそなたよ」`` | directive内の対象と歌詞原文を当該Shot本文へ固定追加する。先頭は`[Shot 1]`、後続は`[Shot {N}] At {START},`を使い、Sceneのannotationは参照しない |
| ``* `明示台詞のみ` `` | 明示された`<d>...</d>`以外の発声を追加しない固定prompt要素を一つ追加 |
| ``* `無音` `` | `source_reference: "off"`、`generated_continuity: "off"`、`source_audio_target: "off"`と`Complete silence. No speech, music, ambience, or sound effects.`を追加 |

`無音`は非MV利用へ残す「無音条件のJSON要素を出す」という明示フラグである。初期MVスコープではPCM gateを実装しない。CompilerはPCMを変更せず、Sceneが本当に無音になるかを検査しない。またContext Loopの`final_audio`はPlan-wide Chain Policyなので、このScene JSONだけでglobal source soundtrackを消すとは主張しない。

`音声参照駆動`と`リップシンク歌詞`は`MiniMaxH3LipSyncOptions`及び`H3_LIP_SYNC_OPTIONS`を要求しない。したがって同経路で発生する追加モデル読み込み・初期化を回避できるが、H3本体の生成負荷を軽減する保証や、現行専用経路と同じ口形精度を保証するものではない。

### 9.5 最小限の文法エラー

Compilerが停止するのは次だけとする。

- 必須`# サブジェクト`、Subject/Picture関連、Scene又は`` `H3長` ``がなく、Ref2VA EMDとしてparseできない。
- Scene絶対範囲又はShot絶対時刻の構文・順序が壊れている。
- 予約annotation、binding、音響directive又はShot `リップシンク歌詞`の書式、値の個数、番号範囲が不正。
- 同一音響directiveが同じSceneで重複する。
- 複数のリップシンク駆動directiveが同じSceneにある。
- `リップシンク歌詞`の概念ID、開始`「`、終了`」`又は歌詞本文が欠けている。
- `無音`が同じSceneの他の音響directive又はShot `リップシンク歌詞`と併記されている。
- `「`が閉じていない。
- H3 timing profileの必須shape、contract ID又は`` `H3長` ``の整数・格子が不正。
- `ja_to_en`でGGUFが未選択、実行時に解決不能、load／推論失敗、空応答又はtranslation unit数不一致となる。

エラー時は行番号、読めなかった構文、期待した最小形式を返す。自動修復、fallback、retryは行わない。

### 9.6 Compilerが扱わないこと

- 翻訳結果の意味監査、出力言語classifier、未翻訳語の検出
- 意味、表現、動作、カメラ、音響内容の妥当性
- 概念の同一性、参照画像の内容又は実配線
- 歌詞、台詞、話者、source audio区間の一致
- full mix/vocalの尺、PCM、mux
- H3が指示どおり生成するか、映像が採用に値するか
- semantic guard、一般辞書置換、repair prompt、翻訳品質を理由とするLLM retry

## 10. Context予算

全LLM taskで呼出し前に次を満たす。

```text
serialized_input_tokens + reserved_output_tokens + safety_margin <= effective_context
```

`serialized_input_tokens`はsystem、profile、payload、chat template、assistant prefillを含む実際の最終要求を同じtokenizerで数える。完全なchat serializationを数えられないbackendは`estimated=true`とし、確認済みと表示しない。

初期の出力予約上限は次とする。

| task | reserved output tokens |
|---|---:|
| Enhancer | 1200 |
| lyric-notes | 900 |
| song-direction | 900 |
| actions | 1400 |
| cameras | 1000 |

安全余裕は`max(1024, ceil(effective_context * 0.08))`。値は保守的な開始点であり、実測後にversioned profileとして変更する。

予算超過時はbatchを縮小する。同じ入力・同じ予算で再試行しない。単一対象でも超過する場合、対象ID、system/profile/payload/token予約/余裕の内訳と必要量を返して停止する。

## 11. Cacheと固定artifact

成功cache keyには少なくとも次を含める。

- task名とprompt/schema/algorithm version
- 原文又は画像pixel hash
- 対象IDと依存する前状態
- user request、profile ID
- model path fingerprint、chat format、量子化を識別できる情報
- seed、temperature、top-p、repeat penalty、出力予約
- 分割範囲と実効context

失敗、途中切れ、未完了batchを成功cacheへ入れない。上流keyが変わった下流だけを無効化する。

Compiler成功時は`plan_json`、`required_references`、入力EMD hash、H3 timing profile ID、translator model fingerprint、chat format、量子化、system prompt version、seed及びsampling設定をimmutable artifactとして保存する。同じEMDでも翻訳条件が異なる結果を同じ成功cacheとして扱わない。

## 12. エラー分類

| 種別 | 動作 |
|---|---|
| Compiler文法不正 | 行番号、該当構文、期待する最小形式を示して停止。修復しない |
| token予算超過 | 有限分割。最小単位なら内訳付き停止 |
| 上流LLM出力schema不正 | 該当する上流nodeの規則で扱う。Compilerへretryさせない |
| 意味・表現への懸念 | 通常経路を止めない。人間の比較対象として残す |
| model load、OOM、backend障害 | 品質warningへ変換せず停止 |
| ユーザー中断 | 即時伝播し、成功cacheへ保存しない |
| audio/Plan区間への懸念 | Compilerは検査しない。必要ならPlanner又はworkflow validatorで扱う |

## 13. 最小受入条件

実モデルの前にFake backendで次を満たす。

- `MVDirectorLyricSegmentation`がLLM、Image to Subject EMD、Planner、H3実行なしでTemplate EMD、SRT、typed timelineを返せる。
- SRTは解決済み歌詞の原文と順序を保持し、section見出しと未解決歌詞を字幕本文へ入れない。
- Whisperが歌詞位置を検出し、粗い20ms VADの端をsample-domainで再探索して、有声境界を整数msで保持する。fixtureでは同じPCMから同じsample indexとmsを再現できる。
- PlannerがTemplate EMDを受けた場合、Whisperと音声解析を再実行しない。
- 空のuser requestでもdirectionが作れる。
- userの短い夜間・顔特徴指定がprovenance付きで最優先になる。
- plan Sceneが0から量子化済みplan終端まで隙間・重複なく並び、元音源尺との差を保持する。
- Template EMDと完成EMDのSceneが`# シーン START --> END`、全Shotが`## ショット TIME`のplan絶対`MM:SS.mmm`で、typed timelineの整数msと完全一致する。
- Shot開始は規則どおりで、LLMが変更できない。CompilerはH3用のScene相対時刻だけを機械算出し、EMDへ書き戻さない。
- actionとcameraが同じShot IDへ合成され、互いの本文を再出力しない。
- annotationが原文artifactに保持され、H3 promptへ漏れない。
- `<Subject N>`と`<Picture N>`は`# サブジェクト`の予約行だけに現れ、自由文へ混在しない。
- `# サブジェクト`に`<Subject N>`と`<Picture N>`を持つ完全Ref2VA EMDを、画像tensorなしでもCompiler単独で処理し、Picture接続要求を返せる。
- Picture関連のない完全EMDはRef2VA Compilerが明示的に対象外として停止し、T2VA等へ暗黙fallbackしない。
- Lyric SegmentationがContext Loop基準contractのraw `length`、delivered frames、Scene境界及び量子化差分を確定し、Template EMDへ`` `H3長` ``を出せる。
- CompilerはEMDの`` `H3長` ``をPlan `length`へ無変換で写し、`duration_seconds`又は未対応の`duration_ms`を併記しない。
- Compilerが出した各Scene promptを基準Context LoopのRef2VA schema analyzerへ渡すと、正規六セクション、Shot順及び時刻構文にerrorがない。
- `# 共通プロンプト`の翻訳済み行がPlan `prompt_prefix`と順序・行数とも一致し、Context Loopが作る各Scene完全promptの先頭に一回だけ現れる。
- 日本語EMDの描写文が英語へ一対一で翻訳され、情報追加・要約・並べ替えなしでPlanへ入る。
- 音響省略時はScene固有keyを出さず、`無音`がある場合だけ対応するoff値とsilence prompt要素を出す。
- `「...」`の内容を変更せず`<d>[Japanese]...</d>`へ包み、`明示台詞のみ`がある場合だけ追加発声禁止要素を出す。
- `音声参照駆動`を翻訳LLMなしで対象token、`<Audio N>`及び固定英文へ変換し、必要音声slotを返せる。
- Plannerが歌詞開始時刻を含むShotへ対象付き`リップシンク歌詞`を生成し、Compilerはannotationを参照せず、Shot開始位置とdirective内の原文を順序どおりの`<d>[Japanese]...</d>`へ変換できる。
- 同一Sceneのリップシンク駆動方式は一つに限定され、後二方式では`H3_LIP_SYNC_OPTIONS`を要求しない。
- `model_name` comboから任意の利用可能なGGUFを選択でき、`ja_to_en`ではそのGGUFを内部PromptTranslator adapterで使う。`already_english`ではGGUFをloadしない。
- CompilerはIMAGE、AUDIO、上流node又はworkflow graphなしで単独実行できる。
- `MVDirectorAudioPadPair`だけが公開登録され、単体Audio Pad nodeは存在しない。Pairはfull mixとvocalを共通尺へ末尾補完し、混合又は再同期しない。
- プレフィクスなしの日本語`subject_hint`と`additional_instruction`を外部STRINGから入力でき、`lock_identity`時だけ前者がuser authorityとしてEMDへ残る。
- Image to Subject EMDのprofile、hint policy、Picture mode、concept/subject/picture index、cache、解析解像度及びruntime設定を外部socketから上書きできる。
- `auto_h3`が同一IMAGEの`ref_image_N`接続を`<Picture N+1>`へ解決し、異なる番号への分岐を曖昧エラーにする。
- H3 Timing Profile、32-bit Seed、String Combo、Connected Combo、Load Text Fileを`MV Director/Utilities`から利用でき、旧`CL...` aliasは登録されない。
- Load Text FileからUTF-8歌詞をSTRINGとしてLyric Segmentationへ接続でき、workflow再読込時は埋め込み済み本文だけで再現できる。
- 上流LLMは16Kちょうど、1 token超過、単一対象超過を区別できる。
- 成功artifactを固定したままH3 seedだけ変更できる。
