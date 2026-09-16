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
<Subject 1> is described here: ... Use these connected references for it: <Picture 2>, <Video 1>.
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
* `サブジェクト1`: 顔立ち、髪、衣装、配色を保持する。
```

対象は`# サブジェクト`で定義済みでなければならない。章が省略された場合、Compilerは各Subjectに固定の保持文を出す。Picture参照を持つSubjectでは、そのPictureも自動保持対象になる。

## 5. 共通プロンプト

`# 共通プロンプト`は任意であり、次の任意subsectionを固定順で持つ。

1. `## スタイル`
2. `## モーション`
3. `## カメラ`
4. `## その他`

存在するsubsectionは一個以上の通常list itemを持つ。Compilerは見出しを除去し、本文をこの順序で翻訳してPlanの`prompt_prefix`へ一度だけ格納する。

```markdown
# 共通プロンプト
## スタイル
* 参照設計を保ちながら実写映画として描写する。
## モーション
* 接地と重心移動が読める連続動作にする。
## カメラ
* 前景と背景の視差を使う。
## その他
* 夜明けへ向かう静かな緊張感を保つ。
```

画風変換へ強く影響するため、Styleは`prompt_prefix`の先頭に置く。CompilerはStyleをSceneへ推測複製しない。

## 6. Scene

Sceneは番号annotationと見出しを物理的に連続する2行で書く。

```markdown
> `シーン` 1
# シーン 00:00.000 --> 00:10.125
* `H3長` 243
```

規則:

- Scene番号は1から連番。
- 時刻は`MM:SS.mmm`形式。
- Sceneは正の長さを持ち、前Sceneの終了と次Sceneの開始が一致する。
- 一Sceneは最大60000 ms。
- `H3長`はSceneの最初の行であり、選択したH3 timing profileの`17k+5` gridに適合する。
- `length`は秒又はmsではなく、Context Loopへそのまま渡すraw H3 lengthである。

`H3長`の後、最初のShotより前へ通常list itemを置くとScene descriptionになる。

## 7. Shot

各Sceneは一個以上のShotを持つ。最初のShotはScene開始時刻と一致し、後続Shotは絶対時刻で昇順にする。

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
* `サブジェクト1`: 顔立ち、髪、狐耳、尾、衣装と配色を保持する。

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
