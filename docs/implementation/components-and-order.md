# 既存部品の移植可否と実装順序

作成日: 2026-09-15<br>
状態: 初期調査に基づく選定。コード移植はまだ行っていない。

## 1. 判定基準

判定は「新仕様で必要か」を先に決め、その後に旧実装から再利用できる最小部分を探す。旧class、旧interface又は旧workflowを維持するための移植は行わない。再利用によって不要な設定、fallback、検査、prompt又は依存が連鎖する場合は、その部品をさらに小さく抽出するか新設する。

- `そのまま`: 責務が独立し、新方針と競合せず、名前空間・import・テストの調整だけで使える。
- `抽出`: 旧ノード全体は使わず、有限で検証可能なアルゴリズム又は基盤だけを新しい責務へ切り出す。
- `参考のみ`: 実績や回帰fixtureは使うが、実行フローやclassは移植しない。
- `移植しない`: 新方針と競合するか、初期最小経路に不要。

旧プロジェクトはGPL-3.0-onlyである。コードを実際にコピーする段階では新プロジェクトのlicenseを先に確定し、必要な著作権・license表示を保つ。今回コピーした旧コードはない。

## 2. 部品別判断

| 旧部品 | 判定 | 初期利用 | 根拠と扱い |
|---|---|---|---|
| `node_prompt_enhancer` | 参考のみ | profileの視覚的知見と実ログfixture | 文字一致の時刻競合、source分類、固定行追加、Merger、任意味監査が結合している。新Enhancerは一回の大局的統合として新設する |
| `node_mv_prompt_planner` | 参考のみ | 型名、失敗ログ、camera/motion表現 | Shot数・ACTION段階・AUX数・修復・再生成が絡む。新Plannerはtask分割とPython所有時間枠から新設する |
| `node_japanese_to_json` | 参考のみ | EMDの基本見出し、H3 frame-grid計算、翻訳入出力fixture、Context Loop回帰fixture | 多段の意味監査・修復・辞書・placeholder救済・6セクション固定文を持ち込まない。parser、限定翻訳adapter、compilerは新設する |
| `node_prompt_merger` | 移植しない | なし | 独立ノードを廃止。user authorityを含む統合はEnhancerのLLM責務にする。omit用部分一致も使わない |
| `node_seed32` | そのまま | 言語生成seedとH3 seedを供給 | `secrets.randbelow`、範囲`1..2^31-1`、ComfyUI cache制御が独立。package名、カテゴリ、logging importだけ調整する |
| `node_string_combo` + web拡張 | そのまま | user-defined preset選択が必要なworkflow | `|`/`||` parserとstale selection検出が独立。初期3 profileは静的comboでも足りるため、core完成後に追加する |
| `node_connected_combo` | そのまま | サブグラフ内部の頻繁に変更するcomboを外側へ引き出す | 接続候補の伝播という責務が独立している。`MVDirectorConnectedCombo`へ改名し、旧ID aliasは作らない |
| `common/gguf/discovery.py` | 抽出 | 全text node共通のGGUF探索とcombo | `models/LLM/GGUF`と追加`LLM` root、再帰探索、mmproj除外、相対ID、重複root表示、実path再解決を維持する。特定modelへ固定しない |
| `common/gguf/runtime.py` | 抽出 | text model lifecycle | load signature、解放、中断bridge、Qwen3 non-thinking処理を候補にする。旧`count_input_tokens()`の近似は予算確認に使わず、最終chat serialization計測を追加する |
| Vision `discovery.py` / `runtime.py` | 抽出 | observerのmodel+mmproj解決 | MTMDとprojector処理は再利用価値がある。旧観察repair、英語残存で全体再試行する経路は切り離す |
| Vision observation schema / renderer | 参考＋抽出 | Image to Subject EMDの可視事実、uncertainty、Subject/Picture関連 | 「見える事実だけ」「hintはauthorityだが視覚証拠を捏造しない」を維持。新しい`# サブジェクト` rendererへ合わせる |
| Vision `cache.py` | 抽出 | 成功観察cache | pixel、model、projector、推論条件、prompt版を含むkeyと原子的保存は有用。保存先schemaと型を新規化する |
| Vocal Whisper discovery/runtime | 抽出 | ローカルword timestamps | 遅延import、ローカルcheckpoint限定、自動download禁止を維持する |
| Vocal VAD | 部分抽出 | voiced/silent候補 | 20ms窓と区間整形は粗探索へ再利用する。境界近傍のsample-domain refinementを新設し、決定sample index、整数ms、threshold条件をartifactへ残す |
| Vocal lyrics parser/alignment | 抽出 | sectionと歌詞絶対時刻 | 原文・section・時刻を保持する部分を使う。未解決箇所のtargeted Whisper retryは初期経路へ入れず、`unplaced_lyrics`として返す |
| Vocal `build_scenes()` | 部分抽出 | Scene時間枠 | 連続被覆と最大長以下への均等分割だけを使う。旧整数秒量子化は破棄し、元音源msの要求範囲をContext Loop互換raw `17k+5`へ上流で割り当てる |
| Vocal `normalize_chainable_scenes()` | 抽出して再検証 | 短すぎる中間Sceneの調整 | H3 continuation前提に有用だが、旧定数とerror文が一致しない。新仕様の2000ms基準をテストで固定する |
| Vocal prompt Markdown renderer | 移植しない | なし | `//` metadata、H3 tag、Shot内lip-syncという旧形式を生成する。新annotation/audio構文と競合する |
| `CLAudioPad` | 移植しない | なし | 単体Audio Padは利用せず、node typeも登録しない。共通の入力検証とPCM padding処理が必要ならPair内部のprivate helperへ限定する |
| `CLAudioPadPair` | そのまま | full mix/vocalの共通尺への末尾無音補完 | `MVDirectorAudioPadPair`へ改名して再利用する。dtype/device/channel保持、非truncate、H3 frame targetを維持し、offset検出、resample、mixは追加しない |
| Context Loop `MiniMaxH3LipSyncOptions` | 外部の任意経路 | `ソースボーカル同期`を選んだworkflowだけ | 本プロジェクトへ移植しない。8GB VRAM環境で同経路の追加モデルload/initが停止する場合に備え、Compilerだけで出力できる`音声参照駆動`と`リップシンク歌詞`を別経路として実装する |
| `node_scene_limiter` | 初期は移植しない | なし | まず全pipelineと対象Scene単位cache/再開で成立させる。別ノードの切り出しは後続 |
| `node_text_file` + web拡張 | そのまま | 歌詞、LRC、SRT及び通常テキスト読込 | browser側D&D、UTF-8検証、workflow埋込、内容ベースcacheは独立している。`MVDirectorLoadTextFile`へ改名し、`.lrc`を選択候補へ加える。backend path読込、文字コード推測、監視及び旧ID aliasは持ち込まない |
| `node_vision_analyzer/graph_binding.py` | 抽出 | Image to Subject EMDの`auto_h3` Picture解決 | hidden `PROMPT`と`UNIQUE_ID`、`ref_image_0..8`、複数同番号許可、異番号曖昧エラー、binding fingerprintを再利用する。対応H3 class typeはContext Loop adapterへ分離する |
| `common/scene_anchors.py` | 概念のみ | 場所・固定構造物の維持 | 正規表現による意味抽出は使わず、Enhancerのprovenance付きdirectionへ統合する |
| `common/semantic_review.py`とreview prompts | 移植しない | なし | 同系統LLMの監査・修復を通常経路へ戻さない |
| compiler term dictionary | 移植しない | なし | 代替意味辞書を増やさない。固有の構造markerだけPythonで写像する |
| motion repair / performance policy | 移植しない | 回帰fixtureのみ | 動作語句、段階数、固定ACTION転記、placeholder復元は停止増加の主要因 |
| debug output | 抽出 | 数値metricsと任意artifact | 通常ログはtask、対象ID、token内訳、時間、retry理由だけ。prompt全文は明示debug時だけ |
| workflow test loader | 抽出 | JSONが現行node型・配線を持つか検証 | 旧workflow自体は新node仕様へ直接移行せず、短尺fixtureの入力と接続を参考にする |

