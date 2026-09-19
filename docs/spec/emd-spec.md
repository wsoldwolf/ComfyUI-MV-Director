# MV Director EMD仕様

Status: normative

Schema: `MVD_EMD_V1`

Compiler target: Context Loop / MiniMax H3 Ref2VA

## 1. EMDとは

EMDは **Easy MarkDown** の略であり、Extended Markdownではない。

EMDは、人間、Vision node、Direction Enhancer及びTimeline Plannerが共有する行指向の中間表現である。Ref2VA EMD Compilerは、この文法を構文解析し、日本語のprompt本文だけを英訳して、Context Loop Plan JSONへ機械的に写す。

Compilerは演出の追加、要約、意味修復、画像内容の確認、音声区間の再推定又はH3出力品質の評価を行わない。

## 2. 文書構造

Compiler-ready EMDの順序は次のとおり。

1. 必須 `# サブジェクト`
2. 任意 `# 保持分析`
3. 任意 `# 共通プロンプト`
4. 一個以上のScene

空入力はEnhancerの入力として許されるが、Compiler-ready EMDとしては許されない。

## 3. サブジェクト

### 3.1 1行＝1 Subject

`# サブジェクト`直下では、一つのlist itemが一つのH3 Subjectを定義する。

```markdown
# サブジェクト
* `画像1` 狐耳の少女。金髪で赤い目を持ち、白と赤の着物風衣装を着ている。
* `画像3` 神社の境内。朱塗りの鳥居と石畳がある。
* 赤い宝石を持つ長剣。
```

文書順がbindingを決定する。

| EMD上の行 | 内部ID | H3 prompt上の意味Subject |
|---|---|---|
| 1行目 | `サブジェクト1` | `<Subject 1>` |
| 2行目 | `サブジェクト2` | `<Subject 2>` |
| 3行目 | `サブジェクト3` | `<Subject 3>` |
| 4行目 | `サブジェクト4` | `<Subject 4>` |

明示的な`人物N`、`場所N`、`物品N`、`H3サブジェクト`、`名称`行は使用しない。人物、場所、物品の区別はdescriptionの自然言語で表す。

Subjectは1～4行を必須とする。各行には空でないdescriptionが必要である。

### 3.2 media binding

各Subject行の先頭には、次のinline-code tokenを0個以上置ける。

| EMD token | H3 tag | slot範囲 | required input |
|---|---|---:|---|
| `画像N` | `<Picture N>` | 1..9 | `ref_images.ref_image_(N-1)` |
| `動画N` | `<Video N>` | 1..3 | `ref_videos.ref_video_(N-1)` |
| `音声N` | `<Audio N>` | 1..3 | `ref_audios.ref_audio_(N-1)` |

tokenはdescriptionより前に置く。同じSubject行で同じH3参照を重複させてはならない。media tokenのないSubjectは、外部参照を持たないH3内蔵概念として有効である。

```markdown
# サブジェクト
* `画像2` `動画1` 白いコートを着たダンサー。
* 夜明け前の海岸。
```

Compilerはこれを、概念的に次のSubject定義へ変換する。

```text
<Subject 1> is described here: ... Use these connected references only for its visual identity and design: <Picture 2>, <Video 1>. Treat every panel or alternate view as identity material for the same single physical instance. Render exactly one physical instance of this Subject, with one head and one body. Never show a duplicate, twin, clone, reflection, background lookalike, inset view, split-screen copy, or second representation of this Subject. Do not copy a reference pose, framing, composition, panel layout, or background; follow the current Shot instead. The reference is identity evidence, not a storyboard, montage, or layout template. Render one unified full-frame continuous camera view that fills the entire image. Never create an internal border, seam, divider, panel, inset, picture-in-picture, side-by-side view, or simultaneous alternate angle. If the reference contains multiple views, fuse only compatible identity features into this one view. Camera angle and framing changes must happen over time or at a scene cut, never simultaneously within one frame. The current Scene environment and time-lighting directions are the sole authority for the rendered world and fully replace every background and illumination visible inside this identity reference. Treat any blank or white studio field, daylight, backdrop, panel-specific setting, or other conflicting reference environment as non-renderable source residue. Continue the specified Scene environment across the entire frame, including behind and around the Subject. Generate a newly staged Shot from the current action and camera instructions. The first output frame must already use the new Shot-specific body pose, gaze, blocking, framing, viewpoint, camera height, and camera distance. Never show, reconstruct, paste, hold, or transition from the reference image itself as a frame, still, plate, poster, inset, background, or composition. Keep visible skin and clothing clean and intact unless an author-written Shot explicitly requires a physical condition. Lyric text inside <d> is vocal content only: figurative words about wounds, scars, pain, blood, or a broken heart never authorize a visible cut, scar, bruise, bleeding, bandage, lesion, stain, tattoo-like mark, torn skin, or damaged clothing.
<Subject 2> is described here: ...
```

