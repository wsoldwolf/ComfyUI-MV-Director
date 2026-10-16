# Directionプロファイル

Style・Motion・CameraはこのディレクトリのUTF-8 EMDファイルから読み込みます。
PlannerはGemma 4 31Bを基準にしたScene Authorへ一本化しました。
プロファイルは表現方針を選ぶものであり、旧8B向けの別生成経路を選ぶものではありません。

| ディレクトリ | 必須見出し | 用途 |
|---|---|---|
| style/ | `## スタイル` | 媒体、画風、材質など |
| motion/ | `## モーション` | 身体演技の表現方針 |
| camera/ | `## カメラ` | 撮影の表現方針 |

ファイル名の拡張子を除いた部分がUIのprofile IDです。先頭は小文字、以降は小文字英数字と
underscoreを使います。予約ID `passthrough`は使えません。変更後はComfyUIを再起動してください。
未知metadata、種類に合わない見出し、空項目、code fence、NULはエラーになります。

## 最小形

```markdown
# 共通プロンプト
## モーション
* 歌詞の感情を、人物の支持・体幹・腕・表情がつながる演技で表す。
```

複数の箇条書きは文書順に空白一個で連結されます。生成はすべて
Event → Performance → CameraのScene単位で行います。
作者がShotに指定した確定 `演出`・`演技`・`カメラ`は生成で置換しません。

## 現行metadata

先頭の任意の `# プロファイル`に記述します。

| 種類 | key | 値・用途 |
|---|---|---|
| Style | locked | true / false。trueはStyle本文を固定 |
| Style | retention | `fully_preserved`又は`partially_preserved`で始まる保持分析 |
| Style | scene_reinforcement | Scene冒頭へ再掲する媒体条件 |
| Motion・Camera | render_prompt | 計画用のprofile本文と完全一致する項目だけを、描画用本文へ置換 |
| Motion | composition_timing | pre_author（省略時）/ post_author |
| Motion | composition_reselection | off（省略時）/ guarded_no_drop |
| Camera | arc_roll_policy | off（省略時）/ selective_arc |

`render_prompt`は作者の追記やLLM生成文を書き換えません。
`arc_roll_policy=selective_arc`はCamera段にArcとRollの組合せを選択的に提案します。
特定のplanner_policy指定は不要です。Rollは画面の傾きで、上下へのTiltとは異なります。

## モーション補完

Motion profileに任意の `# モーション補完`を置けます。通常箇条書きで最大12件、各500文字です。
ユーザー入力の同名sectionで全置換でき、`* 無効`で停止します。共通promptには入りません。
作者確定のShot演技には追加しません。

Motionの`anime_emotional_mv`は、接地・荷重移動を含む補完ありの方式です。本文、render_prompt、
post_author及びguarded_no_dropのmetadata、3件の補完候補を`anime_scene_composed_mv`と同一にしています。
`anime_scene_composed_mv`は既存WFとの互換用に元のファイルを残しており、付属WFでの選択も引き続き有効です。
post_authorでは演技・Camera生成後に補完を合成します。補完なしで使う場合は、ユーザー入力に
`# モーション補完`と`* 無効`を記述します。
guarded_no_dropは確定Event・Performance・Cameraを読み、候補番号だけをSceneごとに選び直します。
確定本文は書き換えず、補完なしにもできません。不正応答は一回だけ再試行し、
失敗時は元の巡回選択を維持します。補完による画質・自然さは動画で確認してください。

## 旧profileからの移行

`performance_mode`、`body_accent_policy`、`choreography_policy`、`planner_policy`、
`camera_render_style`、`lyric_cue_mode`、`lyric_interpretation`、`priority_lyric_cues`、
`arc_tilt_policy`は廃止しました。カスタムprofileから削除してください。
無視して旧経路へフォールバックすることはありません。

ID付き `# 振付候補`も廃止しました。ユーザーの任意演出は `# 演出候補`、
機械的な身体補完は `# モーション補完`へ分けて記述してください。
旧実験profile `anime_choreography_mv`・`anime_scene_phrase_mv`は撤去しました。
`anime_scene_author_mv`、`anime_story_mv`及び`limited_animation`は削除しました。
旧WFでこれらを選択している場合は、該当欄を再選択してください。アニメ向けはStyle・Motion・Cameraの
`anime_emotional_mv`を使用でき、Motionの`anime_scene_composed_mv`も互換用に残しています。
従来の補完なしに相当する使い方は、上記の明示的な補完無効化で指定します。
Style・Cameraの`anime_emotional_mv`、及び削除対象以外のprofile本文は変更していません。

詳細は[EMD仕様](../docs/spec/emd-spec.md)及び
[補完と演技のTIPS](../docs/tips/mechanical-motion-and-perceived-performance.md)を参照してください。
