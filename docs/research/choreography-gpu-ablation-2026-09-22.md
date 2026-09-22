# 身体振り付け：8B短区間GPU比較と採用判断

2026-09-22

## 結論

GPUを解放した状態で、Qwen3 8B Q4_K_Mの短区間推論を計27回実行した。Visual Beat指示の増補、Motion共通文の短縮、Action指示の簡略化、長尺Shotの複数段階化、1 Shot内のAction複数行化、旧プロトタイプの歌詞Action Blueprint形式は、いずれも**身体演技の改善を確認できなかった**。形式どおりの行が出ることと、MVに使える動作が出ることは別である。今回はH3レンダリングや全編Planner実行へ進まない。

本番へ採用した変更は、継続Sceneの最初のActionとScene Spineに、直前Sceneで確定したLLMの終端姿勢を原文のまま渡す小改修だけである。前SceneにScene Spineがあれば最後の`TO`、なければCue Cardの`終端`を使用する。Pythonは自然文を修復・生成しない。この変更は姿勢引き継ぎの情報欠落を減らすもので、振り付けの多様性向上やH3での改善は**未検証**である。

## 比較条件と証拠

モデルは`qwen3-8b-abliterated-Q4_K_M.gguf`、`gpu_layers=-1`、`temperature=0.2`、seed 1/2/3、同一条件内で歌詞・Scene/Shot境界を固定した。各生応答、入力、プロンプトSHA-256、所要時間は以下に残した。Visual Beat実験は実キャッシュ由来のScene 11–12を使用した。Action実験は[既存の固定fixture](../assets/research/scene-body-chain-2026-09-22/fixture.json)から元Actionをモデル入力に含めず、**代理Cue**を使った。両fixtureの歌詞は異なるので、実験群を横断した優劣はつけない。

| 条件 | 推論数 | 観察 | 証拠 |
| --- | ---: | --- | --- |
| Visual Beat旧指示 vs 身体主導・終端の強化指示 | 6 | 新指示でも「歩く」「くぐる」や左右反転の前傾・手上げへ戻った。追加指示は本番から撤回 | [seed 1](../assets/research/visual-beat-choreography-2026-09-22/seed1/evidence.json)、[seed 2–3](../assets/research/visual-beat-choreography-2026-09-22/seeds2-3/evidence.json) |
| Action現行 vs 4秒以上の複数身体段階 | 6 | 長い文章にはなるが、片足上げ・前傾・手上げの同型反復 | [比較](../assets/research/action-phases-2026-09-22/evidence.json) |
| Motion共通文だけ短縮 | 3 | 同型反復が残り、Motion文だけが主因とは言えない | [比較](../assets/research/action-phases-compact-motion-2026-09-22/evidence.json) |
| Actionシステム指示を短縮 | 3 | 左右を替えた肩・手・足の動きが残った | [比較](../assets/research/action-minimal-2026-09-22/evidence.json) |
| 1 Shotを時間順の2 Action行へ分割 | 3 | seed 1–2は左右反転が強く、seed 3も手を腰へ戻す定型が残った | [比較](../assets/research/action-per-phase-2026-09-22/evidence.json) |
| 旧`lyric_action_system_prompt.txt`による歌詞Action案 | 6 | Scene 3の苔を剥がす／踏みつける、Scene 4の「契りの表面を擦る」が出た。時系列Action行を増やしても意味・空間が破綻 | [固定歌詞と生応答](../assets/research/prototype-blueprint-gpu-2026-09-22/evidence.json) |

旧方式の比較は、別の具体物を含むScene 3–4の固定歌詞で実施した。旧プロンプトは「最初の物理述語」を強く優先するため、抽象的な歌詞を文字どおりの接触へ無理に変換した。旧実装の`planning.py`はこの歌詞Action案を後段へ渡すだけでなく、`_apply_lyric_action_blueprint`で後段Scene LLMのActionを置換・Shotへ配分していた。したがって、旧動画の振り付け差を「同じ8Bなのに旧システムプロンプトだけが優秀」と断定できない。現在のAS IS原則へこの置換をそのまま持ち込むのも適切でない。

## 今回の実装と次の判定

- `core/planner/engine.py`で、直前Sceneの最後のScene Spine `TO`をCue Card終端より優先して次の継続Sceneへ渡す。継続しないSceneには渡さない。Scene SpineとActionは同一の入力値を見る。
- `prompts/timeline_planner_scene_spine_system_prompt.txt`に、前Sceneの身体姿勢だけを継ぎ、歌詞対象・出来事を流用しない指示を追加した。Scene SpineとActionの生成文はAS ISのまま。
- Scene間引き継ぎの単体・Planner統合テストを追加した。アルゴリズム版を更新し、旧キャッシュの再利用を避ける。

次の品質評価は、実際の継続Sceneを短い範囲で生成し、前Sceneの最終姿勢と次Sceneの開始姿勢が整合するか、左右反転・前傾・手上げの反復が残るかをEMDで比較する。この手渡しで演技が豊かにならなければ、旧Blueprintの機械的置換ではなく、歌詞の出来事とScene単位の身体進行を**一度だけLLMが選ぶ契約**を設計し、まず歌詞の抽象行・具体物行の双方で安全性を検証する。全曲への新規推論段やH3全編生成は、短区間の文章品質が通るまで追加しない。
