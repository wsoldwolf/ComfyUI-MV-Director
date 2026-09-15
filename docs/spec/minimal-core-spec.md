# 最小コア仕様

版: `draft-0.33`<br>
作成日: 2026-09-16<br>
状態: 初期実装の基準。現行ノードで利用可能な構文の説明ではない。

## 1. 目的

任意の一枚の参照画像、歌詞、ボーカルステム、フルミックスと、空又は短いユーザー希望から、Context Loop / H3 Ref2VAへ渡せる計画を現実的な回数のローカル推論で作る。初期の自動MV経路では一個のImage to Subject EMDだけをEnhancerとPlannerへ分岐し、複数のサブジェクト断片を自動統合しない。Image to Subject EMD、Enhancer、Lyric Segmentation及びPlannerは個別利用できるが、本仕様のCompilerはRef2VAだけを出力する。Picture参照あり又はH3内蔵概念だけの複数Subjectを記述した完全なRef2VA EMDがあれば、Compiler単独でもPlanを作れることを必須境界とする。

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
| `MV Director - Image to Subject EMD` | IMAGE、`subject_hint`、`additional_instruction`、観察・hint・binding制御、Vision model | `MVD_EMD_FRAGMENT_V1`、任意の`MVD_REFERENCE_BINDINGS_V1`、IMAGE pass-through、読み取り専用Picture表示 | 可視事実と明示ヒントを区別した編集可能なサブジェクトEMDへし、Ref2VA利用時は同じ画像を`<Picture N>`へ束縛する |
| `MV Director - Direction Enhancer` | 任意の概念EMD、空又は短い希望、演出profile、言語生成seed | `MVD_DIRECTION_V1`、人間向けpreview | 利用者記述がなくてもprofileから動作し、存在する概念・希望を短い全体方針へ統合する。Visionは必須にしない |
| `MV Director - Timeline Planner` | 任意の概念EMD、Template EMD、任意のdirection artifact、lip-sync mode、GGUFとllama.cpp調整値 | `MVD_EMD_V1`、EMD文字列、status | 確定済み時間枠へ概念、歌詞解釈、人物動作、カメラ及び機械的なlip-sync directiveを展開する |
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
- Load Text File: ローカルのplain lyrics `.txt`をブラウザで選択/D&Dし、workflowへ埋め込まれたUTF-8本文をSTRINGとして返す公開utility node。
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

Compilerはbinding manifest又は実画像tensorを入力に要求しない。完全Ref2VA EMDの`# サブジェクト`には一件以上の内部IDと`<Subject N>`を必須とするが、`<Picture N>`関連はSubjectごとに任意とする。PictureがなければそのSubjectを文章だけで定義するH3内蔵概念として扱い、Ref2VAのままコンパイルする。使用されたPictureだけを必要参照一覧へ返し、実tensorとの一致はworkflow接続時の別検証とする。T2VA、I2VA、FL2VA、L2VAへ暗黙fallbackせず、必要になった場合は別Compiler契約を作る。

### 2.5 Context Loop基準contract

初期実装は、2026-09-15時点で利用するContext Loop `0.6.6`、commit `136db5dbbf25405063a96e898ae880e8785b7f29`のPlan parser、Ref2VA prompt schema、参照socket及びtiming規則を基準にする。開発中のContext Loop tipへ追従し続けず、まずこのcommitに対して実装する。実装完了後に同commitとの契約テストを行い、その後の更新はadapter追加又は契約更新として別に検証する。

### 2.6 LLM行指向出力protocol

LLMにJSON、Markdown又は最終EMDの構造を生成させない。EnhancerとPlannerのLLM応答は、request metadataでversionを固定した`MVD_LLM_RECORDS_V1`の行recordだけとし、Pythonがtyped artifact、EMD及び最終JSONを組み立てる。PythonからLLMへ渡す入力はPython自身が直列化するためJSONを利用してよいが、LLMからPythonへの返却形式にはJSONを使わない。

一行の文法は次だけとする。

```text
RECORD_TYPE<TAB>SLOT<TAB>TEXT
```

- `RECORD_TYPE`はtaskごとの固定ASCII大文字、`SLOT`は呼出し内だけで有効な1始まりの短い10進整数、`TEXT`は二つ目のTABより後ろ全部である。
- Pythonは呼出し前に`SLOT -> Scene/Shot/区分`のside tableを作る。LLMに実Scene ID、Shot ID、時刻、配列、object key、引用符又はescapeを生成させない。
- header、終了marker、括弧の対応、Markdown fence及び説明文を要求しない。一物理行を一recordとし、本文改行が必要な構造は作らない。
- parserはCRLFをLFへ正規化し、空行と単独のMarkdown fenceを無視し、各行を`split("\t", 2)`で読む。残りのTABは本文内空白へ正規化する。
- 未知type、field不足、数値でないslot、対象外slot及び空本文の行は採用せずstatusへ残す。同じtypeとslotが重複した場合は最初の有効recordだけを採用する。前置き説明や壊れた一行のために、他の有効recordを捨てない。
- 必須slotがそろえば、未知行、重複又は余分な行だけを理由にretryしない。必須slotが欠けた場合だけ、欠落slotを一回局所retryできる。意味、文章品質、英語らしさ又は演出の好みはparserで検査しない。
- 明示debug時はraw応答、採用record、拒否行と理由、slot side table及び欠落slotを保存する。raw応答を成功artifact又はEMDへ混入させない。

初期typeは次へ限定する。

| task | `RECORD_TYPE` | slotの意味 | 必須数 |
|---|---|---|---:|
| Enhancer | `STYLE` / `MOTION` / `CAMERA` | 各区分内の項目番号 | 各1 |
| Enhancer | `OTHER` | その他区分の項目番号 | 0又は1 |
| `lyric-notes` | `NOTE` | request side table上のScene番号 | 対象Sceneごとに1 |
| `song-direction` | `DIRECTION` | 常に1 | 1 |
| `actions` | `ACTION` | request side table上のShot番号 | 対象Shotごとに1 |
| `cameras` | `CAMERA` | request side table上のShot番号 | 対象Shotごとに1 |

例えば二つのShotのaction応答は次だけでよい。

```text
ACTION<TAB>1<TAB>人物は足を踏み出し、袖を後方へ流しながら鳥居へ手を伸ばす。
ACTION<TAB>2<TAB>人物は立ち止まり、上げた手を胸元へ静かに戻す。
```

表示上の`<TAB>`は実際のU+0009 TAB一文字を表す。上例のslot `1`と`2`をどのShotへ入れるかはPythonだけが知る。旧実装の行指向という考え方は再利用するが、`SONG_BIBLE` / `END_*`、入れ子block、多段enum及び意味修復は移植しない。

## 3. 入力のauthority

優先順位は次で固定する。

1. ユーザーが明示した希望
2. 参照画像から直接観察できる事実
3. 選択した演出profile
4. LLMが創作的に補完した詳細

上位と下位が競合するとき、Enhancerが文脈として統合する。Pythonの正規表現、同義語辞書、キーワード一致で意味を削除・反転・矯正しない。Pythonが行ってよい重複除去は、Unicode正規化と前後空白を除いた**全文完全一致**だけとする。

出力には各入力及び採用したLLM行の`source`を`user`、`vision`、`profile`、`generated`のいずれかとして保持する。provenanceは内部JSONに持ち、H3 promptへは漏らさない。これは入力と機械処理の履歴であり、LLMの意味判断、思考過程又は因果関係を捏造しない。

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
- `local_4b_32k`: Enhancer / Planner / Compilerの8GB VRAM向け試験基準。`n_ctx=32768`、`kv_cache_type=q8_0`、`flash_attn=true`、`keep_model_loaded=false`。

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

#### 4.4.1 Ref2VA参照adapter

初期実装は基準Context Loopの通常Ref2VA nodeへ画像と音声を直接接続する固定番号方式だけを対象とする。画像socket `ref_images.ref_image_0..8`は`<Picture 1..9>`、音声socket `ref_audios.ref_audio_0..2`は`<Audio 1..3>`へ対応する。画面上で末端名だけが提示される場合はそれぞれ`ref_image_N`、`ref_audio_N`と表示してよい。

Sceneごとに`@tag`を有効化してnative番号を詰め直すTagged Reference経路は初期adapterへ含めない。Compiler及びImage to Subject EMDは`@tag`を生成又は解決せず、固定されたPicture/Audio番号だけを扱う。Tagged Reference対応が必要になった場合は、EMDの意味IDを変更せず別のversioned adapterとして追加する。

### 4.5 32-bit Seed

公開utility nodeは`MVDirectorSeed32`、表示名は`MV Director - 32-bit Seed`、カテゴリは`MV Director/Utilities`とする。出力を`1..2147483647`の通常INTに限定し、GGUF系とH3系へ同じ値を分岐できるようにする。`seed=-1`、`fixed`、`random`及びrandomボタン直後の一回保持だけを旧実装から再利用する。固定seedは通常cacheを許可し、毎回randomの場合だけ`IS_CHANGED`で再実行させる。64-bitからの剰余変換nodeにはせず、本nodeが最初から両系統で有効な共通seedを生成する。

### 4.6 Combo utilities

`MVDirectorStringCombo`（表示名`MV Director - String Combo`）と`MVDirectorConnectedCombo`（表示名`MV Director - Connected Combo`）を`MV Director/Utilities`へ登録する。String Comboは有限な文字列候補を選び通常STRINGとして出力する。Connected Comboはサブグラフ内部で頻繁に変更するcomboを外側へ引き出し、接続された候補集合から値を選ぶ用途を維持する。旧`CL...` IDとのalias、用途別の派生Combo又は暗黙の文字列修復は追加しない。

### 4.7 Load Text File