### 3.3 内部ID

Shot、保持分析及びlip-syncでSubjectを参照する場合は、派生ID `サブジェクト1`～`サブジェクト4`をbacktickで囲む。

```markdown
* `サブジェクト1`は石畳を歩く。
```

定義されていない番号の使用は構文エラーである。通常本文中の「サブジェクト1」はIDではなく、backtickを持つ完全tokenだけがIDである。

## 4. 保持分析

`# 保持分析`は任意である。存在する場合は空にできず、各行を次の形にする。

```markdown
# 保持分析
* `サブジェクト1`: `partially_preserved` 髪、衣装、配色を保持する。
```

コロン直後の保持モードは ``fully_preserved`` 又は
``partially_preserved`` の固定tokenであり、省略又は翻訳できない。Compilerは
このtokenをH3の正規語彙としてそのまま出力し、後続の説明だけを英訳する。

`illust_to_photoreal`を使用する自動Plannerは、旧japanese2jsonで有効だった参照範囲限定を現行文法へ移し、各Subjectについて概念的に次を明記する。

```markdown
# 保持分析
* `サブジェクト1`: `partially_preserved` 髪型、髪色、衣装、配色及び装飾品を維持する。
```

同profileの`## スタイル`は、実写風生成に成功した保存Plan `context_loop_plan_00009.txt`の長い英語anchorを完全一致で持つ。さらに各Sceneの最初のShotへ``Shoot as a photorealistic live-action video, depicting the characters as real human actors.``を一回明示する。Compilerは既に英語の両方を翻訳器へ渡さず完全一致で写す。

対象は`# サブジェクト`で定義済みでなければならない。章が省略された場合、Compilerは各Subjectに固定の保持文を出す。この既定文は記述済みの局所形状、個数、配置、大きさ、色、材質及び除外条件を文字どおり保持し、特殊な特徴を一般的な形へ置換しないよう要求する。Picture参照を持つ場合もPicture自体を独立した保持対象として自動追加しない。

## 5. 共通プロンプト

`# 共通プロンプト`は任意であり、次の任意subsectionを固定順で持つ。

1. `## スタイル`
2. `## 環境`
3. `## 時間・照明`
4. `## モーション`
5. `## カメラ`
6. `## その他`

存在するsubsectionは一個以上の通常list itemを持つ。Compilerは見出しを除去し、本文をこの順序で翻訳してPlanの`prompt_prefix`へ一度だけ格納する。

```markdown
# 共通プロンプト
## スタイル
* 参照設計を保ちながら実写映画として描写する。
## 環境
* 苔むした大樹、石段及び古い鳥居が存在する深い森。
## 時間・照明
* 深夜。青白い月光が木々の間から差す。
## モーション
* 接地と重心移動が読める連続動作にする。
## カメラ
* 前景と背景の視差を使う。
## その他
* 夜明けへ向かう静かな緊張感を保つ。
```

画風変換へ強く影響するため、Styleは`prompt_prefix`の先頭に置く。`環境`は接触可能な物体を含む物理世界、`時間・照明`は完成映像の時間帯と照明を表し、明示された夜間等の演出指定はVisionで観測した昼夜より上位とする。Compilerはどの区分もSceneへ推測複製せず、存在する行を固定順で一対一翻訳する。

## 6. Scene