## 3. 初期ディレクトリ案

過剰に層を増やさず、次を開始形とする。

```text
ComfyUI-MV-Director/
├─ __init__.py
├─ core/
│  ├─ artifacts/
│  ├─ audio/
│  ├─ emd/
│  ├─ h3_contract/
│  │  ├─ base.py
│  │  ├─ context_loop_0_6_6.py
│  │  └─ prompt_schema_ref2va.py
│  ├─ inference/
│  └─ timing/
├─ nodes/
│  ├─ __init__.py
│  ├─ node_image_to_subject_emd/
│  │  ├─ node.py
│  │  ├─ graph_binding.py
│  │  └─ schema.py
│  ├─ node_direction_enhancer/
│  ├─ node_timeline_planner/
│  ├─ node_emd_compiler/
│  ├─ node_lyric_segmentation/
│  ├─ node_audio_pad_pair/
│  ├─ node_h3_timing_profile/
│  ├─ node_seed32/
│  ├─ node_string_combo/
│  ├─ node_connected_combo/
│  └─ node_load_text_file/
├─ profiles/
│  ├─ creative/
│  └─ execution/
├─ prompts/
│  ├─ enhancer/
│  ├─ planner/
│  └─ compiler/
├─ web/
│  └─ js/
├─ workflows/
├─ tests/
└─ docs/
```

