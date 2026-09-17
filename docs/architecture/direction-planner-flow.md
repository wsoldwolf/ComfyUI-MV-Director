# Direction EnhancerとTimeline Plannerの処理フロー

![Direction Enhancerが外部profileと入力をDirection artifactへ統合し、Timeline Plannerが確定時間枠へVisual Beat、Shot layout、Action、Camera及びリップシンクdirectiveを展開する処理フロー](../assets/direction-planner-flow.png)

青はLLMへ渡す処理、緑はPythonが所有する決定的処理、橙は利用者又は上流からの入力です。Direction Enhancerは全体方針を一度だけ統合し、Timeline Plannerは短い行protocolを五つのtaskへ分離します。LLMの採用行はActionとCamera本文としてAS ISで流し、EMD構造、CUT/CONTINUE、H3時間格子、台詞保護及びlip-sync directiveはPythonが所有します。

外部profileの文法と追加方法は[Direction profile EMD](../../profiles/README.md)、各socketは[Direction Enhancer](../nodes/direction-enhancer.md)と[Timeline Planner](../nodes/timeline-planner.md)を参照してください。
