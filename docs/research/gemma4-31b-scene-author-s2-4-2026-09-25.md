# Gemma 4 31B：実8B入力の再生と苔・花Scene短区間映像（2026-09-25）

## 目的と入力の出典

`audio_ref_compact_s2_4_20260924.mp4`は人手でH3文を簡潔化した比較結果であり、8Bの生成文そのものではない。モデル比較ではこれを8Bの代表として使わず、同じ楽曲のScene 2–4を収めた[8Bの保存済みオフラインScene Author実行](../assets/research/scene-composition-full-sequence-2026-09-23/p1b-six-scenes-seed2-v2/summary.json)から、Event・Performance・Camera計9件の**実際のsystem promptとJSON payload**を抽出した。抽出物と8Bの応答は[実験素材](../assets/research/gemma4-31b-scene-author-s2-4-2026-09-25/manifest.json)に分離した。Gemmaへの入力からはQwen固有の`/no_think`だけを外し、8Bの応答はGemmaに見せていない。

この保存済みトレースは**対象動画を作った本番Planner呼出しそのものの生ログではない**。同じ題材を使い、8Bに実際に投入した別のP1bオフライン実行である。完全な「モデルだけを交換した本番経路」ではないことを前提に、まず31Bが同じ役割・歌詞・Scene情報から何を生成するかを調べた。

モデルはローカルの公式Gemma 4 31B Instruct GGUF（Unsloth Q4_K_S、19.70 GB）を使用した。LM Studioで16,384 token、並列1、GPU最大オフロードとしてロードし、temperature 0.2、top_p 0.9で推論した。先にLM Studioでユーザーがロードしていた派生版Heretic Ara Q6は、この実験には使用していない。

## 31Bのテキスト結果

- [Scene 3 Performance](../assets/research/gemma4-31b-scene-author-s2-4-2026-09-25/scene-03-performance-gemma-result.json)は2/2行、[Scene 4 Performance](../assets/research/gemma4-31b-scene-author-s2-4-2026-09-25/scene-04-performance-gemma-result.json)は3/3行を返した。苔Sceneでは胸郭、後退と前方への切返し、視線、指先の変化を時間順に記述した。花Sceneでは重心を沈め、右腕を弧状に開き、最後に顔・視線と袖口の動作へ進む。
- Event・Cameraも同じ保存済み8B入力から推論し、応答ファイルを同directoryに保存した。ただし今回の映像には**Performanceのみ**を採用した。EventまたはCameraも同時に差し替えると、人物演技単独の映像効果を切り分けられないためである。
- 思考tokenを含めた上限1,024ではScene 3 Performanceが本文を返す前に`length`で停止した。Eventの上限2,048、Scene 4 Cameraの上限2,048でも同様の事象を観察し、それぞれ上限を広げて再取得した。これは入力が16kを超えた証拠ではなく、出力枠に思考が含まれる実装上の注意点である。

## H3短区間の比較条件

[元の8B EMD](../assets/research/gemma4-31b-scene-author-s2-4-2026-09-25/qwen3-8b-full.emd.md)と[31B演技差し替えEMD](../assets/research/gemma4-31b-scene-author-s2-4-2026-09-25/gemma4-31b-body-full.emd.md)は16 Scene全体を保持し、[差分](../assets/research/gemma4-31b-scene-author-s2-4-2026-09-25/emd-body-diff.patch)はScene 3・4の人物演技5行だけ。両方とも既存EMD parserで16 Sceneとして解析した。31B側のEMDは**比較注釈**であり、Plannerが直接生成したものではない。

動画は元の英語Plan（SHA-256 `3dce5133ab8f42aa12e2762439793fb4ed08863c99ce48689f8d3eeb1035eda9`）から[翻訳済み31B演技](../assets/research/gemma4-31b-scene-author-s2-4-2026-09-25/gemma-performance-english.json)を反映した[比較Plan](../assets/research/gemma4-31b-scene-author-s2-4-2026-09-25/gemma-body-scene3-4-plan.json)で生成した。変更はScene 3概要と2 Shot、Scene 4概要と3 Shotの7 prompt行のみ。元Planの対象位置を短く保持し、各ShotのCamera後半文は原文のまま残した。Scene 2、seed、尺、参照画像、音声、H3 Hybridモデル、8 steps、動画graphは不変。Graphで変更した追加箇所は別run名・ファイル名のみ。ComfyUIは`--fast fp16_accumulation`で起動し、提出ID `eb265e85-c7ea-4356-9d48-10e35ca2436a`が成功した。再現用の[提出graph](../assets/research/gemma4-31b-scene-author-s2-4-2026-09-25/submitted-api-prompt.json)も保存した。

| 映像 | 場所 | SHA-256 |
|---|---|---|
| Qwen3 8B元Plan | [30.667秒・736 frame](<C:/Software/ComfyUI/output/h3_chains/audio_ref_body_s2_4_context_20260924/final/audio_ref_body_s2_4_context_20260924.mp4>) | `c549dfb5812d1c7ffcea288ba32510a07bf7993dc7ea8ac678288bfc94edb09e` |
| Gemma 4 31B演技置換 | [30.667秒・736 frame](<C:/Software/ComfyUI/output/h3_chains/gemma4_31b_body_s2_4_20260925/final/gemma4_31b_body_s2_4_20260925.mp4>) | `28f37d9cd93b9fc021688b5de9e58e00af0f683703742b9d055b3fe173b06073` |
| 上下比較・無音 | [864×960・24 fps・736 frame](<C:/Software/ComfyUI/output/h3_chains/gemma4_31b_body_s2_4_20260925/comparison/qwen3-8b_vs_gemma4-31b_vertical.mp4>) | `76586811d8b2be7503e6dba3b0781527b11feaaf4ff57aedf6fe56c829441b89` |

上下比較は上がQwen3 8B元Plan、下がGemma 4 31B演技置換。両方をフレーム番号で24 fpsへ整列し、音声を除いた。23秒の[比較フレーム](../assets/research/gemma4-31b-scene-author-s2-4-2026-09-25/comparison-frame-23s.png)では、8B側が顔と花へ寄り、31B側は人物全身と参道脇の花を広く見せている。ただし、単一静止画で演技の良し悪しは決めない。連続視聴による人間の判定を待つ。

## 解釈上の制限

今回のH3は「実8B入力に対する31Bの人物演技案が、保存済み8B Planの同区間でどう映るか」という**差し替え試験**である。元の本番8B PlannerとGemmaを同じライブ上流状態から全段通したA/Bではない。GemmaのEvent・Camera応答や、Scene 2の31B再計画は動画へ入れていない。英訳も31Bの追加呼出しで行ったため、その揺らぎは残る。ゆえに、この映像だけで31B一般が8Bより優れる／劣るとは判定しない。

次に必要な判定は、上下動画を連続で見て、人物の重心・胸郭・両腕と花／苔の見せ方がどちらで説得力を増すかを記録すること。その結果が良好であれば、Event→Performance→Cameraを31Bで一貫して再計画し、同一上流入力からCompilerを通す第二段階を設計する。5060への縮約はその後の問題として分ける。