`core/`はComfyUIをimportせずFake backendでテストできるようにする。初期段階でrepository pattern、plugin system、汎用workflow engineは作らない。

公開node typeは4コアの`MVDirectorImageToSubjectEMD`、`MVDirectorDirectionEnhancer`、`MVDirectorTimelinePlanner`、`MVDirectorEMDCompiler`、supportの`MVDirectorLyricSegmentation`、`MVDirectorAudioPadPair`、utilityの`MVDirectorH3TimingProfile`、`MVDirectorSeed32`、`MVDirectorStringCombo`、`MVDirectorConnectedCombo`、`MVDirectorLoadTextFile`の11個で開始する。全追加nodeは`MVDirector`、custom socketは`MV_DIRECTOR_`を接頭辞とし、表示カテゴリは`MV Director/...`に置く。旧`CL...`又は`MiniMaxH3...`をaliasとして登録しない。Pythonの公開node packageをrepository rootへ散在させず、全て`nodes/node_*/`へ置く。

## 4. 実装順序

### Phase 0: 契約fixture

最初に実装するもの:

- `MVD_OBSERVATIONS_V1`、`MVD_EMD_FRAGMENT_V1`、`MVD_REFERENCE_BINDINGS_V1`、`MVD_DIRECTION_V1`、`MVD_TIMELINE_V1`、`MVD_EMD_TEMPLATE_V1`、`MVD_EMD_V1`、`MVD_REQUIRED_REFERENCES_V1`
- EMD（Easy MarkDown）canonical exampleとinvalid fixture
- `# シーン START --> END`と全`## ショット TIME`の絶対`MM:SS.mmm` fixture、Scene相対H3時刻への固定変換fixture
- Lyric Segmentationが要求msとH3 Timing Profileからraw `length`、delivered frames、plan Scene境界、量子化差分を得るfixture。Compilerが`` `H3長` ``を無変換で写し、`duration_seconds`と`duration_ms`をPlanへ出さないことも固定する
- `MVDirector...` node type、`MV Director/...` category、`MV_DIRECTOR_...` socketのnamespace fixture
- 日本語描写から英語promptへの一対一変換、保護span、`「...」`、3種類のリップシンク駆動、各音響directive、省略音響、`無音`併記、不正文法のfixture
- 音声参照slot、複数Shotと同一Shot内の複数`リップシンク歌詞`行、駆動方式の重複、不完全な歌詞directiveのfixture
- 旧ログ由来の「自然な動作なのに語句検査で止まった」入力fixture
- Context Loop 0.6.6 commit `136db5dbbf25405063a96e898ae880e8785b7f29`が受理する`prompt_prefix`先頭連結、Ref2VA六セクション、正規Shot構文、Planの最小valid fixture

