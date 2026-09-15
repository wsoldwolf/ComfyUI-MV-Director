# EMD（Easy MarkDown）仕様書

版: `draft-0.10`<br>
作成日: 2026-09-16<br>
対象schema: `MVD_EMD_FRAGMENT_V1`、`MVD_EMD_TEMPLATE_V1`、`MVD_EMD_V1`<br>
対象Compiler: `MV Director - EMD Compiler (Ref2VA)`<br>
状態: 初期実装前のレビュー基準

## 1. 目的

EMDは**Easy MarkDown**の略であり、Extended Markdownではない。画像認識、歌詞時間解析、演出計画とH3向けJSONの間に置く、人間が読めて直接編集できる中間言語である。

EMD自身はH3 prompt JSONではない。日本語の構造化された制作意図を保持し、Compilerが次だけを機械的に行う。

1. EMD構造、Scene、Shot、参照、時刻及びdirectiveを構文解析する。
2. H3へ渡す自由描写だけを日本語から英語へ一対一で翻訳する。
3. Ref2VA六セクションとContext Loop Plan JSONへ直列化する。
4. 必要なPicture/Audio接続一覧を返す。

Compilerは演出の追加、要約、意味修復、参照画像の内容確認、音声区間の照合又はH3出力品質の評価を行わない。

## 2. 文書種別

| schema | 用途 | 必須部分 | Compiler入力 |
|---|---|---|---|
| `MVD_EMD_FRAGMENT_V1` | Image to Subject EMDが返す編集可能な断片 | `# サブジェクト` | 単独では不可 |
| `MVD_EMD_TEMPLATE_V1` | Lyric Segmentationが返す時間枠 | Scene番号annotation、1個以上のScene、`H3長`、Shot、任意の歌詞annotation | 未完成のため不可 |
| `MVD_EMD_V1` | Planner又は人間が完成させたRef2VA文書 | 一個以上のSubject定義、Scene番号annotation、1個以上の完成Scene。Picture関連と共通プロンプトは任意 | 可 |

初期の自動MV経路は一個のImage to Subject EMDだけをEnhancerとPlannerへ渡す。複数のSubject/Pictureを使う場合は、人間又は外部処理が完成EMDを構成してCompiler単独経路へ渡す。

### 2.1 Fragment例

Picture関連を持つ`MVD_EMD_FRAGMENT_V1`は次の形を取る。`picture_reference_mode=none`又は未接続の`auto_h3`では、`H3サブジェクト`を残して`参照画像`行だけを省略する。

```markdown
# サブジェクト
* `人物1`
* `H3サブジェクト` `<Subject 1>`
* `参照画像` `<Picture 1>`
* `名称` 主人公
* 長い黒髪と白と朱色の衣装を持つ人物。
```

### 2.2 Template例

`MVD_EMD_TEMPLATE_V1`は時間枠と歌詞annotationを持つが、Subject、共通プロンプト及び演出本文を完成させない。

```markdown
> `シーン` 1
# シーン 00:00.000 --> 00:10.125
* `H3長` 243
> `歌詞開始` 00:02.300
> `歌詞終了` 00:05.800
> `歌詞` 千年鳥居をくぐるそなたよ
## ショット 00:00.000
* 未計画
## ショット 00:05.000
* 未計画
```

`未計画`はTemplateで枠を可視化するplaceholderであり、Plannerは完成EMDを出す前に演出本文へ置き換える。Compilerは`未計画`を含むTemplateを完成EMDとして受理しない。

## 3. 文字とMarkdown規則

- 文書はUnicode文字列として扱い、保存時はUTF-8を推奨する。
- 改行は入力層でLFへ正規化する。
- 見出し記号、list記号、引用記号、backtick及びASCII spaceは構文の一部である。
- canonical list記号は`* `だけとする。`- `又は`+ `をaliasとして受理しない。
- 空行はblock間で使用でき、parserは構造上無視する。
- 予約見出しの大文字小文字、全角半角又は表記揺れを補正しない。
- 内部IDと予約labelはbacktickを含む完全なinline-code tokenとして認識する。
- 通常本文中の「人物1」はIDではなく、`` `人物1` ``だけがIDである。
- Markdownの見た目を整える自動修復、HTML decode又は未知labelの読み替えは行わない。

### 3.1 予約token

