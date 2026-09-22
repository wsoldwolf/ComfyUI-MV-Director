# Direction profile EMD

Direction Enhancerの`style_profile`、`motion_profile`、`camera_profile`はPython定数ではなく、このディレクトリのUTF-8 EMDファイルから読み込みます。

| ディレクトリ | 必須subsection | 用途 |
|---|---|---|
| `style/` | `## スタイル` | 媒体、画風、材質、照明上の全体方針 |
| `motion/` | `## モーション` | 人物演技と動きの全体方針 |
| `camera/` | `## カメラ` | Shot固有CameraをPlannerが選ぶための全体方針 |

ファイル名の拡張子を除いた部分がprofile IDです。例えば`profiles/style/my_anime.md`はComfyUIの`style_profile` comboへ`my_anime`として追加されます。IDは小文字英数字とunderscoreだけを使い、先頭は小文字、予約ID `passthrough`は使えません。追加・変更後はComfyUIを再起動してください。

## 最小形

```markdown
# 共通プロンプト
## スタイル
* 映画的な手描きセルアニメーションとして描く。
* 人物の識別要素と衣装配色を保持する。
```

複数のlist itemは文書順に空白一個で連結され、Direction profileの一つの本文になります。指定ディレクトリとsubsectionは一致しなければなりません。Motion専用の任意`# 振付候補`を除き、別section、空item、code fence、NUL及び未知metadataは起動時エラーです。

## Style metadata

先頭の任意の`# プロファイル`に、種類ごとのmetadataを置けます。

```markdown
# プロファイル
* `locked` true
* `retention` `partially_preserved` 髪型、配色及び衣装を保持する。
* `scene_reinforcement` 各Sceneでも同じ媒体表現を維持する。

# 共通プロンプト
## スタイル
* 目標媒体を先頭にした固定Style本文。
```

- `locked`: `true`又は`false`。`true`ではLLMが返したSTYLEを採用せず、この本文をそのまま使います。
- `retention`: `retention_policy=profile`時にSubjectごとへ出す保持分析です。先頭は`` `fully_preserved` ``又は`` `partially_preserved` ``にします。
- `scene_reinforcement`: 各Scene最初のShotでも短く再掲するStyle条件です。

## Motion metadata

### 計画用本文と描画用本文の分離

MotionとCameraは任意metadata `render_prompt` を持てます。`# 共通プロンプト`の本文は
Direction→Plannerの計画用入力として従来どおり使い、EMDへ出す時だけ、選択profileの
本文と**完全一致する項目**を`render_prompt`へ置き換えます。作者の追記・LLM生成文・
編集された本文は変更しません。未指定なら従来どおり本文を出します。

```markdown
# プロファイル
* `performance_mode` dance_phrase
* `render_prompt` 動作は一つの意図ある経路を通り、明瞭なアクセントと余韻へ連続する。

# 共通プロンプト
## モーション
* 歌詞に応じて準備・アクセント・解放をShotへ配分する。
```

配分率・slot・監査等のPlanner向け規則を動画モデルへ送らず、描画に必要な短い全体条件を
別に記述するための機能です。UI追加はありません。`anime_emotional_mv`のMotionとCameraで
使用しています。metadataもPlannerキャッシュに含むため、変更後は再起動してPlanを再生成します。

```markdown
# プロファイル
* `performance_mode` dance_phrase

# 共通プロンプト
## モーション
* 重心から体幹、腕、表情へつながる演技を、準備・アクセント・解放として描く。
```

`performance_mode`は`event_based`（省略時）又は`dance_phrase`です。
`anime_choreography_mv`は全編比較用の選択可能なMotionであり、既定の`anime_emotional_mv`には適用しません。`# プロファイル`で`choreography_policy scene_palette`と`performance_mode dance_phrase`を明示し、共通本文の後に二つ以上の`# 振付候補`を置いた時だけ、Plannerが候補群を任意の着想としてScene SpineとActionへ渡します。各候補は`* `id` 始点・支持／重心・体幹／腕・終端の運動経路`形式です。候補IDの選択、候補本文の再現、均等な使用は要求しません。歌詞に合えばLLMは候補を使わず、独自の身体経路を考案できます。候補本文は動画用`render_prompt`へ混ぜません。Actionの自然文はPythonで修復しません。候補を置くだけ、又は他のMotionを選ぶだけでは機能しません。有限IDを別のLLM段階で選ぶ`scene_choice`も仕様上残しますが、8B全編試験では静かな候補に偏ったため、このprofileでは使用しません。
`anime_emotional_mv`と、現在その内容を複製した`anime_story_mv`のMotionは`dance_phrase`を選びます。選択したMotionの
metadataだけで切り替え、UI項目は追加しません。Cameraだけをemotionalにしても
有効になりません。設定もPlannerのcache keyへ含めます。