完了条件:

- schemaとversionが固定され、旧形式との混在が明示エラーになる。
- 実モデル不要で全fixtureを読める。

### Phase 1: Compiler最小核

1. EMD見出し、Scene、Shot、annotationのparser
2. 翻訳対象unitと保護spanの分離
3. `PromptTranslator` interfaceとFake translator
4. Subject/Picture関連、`「...」`、予約音響directive及びShot単位`リップシンク歌詞`の固定写像
5. 英訳unitを元の位置へ一対一で復元
6. `# 共通プロンプト`からPlan `prompt_prefix`への一対一写像、Ref2VA六セクションrenderer、`` `H3長` ``の無変換コピー、標準JSON serialization

完了条件:

- 手書きの完全Ref2VA EMDとFake translatorだけを入れれば、英語の六セクションPlan JSONまで通る。
- Subject/Picture関連を持つEMDはIMAGEなしでもPlanとrequired referencesまで通る。
- 実LLM、Vision、Whisperなしで接続契約をテストできる。
- `## 音響`省略時はScene固有keyを出さず、`無音`明記時だけ対応するJSON要素を出せる。
- `音声参照駆動`は対象と`<Audio N>`を、`リップシンク歌詞`は所属Shotの開始位置、明記された対象、原文`<d>[Japanese]...`を、翻訳backendを呼ばず固定出力できる。
- EMDの絶対Scene/Shot時刻を変更せず、H3 prompt用Shot時刻だけをScene相対msへ機械変換できる。
- Context Loop PlanのScene長はEMDの`` `H3長` ``を`length`へ無変換で出し、Compiler内でframe計算しない。
- 後二方式のcompile及び実行契約は`H3_LIP_SYNC_OPTIONS`を要求しない。
- 描写文は英訳され、構造と順序は維持され、`「...」`の内容は原文のまま残る。

### Phase 2: 共通実行基盤

1. GGUF探索
2. `model_name` combo、相対ID、重複root識別、選択値の実行時再解決
3. model lifecycleと明示解放
4. final serialized requestのtoken計測
5. ComfyUI interrupt伝播
6. 成功cache、artifact固定、数値metrics

完了条件:

- 16Kちょうど、1 token超過、最小単位超過をFake tokenizerで再現できる。
- cancel/OOM/model errorを品質warningへ変換しない。
- 失敗artifactを成功cacheへ入れない。

### Phase 3: Image to Subject EMD

1. Vision観察の最小schemaとimage fingerprint
2. `subject_hint`と`additional_instruction`の独立STRING socket
3. `analysis_profile`、`hint_mode`、`hint_conflict`、`picture_reference_mode`、concept/subject/picture indexの外部override
4. プレフィクスなし日本語自然文の透過入力。名前付きプレフィクスの検出・除去は行わない
5. `# サブジェクト` EMD fragment renderer
6. `auto_h3`、`manual`、`none`とContext Loop adapter別の認識H3 class type
7. `<Subject N>`と`<Picture N>`の関連、optional binding manifest、同一IMAGE pass-through

完了条件:

- primary出力が編集可能なEMD文字列である。
- `none`又は`auto_h3`のunboundではPicture関連を作らず、IMAGE pass-throughと観察結果は返す。
- binding時はVisionに渡したものと同じIMAGE tensorだけをH3側へ分岐し、接続先`ref_image_N`から`<Picture N+1>`を決める。
- 同じPicture番号への複数分岐は許可し、異なる番号への分岐は曖昧エラーにする。
- 各hint/controlを外部socketから与えられ、接続値がローカルwidgetより優先される。
- `subject_hint`原文にラベルや構造記法がなくても日本語自然文として処理できる。
- `subject_hint`はuser authority、`additional_instruction`は観察焦点としてprovenanceが混ざらない。
- Scene、Shot、音響、カメラを生成しない。

### Phase 4: Enhancer

