# Plan / Videoを分離する理由

配布workflowは、Plan / Compiler段階とVideo段階を一つの巨大なgraphにせず、方式ごとに二本へ分けています。これは単なる操作上の都合ではなく、再生成、障害復旧及び計算資源の境界です。

## 計画を固定してVideo段階を再実行する

Plan / Compiler段階は、人物と背景の認識、歌詞時刻、Direction、Scene/Shot構成、Action、Camera、lip-sync directive及び英訳済みH3 promptを確定します。その出力を`.txt`のPlan JSONとして保存します。

Video段階では同じPlan JSONを再利用し、前段の演出設計や歌詞対応を動かさずに再Queueできます。Video workflowに独立した「動画seed A/B」という入力はありません。必要な変更は、実在する`Scene Seed`、sampler、denoising steps、Review又はScene Debug Splitterの各ノード上で行います。

## 重い処理を繰り返さない

統合workflowでは、後段の動画生成、Review、Scene連結又は保存処理が停止した時でも、Queue方法やcache状態によって次の前段処理を再実行しやすくなります。

- Vision GGUFによる人物・背景解析
- Whisper/VADによる歌詞整列とtargeted retry
- Direction LLM
- Lyric Cue、Visual Beat、Song Direction、Shot Layout、Action、Action Audit、CameraのPlanner呼び出し
- Compilerの日本語prompt翻訳

これらを先に完了してPlan JSONへ固定すれば、後段だけを再実行できます。LLM、Vision、WhisperとH3を同じ実行に抱えないため、モデルのload/unload、VRAM、待ち時間及び停止原因も切り分けやすくなります。特に限られたVRAMを想定する本プロジェクトでは、統合による利便性より再開可能性を優先します。

## どこから再実行するか

| 変更内容 | 再実行する段階 |
|---|---|
| Scene Seed、sampler、denoising steps、Review設定 | Videoだけ |
| Scene Debug Splitterの範囲 | Videoだけ |
| 人物・背景参照のH3入力だけを差し替える実験 | Videoだけ。ただしPlan内のSubject/Scene定義との不一致に注意 |
| 歌詞、音源時刻、Direction、profile、Planner seed、Scene構成 | Plan / Compilerから |
| Subject EMD又はScene EMDを変える | Plan / Compilerから |
| Compiler翻訳条件又はTiming Profileを変える | 原則Plan / Compilerから |

動画workflowには、対応方式のPlanを渡します。`01`と`02`、`03`と`04`、`05`と`06`を組にし、異なるlip-sync方式のPlanを混ぜません。Planに記録された必要Picture、音声方式及び時間契約と、Video側の参照入力を一致させます。

## デバッグ

全編を再生成する必要がない場合は、Video workflowの`Scene Debug Splitter`を有効にします。保存済みPlanと二つのPCMを同じ連続Scene範囲へ切り出すため、計画全体を変えずに問題Sceneだけを反復確認できます。使い方は[Scene Debug Splitter](../nodes/scene-debug-splitter.md)を参照してください。
