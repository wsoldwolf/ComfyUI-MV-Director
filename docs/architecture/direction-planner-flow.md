# Direction EnhancerとTimeline Plannerの処理フロー

![Gemma4によるDirection、Scene AuthorのEvent・Performance・Camera、任意の補完とCompilerへの受け渡し](../assets/direction-planner-flow.png)

図は現行dev workflowのScene Author経路です。人物・背景Vision、Enhancer、Planner、CompilerはGemma4 31B Q4_K_Sを使用します。歌詞整列はWhisper、動画生成はMiniMax H3の別責務です。青はLLM、緑はPython、橙は入力、紫は受け渡す成果です。

## 現行Planner：Scene Author

前段WFはStyleとCameraに`anime_emotional_mv`、Motionに`anime_scene_composed_mv`を指定します。Motion profileのmetadataでScene Authorを有効化します。Scene内の複数Shotを同じ要求に含め、現在Sceneと歌詞sectionの文脈、人物・背景EMD及びDirectionを渡します。

| 順序 | LLMの責務 | 次段へ渡す情報 |
|---|---|---|
| EVENT | 歌詞・演出候補から出来事、対象、外部effectを計画 | 採用Eventと出所 |
| PERFORMANCE | Eventに対応する身体・表情の演技を計画 | 採用演技。出来事と身体を別責務として保持 |
| CAMERA | Eventと演技を読んで撮影を計画 | Cameraと終端状態 |

Shotの`演出`、`演技`、`カメラ`に直接書かれた確定指示は保持し、該当fieldの生成を省略します。`END_STATE`は輸送用metadataとして自然文から分離し、`CONTINUE`の次Sceneだけへ各終端を渡します。CUTでは渡しません。映像上の完全な連続性を保証するものではありません。

`staging_candidate_policy=optional`は候補を任意の着想として扱います。`prefer_matched`は歌詞に適合する候補を優先して検討させます。全Sceneへの強制適用や、必ず対象が映像に出ることを保証する設定ではありません。

profileが明示的に有効化した場合だけモーション補完を合成します。`pre_author`は予定補完を演技生成前に提示し、Cameraへ合成済み演技を渡します。`post_author`はEvent・演技・Camera生成後に補完します。任意の`guarded_no_drop`ではLLMが既存の補完候補を選び直し、不正選択は一度再試行、回復不能なら元の候補を保持します。旧Action Auditとは別機能で、作者の確定演技・Cameraは変更しません。

Pythonは時刻、slot、構造grammar、protocol検証、有限retry及びEMD/JSONの組み立てを担当します。LLM原文を意味的に書き換えず、補完と歌唱・lip-sync directiveは別責務として合成し、出所を残します。「最終文はすべてLLM原文だけ」という設計ではありません。Compilerは翻訳対象fieldを英訳し、予約directiveとH3時間格子を機械処理してPlanを保存します。詳細は[Plannerノード](../nodes/timeline-planner.md)を参照してください。

編集用[SVG](../assets/direction-planner-flow.svg)は`python tools/generate_runtime_flow_diagram.py`で再生成します。更新時はPNGも再描画してください。

## Direction Enhancer

Direction Enhancerは`retention_policy`、人物`concept_emd`、背景`scene_emd`、Style/Motion/Camera profile及び`user_request`を受け取ります。`# 共通プロンプト`の希望は全Scene共通です。`# 演出候補`の箇条書きはPythonが構文だけを分離し、Direction LLMや全Scene共通の`prompt_prefix`には渡さず、同じtyped artifactに原文を保持します。外部profileの構造、固定section及びauthorityはPythonが検証し、LLMは固定されていない`STYLE`、`ENVIRONMENT`、`TIME_LIGHTING`、`MOTION`、`CAMERA`、`OTHER`行だけを返します。欠落slotは局所retryし、Pythonが`MVD_DIRECTION_V4`と人間向けpreviewを構築します。

Motion、Camera及びlocked Styleはprofile本文が所有し、LLMへ再生成させません。`scene_emd`は参照背景の構図を複製する入力ではなく、環境、時刻・照明baseline及び背景Pictureの根拠です。明示された利用者DirectionがVision観測より優先します。

## 旧Planner経路（現行Scene Authorとは別）

以下は旧profile向けの別経路です。Scene Authorにこれらがすべて追加実行されるわけではありません。

PlannerはJSONをLLMへ生成させません。Template EMDのScene時間枠と歌詞、Concept EMDのSubject roster、Scene EMD、typed DirectionをPythonが読み、次の順に短い行protocolを要求します。