| token | canonical pattern | 範囲 |
|---|---|---|
| EMD時刻 | `[0-9]{2,}:[0-5][0-9].[0-9]{3}` | `MM:SS.mmm` |
| 内部ID | `` `(人物|場所|物品)N` `` | `N=1..16` |
| H3 Subject | `<Subject N>` | `N=1..4` |
| H3 Picture | `<Picture N>` | `N=1..9` |
| H3 Audio論理ID | `` `H3音声N` `` | `N=1..3` |
| H3 raw length | ASCII十進整数 | Timing Profileの範囲と格子に一致 |

表の`.`は説明上のピリオドではなく、EMD時刻ではliteral `.`として扱う。実装時の時刻正規表現ではdotをescapeする。構造行の先頭indent、全角spaceへの置換又は末尾commentは許可しない。自由本文の文字、空白及び句読点はこの制限を受けない。

## 4. 完成EMDの文書順

完成`MVD_EMD_V1`は次の順に並べる。

1. `# サブジェクト`
2. 任意の`# 保持分析`
3. 任意の`# 共通プロンプト`。直下を固定順の任意の`## スタイル`、`## モーション`、`## カメラ`、`## その他`に分ける
4. 必須の``> `シーン` N``を直前に持つ、1個以上の`# シーン START --> END`

同じtop-level見出しを離れた位置へ再掲しない。未知のtop-level見出しはV1では受理しない。

簡略構造を次に示す。これはparser実装用の完全な文字列正規表現ではなく、block関係を示す文法である。

```ebnf
emd_document       = subject_section, [retention_section],
                     [common_prompt_section], scene, {scene};
subject_section    = "# サブジェクト", subject_item, {subject_item};
subject_item       = concept_start_line, binding_line,
                     [picture_line], [name_line], {description_line};
concept_start_line = "* `", concept_id, "`";
retention_section  = "# 保持分析", retention_line, {retention_line};
common_prompt_section = "# 共通プロンプト", [style_prompt_section],
                        [motion_prompt_section], [camera_prompt_section],
                        [other_prompt_section];
style_prompt_section  = "## スタイル", prompt_line, {prompt_line};
motion_prompt_section = "## モーション", prompt_line, {prompt_line};
camera_prompt_section = "## カメラ", prompt_line, {prompt_line};
other_prompt_section  = "## その他", prompt_line, {prompt_line};
scene              = scene_annotation, scene_heading, h3_length_line,
                     {scene_description}, annotated_shot,
                     {annotated_shot}, [audio_section];
scene_annotation   = "> `シーン` ", positive_integer;
annotated_shot     = {lyric_annotation}, shot;
shot               = shot_heading, shot_body_line, {shot_body_line};
audio_section      = "## 音響", audio_directive, {audio_directive};
```

## 5. サブジェクト

### 5.1 内部ID

作品内IDは次だけを使用する。

- `` `人物1` ``～`` `人物16` ``
- `` `場所1` ``～`` `場所16` ``
- `` `物品1` ``～`` `物品16` ``

内部IDの番号はH3 slot番号ではない。内部ID、`<Subject N>`、`<Picture N>`を別の値として明示的に関連付ける。

### 5.2 canonical形式

```markdown
# サブジェクト
* `人物1`
* `H3サブジェクト` `<Subject 1>`
* `参照画像` `<Picture 1>`
* `名称` 主人公
* 長い黒髪と淡い金色の短く丸い眉を持ち、白と朱色の衣装を着た人物。
```

規則:

- ``* `人物N` ``、``* `場所N` ``又は``* `物品N` ``がSubject recordの開始を表す。`##`見出しは使用しない。
- recordは次の内部ID開始行又は次のtop-level `#`見出しの直前まで続く。
- `H3サブジェクト`は各recordの内部ID開始行の直後に一件必須とする。`参照画像`はその直後へ任意で一件だけ置ける。
- 完成EMDでも`参照画像`は省略できる。省略したrecordは文章だけで定義するH3内蔵概念であり、Compiler-readyである。
- `<Subject N>`は1～4で、完成EMD内で一意とする。
- `<Picture N>`は1～9。同じPictureを複数Subjectから参照できる。
- `名称`は任意で一件だけ置ける。Compilerは名称を参照内容の根拠として扱わない。
- 予約labelを持たない通常list itemはSubjectの自由描写として文書順を保持する。
- `<Subject N>`と任意の`<Picture N>`をSubject予約行以外の自由文へ直接書かない。
- Compilerは画像tensor又は配線を調査しない。

通常Ref2VAへの固定番号直接接続では、`ref_images.ref_image_0..8`が`<Picture 1..9>`に対応する。Image to Subject EMDの`auto_h3`は同一IMAGE pass-throughの接続先からこの番号を取得する。