1. 任意concept EMDのschema adapter
2. 初期3 preset
3. user > vision concept > profile > generatedの統合prompt
4. 一回生成＋schema不正時だけ一回局所retry

完了条件:

- user requestが空でもdirectionを得る。
- Vision node又はconcept EMDがなくてもdirectionを得る。
- 「夜間」「丸く短い金色の眉」の短い指定が、長い旧手書きCommonなしでauthorityとして残る。
- time-of-day辞書やomit部分一致を使わない。

### Phase 5: Lyric Segmentation

1. ローカルWhisper一回による歌詞位置検出と歌詞alignment
2. 20ms VAD粗探索とsample-domain境界refinement、整数msの要求Scene、Shot候補生成
3. H3 Timing Profileによるraw `17k+5`、delivered frames、plan Scene境界の確定
4. annotationと`` `H3長` ``付き`MVD_EMD_TEMPLATE_V1` renderer
5. 解決済み原文だけの標準SRT serializer
6. SRTだけに適用する`srt_time_offset_ms`
7. ComfyUI node wrapper、成功cache、status

完了条件:

- LLM、Vision、Planner、H3なしでTemplate EMD、SRT、typed timelineを出せる。
- section見出しをSRT本文へ入れず、解決済み歌詞の文字列と順序を変えない。
- 未解決歌詞へ時刻を捏造せず、SRTから除外してtimelineとstatusへ残す。
- SRT offsetがTemplate EMD又は元timelineを変更しない。
- VAD境界、歌詞、Scene、Shotを整数msで保持し、整数秒へfloor/ceilしない。
- Template EMDの全Sceneと全Shotがplan絶対`MM:SS.mmm`で出力され、各Sceneの`` `H3長` ``がtimelineの`raw_length`と一致する。歌詞とSRTの元音源msは量子化しない。
- synthetic PCM fixtureでVAD refinementが同じsample indexと整数msを再現し、20ms格子へ戻らないことを検証する。

### Phase 6: Planner

1. Template EMD parserと確定Scene/Shot枠の取込み
2. lyric-notesと短いsong-direction
3. action batch
4. 確定actionを読むcamera batch
5. 外部接続可能なlip-sync driver、対象概念、音声slot control
6. Pythonによる同じShot IDへの合成、lip-sync directiveの挿入、完成EMD出力

完了条件:

- 全歌詞と全過去出力を各Sceneへ再投入しない。
- actionをcamera LLMに再出力させない。
- schema invalid以外の品質理由で自動retryしない。
- Template EMD入力時にWhisper又は音声解析を再実行しない。
- lip-sync driver controlをLLMへ渡さず、Pythonだけが有声Scene又は歌詞開始時刻を含むShotへ対応directiveを出す。

### Phase 7: Compiler node wrapper

1. `emd_text`、H3 timing profile、`translation_mode`、`model_name`とGGUF runtime設定を入力にする
2. Phase 1の純粋関数を呼ぶ
3. `plan_json`、`required_references`、文法エラーをComfyUIへ返す

完了条件:

- 上流custom socket、IMAGE、AUDIO、graph inspectionなしで単独実行でき、日本語modeではCompiler内部adapterが選択GGUFを使う。
- Picture関連のあるRef2VA EMDからrequired referencesを返し、関連がなければT2VAへfallbackせず停止する。
- 任意の利用可能なGGUFをcomboから選択できる。4B又は8Bを初期比較対象とし、翻訳seedは固定可能にするが、品質監査retry、意味辞書又はsemantic guardを持たない。
- 描写文だけを英訳し、補強、要約、並べ替え、重複除去又は自動言語判定をしない。
- `無音`は対応JSON要素の出力フラグとしてだけ動作し、PCM又は最終muxを検査しない。
- node wrapperに別の補正、cache、retry又はgraph inspectionを追加しない。

### Phase 8: ComfyUI workflow

