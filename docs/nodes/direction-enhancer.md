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
| `observations_json` | 任意 | Vision観察とprovenance |
| `direction_emd_passthrough` | 任意 | profileを使わず、利用者が直接書く演出EMD |
| `cache_mode` | `reuse` | 成功結果の再利用方針 |

profileには`reference_anime`、`anime_mv`、`reference_cinematic`、`illust_to_photoreal`、`reference_painterly`等があります。Motion/Cameraにも`anime_mv`があります。正確な現在値はnode comboを正本としてください。

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