### 5.3 `<Subject N>`を適用できる概念

`<Subject N>`は人物型に限定されたsocketではなく、prompt内で一貫して参照する意味上の主体labelである。V1では三種類すべてへ適用できる。

| 内部ID | Compilerの固定分類語 | 主な保持対象 |
|---|---|---|
| `` `人物N` `` | `person` | 顔、体格、髪、衣装、身体付属物、人物同一性 |
| `` `場所N` `` | `environment` | 建築、地形、空間配置、材質、照明、場所の同一性 |
| `` `物品N` `` | `object` | 形状、比率、材質、色、模様、部品構成、物品同一性 |

Compilerは内部IDの種類から上記分類語を機械選択し、例えば次の固定形を作る。

```text
<Subject 1> is the person defined by <Picture 1>.
<Subject 2> is the environment defined by <Picture 2>.
<Subject 3> is the object defined by <Picture 3>.
```

Picture関連がない場合は存在しない参照を補わず、次の固定形を使う。

```text
<Subject 1> is the person described here: ...
```

実画像条件をH3へ供給するのは`<Picture N>`と接続画像であり、`<Subject N>`だけでは画像条件を追加しない。場所の場合は一個の可動主体というより「同じ世界・空間」として扱うため、建築、地形、相対配置及び照明を明記する。物品の場合は形状、材質、部品数及び人物との接触関係を明記する。人物と同じ保持精度は保証せず、実出力で比較する。

## 6. 保持分析

`# 保持分析`は任意である。各行は既に定義された内部IDと、保持したい視覚条件を関連付ける。

```markdown
# 保持分析
* `人物1`: 顔立ち、髪、衣装、配色、身体付属物の数と形を保持する。
```

- 行順を保持する。
- 未定義IDを参照すると構文エラーにする。
- 内容の妥当性又は参照画像との一致は検査しない。
- 該当行がないSubject/Pictureには、Compilerが六セクション成立用の固定保持文を一行ずつ出す。LLMには生成させない。

## 7. 共通プロンプト

```markdown
# 共通プロンプト
## スタイル
* 実写映画として描画し、自然な肌、物理的な布、現実的な月光、映画的なレンズの奥行きを保つ。
## モーション
* 接地、重心、手と対象の接触、髪と衣装の追従が読める連続動作として描く。
## カメラ
* 顔と全身動作を読める距離を保ち、前景・中景・遠景の視差を使う。
## その他
* 全Sceneを通して夜から夜明けへの色温度変化を保つ。
```

- `# 共通プロンプト`自体と、`## スタイル`、`## モーション`、`## カメラ`、`## その他`はすべて省略できる。
- subsectionを置く場合は`スタイル → モーション → カメラ → その他`の相対順を守り、同じsubsectionを重複させず、一件以上の通常list itemを持たせる。前のsubsectionが省略されていてもよい。
- `## その他`は前三分類へ当てはまらない全Scene共通のフリーフォーム領域であり、予約directiveの代替にはしない。
- 4区分の外へlist itemを置かない。未知のsubsection及び順序違反は構文エラーにする。
- parserは`##`見出しだけで区分境界を決める。本文の語句をLLM、正規表現又はキーワード辞書で再分類したり、別区分から切り落としたりしない。
- Compilerは各区分の本文を別のtranslation unit群として扱い、区分内の行数と順序を保つ。その後、存在する本文だけを`スタイル → モーション → カメラ → その他`の固定順で平坦化し、Planの`prompt_prefix`へ文字列配列として一回だけ写す。全区分が省略されていれば`prompt_prefix` field自体を出力しない。
- subsection見出し自体は構造境界であり、翻訳せず`prompt_prefix`へ出力しない。スタイルが存在する場合、その最初の本文は必ず`prompt_prefix[0]`になる。
- スタイル先頭固定は、H3がprompt先頭の画風指定を画像変換の強い条件として解釈するという観察を検証可能な契約にするためである。Compilerは内容を意味判定して並べ替えない。
- スタイルを使う場合、その先頭行には生成先の目標画風を短い肯定文で書く。
- 元画像がイラストでも、実写化したい場合は「実写として描画する」のように生成先を記述する。
- `subject_definitions:`等の六セクション見出し、Shot marker、音響directive又は動的`{A|B}`候補を置かない。
- Compilerは共通プロンプトを各Scene本文へ意味推測で複製しない。
- Enhancerは`style_direction`、`motion_direction`、`camera_direction`、`other_direction`のうち生成したものだけを対応する区分へ書き、Subject record又は保持分析を書き換えない。Plannerは区分境界と順序を保持する。