Sceneは番号annotationと見出しを物理的に連続する2行で書く。

```markdown
> `シーン` 1
# シーン 00:00.000 --> 00:10.125
* `H3長` 243

> `シーン` 2
# シーン 00:10.125 --> 00:20.042 継続
* `H3長` 260
```

規則:

- Scene番号は1から連番。
- 時刻は`MM:SS.mmm`形式。
- Sceneは正の長さを持ち、前Sceneの終了と次Sceneの開始が一致する。
- 見出し末尾の`継続`は直前Sceneの映像contextを使う明示フラグ。先頭Sceneでは使用できない。
- `継続`を省略したSceneはカットであり、前Sceneの映像contextを受け取らない。省略を暗黙継続とは解釈しない。
- 一Sceneは最大60000 ms。
- `H3長`はSceneの最初の行であり、選択したH3 timing profileの`17k+5` gridに適合する。
- `H3長`は秒又はmsではなく、選択済みのカット／継続modeに対応し、Context Loopへそのまま渡すraw H3 lengthである。Plannerがmodeを変更した場合はPlanner自身が累積H3格子へ再配分し、Compilerは再計算しない。

CompilerはカットSceneへ`context_length: 0`、`audio_context_length: 0`を出す。継続Sceneへtiming profileのvisual/audio context lengthと`continuation_mode: "guide"`を出す。`generated_continuity`は生成音声の別軸であり、この映像境界フラグの代用ではない。

`H3長`の後、最初のShotより前へ通常list itemを置くとScene descriptionになる。

## 7. Shot

各Sceneは一個以上のShotを持つ。最初のShotはScene開始時刻と一致し、後続Shotは絶対時刻で昇順にする。自動PlannerはPythonが提示した、互いに1500 ms以上離れた境界IDからだけShot境界を選び、最大4 Shot、通常は2～3 Shotとし、4 Shotは8秒以上のSceneで四つの異なる視覚目的を各2秒以上確保できる場合だけ選び、複数Shot時は各Shot 1500 ms以上とする。Scene全体が1500 ms未満の場合は一Shotのまま許す。LLMは時刻を生成せず、Pythonが境界IDを絶対msへ機械変換する。不正な候補列は該当Sceneだけ一Shotへfallbackし、ActionとCameraの処理を継続する。手書きEMDは同じ時刻規則を満たせばよい。

Scene内の後続Shotは一回のH3生成に含まれる時刻付きprompt変化であり、編集上のハードカットを保証しない。構図、画角又は視点を不連続に切り替える必要がある場合は、新しいSceneをカットとして開始し、そのScene見出しから`継続`を外す。

```markdown
## ショット 00:00.000
* `サブジェクト1`は石畳を踏みしめて前へ進む。
## ショット 00:05.000
* `サブジェクト1`は立ち止まり正面を向く。
```

Compilerは最初を`[Shot 1]`、後続をScene相対時刻の`[Shot N] At MM:SS.mmm,`へ変換する。

### 7.1 台詞保護

日本語の`「...」`は翻訳前に保護し、`<d>[Japanese]...</d>`としてH3へ渡す。

明示的な`<d>...</d>`又は`<d>[Language]...</d>`も翻訳しない。tagの不整合、nest又は未閉鎖は構文エラーである。

## 8. 歌詞annotation

Lyric Segmentationが生成するannotationは、対象Shot見出しの直前へ置く。

```markdown
> `セクション` VERSE1
> `歌詞開始` 00:02.300
> `歌詞終了` 00:05.800
> `歌詞` 千年鳥居をくぐるそなたよ
## ショット 00:00.000
* `サブジェクト1`は鳥居へ歩み寄る。
```

`歌詞`は必須、`セクション`は任意、開始と終了は両方を置くか両方を省略する。Compilerはannotation自体からlip-sync directiveを推測しない。

## 9. lip-syncと音響

### 9.1 歌詞方式

歌詞方式だけはShot本文内へ明示する。

```markdown
* `リップシンク` `歌詞` `サブジェクト1` 「千年鳥居をくぐるそなたよ」
```

Compilerは歌詞原文を翻訳せず、対象Shotへ次の固定文を追加する。

