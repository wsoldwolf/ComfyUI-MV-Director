# H3高速化設定と安定性

Comfy Kitchen、SLA、Spectrum、FP16 accumulationの運用上の注意と、2026-09-27〜28の低速化・全編検証をまとめます。導入に必要なclone手順は[導入マニュアル](../installation.md)、配布WFの使い方は[workflowマニュアル](../../workflows/README.md)を参照してください。

現在の動画workflowは、次の順序でモデルへ設定を適用します。これらはTurbo LoRAの代替となる高速化構成ですが、同じ画質や速度をすべての環境で保証するものではありません。

```text
Hybrid Loader → Turbo LoRA（バイパス）→ Model Attention Backend
             → Block Sparse Attention → Spectrum
             → Model Patch Torch Settings → Sigma Shift
```

## Comfy Kitchen

`ModelAttentionBackend`で`comfy kitchen attention`を選択します。ComfyUI本体が利用する`comfy-kitchen`のAttention実装を使用する設定で、別の「Comfy Kitchen」カスタムノードをcloneするものではありません。対応するComfyUI・依存package・GPU環境が必要です。導入については[Comfy Kitchen公式リポジトリ](https://github.com/Comfy-Org/comfy-kitchen)を参照してください。

この設定はAttentionの実行方法を選ぶものであり、モデル全体をVRAMへ常駐させる設定ではありません。Dynamic VRAM、Block Sparse Attention、Spectrumと併用する際は、各実装の対応版を揃えてください。

## Block Sparse Attention（SLA）

ComfyUI本体の`BlockSparseAttention`で`selection=sla`を選択します。重要と判定したAttention blockを選び、計算対象を減らす近似的な高速化です。現在の配布workflowの設定は次の通りです。

| 項目 | 設定値 |
| --- | --- |
| `selection` | `sla` |
| `selection.keep_percent` | `10` |
| `start_percent` / `end_percent` | `0.2` / `1.0` |
| `min_tokens` | `12288` |
| `extra_tokens` | `256` |
| `sink_conditioning` | `exact_kv_and_rows` |

`keep_percent=10`は選択するblockの割合を指定する値であり、総計算量が必ず10%になるという意味ではありません。適用期間外、token数が閾値未満の場合などはdense計算になります。`exact_kv_and_rows`は、H3の参照条件に関わるKVと所定のquery行をdenseに扱う設定です。映像・参照再現性・音声への影響も含めて確認してください。

## Spectrum

[ComfyUI-Spectrum-MiniMax-H3](https://github.com/xmarre/ComfyUI-Spectrum-MiniMax-H3)は、過去のH3計算から一部のステップを予測し、モデルの実計算回数を削減します。Planの20stepすべてで同じ重い計算を実行するわけではありません。現在の配布workflowでは`enabled=true`、`history_storage=system_ram`、`offline_archive_storage=system_ram`、`offline_smoothing_replay=true`です。RAM保存を選んでも、一時的なCUDAメモリの使用やCPU–GPU間の転送がなくなるわけではありません。

### 2026-09-27の更新と2026-09-28の全編確認

- 旧導入版は`v0.2.23`。0.9MP・20step・Turbo LoRAなしで短区間が完走しても、全編では再び大幅な低速化が発生しました。低速時はGPU使用率が高い一方、消費電力が約140 Wへ低下し、PCIe転送が大きく増える状況が見られました。これだけで原因を特定したものではありません。
- `v0.2.25`は、SpectrumとComfyUI Dynamic VRAM / Comfy Compilerのmalloc-graph互換性を修正しています。最初の生成が完了しても次の生成でクラッシュする事例が対象です。本プロジェクトの低速化と同一の不具合と断定はしていません。[v0.2.25修正内容](https://github.com/xmarre/ComfyUI-Spectrum-MiniMax-H3/releases/tag/v0.2.25)
- `v0.2.27`は、実計算ステップのCUDA hidden tensorが参照に保持される問題を修正し、予測時の出力投影もRAMから小分けに転送する方式へ変更しています。履歴の保存先がRAMでもCUDA tensorが残る問題だったため、今回の有力な確認対象です。修正目的はVRAM圧迫の軽減で、無条件の高速化や数値的に同一の出力を保証するものではありません。[v0.2.27修正内容](https://github.com/xmarre/ComfyUI-Spectrum-MiniMax-H3/releases/tag/v0.2.27)、[修正PR #107](https://github.com/xmarre/ComfyUI-Spectrum-MiniMax-H3/pull/107)
- Spectrum `v0.2.27`とComfyUI `v0.37.4`へ更新し、起動引数の`--disable-fast-disk`を外した構成で、2026-09-28に全21区間の完走を確認しました。今回の全編では、以前のようなストールは報告されていません。単一の全編試験による安定候補であり、原因の確定やすべての環境での再現を意味しません。
- 旧構成で`--disable-fast-disk`とSpectrumを併用した継続Sceneは、20stepで5分48秒、5分18秒、4分08秒の完走例がありました。ただし全編で再発したため、短区間の成功だけで「解決済み」としない方針です。

今回の比較条件は**0.9MP・Planの`default_steps=20`・Turbo LoRAバイパス**です。Sceneごとの経過時間、GPUメモリ、消費電力、PCIe転送量、画質を記録してください。Spectrumの予測やreplayがあるため、進捗表示の一時的な`it/s`だけでは全体の処理時間を判断できません。ComfyUIとSpectrumを同時に更新しているので、改善してもどちらの変更が原因かはこの試験だけでは確定しません。

再発した場合は、まず他の設定を維持して`--disable-fast-disk`だけを戻し、同条件で比較します。さらに必要なら別の試験で`offline_smoothing_replay=false`を比較します。一度に複数の設定を変えないでください。完走構成を基準として保存し、速度比較の変更は一項目ずつ行います。配布WFの解像度はその後0.4MPへ変更していますが、ここで記録した全編試験は0.9MPであり、条件を混同しないでください。

### 完走時の所要時間

- 全体：3時間15分53秒。
- サンプリング表示の合計：2時間44分15秒（全21区間）。
- 1区間平均：約7分49秒。最短3分08秒、最長10分00秒。
- サンプリング表示以外の処理との差分：約31分38秒。conditioning、モデル準備、decode、保存等の内訳はこのログだけでは確定していません。

旧版で成功した短区間より遅い区間もありましたが、同一条件のA/Bではありません。ComfyUI更新、Spectrum更新、fast-disk設定が同時に変わっているため、速度変化を一つの修正だけに帰することはできません。後半も所要時間が単調に増え続ける傾向は見られませんでしたが、Sceneの尺・条件が異なるため厳密な性能比較ではありません。

### Spectrumの更新・退避

SpectrumをGitで管理している場合は、ComfyUI終了後、まず`git status --short`でローカル変更を確認してから`git fetch origin --tags`でタグを取得します。今回の再現対象を固定する場合は`git checkout --detach v0.2.27`を使用します。ZIP又はManager経由で導入したフォルダには`.git`がない場合があり、その状態での`git pull`は親のComfyUIリポジトリを対象にしてしまう可能性があります。Spectrum自身のGit checkoutであることを確認してください。旧版を退避する場合は二重読み込みを避けるため、退避先を`custom_nodes`の外に置きます。

## fast FP16 accumulation

`ModelPatchTorchSettings`（KJNodes）の`enable_fp16_accumulation=true`で、`torch.backends.cuda.matmul.allow_fp16_accumulation`を有効にします。対応するFP16行列積でFP16の累積を許可する設定です。全モデル・VAE・Text EncoderをFP16へ変換する設定ではなく、BF16の演算すべてをFP16へ変更するものでもありません。速度への効果は、実際に使用されるdtype、演算kernel、GPUに依存します。数値精度にも影響し得るため、画質と安定性を確認してください。

このノードは接続したモデルの実行前にPyTorchのプロセス共通フラグを設定し、cleanup時に解除するcallbackを登録します。ノード内だけに閉じたdtype設定ではありません。切り分け時はノードのbooleanを`false`にし、起動引数にも`--fast fp16_accumulation`を指定していないことを確認してください。起動引数とノード設定を同時に変えると比較条件が不明瞭になります。