公開utility nodeは`MVDirectorLoadTextFile`、表示名は`MV Director - Load Text File`、カテゴリは`MV Director/Utilities`とする。ブラウザのファイル選択又はD&Dでローカルのplain lyrics `.txt`を読み、本文だけを通常STRINGとして返す。初期版の選択対象は`.txt`だけとし、LRC、SRT、VTT、Markdown又はJSONを入力形式として扱わない。

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

### 5.2 Vision観測protocol

旧`cl-vision-observation-line-v2`の実績あるrecord構成を、新名前空間`MVD_VISION_OBSERVATION_LINES_V1`として引き継ぐ。Vision modelへJSON、Markdown、EMD、`<Picture N>`又は`<Subject N>`を生成させない。正規応答は次の順序固定TAB区切り行とする。

```text
MVD_VISION_OBSERVATION_LINES_V1
OVERVIEW\t日本語の概要
PRIMARY_SUBJECT\t日本語の単数名詞句又は空
HINT_ASSESSMENT\tnot_used|consistent|ambiguous|conflict\t日本語の根拠又は空
SUBJECT_FEATURE\tface|hair|eyes|eyebrows|ears|body|clothing|accessory|tail|distinctive_feature\t日本語の可視特徴\tclear|partial|uncertain
SUBJECT_POSE\t日本語の姿勢又は空
SCENE_SETTING\t日本語の場所・環境又は空
SCENE_ELEMENT\t日本語の背景要素
LIGHTING\t日本語の照明又は空
TIME_WEATHER\t日本語の時間帯・天候又は空
COMPOSITION\tshot_size\t日本語値又は空
COMPOSITION\tviewpoint\t日本語値又は空
COMPOSITION\tsubject_placement\t日本語値又は空
COMPOSITION\tdepth\t日本語値又は空
STYLE\tmedium\t日本語値又は空
STYLE\trendering\t日本語値又は空
STYLE\tpalette\t日本語値又は空
VISIBLE_TEXT\t画像内で実際に読めた文字
UNCERTAINTY\t確認できない事項
END_MVD_VISION_OBSERVATION
```

`SUBJECT_FEATURE`、`SCENE_ELEMENT`、`VISIBLE_TEXT`、`UNCERTAINTY`は0件以上、それ以外は各固定数を要求する。`SUBJECT_FEATURE`の同一category反復を許す。人体分類に当てはまらない物品の形、色、数、材質、模様又は状態は`distinctive_feature`を使い、modelに新categoryを作らせない。`visibility`は校正済み確率ではなく、`clear`、`partial`、`uncertain`の三値表示だけとする。

Python parserは旧実装から、CRLF正規化、空値`SUBJECT_POSE`、`visible`から`clear`、visibility欠落時の保守的`partial`、自然文中へ混入した追加TAB断片の順序保持結合、全必須recordが揃う場合だけの終端marker欠落warningを再利用する。未知record、未知category、未知enum、固定順違反、code fence、参照tag、NUL又は必須record欠落は推測修復せず停止する。画像なしLLM修復、英日翻訳repair、画像全体の再観測retry及び旧`subject_hint:`互換正規化は移植しない。

検証済みrecordからPythonが`MVD_OBSERVATIONS_V1`を構築し、`observations_json`を生成する。旧構造の`overview`、`primary_subject`、`hint_assessment`、`scene`、`composition`、`style`、`visible_text`、`uncertainties`を維持するが、schema IDとprotocol IDは新名称だけを使う。生model応答をJSONとしてparseしない。

新EMD rendererは旧Markdown rendererを使用しない。`person`又は`object`ではidentityと`clear`／`partial`の可視特徴、`location`ではscene settingとscene elementsを主に`# サブジェクト`へ写す。`uncertain`特徴はEMDの確定条件へ入れずstatusと`observations_json`へ残す。pose、composition、source medium/style、visible textは参照画像固有の状態として観測artifactへ保持するが、Subjectの恒常条件又は目標画風としてEMDへ自動転記しない。

`picture_reference_mode=auto_h3`ではComfyUIのhidden `PROMPT`と`UNIQUE_ID`を読み、自ノードのIMAGE pass-through出力が接続された、基準Context Loop adapterで認識できるH3 Ref2VA画像入力を探す。`ref_image_0`を`<Picture 1>`、`ref_image_8`を`<Picture 9>`として解決する。nested `ref_images.ref_image_N`も同じ規則で扱う。同じPicture番号への複数分岐は許可し、異なる番号へ同時分岐した場合は勝手に一つを選ばず曖昧エラーにする。認識対象は同一IMAGEの直接linkとComfyUIが実行promptで解決済みのrerouteに限り、画像加工nodeを越えたtensorを同一画像とはみなさない。

`manual`は`picture_index`を使い、グラフを調べない。`none`は画像を観察資料としてだけ使い、`<Picture N>`関連を出さない。`auto_h3`で対応H3入力が見つからない場合も観察は成功させ、bindingを`unbound`として返す。解決したH3 node ID、class type、input名、Picture番号をbinding fingerprintとComfyUIの`IS_CHANGED`へ含め、配線だけを変更した場合に古いEMD断片を再利用しない。

ノード内には`resolved_picture_reference`という読み取り専用の一行表示を置く。解決成功時は`<Picture N>`、未接続時は`unbound`、異なる番号への複数分岐時は`ambiguous`を表示する。これは編集可能な入力widget又は下流socketではなく、直近のgraph解決結果を確認するためのUIである。表示値をbindingの根拠にはせず、backendがhidden graphから得た結果を正とする。

### 5.3 出力

- `emd_fragment`: 通常のSTRINGでも保存・編集できる`MVD_EMD_FRAGMENT_V1`。`# サブジェクト`を持ち、binding成功時は同じ項目内へ`<Subject N>`と`<Picture N>`の関係を書く。
- `reference_bindings`: optional `MV_DIRECTOR_REFERENCE_BINDINGS`。`MVD_REFERENCE_BINDINGS_V1`としてserializeでき、概念ID、`subject_ref`、`picture_ref`、接続先signature、入力image fingerprintを持つ。
- `image`: H3へ分岐できる、入力と同一のIMAGE tensor。modeにかかわらず常にpass-throughする。
- `observations_json`: 可視事実、uncertainty、provenanceを持つdebug/再利用用出力。下流必須にしない。

`resolved_picture_reference`は上記出力socketへ加えず、frontendの読み取り専用表示として返す。workflowを開いただけでは古い表示を確定値とみなさず、配線変更後の次回実行で更新する。

Image to Subject EMDはScene、Shot、歌詞、音響、カメラ又は物語展開を生成しない。person/objectでは見える形、色、数、衣装、材質及び状態、locationでは見える場所と構成要素だけをサブジェクト定義へし、名前、履歴又は画面外を推測しない。画像固有のpose、構図、照明及びsource styleは観測には残すがSubjectの恒常条件へ自動追加しない。`subject_hint`は`user_hint` provenanceを持つauthorityとして保持するが、画像で見えた事実とは偽らない。`additional_instruction`は観察対象を絞るだけで、設定値として本文へ自動追加しない。

### 5.4 bindingなしの単独利用

- Image to Subject EMD自体を接続しない上流編集経路を正式にサポートする。
- `picture_reference_mode=none`又は`auto_h3`の`unbound`は、観察・EMD断片出力として正常である。
- bindingの追加・除去で観察本文やScene演出を再生成する必要はない。
- 本仕様のCompilerはRef2VA専用だが、`<Picture N>`関連のない完全EMDも文章定義だけのH3内蔵概念として受理する。T2VAへfallbackしない。

## 6. Enhancer契約

### 6.1 入力

- `concept_emd`: 一個のImage to Subject EMD出力又は手書きの一個のEMDサブジェクト断片。未接続でもよい。複数socket、可変list又は内部mergeは設けない。
- `observations_json`: provenance確認用の任意入力。接続を要求しない。
- `user_request`: 空又は自由な短文。見出しや定型文を要求しない。
- `style_profile`、`motion_profile`、`camera_profile`
- `model_name`、`seed`、生成設定

概念EMDがなくてもuser requestとprofileからdirectionを作れる。ユーザーが「丸く短い金色の眉」のような重要特徴を明示した場合、その条件をVision由来概念より優先する。

初期の自動MV workflowでは、一個のImage to Subject EMDの`emd_fragment`をEnhancerとPlannerの単一`concept_emd`へ分岐する。複数参照を使う場合は完全EMDを手書き又は外部で構成し、Compiler単独経路へ渡す。Enhancerはサブジェクト断片を結合しない。

### 6.2 出力

`MVD_DIRECTION_V1`はPythonが行recordを解析して構築する内部artifactであり、利用者が記述する第二の文法ではない。LLMへこのJSONを生成させず、Enhancerは同じ内容を人間が確認できる`direction_emd_preview` STRINGも返す。Plannerはartifact socketを直接受け取り、preview文字列を再parseしない。少なくとも次を持つ。

```json
{
  "schema": "MVD_DIRECTION_V1",
  "style_direction": [],
  "motion_direction": [],
  "camera_direction": [],
  "other_direction": [],
  "provenance": [
    {
      "record_id": "src_0001",
      "record_kind": "input",
      "source": "user",
      "source_ref": "user_request",
      "source_position": 0,
      "target": null,
      "disposition": "supplied",
      "reason": "direct_input",
      "sha256": "..."
    },
    {
      "record_id": "out_style_0001",
      "record_kind": "output",
      "source": "generated",
      "source_ref": "STYLE:1",
      "source_position": 1,
      "target": "style_direction[0]",
      "disposition": "accepted",
      "reason": "valid_line_record",
      "sha256": "..."
    }
  ]
}
```

`style_direction`、`motion_direction`、`camera_direction`、`other_direction`は、それぞれ完成EMDの`## スタイル`、`## モーション`、`## カメラ`、`## その他`へ一対一で入る短い全体方針であり、Sceneイベント一覧にはしない。各配列は空を許し、空の区分はEMDへ出さない。`concept_emd`は演出を考えるための読み取り専用contextであり、EnhancerはSubject record、Picture束縛又は保持分析を出力・修正しない。背景と時間帯の全Scene共通表現はstyle、人物や物品の動き方はmotion、構図と視点移動はcamera、前三分類に入らない全Scene共通事項はotherへ分類する。

