# MV Director EMD仕様

Status: normative

Schema: `MVD_EMD_V1`、音声活動付きは`MVD_EMD_V2`、口元計画付きは`MVD_EMD_V3`

Compiler target: Context Loop / MiniMax H3 Ref2VA

## 1. EMDとは

EMDは **Easy MarkDown** の略であり、Extended Markdownではない。

EMDは、人間、Vision node、Direction Enhancer及びTimeline Plannerが共有する行指向の中間表現である。Ref2VA EMD Compilerは、この文法を構文解析し、日本語のprompt本文だけを英訳して、Context Loop Plan JSONへ機械的に写す。

Compilerは演出の追加、要約、意味修復、画像内容の確認、音声区間の再推定又はH3出力品質の評価を行わない。

## 2. 文書構造

### 生成経路と出典のスコープ

Direction profileの任意`render_prompt`は、Motion/Cameraの詳細な計画規則と、EMDの短い
描画条件を分けるためのmetadataであり、EMD文法の新項目ではない。Plannerはprofile本文を
計画に使用し、レンダラはprofile所有本文に完全一致する項目だけを指定の描画文へ投影する。
作者の追加文と採用ActionはAS ISで保持する。詳細は[profile仕様](../../profiles/README.md)を参照。

開発用Scene author経路では、明示された `# モーション補完` だけを限定的な合成例外とする。
原LLM行を書き換えず、別の ``* `演技` 本文`` 行を追加する。補完はCompilerではなく
PlannerがCamera生成前に確定する。作者が演技又は一般Shot本文を書いたSceneは補完しない。
出所を示す次の注釈をShot本文領域で受け付ける。注釈は表示用で、Compiler promptには含めない。

```text
> `モーション補完` source=profile:anime_scene_composed_mv template=1 sha256=<本文のSHA-256小文字64桁>
```

sourceは `user` 又は `profile:<profile_id>`、templateは1ベースの候補番号。
これは手書きの演技・演出を生成後に意味修正する一般的な許可ではない。
入力記法と適用条件は[TIPS](../tips/mechanical-motion-and-perceived-performance.md)を参照。

Compilerは翻訳元をEMD fieldで区切り、共通文と局所Shotを同じ翻訳batchへ混在させない。
field ID・原文hashをINFO、採用結果との対応を成功キャッシュの`translation_trace`へ記録する。
これは出典分離であって、LLMの意味判断を機械的に訂正する処理ではない。

`dance_phrase`かつ有限Camera契約の場合、Python所有の画角・視点は継続グループの終端から
接続する。不可能な背面から正面顔への単純Zoomは同方向Arcで接続できる。自由文Actionの
意味や本文は変更しない。有限構造と自然文の責任範囲を混同しない。

Compiler-ready EMDの順序は次のとおり。

1. 必須 `# サブジェクト`
2. 任意 `# シーン設定`
3. 任意 `# 保持分析`
4. 任意 `# 共通プロンプト`
5. 任意 `# 音声活動`
6. 一個以上のScene

空入力はEnhancerの入力として許されるが、Compiler-ready EMDとしては許されない。

### 音声活動の参考メタデータ

Lyric Segmentationが保持する元ボーカルPCMの活動区間。これは自然文promptではなく、歌詞時刻と伴奏中の演技計画を読むための任意メタデータである。TemplateではSubjectなしの先頭、完成EMDでは共通プロンプトの後かつ最初のSceneより前に一度だけ置く。音声活動付きTemplateのartifact schemaは`MVD_EMD_TEMPLATE_V2`、完成EMDは`MVD_EMD_V2`。活動なしのV1は引き続き有効。

```markdown
# 音声活動
* `音声活動v1` sample_rate=48000 source_samples=480000 sha256=aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa method=energy_vad_sample_refined
* `ボーカル区間` 0 144000 no_vocal_candidate
* `ボーカル区間` 144000 384000 vocal_candidate
* `ボーカル区間` 384000 480000 no_vocal_candidate
* `参照PCM配置` 0 480000 0
```

