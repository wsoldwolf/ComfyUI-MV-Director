# 最小コア仕様

版: `draft-0.34`<br>
作成日: 2026-09-16<br>
状態: 初期実装の基準。現行ノードで利用可能な構文の説明ではない。

## 1. 目的

任意の人物参照画像、任意の独立した背景参照画像、歌詞、ボーカルステム、フルミックスと、空又は短いユーザー希望から、Context Loop / H3 Ref2VAへ渡せる計画を現実的な回数のローカル推論で作る。初期の自動MV経路では一個の人物用Image to Subject EMDだけをEnhancerとPlannerへ分岐し、複数のサブジェクト断片を自動統合しない。背景画像は人物Subjectへ統合せず、計画時の環境観察と動画生成時の環境専用Pictureに分離する。Image to Subject EMD、Enhancer、Lyric Segmentation及びPlannerは個別利用できるが、本仕様のCompilerはRef2VAだけを出力する。Picture参照あり又はH3内蔵概念だけの複数Subjectを記述した完全なRef2VA EMDがあれば、Compiler単独でもPlanを作れることを必須境界とする。

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
| `MV Director - Image to Subject EMD` | IMAGE、`subject_hint`、`additional_instruction`、観察・hint・binding制御、Vision model | `MVD_EMD_FRAGMENT_V1`、`MVD_SCENE_EMD_FRAGMENT_V1`、任意の`MVD_REFERENCE_BINDINGS_V1`、IMAGE pass-through、debug observations、読み取り専用Picture表示 | subject-onlyでは人物・物体概念、scene-onlyでは環境専用Scene EMDを決定的にrenderする |
| `MV Director - Direction Enhancer` | 任意の概念EMD、任意のScene EMD、短い希望、演出profile又はDirection EMDパススルー | `MVD_DIRECTION_V3`、人間向けpreview | profile又はユーザー直書き方針から動作する。raw observationsは受けない |
| `MV Director - Timeline Planner` | 任意の概念EMD、任意のScene EMD、Template EMD、任意のdirection artifact、lip-sync mode、GGUFとllama.cpp調整値 | `MVD_EMD_V1`、EMD文字列、status | 確定済み時間枠へ概念とScene設定を構造統合し、歌詞解釈、人物動作、カメラ及び機械的なlip-sync directiveを展開する |
| `MV Director - EMD Compiler` | 完全Ref2VA EMD文字列、H3 timing profile、翻訳mode、選択GGUFとruntime設定 | Context Loop Ref2VA Plan JSON、必要参照一覧、固定artifact | EMD構造を保持し、選択したGGUFでH3 promptへ出す自由文だけを英訳してRef2VA六セクションへ直列化する |

旧Prompt Enhancer、MV Prompt Planner、Japanese to JSONのクラスや実行フローを新ノードの土台にしない。

### 2.2 補助層

- Lyric Segmentation: 歌詞とボーカルからTemplate EMD、SRT、`MVD_TIMELINE_V1`を返す公開support node。MV用TemplateではContext Loop互換のraw `length`も確定する。Planner及びH3実行なしで単独利用できる。
- audio timeline engine: 上記support node内部でVAD、Whisper一回、歌詞整列、Scene/Shot枠生成を行う純粋な層。
- GGUF backend: モデル探索、ロード、token計測、中断、解放を共通化する。
- PromptTranslator: prompt本文の日本語から英語への一方向変換だけを行う交換可能なinterface。初期実装はローカル4B又は8Bを想定するが、LLM固有の契約にはしない。
- Audio Pad Pair: full mixとvocal stemを同じ基準尺へ末尾無音補完し、明示mode時だけsource SceneをPlan frame位置へPCM無音で配置した参照専用vocalも返す公開support node。単体Audio Padは公開しない。
- H3 Timing Profile: Context Loop基準contract、24fps、anchor mode、visual/audio context lengthを一つの`MV_DIRECTOR_H3_TIMING_PROFILE`へまとめ、Lyric SegmentationとCompilerへ共有する公開utility node。
- 32-bit Seed: GGUF系とH3系へ同じ再現可能な符号付き32-bit正整数seedを分岐する公開utility node。旧実装の有限なrandom/fixed/一回保持処理だけを再利用する。
- String Combo: 文字列候補を通常の接続可能なSTRINGとして選択・出力する公開utility node。
- Connected Combo: サブグラフ内部で頻繁に変更するcomboを外側へ引き出し、接続値を選択肢として扱う公開utility node。
- Load Text File: ローカルのplain lyrics `.txt`をブラウザで選択/D&Dし、workflowへ埋め込まれたUTF-8本文をSTRINGとして返す公開utility node。
- Scene Debug Splitter: Context Loop Planの連続Scene部分列と同じdelivered-frame区間のvocal/full mixを切り出す公開utility node。無効時は三入力をそのまま返す。
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
| Scene Debug Splitter type / class | `MVDirectorSceneDebugSplitter` |
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

初期実装は、2026-09-16時点で利用するComfyUI `0.36.0`、commit `ee71d5c4993f29086b27fde1629a945ae48425bf`とContext Loop `0.6.9`、commit `9860a063784c8c23b58e00107f2180e0df3c43d9`のPlan parser、Ref2VA prompt schema、参照socket及びtiming規則を基準にする。開発中のtipへ追従し続けず、まずこの組合せに対して実装する。実装完了後に同commitとの契約テストを行い、その後の更新はadapter追加又は契約更新として別に検証する。

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
- 必須slotがそろえば、未知行、重複又は余分な行だけを理由にretryしない。必須slotが欠けた場合だけ、欠落slotを一回局所retryできる。意味、文章品質又は演出の好みは共通parserで検査しない。`translation-ja-en`だけはtask adapterが採用本文の日本語script残存又はslot番号echoを決定論的に検査し、該当slotを一度だけ隔離再翻訳できる。
- Planner task adapterはstrict parserの後に限り、`TYPE slot: TEXT`等の明示slot wrapperを正規recordへ戻せる。複数の未解決slotに対して非空物理行数が完全一致する場合は、request side table順の位置対応も許す。いずれもrecord type、slot、Markdown bullet等の構造wrapperだけを除去し、`TEXT`本文を変更しない。単一の無番号行、余分な説明行、空行を除く行数不一致又は曖昧な対応は推測しない。復元数を`protocol_recovered_count`へ記録する。
- 明示debug時はraw応答、採用record、拒否行と理由、slot side table及び欠落slotを保存する。raw応答を成功artifact又はEMDへ混入させない。

初期typeは次へ限定する。

| task | `RECORD_TYPE` | slotの意味 | 必須数 |
|---|---|---|---:|
| Enhancer | `STYLE` / `MOTION` / `CAMERA` | 各区分内の項目番号 | 非passthrough区分ごとに1 |
| Enhancer | `ENVIRONMENT` / `TIME_LIGHTING` / `OTHER` | 各任意区分の項目番号 | 0又は1 |
| `visual-beats` | `BEAT` | request side table上のScene番号 | 対象Sceneごとに1 |
| `song-direction` | `DIRECTION` | 常に1 | 1（補助文脈。限定再試行後も欠落なら警告付き空文脈へ縮退） |
| `shot-layout` | `LAYOUT` | request side table上のScene番号 | 対象Sceneごとに1 |
| `actions` | `ACTION` | request side table上のShot番号 | 対象Shotごとに1 |
| `cameras` | `CAMERA` | request side table上のShot番号 | 対象Shotごとに1 |

例えば二つのShotのaction応答は次だけでよい。

```text
ACTION<TAB>1<TAB>人物は足を踏み出し、袖を後方へ流しながら鳥居へ手を伸ばす。
ACTION<TAB>2<TAB>人物は立ち止まり、上げた手を胸元へ静かに戻す。
```

表示上の`<TAB>`は実際のU+0009 TAB一文字を表す。上例のslot `1`と`2`をどのShotへ入れるかはPythonだけが知る。旧実装の行指向という考え方は再利用するが、`SONG_BIBLE` / `END_*`及び入れ子blockは移植しない。例外として`anime_emotional_mv`のActionには、有限理由codeだけを返す独立した意味監査を設け、rejectされたslotをAction生成taskへ戻す。監査自身は自然文を修復又は生成しない。

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

組み込みの初期セットは次の通りとする。本文はPython定数へ埋め込まず、repository直下の`profiles/style/*.md`、`profiles/motion/*.md`、`profiles/camera/*.md`からUTF-8 EMDとして起動時に読み込む。拡張子を除く小文字英数字・underscoreのファイル名をprofile IDとし、`passthrough`は予約する。各文書は`# 共通プロンプト`と種別に一致する一つの`## スタイル`、`## モーション`又は`## カメラ`を持ち、一個以上のlist itemを文書順に空白一個で結合してprofile本文とする。別section、空item、code fence、NUL、未知metadata及びディレクトリとsubsectionの不一致は起動時エラーとする。ファイル変更はComfyUI再起動後に反映する。

Style、Motion、Camera文書は`# 共通プロンプト`の前に任意の`# プロファイル`を持てる。Styleは``locked true|false``、``retention TEXT``、``scene_reinforcement TEXT``、Motionは``performance_mode event_based|dance_phrase``、``body_accent_policy off|sparse_chorus``、``choreography_policy off|scene_choice|scene_palette``と``render_prompt TEXT``、Cameraは``planner_policy POLICY_ID``、``lyric_cue_mode MODE``、``lyric_interpretation MODE``と``render_prompt TEXT``などの種別に応じたmetadataを持つ。`retention`は`` `fully_preserved` ``又は`` `partially_preserved` ``から始める。metadataはUI socketを増やさず、実装済みのPlanner構造最適化をprofile選択と同時に切り替える。生成済み自然文の意味的な置換又は修復には使わない。

Cameraの追加metadata ``arc_roll_policy off|selective_arc`` は有限Camera計画のArc＋Rollを切り替える。`selective_arc`は`planner_policy=anime_emotional_mv`を必要とし、Planner cache keyへ含める。

| 軸 | profile | H3へ伝える肯定的な核 |
|---|---|---|
| 画風 | `reference_anime`（既定） | 参照画像の顔・体格・衣装・配色を同じ設計で保ち、整理された線、明瞭な色面、セル影、繊細な光で手描き2Dアニメとして描く |
| 画風 | `anime_story_mv` | 現在は`anime_emotional_mv`と同一内容の比較用基準。識別要素だけを保持し、感情を伴うセルアニメの身体演技へ再構成する |
| 画風 | `anime_emotional_mv` | `anime_story_mv`の単一画面、非発光素材、参照構図非継承及び無傷の人物契約を維持し、感情を伴う身体演技を主題として再構成する |
| 画風 | `reference_cinematic` | 参照画像の人物設計を保ち、自然な皮膚・布・材質、映画照明、レンズによる奥行きで実写映画として描く |
| 画風 | `illust_to_photoreal` | 2026-09-16 20:30に実写風生成へ成功した保存Planの長い英語anchorを`prompt_prefix`先頭へ完全一致で置き、各Scene先頭Shotにも成功時の短い実写文を明示する。保持分析も同Planの識別要素範囲を使う |
| 画風 | `reference_painterly` | 参照画像の形と配色を保ち、紙目、透明な色層、柔らかな境界を持つ手描き絵画として描く |
| 動作 | `natural_performance`（既定） | 歌詞と音の強弱へ反応する全身動作を、接地、重心、手と対象の接触、髪と衣装の追従が読める連続動作として描く |
| 動作 | `expressive_mv` | 静かな区間は小さな重心と手の動き、強い区間は踏み込み、胴体のひねり、腕の広い軌道へ変化させる |
| 動作 | `limited_animation` | 大きく読めるキーポーズとポーズ間の移行を使い、身体と口形のタイミングを別々に保つ |
| 動作 | `cinema_mv` | 従来のセルアニメ2コマ・3コマ打ち、短いポーズ保持、ポーズ・トゥ・ポーズ及び自然な収束を使う穏やかな映画的MV演技 |
| 動作 | `anime_story_mv` | `dance_phrase`の比較用基準。Motion本文は`anime_emotional_mv`と同じだが、`body_accent_policy=off`のため従来の上半身role割当を保つ |
| 動作 | `anime_emotional_mv` | 開発用。`dance_phrase`に`body_accent_policy=sparse_chorus`を重ね、サビ／最終サビの適格なSceneで最大一Shotに支持脚・骨盤・体幹・腕の連動した身体accentを要求する。その他のShotは元のroleを保つ。現在Sceneの元歌詞又は作者指示だけで対象を活性化し、外部effectは人物から独立させる |
| カメラ | `readable_depth`（既定） | 顔、全身動作、接触点を読める距離を保ち、安定した構図、緩やかな接近・後退・横移動を使い分ける |
| カメラ | `cinematic_depth` | 開始視点、被写体の側面を通る経路、終了視点、前景・中景・遠景の視差を明示する |
| カメラ | `rhythmic_mv` | 楽曲強度に合わせて移動量と構図保持を変え、Scene間で角度、高さ、距離、移動方向を展開する |
| カメラ | `cinema_mv` | 従来の穏やかな映画的camera設計を保持し、Shot目的に必要な時だけarc又はclose-upを選ぶ |
| カメラ | `anime_story_mv` | 現在は`anime_emotional_mv`と同一内容で、metadataも`planner_policy=anime_emotional_mv`。Camera選択時のPlanner構造契約はemotionalと同じ |
| カメラ | `anime_emotional_mv` | 2.5秒以上の適格な非顔slotのおよそ半数を`Arc Shot with large amplitude at fast speed`で始まる60～120度かつShot尺70～90%の長尺Arc候補とし、未割当slotではArcを禁止する。顔Zoomはbatchごとではなく曲全体の疎な予算と既存section face cutで選び、35～55%で顔へ到達して短い表情accentだけを保持する。同一Scene内でArcから顔へ入る又は顔からArcで空間へ抜ける連続phraseを作り、後続Sceneの少なくとも4分の3をCONTINUE可能にし、すべてCONTINUEも許す |

「禁止リストを増やす」のではなく、実現したい材質、形、動き、軌道を記述する。ただしユーザー自身が否定条件を指定した場合は削除しない。

DirectionはPlannerの全LLM task及び完成Planの全Scene `prompt_prefix`へ共通適用される。特定の衣装部品、身体部位又は小物の局所形状は共通Directionへ置かず、参照画像、Subject定義、保持分析又は対象Shotだけの作者本文で所有する。局所形状をStyle、Motion又はCamera profileへ置いて全Shotへ反復し、その部品を演技又はdetail構図の主題へ昇格させてはならない。

STYLE recordは必ず目標medium又はrendering treatmentから書き始める。`illust_to_photoreal`と`anime_story_mv`はlocked STYLE profileとし、Direction EnhancerはSTYLEをLLMへ要求せず、選択profileの固定anchorを機械的に`style_direction[0]`へ設定して`profile_enforced`をprovenanceへ残す。`reference_anime`と`reference_cinematic`は通常profileとしてLLMが統合する。Motion及びCameraも選択profile本文が対応typed fieldを機械的に所有し、MOTION/CAMERA record自体をLLMへ要求しない。ユーザー本文を直接所有させる場合だけ対応profileを`passthrough`にする。

locked集合、profile保持分析及びScene reinforcementもStyle EMD metadataから構築し、別のPython対応表を正本にしない。profile本文とmetadataはDirection cache keyへ入るpayload及びDirection artifactへ反映される。