| 段階 | 担当 | 結果 |
|---|---|---|
| Lyric Cue Discovery | 条件付きLLM | bounded + automatic時だけ、歌詞原文から具体物、場所、現象、外部effect候補を抽出 |
| 演出候補選択 | 条件付きLLM + Python | `# 演出候補`があれば、現在Sceneの歌詞に合う出来事候補一件又は不採用を選ぶ。具体的な出来事を選んだ場合は別の身体候補一件も選べる。PythonはID、anchor及び一回限りの出来事候補の経路だけを管理 |
| Visual Beats | LLM | Sceneごとの感情、原文根拠、対象、配置、可視展開をCue Card化 |
| Song Direction | LLM | 曲全体の感情曲線、section energy、編集連続性を一回だけ作成 |
| Shot Layout | LLM + Python | 既存候補からShotを選び、CUT/CONTINUEを決定。PythonがH3格子へ再配分 |
| Scene spine | 条件付きLLM + Python | 有効Cueを持つ`dance_phrase` SceneのShot進行を一括計画。外部現象では単一Shotも対象とし、人物の`FROM/ADVANCE/TO`と現象の`EFFECT_TO`を分離。`CONTINUE`では直前Sceneの終端状態を次へ渡す。不正なら局所retry後に従来経路へ戻す |
| Actions | LLM | Shotごとの身体演技、表情、対象との空間関係及び外部現象の進行を生成。コーラスの一部と、選択した長尺・単一ShotのPRE-CHORUSで身体accentを一回割り当てる |
| Action Audit | 分類LLM + Python | profile競合、参照pose、偶発背景物、反復、grounding欠落等を分類し、該当slotだけを有限回修復 |
| Cameras | LLM + Python | 確定Actionをread-onlyで参照し、MiniMax H3 Motion Type、長尺Arc、顔Zoom及びcoverageを割り当てる。外部現象のevent Shotでは対象と身体accentの同時可視を要求できる。有限Cameraの選択値はPythonが固定H3文へ直列化 |
| Renderer | Python | 作者台詞を復元し、Action、Camera、歌詞、lip-sync directiveを完成EMDへ配置 |

bounded自動解釈では、Scene EMDを具体対象の発生源にせず、歌詞で認可された対象の空間配置だけに使います。これにより背景に存在する石灯籠等が、歌詞に無い人物Actionの主題へ昇格することを防ぎます。Concept EMDの外見、衣装、履物等も最終Subject定義には保持しますが、Actionの創作sourceにはしません。歌詞から発見した外部effectは対象名だけでなく、Cueの可視展開をevent ShotのActionへ渡します。身体演技は腕・表情だけでなく、必要な通常Shotで支持脚、重心、体幹の変化もつなげます。

LLMが返した合格Action自然文と自由文CameraはAS ISで流します。有限CameraではLLMの選択fieldをPythonが固定H3文へ直列化します。Pythonはslot、時刻、CUT/CONTINUE、H3時間格子、台詞保護、lip-sync directive、有限protocol検証及び狭い表示上の正規化を所有します。Action Auditは品質改善器であり、有限予算を使い切った場合は最小違反のLLM候補をAS ISで保持します。必須slot又はprotocolそのものを復元できない場合だけ、不完全EMDをCompilerへ流さず停止します。

LLM出力は確率的で、出力規約への追従は保証されません。Pythonは一意な構造を検証・復元しますが、有限回復後も必須protocolが不正なら停止します。再試行時のseedとcacheの扱いは[トラブルシューティング](../troubleshooting.md#llmの行protocol不整合が発生する)を参照してください。

長尺曲は`scenes_per_batch`単位で処理します。生成requestへ渡す履歴を限定しながら、採用後の反復検査は全履歴を対象にします。各LLM呼び出しは同じ実行seedからtask、call番号及びpayloadに応じた決定的な`call_seed`を派生するため、同じ入力の再現性とbatch間の乱数列分離を両立します。

人物参照と背景参照は同じauthorityへ統合しません。人物画像から作るSubject EMDはidentity、顔、髪、衣装及び身体特徴を所有します。背景画像のscene-only Visionは検証済み観測から`# シーン設定`断片だけを決定的にrenderし、`emd_fragment`からDirection EnhancerとTimeline Plannerの`scene_emd`入力へ提供します。`observations_json`はdebug出力に留まり、Direction Enhancerの入力ではありません。詳しい理由と推奨配線は[人物参照と背景参照を分ける](../tips/separate-subject-and-background-references.md)を参照してください。

Plannerは背景IMAGE tensorを受け取りません。Plannerは`scene_emd`を完成EMDへAS ISで構造統合し、Compilerが環境専用`<Picture 2>`の定義、保持及びrequired referenceをPlanへ生成します。動画生成時は同じ背景画像をH3 `ref_images.ref_image_1`へ直接入力します。これにより背景再現率を高めつつ、現在のDirection、Scene環境、時刻、照明、Action及びCameraを上位authorityとして維持します。

外部profileの文法と追加方法は[Direction profile EMD](../../profiles/README.md)、各socketは[Direction Enhancer](../nodes/direction-enhancer.md)と[Timeline Planner](../nodes/timeline-planner.md)を参照してください。