## 8. SceneとShot

### 8.1 時刻形式

EMD時刻は`MM:SS.mmm`とする。

- `MM`は2桁以上。
- `SS`は`00`～`59`。
- `mmm`は3桁。
- 「10秒」、`10.5`、`00:10`又はSRT形式`00:00:10,500`を受理しない。
- EMD内のScene/ShotはPlan基準の絶対時刻である。
- 歌詞annotationは元音源基準の絶対時刻である。

### 8.2 Scene

```markdown
> `シーン` 1
# シーン 00:00.000 --> 00:10.125
* `H3長` 243
* 夜の神社の石畳の参道。月光が人物と朱塗りの鳥居を照らす。
```

- Sceneは半開区間`[START, END)`で、`END > START`とする。
- 各Scene見出しの直前の物理行に``> `シーン` N``を必須とする。間へ空行又はcommentを挟まない。
- `N`はASCII十進正整数で、文書先頭を1とし、Scene順に1ずつ増やす。重複、欠番、逆順又は0を許可しない。
- Scene番号は時刻又は配列indexからCompilerが推測・補正しない。
- 先頭Sceneは`00:00.000`から始める。
- 後続SceneのSTARTは直前SceneのENDと一致させ、隙間又は重複を作らない。
- 表示長は1～60000msとする。
- Scene見出し直後の最初の非空行を``* `H3長` RAW_LENGTH``とし、一件だけ置く。
- `H3長`はLyric Segmentation又は作者がH3 Timing Profileから確定した整数である。
- CompilerはScene時刻から`H3長`を再計算、丸め又は補正せず、Planの`length`へそのまま写す。
- V1のScene見出しには追加suffixを付けない。継続条件はScene位置とH3 Timing Profileが所有する。

### 8.3 Shot

```markdown
## ショット 00:00.000
* `人物1`は石畳を踏みしめ、鳥居の奥へ視線と身体を向ける。
* カメラは低い斜め前方から始まり、人物の側面へ移動する。
```

- 各Sceneに一個以上のShotを必須とする。
- 各Shotに一個以上の本文list itemを必須とする。
- 先頭Shot時刻はScene STARTと一致させる。
- 後続Shotは前Shotより後で、Scene ENDより前に置く。
- CompilerはH3 promptへ出す時だけ`shot_absolute_ms - scene_start_ms`を計算する。
- H3 promptでは先頭を`[Shot 1]`、後続を`[Shot N] At MM:SS.mmm,`とする。
- EMDの絶対時刻を書き換えない。
- `` `H3長` ``の後から先頭Shotまでにある通常list itemはScene全体の描写として扱う。

## 9. annotation

### 9.1 Scene debug annotation

```markdown
> `シーン` 3
# シーン 00:20.000 --> 00:30.000
```

Scene annotationは必須のデバッグ識別子である。Lyric Segmentationが`MVD_TIMELINE_V1.scenes[].scene_number`からTemplate EMDへ付与し、Plannerは変更せず保持し、Compilerは番号を検証してPlan Scene `id`へ`scene_0003`のように写す。4桁未満を0 paddingし、10000以上は切り詰めない。

Scene annotationは歌詞用pending metadataへ積まず、直後のScene見出しで即時消費する。翻訳せず、H3 prompt本文へ出力しない。エラー、artifact、cache診断及びログではScene番号を時刻範囲と一緒に表示する。

### 9.2 歌詞annotation

歌詞annotationはPlannerが読むcanonical timeline metadataであり、`off`、`context_loop`、`audio_reference`、`lyrics`のどの口形modeを選んでも完成EMDへ保持する。Compilerは最終H3 promptへ出さない。

```markdown
> `セクション` サビ
> `歌詞開始` 00:02.300
> `歌詞終了` 00:05.800
> `歌詞` 千年鳥居をくぐるそなたよ
## ショット 00:02.292
* `人物1`は正面を向く。
```

canonical順は`セクション`、`歌詞開始`、`歌詞終了`、`歌詞`である。