最初の比較presetは次の3個に限定する。

- `anime_emotional`: `anime_emotional_mv` + `anime_emotional_mv` + `anime_emotional_mv`
- `cinematic_anime_story_mv`: `anime_story_mv` + `anime_story_mv` + `anime_story_mv`
- `cinema_mv`: `anime_story_mv` + `cinema_mv` + `cinema_mv`
- `cinematic_performance`: `reference_cinematic` + `natural_performance` + `readable_depth`
- `painterly_mv`: `reference_painterly` + `natural_performance` + `cinematic_depth`

### 4.2 初期model execution profile

初期実装は次の二つを比較する。model profileは演出を変更せず、contextと実行容量だけを制御する。

- `local_8b_16k`: Enhancer / Plannerの基準。`n_ctx=16384`。
- `local_4b_32k`: Enhancer / Planner / Compilerの8GB VRAM向け試験基準。`n_ctx=32768`、`kv_cache_type=q8_0`、`flash_attn=true`、`keep_model_loaded=false`。

- 実効context上限は`min(backend effective_n_ctx, 16384)`。
- visual beat、action及びcameraは`scenes_per_batch`（既定3、最大6）ごとにpackする。shot layoutは短い候補IDだけを扱うため全Sceneを一要求へまとめる。
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
  "contract": "context-loop-0.6.9@9860a063784c8c23b58e00107f2180e0df3c43d9",
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

- `image`: Visionで観察する一枚のIMAGE、又は同一人物の立ち絵・顔・側面・背面を収めた最大9枚のIMAGE batch。batchはラベル付きcontact sheetへ決定論的に合成して一回で観察する。
- `subject_hint`: 名前、画面外の重要特徴、保持したい特徴を補う任意のSTRING socket。
- `additional_instruction`: 「眉の形と尾の本数を重点的に確認」のように、観測箇所を指定する任意のSTRING socket。
- `analysis_profile`: `general`（既定）、`subject_only`、`scene_only`を選ぶ外部接続可能な制御socket。
- `hint_mode`: `observe_only`、`assist`、`lock_identity`（既定）を選ぶ外部接続可能な制御socket。
- `hint_conflict`: `warn`（既定）、`strict`を選ぶ外部接続可能な制御socket。
- `picture_reference_mode`: `auto_h3`（既定）、`manual`、`none`を選ぶ外部接続可能な制御socket。
- `concept_type`: EMD内部IDの`person`、`location`、`object`を選ぶ外部接続可能なsocket。
- `picture_index`: `manual`時だけ物理入力`<Picture N>`へ使う1～9の外部接続可能な整数socket。
- Vision model、projector、seed、生成設定。

旧ノードには上記のほか、画像選択、`image_override`、`cache_mode`、`picture_reference_mode`、`picture_index`、`subject_index`、`analysis_max_edge`とGGUF runtime設定があった。新ノードでは外部IMAGEを`image`へ統一する。EMD Subject番号はfragment内の行順から導出するため、`concept_index`又は`subject_index` socketを公開しない。`cache_mode`、解析解像度、model/runtime設定は外部接続可能にする。

旧`analysis_profile`の`planner_brief`はprimary出力が直接EMD fragmentになったため不要であり、`structured_json`は常時返す`observations_json`へ統合する。旧出力形式を選ぶための二値は新profileへ残さない。

全ての公開入力はworkflow外部から接続可能とする。ローカルwidgetも表示する項目では、接続socketの値を優先する。未接続時だけwidget既定値を使う。

`subject_hint`と`additional_instruction`は日本語の自然文をそのまま受けるデータ欄であり、見出し、名前付きプレフィクス、JSON又はMarkdown directiveを要求しない。例えば`淡い金色の短い丸眉で、狐の尾は一本です。`だけで有効とする。`subject_hint:`等を検出・除去する互換処理は実装せず、socketへ渡された文字列全体を入力本文として扱う。

`subject_hint`は人物設定のauthority、`additional_instruction`は観察の焦点であり、後者を「画像に存在する事実」へ昇格させない。入力原文と正規化後文字列をartifactへ分けて保持し、semantic keyword parserで特徴へ分解しない。

人物の設定画、turnaround又はcontact sheetでは、明らかに異なる人物が描かれていない限り、全身、顔アップ、側面及び背面を同じ一意の`PRIMARY_SUBJECT`の複数ビューとして統合する。繰り返し描画、panel境界、view label、guide線又は中立poseを別Subjectや恒常特徴として数えない。各ビューで見える互換な特徴は統合するが、遮蔽箇所を推測補完しない。IMAGE batchは1～9枚だけを許し、全viewのpixelと順序をfingerprint及びcache keyへ含める。

- `observe_only`: `subject_hint`をVision要求又はEMDへ適用せず、入力原文artifactにだけ保持する。
- `assist`: ヒントを画像解釈の仮説として渡すが、可視事実を置換せず、確定した人物設定としては出力しない。
- `lock_identity`: ヒントを`user_hint` provenanceの人物設定としてEMDへ保持する。画像観察由来とは表示しない。
- `hint_conflict=warn`: 明瞭な画像証拠との相違をstatusへ記録して続行する。
- `hint_conflict=strict`: 明瞭な画像証拠との相違が返された場合だけ停止する。曖昧又は不可視をconflictとみなさない。

### 5.2 Vision観測protocol

旧`cl-vision-observation-line-v2`の実績あるrecord構成を、新名前空間`MVD_VISION_OBSERVATION_LINES_V2`として引き継ぐ。Vision modelへJSON、Markdown、EMD、`<Picture N>`又は`<Subject N>`を生成させない。正規応答は次の順序固定TAB区切り行とする。受信側は小規模Vision modelの非決定的な順序入替えに対して、既知の名前付きrecordだけを正規順へ並べ直してから検証してよい。未知recordは推測せず拒否し、単値recordの重複は最初の非空値を決定論的に採用してwarningを残す。

```text
MVD_VISION_OBSERVATION_LINES_V2
OVERVIEW\t日本語の概要
PRIMARY_SUBJECT\t日本語の単数名詞句又は空
HINT_STATUS\tnot_used|consistent|ambiguous|conflict
HINT_REASON\t日本語の根拠又は空
SUBJECT_FEATURE\tface|hair|eyes|eyebrows|ears|body|clothing|footwear|accessory|tail|distinctive_feature\t日本語の可視特徴
SUBJECT_POSE\t日本語の姿勢又は空
SCENE_SETTING\t日本語の場所・環境又は空
SCENE_ELEMENT\t日本語の背景要素
LIGHTING\t日本語の照明又は空
TIME_WEATHER\t日本語の時間帯・天候又は空
SHOT_SIZE\t日本語値又は空
VIEWPOINT\t日本語値又は空
SUBJECT_PLACEMENT\t日本語値又は空
DEPTH\t日本語値又は空
STYLE_MEDIUM\t日本語値又は空
STYLE_RENDERING\t日本語値又は空
STYLE_PALETTE\t日本語値又は空
VISIBLE_TEXT\t画像内で実際に読めた文字
UNCERTAINTY\t確認できない事項
END_MVD_VISION_OBSERVATION
```

`SUBJECT_FEATURE`、`SCENE_ELEMENT`、`VISIBLE_TEXT`、`UNCERTAINTY`は0件以上である。任意反復recordは該当内容がなければ行自体を省略する。Vision modelが`SCENE_ELEMENT`、`VISIBLE_TEXT`又は`UNCERTAINTY`を空値で一行だけ出した場合は、情報を捏造せずその行を機械的に省略してwarningへ記録する。`SUBJECT_FEATURE`の空値は受理しない。`OVERVIEW`及び`HINT_STATUS`は必須である。それ以外の「値又は空」と定義された単値recordは、行自体が欠落しても空文字へ機械復元しwarningへ記録する。同一category反復を許す。履物は`footwear`を使い、それ以外の人体分類に当てはまらない物品の形、色、数、材質、模様又は状態は`distinctive_feature`を使う。小型modelが未知categoryを生成した場合は観測本文を失わないよう`distinctive_feature`へ収容しwarningを残す。4B modelが説明文とenumの列順を反転させることを避けるため、model出力ではvisibility列を要求せず、Pythonが保守的な`partial`を割り当てる。明示visibilityを含む内部fixtureは`clear`、`partial`、`uncertain`の三値だけを受理する。modelが`SUBJECT_FEATURE<TAB>本文`だけを返した場合は、本文を変更せずcategoryを`distinctive_feature`、visibilityを`partial`としてwarning付きで受理する。categoryだけで本文がない行は受理しない。

Python parserは旧実装から、CRLF正規化、空値`SUBJECT_POSE`、`visible`から`clear`、visibility欠落時の保守的`partial`、自然文中へ混入した追加TAB断片の順序保持結合、終端marker欠落warningを再利用する。最初のrecordが正規の`OVERVIEW`、`Overview: value` / `OVERVIEW: value`又は`PRIMARY_SUBJECT`である場合だけprotocol ID欠落を決定論的に補う。4B modelで実測したcolon形式だけを`OVERVIEW<TAB>value`へ正規化する。modelがJSON風schema名として出す`protocol_id`は位置、区切り又はpayloadにかかわらずtransport metadataとして除外し、観測recordとして解釈しない。protocol ID直後が`PRIMARY_SUBJECT`である場合に限り、欠落した`OVERVIEW`をそのSubject名と固定句「の参照画像。」から機械生成してwarningへ記録する。既知record名はASCIIの大文字小文字を無視し、空白又はhyphenをunderscoreへ正規化したうえで正規順へ並べる。未知`SUBJECT_FEATURE` categoryは本文を保持して`distinctive_feature`へ収容する一方、未知enum、その他のunknown record、code fence、参照tag、NUL又は必須`HINT_STATUS`欠落は推測修復せず停止する。画像なしLLM修復、英日翻訳repair、無制限の再観測retry及び旧`subject_hint:`互換正規化は移植しない。許可する再試行は、同じ画像と設定を使い出力形式だけを強制する一回に限る。

検証済みrecordからPythonが`MVD_OBSERVATIONS_V1`を構築し、`observations_json`を生成する。旧構造の`overview`、`primary_subject`、`hint_assessment`、`scene`、`composition`、`style`、`visible_text`、`uncertainties`を維持するが、schema IDとprotocol IDは新名称だけを使う。生model応答をJSONとしてparseしない。

新EMD rendererは旧Markdown rendererを使用しない。`person`又は`object`ではidentityと`clear`／`partial`の可視特徴、`location`ではscene settingとscene elementsを主に`# サブジェクト`へ写す。`uncertain`特徴はEMDの確定条件へ入れずstatusと`observations_json`へ残す。pose、composition、source medium/style、visible textは参照画像固有の状態として観測artifactへ保持するが、Subjectの恒常条件又は目標画風としてEMDへ自動転記しない。

`picture_reference_mode=auto_h3`ではComfyUIのhidden `PROMPT`と`UNIQUE_ID`を読み、自ノードのIMAGE pass-through出力が接続された、基準Context Loop adapterで認識できるH3 Ref2VA画像入力を探す。`ref_image_0`を`<Picture 1>`、`ref_image_8`を`<Picture 9>`として解決する。nested `ref_images.ref_image_N`も同じ規則で扱う。同じPicture番号への複数分岐は許可し、異なる番号へ同時分岐した場合は勝手に一つを選ばず曖昧エラーにする。認識対象は同一IMAGEの直接linkとComfyUIが実行promptで解決済みのrerouteに限り、画像加工nodeを越えたtensorを同一画像とはみなさない。

`manual`は`picture_index`を使い、グラフを調べない。`none`は画像を観察資料としてだけ使い、`<Picture N>`関連を出さない。`auto_h3`で対応H3入力が見つからない場合も観察は成功させ、bindingを`unbound`として返す。解決したH3 node ID、class type、input名、Picture番号をbinding fingerprintとComfyUIの`IS_CHANGED`へ含め、配線だけを変更した場合に古いEMD断片を再利用しない。

ノード内には`resolved_picture_reference`という読み取り専用の一行表示を置く。解決成功時は`<Picture N>`、未接続時は`unbound`、異なる番号への複数分岐時は`ambiguous`を表示する。これは編集可能な入力widget又は下流socketではなく、直近のgraph解決結果を確認するためのUIである。表示値をbindingの根拠にはせず、backendがhidden graphから得た結果を正とする。

Visionのuser message先頭には`/no_think`を付け、推論過程を本文へ出さない。modelがそれでも先頭へ閉じた`<think>...</think>`を一ブロック出した場合だけ、parserが機械的に除去してwarningへ記録する。正規protocol ID後に、値なしの`protocol_id`又は値が正規protocol IDだけの`protocol_id` recordが重複した場合は、意味情報を持たないmodel由来の書式ラベルとして除去しwarningへ記録する。それ以外のpayloadを持つ`protocol_id`は未知recordとして拒否する。protocol ID直後の一行がrecord名なしの値で、次行が`PRIMARY_SUBJECT`ならその値を`OVERVIEW`、次行が`HINT_STATUS`ならその値を`PRIMARY_SUBJECT`としてlabel付けする。この二形以外の裸値又は説明文は意味推測しない。初回応答がprotocol不正の場合は、同じ画像へprotocol ID、物理改行及びASCII record名を省略しないformat-only retryを一度だけ行う。初回の圧縮TAB列を位置推測で観測artifactへ変換せず、二回目も不正なら両方のエラーを保持して停止する。

Visionのnative log抑制はMTMDのlog callbackで行い、ComfyUI process全体のstdout又はstderr file descriptorを差し替えない。MTMDのwarning及びerrorはstderrへ残し、tokenize等のinfo/debugだけを抑制する。

`HINT_STATUS`が`consistent`、`ambiguous`又は`conflict`で`HINT_REASON`だけが空の場合、status自体は保持し、理由を捏造せずwarningとして受理する。この診断理由の欠落だけをformat retry条件にしない。`not_used`では引き続き理由を空に限定する。

### 5.3 出力

- `emd_fragment`: 通常のSTRINGでも保存・編集できるprofile依存のEMD断片。`general`又は`subject_only`では`MVD_EMD_FRAGMENT_V1`として`# サブジェクト`と一つのSubject行を持ち、binding成功時はdescriptionの前へ``画像N``を書く。`scene_only`では`MVD_SCENE_EMD_FRAGMENT_V1`として`# シーン設定`、環境、任意の時間・照明baseline及び環境専用Pictureだけを持つ。完全EMDへ組み込まれた位置からSubject番号を導出する。
- `reference_bindings`: optional `MV_DIRECTOR_REFERENCE_BINDINGS`。`MVD_REFERENCE_BINDINGS_V1`としてserializeでき、概念ID、`subject_ref`、`picture_ref`、接続先signature、入力image fingerprintを持つ。
- `image`: H3へ分岐できる、入力と同一のIMAGE tensor。modeにかかわらず常にpass-throughする。
- `observations_json`: 可視事実、uncertainty、provenanceを持つdebug/再利用用出力。下流必須にしない。

旧`scene_emd`出力socketは設けない。背景Visionの`emd_fragment`をDirection EnhancerとTimeline Plannerの`scene_emd`入力へ分岐する。

`resolved_picture_reference`は上記出力socketへ加えず、frontendの読み取り専用表示として返す。workflowを開いただけでは古い表示を確定値とみなさず、配線変更後の次回実行で更新する。