provenance recordのfieldと値域は固定する。`record_id`はPythonが文書順に決定し、入力を`src_NNNN`、採用出力を`out_<section>_NNNN`、機械的に破棄したLLM行を`drop_NNNN`とする。`record_kind`は`input` / `output` / `discard`、`source`は`user` / `vision` / `profile` / `generated`、`source_ref`はsocket名、概念ID、profile ID又は行protocol slot、`source_position`は0始まりの入力item又は応答行番号とする。`target`は採用出力の配列位置だけに設定する。`disposition`は`supplied` / `accepted` / `discarded`、`reason`は`direct_input` / `valid_line_record` / `empty` / `exact_duplicate` / `invalid_line_record`だけをV1で認める。本文は複製せずSHA-256だけを置く。

意味上「どの入力語句を採用、上書き又は破棄したか」はLLMの内部判断であり、Pythonが文字列類似度から推測せず、LLMにも説明を生成させない。`superseded`や`higher_authority`という処分理由はV1 provenanceへ設けない。authority順はEnhancer promptの入力契約であり、provenanceはその遵守を証明するsemantic auditではない。

`concept_emd`が未接続又は空文字列で、`user_request`も空であっても正常入力とする。Enhancerは選択済みの既定profileから基準directionを生成できなければならず、利用者記述のpromptを動作条件にしない。Plannerではdirection artifactも任意であり、未接続時は四方向を空として歌詞由来の局所計画を続行する。PlannerとCompilerのparserはsubsection見出しを境界として扱い、本文を正規表現又はキーワード辞書で再分類しない。

### 6.3 実行規則

- 一回のLLM統合で`STYLE`、`MOTION`、`CAMERA`と任意の`OTHER` recordを出力する。必須recordの欠落だけ同じ対象を一回再生成できる。
- 意味監査、別LLMによる採点、自動意味修復は行わない。
- user、vision、profileを別々に機械連結した巨大promptのまま下流へ送らず、統合結果とprovenanceを保存する。
- userの原文もartifactへ保持するが、LLMへ同じ文章の厳密な再出力を要求しない。

## 7. Timeline生成とPlanner契約

### 7.1 Lyric Segmentation support node

公開nodeは`MVDirectorLyricSegmentation`、表示名は`MV Director - Lyric Segmentation`、カテゴリは`MV Director/Input`とする。LLM、Vision、Planner又はH3を要求せず、字幕生成だけにも単独利用できる。

主入力:

- `vocal_audio`: padding前のボーカル又は発話AUDIO。
- `lyrics_text`: 7.1.1のplain lyrics文法に従うUTF-8テキストSTRING。LRC又はSRTを受理しない。
- `whisper_model`: ComfyUIのWhisper model root以下にローカル配置したOpenAI Whisper `.pt` checkpoint。
- `h3_timing_profile`: `MV_DIRECTOR_H3_TIMING_PROFILE`。未接続時は4.4の基準profileを使う。SRT時刻の検出には影響せず、Template EMDのScene境界と`` `H3長` ``だけに使う。
- `language`（初期既定`ja`）、`max_scene_duration_ms`（既定10000）、`srt_time_offset_ms`、`cache_mode`、`keep_whisper_loaded`（既定`false`）。

主出力:

- `template_emd`: `MVD_EMD_TEMPLATE_V1`の編集可能なSTRING。各Scene直前の必須Scene annotation、Scene/Shot見出しと歌詞annotationを含むが、演出、action、cameraを生成しない。
- `srt_text`: 解決済みatomic lyric segmentをそのまま標準SRTへ直列化したSTRING。section見出しは字幕本文へ入れない。SRTだけは規格どおり`HH:MM:SS,mmm --> HH:MM:SS,mmm`を使い、EMDの`MM:SS.mmm`とは混在させない。
- `timeline`: 絶対ms、Scene/Shot、整列結果、`unplaced_lyrics`を持つ`MVD_TIMELINE_V1`。
- `status`: 解決数、未解決数、尺、cache、警告。

`srt_time_offset_ms`は外部字幕調整用で、`srt_text`だけへ適用する。`template_emd`と`timeline`の元音源時刻は変更しない。未解決歌詞へ推測時刻を作らず、SRTから除外して`unplaced_lyrics`とstatusへ残す。

Template EMDはPlannerの標準入力である。Plannerはこの文字列のannotationと確定枠を読み、内容を補完して`MVD_EMD_V1`を作る。Template EMDを受けた場合はWhisperを再実行しない。Template単体は演出本文が未完成なのでCompilerの完成EMD入力とはみなさない。

#### 7.1.1 plain lyrics入力文法

入力は次のような`.txt`由来のplain lyricsだけを扱う。

```text
[VERSE1]
ほげほげ ふがふが

[VERSE2]
...
```

- 最初の非空行はsection見出しとする。見出しは行全体が`[A-Z][A-Z0-9_-]*`を角括弧で囲んだ形に完全一致し、前後空白を許さない。
- `VERSE1`、`CHORUS`、`BRIDGE_A`等を使用できる。未知名と同名sectionの再登場を許し、出現順を保持して自動統合しない。
- 空行は読みやすさのための区切りとして無視する。空sectionも許可する。
- section外の歌詞本文、comment構文、LRC timestamp、SRT番号・時刻行、inline metadataは受理しない。
- 通常の歌詞行は原文を保持したまま、ASCII空白、tab又は全角空白の一個以上のrunでatomic segmentへ分ける。連続空白から空segmentを作らない。
- section見出しと区切り空白はSRT本文へ出さない。句読点、長音、括弧その他の歌詞文字はsegment本文として変更しない。
- `lyrics_text`は通常STRINGなので直接入力もできるが、由来ファイルにかかわらず同じ文法を適用する。拡張子ではなく本文をparserの正とする。

初期版は日本語歌詞を対象に空白を明示的なphrase境界として扱う。英語等、通常の単語間空白を持つ歌詞はこの文法の対象外とし、暗黙のlanguage別推測を行わない。

### 7.2 音声・歌詞時間解析

初期方式を次で固定する。

1. 歌詞本文の物理改行をhard boundaryとし、各行をASCII空白、tab又は全角空白の一個以上のrunでも分割する。空白run自体は区切りであり、segment本文へ残さない。各非空片へ原文順の不変`segment_id`、元行番号及び文字範囲を与える。section見出しは分割対象にしない。
2. `openai-whisper`を実行時に遅延importし、解決済みローカル`.pt`を`whisper.load_model()`へ渡す。`task="transcribe"`、`temperature=0.0`、`beam_size=5`、`word_timestamps=True`で一回実行し、各atomic lyric segmentが音源上のどこに現れるかを検出する。package、model又は更新を自動インストール／ダウンロードしない。`openai-whisper`がなくてもextension全体のimportと他nodeの登録は成功させ、本node実行時だけ明示エラーにする。
   ComfyUI AUDIOは一batch、1 channel以上、1 sample以上を要求する。VADは元sample rateの全channel中最大RMSを使い、Whisper入力だけはfloat32平均monoへdownmixして16kHzへresampleする。原音tensorを書き換えず、VADのsample-domain境界は元sample rateで保持する。