sample位置は0ベースで終端を含まない。`ボーカル区間`は元PCM全体を重複・欠落なく時系列で覆う。許容stateは`vocal_candidate`、`no_vocal_candidate`、`instrumental_candidate`、`fullmix_silence_candidate`、`unknown`。VADと整列歌詞が食い違う場合は`unknown`へ保留する。ボーカルだけを解析するノードは伴奏の存在を確定できないため`no_vocal_candidate`を使う。全曲の無音指定や歌唱禁止を意味しない。

SHA-256は波形shape、sample rate、連続float PCMから算出する。`method`は`energy_vad_sample_refined`又は作者記述の`author`。任意の`参照PCM配置`は元PCM開始sample、元PCM終了sample、参照PCMでのコピー先開始sampleを表す。元PCMを順序どおり全量コピーし、コピー先は重複させず、間の隙間をpaddingとして扱う。Audio Pad Pairと同じ配置計算を用い、Scene開始時刻差で推測しない。

Plannerは選択したlip-sync方式のPCM時刻で現在Sceneへ切り出し、前後有声境界も参考情報として渡す。配置表のないAudio参照入力では時刻を推測せず通常計画へ戻る。歌詞のないSceneでは前後歌詞の短い抜粋を意味文脈として渡せるが、歌唱時刻として追加しない。候補を不採用にしても品質エラーにしない。

Compilerは音声活動を翻訳せず、Planルートの`mv_director_audio_activity`へ診断情報として保持する。H3の共通prefix、Shot本文、audio mask、既存のリップシンク指定には変換しない。音声・歌唱タイミングのH3上の保証は別問題である。

このメタデータの保存先はCompiler出力のPlan JSONである。現在のContext Loopは独自のPlan正規化時にこの追加キーを利用せず、内部Planへも継承しない。診断の長期保存には元EMD又はCompiler出力を保存する。

### Plannerが確定する口元計画

音声活動は検出事実であり、口元は映像上の演出意図である。Plannerは既存のPCM時刻対応を使い、lip-sync対象の人物について長い無声区間を`閉口`、有声区間を`歌唱`として計画する。閉口は唇を軽く合わせる意図であり、身体・目・眉・頬を静止させる指定ではない。Compilerは検出情報から口元を再判定せず、Planner又は作者が明示した口元計画だけを変換する。

Sceneの`H3長`及び任意の概要行の後、最初のShotより前に置く。

```markdown
> `シーン` 1
# シーン 00:00.000 --> 00:10.125
* `H3長` 243
> `口元` `サブジェクト1` 00:00.000 --> 00:04.800 `閉口`
> `口元` `サブジェクト1` 00:05.000 --> 00:10.125 `歌唱`
## ショット 00:00.000
* `演技` 人物は踏み替えと身体の捻りをつなぎ、目と眉で感情を表す。
## 音響
* `リップシンク` `Context Loop` `サブジェクト1`
```

許容stateは`閉口`、`歌唱`、`自由`。対象Subjectは定義済みのものとし、各区間はScene内の正の長さ、開始を含み終端を含まない。同じSubjectの区間は時系列で重複させない。Scene全体を覆う義務はなく、未指定部分と`自由`には局所的な口元補足を加えない。時刻は当該lip-sync方式の生成用PCMと対応する絶対時刻で、元の検出PCM sampleとは区別する。口元境界はShot境界に一致しなくてよく、Shot・Sceneの分割を追加しない。

Plannerの自動計画は次の規則に従う。

- 連続する既知の無声候補が2秒以上の場合だけ閉口を計画する。長さはSceneで切る前に判定する。
- 有声区間の前後200msは自動閉口から除外し、発音準備・余韻の余地を残す。これは初期方針の値であり、H3での同期を保証する値ではない。
- `unknown`、短い息継ぎ、追加padding、活動情報なしには自動閉口を加えない。
- Audio参照は既存の参照PCM配置表を使用し、配置表がなければ自動計画を省略する。
- `lip_sync_mode=off`では音声活動による自動計画を行わない。作者の明示した口元は保持する。
- 作者の口元アノテーションが最優先。作者が確定した`演技`、歌詞lip-sync又はラベルなしShot本文のある時間には、自動指定を加えない。固定Cameraだけなら自動計画を妨げない。

作者はTemplate EMDの同じ構文をPlannerへ渡すか、完成EMDへ直接書いてCompilerへ渡せる。TemplateのSubject番号は接続された人物定義へ結び付ける。演出候補は従来どおり着想であり、この時間付き確定指定とは区別する。