Image to Subject EMDはScene、Shot、歌詞、音響、カメラ又は物語展開を生成しない。person/objectでは見える形、色、数、衣装、材質及び状態、locationでは見える場所と構成要素だけをサブジェクト定義へし、名前、履歴又は画面外を推測しない。画像固有のpose、構図、照明及びsource styleは観測には残すがSubjectの恒常条件へ自動追加しない。`subject_hint`は`user_hint` provenanceを持つauthorityとして保持するが、画像で見えた事実とは偽らない。`lock_identity`ではrendererがhint原文を一度だけ保持し、Visionはhintにない追加の可視識別factだけを一record一事実で`SUBJECT_FEATURE`へ出す。hintの事実を要約、言い換え、翻訳又は詳述して再掲せず、助詞を省いた短縮tag、同義表現又はhint文から分割した断片も同一factとして再掲しない。追加factは対象部位、衣装、装飾又は材質を本文内で明記した自己完結する自然な日本語とし、参照先をhint又は別recordに依存する形容断片を出さない。locked factと新規factが混ざる候補は新規factだけへ分離する。hintが可視identityを網羅する場合は`SUBJECT_FEATURE`を0件にでき、重複候補を出すより0件を優先する。Pythonは自然言語の類似度でhint又はfeatureを書き換えない。`additional_instruction`は観察対象を絞るだけで、設定値として本文へ自動追加しない。

### 5.4 bindingなしの単独利用

- Image to Subject EMD自体を接続しない上流編集経路を正式にサポートする。
- `picture_reference_mode=none`又は`auto_h3`の`unbound`は、観察・EMD断片出力として正常である。
- bindingの追加・除去で観察本文やScene演出を再生成する必要はない。
- 本仕様のCompilerはRef2VA専用だが、`<Picture N>`関連のない完全EMDも文章定義だけのH3内蔵概念として受理する。T2VAへfallbackしない。

## 6. Enhancer契約

### 6.1 入力

`retention_policy`はDirection Enhancerの先頭widgetとして表示し、保持方針をprofile選択や自由記述より前に確認できるようにする。

- `concept_emd`: 一個のImage to Subject EMD出力又は手書きの一個のEMDサブジェクト断片。未接続でもよい。複数socket、可変list又は内部mergeは設けない。
- `scene_emd`: scene-only Vision出力又は手書きの一個の`# シーン設定`断片。未接続でもよい。raw `observations_json`はEnhancer入力にしない。
- `user_request`: 空又は自由な短文。見出しや定型文を要求しない。
- `style_profile`、`motion_profile`、`camera_profile`
- `retention_policy`: `profile` / `compiler_default` / `passthrough`
- `direction_emd_passthrough`: 外部マルチラインSTRING。`# 保持分析`と`# 共通プロンプト`だけを持つ任意断片
- `model_name`、`seed`、生成設定

概念EMDがなくてもuser requestとprofileからdirectionを作れる。ユーザーが「丸く短い金色の眉」のような重要特徴を明示した場合、その条件をVision由来概念より優先する。

初期の自動MV workflowでは、一個のImage to Subject EMDの`emd_fragment`をEnhancerとPlannerの単一`concept_emd`へ分岐する。複数参照を使う場合は完全EMDを手書き又は外部で構成し、Compiler単独経路へ渡す。Enhancerはサブジェクト断片を結合しない。

### 6.2 出力

`MVD_DIRECTION_V3`はPythonが行recordと機械的パススルーを合成して構築する内部artifactである。LLMへこのJSONを生成させず、Enhancerは同じ内容を人間が確認できる`direction_emd_preview` STRINGも返す。Plannerはartifact socketを直接受け取り、preview文字列を再parseしない。少なくとも次を持つ。

```json
{
  "schema": "MVD_DIRECTION_V3",
  "style_direction": [],
  "environment_direction": [],
  "time_lighting_direction": [],
  "motion_direction": [],
  "camera_direction": [],
  "other_direction": [],
  "style_profile_id": "reference_anime",
  "motion_profile_id": "natural_performance",
  "camera_profile_id": "readable_depth",
  "retention_policy": "compiler_default",
  "retention_lines": [],
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

`style_direction`、`environment_direction`、`time_lighting_direction`、`motion_direction`、`camera_direction`、`other_direction`は、それぞれ完成EMDの`## スタイル`、`## 環境`、`## 時間・照明`、`## モーション`、`## カメラ`、`## その他`へ入る。各profile comboの`passthrough`は対応する断片subsectionを文字列のまま所有し、その区分をLLMへ生成させない。断片に書いた未選択区分や、`retention_policy=passthrough`ではない保持分析は黙って捨てず入力エラーにする。スタイル・モーション・カメラの三区分すべてが`passthrough`ならGGUF探索、ロード、初期化、推論を行わない。ユーザーが`## 時間・照明`へ夜間等を明記した場合、Vision由来の昼間観察より優先する。

保持分析は演出profileから独立して選べる。`profile`は選択styleの機械policyを使い、`illust_to_photoreal`だけが各Subjectへ``partially_preserved``を生成する。`compiler_default`はEnhancer/Plannerから`# 保持分析`を出さず、Compilerの既定``fully_preserved``に委ねる。`passthrough`は外部断片の保持recordを完全一致でPlannerへ渡す。明示行は固定modeと説明を分離し、Compilerはmodeを翻訳せず説明だけを翻訳する。

`illust_to_photoreal`を`retention_policy=profile`で使う場合、Planner rendererは完成EMDへ各Subjectの明示的な`# 保持分析`を追加し、固定modeを``partially_preserved``、説明を保存Planと同じ髪型、髪色、瞳色、衣装、配色及び装飾品の維持と物理的実写表現への具現化とする。Styleは共通プロンプト先頭の保存済み長文を一回置き、各Scene最初のShotへ成功時の短い実写文を一回明示する。`reference_cinematic`を含む他profileには自動保持policyを適用しない。

provenance recordのfieldと値域は固定する。`record_id`はPythonが文書順に決定し、入力を`src_NNNN`、採用出力を`out_<section>_NNNN`、機械的に破棄したLLM行を`drop_NNNN`とする。`record_kind`は`input` / `output` / `discard`、`source`は`user` / `vision` / `profile` / `generated`、`source_ref`はsocket名、profile ID又は行protocol slot、`source_position`は0始まりの入力item又は応答行番号とする。`target`は採用output配列位置だけに設定する。機械的パススルーは`passthrough_enforced`、locked profileは`profile_enforced` / `profile_overridden`として記録する。本文は複製せずSHA-256だけを置く。

意味上「どの入力語句を採用、上書き又は破棄したか」はLLMの内部判断であり、Pythonが文字列類似度から推測せず、LLMにも説明を生成させない。`superseded`や`higher_authority`という処分理由はV1 provenanceへ設けない。authority順はEnhancer promptの入力契約であり、provenanceはその遵守を証明するsemantic auditではない。

`concept_emd`が未接続又は空文字列で、`user_request`も空であっても正常入力とする。Enhancerは選択済みの既定profileから基準directionを生成できなければならず、利用者記述のpromptを動作条件にしない。Plannerではdirection artifactも任意であり、未接続時は六方向を空として歌詞由来の局所計画を続行する。PlannerとCompilerのparserはsubsection見出しを境界として扱い、本文を正規表現又はキーワード辞書で再分類しない。

Direction EnhancerはVision artifact全体をLLMへ再送しない。厳格にparseした`scene_emd`から環境、時間・照明baseline及び背景Pictureだけを`scene_context`へ渡す。pose、shot size、viewpoint、subject placement、depth、source style及びpanel構図はScene EMD文法に存在せず、参照設定画のポーズ又は構図が`OTHER`へ昇格して全Sceneで反復されることを防ぐ。ユーザーのDirection又はpass-throughで明示した環境、時刻及び照明は観測baselineより上位である。`OTHER`は必要に応じて歌詞転換で選択的に使う物語モチーフ又は環境効果を定義できるが、同じモチーフを全Sceneへ強制せず、人物の身体特徴自体を発光体にしない。

### 6.3 実行規則

- 一回のLLM統合では未固定`STYLE`と、必要な`ENVIRONMENT`、`TIME_LIGHTING`、`OTHER`だけを出力する。locked STYLE及び選択Motion/Camera profileはPythonが外部EMD本文を直接採用し、LLM出力条件にしない。必須の未固定STYLE欠落だけ同じ対象を一回再生成できる。
- Qwen3-4Bには`/no_think`を明示する。Direction Enhancerに限り、独立したthink tag、TABで一行へ連結された既知record、及び各typeを1、2、3と連番にした正のslotをparser前に決定論的に正規化する。四typeはすべてslot 1だけを持つためslotは1へ戻す。共通行parser、Planner及びCompilerのslot検証は緩和しない。
- Direction Enhancerでは意味監査、別LLMによる採点、自動意味修復を行わない。Timeline Plannerの`anime_emotional_mv` Action分類監査は7.5の限定例外である。
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
- `status`: 完了可否、解決数、未解決数、尺、cache及び停止理由。

`srt_time_offset_ms`は外部字幕調整用で、`srt_text`だけへ適用する。`template_emd`と`timeline`の元音源時刻は変更しない。未解決歌詞へ推測時刻を作らず、内部診断artifactの`unplaced_lyrics`とstatusへ残す。一件でも未解決なら`complete=no; reason=unplaced_lyrics`として赤いERRORログを出し、公開するTemplate EMD、SRT及びtimelineの三出力を`ExecutionBlocker`で停止する。不完全な結果を成功cacheへ保存しない。

Template EMDはPlannerの標準入力である。Plannerはこの文字列のannotationと確定枠を読み、内容を補完して`MVD_EMD_V1`を作る。Template EMDを受けた場合はWhisperを再実行しない。Template単体は演出本文が未完成なのでCompilerの完成EMD入力とはみなさない。

#### 7.1.1 plain lyrics入力文法

入力は次のような`.txt`由来のplain lyricsだけを扱う。

```text
[VERSE1]
ほげほげ ふがふが

[VERSE2]
...
```

- 最初の非空行はsection見出しとする。見出しはASCII英字で始まる名前を角括弧で囲み、角括弧の内側では前後空白及び名前中のASCII空白、tab又は全角空白を許す。行自体の角括弧外に前後空白は許さない。大文字小文字は区別せず、内部では大文字へ正規化し、名前中の空白runは`_`へ変換する。
- `[VERSE1]`、`[ Chorus ]`、`[Verse 1]`、`[bridge_A]`等を使用できる。`[Verse 1]`は`VERSE_1`となる。未知名と同名sectionの再登場を許し、出現順を保持して自動統合しない。
- 空行は読みやすさのための区切りとして無視する。空sectionも許可する。
- section外の歌詞本文、comment構文、LRC timestamp、SRT番号・時刻行、inline metadataは受理しない。
- 通常の歌詞行は原文を保持したまま、ASCII空白、tab又は全角空白の一個以上のrunでatomic segmentへ分ける。連続空白から空segmentを作らない。
- section見出しと区切り空白はSRT本文へ出さない。句読点、長音、括弧その他の歌詞文字はsegment本文として変更しない。
- `lyrics_text`は通常STRINGなので直接入力もできるが、由来ファイルにかかわらず同じ文法を適用する。拡張子ではなく本文をparserの正とする。

初期版は日本語歌詞を対象に空白を明示的なphrase境界として扱う。英語等、通常の単語間空白を持つ歌詞はこの文法の対象外とし、暗黙のlanguage別推測を行わない。

### 7.2 音声・歌詞時間解析

初期方式を次で固定する。

1. 歌詞本文の物理改行をhard boundaryとし、各行をASCII空白、tab又は全角空白の一個以上のrunでも分割する。空白run自体は区切りであり、segment本文へ残さない。各非空片へ原文順の不変`segment_id`、元行番号及び文字範囲を与える。section見出しは分割対象にしない。
2. `openai-whisper`を実行時に遅延importし、解決済みローカル`.pt`を`whisper.load_model()`へ渡す。`task="transcribe"`、`temperature=0.0`、`beam_size=5`、`word_timestamps=True`、`condition_on_previous_text=False`で全音源を一回認識し、各atomic lyric segmentが音源上のどこに現れるかを検出する。長尺音源で冒頭歌詞を反復する幻覚を避けるため、この全体認識へ歌詞`initial_prompt`は与えない。未解決部分の短窓再認識では、一部の窓又はsegmentだけがtextを返してword timestampを欠いても、その窓だけを除外してほかのtimestamp付き音響証拠を保持する。長い未解決範囲の一部を回収した場合は、その実timestampを新しいアンカーとして残りをより狭い区間で再探索し、新しい回収がある間だけ有限回反復する。全窓がtimestampを欠く場合は時刻を推測せず未配置として停止する。package、model又は更新を自動インストール／ダウンロードしない。`openai-whisper`がなくてもextension全体のimportと他nodeの登録は成功させ、本node実行時だけ明示エラーにする。
   ComfyUI AUDIOは一batch、1 channel以上、1 sample以上を要求する。VADは元sample rateの全channel中最大RMSを使い、Whisper入力だけはfloat32平均monoへdownmixして16kHzへresampleする。原音tensorを書き換えず、VADのsample-domain境界は元sample rateで保持する。
3. vocal stemを20ms窓のenergy VADで粗く解析する。旧既定値を比較開始点として、threshold `-45 dBFS`、最小有声120ms、最小無音300ms、前後padding 80msを使う。実測前の最適値とは呼ばない。
4. 各粗区間の開始・終了近傍だけを、同じthreshold方針の包絡線とhysteresisでsample-domain再探索する。確定したsample indexを`round(sample_index * 1000 / sample_rate)`で整数msへ一度だけ変換する。同じmsへ潰れる場合も内部順序を壊さず、必要なら次のmsへ押し出した事実をstatusへ残す。
5. sectionとatomic segmentを正規化文字列の単調な順序付き整列でWhisper word列へ対応させる。類似度は旧japanese2jsonと同じ`1 - levenshtein(a,b) / max(len(a),len(b))`、primary閾値0.55、前後アンカー限定閾値0.45を使う。候補長、同点時の早い候補優先、反復歌詞の後続最大4行による確認、次行へ0.15以上よく一致する候補の保留、8文字以上の一意歌詞と後続行による長距離再同期、前後アンカー内だけの近傍救済も旧方式から移植する。探索開始は音源先頭から60秒、最初の確定後は直前の確定終了時刻から20秒以内に制限する。各Whisper wordの中点がrefined VAD有声区間外なら候補から除外し、無音後の反復幻覚を歌詞へ対応付けない。Whisperの実在word timestamp以外から開始・終了を作らない。

   全体認識後に未解決segmentが残る場合だけ、直前の解決済み歌詞終了と直後の解決済み歌詞開始（末尾runでは実PCM終端）で範囲を限定し、前2秒・後1秒を含む最大12秒、2秒重複の短窓で有限回再認識する。通常passは歌詞を正解として与えず、物理行へ戻した最大12行・160文字のbounded promptを直前文脈としてだけ使用する。窓端で先頭行だけ欠落し後続行が実認識された場合は、最初の実認識時刻の3秒前から追加の非誘導窓を一回だけ実行する。歌詞を含むguided passは、非誘導passの実在word timestampが各候補区間に重なり、かつ直後の歌詞アンカーが同じ順序・区間に再現された場合だけ採用する。leading runのように前アンカーが無い範囲は再探索しない。これらの条件を満たさない歌詞へ推測時刻を作らず、`unplaced_lyrics`のまま停止する。
   空白分割した同一物理行に未解決segmentが残る場合は、同じ行のsegmentを結合した正規化文字列でも再照合する。候補は直前・直後の解決済みsegmentが作るword範囲内かつ最大20秒へ限定し、すでに同じ行で確定したword spanを全て包含しなければ採用しない。両側に確定アンカーがある場合だけ0.45、それ以外は0.55を要求する。採用した物理行区間は各atomic segmentの正規化文字長と実在Whisper word境界により単調分配し、元の`segment_id`、原文片、section及び文字範囲を維持する。この物理行救済は長い無音をまたぐ時刻、隣接行のword又は音声に存在しない行を補完しない。