3. vocal stemを20ms窓のenergy VADで粗く解析する。旧既定値を比較開始点として、threshold `-45 dBFS`、最小有声120ms、最小無音300ms、前後padding 80msを使う。実測前の最適値とは呼ばない。
4. 各粗区間の開始・終了近傍だけを、同じthreshold方針の包絡線とhysteresisでsample-domain再探索する。確定したsample indexを`round(sample_index * 1000 / sample_rate)`で整数msへ一度だけ変換する。同じmsへ潰れる場合も内部順序を壊さず、必要なら次のmsへ押し出した事実をstatusへ残す。
5. sectionとatomic segmentを正規化文字列の順序付き整列でWhisper word列へ対応させる。Whisperの位置候補をrefined VAD区間へ束縛し、segmentの開始・終了境界を整数msで確定する。初期版では未解決箇所だけの追加Whisper retryを行わない。
6. 解決できたsegmentは`segment_id`、原文片、section、元行・文字範囲、開始・終了絶対msを保持する。未解決segmentは削除せず`unplaced_lyrics`へ残し、警告する。推測時刻を確定値として作らない。
7. 音源総尺はsample数とsample rateから整数msへ一度だけ変換する。sub-msがある場合は末尾sampleを失わない方向へ丸める。有声境界を整数秒へ量子化せず、refined VADが返した整数msのまま接する有声範囲を結合し、補集合を無音範囲とする。
8. 各連続範囲を`max_scene_duration_ms`以下へなるべく均等に分割し、元音源上の要求Scene境界を作る。境界候補が解決済みsegment内部に入る場合は、そのsegmentを切らない最も近い境界へ移動する。空白分割後も一個のsegment自体が上限を越す場合だけ、Whisperの整列済みword境界でさらに分割し、派生した各片を新しいcanonical segmentとして以後のEMDとSRTで共用する。歌詞の確定区間と重なるSceneはvoicedへ昇格する。
9. 要求Scene長をH3 timing profileへ通し、segment内部へ入らない合法なdelivered-frame境界を選ぶ。合法境界を選べない場合だけ直前の規則でword境界分割を行い、Scene割当てを再計算する。先頭Sceneは合法raw `17k+5`、`anchor_mode=head`の後続Sceneはcontext lengthを含む合法raw `17k+5`を使う。
10. Sceneの機械的な開始・終了はdelivered framesの累積値を正とし、表示用EMD時刻だけを`round(cumulative_frames * 1000 / 24)`で整数msへ一度直列化する。各Sceneへ1から始まる不変の`scene_number`、`raw_length`、`delivered_frames`、`context_length`、要求元範囲、量子化差分及びtiming profile IDを保持する。各canonical segmentへ一個の`scene_number`を確定する。Template rendererは`scene_number`から必須の``> `シーン` N``を出力する。Compilerへ渡す`` `H3長` ``はここで確定し、下流で再計算しない。

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
    {"segment_id": "lyric_0001", "text": "千年鳥居をくぐるそなたよ", "section": "VERSE1", "source_line": 1, "source_start": 0, "source_end": 12, "start_ms": 12300, "end_ms": 15800, "scene_number": 2, "shot_index": 2}
  ],
  "scenes": [
    {
      "scene_number": 1,
      "start_ms": 0,
      "end_ms": 10125,
      "source_start_ms": 0,
      "source_end_ms": 10000,
      "raw_length": 243,
      "delivered_frames": 243,
      "context_length": 0,
      "shots": [
        {"start_ms": 0, "end_ms": 10125}
      ]
    },
    {
      "scene_number": 2,
      "start_ms": 10125,
      "end_ms": 20042,
      "source_start_ms": 10000,
      "source_end_ms": 20000,
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

`vad_analysis_hop_ms`は粗探索の窓、`boundary_resolution_ms`は音源解析境界の直列化単位である。後者は音響的な正解の保証値ではない。Sceneの`source_start_ms` / `source_end_ms`はLyric Segmentationが確定した元音声上の連続範囲であり、Audio参照動画生成WFのPCM slice境界にも使う。`start_ms` / `end_ms`はH3 delivered frame累積から別に直列化したPlan境界である。Shotの`end_ms`は次Shotの`start_ms`、最後だけSceneの`end_ms`からPythonが決める。

### 7.3 Shot枠

旧PlannerのShot時刻はLLM判断だったため移植しない。初期Shot枠はLyric Segmentationが確定したatomic lyric segmentだけからPythonが次の規則で作る。

1. 各Sceneの最初のShotはSceneの`start_ms`と同じ絶対ms。
2. Scene内に開始するsegmentの絶対開始msを昇順候補とする。先行segmentの終了前に次segmentが始まる重なりは同じactive groupとし、その途中へShot境界を作らない。
3. 直前に採用したShot開始から3000ms以上離れ、Scene終端まで2000ms以上残る候補だけ採用する。
4. 1 Scene最大3 Shotとする。
5. 採用候補がなければ1 Shotのままにする。beatや任意の中点を初期版では追加しない。

各canonical segmentは必ず一個のSceneと一個のShotへ構造的に割り当て、`scene_number`と`shot_index`をtimelineへ保存する。同じShotへ複数segmentを割り当ててよい。Template EMDでは割り当てた歌詞annotation群を対応する`## ショット`見出しの直前へ置く。歌詞の`start_ms` / `end_ms`はsource audio基準、Scene/Shot見出しはH3 Plan基準なので、数値包含を所属判定へ再利用しない。Template EMDとSRTはこの同じsegment列から生成し、PlannerとCompilerは本文分割、Whisper word再参照、境界跨ぎ補正又はSRT再構成を行わない。

これは映像的最適性ではなく、時刻の出典を明確にし、小さすぎるShotとLLMによる時刻破損を避ける初期方式である。閾値はH3評価後に変更可能だが、変更時はalgorithm versionをcache keyへ含める。

### 7.4 Timeline Planner公開socket

完全な公開socketは次とする。llama.cppの調整項目は旧Plannerから維持するが、旧camera/vocal guard、visual enrichment profile、意味repair及び可変retry回数は移植しない。

| 順 | 名前 | ComfyUI型 | 必須 | 既定値 | 用途 |
|---:|---|---|---|---|---|
| 1 | `template_emd` | `STRING` forceInput | 必須 | なし | Lyric Segmentationの時間・歌詞annotation付きTemplate EMD |
| 2 | `concept_emd` | `STRING` forceInput | 任意 | 空 | 一個のSubject EMD断片。Pictureなしも可 |
| 3 | `direction` | `MV_DIRECTOR_DIRECTION` | 任意 | 空の四方向 | Enhancerの`MVD_DIRECTION_V1`。ユーザー編集対象ではない |
| 4 | `lip_sync_mode` | STRING COMBO | 必須widget／外部接続可 | `lyrics` | `off` / `context_loop` / `audio_reference` / `lyrics` |
| 5 | `lip_sync_target` | `STRING` | 必須widget／外部接続可 | `人物1` | 口形対象の内部ID |
| 6 | `lip_sync_audio_slot` | `INT` 1..3 | 必須widget／外部接続可 | 1 | Audio参照時の`H3音声N` |
| 7 | `model_name` | GGUF COMBO | 必須 | 探索結果先頭 | 使用する任意GGUF |
| 8 | `model_name_override` | `STRING` forceInput | 任意 | 空 | Connected Combo等からの非空上書き |
| 9 | `chat_format` | COMBO | 必須 | `auto` | `auto` / `qwen` / `gemma` |
| 10 | `max_tokens` | `INT` 32..16384 | 必須 | 4096 | 一要求の最大出力token |
| 11 | `temperature` | `FLOAT` 0.1..1.0 | 必須 | 0.1 | sampling |
| 12 | `top_p` | `FLOAT` 0.0..1.0 | 必須 | 0.9 | sampling |
| 13 | `repetition_penalty` | `FLOAT` 0.5..2.0 | 必須 | 1.05 | sampling |
| 14 | `gpu_layers` | `INT` -1..1000 | 必須 | -1 | llama.cpp GPU offload layer数 |
| 15 | `n_batch` | `INT` 32..4096 | 必須 | 256 | llama.cpp prompt batch |
| 16 | `n_ctx` | `INT` 0..131072 | 必須 | 16384 | context長。0はmodel/backend既定、4B/32K試験では32768 |
| 17 | `flash_attn` | `BOOLEAN` | 必須 | true | llama.cpp Flash Attention |
| 18 | `kv_cache_type` | COMBO | 必須 | `q8_0` | `q8_0` / `f16` |
| 19 | `op_offload` | `BOOLEAN` | 必須 | true | llama.cpp op offload |
| 20 | `keep_model_loaded` | `BOOLEAN` | 必須 | false | 実行後model保持 |
| 21 | `seed` | `INT` 1..2147483647 | 必須widget／外部接続可 | 1 | 言語生成seed |
| 22 | `scenes_per_batch` | `INT` 1..6 | 必須 | 3 | action/cameraの最大Scene pack。lyric-notesは最大6 |
| 23 | `cache_mode` | COMBO | 必須 | `use` | `use` / `refresh` / `off` |
| 24 | `save_debug_output` | `BOOLEAN` | 任意 | false | prompt全文等の診断bundle保存 |

出力順は`emd_text: STRING`、`emd: MV_DIRECTOR_EMD`（`MVD_EMD_V1`）、`status: STRING`とする。`emd_text`は通常のマルチラインSTRINGへ接続して人間が編集できる正本で、typed `emd`はcache、診断又は型付き接続用である。Compilerはtyped artifactを要求せず、編集済み`emd_text`だけで単独動作する。

### 7.5 LLMタスク分割

Plannerの`concept_emd`も一個だけを受け取る。初期自動MV経路では同じImage to Subject EMD出力をEnhancerとPlannerへ分岐し、Planner側でも複数断片の結合、優先順位判定又は番号振り直しを行わない。

Plannerの順序は次で固定する。

1. PythonがLLM入力に含まれる作者由来の`「...」`及び明示`<d>...</d>`をID付きplaceholderへ置換し、原文をside tableへ退避する。
2. `lyric-notes`: 対象範囲の原文歌詞とsectionから、局所的な意味、感情変化、視覚モチーフ候補を短く作る。
3. `song-direction`: lyric notesだけから、全曲を通す短い弧、反復してよい要素、変化させる要素を作る。全歌詞を再添付しない。
4. `actions`: direction、対象Scene、該当歌詞、必要な直前状態、Python所有Shot枠から、Shot IDごとの人物動作を生成する。
5. `cameras`: 同じShot枠、確定したaction、camera profileから、Shot IDごとの構図とカメラを生成する。action本文を再出力しない。
6. Pythonが採用した行recordの`TEXT`から新規生成された引用台詞とplaceholder echoを削除する。
7. Pythonが任意のサブジェクトEMD、direction、annotation、action、camera、audio templateを完全EMDへ合成し、選択したlip-sync modeのdirectiveを最後に挿入する。`<Subject N>`と`<Picture N>`の関連及び`` `H3長` ``は内容を創作又は再計算せずそのまま保持する。

人物動作へ開始・主動作・終了の必須欄や最低段階数を課さない。区間内同期は一つ以上の自然文でH3へ伝える。カメラ出力に人物動作の置換・削除権限を与えない。

同じShotの人物動作とカメラは同じShot全区間で並行するものとしてrenderし、人物動作文を先、カメラ文を後に置く。両taskは数値sub-timeを生成せず、`while`、`as`、`then`又は「終わりまでに」に相当する自然な相対関係だけを使える。camera taskは確定actionを読み取り専用contextとして受け、動作の開始、終了又は順序を変更しない。cutは既存Shot境界でだけ表現し、新しい時刻又はShotをcamera LLMに作らせない。従って一つのShot本文にmid-shot cutを出力しない。

#### 7.5.1 Plannerの台詞placeholderと生成台詞filter

- placeholderは一run内で一意な`__MVD_LOCKED_DIALOGUE_0001__`形式とし、元文字列、入力record ID及び位置をPython side tableへ保持する。placeholderとside tableはEMD、cache preview又はH3 promptへ残さない。
- LLM応答は2.6の行protocolでrecord化し、採用した各recordの`TEXT`だけを走査する。typeとslotにはfilterを掛けず、recordの対応関係を変更しない。
- side tableにある既知placeholderもLLM応答中ではsource echoとして削除する。未知placeholder及び重複placeholderも同じく削除する。原文はLLM応答から復元せず、Subject、Direction又は作者Shot本文のPython所有位置から一度だけ出力する。
- LLMが新規生成した`「...」`、`『...』`、`“...”`、文字列field内の`"..."`又は`<d>...</d>`は、delimiterを含むspan全体を無条件で削除する。意味、言語、話者又は内容を判定しない。
- 閉じdelimiterのない開始記号はその位置からfield末尾まで、対応する開始記号のない閉じdelimiterは閉じ記号だけを削除する。削除後は隣接空白だけを一個へ正規化し、空になった生成list itemは落とす。
- このfilterによる削除、空item又は未使用placeholderはLLM retry条件にしない。`removed_generated_dialogue_count`と`unused_protected_dialogue_ids`をstatusへ残す。削除後の成果と原位置に保持した作者本文をPython rendererへ渡す。
- Plannerが`lip_sync_mode=lyrics`で歌詞から作る``リップシンク 歌詞`` directiveはLLM応答ではないためfilter後にPythonが挿入する。作者由来の復元台詞と同様、生成台詞として削除しない。他のmodeではこのdirectiveを挿入しないが、歌詞annotation自体は削除しない。

Plannerには外部接続可能な`lip_sync_mode`（`off`、`context_loop`、`audio_reference`、`lyrics`。既定`lyrics`）、`lip_sync_target`（既定`人物1`）、`lip_sync_audio_slot`（1～3、`audio_reference`時だけ使用）を設ける。これらはLLM promptへ渡さず、Python rendererだけが次のように使う。

- `off`: リップシンクdirectiveを出さない。
- `context_loop`: Lyric Segmentationが一個以上の`歌詞`annotationを構造配置したSceneへ``* `リップシンク` `Context Loop` `人物1` ``を出す。
- `audio_reference`: Lyric Segmentationが一個以上の`歌詞`annotationを構造配置したSceneへ``* `リップシンク` `Audio参照` `人物1` `H3音声1` ``を出す。対象とslotは入力値を使う。
- `lyrics`: Plannerが各Shot見出しの直前に置かれた解決済み`歌詞` annotationを文書順に読み、同じShotへ一segmentごとの``* `リップシンク` `歌詞` `人物1` 「原文」``を出す。歌詞のないShotへは出さない。

歌詞annotationは四つのmodeすべてで同じcanonical表記のまま完成EMDへ保持する。選択歌詞はmodeにかかわらず人物動作・演出推論へ使用でき、`lip_sync_mode`は口形を駆動する実行方式だけを切り替える。従って`context_loop`又は`audio_reference`を選んだ時の「歌詞を破棄する」とは、``リップシンク 歌詞``をmaterializeしないという意味であり、annotation、SRT又は`MVD_TIMELINE_V1`から歌詞を物理削除する意味ではない。Compilerは全modeで歌詞annotationを読み飛ばすため、保持してもH3 promptへ重複転記されない。

Plannerは別の`vocal evidence`判定を行わない。VADとWhisperはLyric Segmentationがatomic lyric segmentのsource開始・終了msを確定する工程だけで使い、PlannerはShot直前へ構造配置済みの歌詞annotationの有無を唯一の`lip_sync_active`条件とする。annotationのない間奏SceneへはContext Loop又はAudio参照directiveを出さない。

`lip_sync_mode`及び`lip_sync_audio_slot`の変更は、確定済み歌詞、Shot枠、人物動作及びカメラ出力を再推論せず、決定的directive rendererとその下流だけを無効化する。`lip_sync_target`は口形対象であると同時に人物動作の対象へ影響し得るため、変更時は対象依存の人物動作taskとrendererを無効化する。

Timeline PlannerはMV専用である。完成動画にどの音声を残すかはPlanner入力でもEMD directiveでもなく、下流の動画生成WFにあるContext Loop Chain Policyが所有する。Plannerは`lip_sync_mode`に対応する口形directiveだけを出し、最終音声方針を表す`lock_source_audio`又は`ソース音声固定`は設けない。標準構成は`context_loop`、`audio_reference`、`lyrics`の三つのPlan/Compiler WFを、同名方式の三つの動画生成WFへ一対一で接続する計6 WFとする。各動画生成WFは自方式の音声socket、Generation Profile、任意Lip-Sync Options及び最終音声Chain Policyを所有する。

### 7.6 再試行

- 各taskの許可type、短いslot集合、重複及び欠落recordだけを検証する。実Scene/Shot IDと時刻はLLM応答に含めない。
- batch応答の一Sceneだけが構造不正なら、そのSceneだけ一回再生成する。
- LLM応答中の引用台詞、発話表現又はdialogue tagは品質・protocol retryの理由にせず、7.5.1のfilterで一回だけ機械削除する。
- 品質が弱い、表現が好みでない、意味が疑わしいという理由で自動再試行しない。
- 同じ対象を上位taskへ戻す入れ子retryを作らない。
- 一回の局所retryでも有効にならなければ未完了artifactを返し、H3 Planとしては出力しない。

### 7.7 Audio Pad Pair

公開support nodeは`MVDirectorAudioPadPair`、表示名は`MV Director - Audio Pad Pair (PCM Silence)`、カテゴリは`MV Director/Audio`とする。旧`CLAudioPadPair`の有限なPCM処理を再利用するが、単体`CLAudioPad`相当のnode typeは実装又は登録しない。

- `audio_a`へfull mix、`audio_b`へvocal stemを接続する。
- 二入力は同じ時刻原点と再生速度を持つことを前提とし、offset検出、同期推定、resample、mix又はtruncateを行わない。
- 共通基準尺は二入力尺、任意の`MVD_TIMELINE_V1.plan_duration_ms`又は明示H3 frame targetの最大値に`extra_padding_ms`を加えてsample数へ変換する。浮動小数秒を基準値にしない。
- 短い側だけを各sample rateで無音補完し、`pad_position=end`を既定にする。
- `padded_audio_a`と`padded_audio_b`はH3 Audio Tracksへ渡す。Lyric SegmentationのVAD / WhisperとH3 Lip-Sync Optionsにはpadding前の元vocalを渡す。
- 単体Audio Padの公開classは再利用しない。入力検証とPCM paddingに必要な処理だけをPair module内のprivate helperへ抽出する。

## 8. EMD（Easy MarkDown）`MVD_EMD_V1`

EMDは**Easy MarkDown**の略称であり、Extended Markdownの略称ではない。標準Markdownの見出し、list及び引用を使い、人間が編集できる簡潔な中間言語へ予約行だけを追加する。

EMDのcanonical構文、文書種別、valid/invalid例及びCompiler固定写像の確認には[EMD仕様書](emd-spec.md)を使う。本節はシステム全体との接続境界を説明し、構文に差異がある場合は専用仕様書を初期実装の基準とする。

### 8.1 基本構造

これは新表記であり、旧ノードには未実装である。

```markdown
# サブジェクト
* `人物1`
* `H3サブジェクト` `<Subject 1>`
* `参照画像` `<Picture 1>`
* `名称` 主人公
* 長い黒髪と淡い金色の短く丸い眉を持ち、白と朱色の衣装を着た人物。

# 保持分析
* `人物1`: 顔立ち、髪、衣装、配色、身体付属物の数と形を保持する。

# 共通プロンプト
## スタイル
* 実写映画として描画し、自然な肌、物理的な布、現実的な月光、映画的なレンズの奥行きを保つ。
## モーション
* 接地と重心を保ち、髪と衣装が身体へ一歩遅れて追従する連続動作として描く。
## カメラ
* 顔と全身動作を読める距離を保ち、前景・中景・遠景の視差を使う。
## その他
* 全Sceneを通して夜から夜明けへの色温度変化を保つ。

> `シーン` 1
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
* `リップシンク` `Context Loop` `人物1`
```

これはPicture関連を持つCompiler入力例である。`# サブジェクト`内で意味上の`<Subject N>`と物理入力の`<Picture N>`を関連付け、別の`# H3参照束縛`章は作らない。Pictureを使わない場合は`参照画像`行だけを省略する。

文書順は`# サブジェクト`、任意の`# 保持分析`、任意の`# 共通プロンプト`、1個以上のSceneとする。共通プロンプト直下の`## スタイル`、`## モーション`、`## カメラ`、`## その他`はすべて省略可能で、存在する場合だけこの相対順に置く。`MVD_EMD_FRAGMENT_V1`は`# サブジェクト`だけを持てる。Compilerが受理する`MVD_EMD_V1`は一件以上のSubject recordと1個以上のSceneを必須とするが、Picture関連は0件でもよい。生成EMDでは全Sceneの絶対開始・終了時刻、各Sceneの`` `H3長` ``及び全Shotの絶対開始時刻を必須にする。

`# 共通プロンプト`の四区分は作品全体で共有する任意のH3 promptである。Compilerは各区分を別に構文解析・翻訳し、見出しを除いた存在する本文だけを`スタイル → モーション → カメラ → その他`の固定順で平坦化してContext Loop Planの`prompt_prefix`へ一回だけ写す。全区分が省略されていれば`prompt_prefix`を出力しない。JSON propertyの記述位置ではなく`prompt_prefix`というkeyが先頭連結を指示する。スタイルが存在する場合、その最初のlist itemは生成先の目標画風を短い肯定文で記述し、元参照画像の媒体表現を生成先の固定条件にしない。`subject_definitions:`等のContext Loopセクション見出し、Shot marker又は動的`{A|B}`候補は共通プロンプトへ入れない。

### 8.2 サブジェクトとPicture関連

- EMD内部IDは`` `人物1` ``～`` `人物16` ``、`` `場所1` ``～`` `場所16` ``、`` `物品1` ``～`` `物品16` ``。これは作品内の同一性を表す。
- ``* `人物N` ``、``* `場所N` ``又は``* `物品N` ``がSubject recordの開始であり、次の内部ID開始行又はtop-level見出しまでを同じrecordとする。内部IDに`##`見出しは使用しない。
- 各Subject recordは``* `H3サブジェクト` `<Subject N>` ``を一件必須とし、直後へ``* `参照画像` `<Picture N>` ``を任意で一件だけ置ける。`<Subject N>`はprompt内の意味上の主体、`<Picture N>`はH3へ接続する物理画像であり、同じslot体系ではない。
- 完全EMD内の`<Subject N>`は1～4で一意とする。同じ`<Picture N>`を複数Subjectから参照することは許可する。初期の自動MV経路は一個だけを生成するが、Compiler単独経路はこの範囲内の複数Subject/Pictureを処理する。
- `<Subject N>`は人物型に限定せず、`` `人物N` ``は`person`、`` `場所N` ``は`environment`、`` `物品N` ``は`object`として固定文型へ写す。場所は建築・地形・空間配置、物品は形状・材質・部品構成を主な保持対象とする。Picture関連がなければSubject説明だけをH3内蔵概念として使い、存在しない画像条件を補わない。
- Image to Subject EMDの`auto_h3`はIMAGE出力の接続先`ref_image_0..8`から`<Picture 1..9>`を決める。`subject_index`は接続先から推測せず、独立入力として保持する。
- backtickを含む完全なinline-code tokenだけをEMD内部IDとして認識する。通常本文中の「人物1」はIDではない。
- Compilerは本文中の内部IDを対応する`<Subject N>`へ固定変換する。Picture関連があるrecordだけ`subject_definitions`へ`<Picture N>`との関係を出し、ないrecordは翻訳済みSubject説明だけで定義する。Picture内容又は実配線を推測しない。
- `<Subject N>`と`<Picture N>`を使用できるのは上記二つの予約行だけとし、自由文へ直接書かれた最終tagは構文エラーにする。旧`` `対象N` ``、`` `画像N` ``、`` `H3対象N` ``、`` `H3画像N` ``のalias又は読み替えは実装しない。
- `<Subject N>`の欠落、番号範囲、予約行の順序又は重複だけを文法エラーにする。`参照画像`行の省略はエラーにせず、画像の意味又はSubjectとPictureの内容的一致も監査しない。
- Compilerは`required_references`として実際に記述されたPictureと対応内部IDだけを返す。PictureとAudio参照が共になければ空配列を返す。`<Subject N>`を`ref_image_N`へ変換しない。実画像tensorとの接続確認は`MVD_REFERENCE_BINDINGS_V1`又はworkflow validatorが行う。

### 8.3 SceneとShot時刻

- 各Scene見出しの直前の物理行へ``> `シーン` N``を必須とする。`N`は1からScene順に1ずつ増やし、重複、欠番、逆順又は0を許可しない。Compilerは番号を推測又は補正せず、Plan Scene `id`へ`scene_NNNN`として写す。
- Scene見出しは`# シーン START --> END`だけとし、`START`と`END`はH3 delivered frame累積から直列化したplan絶対時刻を必須とする。追加suffixは付けず、継続条件はScene位置とH3 Timing Profileが所有する。
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
| `シーン` | 直後のScene見出し一件 | 必須。1から始まる連番。見出しとの間に空行を置かない |
| `セクション` | 次の`歌詞`一件 | 任意。重複不可 |
| `歌詞開始` | 次の`歌詞`一件 | 元音源の絶対時刻。終了と対で使う |
| `歌詞終了` | 次の`歌詞`一件 | 元音源の絶対時刻。開始より後 |
| `歌詞` | 次のShot見出し一件 | atomic segment原文。直前のpending metadataを一組として確定し、Shot直前のpending segment列へ追加する |

canonical順は`セクション`、`歌詞開始`、`歌詞終了`、`歌詞`とする。時刻形式は`MM:SS.mmm`で、分は2桁以上、秒00～59、msは3桁。開始と終了は両方あるか両方ないかとする。

Lyric Segmentationは一個のatomic segmentにつき一組を作り、同じShotへ属する一組以上を連続blockとして、そのShot見出しの直前へ一回だけ配置する。歌詞時刻はsource audio基準、Scene/Shot時刻はH3 Plan基準なので数値包含を要求しない。blockの途中へ通常本文、別見出し又はcommentを挟む場合、あるいはblock直後がShot見出しでない場合は構造エラーとする。

値はlabel終端後の一つ目のASCII spaceより後を、Markdown unescape、HTML decode、trimせず保持する。CR/LFだけは文書行区切りとして除く。backslash、backtick、`>`、Markdown記号を値中で特別扱いしない。空の歌詞はエラーとする。入力の物理改行又は空白runによる分割はLyric Segmentationが済ませており、EMD parserは`歌詞`値を再分割しない。

`シーン` annotationは歌詞用pending metadataへ積まず、直後のScene見出し一件で即時消費する。直後がScene見出しでない、間に空行又はcommentがある、あるいはScene見出しまでに別の予約行が入る場合は構造エラーにする。

`> 人間向けコメント`のようにinline-code labelを持たない引用行は人間向けcommentとして保持できる。`> `で始まり未知のinline-code labelを持つ行は、誤記を黙ってcommentにしないため構造エラーにする。歌詞用pending annotationを残したままShot又は次Sceneへ進む場合もエラーとする。

annotationはPythonが工程間で保持し、必要なPlanner taskだけへ渡す。翻訳LLMへ転記させず、最終H3 promptへ出力しない。

### 8.5 Shot単位の``リップシンク 歌詞``

``リップシンク 歌詞``はScene末尾の`## 音響`ではなく、対象Shotの本文へ置くlist directiveである。次は全timeline中の`00:10.000`から始まるScene抜粋である。

```markdown
> `シーン` 2
# シーン 00:10.000 --> 00:20.000
* `H3長` 260
> `歌詞開始` 00:12.300
> `歌詞終了` 00:15.800
> `歌詞` 千年鳥居をくぐるそなたよ
## ショット 00:10.000
* `人物1`は鳥居の奥へ視線を向ける。
* `リップシンク` `歌詞` `人物1` 「千年鳥居をくぐるそなたよ」
## ショット 00:15.000
* `人物1`は石畳を進む。
* `リップシンク` `歌詞` `人物1` 「月明かりの道を」
```

Plannerは各Shot見出しの直前に構造配置された解決済み歌詞を、そのShotへ割り当て済みとして扱う。同じShotに複数segmentが入る場合は一行ずつ文書順に出す。CompilerはShot見出しの絶対開始時刻からScene相対開始時刻を機械算出し、各directive内の対象・歌詞原文だけを固定promptへ展開する。`歌詞` annotationを検索、時刻対応付け又は補完しない。

これはShot区間でH3に歌唱時の可視口形を促す時間付きpromptである。音素、word又はframe単位の口形列は生成せず、元音声との完全同期を保証しない。

### 8.6 `## 音響`

音響は説明文を解析せず、予約済みdirectiveだけを扱う。リップシンク駆動方式はSceneごとに一つだけ選ぶ。現在のContext Loop Lip-Sync Optionsを使う場合は次とする。

```markdown
## 音響
* `リップシンク` `Context Loop` `人物1`
```

Lip-Sync Optionsの追加モデルを使わず、H3音声参照で駆動する場合:

```markdown
## 音響
* `リップシンク` `Audio参照` `人物1` `H3音声1`
```

生成条件を無音にする場合:

```markdown
## 音響
* `無音`
```

`## 音響`の省略はエラーでも無音でもなく、Scene固有の音声要素を出力しないことを意味する。下流のChain Policyをそのまま継承する。Compilerは接続音声を調査せず、次の予約directiveだけを機械的に写像する。

- `リップシンク` + `Context Loop` + 一つの概念ID
- `リップシンク` + `Audio参照` + 一つの概念ID + 一つの`H3音声N`
- `明示台詞のみ`
- `無音`

``リップシンク Context Loop``、``リップシンク Audio参照``、同じScene内の一つ以上のShot ``リップシンク 歌詞``は相互排他とする。Shotの歌詞方式は同じ方式のlist directiveとして複数行を許す。Audio参照方式の`H3音声N`はこのdirective内でだけ直接指定でき、Compilerの`required_references`へ音声slotとして追加する。Compilerは音声tensorを要求せず、接続確認もしない。

未知directive、値の個数が違う行、同一directiveの重複を文法エラーにする。`無音`は同じJSON keyへの相反する値を避けるため、同一Scene内では他の音響directive又はShotの``リップシンク 歌詞``と併記できない。これは音響内容の意味監査ではなく、直列化を一意にする最小文法である。実際の音声接続、対象人物、区間内容はCompilerが推測又は監査しない。

### 8.7 保護台詞`「...」`と明示`<d>...</d>`

Shot本文中の日本語括弧`「...」`は歌詞annotationと区別し、明示的な直接話法として扱う。Compilerは括弧内の文字列を変更せず、JSON escapeした上で`<d>[Japanese]...</d>`へ包むだけとする。

- 話者推定、source audio照合、翻訳、言換え、発話内容の評価を行わない。
- Shot本文へ直接書かれたwell-formed `<d>...</d>`は全体をopaque spanとして保護し、翻訳、言語推定、言語label追加又は二重wrapperを行わずそのままH3 promptへ写す。`<d>[English]Stay with me.</d>`のような明示言語付きも同じで、labelを検証又は変更しない。
- 一つのShot本文に複数spanを置ける。入れ子又は開始・終了tagの不整合だけを構文エラーにし、span外側の通常描写だけを翻訳する。
- 直前に概念IDがあれば通常の概念／H3 binding規則で写すが、話者として正しいかは監査しない。
- 追加発声禁止が必要なら、EMD作者又はPlannerが`## 音響`へ`明示台詞のみ`を書く。Compilerはそのときだけ固定の禁止文をprompt要素として出す。
- `歌詞`annotationはPlannerが認識するtimeline metadataである。Compilerは構文上読み飛ばして最終promptへ出力せず、`「...」`又は``リップシンク 歌詞``へ自動変換しない。
- ``リップシンク 歌詞``内の`「...」`はShot directive parserが先に取得し、通常の直接話法として二重処理しない。
- 閉じ括弧のない`「`は文法エラー。台詞内容、個数、話者、音声区間の整合性はエラー条件にしない。

### 8.8 非対応形式

本プロジェクトは新規仕様だけを実装する。旧`// 歌詞:`、`// 検出状態:`、`` `対象N` ``、`` `画像N` ``、`` `H3対象N` ``等を読み替えるparser、importer、alias又は自動変換は設けない。`<Subject N>`と`<Picture N>`は`# サブジェクト`の予約行でだけ受理し、自由文中の旧形式としては受理しない。

## 9. Compiler契約

### 9.1 処理順

CompilerはRef2VA専用のEMD parser、限定翻訳orchestrator、H3 prompt renderer、JSON serializerとする。通常入力はSTRING `emd_text`、H3 timing profile、`translation_mode`、`model_name`とruntime設定である。`translation_mode=ja_to_en`では選択GGUFを内部PromptTranslator adapterで使う。初期比較候補は4Bと8Bだが特定modelへ固定しない。Image to Subject EMD、Enhancer、Planner、IMAGE、AUDIO又はworkflow graphは要求しない。

1. EMDの`# サブジェクト`、必須Scene番号annotation、Scene、Shot、`` `H3長` ``及び予約directiveを構文解析する。
2. Subject/Picture関連、概念ID、`「...」`、明示`<d>...</d>`、annotation、音響directive、Shotの``リップシンク 歌詞``を翻訳対象から分離する。
3. `# サブジェクト`の説明、任意の`# 共通プロンプト`の四区分本文、`# 保持分析`及びShot本文だけを、区分を保持したtranslation unitとして英訳する。
4. EMD内部IDを対応する`<Subject N>`へ固定変換し、実際に記述された`<Picture N>`と`<Audio N>`だけの必要slot一覧を作る。自由描写中の`<Video N>`は翻訳保護してas-isで渡すが、V1では必要slot一覧を生成しない。
5. 各Shotの``リップシンク 歌詞``を、そのShot開始位置、対象token、原文`<d>[Japanese]...</d>`を持つ固定prompt要素へ写す。
6. 通常の`「...」`の内容を変えず`<d>[Japanese]...</d>`へ包む。
7. 明示された音響directiveだけを固定対応表でScene JSON要素と固定prompt要素へ写す。音声参照tagと歌詞原文は翻訳unitへ入れない。
8. 各Sceneの`` `H3長` ``を整数のままPlan `length`へ写す。Scene時刻からlengthを再計算、丸め又は補正しない。
9. ``> `シーン` N``を0 paddingしたPlan Scene `id`の`scene_NNNN`へ写す。
10. 任意の`# 共通プロンプト`の翻訳済みlistを`スタイル → モーション → カメラ → その他`の固定順で平坦化し、subsection見出しを除いてPlan `prompt_prefix`へ一回だけ出力する。本文がなければfieldも出力しない。
11. 各Scene固有promptを`subject_definitions`、`summary`、`retention_analysis`、`detailed_description`、`overall_soundscape`、`non_diegetic_music`の正規順で構成する。
12. 標準JSON serializerでescapeし、Ref2VA Plan JSONを返す。

六セクションはEMDに存在しない演出をLLMで補わず、次の決定規則で満たす。

- `subject_definitions`: そのSceneで使うSubjectと、存在する場合だけPicture関連を`# サブジェクト`の説明と共に固定文型へ写す。参照なしSubjectは`<Subject N> is the {TYPE} described here: ...`と定義する。
- `summary`: Scene本文の先頭記述を翻訳後そのまま一行コピーする。Scene本文がなければ先頭Shot本文をmarkerなしで一行コピーする。どちらもなければ文法エラーとする。要約文を新規生成しない。
- `retention_analysis`: `# 保持分析`の該当行を文書順で写す。明記がない場合、Picture関連のあるSubject/Pictureには接続画像をidentity referenceとして保持する固定文を、参照なしSubjectには文章で定義した同一性と属性をShot間で保持する固定文を一行だけ出す。
- `detailed_description`: Scene本文と全Shot本文を文書順で写し、Shot markerと相対時刻だけを機械付与する。
- `overall_soundscape`: 明示音響directiveの固定文を出す。音響指定がなければ`No scene-specific soundscape instruction is provided.`だけを出す。
- `non_diegetic_music`: `無音`時は`No non-diegetic music.`、それ以外は`No additional non-diegetic music is requested.`だけを出す。完成動画のsoundtrack選択はEMDから記述しない。

`summary`への一行コピーと、strict schemaのために必要な固定保持・音響文はrendererの構造化処理であり、PromptTranslatorによる補強、要約又は創作には数えない。固定文はversioned fixtureで完全一致させ、モデル出力へ委ねない。

### 9.2 翻訳境界と`as is`の定義

`as is`は「日本語をそのまま残す」ではなく、EMDの構造、情報量、文書順、Scene/Shot対応を変えないという意味で使う。H3自体が日本語を受理できる場合でも、本Compilerのtarget contractでは純粋な生成promptを英語で出力する。PromptTranslatorは日本語の描写文を英語へ翻訳するが、要約、補強、創作、並べ替え、重複除去、禁止文追加又は演出修正を行わない。

翻訳へ渡す前に保護spanを一時tokenへ置換し、翻訳後に完全一致で復元する。保護対象はH3 binding、概念ID、`「...」`、作者が明示した`<d>...</d>`、予約annotation、音響directive、Shotの``リップシンク 歌詞``である。日本語括弧の台詞と明示された歌詞方式リップシンクは英訳せず`<d>[Japanese]...</d>`にし、作者が既に書いた`<d>...</d>`はlanguage labelの有無を含めて一文字も変更しない。概念IDは自然名を生成せず、束縛又は固定英語tokenへ変換する。

`translation_mode`は`ja_to_en`を既定とし、入力本文が既に英語の場合だけ利用者が`already_english`を明示できる。自動言語判定は行わない。annotationはPlanへ出さず原文artifactに保持する。Compiler自身には翻訳品質を理由とするretry経路を置かない。

### 9.3 Context Loop出力

基準Context Loopの標準Plan shapeを使う。次は`00:00.000 --> 00:10.125`、`` `H3長` 243``の先頭Sceneについて、日本語本文を英訳し、``リップシンク Context Loop``を機械変換した例である。

```json
{
  "prompt_prefix": [
    "Render every scene as photorealistic live-action cinema with natural skin, physical fabrics, realistic moonlight, and cinematic lens depth.",
    "Use continuous grounded movement with readable weight shifts and delayed follow-through in the hair and clothing.",
    "Keep the face and full-body action readable while using parallax across the foreground, middle ground, and background."
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
        "[reference generation] A moonlit shrine approach with stone pavement and vermilion torii gates.",
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
        "Use the locked source vocal as the lip-sync timing target for <Subject 1>.",
        "",
        "non_diegetic_music:",
        "No additional non-diegetic music is requested."
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

Plan `prompt_prefix`には任意の`# 共通プロンプト`の存在する本文だけを`スタイル → モーション → カメラ → その他`の順で一回出し、`##`見出しは出さない。スタイルが存在すればその先頭本文が配列の先頭要素になり、全区分がなければfieldを出さない。各Sceneの`prompt`には完全なRef2VA六セクションを出す。Context Loop 0.6.6は実行時に`prompt_prefix`、空行二つ、Scene promptの順で機械連結する。`subject_definitions`では使用する各`<Picture N>`と`<Subject N>`をそれぞれ行頭から一回ずつ定義し、`retention_analysis`にも両方のmarkerを出す。Subject定義と保持分析は各Sceneへ決定的に再掲するが、共通プロンプト本文をScene promptへ暗黙複製しない。annotationとprovenanceは含めない。

`prompt_prefix`は文字列又は文字列配列をContext Loopが受理するが、本Compilerは編集差分を読みやすくするため文字列配列だけを出力する。Context Loopの動的`{A|B}`解決はScene promptへだけ適用され、prefixには適用されないため、本Compilerもprefixへ動的候補を生成しない。prefix変更は全Sceneの完全prompt hashを変え、異なるprefixで生成したcheckpoint revision同士は一つの出力へ混在できない。

Context Loopのstrict Ref2VA analyzerは、prefix内の通常Style文を六セクション外のerrorにはしない。一方、`detailed_description:`内で`[Shot 1]`より前に求める1～2個のStyle文をprefixだけでは充足したと判定しない。H3実出力にprefix単独で十分か、Scene側にも短いStyle文を明示するかは実装後のA/B試験項目とし、Compilerが意味推測で自動複製しない。

`# サブジェクト`に実在するPicture関連と、任意の``リップシンク Audio参照``から次の独立出力を返す。両方なければ`references`は空配列になる。

```json
{
  "schema": "MVD_REQUIRED_REFERENCES_V1",
  "references": [
    {"concept_id": "人物1", "subject_ref": "<Subject 1>", "h3_ref": "<Picture 1>", "required_input": "ref_images.ref_image_0", "purpose": "visual_identity"},
    {"concept_id": "人物1", "h3_ref": "<Audio 1>", "required_input": "ref_audios.ref_audio_0", "purpose": "lip_sync_audio_reference"}
  ]
}
```

この一覧は接続要求であり、画像又は音声の内容をCompilerが認識したという主張ではない。同じ概念が視覚参照と音声参照を持つ場合は`purpose`で区別する。

### 9.4 音響・リップシンクdirectiveの固定写像

Compilerは音響又は歌詞の意味を推測しない。EMDに書かれた予約directiveだけを次へ写す。

| EMD | Scene JSON / promptへの出力 |
|---|---|
| `## 音響`なし | Scene固有の音声keyを出さずChain Policyを継承する。六セクションを満たす固定no-op文だけを音響欄へ出す |
| ``* `リップシンク` `Context Loop` `人物1` `` | `source_reference: "off"`、`generated_continuity: "off"`、`source_audio_target: "locked"`を出し、対象tokenを通常規則で写して標準lip-sync用固定prompt要素を一つ追加。vocal、Generation Profile、任意`H3_LIP_SYNC_OPTIONS`及び最終音声Chain Policyは対応する動画生成WFの責務 |
| ``* `リップシンク` `Audio参照` `人物1` `H3音声1` `` | 対象tokenと`<Audio 1>`を固定写像し、`{TARGET} performs visible lip movements synchronized to {AUDIO_TAG}.`を一つ追加。音声slotを`required_references`へ追加 |
| Shot内の``* `リップシンク` `歌詞` `人物1` 「千年鳥居をくぐるそなたよ」`` | directive内の対象と歌詞原文を当該Shot本文へ固定追加する。先頭は`[Shot 1]`、後続は`[Shot {N}] At {START},`を使い、Sceneのannotationは参照しない |
| ``* `明示台詞のみ` `` | 明示された`<d>...</d>`以外の発声を追加しない固定prompt要素を一つ追加 |
| ``* `無音` `` | `source_reference: "off"`、`generated_continuity: "off"`、`source_audio_target: "off"`と`Complete silence. No speech, music, ambience, or sound effects.`を追加 |

`無音`は非MV利用へ残す「無音条件のJSON要素を出す」という明示フラグである。初期MVスコープではPCM gateを実装しない。CompilerはPCMを変更せず、Sceneが本当に無音になるかを検査しない。またContext Loopの`final_audio`はPlan-wide Chain Policyなので、このScene JSONだけでglobal source soundtrackを消すとは主張しない。

``リップシンク Audio参照``と``リップシンク 歌詞``は`MiniMaxH3LipSyncOptions`及び`H3_LIP_SYNC_OPTIONS`を要求しない。したがって同経路で発生する追加モデル読み込み・初期化を回避できるが、H3本体の生成負荷を軽減する保証や、現行専用経路と同じ口形精度を保証するものではない。

Audio参照動画生成WFは入力vocalを事前にファイル分割しない。Lyric Segmentationが確定した`MVD_TIMELINE_V1.scenes[].source_start_ms` / `source_end_ms`をsource timeline adapterへ渡し、実行中のSceneに対応する連続vocal sliceを一個のnative `<Audio 1>`として`ref_audios.ref_audio_0`へ接続する。歌詞annotationの有無はSceneのAudio参照directiveを出す条件、各歌詞の`start_ms` / `end_ms`は整列結果とSRTの正本、Sceneのsource境界はPCM sliceの正本として役割を分ける。同じScene内の複数歌詞segmentを別Audio slotへ分けたり、segment間や歌い出し前の無音を除去して連結したりしない。CompilerはPCMを扱わず、固定promptと必要slotだけを出す。入力sliceの時間対応が正確であることと、H3出力が音素単位で完全に同期することは別の保証である。

### 9.5 最小限の文法エラー

Compilerが停止するのは次だけとする。

- 必須`# サブジェクト`、Subject record内の`H3サブジェクト`、Scene番号annotation、Scene又は`` `H3長` ``がなく、Ref2VA EMDとしてparseできない。Picture関連の欠如だけでは停止しない。
- 存在する`# 共通プロンプト`のsubsectionが重複、空、未知又は`スタイル → モーション → カメラ → その他`の相対順に一致しない。
- Scene番号annotationが見出しの直前にない、1から連番でない、重複、欠番、逆順又は0である。
- Scene絶対範囲又はShot絶対時刻の構文・順序が壊れている。
- 予約annotation、binding、音響directive又はShotの``リップシンク 歌詞``の書式、値の個数、番号範囲が不正。
- 同一音響directiveが同じSceneで重複する。
- 複数のリップシンク駆動directiveが同じSceneにある。
- ``リップシンク 歌詞``の概念ID、開始`「`、終了`」`又は歌詞本文が欠けている。
- `無音`が同じSceneの他の音響directive又はShotの``リップシンク 歌詞``と併記されている。
- `「`が閉じていない。
- Shot本文の`<d>` tagが不整合又は入れ子になっている。
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
| 上流LLM行record欠落 | 該当する上流nodeで欠落slotだけ一回局所retryする。Compilerへretryさせない |
| 意味・表現への懸念 | 通常経路を止めない。人間の比較対象として残す |
| model load、OOM、backend障害 | 品質warningへ変換せず停止 |
| ユーザー中断 | 即時伝播し、成功cacheへ保存しない |
| audio/Plan区間への懸念 | Compilerは検査しない。必要ならPlanner又はworkflow validatorで扱う |

## 13. 最小受入条件

実モデルの前にFake backendで次を満たす。

- `MVDirectorLyricSegmentation`がLLM、Image to Subject EMD、Planner、H3実行なしでTemplate EMD、SRT、typed timelineを返せる。
- SRTは解決済みatomic segmentの本文、時刻及び順序をtimelineと一致させ、section見出しと未解決segmentを字幕本文へ入れない。Template EMDの歌詞annotation件数とSRT cue件数も一致する。
- Whisperが歌詞位置を検出し、粗い20ms VADの端をsample-domainで再探索して、有声境界を整数msで保持する。fixtureでは同じPCMから同じsample indexとmsを再現できる。
- PlannerがTemplate EMDを受けた場合、Whisperと音声解析を再実行しない。
- Fake LLMの行応答を、括弧又はJSON parserなしで`RECORD_TYPE`、短いslot、本文へ分離できる。行順が変わってもside tableで同じScene/Shotへ戻り、前置き、未知行又は重複recordがあっても他の有効recordを失わず、欠落slotだけを列挙できる。
- 空のuser requestでもdirectionが作れる。
- userの短い夜間・顔特徴指定がprovenance付きで最優先になる。
- plan Sceneが0から量子化済みplan終端まで隙間・重複なく並び、元音源尺との差を保持する。
- Template EMDと完成EMDの各Sceneが直前に連番の``> `シーン` N``を持ち、Sceneが`# シーン START --> END`、全Shotが`## ショット TIME`のplan絶対`MM:SS.mmm`で、typed timelineの整数msと完全一致する。
- Shot開始は規則どおりで、LLMが変更できない。CompilerはH3用のScene相対時刻だけを機械算出し、EMDへ書き戻さない。
- actionとcameraが同じShot IDへ合成され、互いの本文を再出力しない。
- 同じShotのactionとcameraを並行する全区間記述としてaction、cameraの順にrenderし、cameraは数値sub-time、mid-shot cut、新規Shot又はaction変更を生成しない。cutは既存Shot境界でだけ表現する。
- Plannerが7.4の全socketを公開し、`n_ctx`を含むllama.cpp調整値とmodel overrideをcache signatureへ含める。
- Direction artifact未接続でもPlannerが動作し、接続時は四方向を再分類せず読む。Enhancerのpreviewは人間が確認できるがPlannerは再parseしない。
- provenanceは入力、採用行及び機械的破棄だけを固定enumで記録し、原文、LLMの意味判断又は推測した上書き理由を含めない。
- Plannerが作者由来の`「...」`と明示`<d>...</d>`をplaceholderでLLM入力から保護し、原文をPython所有位置へ一度だけ保持する。LLM新規生成の引用台詞及びplaceholder echoを削除し、引用出現を理由にLLMをretryしない。
- annotationが原文artifactに保持され、H3 promptへ漏れない。
- `<Subject N>`と任意の`<Picture N>`は`# サブジェクト`の予約行だけに現れ、自由文へ混在しない。
- `# サブジェクト`に`<Subject N>`と任意の`<Picture N>`を持つ完全Ref2VA EMDを、画像tensorなしでもCompiler単独で処理できる。Picture関連があれば接続要求を返し、なければ参照なしH3内蔵概念として空の必要参照一覧を返す。
- Picture関連のない完全EMDもRef2VAとしてコンパイルし、T2VA等へ暗黙fallbackしない。
- Lyric SegmentationがContext Loop基準contractのraw `length`、delivered frames、Scene境界及び量子化差分を確定し、Template EMDへ`` `H3長` ``を出せる。
- CompilerはEMDの`` `H3長` ``をPlan `length`へ無変換で写し、`duration_seconds`又は未対応の`duration_ms`を併記しない。
- Compilerが出した各Scene promptを基準Context LoopのRef2VA schema analyzerへ渡すと、正規六セクション、Shot順及び時刻構文にerrorがない。
- `# 共通プロンプト`と四区分がすべて省略可能で、Compilerが存在する翻訳済み行だけをスタイル、モーション、カメラ、その他の固定順でPlan `prompt_prefix`へ入れる。スタイルがあれば先頭になり、全区分がなければfieldを出さない。
- 日本語EMDの描写文が英語へ一対一で翻訳され、情報追加・要約・並べ替えなしでPlanへ入る。
- 音響省略時はScene固有keyを出さず、`無音`がある場合だけ対応するoff値とsilence prompt要素を出す。
- `「...」`の内容を変更せず`<d>[Japanese]...</d>`へ包み、`明示台詞のみ`がある場合だけ追加発声禁止要素を出す。
- Shot本文に明示された`<d>...</d>`と`<d>[English]...</d>`を翻訳又は書換えせず、そのまま一回だけH3 promptへ出す。
- ``リップシンク Audio参照``を翻訳LLMなしで対象token、`<Audio N>`及び固定英文へ変換し、必要音声slotを返せる。
- Lyric Segmentationが同じatomic segment列からTemplate EMD、timeline、SRTを作り、歌詞annotationを割当て済みShotの直前へ配置できる。Plannerは数値包含で再対応付けせず対象付きの``リップシンク 歌詞``を生成し、Compilerはannotationを参照せず、Shot開始位置とdirective内の原文を順序どおりの`<d>[Japanese]...</d>`へ変換できる。
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
