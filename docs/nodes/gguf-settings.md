# GGUF共通設定

Image to Subject EMD、Direction Enhancer、Timeline Planner、EMD Compilerで共通する主な設定です。ノードごとに許容値と既定値が少し異なります。

| 項目 | 意味 | 初期方針 |
|---|---|---|
| `model_name` | `models/LLM/GGUF`等から探索したGGUF | 配布WFはGemma4 31B Q4_K_S。Visionは対応mmprojを併用 |
| `chat_format` | chat template | 配布WFは`auto`。GGUF自身のtemplateを使う |
| `max_tokens` | 応答上限 | 小さすぎるとprotocolが未完了になる |
| `temperature` | 生成の揺らぎ | Compilerは`0`、他も低値を基準にする |
| `top_p` | nucleus sampling | 既定`0.9` |
| `repetition_penalty` | 反復抑制 | 既定`1.05` |
| `gpu_layers` | GPUへoffloadするlayer数 | `-1`は可能なlayerをoffload |
| `n_batch` | prompt処理batch | VRAM不足時は下げる |
| `n_ctx` | context上限 | 配布WFはVision/Planner/Enhancerが24,576、Compilerが16,384 |
| `flash_attn` | Flash Attention | 対応buildでは`true` |
| `kv_cache_type` | KV cache量子化 | 配布WFは`q8_0` |
| `op_offload` | 演算offload | 既定`true` |
| `keep_model_loaded` | 実行後もmodelを保持 | 配布WFは`false`。次段のH3へGPUを解放する |
| `seed` | LLM生成seed | 比較中は固定値を使う |
| `cache_mode` | 成功cache | `reuse`、`refresh`、`disabled` |

`reuse`は同じ入力・モデルfingerprint・生成条件・prompt版の成功結果だけを再利用します。`refresh`は再生成して成功結果を更新し、`disabled`は読み書きしません。失敗結果はcacheしません。

VRAM 8 GBは現在の対象外です。容量要件は量子化・context・offloadに依存し、未検証構成の動作を保証しません。導入条件は[導入マニュアル](../installation.md)を参照してください。