`dance_phrase`では既存Cue Cardの`身体主導`と`終端`を、一つのつながる全身演技として
Actionへ渡します。準備・アクセント・解放をScene内のShotへ配分し、短い顔Shotでは
その演技の表情accentだけを扱います。踏み替えや膝の弾みを全身演技として許可しますが、
足先の接写、不要な走行、人物の連続回転は求めません。歌詞の具体物・外部effectは
保持し、身体演技を追加するために対象を置き換えません。静かな場面も残します。

下半身語だけで演技違反と決めるPython検査は、このmodeでは適用せず既存の意味監査へ
委ねます。足指や履物の細部を主役にする演出は監査promptで引き続き禁止しますが、
意味監査は品質保証ではありません。生成文の機械的な書換え、追加LLM段階、監査回数の
増加、音楽beat解析は行いません。実時間での拍同期やCameraの位相制御は別課題です。

## Camera metadata

`dance_phrase`では、通常の内部Shot候補の最短間隔を4秒として演技が収まる時間を確保します。
Sceneや音声の区切りは変えず、4秒未満のSceneも一Shotとして扱えます。Actionには
`performance_phase`、Scene内の進行位置、継続時の前Cueの終了状態を渡します。終了状態は
LLMが計画した状態であり、生成動画からの姿勢検出ではありません。

emotionalの有限Camera契約では、同じ継続グループの前Camera終了画角・視点を開始値として
接続します。背面・側面から正面顔へ単純Zoomする不可能な接続は、同じ旋回方向のArcとして
解決し、INFOに接続を記録します。この幾何接続は有限値の構造処理で、Action本文はAS ISです。
自由文Cameraや作者が書いた演技の意味を書き換える機能ではありません。実画像の連続性は別途検証が必要です。

Cameraは任意の`planner_policy`、
`lyric_cue_mode`、`lyric_interpretation`及び`priority_lyric_cues` metadataを持てます。

```markdown
# プロファイル
* `planner_policy` anime_emotional_mv
* `lyric_cue_mode` automatic
* `lyric_interpretation` bounded

# 共通プロンプト
## カメラ
* 長尺Arcと顔Zoomを連続した演出として使う。
```

`planner_policy`はUIへ別項目を追加せず、Camera profileを選んだ時にだけTimeline PlannerのShot配分、CUT/CONTINUE方針及びCamera構造予算を切り替える内部policy IDです。本文の自然文をPythonで書き換える機能ではありません。`anime_emotional_mv`では現在Sceneの元歌詞だけを対象triggerとし、scene EMD又はDirectionの環境inventoryをAction sourceにせず、対象の一Scene消費、外部effectの自律性、まぶたを含む全身演技及び曲全体で疎な顔Zoomをplanning stageへ共有します。未知policyは本文だけの通常profileとして動作し、実装済みpolicyだけが追加の構造契約を持ちます。選択したMotion/Camera profile本文は対応するtyped fieldを機械的に所有し、LLMのMOTION/CAMERA言い換えでは置換されません。これによりStyleや履物条件がCameraへ誤分類されることを防ぎます。ユーザーが完全なDirection EMDを直接管理する場合は外部profileではなく、Direction Enhancerの`passthrough`を使います。

`anime_story_mv`はStyle/Motion/Cameraを`anime_emotional_mv`から複製した比較用基準です。Cameraの`planner_policy`は両者とも`anime_emotional_mv`です。現在は`anime_emotional_mv`を開発用とし、そのMotionだけに`body_accent_policy=sparse_chorus`、Cameraだけに`arc_roll_policy=selective_arc`を付けています。`anime_story_mv`は両metadataとも省略時の`off`で、従来の上半身roleとCamera経路を保ちます。変更前のstory profileはGit履歴から参照できます。