- `セクション`は任意。
- `歌詞開始`と`歌詞終了`は両方あるか、両方ないかとする。
- 終了は開始より後にする。
- `歌詞`は空にできない。
- 一件の`歌詞`でpending metadataを消費し、次の歌詞へ持ち越さない。
- Lyric Segmentationが空白又は物理改行で分割し、時刻を確定した一個のatomic lyric segmentにつき一組を置く。
- 同じShotへ割り当てた一組以上の歌詞annotation群を連続blockにし、その`## ショット`見出しの直前へ置く。各群は文書順に次のShotへ所属する。
- Lyric Segmentationは開始・終了がsource audio総尺内にあることを検証する。Compiler単独実行ではsource audioを持たないため、時刻形式と`終了 > 開始`だけを検証し、Plan基準Scene範囲との交差を要求しない。
- 複数行及び一行内の空白区切り歌詞は分割後の片ごとに別の`歌詞`recordへする。区切り空白は本文へ残さない。
- label後の値は翻訳、trim、Markdown unescape又はHTML decodeせず保持する。
- inline-code labelを持たない引用行は人間向けcommentとして保持できる。
- 未知のinline-code annotation labelは構文エラーにする。

Template EMD、`MVD_TIMELINE_V1`及びSRTはLyric Segmentationが作った同じsegment列を原文順で共有する。歌詞開始・終了はsource audio基準、Scene/Shot見出しはH3 Plan基準なので、PlannerとCompilerは数値包含で所属先を再計算しない。直後のShotという構造的配置をそのまま使い、segmentを再分割、結合又は別時刻へ移動しない。同じShotに複数segmentがあればannotationと``リップシンク 歌詞``をそれぞれ文書順に保持できる。

## 10. 台詞とShot単位リップシンク

### 10.1 保護台詞

Shot本文中の`「...」`は明示的な日本語直接話法である。

- Compilerは括弧内を翻訳又は言い換えず、`<d>[Japanese]...</d>`へ包む。
- Shot本文に作者が`<d>...</d>`を直接書いた場合は、開始tag、内容、任意の言語指定及び終了tagを一つのopaque spanとして翻訳せず、そのままH3 promptへ写す。
- `<d>[English]Stay with me.</d>`、`<d>[Japanese]ここにいて。</d>`及び言語指定のない`<d>Stay with me.</d>`はいずれも内容を変更しない。Compilerは言語を推定、検証、追加又は置換しない。
- 一つのShot本文に複数のwell-formed `<d>...</d>` spanを置ける。入れ子、開始tagだけ又は終了tagだけの不整合は構文エラーにする。
- 明示的な`<d>...</d>`を`「...」`規則で二重に包まない。span外側の通常描写だけを翻訳する。
- 話者、source audio又は時間との一致を検査しない。
- 閉じていない`「`は構文エラーにする。

PlannerがLLMを使って完成EMDを作る場合は、作者由来の`「...」`と明示`<d>...</d>`をLLM呼出し前にID付きplaceholderへ退避する。LLMにはJSON又はEMDを返させず、`TYPE<TAB>SLOT<TAB>TEXT`の行recordだけを返させる。Pythonが採用したrecordの`TEXT`で、既知placeholder以外にLLMが新規生成した引用台詞spanを無条件で削除し、既知placeholderだけを原文へ戻す。引用出現又は削除を理由にLLMをretryしない。歌詞から作る``リップシンク 歌詞``はfilter後にPythonが挿入する。

この生成台詞filterはPlannerの出力制御であり、Compilerの入力修復ではない。人間が完成EMDへ直接書いた`「...」`又は`<d>...</d>`をCompilerが削除することはなく、上記の保護規則で処理する。

### 10.2 ``リップシンク 歌詞``

```markdown
## ショット 00:02.300
* `人物1`は正面を向いて歌う。
* `リップシンク` `歌詞` `人物1` 「千年鳥居をくぐるそなたよ」
```

- ``リップシンク 歌詞``は`## 音響`ではなく対象Shotへ置く。
- 一行につき対象内部IDと一個の`「歌詞原文」`を必須とする。
- 同じShotに複数行を文書順で置ける。
- Plannerは直前に歌詞annotationが構造配置されたShotへそのまま配置し、歌詞時刻との数値包含を再計算しない。
- Compilerはannotationとの一致を検索又は補完せず、明記されたdirectiveだけを処理する。
- 歌詞原文は翻訳せず`<d>[Japanese]...</d>`へ包む。
- これはShot区間の可視口形を促すもので、音素又はframe単位の完全同期を保証しない。
- Plannerがこのdirectiveをmaterializeするのは`lip_sync_mode=lyrics`の時だけである。他のmodeでも歌詞annotationは人物動作・演出の入力として保持するが、このdirectiveへ変換しない。

## 11. 音響directive

`## 音響`は各Sceneの全Shot後に最大一回置く。

```markdown
## 音響
* `リップシンク` `Audio参照` `人物1` `H3音声1`
```