1. `nodes/node_*/`から`MVDirector...`名前空間の4コアnodeを登録
2. `MVDirectorLyricSegmentation`と`MVDirectorAudioPadPair`をsupport nodeとして登録し、単体Audio Padを登録しない
3. H3 Timing Profile、32-bit Seed、String Combo、Connected Combo、Load Text Fileをutility nodeとして登録する
4. SRT単独、Ref2VA Compiler単独、Image to Subject EMD参照付き自動MVのworkflow fixtureを作る
5. 同一IMAGEをImage to Subject EMDとH3へ分岐し、`auto_h3`のPicture番号を検証する
6. 基準Context Loop 0.6.6のGeneration Profile、Plan `plan_json_input`、H3 Audio Tracks、Source Timelineへ接続する

完了条件:

- 旧custom nodeと旧workflowを上書きせず、`MVDirector...` type名だけでloadできる。
- Image to Subject EMDを削除しても、Picture関連を手書きした完全Ref2VA EMDからCompiler単独workflowがload・compileできる。
- full mixとvocalが同起点・同尺で、vocalを最終mixへ重ねない。
- 公開Audio padding nodeがPairだけで、単体Audio Padのtype IDが登録されていない。
- Lyric SegmentationだけのworkflowでSRTを保存できる。
- Load Text FileのSTRING出力をLyric Segmentationの歌詞入力へ接続できる。
- 32-bit Seedを分岐して言語生成とH3へ同じseedを渡せ、個別seedも独立固定できる。

## 5. 評価順序

### 5.1 テキスト生成の安定性

H3を動かす前に、短尺と通常尺で次を測る。

| 指標 | 内容 |
|---|---|
| 成立率 | 完成Plan / 実行回数 |
| stage別要求数 | Vision、Enhancer、lyric note、song direction、action、camera、Compiler prompt translation |
| token | serialized input、予約、実出力、余裕、実効上限 |
| 時間 | 最初の有効direction、EMD、Planまでと総時間 |
| 局所失敗 | schema、参照、予算、backend、Compiler文法 |
| 再利用 | cache hit、成功Sceneの保持率、再開対象 |
| 原文保持 | annotation、歌詞時刻、保護台詞、参照ID |

比較条件は同じ入力、同じmodel/量子化、同じ言語生成seed、同じprofileにする。Compiler翻訳は4Bと8Bを別条件として記録する。旧厳密監査との比較が必要な場合も、旧経路を新通常経路へ混ぜず、別runとして測る。

### 5.2 H3映像評価

テキスト成立後、固定PlanでH3 seedだけを変え、次を人間が評価する。

- 参照人物の同一性、顔特徴、体格、衣装、付属物
- 歌詞又は音楽への反応
- 人物動作の自然さ、接地、接触、反復
- カメラの読みやすさ、奥行き、軌道、単調さ
- Scene境界の連続性
- lip-sync、間奏、Scene境界を越えた最終full mixの連続性、追加発声の有無
- 採用候補を得るまでのseed数と手直し量

意味監査PASS数、ACTION行数、動作段階数を映像品質指標にしない。

## 6. 次に試す具体的な順番

1. Subject/Picture関連と`` `H3長` ``を持つ手書き日本語Ref2VA EMDをFake PromptTranslator付きCompiler単独で英語Planへ変換する。
2. 同EMDを画像なしでcompileし、required Picture一覧を検証する。
3. 20秒のsynthetic timelineで、Context Loop格子化後のScene/Shot/`` `H3長` ``/annotation/保護台詞をunit testする。
4. Image to Subject EMDの`none`、`auto_h3`、`manual`を同じ画像で比較する。
5. 旧短尺asset相当の歌詞とボーカルでWhisper一回のalignmentと未解決保持を測る。
6. Fake backendで4コアの一周と、手書きRef2VA EMDからCompilerだけの一周を通す。
7. 8B/16Kで`anime_emotional`だけを使い、短尺を3 language seedで生成する。H3はまだ動かさない。
8. 通常尺を同条件で実行し、要求数、token、時間、局所失敗を比較する。
9. 一つの固定Planを選び、H3 seedを3個だけ比較する。
10. その後にprofile差又はShot境界閾値のどちらか一方だけを変える。

同時に複数要因を変えず、未実測の改善を保証しない。