6. 解決できたsegmentは`segment_id`、原文片、section、元行・文字範囲、開始・終了絶対msを保持する。未解決segmentは削除せず`unplaced_lyrics`へ残し、node実行を失敗として停止する。推測時刻を確定値として作らない。
7. 音源総尺はsample数とsample rateから整数msへ一度だけ変換する。sub-msがある場合は末尾sampleを失わない方向へ丸める。有声境界を整数秒へ量子化せず、refined VADが返した整数msのまま接する有声範囲を結合し、補集合を無音範囲とする。
8. 各連続範囲を`max_scene_duration_ms`以下へなるべく均等に分割し、元音源上の要求Scene境界を作る。境界候補が解決済みsegment内部に入る場合は、そのsegmentを切らない最も近い境界へ移動する。空白分割後も一個のsegment自体が上限を越す場合だけ、Whisperの整列済みword境界でさらに分割し、派生した各片を新しいcanonical segmentとして以後のEMDとSRTで共用する。歌詞の確定区間と重なるSceneはvoicedへ昇格する。
9. 要求Scene長をH3 timing profileへ通し、segment内部へ入らない合法なdelivered-frame境界を選ぶ。合法境界を選べない場合だけ直前の規則でword境界分割を行い、Scene割当てを再計算する。先頭Sceneは合法raw `17k+5`、`anchor_mode=head`の後続Sceneはcontext lengthを含む合法raw `17k+5`を使う。
10. Sceneの機械的な開始・終了はdelivered framesの累積値を正とし、表示用EMD時刻だけを`round(cumulative_frames * 1000 / 24)`で整数msへ一度直列化する。各Sceneへ1から始まる不変の`scene_number`、`raw_length`、`delivered_frames`、`context_length`、要求元範囲、量子化差分及びtiming profile IDを保持する。各canonical segmentへ一個の`scene_number`を確定する。Template rendererは`scene_number`から必須の``> `シーン` N``を出力し、2件目以降の初期境界は``継続``として明示する。Plannerが境界modeを変更した場合だけ、Plannerが累積H3格子へraw lengthとPlan時刻を再配分する。Compilerは`` `H3長` ``を再計算しない。

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
  "timing_profile": "context-loop-0.6.9@9860a063784c8c23b58e00107f2180e0df3c43d9",
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
| 3 | `direction` | `MV_DIRECTOR_DIRECTION` | 任意 | 空の六方向 | Enhancerの`MVD_DIRECTION_V3`。ユーザー編集対象ではない |
| 4 | `lip_sync_mode` | STRING COMBO | 必須widget／外部接続可 | `lyrics` | `off` / `context_loop` / `audio_reference` / `lyrics` |
| 5 | `lip_sync_target` | `STRING` | 必須widget／外部接続可 | `サブジェクト1` | 口形対象の派生内部ID |
| 6 | `lip_sync_audio_slot` | `INT` 1..3 | 必須widget／外部接続可 | 1 | Audio参照時の`音声N` |
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
| 22 | `scenes_per_batch` | `INT` 1..6 | 必須 | 3 | visual beat、action及びcameraの最大Scene pack。shot-layoutは全Sceneを候補表として一括要求する |
| 23 | `cache_mode` | COMBO | 必須 | `reuse` | `reuse` / `refresh` / `disabled` |
| 24 | `save_debug_output` | `BOOLEAN` | 任意 | false | prompt全文等の診断bundle保存 |

出力順は`emd_text: STRING`、`emd: MV_DIRECTOR_EMD`（`MVD_EMD_V1`）、`status: STRING`とする。`emd_text`は通常のマルチラインSTRINGへ接続して人間が編集できる正本で、typed `emd`はcache、診断又は型付き接続用である。Compilerはtyped artifactを要求せず、編集済み`emd_text`だけで単独動作する。

### 7.5 LLMタスク分割

Plannerの`concept_emd`も一個だけを受け取る。初期自動MV経路では同じImage to Subject EMD出力をEnhancerとPlannerへ分岐し、Planner側でも複数断片の結合、優先順位判定又は番号振り直しを行わない。

Plannerの順序は次で固定する。

1. PythonがLLM入力に含まれる作者由来の`「...」`及び明示`<d>...</d>`をID付きplaceholderへ置換し、原文をside tableへ退避する。
2. `visual-beats`: Sceneごとの全原文歌詞と作者本文、timeline上のopening/middle/closing位置、歌詞解決有無、直近12 Sceneのbeat、Subjectの構造的roster及びDirectionのStyle、Time/Lighting、Motion、Other制約から、対象物、身体動作、接触、結果、感情表現を一行へ圧縮する。Environment inventory、scene EMD、背景Picture及びCamera profileはこの段階へ渡さず、背景に存在するだけの物を演技対象へ昇格させない。Cue Cardは`感情=...｜根拠=...｜対象=...｜接触=...｜現象=...｜身体主導=...｜終端=...`の固定順とし、`根拠`は現在Sceneの原文歌詞又は作者本文からの完全一致引用、`対象`はその引用に含まれる完全一致部分文字列、`接触`は`禁止|許可`、`現象`は`なし|外部自律|身体操作`だけを許す。Pythonは自然文を変更せず構造と原文根拠だけを検証し、無効なCue CardはAction/Cameraの対象・接触・effect sourceとして渡さない。 検証後は有効数、無効数及び有効な具体対象をINFOへ記録する。最初の述語だけを選ばず、同一Scene内の後続歌詞にある具体名詞又はeffectも別の位相へ割り当てる。動詞のない名詞も同一Sceneで固有の状態、動き、変化、雰囲気、空間関係又は人物の非接触反応として可視化するが、操作動詞なしに接触、保持又は誘導へ変換しない。Concept EMDの詳細な外見、身体構造、衣装構造、履物、色、材質及び参照保持文は創作taskへ渡さず、最終EMDのSubject定義としてだけ保持する。段階Directionは歌詞の創作的解釈、履歴及び照明効果より上位とし、いずれかの区分と矛盾する述語を生成しない。髪、衣装、耳、尾、風、光又は口形の受動変化だけを主beatにせず、歌詞のないSceneも直前動作の言い換えではなく新しい状態又は結末へ進める。歌詞中の傷、古傷、痛み、血又は心の損傷は、作者本文又はSubject定義が可視の身体状態として明示しない限り比喩として扱い、外傷、傷跡、痣、出血、包帯、皮膚若しくは衣装の損傷又は接触対象へ変換しない。
3. `song-direction`: visual beatsだけから、全曲を通す短い弧、反復してよい要素、変化させる要素を作る。全歌詞を再添付しない。
4. `shot-layout`: PythonがScene開始、既存Shot及び安全な均等位置から、互いにも1500ms以上離れた候補IDを作る。LLMは各Sceneへ`CUT`又は`CONTINUE`を一個選び、その後へ候補IDを最大4個並べる。先頭Sceneは`CUT`固定。新しい画角、detail、逆方向又は場所を編集点で提示する場合は`CUT`、直前の画像状態とカメラ経路を物理的に引き継ぐ場合だけ`CONTINUE`とする。各Sceneへ直前Sceneの歌詞とvisual beatに加え、`first_section_appearance`、`new_sections`及び`section_entry_shot_index`を明示する。同じ物理動作又は接触の次段階なら`CONTINUE`とし、実行可能な範囲で新section初出Sceneを`CUT`として保持する。構造的な顔インサートと歌詞固有の具体名詞又はeffectが同居するSceneでは、顔インサートに唯一のShotを占有させず、歌詞cueを可視化する通常Shotを少なくとも一つ残す。4 Scene以上では、最初のmode列がScene 1をCUT、後続境界の4分の1以上をCUT、半数以上をCONTINUE、同一mode最大3連続及びmode遷移数上限という構造契約を満たさない場合、隣接歌詞とvisual beatを比較させる境界mix再計画を一度行う。完全なCUT/CONTINUE交互列は遷移数上限違反である。再応答も満たさない場合、PythonはCUT/CONTINUE列だけを元の選択から最小変更で契約内へ修復し、変更Sceneを`layout_repaired_scenes`へ記録する。Action、Camera、歌詞、Shot候補及び自然文は修復しない。時刻を生成させず、通常は2～3 Shotを選び、4 ShotはSceneが8秒以上で四つの異なる視覚目的を各2秒以上確保できる場合だけにし、複数Shot時は各Shotを1500ms以上にする。Scene全体が1500ms未満なら一個のShotを許す。候補数超過、区切り差、重複、順序違反又は未知候補を含む応答は、既知IDの抽出、時系列順整列、重複除去及び最大4 Shotへの切り詰めだけで機械修復し、修復Sceneをstatusへ記録する。境界mode自体を認識できない場合はLLMを再試行せず`CUT,B0`へfallbackする。
5. Pythonが選択候補をShot構造へ展開し、カット／継続modeに合わせて累積H3格子上のraw length、Scene時刻及びShot時刻を再配分し、既存本文と歌詞annotationを時刻順に再配置する。
6. `actions`: DirectionのStyle、Environment、Time/Lighting、Motion、Other制約、visual beat、対象Scene、該当歌詞、Shot終了・長さ・Scene内Shot数、必要な直前状態、直近18 Shotの採用action、Subject instance policy、Python所有Shot枠及び構造的`performance_role`から、Shot IDごとの人物動作を生成する。Camera profileは渡さず、`Arc Shot`等の撮影語をActionへ混入させない。複数Shot Sceneでは、先頭の顔・上半身accent又は継続状態の変化、二番目の腕・手主体の演技、三番目の環境相互作用又は身体方向転換、四番目の異なる終端silhouetteへroleを分配する。Scene-level visual beatが移動でも全Shotを同じ歩行cycleへせず、割り当てroleでは歩行を接続動作へ降格する。段階Directionをvisual beatより上位とし、beatの対象、物理動詞、接触及び結果は維持する一方、Directionと矛盾する付随的な外見、材質、照明、変形、動作又は構図の句は出力しない。同一Scene内の各Shotは同じ主動詞と結果を反復せず、準備、接触、反応、収束等の異なる位相を持つ。MVアクセントでは加速、強い重心移動、方向転換、反動又は鋭い停止を使い、静かな区間とのpose差を作る。Action batchはslow表現上限、単純な手の上下0件及び作者未指定のlower-body主体0件及び作者・歌詞未指定の走行0件という予算を持ち、違反slotだけを一度LLMへ再要求する。 単純な手の上下は文末だけでなく、その後ろへ頭、肩、胸郭又は左右非対称silhouetteを付加した複合文も含む。`anime_emotional_mv`で検証済みCue Cardが具体対象を持つ場合は、全Shotへ反復させず、Scene内のrole上最も適した一Shot以上で完全一致対象名と認可済み関係を必須にする。`face_and_upper_body_accent`はまぶた、視線、眉、口又は表情変化を一つ以上必要とする。欠落slotだけを品質再要求する。比喩的な傷表現は清潔で損傷のない皮膚と衣装の上で、視線、呼吸、肩、胴体、手及び終端poseによる感情演技へ変換する。歌詞transcript自体を身体状態の指示として扱わない。
7. `action-audit`: `anime_emotional_mv`だけで、同じLLMを分類専用promptへ切り替え、Actionを現在歌詞、作者本文、Direction、visual beat、role、同一batch及び直近履歴と照合する。出力は`PASS`又は有限理由codeだけであり、Action自然文を生成、引用又は修正しない。 理由codeには歌詞根拠対象を落とした`MISSING_GROUNDED_CUE`及び顔roleに顔演技が無い`FACE_PERFORMANCE_MISSING`を含める。相互反復では先行する妥当slotを保持し、後方の重複だけをrejectする。監査reject、step 6後も残る構造品質違反及び表層反復を一つの有限修復集合へ統合し、該当slotだけをstep 6へ一回戻して最終auditを一回行う。auditは初回と最終の最大二回である。各roundでslotごとの最小違反候補を保持し、最終監査のreject、未知verdict、protocol欠落又はrepair欠落が残っても、その最良候補をAS IS採用して警告する。Pythonは理由codeと決定論的品質条件の構造だけを検証し、本文を意味解釈しない。
8. `cameras`: Style、Environment、Time/Lighting、Camera及びOtherだけに限定したCamera用Direction、同じShot枠、visual beat、確定したaction、Subject instance policy、構造的`editorial_role`、直近12件までのcamera履歴及びCamera profileから、Shot IDごとの構図とカメラを生成する。Motion profileとSong DirectionはCameraへ渡さない。通常slotではPythonはcamera自然文を生成又は書き換えず、LLMが選んだCamera行をAS ISで渡す。Camera行は確定Actionを言い換えず、Motion Type、画角、視点、経路、視差及び必要な可視範囲だけを記述する。リップシンク有効かつ歌詞sectionが初登場するCUT Sceneでは、新section名を持つ最初の歌詞annotationが属するShotだけを`face_performance_cut`とし、Scene開始と歌詞開始が異なる場合も前倒ししない。通常profileではそのActionとCameraをRenderer所有の固定文へ割り当てる。`anime_emotional_mv`ではActionだけをLLMへ渡し、現在歌詞に応じた閉眼、半開き、伏し目、細め又は再開眼を含む顔演技をAS ISで採用する。固定Cameraは頭肩構図から読み取れる顔close-upへ進む`Zoom In with large amplitude at fast speed`とし、Shotの35～55%で到達して短い表情accentだけを保持し、両目、両眉、鼻、完全な歌唱口及び顔輪郭を残す。Renderer所有文はEMDで日本語表示し、Compilerが翻訳backendを介さず正規のH3英語文へ決定的に置換する。各通常Camera行はMiniMax H3正式Motion Typeの一つから始める。Camera batchは通常Arc最大1、`anime_story_mv`では適格な通常slotのおよそ3分の1、`anime_emotional_mv`では2.5秒以上の適格な非顔slotのおよそ半数を`long_arc_emphasis`とする。各slotの`arc_permission`は必須又は禁止を明示する。長尺Arcは`Arc Shot with large amplitude at fast speed`で始まり、60～120度かつShot尺70～90%を移動する。顔インサートと構造的に連携するArc、Tracking最大1、その他の同一Motion Type最大2、slow上限及び作者未指定のlower-body detail 0という予算を持ち、正式Motion Type欠落、未割当Arc、長尺Arcの振幅・速度不足又は速度語競合を含む違反slotだけを一度LLMへ再要求する。共通Directionに反する付随表現を撮影目的、照明効果又は視覚的強調へ拡大しない。action本文を再出力せず、一Shotでは一つの主要なCamera Motion Typeだけを選ぶ。顔インサートと同一Scene内で隣接する通常Shot一個へ`face_arc_transition`を割り当て、顔Zoomへ入る又は顔Zoomから抜ける60～120度の長尺Arcを必須化する。ただし2.5秒未満の隣接Shotは長尺Arc対象にしない。

