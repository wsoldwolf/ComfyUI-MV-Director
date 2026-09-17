# Direction Enhancer

Subject EMD、Vision観察、ユーザー希望、三つのprofileを統合し、MV全体の演出方針をtyped Direction artifactとEMD previewで返します。

## 主な入力

| 入力 | 既定 | 説明 |
|---|---|---|
| `retention_policy` | `profile` | profile既定の保持、Compiler既定、完全pass-throughを切り替える |
| `user_request` | 空 | 最優先の演出希望。空でも動作する |
| `style_profile` | `reference_anime` | 画風と媒体変換。`passthrough`で直接記述を優先 |
| `motion_profile` | `natural_performance` | 全体の身体演技方針 |
| `camera_profile` | `readable_depth` | 全体の撮影方針。Shot固有のカメラはPlannerが決める |
| `concept_emd` | 任意 | Image to Subject EMD等の概念EMD |
| `observations_json` | 任意 | Vision観察。推論へは背景・環境・照明・時刻だけを縮約して渡す |
| `direction_emd_passthrough` | 任意 | profileを使わず、利用者が直接書く演出EMD |
| `cache_mode` | `reuse` | 成功結果の再利用方針 |

profileには`reference_anime`、`anime_mv`、`reference_cinematic`、`illust_to_photoreal`、`reference_painterly`等があります。Motion/Cameraにも`anime_mv`があります。profile本文は[`profiles/style`、`profiles/motion`、`profiles/camera`](../../profiles/README.md)の外部EMDから起動時に読み込み、ファイル名をnode comboのIDとして自動列挙します。利用者はPythonを編集せず独自profileを追加できます。追加・変更後はComfyUIを再起動してください。

選択したMotion及びCamera profileは、それぞれ完成Directionの`## モーション`及び`## カメラ`を機械的に所有します。これらのrecordはLLMへ要求せず、外部profile EMD本文をそのまま採用します。locked Styleも同様です。LLMには未固定Style及び環境・時間・照明・その他の統合判断だけを担当させるため、profile本文の欠落や言い換えを理由に停止しません。ユーザーが本文を直接管理する場合だけ、対応comboを`passthrough`にして外部Direction EMDを入力します。

DirectionはCompiler後の全Scene `prompt_prefix`へ共通適用されます。Plannerでは型別に経路を分け、Visual BeatとActionへStyle、Environment、Time/Lighting、Motion、Otherを渡し、Camera profileはCamera taskだけへ渡します。特定の衣装部品、身体部位又は小物の局所形状をprofileへ書くと、全Shotで反復されて演技やCameraの主題になり得ます。これらは参照画像、`# サブジェクト`又は必要な作者Shot本文へ置き、Direction profileには画風、全体的な身体演技、Camera運用等のMV全体へ本当に共通する方針だけを置きます。

Vision観察の`subject_pose`、shot size、viewpoint、subject placement及びdepthはDirection LLMへ渡しません。参照設定画の立ち姿、両手を広げたポーズ又は左右panel構図が`## その他`へ入り、全Sceneで固定反復されることを防ぐためです。背景のsetting/elements、照明及び時刻・天候だけを`vision_scene_context`へ縮約します。`## その他`は必要なら、歌詞転換で選択的に使う物語モチーフ又は環境効果を定義できます。狐火等の超自然効果は環境側へ置き、人物の髪、耳、尾、目、皮膚又は衣装自体を発光体にしません。

## 出力

| 出力 | 用途 |
|---|---|
| `direction` | Timeline Plannerへ渡すtyped artifact |
| `direction_emd_preview` | 人が確認・保存できる演出EMD |
| `status` | cache hit/miss、issue等 |

## 保持方針とpass-through

画風変換時は「参照の媒体表現まで保持する」と「別媒体として描き直す」が矛盾しやすいため、`retention_policy=profile`を基準にします。`illust_to_photoreal`は髪色、瞳色、衣装、配色、装飾等の識別要素を保持しつつ、物理的な実写表現へ変換します。

ユーザーが全体方針を直接管理したい場合は、各profileを`passthrough`にして`direction_emd_passthrough`を接続します。pass-through本文はLLMによる言い換えを避けたい用途に使います。

Directionは全Scene共通の制約です。`arc`やclose-up等をここで一律に強制するとShotの多様性を失うため、個別の画角・カメラ経路はTimeline Plannerへ任せます。

DirectionからPlannerまでのLLM taskとPython所有境界は[処理フロー図](../architecture/direction-planner-flow.md)を参照してください。