Plannerは口元計画を既存のPerformance・Camera推論へ渡し、出力は従来のline protocolを維持する。追加LLM段階、本文の語句検索による修復、口元品質による生成停止は設けない。結果はPlanner成功キャッシュにも保持する。

口元付きTemplateのartifact schemaは`MVD_EMD_TEMPLATE_V3`、完成EMDは`MVD_EMD_V3`。既存V1・V2も有効であり、音声活動だけを持つ旧EMDをCompilerへ渡しても口元を自動補完しない。

Compilerは口元を英語の時間付き肯定文として局所本文へ写す。継続SceneではTiming Profileの映像context framesを秒へ換算して加え、生成クリップの保護プレフィックス後へ指定を置く。全Sceneが同じSubjectへの閉口指定で覆われる場合は、そのSubjectへの一括歌唱文を重ねない。ただし`source_audio_target="locked"`などの音声方針は音響directiveから従来どおり生成する。

独自の`mouth_closed` JSONキーや顔の映像マスクではなく、H3の`prompt`に作用する演出指定である。閉口の映像的な遵守は短区間で検証する必要がある。

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

本文と参照tokenの対応は次のとおりである。英訳の文言は翻訳backendに依存するが、
Subject番号と参照番号は原文から機械的に決まる。

| 原文のSubject行 | H3 Subject | descriptionの英訳例 | 接続参照 |
|---|---|---|---|
| 白いコートを着たダンサー。 | `<Subject 1>` | A dancer wearing a white coat. | `<Picture 2>`, `<Video 1>` |
| 夜明け前の海岸。 | `<Subject 2>` | A coast before dawn. | なし |

Compiler出力のうち、本文と参照の対応だけを抜粋すると次のようになる。
識別保持・単一instance・参照構図非継承等の固定付加文は、この例では省略している。

```text
<Subject 1> is described here: A dancer wearing a white coat.
Use these connected references only for its visual identity and design: <Picture 2>, <Video 1>.
<Subject 2> is described here: A coast before dawn.
```

上例の改行は説明用であり、実際の定義の行分割を規定しない。
参照は一行目のSubjectだけに属し、二行目へ継承しない。
二行目は原文で`# サブジェクト`に書かれているため、場所の記述であっても
`<Subject 2>`となる。共通背景として扱いたい場合は、その行を
`# シーン設定`の`## 環境`へ記述する。

### 3.3 内部ID

Shot、保持分析及びlip-syncでSubjectを参照する場合は、派生ID `サブジェクト1`～`サブジェクト4`をbacktickで囲む。

```markdown
* `サブジェクト1`は石畳を歩く。
```

定義されていない番号の使用は構文エラーである。通常本文中の「サブジェクト1」はIDではなく、backtickを持つ完全tokenだけがIDである。

## 4. シーン設定

`# シーン設定`は、背景の観測事実と環境専用PictureをSubjectから分離して運ぶ任意断片である。存在する場合は`# サブジェクト`の直後、`# 保持分析`より前に置く。

```markdown
# シーン設定
## 環境
* 森の中の神社境内、赤い鳥居、石畳の参道、紅葉及び道端の灯籠。

## 時間・照明
* 夜間。月明かりと灯籠の暖色光がある。

## 背景参照
* `画像2`
```

`## 環境`は必須で一個以上の通常list itemを持つ。`## 時間・照明`は任意で観測時のbaselineを持つ。`## 背景参照`は任意で、`画像1`～`画像9`のうち一個だけを持つ。subsectionはこの順序を変えない。

背景Pictureは環境証拠であり、Subjectを追加しない。Compilerはこれを環境専用definition、`environment_partially_preserved`保持行及び`environment_reference` required inputへ変換する。人物、pose、文字、分割構図、camera angle又は参照画像の照明をコピーする用途には使わない。`# 共通プロンプト`又はDirectionで明示された環境、時刻及び照明は、この観測baselineより上位である。

## 5. 保持分析

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

## 6. 共通プロンプト

### 計画入力だけで使う演出候補ディレクティブ