`planner_policy=anime_emotional_mv`ではstep 4の通常境界mixを置換し、先頭SceneだけをCUT固定、後続Sceneの4分の3以上をCONTINUEとし、CUT最小数及び同一mode最大3連続を要求しない。step 2のVisual Beatは`感情、根拠、対象、接触、現象、身体主導、終端`のCue Cardを出し、step 6へは検証済みCue Cardと元歌詞だけが具体対象を活性化すること、動詞のない具体名詞又はeffectも同一Sceneの自律的な可視述語へすること、scene EMDとDirectionのEnvironment inventoryをVisual Beat、Action及びCamera sourceにしないこと、一つの対象triggerを一Sceneで消費すること、接触には歌詞上の物理的操作意味を別途必要とすること、外部effectを既定で自律させること、まぶたと誇張した全身の感情演技を使うことを構造契約として渡す。Environmentは最終EMDで独立して合成する。Song Directionは感情・energy・編集連続性だけを扱い、ActionとCameraへ直接渡さない。step 8では2.5秒以上の適格な非顔Camera slotのおよそ半数を長尺Arcへ割り当てる一方、顔Zoomは曲全体のScene数と既存section face cutを合わせた疎な予算にする。顔Zoomは35～55%で到達し、可能なら同一Scene内の隣接slotへArc-in又はArc-out関係を設定する。これらはprofile EMD metadata由来のslot契約であり、LLMが返したAction又はCamera本文をPythonで書き換えない。
`anime_emotional_mv`の通常Camera slotは自由文を廃止し、`MOTION、START_SCALE、END_SCALE、START_VIEW、END_VIEW、PATH、COVERAGE`の七つの有限fieldを固定順で返す。各fieldはrequestに添付された列挙値だけを使い、Pythonは選択値を意味変更せず、対象名又は人物動作を追加しない固定英語H3 Camera文へ直列化する。Motion TypeとPATHの物理的一致、短尺Arc禁止、`arc_permission`、顔Zoomの顔可視範囲及び顔Arc handoffを構造検証する。不正slotだけを一回再要求し、なお不正なら同じslot role、Arc割当、顔割当及びShot尺から決定論的な有限fallbackを選ぶ。 同一七field計画は同一batch及び直近12 Shotで一回だけ許し、重複を品質違反として再要求する。fallbackはScene番号とShot番号から複数のArc左右、開始・終了scale、view及び非Arc motionへ分散し、直近と同じ直列化文を可能な限り選ばない。fallbackは環境物名、歌詞対象及び人物Actionを含めない。通常profileは従来のCamera自由文をAS ISで使用する。

Camera profileの`arc_roll_policy`は`off`（省略時）又は`selective_arc`とする。後者は開発用`anime_emotional_mv`の3.5秒以上の長尺Arc又は固定顔Shotから抜けるArcから、Camera batch当たり最大一Shotを選ぶ。顔へ入るArc及び顔だけを見せるScene Spine条件は除外する。歌詞対象と手の必須coverageは維持し、全身scaleだけを候補条件にはしない。有限Camera計画では主要Motion Typeを`Arc Shot with large amplitude at fast speed`とし、専用PATHで旋回中盤に小振幅の`Roll Clockwise`又は`Roll Counterclockwise`を重ねる。画面全体を光軸まわりに約10度傾け、Shot終端までに水平へ戻す。顔から全身へ抜けるArcでは開始scaleを`face_closeup`又は`head_and_shoulders`、終了scaleを`full_body`とし、Scene Spineが`upper_body_hands`を要求する場合は`whole_body_hands`を使用する。その他のArcでは水平線が読める中景以上を使う。PATHはArc左右の基底方向を保持するため、後続CONTINUE Shotの旋回方向判定に使う方向はRollの有無に依存しない。LLMのfield選択をAction変更へ拡張せず、不正fieldには既存の有限fallbackを使用する。`anime_story_mv`は`off`で比較基準を保つ。

Planner v73では、`CONTINUE`の次Sceneへ渡す`entry_body_state`に、直前Sceneで採用済みのScene Spineがあれば最終Shotの`TO`を原文のまま優先し、なければ直前Cue Cardの`終端`を使う。現在SceneのScene Spine最初の`FROM`及び最初のActionがこの身体姿勢を受け取る。`CUT`では空とし、前Sceneの歌詞対象や出来事を新Sceneへ持ち込まない。Pythonは姿勢文を解釈・合成・修復せず、LLMの文を転送するだけである。これは姿勢情報の連続性を補う契約であり、振り付けの多様化を保証しない。

Planner v74では、Motion profileが`performance_mode dance_phrase`と`choreography_policy scene_palette`をともに宣言し、二つ以上の`# 振付候補`を持つ場合に限り、候補群をScene SpineとActionへ任意の着想として渡す。LLMに候補IDの選択、逐語的再現又は候補間の均等配分を要求しない。候補を使わず独自の身体経路も生成でき、追加LLM段階も設けない。任意の別方式`scene_choice`は候補ID又は`FREEFORM`を一Sceneずつ選べるが、8Bで特定候補への強い偏りを確認したため、運用用`anime_choreography_mv`では選ばない。PythonはAction自然文を合成・修復・置換しない。既存Motion profileは`off`のままであり、UI項目は増やさない。

可視の傷等に関する旧Visual Beat規則の「作者本文又はSubject定義だけ」という限定は、意図的な歌詞解釈を排除しない規則へ改める。歌詞文字列だけから身体の損傷を自動追加しないが、LLMが歌詞に基づいて可視の比喩又は身体状態を明確なShot演出として採用した場合、完成EMDのShot本文を下流Style及びCompilerが優先する。日本語Actionの意味内容をPythonで禁止語除去又は書換えせず、歌詞に無関係な損傷を既定描写へ追加しない。

Camera profileの`lyric_cue_mode`は`automatic`、`priority_only`又は`off`とする。
`automatic`では現在Sceneの原文からVisual Beat LLMが最も具体的な可視名詞句
又は独立effectを一つ選び、検証済みCue CardをActionへ渡す。Planner v54以降の
組込み`bounded + automatic`では、選択前に下記の歌詞行Discoveryを行う。
`priority_lyric_cues`は`TOKEN:KIND`の任意の回帰override metadataであり、
現在Sceneの原文へ完全一致したtokenだけをVisual Beatへ渡す。Cue Cardが優先token、
又は`external_effect`の外部自律性を落とした場合はVisual Beat slotを一回再要求する。
それでも不正なCue Card本文はAction sourceにせず、元歌詞で検証済みのtoken、kind、
evidenceだけをActionへ渡す。各ShotはScene内で対象を確立し、関係を作り、人物が
反応し、解放する有限位相を担当する。Pythonは位相と完全一致tokenだけを検査し、
Action本文を合成又は書換えない。設定tokenが歌詞に無いSceneではこの契約を
起動しない。

9. Pythonが採用した行recordの`TEXT`から新規生成された引用台詞とplaceholder echoを削除する。
10. Pythonが任意のサブジェクトEMD、direction、annotation、action、camera、audio templateを完全EMDへ合成し、選択したlip-sync modeのdirectiveを最後に挿入する。`<Subject N>`と`<Picture N>`の関連は変更しない。`` `H3長` ``はstep 5で境界modeと同時に確定した値をそのまま出し、Compilerには再計算させない。

Visual Beatは一般的な歩行、正面立ち、両手を広げる、手を上げる又は背景物へ触る動作を既定にしない。現在Sceneの全原文歌詞又は作者指示だけが具体物、場所要素又は外部effectを活性化し、最初の述語だけで後続の具体名詞を捨てない。scene EMD、Direction及び過去SceneはAction sourceにしない。動詞のない名詞も固有の状態、動き、変化、雰囲気、空間関係又は人物の非接触反応として同一Sceneで可視化する。対象名だけでは接触を許可せず、物理的操作の意味が無い場合は、まぶた、視線、頭、肩、胴体、骨盤、腕、手、支持脚、遊脚、重心及び身体レベルを連動した非接触の全身演技へ変換する。外部effectは既定で人物から独立して空間内を移動し、人物は視線、姿勢、回避又は一回の感情反応だけを返す。

Visual Beat、Action及びCameraの長いTEXTが同一request内又は直近履歴と完全一致若しくは高い表層類似度を持つ場合、Pythonは本文を変更せず、該当slotだけをScene単位で最大二回再要求する。retry payloadには`rejected_output`、`must_differ_from`、`diversity_retry_attempt`及び直近と同一batchの採用候補最大12件からなる`forbidden_recent_outputs`を入れ、左右交換、同義語又は語順変更ではなく、主動詞、対象、結果、終端pose、Motion Type、構図又は撮影目的を実質的に変更させる。Action又はCameraの構造予算違反は該当slotだけを`action_quality_budget`又は`camera_quality_budget`として一度再要求する。残存違反は最小違反のLLM候補をAS IS採用してログへ記録する。Cameraは必須slot欠落又はprotocol回復失敗だけをfail-closedとする。いずれの場合も採用TEXTは一文字も機械修正しない。

UIで固定したseedはPlanner全体の再現性を所有する。各LLM requestではbase seed、task、task内call番号及びpayloadから1..2147483647の`call_seed`を決定的に派生し、同じrun入力では同じ結果を保ちながら、batch又はretryごとに同じ乱数列の先頭を再利用しない。

人物動作を複数fieldへ分解せず、行指向の`ACTION`本文をAS ISでEMDへ渡す。ただしsystem promptでは、一つの自然文内に予備動作、主動作、反応又は収束が読め、歌詞の具体名詞へ身体が接触して結果が生じる構成を優先する。手を上下するだけ等の抽象動作を十分とは扱わない。カメラ出力に人物動作の置換・削除権限を与えない。

髪、体毛、動物耳、耳内部、尾、皮膚及び衣装の照明は人物動作へ変換しない。作者Shot本文が発光を明示しない限り、Visual Beat、Action及びCamera taskはこれらを光源、発光体、glow、bloom又は発光haloとして記述せず、月光、逆光及び灯火は通常の反射光へ限定する。特に耳内部を透過光で局所的に白飛びさせる指示を生成しない。この条件も採用行を後段置換するfilterではなく、各taskへ関連するDirection区分を渡した上でsystem promptにより生成前から制約する。Pythonは意味解釈、競合句の検出又は削除を行わず、PlannerのAS IS原則を維持する。

同じShotの人物動作とカメラは同じShot全区間で並行するものとしてrenderし、人物動作文を先、カメラ文を後に置く。両taskは数値sub-timeを生成せず、`while`、`as`、`then`又は「終わりまでに」に相当する自然な相対関係だけを使える。camera taskは確定actionを読み取り専用contextとして受け、動作の開始、終了又は順序を変更しない。編集上のhard cutはScene境界の`CUT`だけが所有する。Scene内Shot境界は同一H3生成内の時刻付きprompt変化であり、camera LLMに新しい時刻、Shot又はmid-shot cutを作らせない。

#### 7.5.1 Plannerの台詞placeholderと生成台詞filter

- placeholderは一run内で一意な`__MVD_LOCKED_DIALOGUE_0001__`形式とし、元文字列、入力record ID及び位置をPython side tableへ保持する。placeholderとside tableはEMD、cache preview又はH3 promptへ残さない。
- LLM応答は2.6の行protocolでrecord化し、採用した各recordの`TEXT`だけを走査する。typeとslotにはfilterを掛けず、recordの対応関係を変更しない。
- side tableにある既知placeholderもLLM応答中ではsource echoとして削除する。未知placeholder及び重複placeholderも同じく削除する。原文はLLM応答から復元せず、Subject、Direction又は作者Shot本文のPython所有位置から一度だけ出力する。
- LLMが新規生成した`「...」`、`『...』`、`“...”`、文字列field内の`"..."`又は`<d>...</d>`は、delimiterを含むspan全体を無条件で削除する。意味、言語、話者又は内容を判定しない。
- 閉じdelimiterのない開始記号はその位置からfield末尾まで、対応する開始記号のない閉じdelimiterは閉じ記号だけを削除する。削除後は隣接空白だけを一個へ正規化し、空になった生成list itemは落とす。
- このfilterによる削除、空item又は未使用placeholderはLLM retry条件にしない。`removed_generated_dialogue_count`と`unused_protected_dialogue_ids`をstatusへ残す。削除後の成果と原位置に保持した作者本文をPython rendererへ渡す。
- Plannerが`lip_sync_mode=lyrics`で歌詞から作る``リップシンク 歌詞`` directiveはLLM応答ではないためfilter後にPythonが挿入する。作者由来の復元台詞と同様、生成台詞として削除しない。他のmodeではこのdirectiveを挿入しないが、歌詞annotation自体は削除しない。

Plannerには外部接続可能な`lip_sync_mode`（`off`、`context_loop`、`audio_reference`、`lyrics`。既定`lyrics`）、`lip_sync_target`（既定`サブジェクト1`）、`lip_sync_audio_slot`（1～3、`audio_reference`時だけ使用）を設ける。正確なmodeとaudio slotはPython rendererだけがdirective生成に使う。通常Camera taskへは`lip_sync_active = (mode != off)`とtargetだけを渡し、口が見える構図を維持させる。節入口の構造的な極端顔close-upはCamera taskへ渡さず、Python rendererが両目、両眉及び口全体を同時に表示する固定Action/Cameraを割り当てる。他のLLM taskへmode又はaudio slotを渡さない。Concept EMDのSubject行が一行だけならPythonが`single_subject_exactly_one_visible_instance`、複数なら`defined_subjects_only_no_duplicate_instances`をactionとcameraへ渡す。前者ではCamera行へ主要Subject一体だけを画面へ置く旨を明記し、参照設定画のpanel、alternate view、鏡像又は似た背景人物を別instanceとして再現させない。

固定顔インサートのActionは、Subjectで記述済みの眉の個数、compactness、形、配置及び色を維持し、特殊な眉markを通常の長い線状、湾曲又は弓状の眉へ置換しない。これは特定キャラクター名又は日本語語彙を判定するfilterではなく、既述の局所識別形状を顔演技中も保持する固定契約である。

- `off`: リップシンクdirectiveを出さない。
- `context_loop`: 歌詞annotationの有無にかかわらず全Sceneへ``* `リップシンク` `Context Loop` `サブジェクト1` ``を出す。これによりCompilerは全Sceneへgeneration-timeのsource音声方針を明示でき、歌詞のない間奏又は末尾Sceneだけ動画生成WFの既定値へ暗黙fallbackしない。
- `audio_reference`: Lyric Segmentationが一個以上の`歌詞`annotationを構造配置したSceneへ``* `リップシンク` `Audio参照` `サブジェクト1` `音声1` ``を出す。対象とslotは入力値を使う。
- `lyrics`: Plannerが各Shot見出しの直前に置かれた解決済み`歌詞` annotationを文書順に読み、同じShotへ一segmentごとの``* `リップシンク` `歌詞` `サブジェクト1` 「原文」``を出す。歌詞のないShotへは出さない。

