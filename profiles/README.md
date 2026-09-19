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

Motionにはmetadataを置けません。Cameraは任意の`planner_policy` metadataを一つ持てます。

```markdown
# プロファイル
* `planner_policy` anime_emotional_mv

# 共通プロンプト
## カメラ
* 長尺Arcと顔Zoomを連続した演出として使う。
```

`planner_policy`はUIへ別項目を追加せず、Camera profileを選んだ時にだけTimeline PlannerのShot配分、CUT/CONTINUE方針及びCamera構造予算を切り替える内部policy IDです。本文の自然文をPythonで書き換える機能ではありません。`anime_emotional_mv`では現在Sceneの元歌詞だけを対象triggerとし、scene EMD又はDirectionの環境inventoryをAction sourceにせず、対象の一Scene消費、外部effectの自律性、まぶたを含む全身演技及び曲全体で疎な顔Zoomをplanning stageへ共有します。未知policyは本文だけの通常profileとして動作し、実装済みpolicyだけが追加の構造契約を持ちます。選択したMotion/Camera profile本文は対応するtyped fieldを機械的に所有し、LLMのMOTION/CAMERA言い換えでは置換されません。これによりStyleや履物条件がCameraへ誤分類されることを防ぎます。ユーザーが完全なDirection EMDを直接管理する場合は外部profileではなく、Direction Enhancerの`passthrough`を使います。