V1で受理するdirectiveは次だけである。

| directive | 引数 | 意味 |
|---|---|---|
| `リップシンク` `Context Loop` | 内部ID一個 | Context Loop標準経路で口形を駆動するScene宣言 |
| `リップシンク` `Audio参照` | 内部ID、`H3音声1..3` | `<Audio 1..3>`参照で口形を促すScene宣言 |
| `リップシンク` `歌詞` | 内部ID、`「歌詞原文」` | 対象Shotの歌詞から口形を促すShot宣言 |
| `明示台詞のみ` | なし | 明示した台詞以外の発声を追加しない固定promptを出す |
| `無音` | なし | Sceneの音声off値と完全無音promptを出す |

組合せ規則:

- ``リップシンク Context Loop``、``リップシンク Audio参照``、Scene内の一個以上の``リップシンク 歌詞``は相互排他とする。
- `無音`は同じSceneの他の音響directive又は``リップシンク 歌詞``と併記できない。
- 同一directiveを同じSceneへ重複して置かない。
- `H3音声N`を自由文又は他のdirectiveで使用しない。
- 未知directive又は引数個数の違う行は構文エラーにする。
- `## 音響`の省略は無音ではない。Scene固有の音声keyを出さず、下流Chain Policyを継承する。

mode切替は口形の実行方式だけを変える。`context_loop`又は`audio_reference`を選んでも歌詞annotationをEMDから削除せず、Compilerがmetadataとして読み飛ばす。これにより、同じ歌詞・Scene・Shot・人物動作を保ったまま口形方式だけを比較できる。

Plannerは独立した`vocal evidence`判定を持たない。`context_loop`又は`audio_reference`では、Lyric Segmentationが一個以上の歌詞annotationを構造配置したSceneだけへ対応directiveを出す。歌詞文字列、音量又はVAD区間をPlannerが再評価することはなく、annotationのない間奏Sceneへは出さない。

Audio参照動画生成WFは、Lyric Segmentationが`MVD_TIMELINE_V1`へ保存したSceneのsource開始・終了を使い、元vocalから現Sceneの連続PCM sliceを一個だけ作ってnative `<Audio 1>`へ渡す。各歌詞区間は整列とSRTの正本だが、複数区間を個別Audio slotへ割り当てたり、間の無音を除いて連結したりしない。CompilerはPCMの切出しをせず、明記された``リップシンク Audio参照``を固定promptと必要slotへ写すだけである。

完成動画にsource、generated又はnoneのどの音声を残すかはEMDへ書かない。これは対応する動画生成WFのContext Loop Chain Policyが所有する。従って「最終音声として保持」に相当するEMD directive、Planner option又はCompiler変換は存在しない。

通常Ref2VAへの固定番号直接接続では、`ref_audios.ref_audio_0..2`が`<Audio 1..3>`に対応する。固定socket又はPlan JSON自体には元音声上の開始・終了offset指定がないため、区間選択は動画生成WFのsource timeline adapterが接続前に行う。初期版はTagged Referenceの`@tag`をEMD文法として扱わない。