歌詞annotationは四つのmodeすべてで同じcanonical表記のまま完成EMDへ保持する。選択歌詞はmodeにかかわらず人物動作・演出推論へ使用でき、`lip_sync_mode`は口形を駆動する実行方式だけを切り替える。従って`context_loop`又は`audio_reference`を選んだ時の「歌詞を破棄する」とは、``リップシンク 歌詞``をmaterializeしないという意味であり、annotation、SRT又は`MVD_TIMELINE_V1`から歌詞を物理削除する意味ではない。Compilerは全modeで歌詞annotationを読み飛ばすため、保持してもH3 promptへ重複転記されない。

Plannerは別の`vocal evidence`判定を行わない。VADとWhisperはLyric Segmentationがatomic lyric segmentのsource開始・終了msを確定する工程だけで使う。`context_loop`は選択modeそのものを全Sceneのgeneration-time音声方針とし、歌詞annotationのない間奏又は末尾Sceneにもdirectiveを出す。`audio_reference`と`lyrics`だけは、Shot直前へ構造配置済みの歌詞annotationの有無を`lip_sync_active`条件とし、annotationのないScene又はShotへdirectiveを出さない。

Plannerの視覚beat、Shot layout、人物動作及びカメラ要求はすべて`scenes_per_batch`以下へ分割する。Shot layoutも全Sceneを一括送信せず、各Sceneが保持する直前Sceneの歌詞と視覚beatを境界判断の局所文脈とする。全体のCUT/CONTINUE比率は分割応答を統合後に検査し、必要な再要求も同じbatch上限で行う。

`lip_sync_mode`の`off`と有効mode間の変更は、口が見える構図条件が変わるためcamera taskとrendererを無効化する。有効な三mode間の変更と`lip_sync_audio_slot`変更は確定済み歌詞、Shot枠、人物動作及びカメラを再推論せず、決定的directive rendererとその下流だけを無効化する。`lip_sync_target`は口形対象であると同時に人物動作及びcamera対象へ影響し得るため、変更時は対象依存taskとrendererを無効化する。

Timeline PlannerはMV専用である。完成動画にどの音声を残すかはPlanner入力でもEMD directiveでもなく、下流の動画生成WFにあるContext Loop Chain Policyが所有する。Plannerは`lip_sync_mode`に対応する口形directiveだけを出し、最終音声方針を表す`lock_source_audio`又は`ソース音声固定`は設けない。標準構成は`context_loop`、`audio_reference`、`lyrics`の三つのPlan/Compiler WFを、同名方式の三つの動画生成WFへ一対一で接続する計6 WFとする。各動画生成WFは自方式の音声socket、Generation Profile、任意Lip-Sync Options及び最終音声Chain Policyを所有する。

Planner v47以降、step 2に記載したscene EMD非入力規則は限定入力へ置換する。scene EMDはVisual Beatだけへ`scene_context`として渡し、現在歌詞又は作者本文が既に認可した対象の位置と空間関係だけを補う。scene EMD単独では対象、接触、人物動作又はeffectを活性化できず、Action及びCameraへscene EMD本文を渡さない。profileの優先Cue実tokenはshared contractへ格納せず現在Scene entityだけへ渡す。優先Cueを持つSceneはVisual Beat及びAction/Auditを単独requestとし、採用Visual BeatとAction本文を後続Sceneのrecent historyへ積まない。現在Sceneで許可されていないprofile tokenがActionへ出た場合は`unexpected_priority_cue`として該当slotだけを再要求し、不採用本文はretry promptへ再掲しない。

Planner v48ではVisual Beat Cue Cardへ`配置`と`可視展開`を追加する。対象がある
場合は両fieldを非空にし、scene EMDは認可済み対象の空間anchor選択にだけ使う。
ActionはCue Cardの対象名だけでなく、そのanchorと対象自身の状態、変化、軌道又は
環境結果をScene内の少なくとも一Shotで可視化する。Auditは裸の名詞への縮退、
左右交換だけの身体choreography template反復及び`ACTION N`等の内部labelを有限
reasonでrejectする。Pythonは採用自然文を削除又は修正せずAS IS原則を維持する。

Planner v49では`anime_emotional_mv`のprofile優先Cue Sceneについて、Visual Beat
が生成した`配置`と`可視展開`をAction生成対象の先頭二slotへ有限に割り当てる。
生成対象が一slotだけなら同じslotへ両方を割り当てる。各slotは割り当てられた
完全な文字列をAction本文へ一回含める必要があり、対象名だけのprefix、短縮、
同義語又は代名詞では満たさない。Pythonはslot割当と完全一致検査だけを行い、
Action自然文を生成、補完又は置換しない。品質retryとAction Audit後も割当句が
欠落する場合は`ACTION_GROUNDING`として停止する。`ACTION N`だけでなく、本文
先頭の裸のslot番号、`TAB`、`タブ`、`<TAB>`又は`\\t`もprotocol断片として
再要求し、残存時は`ACTION_PROTOCOL`として停止する。割当slotと二句はINFOへ
記録する。

Planner v50ではv49の完全一致転送対象をprofile優先Cueだけに限定せず、
`lyric_cue_mode=automatic`で検証済みの全Cue Card対象へ拡張する。Visual Beatは
現在Sceneの原文に完全一致する、物理的に表示可能な最も具体的な連続名詞句又は
独立effectを選ぶ。複合名詞は一般語へ短縮せず、例えば`御神木`は`木`ではなく
`御神木`のまま扱う。抽象語だけの句は具体的なvisual carrierが原文にない限り
対象にしない。Pythonは対象を辞書分類又は生成せず、Cue Cardの検証、Scene局所
scope、slot位相、配置・可視展開の完全一致及び有限retryだけを担う。

### 7.6 再試行

- 各taskの許可type、短いslot集合、重複及び欠落recordだけを検証する。実Scene/Shot IDと時刻はLLM応答に含めない。
- batch応答の一Sceneだけが構造不正なら、そのSceneの欠落slotだけを一回再生成する。Scene単位再要求でも一部が欠落した場合は、残るslotを一件ずつ`isolated_missing_slot`として一度再要求する。隔離要求はside table上の対応が一意なので、正規wrapperを省略した単一の非空物理行もTEXTを変更せず回収できる。
- LLM応答中の引用台詞、発話表現又はdialogue tagは品質・protocol retryの理由にせず、7.5.1のfilterで一回だけ機械削除する。
- Qwen3-4Bへは各Planner taskのuser message先頭で`/no_think`を指定する。Plannerに限り、閉じた`<think>...</think>`、separatorとして出力された文字列`<TAB>`、`slot N`表記、及び同じ既知typeが一物理行へ連結された応答をparser前に決定論的に正規化する。slot番号はScene/Shot対応を所有するため変更しない。
- 漠然と品質が弱い、表現が好みでない又は意味が疑わしいという理由では自動再試行しない。7.5で定義した反復判定と有限なAction／Camera構造予算だけを品質再試行条件にする。
- 同じ対象を上位taskへ戻す入れ子retryを作らない。
- 一回の局所retryでも有効にならなければ内部では未完了artifactとmissing slotを保持する。ComfyUI nodeの`emd_text`及び`emd`出力は`ExecutionBlocker`として下流を停止し、Template EMDをCompilerへ誤入力しない。statusにはmissing slotを残す。

### 7.6.1 Planner v54：現在歌詞からの対象抽出

`lyric_interpretation=bounded`かつ`lyric_cue_mode=automatic`の組込み経路は、
Visual Beatの前に`lyric-cues` taskを追加する。現在Sceneの歌詞・作者本文だけを
行単位で分類し、同一原文行は全曲で一回、最大16行のbatch、出力上限は
`min(max_tokens, 768)`とする。画像やVisionの再認識は追加しない。

LLMは各行から`motif|effect|place|body|none`と、その原文に含まれる連続した
対象文字列を返す。Pythonは名詞辞書を持たず、各Sceneの原文順で最後の
`motif/effect/place`候補一つを選ぶ。分類kind間に優先順位は付けず、bodyとnoneは
対象選択に使わない。これは冒頭の背景へ固定される傾向を避ける順序規則であり、
意味的重要度を保証するものではない。作者の明示`priority_lyric_cues`は優先する。

生成時文法は選択済みの対象と同じ行の根拠を固定する。配置も対象文字列から
始めるが、その後の支持物、位置関係、可視変化と動詞はLLMが生成する。
分類kindは接触許可又はeffect操作権限には変換しない。空候補は対象なしとし、
隣接Scene・背景inventoryから対象を補わない。対象九項目と最終EMD schemaは維持する。

boundedのBeat/Action生成には以前の採用自然文履歴を再掲しない。監査とPythonの
反復検査は履歴を保持し、現在の修復候補・違反理由及びDirectionの明示制約は
引き続き生成側へ渡す。既定Action promptは既存の通常版を使用する。
監査最大二回・修復一回の上限は変えない。Discovery候補とScene選択をINFOへ記録し、
`mvd-timeline-planner-v54`として旧cacheと区別する。UI・WFの追加変更はない。

### 7.7 Audio Pad Pair

公開support nodeは`MVDirectorAudioPadPair`、表示名は`MV Director - Audio Pad Pair (PCM Silence)`、カテゴリは`MV Director/Audio`とする。旧`CLAudioPadPair`の有限なPCM処理を再利用するが、単体`CLAudioPad`相当のnode typeは実装又は登録しない。

- `audio_a`へfull mix、`audio_b`へvocal stemを接続する。
- 二入力は同じ時刻原点と再生速度を持つことを前提とし、offset検出、同期推定、resample、mix又はtruncateを行わない。
- 共通基準尺は二入力尺、任意の`MVD_TIMELINE_V1`に含まれるScene `delivered_frames`合計、任意のCompiler出力`plan_json`に含まれる各Sceneの`length - context_length`合計、`plan_duration_ms`又は明示H3 frame targetの最大値に`extra_padding_ms`を加えてsample数へ変換する。Timeline接続時は整数msへ直列化した`plan_duration_ms`ではなく、`delivered_frames`合計を正確な初期Plan尺の正とする。Plannerがカット／継続を変更した動画生成WFでは、同じCompiler出力をContext LoopとAudio Pad Pairの`plan_json`へ分岐し、再配分後の最終Plan尺を優先する。例えば719 frame / 24 fpsを29,958 msだけで計算すると末尾が16 sample不足し得るためである。浮動小数秒を基準値にしない。
- 短い側だけを各sample rateで無音補完し、`pad_position=end`を既定にする。
- `padded_audio_a`と`padded_audio_b`はH3 Audio Tracksへ渡す。Lyric SegmentationのVAD / WhisperとH3 Lip-Sync Optionsにはpadding前の元vocalを渡す。
- 既存二出力と`status`の後ろへ参照専用`reference_audio_b: AUDIO`を追加する。`reference_alignment=off`（既定）では`padded_audio_b`と同じ値を返し、通常Pairの意味を変えない。
- `reference_alignment=source_scenes_to_plan`では`MVD_TIMELINE_V1`を必須とし、padding前`audio_b`の各`source_start_ms`～`source_end_ms`を順番のまま取り出して、累積`delivered_frames`を24fpsでsample位置へ変換したPlan区間の先頭へ配置する。各Sceneの量子化余剰はScene末尾PCM無音とし、Scene内の無音を保持する。
- Scene alignmentでもresample、mix又は音声内容のtruncateを行わない。source Sceneが対応Plan delivered区間へ収まらない、source区間が非連続、又はtimelineがない場合は明示エラーにする。`reference_audio_b`だけをAudio参照workflowのH3 Audio Tracks／Source Timelineへ渡し、最終full mixには使わない。
- 単体Audio Padの公開classは再利用しない。入力検証とPCM paddingに必要な処理だけをPair module内のprivate helperへ抽出する。

### 7.8 Scene Debug Splitter

公開utility nodeは`MVDirectorSceneDebugSplitter`、表示名は`MV Director - Scene Debug Splitter`、カテゴリは`MV Director/Utilities`とする。

- 必須入力は`plan_json: STRING`、`vocal_audio: AUDIO`、`full_mix_audio: AUDIO`、`enable: BOOLEAN`、`scene_start: INT`及び`scene_length: INT`とする。`plan_json`は接続入力、後三項目はUI widgetで、`enable=true`、`scene_start=1`、`scene_length=1`を既定とする。
- `scene_start`は1ベースであり、JSON上の選択開始は`shots[scene_start - 1]`とする。PCMスキップframe数はindex 0から選択開始直前までの各`length - context_length`を総和する。`scene_start=1`では0 frameをスキップする。
- 出力frame数は選択する連続`scene_length`件の`length - context_length`合計とする。raw `length`だけを加算して継続contextの音声を重複させない。
- 24fpsの累積開始frameと終了frameをそれぞれ入力sample rateへ有理数変換してsample境界を求める。両PCMを同じframe窓で切り出し、入力が選択終端より短い場合だけ不足分を末尾PCM無音で補う。resample、mix又は時間伸縮を行わない。
- 出力Planはroot objectの`shots`だけを選択部分列へ置換し、他field及び選択Shot objectを変更しない。範囲がPlanを超える場合は暗黙に縮めず停止する。
- 出力順は`plan_json: STRING`、`vocal_audio: AUDIO`、`full_mix_audio: AUDIO`とする。`enable=false`ではJSON又はPCMを検証せず、三入力を同一値のまま返す。

## 8. EMD（Easy MarkDown）`MVD_EMD_V1`

EMDは**Easy MarkDown**の略称であり、Extended Markdownの略称ではない。標準Markdownの見出し、list及び引用を使い、人間が編集できる簡潔な中間言語へ予約行だけを追加する。

EMDのcanonical構文、文書種別、valid/invalid例及びCompiler固定写像の確認には[EMD仕様書](emd-spec.md)を使う。本節はシステム全体との接続境界を説明し、構文に差異がある場合は専用仕様書を初期実装の基準とする。

### 8.1 基本構造

`# サブジェクト`直下では、一つのlist itemが一つのH3 Subjectを定義する。文書順から`サブジェクト1..4`及び`<Subject 1..4>`を導出し、明示的な`人物N`、`場所N`、`物品N`、`H3サブジェクト`又は`名称`行は持たない。

```markdown
# サブジェクト
* `画像1` 狐耳の少女。長い金髪、赤い瞳、白と赤の着物風衣装を持つ。
* 夜の神社。朱塗りの鳥居と石畳がある。

# 保持分析
* `サブジェクト1`: `partially_preserved` 髪、狐耳、尾、衣装と配色を保持する。

# 共通プロンプト
## スタイル
* 参照設計を保ちながら実写映画として描写する。
## モーション
* 接地と重心移動が読める連続動作にする。
## カメラ
* 顔と全身動作を読める距離を保つ。

> `シーン` 1
# シーン 00:00.000 --> 00:10.125
* `H3長` 243
## ショット 00:00.000
* `サブジェクト1`は石畳を踏みしめ、鳥居の奥へ進む。
```

文書順は`# サブジェクト`、任意の`# 保持分析`、任意の`# 共通プロンプト`、一個以上のSceneとする。共通プロンプトの存在する本文は`スタイル → 環境 → 時間・照明 → モーション → カメラ → その他`の順で`prompt_prefix`へ写す。

### 8.2 サブジェクトとmedia binding

