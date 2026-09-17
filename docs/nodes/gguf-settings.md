# GGUF共通設定

Image to Subject EMD、Direction Enhancer、Timeline Planner、EMD Compilerで共通する主な設定です。ノードごとに許容値と既定値が少し異なります。

| 項目 | 意味 | 初期方針 |
|---|---|---|
| `model_name` | `models/LLM/GGUF`等から探索したGGUF | Visionはmodel+mmproj、他はText GGUF |
| `chat_format` | chat template | 原則`auto`または空。必要時だけ`qwen`/`gemma` |
| `max_tokens` | 応答上限 | 小さすぎるとprotocolが未完了になる |
| `temperature` | 生成の揺らぎ | Compilerは`0`、他も低値を基準にする |
| `top_p` | nucleus sampling | 既定`0.9` |
| `repetition_penalty` | 反復抑制 | 既定`1.05` |
| `gpu_layers` | GPUへoffloadするlayer数 | `-1`は可能なlayerをoffload |
| `n_batch` | prompt処理batch | VRAM不足時は下げる |
| `n_ctx` | context上限 | Planner/Enhancerは16K、Compilerは32K基準 |
| `flash_attn` | Flash Attention | 対応buildでは`true` |
| `kv_cache_type` | KV cache量子化 | 8GB VRAMでは`q8_0`を基準にする |
| `op_offload` | 演算offload | 既定`true` |
| `keep_model_loaded` | 実行後もmodelを保持 | 8GB VRAMでは`false`を推奨 |
| `seed` | LLM生成seed | 比較中は固定値を使う |
| `cache_mode` | 成功cache | `reuse`、`refresh`、`disabled` |

`reuse`は同じ入力・モデルfingerprint・生成条件・prompt版の成功結果だけを再利用します。`refresh`は再生成して成功結果を更新し、`disabled`は読み書きしません。失敗結果はcacheしません。

VRAM 8GBでは複数GGUFやH3 modelを同時保持しないよう、まず`keep_model_loaded=false`で動作確認してください。