```text
<Subject 1> performs visible lip movements to <d>[Japanese]...</d>.
```

### 9.2 Scene音響方式

Scene末尾の`## 音響`は任意であり、存在する場合は空にできない。

Timeline Plannerで`context_loop`を選んだ場合は、歌詞annotationのない間奏又は末尾を含む全SceneへContext Loop directiveを明示する。これによりCompilerが全Sceneへ同じgeneration-time source音声方針を出力する。`audio_reference`は歌詞annotationのあるSceneだけに出し、歌詞方式は対応Shotだけに出す。手書きEMDでは必要なSceneへ明示し、Compilerは欠けたdirectiveを推測しない。

```markdown
## 音響
* `リップシンク` `Context Loop` `サブジェクト1`
```

```markdown
## 音響
* `リップシンク` `Audio参照` `サブジェクト1` `音声1`
```

```markdown
## 音響
* `明示台詞のみ`
```

```markdown
## 音響
* `無音`
```

規則:

- `Context Loop`、`Audio参照`及びShotの`歌詞`方式はScene内で相互排他。
- `Audio参照`の`音声N`は`<Audio N>`及び対応するrequired inputへ機械変換する。
- `無音`は他の音響directive又は歌詞方式と併用できない。
- `無音`はPlan JSONへ無音条件を出すフラグであり、PCM無音を保証しない。真の無音が必要な場合は下流PCM audio gateの責務。

## 10. 完全例

```markdown
# サブジェクト
* `画像1` 狐耳の少女。長い金髪、赤い瞳、白と赤の着物風衣装を持つ。

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
* 鳥居の奥へ進む静かな導入。
> `セクション` VERSE1
> `歌詞開始` 00:02.300
> `歌詞終了` 00:05.800
> `歌詞` 千年鳥居をくぐるそなたよ
## ショット 00:00.000
* `サブジェクト1`は石畳を踏みしめ、鳥居の奥へ進む。
* `リップシンク` `歌詞` `サブジェクト1` 「千年鳥居をくぐるそなたよ」
## ショット 00:05.000
* `サブジェクト1`は立ち止まり正面を向く。
```

## 11. Compiler出力契約

CompilerはContext Loop Plan JSONをUTF-8相当のUnicode文字列として返し、次の表示形式を規範とする。

- 2-space indent
- keyの決定的sort
- 非ASCIIを`\uXXXX`へescapeしない
- 末尾newlineあり
- NaN禁止

各Scene promptは次の6 sectionを固定順で持つ。

1. `subject_definitions:`
2. `summary:`
3. `retention_analysis:`
4. `detailed_description:`
5. `overall_soundscape:`
6. `non_diegetic_music:`

`summary:`は翻訳したScene先頭記述又は先頭Shot本文の前へ、Compilerが固定task directive ``[reference generation]``を付ける。`subject_definitions:`では各`<Subject N>`を行頭から一回だけ定義し、Picture等の参照tokenは同じ行の文中で関連付ける。`# 保持分析`が省略された場合、`retention_analysis:`はSubjectごとの固定保持文だけを持ち、Picture tokenを独立保持対象として自動追加しない。作者が`# 保持分析`を明記した場合、Compilerは固定modeをそのまま写し、説明だけを英訳して文書順で使う。保持範囲を意味推測で補正しない。

`required_references`は、Subject行及びAudio参照directiveで明示されたslotだけを列挙する。CompilerはComfyUI graphの実配線を検査しない。

日本語翻訳はline protocolで行い、一回の推論batchを最大7 unitに制限する。これは小型GGUFが長いslot列で番号を欠落又はshiftする事例を避けるためのprotocol上限であり、欠落slotを推測修復しない。

## 12. 構文エラーとしない事項

Compilerは次を意味検証しない。

- Subject descriptionと参照画像の内容的一致
- 人物、場所、物品という意味分類
- motion又はcamera指示の品質
- 音声内に実際の歌唱があるか
- required referenceがH3 nodeへ接続済みか
- 生成映像又は音響の品質

これらはPlanner、workflow又は利用者の責務である。