- Subjectは1～4行。各行は空でない自然言語descriptionを持つ。
- 行順だけで`サブジェクトN`と`<Subject N>`を決定する。
- descriptionより前へ``画像1..9``、``動画1..3``、``音声1..3``を0個以上置ける。
- Compilerはこれらをそれぞれ`<Picture N>`、`<Video N>`、`<Audio N>`とrequired referenceへ固定変換する。
- media tokenのないSubjectは文章定義だけのH3内蔵概念として有効。
- Shot、保持分析及びlip-syncからの参照は、定義済みの``サブジェクト1..4``だけを使う。
- Image to Subject EMDの`auto_h3`は接続先`ref_image_0..8`から``画像1..9``を出す。Subject番号を選ぶsocketは持たない。
- Compilerは意味分類、参照内容又は実配線を検査しない。
### 8.3 SceneとShot時刻

- 各Scene見出しの直前の物理行へ``> `シーン` N``を必須とする。`N`は1からScene順に1ずつ増やし、重複、欠番、逆順又は0を許可しない。Compilerは番号を推測又は補正せず、Plan Scene `id`へ`scene_NNNN`として写す。
- Scene見出しは`# シーン START --> END [継続]`とし、`START`と`END`はH3 delivered frame累積から直列化したplan絶対時刻を必須とする。`継続`は直前Sceneの映像contextを使う明示suffixで、先頭Sceneでは禁止する。suffix省略はカットであり暗黙継続にしない。
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
* `サブジェクト1`は鳥居の奥へ視線を向ける。
* `リップシンク` `歌詞` `サブジェクト1` 「千年鳥居をくぐるそなたよ」
## ショット 00:15.000
* `サブジェクト1`は石畳を進む。
* `リップシンク` `歌詞` `サブジェクト1` 「月明かりの道を」
```

Plannerは各Shot見出しの直前に構造配置された解決済み歌詞を、そのShotへ割り当て済みとして扱う。同じShotに複数segmentが入る場合は一行ずつ文書順に出す。CompilerはShot見出しの絶対開始時刻からScene相対開始時刻を機械算出し、各directive内の対象・歌詞原文だけを固定promptへ展開する。`歌詞` annotationを検索、時刻対応付け又は補完しない。

これはShot区間でH3に歌唱時の可視口形を促す時間付きpromptである。音素、word又はframe単位の口形列は生成せず、元音声との完全同期を保証しない。

### 8.6 `## 音響`

音響は説明文を解析せず、予約済みdirectiveだけを扱う。リップシンク駆動方式はSceneごとに一つだけ選ぶ。現在のContext Loop Lip-Sync Optionsを使う場合は次とする。

```markdown
## 音響
* `リップシンク` `Context Loop` `サブジェクト1`
```

Lip-Sync Optionsの追加モデルを使わず、H3音声参照で駆動する場合:

```markdown
## 音響
* `リップシンク` `Audio参照` `サブジェクト1` `音声1`
```

生成条件を無音にする場合:

```markdown
## 音響
* `無音`
```

`## 音響`の省略はエラーでも無音でもなく、Scene固有の音声要素を出力しないことを意味する。下流のChain Policyをそのまま継承する。Compilerは接続音声を調査せず、次の予約directiveだけを機械的に写像する。

- `リップシンク` + `Context Loop` + 一つの概念ID
- `リップシンク` + `Audio参照` + 一つの派生Subject ID + 一つの`音声N`
- `明示台詞のみ`
- `無音`

``リップシンク Context Loop``、``リップシンク Audio参照``、同じScene内の一つ以上のShot ``リップシンク 歌詞``は相互排他とする。Shotの歌詞方式は同じ方式のlist directiveとして複数行を許す。Audio参照方式の`音声N`はこのdirective内でだけ直接指定でき、Compilerの`required_references`へ音声slotとして追加する。Compilerは音声tensorを要求せず、接続確認もしない。

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

CompilerはRef2VA専用のEMD parser、限定翻訳orchestrator、H3 prompt renderer、JSON serializerとする。通常入力はSTRING `emd_text`、H3 timing profile、`translation_mode`、`model_name`、`cache_mode`とruntime設定である。`cache_mode`は`reuse`（既定）/ `refresh` / `disabled`とし、文法検証後の成功したPlan JSONとrequired referencesだけを保存する。`translation_mode=ja_to_en`では選択GGUFを内部PromptTranslator adapterで使う。初期比較候補は4Bと8Bだが特定modelへ固定しない。Image to Subject EMD、Enhancer、Planner、IMAGE、AUDIO又はworkflow graphは要求しない。

1. EMDの`# サブジェクト`、必須Scene番号annotation、Scene、Shot、`` `H3長` ``及び予約directiveを構文解析する。
2. Subject/Picture関連、概念ID、`「...」`、明示`<d>...</d>`、MiniMax H3正式Camera Motion Typeとamplitude/speed句、annotation、音響directive、Shotの``リップシンク 歌詞``を翻訳対象から分離する。
3. `# サブジェクト`の説明、任意の`# 共通プロンプト`の六区分本文、`# 保持分析`の説明及びShot本文だけを、区分を保持したtranslation unitとして英訳する。識別上重要な局所形状、個数、配置、大きさ、色、材質及び否定条件は具体的な物理形状として保持し、特殊な特徴を一般的な解剖・衣装・装飾形状へ正規化しない。「丸く横へ線が伸びない」のような形状は単なる`round`又は`rounded`へ弱めず、長い線を形成しない小さな円形又は楕円形のmarkとして対象部位を明記して訳す。保持mode ``fully_preserved`` / ``partially_preserved``は翻訳unitへ入れず固定tokenのまま保つ。翻訳応答の一部slotが欠落した場合、又は採用本文に日本語scriptが残るかslot番号そのものの場合、正常slotは保持し、該当原文だけを一件の`slot 1`として一度だけ隔離再試行して元位置へ戻す。壊れたslot番号、重複、未知行又は本文の意味を推測修復せず、隔離再試行も行protocol不正、欠落又は非英語なら停止する。
4. EMD内部IDを対応する`<Subject N>`へ固定変換し、実際に記述された`<Picture N>`と`<Audio N>`だけの必要slot一覧を作る。自由描写中の`<Video N>`は翻訳保護してas-isで渡すが、V1では必要slot一覧を生成しない。
5. 各Shotの``リップシンク 歌詞``を、そのShot開始位置、対象token、原文`<d>[Japanese]...</d>`を持つ固定prompt要素へ写す。
6. 通常の`「...」`の内容を変えず`<d>[Japanese]...</d>`へ包む。
7. 明示された音響directiveだけを固定対応表でScene JSON要素と固定prompt要素へ写す。音声参照tagと歌詞原文は翻訳unitへ入れない。
8. 各Sceneの`` `H3長` ``を整数のままPlan `length`へ写す。Scene時刻からlengthを再計算、丸め又は補正しない。
9. ``> `シーン` N``を0 paddingしたPlan Scene `id`の`scene_NNNN`へ写す。
10. 任意の`# 共通プロンプト`の翻訳済みlistを`スタイル → 環境 → 時間・照明 → モーション → カメラ → その他`の固定順で平坦化し、subsection見出しを除いてPlan `prompt_prefix`へ一回だけ出力する。本文がなければfieldも出力しない。
11. 各Scene固有promptを`subject_definitions`、`summary`、`retention_analysis`、`detailed_description`、`overall_soundscape`、`non_diegetic_music`の正規順で構成する。
12. 標準JSON serializerでescapeし、Ref2VA Plan JSONを返す。

六セクションはEMDに存在しない演出をLLMで補わず、次の決定規則で満たす。

- `subject_definitions`: そのSceneで使う各`<Subject N>`を行頭から一回だけ定義し、存在するPicture等の参照tokenは同じSubject行の末尾で関連付ける。翻訳済みdescriptionと固定の参照文を連結する前に英文の終端句読点を保証する。記述済みの局所形状、個数、配置、大きさ、色、材質及び除外条件を文字どおりのidentity constraintとし、特殊な顔・身体・衣装・装飾特徴を通常形へ置換しない固定文を続ける。参照は外見同一性と設計だけに使用し、alternate viewを一人物として扱い、参照のpose、framing、composition、panel layout及びbackgroundを現在Shotへ複製しない固定文を付ける。Picture/Video参照では、一つの連続した全画面camera viewだけを描き、内部境界、split screen、picture-in-picture及び複数角度の同時表示を禁止し、視点変更を時間方向のcamera motion又はscene cutだけで表す固定文も付ける。現在Sceneの環境・時刻・照明を参照背景・参照照明より優先し、白背景、無地背景、昼光、backdrop又はpanel固有背景を描画対象から除外する。各Shotは先頭frameから現在のActionとCameraによる新規stagingを使い、参照画像そのもの、参照構図又は参照ポーズから開始若しくは遷移しない。Pictureを独立したSubject又は保持対象として自動定義しない。
- `summary`: Scene本文の先頭記述を翻訳後一行コピーし、その先頭へ固定task directive ``[reference generation]``を機械付与する。Scene本文がなければ先頭Shot本文をmarkerなしで使う。どちらもなければ文法エラーとし、要約文を新規生成しない。
- `retention_analysis`: `# 保持分析`のSubjectを`<Subject N>`へ、固定modeを未翻訳で、翻訳済み説明をハイフン後へ写す。明記がない場合は、参照の有無にかかわらず行頭で定義した各`<Subject N>`について、文章で定義した同一性と属性に加え、局所形状、個数、配置、大きさ、色、材質及び除外条件をShot間で文字どおり保持し、特殊な特徴を通常形へ置換しない``fully_preserved``固定文を一行だけ出す。Subject行の文中に関連付けた`<Picture N>`を独立した保持対象として自動出力しない。
- `detailed_description`: Scene本文と全Shot本文を文書順で写し、Shot markerと相対時刻だけを機械付与する。
- `overall_soundscape`: 明示音響directiveの固定文を出す。音響指定がなければ`No scene-specific soundscape instruction is provided.`だけを出す。
- `non_diegetic_music`: `無音`時は`No non-diegetic music.`、それ以外は`No additional non-diegetic music is requested.`だけを出す。完成動画のsoundtrack選択はEMDから記述しない。

`summary`への一行コピーと、strict schemaのために必要な固定保持・音響文はrendererの構造化処理であり、PromptTranslatorによる補強、要約又は創作には数えない。固定文はversioned fixtureで完全一致させ、モデル出力へ委ねない。

### 9.2 翻訳境界と`as is`の定義

`as is`は「日本語をそのまま残す」ではなく、EMDの構造、情報量、文書順、Scene/Shot対応を変えないという意味で使う。H3自体が日本語を受理できる場合でも、本Compilerのtarget contractでは純粋な生成promptを英語で出力する。PromptTranslatorは日本語の描写文を英語へ翻訳するが、要約、補強、創作、並べ替え、重複除去、禁止文追加又は演出修正を行わない。

360文字を超えるunitは、既存の句点又は読点境界から二個以上のchunkを一意に作れる場合、初回推論前に120文字以下を目標として分割する。通常batchで日本語echo、欠落又は競合重複となった他のunitは一件だけで隔離再試行し、日本語echoが隔離再試行でも残る長文にも同じ分割回復を適用する。隔離再試行はsource unitが一件だけでslot対応が一意なので、異なる`TRANSLATION 1`が複数返った場合は空候補、日本語scriptを含む候補及びslot番号echoを除外し、応答順で最初の有効な英訳を無改変で採用する。候補数と`first_valid_english`選択規則はINFOへ記録する。ほぼ完成した英文に少数の日本語だけが残る場合は、英文候補全体を再翻訳せず、連続する残存日本語spanだけを出現順に一意化して同じstrict翻訳protocolへ通し、得た英訳を元位置へ機械置換する。同一spanの反復は一度だけ翻訳し、既存英文の語順と内容を変更しない。Compilerは原文文字列を変更せず、全span又は全chunkが英語になった場合だけ再結合する。短文、安全な境界のない長文又はspan cleanup・chunk翻訳にも日本語が残る場合は推測翻訳せず停止する。回復の隔離開始、分割・cleanup開始、各batch、完了又は失敗をslot番号・trigger・文字数・span数・chunk数とともにINFOへ記録し、正常完了statusへ`protocol_recovered`、`segmented_recovered`及び`cleanup_recovered`件数を出す。

翻訳へ渡す前に保護spanを自由文から分離し、翻訳後に原位置へ機械的に再結合する。保護対象はH3 binding、概念ID、`「...」`、作者が明示した`<d>...</d>`、MiniMax H3正式Camera Motion Typeと`with small amplitude`、`with large amplitude`、`at slow speed`、`at fast speed`、予約annotation、音響directive、Shotの``リップシンク 歌詞``である。保護span又はそのplaceholderは翻訳LLMへ渡さない。日本語括弧の台詞と明示された歌詞方式リップシンクは英訳せず`<d>[Japanese]...</d>`にし、作者が既に書いた`<d>...</d>`はlanguage labelの有無を含めて一文字も変更しない。概念IDとCamera directiveは自然な言い換えを生成せず原文を完全一致で再結合する。日本語、CJK又はHangul文字を含まない既存英語fragmentは翻訳batchへ入れず完全一致で保持する。

`translation_mode`は`ja_to_en`を既定とする。行単位の決定論的な文字種検査だけを行い、日本語、CJK又はHangul文字を含む行をPromptTranslatorへ渡し、それらを含まない行は既存英語としてpass-throughする。言語の意味推測やLLMによる分類は行わない。annotationはPlanへ出さず原文artifactに保持する。翻訳品質、文体又は意味を理由とするretryは行わず、欠落又は日本語script残存という機械条件に限り一度だけ隔離再翻訳する。

### 9.3 Context Loop出力

基準Context Loopの標準Plan shapeを使う。次は`00:00.000 --> 00:10.125`、`` `H3長` 243``の先頭Sceneについて、日本語本文を英訳し、``リップシンク Context Loop``を機械変換した例である。

```json
{
  "prompt_prefix": [
    "Render every scene as photorealistic live-action cinema with natural skin, physical fabrics, realistic moonlight, and cinematic lens depth.",
    "Use continuous grounded movement with readable weight shifts and delayed follow-through in the hair and clothing.",
    "Keep the face and full-body action readable while using parallax across the foreground, middle ground, and background."
  ],
  "defaults": {"steps": 8},
  "shots": [
    {
      "id": "scene_0001",
      "length": 243,
      "prompt": [
        "subject_definitions:",
        "<Subject 1> is described here: The protagonist has long black hair, short rounded pale-gold eyebrows, and white-and-vermilion clothing. Use these connected references only for its visual identity and design: <Picture 1>. Treat every panel or alternate view as identity material for the same single physical instance. Render exactly one physical instance of this Subject, with one head and one body. Never show a duplicate, twin, clone, reflection, background lookalike, inset view, split-screen copy, or second representation of this Subject. Do not copy a reference pose, framing, composition, panel layout, or background; follow the current Shot instead. The reference is identity evidence, not a storyboard, montage, or layout template. Render one unified full-frame continuous camera view that fills the entire image. Never create an internal border, seam, divider, panel, inset, picture-in-picture, side-by-side view, or simultaneous alternate angle. If the reference contains multiple views, fuse only compatible identity features into this one view. Camera angle and framing changes must happen over time or at a scene cut, never simultaneously within one frame. The current Scene environment and time-lighting directions are the sole authority for the rendered world and fully replace every background and illumination visible inside this identity reference. Treat any blank or white studio field, daylight, backdrop, panel-specific setting, or other conflicting reference environment as non-renderable source residue. Continue the specified Scene environment across the entire frame, including behind and around the Subject. Generate a newly staged Shot from the current action and camera instructions. The first output frame must already use the new Shot-specific body pose, gaze, blocking, framing, viewpoint, camera height, and camera distance. Never show, reconstruct, paste, hold, or transition from the reference image itself as a frame, still, plate, poster, inset, background, or composition.",
        "",
        "summary:",
        "[reference generation] A moonlit shrine approach with stone pavement and vermilion torii gates.",
        "",
        "retention_analysis:",
        "<Subject 1>: fully_preserved - preserve the described identity and attributes across shots.",
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

この例の`00:05.000`は、EMDの絶対Shot時刻からScene STARTを引いた値である。先頭Shotは時刻句を付けず`[Shot 1]`、2番目以降だけ`[Shot N] At MM:SS.mmm,`とする。これはContext Loop 0.6.9のRef2VA prompt構文であり、Planのms scheduling fieldではない。

Plan `prompt_prefix`には任意の`# シーン設定`の環境・時間照明baselineを先に置き、続いて`# 共通プロンプト`の存在する本文を`スタイル → 環境 → 時間・照明 → モーション → カメラ → その他`の順で一回出す。後段の明示Directionが観測baselineより上位になる順序であり、`##`見出しは出さない。各Sceneの`prompt`には完全なRef2VA六セクションを出す。Context Loop 0.6.9は実行時に`prompt_prefix`、空行二つ、Scene promptの順で機械連結する。`subject_definitions`では各`<Subject N>`を行頭から一回だけ定義し、`<Picture N>`等はそのSubject行の文中で関連付ける。背景Pictureは別の環境definitionを持ちSubjectへ数えない。既定`retention_analysis`はSubject marker及び存在する環境Pictureの保持契約を出す。作者が`# 保持分析`を明記した場合だけ、そのSubject記述を文書順で優先する。Subject定義と保持分析は各Sceneへ決定的に再掲するが、共通プロンプト本文をScene promptへ暗黙複製しない。annotationとprovenanceは含めない。