## 12. 完成例

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
* `リップシンク` `歌詞` `人物1` 「千年鳥居をくぐるそなたよ」
* カメラは低い斜め前方から始まり、人物の側面へ移動する。
## ショット 00:05.000
* `人物1`は鳥居へ歩み寄り、袖と髪が一歩遅れて追従する。
* カメラは歩行を横から追い、鳥居と社殿の奥行きを広げる。
```

## 13. Compilerへの固定写像

### 13.1 翻訳対象

次の自由描写だけを文書順で英訳する。

- Subjectの名称と説明
- 保持分析本文
- 共通プロンプトのスタイル、モーション、カメラ、その他本文
- Scene本文
- Shotの通常本文

次は翻訳から保護する。

- 内部ID、`<Subject N>`、`<Picture N>`、`H3音声N`
- 見出し、時刻、`H3長`
- annotationと音響directive
- `「...」`、作者が明示した`<d>...</d>`及び``リップシンク 歌詞``の原文

`as is`とは、構造、情報量、行順、Scene/Shot対応を変えないことを意味する。英訳そのものは行うが、補強、要約、創作、並べ替え又は意味修復は行わない。

### 13.2 Ref2VA六セクション

各Scene promptは次の正規順で生成する。

1. `subject_definitions:`
2. `summary:`
3. `retention_analysis:`
4. `detailed_description:`
5. `overall_soundscape:`
6. `non_diegetic_music:`

固定規則:

- `subject_definitions`: Sceneで使うSubjectと、存在する場合だけPicture関連をSubject説明と共に固定文型へ写す。参照なしSubjectは文章定義だけで出す。
- `summary`: Scene本文の先頭行を翻訳後そのままコピーする。なければ先頭Shot本文をmarkerなしでコピーする。
- `retention_analysis`: 明記された保持分析を写す。欠けたPicture関連には画像保持文を、参照なしSubjectには文章で定義した同一性と属性の保持文を固定出力する。
- `detailed_description`: Scene本文とShot本文を順序どおり出し、Shot markerとScene相対時刻だけを付ける。
- `overall_soundscape`: directiveに対応する固定文。指定なしでは`No scene-specific soundscape instruction is provided.`を出す。
- `non_diegetic_music`: 無音又は指定なしに対応する固定文を出す。最終soundtrackの選択は表現しない。

固定補完文は六セクション構造を成立させるrenderer処理であり、LLMに生成させない。

### 13.3 Plan field

- 任意の`# 共通プロンプト`の本文だけを`スタイル → モーション → カメラ → その他`の順で平坦化し、Plan `prompt_prefix`へ一回だけ写す。subsection見出しは出力せず、本文がなければfieldも出力しない。
- ``> `シーン` N``をPlan Scene `id`の`scene_NNNN`へ写す。
- `H3長`をScene `length`へ整数のまま写す。
- `duration_seconds`又は`duration_ms`をPlanへ追加しない。
- 先頭Sceneの`context_length`はTiming Profileに従い0、継続Sceneはprofile値を使う。
- リップシンクmode又は`無音`directiveを固定表に従ってScene JSON fieldとpromptへ写す。

### 13.4 必要参照一覧

```json
{
  "schema": "MVD_REQUIRED_REFERENCES_V1",
  "references": [
    {
      "concept_id": "人物1",
      "subject_ref": "<Subject 1>",
      "h3_ref": "<Picture 1>",
      "required_input": "ref_images.ref_image_0",
      "purpose": "visual_identity"
    }
  ]
}
```

``リップシンク Audio参照``があれば対応する`ref_audios.ref_audio_N`も追加する。この一覧は接続要求であり、Compilerが実tensor又は内容を確認したという意味ではない。

Picture関連もAudio参照もない場合は次を返す。これは未完成ではなく、参照なしH3内蔵概念だけで実行するCompiler-ready EMDを表す。

```json
{"schema":"MVD_REQUIRED_REFERENCES_V1","references":[]}
```

### 13.5 音響directiveの固定出力

| EMD条件 | Scene JSON | 固定prompt要素 |
|---|---|---|
| `## 音響`なし | 音声keyを追加しない | soundscapeに`No scene-specific soundscape instruction is provided.`、musicに`No additional non-diegetic music is requested.` |
| ``リップシンク Context Loop`` | `source_reference: "off"`、`generated_continuity: "off"`、`source_audio_target: "locked"` | 対象Subjectに対する標準lip-sync固定文を一件。vocal、Generation Profile、任意`H3_LIP_SYNC_OPTIONS`及び最終音声Chain Policyは動画生成WFが供給する |
| ``リップシンク Audio参照`` | 音声keyを暗黙追加しない | `{TARGET} performs visible lip movements synchronized to {AUDIO_TAG}.`。`{AUDIO_TAG}`は対応する`<Audio N>` |
| ``リップシンク 歌詞`` | なし | 対象Subject、Shot marker及び原文`<d>[Japanese]...</d>`を持つ固定文 |
| `明示台詞のみ` | なし | 明示された`<d>...</d>`以外の発声を追加しない固定文を一件 |
| `無音` | `source_reference: "off"`、`generated_continuity: "off"`、`source_audio_target: "off"` | `Complete silence. No speech, music, ambience, or sound effects.`及び`No non-diegetic music.` |

``リップシンク Context Loop``は標準経路を選ぶgeneration-time契約であり、Compilerは追加モデルのload、options objectの生成又は接続検査を行わない。``リップシンク Audio参照``と``リップシンク 歌詞``は同options objectを要求しない。

## 14. 文法エラー

Compilerが停止するのは次の場合に限定する。

