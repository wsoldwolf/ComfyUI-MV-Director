# Direction EnhancerとTimeline Plannerの処理フロー

![Direction Enhancerが外部profileと入力をDirection artifactへ統合し、Timeline Plannerが確定時間枠へVisual Beat、Shot layout、Action、Camera及びリップシンクdirectiveを展開する処理フロー](../assets/direction-planner-flow.png)

青はLLMへ渡す処理、緑はPythonが所有する決定的処理、橙は利用者又は上流からの入力です。Direction Enhancerは全体方針を一度だけ統合し、Timeline Plannerは短い行protocolを五つのtaskへ分離します。LLMの採用行はActionとCamera本文としてAS ISで流し、EMD構造、CUT/CONTINUE、H3時間格子、台詞保護及びlip-sync directiveはPythonが所有します。

人物参照と背景参照は同じauthorityへ統合しません。人物画像から作るSubject EMDはidentity、顔、髪、衣装及び身体特徴を所有します。背景画像のscene-only Visionは検証済み観測から`# シーン設定`断片だけを決定的にrenderし、`emd_fragment`からDirection EnhancerとTimeline Plannerの`scene_emd`入力へ提供します。`observations_json`はdebug出力に留まり、Direction Enhancerの入力ではありません。詳しい理由と推奨配線は[人物参照と背景参照を分ける](../tips/separate-subject-and-background-references.md)を参照してください。

Plannerは背景IMAGE tensorを受け取りません。Plannerは`scene_emd`を完成EMDへAS ISで構造統合し、Compilerが環境専用`<Picture 2>`の定義、保持及びrequired referenceをPlanへ生成します。動画生成時は同じ背景画像をH3 `ref_images.ref_image_1`へ直接入力します。これにより背景再現率を高めつつ、現在のDirection、Scene環境、時刻、照明、Action及びCameraを上位authorityとして維持します。

外部profileの文法と追加方法は[Direction profile EMD](../../profiles/README.md)、各socketは[Direction Enhancer](../nodes/direction-enhancer.md)と[Timeline Planner](../nodes/timeline-planner.md)を参照してください。