`prompt_prefix`は文字列又は文字列配列をContext Loopが受理するが、本Compilerは編集差分を読みやすくするため文字列配列だけを出力する。Context Loopの動的`{A|B}`解決はScene promptへだけ適用され、prefixには適用されないため、本Compilerもprefixへ動的候補を生成しない。prefix変更は全Sceneの完全prompt hashを変え、異なるprefixで生成したcheckpoint revision同士は一つの出力へ混在できない。

Context Loopのstrict Ref2VA analyzerは、prefix内の通常Style文を六セクション外のerrorにはしない。一方、`detailed_description:`内で`[Shot 1]`より前に求める1～2個のStyle文をprefixだけでは充足したと判定しない。実画像A/Bの結果、`illust_to_photoreal`ではPlannerが各Scene先頭Shotへ固定Style文を明示する。Compilerが本文の意味を推測して複製する処理ではない。

`# サブジェクト`に実在するPicture関連、`# シーン設定`の背景Picture及び任意の``リップシンク Audio参照``から次の独立出力を返す。いずれもなければ`references`は空配列になる。

```json
{
  "schema": "MVD_REQUIRED_REFERENCES_V2",
  "references": [
    {"concept_id": "サブジェクト1", "subject_ref": "<Subject 1>", "h3_ref": "<Picture 1>", "required_input": "ref_images.ref_image_0", "purpose": "visual_identity"},
    {"h3_ref": "<Picture 2>", "required_input": "ref_images.ref_image_1", "purpose": "environment_reference"},
    {"concept_id": "サブジェクト1", "subject_ref": "<Subject 1>", "h3_ref": "<Audio 1>", "required_input": "ref_audios.ref_audio_0", "purpose": "lip_sync_audio_reference"}
  ]
}
```

この一覧は接続要求であり、画像又は音声の内容をCompilerが認識したという主張ではない。同じ概念が視覚参照と音声参照を持つ場合は`purpose`で区別する。

### 9.4 音響・リップシンクdirectiveの固定写像

Compilerは音響又は歌詞の意味を推測しない。EMDに書かれた予約directiveだけを次へ写す。

| EMD | Scene JSON / promptへの出力 |
|---|---|
| `## 音響`なし | Scene固有の音声keyを出さずChain Policyを継承する。六セクションを満たす固定no-op文だけを音響欄へ出す |
| ``* `リップシンク` `Context Loop` `サブジェクト1` `` | `source_reference: "off"`、`generated_continuity: "off"`、`source_audio_target: "locked"`を出し、対象tokenを通常規則で写して標準lip-sync用固定prompt要素を一つ追加。vocal、Generation Profile、任意`H3_LIP_SYNC_OPTIONS`及び最終音声Chain Policyは対応する動画生成WFの責務 |
| ``* `リップシンク` `Audio参照` `サブジェクト1` `音声1` `` | 対象tokenと`<Audio 1>`を固定写像し、`{TARGET} performs visible lip movements synchronized to {AUDIO_TAG}.`を一つ追加。音声slotを`required_references`へ追加 |
| Shot内の``* `リップシンク` `歌詞` `サブジェクト1` 「千年鳥居をくぐるそなたよ」`` | directive内の対象と歌詞原文を当該Shot本文へ固定追加する。先頭は`[Shot 1]`、後続は`[Shot {N}] At {START},`を使い、Sceneのannotationは参照しない |
| ``* `明示台詞のみ` `` | 明示された`<d>...</d>`以外の発声を追加しない固定prompt要素を一つ追加 |
| ``* `無音` `` | `source_reference: "off"`、`generated_continuity: "off"`、`source_audio_target: "off"`と`Complete silence. No speech, music, ambience, or sound effects.`を追加 |

`無音`は非MV利用へ残す「無音条件のJSON要素を出す」という明示フラグである。初期MVスコープではPCM gateを実装しない。CompilerはPCMを変更せず、Sceneが本当に無音になるかを検査しない。またContext Loopの`final_audio`はPlan-wide Chain Policyなので、このScene JSONだけでglobal source soundtrackを消すとは主張しない。

``リップシンク Audio参照``と``リップシンク 歌詞``は`MiniMaxH3LipSyncOptions`及び`H3_LIP_SYNC_OPTIONS`を要求しない。したがって同経路で発生する追加モデル読み込み・初期化を回避できるが、H3本体の生成負荷を軽減する保証や、現行専用経路と同じ口形精度を保証するものではない。

Audio参照動画生成WFは入力vocalを事前にファイル分割しない。Lyric Segmentationが確定した`MVD_TIMELINE_V1.scenes[].source_start_ms` / `source_end_ms`をsource timeline adapterへ渡し、実行中のSceneに対応する連続vocal sliceを一個のnative `<Audio 1>`として`ref_audios.ref_audio_0`へ接続する。歌詞annotationの有無はSceneのAudio参照directiveを出す条件、各歌詞の`start_ms` / `end_ms`は整列結果とSRTの正本、Sceneのsource境界はPCM sliceの正本として役割を分ける。同じScene内の複数歌詞segmentを別Audio slotへ分けたり、segment間や歌い出し前の無音を除去して連結したりしない。CompilerはPCMを扱わず、固定promptと必要slotだけを出す。入力sliceの時間対応が正確であることと、H3出力が音素単位で完全に同期することは別の保証である。

### 9.5 最小限の文法エラー

Compilerが停止するのは次だけとする。

- 必須`# サブジェクト`、1～4行のSubject description、Scene番号annotation、Scene又は`` `H3長` ``がなく、Ref2VA EMDとしてparseできない。media bindingの欠如だけでは停止しない。
- 存在する`# 共通プロンプト`のsubsectionが重複、空、未知又は`スタイル → 環境 → 時間・照明 → モーション → カメラ → その他`の相対順に一致しない。
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
| visual-beats | 900 |
| song-direction | 900 |
| shot-layout | 400 |
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

Compiler wrapperは単純な構文・翻訳・直列化境界を保つため独自の成功cacheを持たない。成功時は`plan_json`と`required_references`をその実行の成果として返し、永続化はworkflow又は既存の出力保存nodeへ委ねる。`plan_json`は人間の比較とデバッグを容易にするため、Unicodeをescapeせず、keyを決定論的にsortし、2 space indent、LF改行及び末尾LFを持つpretty-printed JSONとして直列化する。JSONの空白は意味を持たず、Context Loopへ渡す値の構造はcompact JSONと同一とする。実GGUF比較では入力EMD hash、H3 timing profile ID、translator model fingerprint、chat format、量子化、system prompt version、seed及びsampling設定を外部の試験記録へ残し、異なる翻訳条件の結果を同一runとして扱わない。

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
- 一件以上の`unplaced_lyrics`がある場合、Lyric SegmentationはERRORログへ件数と先頭項目を出し、三データ出力を`ExecutionBlocker`にしてPlannerへ不完全なTemplateを渡さない。
- SRTは解決済みatomic segmentの本文、時刻及び順序をtimelineと一致させ、section見出しと未解決segmentを字幕本文へ入れない。Template EMDの歌詞annotation件数とSRT cue件数も一致する。
- Whisperが歌詞位置を検出し、粗い20ms VADの端をsample-domainで再探索して、有声境界を整数msで保持する。fixtureでは同じPCMから同じsample indexとmsを再現できる。
- PlannerがTemplate EMDを受けた場合、Whisperと音声解析を再実行しない。
- Fake LLMの行応答を、括弧又はJSON parserなしで`RECORD_TYPE`、短いslot、本文へ分離できる。行順が変わってもside tableで同じScene/Shotへ戻り、前置き、未知行又は重複recordがあっても他の有効recordを失わず、欠落slotだけを列挙できる。
- 空のuser requestでもdirectionが作れる。
- userの短い夜間・顔特徴指定がprovenance付きで最優先になる。
- plan Sceneが0から量子化済みplan終端まで隙間・重複なく並び、元音源尺との差を保持する。
- Template EMDと完成EMDの各Sceneが直前に連番の``> `シーン` N``を持ち、Sceneが`# シーン START --> END [継続]`、全Shotが`## ショット TIME`のplan絶対`MM:SS.mmm`で、Plannerによる境界mode確定後の整数msと一致する。
- Shot開始は規則どおりで、LLMが変更できない。CompilerはH3用のScene相対時刻だけを機械算出し、EMDへ書き戻さない。
- actionとcameraが同じShot IDへ合成され、互いの本文を再出力しない。
- 同じShotのactionとcameraを並行する全区間記述としてaction、cameraの順にrenderし、cameraは数値sub-time、mid-shot cut、新規Shot又はaction変更を生成しない。hard cutはshot-layoutがSceneへ選んだ`CUT`だけで表現する。
- Plannerが7.4の全socketを公開し、`n_ctx`を含むllama.cpp調整値とmodel overrideをcache signatureへ含める。
- Direction artifact未接続でもPlannerが動作し、接続時は六方向を再分類せず読む。Enhancerのpreviewは人間が確認できるがPlannerは再parseしない。
- provenanceは入力、採用行及び機械的破棄だけを固定enumで記録し、原文、LLMの意味判断又は推測した上書き理由を含めない。
- Plannerが作者由来の`「...」`と明示`<d>...</d>`をplaceholderでLLM入力から保護し、原文をPython所有位置へ一度だけ保持する。LLM新規生成の引用台詞及びplaceholder echoを削除し、引用出現を理由にLLMをretryしない。
- annotationが原文artifactに保持され、H3 promptへ漏れない。
- `<Subject N>`と任意の`<Picture N>`は`# サブジェクト`の予約行だけに現れ、自由文へ混在しない。
- `# サブジェクト`に`<Subject N>`と任意の`<Picture N>`を持つ完全Ref2VA EMDを、画像tensorなしでもCompiler単独で処理できる。Picture関連があれば接続要求を返し、なければ参照なしH3内蔵概念として空の必要参照一覧を返す。
- Picture関連のない完全EMDもRef2VAとしてコンパイルし、T2VA等へ暗黙fallbackしない。
- Lyric SegmentationがContext Loop基準contractのraw `length`、delivered frames、Scene境界及び量子化差分を確定し、Template EMDへ`` `H3長` ``を出せる。
- CompilerはEMDの`` `H3長` ``をPlan `length`へ無変換で写し、`duration_seconds`又は未対応の`duration_ms`を併記しない。
- Compilerが出した各Scene promptを基準Context LoopのRef2VA schema analyzerへ渡すと、正規六セクション、Shot順及び時刻構文にerrorがない。
- `# 共通プロンプト`と六区分がすべて省略可能で、Compilerが存在する翻訳済み行だけをスタイル、環境、時間・照明、モーション、カメラ、その他の固定順でPlan `prompt_prefix`へ入れる。スタイルがあれば先頭になり、全区分がなければfieldを出さない。
- 日本語EMDの描写文が英語へ一対一で翻訳され、情報追加・要約・並べ替えなしでPlanへ入る。
- 音響省略時はScene固有keyを出さず、`無音`がある場合だけ対応するoff値とsilence prompt要素を出す。
- `「...」`の内容を変更せず`<d>[Japanese]...</d>`へ包み、`明示台詞のみ`がある場合だけ追加発声禁止要素を出す。
- Shot本文に明示された`<d>...</d>`と`<d>[English]...</d>`を翻訳又は書換えせず、そのまま一回だけH3 promptへ出す。
- ``リップシンク Audio参照``を翻訳LLMなしで対象token、`<Audio N>`及び正規のH3固定英語文へ変換し、必要音声slotを返せる。
- Lyric Segmentationが同じatomic segment列からTemplate EMD、timeline、SRTを作り、歌詞annotationを割当て済みShotの直前へ配置できる。Plannerは数値包含で再対応付けせず対象付きの``リップシンク 歌詞``を生成し、Compilerはannotationを参照せず、Shot開始位置とdirective内の原文を順序どおりの`<d>[Japanese]...</d>`へ変換できる。
- 同一Sceneのリップシンク駆動方式は一つに限定され、後二方式では`H3_LIP_SYNC_OPTIONS`を要求しない。
- `model_name` comboから任意の利用可能なGGUFを選択でき、`ja_to_en`ではそのGGUFを内部PromptTranslator adapterで使う。`already_english`ではGGUFをloadしない。
- CompilerはIMAGE、AUDIO、上流node又はworkflow graphなしで単独実行できる。
- `MVDirectorAudioPadPair`だけが公開登録され、単体Audio Pad nodeは存在しない。通常のPair二出力はfull mixとvocalを共通尺へ末尾補完し、混合又は再同期しない。明示modeの参照専用追加出力だけがsource SceneをPlan frame位置へPCM無音で配置する。
- プレフィクスなしの日本語`subject_hint`と`additional_instruction`を外部STRINGから入力でき、`lock_identity`時だけ前者がuser authorityとしてEMDへ残る。
- Image to Subject EMDのprofile、hint policy、Picture mode、concept/subject/picture index、cache、解析解像度及びruntime設定を外部socketから上書きできる。
- `auto_h3`が同一IMAGEの`ref_image_N`接続を`<Picture N+1>`へ解決し、異なる番号への分岐を曖昧エラーにする。
- H3 Timing Profile、32-bit Seed、String Combo、Connected Combo、Load Text Fileを`MV Director/Utilities`から利用でき、旧`CL...` aliasは登録されない。
- Load Text FileからUTF-8歌詞をSTRINGとしてLyric Segmentationへ接続でき、workflow再読込時は埋め込み済み本文だけで再現できる。
- 上流LLMは16Kちょうど、1 token超過、単一対象超過を区別できる。
- 成功artifactを固定したままH3 seedだけ変更できる。
