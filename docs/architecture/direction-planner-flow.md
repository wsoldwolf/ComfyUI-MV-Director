# Direction EnhancerとTimeline Plannerの処理フロー

![Direction Enhancerが外部profileと入力をDirection artifactへ統合し、Timeline Plannerが確定時間枠へVisual Beat、Shot layout、Action、Camera及びリップシンクdirectiveを展開する処理フロー](../assets/direction-planner-flow.png)

青はLLMへ渡す処理、緑はPythonが所有する決定的処理、橙は利用者又は上流からの入力です。Direction Enhancerは全体方針を一度だけ統合します。Timeline Planner v55は六つの中核taskへ処理を分け、`anime_emotional_mv`のbounded自動解釈では、その前に条件付きのLyric Cue Discoveryを実行します。

## Direction Enhancer

Direction Enhancerは`retention_policy`、短い利用者希望、人物`concept_emd`、背景`scene_emd`、Style/Motion/Camera profileを受け取ります。外部profileの構造、固定section及びauthorityはPythonが検証し、LLMは固定されていない`STYLE`、`ENVIRONMENT`、`TIME_LIGHTING`、`MOTION`、`CAMERA`、`OTHER`行だけを返します。欠落slotは局所retryし、Pythonが`MVD_DIRECTION_V3`と人間向けpreviewを構築します。

Motion、Camera及びlocked Styleはprofile本文が所有し、LLMへ再生成させません。`scene_emd`は参照背景の構図を複製する入力ではなく、環境、時刻・照明baseline及び背景Pictureの根拠です。明示された利用者DirectionがVision観測より優先します。

## Timeline Planner v55

PlannerはJSONをLLMへ生成させません。Template EMDのScene時間枠と歌詞、Concept EMDのSubject roster、Scene EMD、typed DirectionをPythonが読み、次の順に短い行protocolを要求します。

| 段階 | 担当 | 結果 |
|---|---|---|
| Lyric Cue Discovery | 条件付きLLM | bounded + automatic時だけ、歌詞原文から具体物、場所、現象、外部effect候補を抽出 |
| Visual Beats | LLM | Sceneごとの感情、原文根拠、対象、配置、可視展開をCue Card化 |
| Song Direction | LLM | 曲全体の感情曲線、section energy、編集連続性を一回だけ作成 |
| Shot Layout | LLM + Python | 既存候補からShotを選び、CUT/CONTINUEを決定。PythonがH3格子へ再配分 |
| Actions | LLM | Shotごとの身体演技、表情、対象との空間関係及び終端poseを生成 |
| Action Audit | 分類LLM + Python | profile競合、参照pose、偶発背景物、反復、grounding欠落等を分類し、該当slotだけを有限回修復 |
| Cameras | LLM + Python | 確定Actionをread-onlyで参照し、MiniMax H3 Motion Type、長尺Arc、顔Zoom、coverageを割り当て |
| Renderer | Python | 作者台詞を復元し、Action、Camera、歌詞、lip-sync directiveを完成EMDへ配置 |

bounded自動解釈では、Scene EMDを具体対象の発生源にせず、歌詞で認可された対象の空間配置だけに使います。これにより背景に存在する石灯籠等が、歌詞に無い人物Actionの主題へ昇格することを防ぎます。Concept EMDの外見、衣装、履物等も最終Subject定義には保持しますが、Actionの創作sourceにはしません。

LLMが返した合格ActionとCameraの自然文はAS ISで流します。Pythonはslot、時刻、CUT/CONTINUE、H3時間格子、台詞保護、lip-sync directive、有限protocol検証及び狭い表示上の正規化を所有します。Action Auditは品質改善器であり、有限予算を使い切った場合は最小違反のLLM候補をAS ISで保持します。必須slot又はprotocolそのものを復元できない場合だけ、不完全EMDをCompilerへ流さず停止します。

LLMのcreative textは確率的であり、既定のQwen 8B級モデルはsystem prompt又はprofileの出力規約へ常に従うとは限りません。Pythonは一意に判断できる構造だけを決定論的に検証・復元できますが、欠落した意味内容をAS ISのまま合成することはできません。そのため、全てのprotocol違反を必ず成功へ変換する決定論的fallbackは設けず、有限回復後も不正な場合は停止します。運用上は`cache_mode=refresh`と別の言語生成seedを使い、別のLLM出力パターンを得ることで回避します。詳細は[トラブルシューティング](../troubleshooting.md#llmの行protocol不整合が発生する)を参照してください。

長尺曲は`scenes_per_batch`単位で処理します。生成requestへ渡す履歴を限定しながら、採用後の反復検査は全履歴を対象にします。各LLM呼び出しは同じ実行seedからtask、call番号及びpayloadに応じた決定的な`call_seed`を派生するため、同じ入力の再現性とbatch間の乱数列分離を両立します。

人物参照と背景参照は同じauthorityへ統合しません。人物画像から作るSubject EMDはidentity、顔、髪、衣装及び身体特徴を所有します。背景画像のscene-only Visionは検証済み観測から`# シーン設定`断片だけを決定的にrenderし、`emd_fragment`からDirection EnhancerとTimeline Plannerの`scene_emd`入力へ提供します。`observations_json`はdebug出力に留まり、Direction Enhancerの入力ではありません。詳しい理由と推奨配線は[人物参照と背景参照を分ける](../tips/separate-subject-and-background-references.md)を参照してください。

Plannerは背景IMAGE tensorを受け取りません。Plannerは`scene_emd`を完成EMDへAS ISで構造統合し、Compilerが環境専用`<Picture 2>`の定義、保持及びrequired referenceをPlanへ生成します。動画生成時は同じ背景画像をH3 `ref_images.ref_image_1`へ直接入力します。これにより背景再現率を高めつつ、現在のDirection、Scene環境、時刻、照明、Action及びCameraを上位authorityとして維持します。

外部profileの文法と追加方法は[Direction profile EMD](../../profiles/README.md)、各socketは[Direction Enhancer](../nodes/direction-enhancer.md)と[Timeline Planner](../nodes/timeline-planner.md)を参照してください。