- 必須section、Subject recordの`H3サブジェクト`、Scene annotation、Scene、Shot又は`H3長`がない。`参照画像`の省略だけではエラーにしない。
- 存在する共通プロンプトのsubsectionが重複、空、未知又は`スタイル → モーション → カメラ → その他`の相対順に一致しない。
- Scene annotationが見出しの直前にない、1から連番でない、重複又は時刻順と一致しない。
- section順、Scene範囲、Shot時刻又は番号範囲が不正。
- 予約binding、annotation又はdirectiveの書式・引数個数が不正。
- 未定義内部IDを予約構文から参照している。
- 同一`<Subject N>`、予約行又は音響directiveが不正に重複している。
- リップシンク方式が競合している。
- `無音`が他の音響directive又は``リップシンク 歌詞``と併記されている。
- 台詞又は歌詞方式リップシンクの括弧が閉じていない。
- Shot本文の`<d>` tagが不整合又は入れ子になっている。
- H3 Timing Profile又は`H3長`の整数・格子が不正。
- 翻訳backendが必要なのに選択又は実行できず、translation unitを一対一で返せない。

エラーには行番号、該当構文、期待する最小形式を含める。Compilerは自動修復、fallback又はretryを行わない。

## 15. Compilerが検査しない事項

- 参照画像とSubject説明の一致
- Picture/Audioの実配線又はtensor内容
- 演出、動作、カメラ、音響の作品的妥当性
- 歌詞、台詞、話者、口形又はsource audio区間の一致
- 翻訳の意味品質又はH3が指示に従ったか
- PCM無音、full mix/vocalの尺、mux又は最終音声波形

`無音`は対応JSON fieldと固定silence promptを出す明示フラグであり、PCM gateではない。

## 16. 非対応形式

- 旧`// 歌詞:`、`// 検出状態:`形式
- `` `対象N` ``、`` `画像N` ``、`` `H3対象N` ``、`` `H3画像N` ``
- Subject予約行以外に直接書いた`<Subject N>`又は`<Picture N>`
- 秒数表記、SRT時刻を混ぜたScene/Shot
- T2VA、I2VA、FL2VA又はL2VA向けmode
- Tagged Referenceの`@tag`
- 未知section、未知annotation又は未知directiveの黙示的保持
- 旧`ソース音声固定`、`ソースボーカル同期`、`音声参照駆動`又は`リップシンク歌詞`

互換parser、alias又は自動変換は作らない。別形式が必要になった場合は、既存V1の意味を変えず別Compiler又はversioned schemaとして追加する。

## 17. invalid例

SubjectとPictureを同じslotとして省略した例:

```markdown
* `人物1`
* `参照画像` `<Picture 1>`
```

完成EMDでは`H3サブジェクト`が欠けているためエラーになる。

Scene相対時刻をShotへ書いた例:

```markdown
> `シーン` 1
# シーン 00:10.000 --> 00:20.000
* `H3長` 260
## ショット 00:00.000
* `人物1`が歩く。
```

ShotはPlan絶対時刻でなければならず、先頭ShotがScene STARTと一致しないためエラーになる。

Scene annotationがない例:

```markdown
# シーン 00:00.000 --> 00:10.000
* `H3長` 243
## ショット 00:00.000
* `人物1`が歩く。
```

``> `シーン` 1``がScene見出しの直前にないためエラーになる。

共通プロンプトの順序が不正な例:

```markdown
# 共通プロンプト
## カメラ
* カメラは人物へゆっくり接近する。
## スタイル
* 実写映画として描画する。
```

`## カメラ`の後へ`## スタイル`が現れ、定義済みの相対順に一致しないためエラーになる。Compilerは本文を読んで区分を入れ替えない。

競合するリップシンク方式の例:

```markdown
## ショット 00:00.000
* `リップシンク` `歌詞` `人物1` 「歌詞」
## 音響
* `リップシンク` `Audio参照` `人物1` `H3音声1`
```

同じSceneで歌詞駆動と音声参照駆動が併記されているためエラーになる。

## 18. レビュー時の確認項目

- Subject/Pictureの予約行と番号体系が手書きしやすいか。
- Scene/Shotを絶対`MM:SS.mmm`で書く方式が読みやすいか。
- 必須の``> `シーン` N``がデバッグ時の識別に十分か。
- 共通プロンプトの四分割、全省略及びスタイル存在時の先頭固定が手書き及びEnhancer処理に十分明確か。
- `「...」`のJapanese shorthandと明示`<d>...</d>`のopaque pass-throughが明確か。
- 歌詞annotationとShotの``リップシンク 歌詞``が明確に分離されているか。
- `## 音響`の省略、三つのリップシンク方式、無音及び下流Chain Policyの違いが明確か。
- 六セクションの固定補完が「as is」の範囲として許容できるか。
- 初期自動MVを一参照に限定し、複数参照をCompiler単独経路へ残す境界が適切か。