Direction Enhancerの既存`user_request`には、`# 演出候補`セクションの箇条書きを任意に記述できる。最大12行、各本文500文字までとし、行の順序と自然文を保持する。これは**完成`MVD_EMD_V1`には存在しない計画入力専用section**である。Directionがユーザー入力から構文だけを抽出してtyped artifactへ保持し、通常の共通プロンプトへ混ぜない。Plannerは現在SceneのEvent、Performance、Cameraへ候補を原文のまま渡し、局所的な着想として扱う。候補の採用・変形・不採用はいずれも有効であり、Pythonは対象や動詞を辞書で選ばない。候補の原文はCompiler及びH3の全Scene共通`prompt_prefix`へ渡らない。別のPlanner入力ソケットは設けない。

```markdown
# 共通プロンプト
## 時間・照明
* 夜間を基調とする。

# 演出候補
* 苔を扱う場面では、参道脇の大木の根元に生えた苔へ人物が近づき、指先で撫でる。
```

この例の`# 演出候補`セクションはDirection入力時に分離される。完成EMDの`# 共通プロンプト`へ同じ見出しを手で直接追加すると、後述の完成EMD文法上は未知sectionとして拒否される。演出候補はこのセクション内に通常の箇条書きで記述する。ユーザー指定の場面候補は必須の歌詞対象でも共通背景命令でもない。

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

## 7. Scene

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

## 8. Shot

各Sceneは一個以上のShotを持つ。最初のShotはScene開始時刻と一致し、後続Shotは絶対時刻で昇順にする。自動PlannerはPythonが提示した、互いに1500 ms以上離れた境界IDからだけShot境界を選び、最大4 Shot、通常は2～3 Shotとし、4 Shotは8秒以上のSceneで四つの異なる視覚目的を各2秒以上確保できる場合だけ選び、複数Shot時は各Shot 1500 ms以上とする。Scene全体が1500 ms未満の場合は一Shotのまま許す。LLMは時刻を生成せず、Pythonが境界IDを絶対msへ機械変換する。不正な候補列は該当Sceneだけ一Shotへfallbackし、ActionとCameraの処理を継続する。手書きEMDは同じ時刻規則を満たせばよい。

Scene内の後続Shotは一回のH3生成に含まれる時刻付きprompt変化であり、編集上のハードカットを保証しない。構図、画角又は視点を不連続に切り替える必要がある場合は、新しいSceneをカットとして開始し、そのScene見出しから`継続`を外す。

```markdown
## ショット 00:00.000
* `サブジェクト1`は石畳を踏みしめて前へ進む。
## ショット 00:05.000
* `サブジェクト1`は立ち止まり正面を向く。
```

Compilerは最初を`[Shot 1]`、後続をScene相対時刻の`[Shot N] At MM:SS.mmm,`へ変換する。

### 8.1 用途を明示したShot本文（Scene Author）

通常の箇条書きに加え、各Shotは``演出``、``演技``、``カメラ``の
いずれかを先頭tokenに持つことができる。ここで`演出`は対象・空間・外部現象の
出来事、`演技`は人物の身体・顔の演技、`カメラ`は撮影を指す。

```markdown
## ショット 00:05.000
* `演出` 大樹の根元に生えた苔が風を受けて揺れる。
* `演技` 人物は片足へ荷重し、根元の苔へ指先を寄せて離す。
* `カメラ` Arc Shotで大樹との距離と人物の表情を一続きに見せる。
```

これらのtokenは作者が書いた役割を示す構造であり、H3の自然文には混入させない。
Compilerは本文を英訳し、構造を使って局所的な優先順位を解決する。`演技`を
明記したShotでは全曲共通の``## モーション``をそのShotに重複注入せず、
`カメラ`を明記したShotでも同様に``## カメラ``の重複を避ける。他のShotには
これらの共通項目が継承される。作者が明記したShot本文をCompilerが創作・置換
することはない。ラベルなし箇条書きは従来どおり有効だが、その責務は自動推定しない。

