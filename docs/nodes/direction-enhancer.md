# Direction Enhancer

Subject EMD、Scene EMD、ユーザー希望、三つのprofileを統合し、MV全体の演出方針をtyped Direction artifactとEMD previewで返します。

## 主な入力

| 入力 | 既定 | 説明 |
|---|---|---|
| `retention_policy` | `profile` | profile既定の保持、Compiler既定、完全pass-throughを切り替える |
| `user_request` | 空 | 最優先の演出希望。計画専用の演出候補ディレクティブも記述できる。空でも動作する |
| `style_profile` | `anime_emotional_mv` | 画風と媒体変換。`passthrough`で直接記述を優先 |
| `motion_profile` | `anime_emotional_mv` | 全体の身体演技方針 |
| `camera_profile` | `anime_emotional_mv` | 全体の撮影方針。Shot固有のカメラはPlannerが決める |
| `concept_emd` | 任意 | Image to Subject EMD等の概念EMD |
| `concept_emd_2` / `concept_emd_3` / `concept_emd_4` | 未接続 | 追加のSubject EMD断片。統合後のSubjectは合計4件まで |
| `scene_emd` | 任意 | scene-only Visionが確定した環境、時刻・照明baseline、背景Picture。Plannerにも同じ断片を渡す |
| `direction_emd_passthrough` | 任意 | profileを使わず、利用者が直接書く演出EMD |
| `cache_mode` | `reuse` | 成功結果の再利用方針 |

`user_request`には共通指示と計画専用の演出候補を別セクションで記述できます。候補は最大12件、各500文字までです。

```markdown
# 共通プロンプト
## 時間・照明
* シーン全編を通して夜間。

# 演出候補
* 苔を扱う場面では、参道脇の大木の根元に生えた苔へ人物が近づき、指先で撫でる。
* 歌詞に合う場面では、片側への荷重から胸郭と腕を連動させ、歌唱口が見える瞬間にアクセントを置く。
```

Directionは`# 演出候補`の各箇条書きを共通指示から分離し、原文のままtyped artifactへ保持します。Direction LLM、`direction_emd_preview`、完成EMD及びH3の全Scene共通`prompt_prefix`へは入れません。PlannerはSceneごとの短いLLM選択で歌詞との適合を判断し、出来事候補一件又は不採用を選びます。対象・配置を伴う出来事候補を選んだ場合は、別の身体演技候補一件も選べます。出来事の場所と支持物はCue Card及び接触Shotへ伝え、同じ具体的出来事の候補を後続Sceneへ再配布しません。身体演技だけの候補は再選択できます。候補の記載は発生を保証しません。候補件数と採用SceneはINFOログで確認できます。Plannerへの専用入力ソケットや特別なMotion profile指定は不要です。

`anime_choreography_mv`は身体演技の共通方針だけを提供します。以前の`scene_palette`による振付候補の一括投入は廃止しました。必要な身体フレーズは`# 演出候補`へ記述し、PlannerにScene単位で採否を決めさせてください。

`max_tokens`は利用者が指定する生成上限ですが、Directionの応答は少数の型付き行に限定されます。そのため実推論では入力を削らず、出力予約だけを最大1024 tokenへ自動調整します。さらにcontextが狭い場合は、安全余白を維持したまま128 token以上の範囲で縮小します。調整時は`requested_max_tokens`と`effective_max_tokens`をINFOログへ出します。128 tokenも確保できない場合だけ、入力を黙って切り詰めず`ContextBudgetError`で停止します。

profileには`reference_anime`、`anime_story_mv`、`anime_emotional_mv`、`reference_cinematic`、`illust_to_photoreal`、`reference_painterly`等があります。Motion/Cameraにも`anime_story_mv`及び`anime_emotional_mv`があります。profile本文は[`profiles/style`、`profiles/motion`、`profiles/camera`](../../profiles/README.md)の外部EMDから起動時に読み込み、ファイル名をnode comboのIDとして自動列挙します。利用者はPythonを編集せず独自profileを追加できます。追加・変更後はComfyUIを再起動してください。

選択したMotion及びCamera profileは、明示的なユーザー本文がない場合、
それぞれ完成Directionの`## モーション`及び`## カメラ`を機械的に所有します。
ユーザーは既存`user_request`に`# 共通プロンプト`のsubsectionを記述して、
選択profileの該当本文だけを上書きできます。profile本文はLLMへ再要求せず、
上書き時は破棄としてprovenanceに残します。Motionの本文を上書きした場合も、
選択profileのPlanner方式は別の`motion_policy_profile_id`へ保持します。
全本文を直接管理する場合は`passthrough` comboと外部Direction EMDも利用できます。

Camera profileは非表示metadata `planner_policy`を任意に宣言できます。これは同じprofile選択からTimeline Plannerの構造最適化も切り替えるためのもので、UI socketは増えません。`anime_emotional_mv`は同名policyを宣言し、感情演技、継続Scene、長尺Arc及び顔Zoomの配分を変更します。生成済みAction又はCamera本文を書き換えないため、AS IS原則は維持されます。

DirectionはCompiler後の全Scene `prompt_prefix`へ共通適用されます。PlannerはScene Authorで出来事、人物演技、Cameraの責務を分け、必要なDirection fieldを各担当へ渡します。特定の衣装部品、身体部位又は小物の局所形状をprofileへ書くと、全Shotで反復されて演技やCameraの主題になり得ます。これらは参照画像、`# サブジェクト`又は必要な作者Shot本文へ置き、Direction profileには画風、全体的な身体演技、Camera運用等のMV全体へ本当に共通する方針だけを置きます。

