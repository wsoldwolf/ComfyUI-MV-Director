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

複数のlist itemは文書順に空白一個で連結され、Direction profileの一つの本文になります。指定ディレクトリとsubsectionは一致しなければなりません。別section、空item、code fence、NUL及び未知metadataは起動時エラーです。

## Style metadata

Styleだけは先頭へ任意の`# プロファイル`を置けます。

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

Motionにはmetadataを置けません。Cameraは任意の`planner_policy`、
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
人物の全身演技を毎Shotへ強制せず、対象自身の動きと短い反応でも成立させます。
既存九項目を使います。v54の`bounded + automatic`では歌詞行Discoveryを一段
追加し、16行ずつ最大768出力tokenで具体物候補を抽出します。原文順で最後の
非body候補をSceneの対象に選ぶため、分類誤りや複数対象の取り落としはあり得ます。
bounded専用Visual Beat promptと原文に結び付いた生成時文法を使いますが、
Actionは既存の通常promptを使用します。意味の正しさを保証する機能ではありません。
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
