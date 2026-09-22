# 旧EMDに基づく身体演技・Camera連携のCPU予備試験

2026-09-22

## 目的と条件

[旧EMD評価](restored-prototype-emd-choreography-2026-09-22.md)で提案した「身体の連続変化を、Cameraの見せ方と同時に考える」を、全曲Plannerへ導入する前に小範囲で試した。ComfyUIがGPUを使用中のため、今回のモデル実行はすべて `gpu_layers=0` のCPU推論で、H3レンダリングやComfyUIの起動はしていない。

[既存実験](scene-body-chain-offline-2026-09-22.md)と同じ固定fixture SHA-256 `b131cdff9a35e254efa76dd8245d86c63f4731289588ddd31374a704fc5ff675`、Qwen3 8B Q4_K_M、seed 1、`n_ctx=8192`、`max_tokens=1200`を使用した。対象はScene 11の2 Shotと、継続するScene 12の1 Shot。歌詞・Cue・Shot境界を固定し、元Actionをモデル入力へ渡していない。Cueは保存歌詞から再構成した代理Cueであり、実際のPlanner Cue Cardの再現ではない。

比較条件は以下の通り。

| 条件 | 追加した入力 | モデル出力の証拠 |
| --- | --- | --- |
| 既存のShot連鎖 | なし | [既存baseline](../assets/research/scene-body-chain-2026-09-22/unified_shot_chain/evidence.json) |
| Camera役割 | Shotごとの撮影範囲と受け渡し | [CPU結果](../assets/research/scene-body-chain-2026-09-22/camera_guided_shot_chain_cpu/evidence.json) |
| Scene固有の短い身体意図＋Camera役割 | 上記に加え、歌詞の感情を身体へ展開する手書きbrief | [CPU結果](../assets/research/scene-body-chain-2026-09-22/brief_camera_guided_cpu/evidence.json) |

後二条件の入力は [Camera scaffold](../assets/research/scene-body-chain-2026-09-22/camera-scaffold.json) と [身体brief](../assets/research/scene-body-chain-2026-09-22/performance-brief.json) に保存した。後者は実験用の人手による条件設定で、現行Plannerが自動生成できることを示すものではない。

## 結果

両CPU条件とも2 Sceneの出力はJSONとして読め、Scene 12の始点姿勢はScene 11の終端姿勢と文字列上つながった。しかし、**撮影可能で固有な身体連鎖は得られなかった**。

- 既存baselineのseed 1は、Scene 11の2 Shotで左右を入れ替えた「手を胸／腰へ、足を前へ、前傾」の反復だった。
- Camera役割だけの条件は歩行と前傾を減らしたが、「右手を胸前→顔横」「左手は腰へ固定」という小さな手の動きへ縮んだ。Scene 12でも手を顔の前へ動かし、肩を少し倒すだけで、全身の感情変化にはならない。
- 手書き身体briefを加えると、Scene 11の右腕を外へ差し出す意図は一部実現した。しかし左手は腰→顔横へ動き、支持脚や体幹の明確な変化は出ず、Scene 12では右手が再び腰へ戻る。Camera役割に合わせて身体の主動作を進めるより、見える手を小さく動かす解釈に寄った。
- CPU実行時間はCamera条件のScene 11/12が約93/61秒、brief＋Camera条件が約186/112秒。後者の高コストに見合う演技改善は確認できない。CPU時間は5060のGPU時間へ換算できないが、新しい全曲推論段を安易に追加しない判断を補強する。

この2条件はseed 1のみの予備試験であり、偶然性を排除できない。ただし、どちらも本番既定へ採用する品質の候補ではない。Camera経路を与えるだけ、あるいはScene固有の身体意図を文章で加えるだけでは、8Bが支持・体幹・腕・表情の自然な連鎖へ必ず変換するとは言えない。

## 保存済み実Plannerキャッシュとの照合

2026-09-22 14:12:12の成功キャッシュ `C:/Software/ComfyUI/temp/mv_director/planner_cache/15/15a460124e519025a310f9485557e8a6476c265e4fbf3cf9af484c444bab0490.json` を読み取り専用で確認した。これはオフラインfixtureとは別の実行で、16 SceneのCue Card、29 Action、24 Scene-spine Shotが保存されていた。

身体主導の時点で「手を上げて下げる」「前傾する」「肩を揺らす」という近縁動作が多い。例としてScene 11の身体主導は肩・腕・足を前に出し終端で手を顔前に止めるもの、Scene 12は左右を入れ替えたほぼ同形だった。Scene spineとActionもこれを引き継ぎ、Scene 12では「鳥居の上へ足を置く」に進んでいた。後段Actionの語彙不足だけではなく、**Cue Cardが最初に固定する身体意図と終端状態の反復・空間解釈**が主要な上流ボトルネックである。Camera指示だけを変えても、この上流の動作は別の振り付けへ変わらない。

## 次の実装判断

この時点では[オフライン比較ツール](../../tools/offline_scene_body_chain.py)の条件、入力資料とテスト、およびVisual Beatステージのdance_phrase向け身体主導・終端指示を検討した。後者は後続の[GPU 3 seed比較](choreography-gpu-ablation-2026-09-22.md)で改善が確認できなかったため、本番プロンプトへの変更を撤回した。現行PlannerのAction/Camera構造、LLM呼出し回数、プロファイル既定値はこの予備試験では変えていない。

次は実際のCue Cardにある`身体主導`と`終端`、Scene spineの`FROM/ADVANCE/TO/SHOW`を保存して入力差を調べる。今回の代理Cueと手書きbriefでは、旧Plannerが与えていた実際の情報量を比較できない。実データ上で、(1) 身体意図自体が不足するのか、(2) 十分な意図がActionへ転送されないのか、(3) Camera coverageが完成したActionを見せられないのかを切り分ける。そのうえで既存ステージの入力・出力契約だけを改修し、全曲LLM段階の追加は避ける。

GPUを使った3 seedの短区間比較結果と採用判断は[後続レポート](choreography-gpu-ablation-2026-09-22.md)を参照。今回の指示文だけによる候補はEMD品質基準を満たさず、短いH3区間へは進めていない。