`scene_emd`は`# シーン設定`、`## 環境`、任意の`## 時間・照明`及び`## 背景参照`だけを持つ厳格な断片です。Direction Enhancerはこれをparseして`scene_context`へ渡します。参照設定画のpose、shot size、viewpoint、subject placement及びpanel構図はこの経路へ入らず、全Sceneで固定反復されません。ユーザーのDirection又はpass-throughで明示した環境、時刻及び照明は観測baselineより上位です。`observations_json`はVisionのdebug出力として残りますが、Direction Enhancerの入力ではありません。

`## その他`は必要なら、歌詞転換で選択的に使う物語モチーフ又は環境効果を定義できます。狐火等の超自然効果は環境側へ置き、人物の髪、耳、尾、目、皮膚又は衣装自体を発光体にしません。

## 出力

| 出力 | 用途 |
|---|---|
| `direction` | Timeline Plannerへ渡すtyped artifact |
| `direction_emd_preview` | 人が確認・保存できる演出EMD |
| `status` | cache hit/miss、issue等 |
| `subjects_emd` | 入力順に統合したSubject EMD。Plannerの`concept_emd`へ接続できる |

## 複数Subject入力

各入力は`# サブジェクト`と箇条書きだけを持つEMD断片です。既存の`concept_emd`一つに複数行を書く方法も維持します。空入力は無視し、入力番号順・断片内の行順に`サブジェクト1`〜`サブジェクト4`を割り当てます。途中の入力が空の場合も番号を詰めるため、`status`とINFOログの`subject_map`で対応を確認してください。

説明文と画像・動画・音声参照は原文のまま保持します。画像番号はSubject番号と独立しており、自動で振り直しません。複数のVisionノードを使う場合は、各ノードの画像slotと動画WFの実参照slotを一致させてください。同じ画像・説明を持つ行も別Subjectとして残し、意味による重複除去はしません。`scene_emd`はこのSubject件数に含みません。

推奨接続は、最大4断片をEnhancerへ渡し、`subjects_emd`をPlannerの`concept_emd`へ渡す方法です。Plannerの追加入力へ同じ断片を再接続すると、重複して別Subjectに数えられます。既存の出力0〜2は変えず、統合済み出力を末尾の3へ追加しています。全入力が空なら出力も空とし、未指定人物の補完は従来どおりPlanner側だけで行います。

配布のPlan WFはこの統合出力をPlannerへ接続し、両ノードの`concept_emd_2`〜`concept_emd_4`を公開しています。ノード更新後はComfyUIを再起動し、同期したWFを読み込んでください。人物を追加する場合は、Image to Subject EMDを複製して画像slotを指定し、その出力をEnhancerの追加入力へ接続します。動画WFでは同じ画像を対応する`ref_images.ref_image_N`へ接続してください。例えば`画像3`はゼロベースの`ref_images.ref_image_2`です。既定の素材は一人のままです。

既存WFはジェネレーターの`--sync-subject-inputs`で更新できます。レイアウト・配色・widget値・素材を保持し、従来の同じVision出力をEnhancerとPlannerへ二重に渡す配線だけを統合出力へ変更します。Plannerへ別の作者断片や追加入力を独自接続している場合は、その配線を保持するため、必要に応じて手動で統合してください。

入力統合とCompilerへの受け渡しに加え、Plannerの演技対象・人物別終端状態、補完の適用対象、小道具の所有者別の手の計画までCPU試験しています。Enhancerは人物別の演技を追加推論せず、同じSubject定義をPlannerへ渡します。2026-10-13のGemma4 31B Q4_K_S実推論では、人物二人・木・舞台の4入力を統合し、単一Subjectの対照入力も完了しました。続く英訳比較では、断片英訳で主体と対象が分断される問題を確認し、複数Subjectの関係文を一時記号で保護した全文英訳へ変更しました。配布Plan WFの接続同期に加え、実画像を使う人物二人・古木・岩の4 Subjectを通常3段で推論し、16.5秒のH3生成も完了しています。四人の同時演技や、英文の意味・映像品質全体を保証するものではありません。詳細は[Compilerの翻訳境界](emd-compiler.md#翻訳の出典分離とログ)を参照してください。

## 保持方針とpass-through

画風変換時は「参照の媒体表現まで保持する」と「別媒体として描き直す」が矛盾しやすいため、`retention_policy=profile`を基準にします。`illust_to_photoreal`は各Subjectと参照画像にある形状、顔面の被覆、衣装、配色、装飾等の識別要素を保持しつつ、材質・照明・レンズ表現を物理的な実写表現へ変換します。通常の人間の顔や露出した身体、特定の動物部位を一律に追加するプロファイルではありません。顔まで覆う全身スーツ等は、被覆面自体をSubjectの特徴として記述してください。

プロファイル変更後はComfyUIを再起動し、01_ WFでEMDとPlanを再生成してください。既存Planの`prompt_prefix`は更新されません。顔を覆ったまま身体演技を見せる用途では、歌唱口の可視性と競合しないようPlannerの`lip_sync_mode=off`も検討してください。これは今回の生成設定の選択であり、一般の歌唱MVのリップシンクを無効化する変更ではありません。

ユーザーが全体方針を直接管理したい場合は、各profileを`passthrough`にして`direction_emd_passthrough`を接続します。pass-through本文はLLMによる言い換えを避けたい用途に使います。

Directionは全Scene共通の制約です。`arc`やclose-up等をここで一律に強制するとShotの多様性を失うため、個別の画角・カメラ経路はTimeline Plannerへ任せます。

DirectionからPlannerまでのLLM taskとPython所有境界は[処理フロー図](../architecture/direction-planner-flow.md)を参照してください。