Motion profileの`body_accent_policy`は`off`（省略時）又は`sparse_chorus`を指定できます。後者は`performance_mode=dance_phrase`を必要とし、サビ及び最終サビの適格なSceneで最大一Shotだけ`body_phrase_accent`を選びます。顔Shot及びScene-spineが対象との接触・現象・顔だけを要求するShotは除外します。本文をPythonで書き換えず、LLMに支持脚から体幹・腕へつながる演技を要求します。監査はこのroleにだけ不足理由を返せますが、再要求上限に達した場合は既存のAS IS候補を警告付きで残します。metadataはPlanner cache keyに含めます。

Camera profileの`arc_roll_policy`は`off`（省略時）又は`selective_arc`です。後者は3.5秒以上の長尺ArcからCamera batchごとに最大一Shotを選び、Arcの中盤で画面を光軸まわりに約10度傾け、終端までに水平へ戻します。これは上下を見上げる`Tilt Up`ではなく、水平線が傾く`Roll Clockwise / Counterclockwise`です。Arcの左右方向は維持し、Roll方向はArc方向に対応させます。固定顔Shotから全身へ抜けるArcも候補に含めますが、顔へ入るArcと顔だけの可視条件は除外します。歌詞対象の必須coverageはそのまま維持します。有限Camera fieldをLLMが選び、Pythonは選択済み経路を固定H3文へ直列化するだけです。`anime_story_mv`では従来どおり無効です。
旧`arc_tilt_policy`は上下首振りを意味する別の動きであり廃止しました。カスタムCamera profileで使用している場合は`arc_roll_policy`へ明示的に移行してください。

`lyric_cue_mode`は`automatic`、`priority_only`又は`off`です。
`automatic`ではVisual Beatが現在Sceneの歌詞又は作者本文を読み、物理的に
表示できる最も具体的な名詞句又は独立effectを一つ選びます。例えば
`御神木`を`木`へ短縮せず、Cue Cardの配置・可視展開と共にActionへ渡します。
固定辞書や追加のLLM呼び出しは使いません。`priority_only`では下記の明示一覧
だけを使い、`off`ではこの局所Cue契約を無効にします。

`lyric_interpretation`は`literal`（省略時）又は`bounded`です。
`anime_emotional_mv`は`bounded`を選びます。対象を現在歌詞から選ぶ制約は
維持し、選択済み対象への非破壊的な接触や自然な支持面の推定をLLMへ許します。
接触を必須にせず、外部effectの操作や背景設備の主役化は許しません。
人物の全身演技を毎Shotへ強制しません。Motionの`event_based`では対象自身の動きと
短い反応でも成立させ、`dance_phrase`では独立した歌唱演技との共存を許します。
既存九項目を使います。v54の`bounded + automatic`では歌詞行Discoveryを一段
追加し、16行ずつ最大768出力tokenで具体物候補を抽出します。原文順で最後の
非body候補をSceneの対象に選ぶため、分類誤りや複数対象の取り落としはあり得ます。
bounded専用Visual Beat promptと原文に結び付いた生成時文法を使いますが、
Actionは既存の段階を使用し、v56の`dance_phrase`選択時だけ短い振付向けpromptへ
切り替えます。他のMotionは通常promptです。意味の正しさを保証する機能ではありません。
変更後はComfyUIを再起動してください。metadataもPlannerのcache keyへ含まれます。

前後各二行・各256文字までの歌詞をVisual Beatへ読解用に渡しますが、その
隣接文脈だけにある名詞は対象として選べません。Sceneをまたぐ出来事の新しい
所有権fieldや複数Cueリストは今回導入していません。

`priority_lyric_cues`は任意の回帰overrideです。`TOKEN:KIND`をカンマ区切りで
指定し、`KIND`は
`object`、`symbolic_motif`又は`external_effect`です。設定tokenは現在Sceneの
歌詞又は作者本文に完全一致する時だけ有効になり、Cue Card、Action及びauditへ
渡されます。profileに書いたtokenを全Sceneへ出現させる機能ではありません。
`external_effect`は接触禁止かつ人物から独立した現象として検証されます。
`anime_emotional_mv`では、automatic又は優先CueのCue Cardが生成した`配置`と`可視展開`を
Actionへ完全一致で転送します。これはprofile tokenを全Sceneへ展開する処理では
なく、現在Sceneの歌詞で一致したtokenだけを具体的な場所、状態、軌道又は環境結果
へ結び付ける局所契約です。