現行Plannerは全profileでScene Authorを使用し、
元TemplateのShot境界・Sceneの継続指定を保ち、作者が書いた用途別項目は固定する。
未指定の出来事、人物演技、撮影だけをScene単位で順に生成する。演出候補は出来事
担当と人物演技担当へ原文のまま渡す任意の着想で、必須条件ではない。
セクションの連続区間に属する原歌詞を読み取り文脈として渡すが、当該Sceneの
歌詞時刻を変更せず、区間全体を描写する義務も作らない。元見出しIDのないTemplate
では隣接同名見出しを区別できない。作者の固定本文は後続担当へ渡すが、
Pythonは意味を推測して文章を書き直さない。完成済み`# サブジェクト`から始まる
全文EMDをPlannerの`template_emd`へ入れた場合は、検証後にLLMとprofile生成を
通さずそのまま返せる。通常はCompilerへ直接入力してもよい。

### 8.2 台詞保護

日本語の`「...」`は翻訳前に保護し、`<d>[Japanese]...</d>`としてH3へ渡す。

明示的な`<d>...</d>`又は`<d>[Language]...</d>`も翻訳しない。tagの不整合、nest又は未閉鎖は構文エラーである。

## 9. 歌詞annotation

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

## 10. lip-syncと音響

### 10.1 歌詞方式

歌詞方式だけはShot本文内へ明示する。

```markdown
* `リップシンク` `歌詞` `サブジェクト1` 「千年鳥居をくぐるそなたよ」
```

Compilerは歌詞原文を翻訳せず、対象Shotへ次の固定文を追加する。

```text
<Subject 1> performs visible lip movements to <d>[Japanese]...</d>.
```

### 10.2 Scene音響方式

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
- `Context Loop`は`source_audio_target=locked`等の音声設定に加え、指定Subjectが入力ボーカルの有声句に合わせて歌い、既存の身体演技と並行して口・顎を音節に同期させる固定文を`overall_soundscape`へ出力する。音声の同期対象と人物の可視歌唱を結び付ける音響契約であり、個別Action／Cameraによる共通文の継承抑制とは独立する。Action／Camera本文・Scene長・歌詞時刻は変更せず、顔アップを強制しない。有声句に限定する指示であり、無声区間への歌唱の追加や音素同期の保証ではない。
- Compilerが生成する説明用の固定文へ、未閉鎖の発話特殊トークンを含めない。明示された発話・歌詞の`<d>...</d>`は従来どおり保持する。
- `Audio参照`の`音声N`は`<Audio N>`及び対応するrequired inputへ機械変換する。
- `無音`は他の音響directive又は歌詞方式と併用できない。
- `無音`はPlan JSONへ無音条件を出すフラグであり、PCM無音を保証しない。真の無音が必要な場合は下流PCM audio gateの責務。

## 11. 完全例

```markdown
# サブジェクト
* `画像1` 狐耳の少女。長い金髪、赤い瞳、白と赤の着物風衣装を持つ。

# シーン設定
## 環境
* 森の中の神社境内、赤い鳥居及び石畳の参道。
## 時間・照明
* 夜間。月明かりが木々の間から差す。
## 背景参照
* `画像2`

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

## 12. Compiler出力契約

denoising step数はEMD及びCompilerの責務に含めない。Compilerは`steps`入力を持たず、Plan JSONの直下、`defaults`及びScene要素へ`steps`を出力しない。動画生成時にContext Loop Planノードの`default_steps`で全Scene共通に指定する（配布WFの既定は20）。旧Planを再利用する場合は、JSON内のstep指定がノード値より優先されるため、その指定を除去してから使用する。

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

`required_references`は、Subject行、`# シーン設定`の背景Picture及びAudio参照directiveで明示されたslotだけを列挙する。背景Pictureのpurposeは`environment_reference`であり、`concept_id`又は`subject_ref`を持たない。CompilerはComfyUI graphの実配線を検査しない。

日本語翻訳はline protocolで行い、一回の推論batchを最大7 unitに制限する。これは小型GGUFが長いslot列で番号を欠落又はshiftする事例を避けるためのprotocol上限であり、欠落slotを推測修復しない。

## 13. 構文エラーとしない事項

Compilerは次を意味検証しない。

- Subject descriptionと参照画像の内容的一致
- 人物、場所、物品という意味分類
- motion又はcamera指示の品質
- 音声内に実際の歌唱があるか
- required referenceがH3 nodeへ接続済みか
- 生成映像又は音響の品質

これらはPlanner、workflow又は利用者の責務である。
