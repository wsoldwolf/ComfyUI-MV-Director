# RTX 5080でGemma4 31B IQ3 XSを使う設定

VRAM 16GBのRTX 5080で、Gemma4 31B IQ3_XSを使う場合の開始設定をまとめます。2026-10-04時点のモデル構造と現行コードから計算した目安であり、この4ノード構成をRTX 5080実機で通して検証した結果ではありません。動作保証や自動設定ではなく、手動調整の起点です。

このTIPSのVRAM容量・context計算の対象モデルは`gemma-4-31B-it-heretic.i1-IQ3_XS.gguf`です。[配布元](https://huggingface.co/mradermacher/gemma-4-31B-it-heretic-i1-GGUF)と配置手順は[導入マニュアル](../installation.md#text推論を31b-iq3_xsへ切り替える)を参照してください。26B MoEや12BのIQ3モデルには、この計算を適用しません。一方、以下のPlanner推論高速化はIQ3_XS専用ではなく、通常パイプラインの既定Q4_K_Sにも適用されます。メモリ容量の見積もりと、高速化の適用条件を区別してください。

## 推奨する開始設定

| ノード | n_ctx | n_batch | KVキャッシュ概算 | 注意点 |
| --- | ---: | ---: | ---: | --- |
| 人物・背景Vision | 4096 | 128 | 約1.83GiB | IQ3_XSと対応mmprojを使い、`mmproj_use_gpu=false`でprojectorをCPUへ配置する場合 |
| Direction Enhancer | 16384 | 256 | 約1.18GiB | 通常のユーザー指示・プロファイル入力向け |
| Timeline Planner | 24576 | 256 | 約1.51GiB | 歌詞・演出候補・前Scene情報の余裕を確保。VRAM不足時は16384から試す |
| EMD Compiler | 8192 | 256 | 約0.85GiB | field単位で翻訳するため、全編EMDを一括でcontextへ保持しない |

共通の前提は`gpu_layers=-1`、`kv_cache_type=q8_0`、`flash_attn=true`、`op_offload=true`、`keep_model_loaded=false`です。ノードは順次実行し、LLM・H3・LM Studio等を同時にGPUへ常駐させない構成を想定しています。`gpu_layers=-1`でも必要なVRAMが自動的に16GBへ収まるわけではありません。

`n_ctx`には入力、Visionの画像token、出力が含まれます。`max_tokens`は別途確保する出力上限なので、入力だけが上記の長さまで入るわけではありません。context予算エラーとVRAM不足は別の問題として確認してください。モデル側の巨大な既定contextを選ばないよう、`n_ctx=0`ではなく表の値を指定します。

## 通常パイプラインの推論高速化

2026-10-05時点の[Planner実装](../../nodes/node_timeline_planner/node.py)は、選択したGGUFのファイル名から次の生成方式を自動選択します。RTX 5080専用の処理ではなく、通常のPlannerノードと配布WFで使用します。

| GGUFファイル名 | grammarなしで初回生成する担当 | 初回からgrammarを使用する担当 |
| --- | --- | --- |
| `gemma-4-31b-it-heretic-ara.Q4_K_S.gguf` | Performance・Camera | Event・候補選択 |
| `gemma-4-31B-it-heretic.i1-IQ3_XS.gguf` | Performance・Camera | Event・候補選択 |
| `Gemma4-26B-A4B-Uncensored-HauhauCS-Balanced-IQ2_M.gguf` | Event・Performance・Camera | 候補選択 |

対象担当では、毎tokenのgrammar制約を省いて生成し、その後にline protocolを検査します。不整合があればgrammar付きで再推論し、必要なslotが欠けた場合は該当slotをgrammar付きで再試行します。検査を省略する方式ではありません。上記以外のファイル名は初回からgrammar付きです。ディレクトリ名とファイル名の大文字・小文字は判別に影響しませんが、GGUFのファイル名自体は変更しないでください。別の量子化やすべてのGemmaモデルへ一律に適用するものではありません。

適用時のPlannerログは`sampling=unconstrained_first`、初回からgrammarを使う担当は`sampling=grammar`です。`fallback=grammar_full_batch`は出力不整合による再推論を示します。ログで推論を確認する際は`cache_mode=refresh`を使用してください。キャッシュ再利用時は推論自体を省略します。再推論の頻度、CPUに残すモデル層、入力長によって効果が変わるため、一定の速度向上倍率は保証しません。

別の共通設定として、[Text lifecycle](../../core/inference/llama_cpp_backend.py)はEnhancer・Planner・Compilerのモデル読み込みで`swa_full=False`と`offload_kqv=True`を指定し、`op_offload`と`flash_attn`はノード設定に従います。これらはIQ3_XS限定ではありません。ただし、上記のgrammarなし初回生成はPlannerだけの仕組みです。Visionは別の読み込み経路であり、Textと同じSWA設定とは限りません。

通常パイプラインへの適用に追加UI・専用WFは不要です。Q4_K_Sでも高速化経路は使用しますが、このTIPSのIQ3_XS向け容量計算をQ4_K_Sへ流用して16GBに収まると判断しないでください。

## 計算の前提

[配布元メタデータ](https://huggingface.co/api/models/mradermacher/gemma-4-31B-it-heretic-i1-GGUF?blobs=true)で確認したファイル容量は13,072,368,576 bytes、約12.17GiBです。以下ではこれをモデル重みの保守的な容量目安として扱います。ファイル容量と実際のCUDA model bufferは同じとは限りません。

[モデル構成](https://huggingface.co/coder3101/gemma-4-31B-it-heretic/blob/main/config.json)は60層で、SWA（Sliding Window Attention）が50層、通常Attentionが10層です。SWAはKV headが16、head次元が256、通常AttentionはKV headが4、head次元が512、SWA幅は1024です。KとVをそれぞれq8_0で確保する前提の概算式は次です。

```text
KV bytes ≈ (SWA cells × 50 × 16 × 256
          + n_ctx × 10 × 4 × 512) × 2 × 34 / 32
```

Textノードの`n_batch=256`では、SWA cellsを1024＋256＝1280として計算しています。llama.cppは縮小SWA cacheを窓幅と処理batchから確保し、256 cells単位へ丸めます。[SWA cache実装](https://github.com/ggml-org/llama.cpp/blob/master/src/llama-kv-cache-iswa.cpp)

Textでは、モデル容量目安とKVの合計はEnhancerの16kで約13.36GiB、Plannerの24kで約13.69GiB、Compilerの8kで約13.03GiBです。演算バッファ、CUDA、Windowsの画面表示、他プロセスの使用量は含みません。これらを加えたピークVRAMは実機で確認する必要があります。

## Visionだけcontextを小さくする理由

現行の[Text lifecycle](../../core/inference/llama_cpp_backend.py)は`swa_full=False`を明示しています。一方、[Vision lifecycle](../../core/vision/llama_cpp_vision.py)は指定しておらず、確認したllama-cpp-python 0.3.34のnative既定値は`True`でした。この状態のVisionは、SWA層にも全context分のKVを確保するため、Textとはメモリ増加率が異なります。ランタイム更新後は既定値も再確認してください。

Visionの4096ではモデル容量目安＋KVが約14.00GiBですが、8192では約15.83GiBになります。8192ではprojectorをCPUへ置いても、演算バッファや画面表示に十分な余裕がありません。projectorのCPU配置はprojector側のVRAMを減らす設定で、LLMのKVをCPUへ移す設定ではありません。

VisionもIQ3_XSへ切り替えるには、対応するmmprojとモデルペアの互換性確認が必要です。上記はその場合のメモリ目安であり、本プロジェクトでのIQ3_XS Visionの実推論成功を示すものではありません。配布WFのVisionが既定のheretic-ara Q4_K_Sのままなら、この12.17GiBの計算は適用できません。またIQ3_XSは既定Q4_K_Sと別配布モデルで、単なる量子化違いとは限りません。

## 不足時の調整順序

1. H3、別のLLM、他プロセスがVRAMを保持していないか確認する。
2. TextではPlannerの`n_ctx`を24576から16384へ下げ、同じ入力でcontext予算も確認する。
3. VisionではmmprojのCPU配置と`n_batch=128`を確認する。4096で画像・出力が入らない場合は、単にcontextを増やさず、SWA設定の改善又は一部のLLM層のCPU配置を別途検討する。
4. CUDA OOMだけでなく、専用VRAM不足から共有GPUメモリへ退避して著しく遅くなる状態にも注意し、ピーク使用量と所要時間を記録する。

## RTX 5080での実行時間の事例

### 01 WFのプラン生成とコンパイル

2026-10-04のユーザー報告では、RTX 5080環境で01 WF（プラン生成・コンパイル）の実行が完了し、ComfyUIの総実行時間は14分41秒（881秒）でした。

```text
[INFO] Prompt executed in 00:14:41
```

これは01 WF全体の実測例であり、02 WFのH3動画生成時間や、個別ノードの推論時間ではありません。実行時の各ノードのモデル・`n_ctx`・GPU配置、入力の長さ、キャッシュ利用状況はこのログだけでは確認できないため、上記の推奨設定をすべて適用した結果とは断定しません。同条件での再測定や機種間比較では、これらの条件も併せて記録してください。

### 02 WFの全編動画生成

2026-10-05のユーザー報告では、RTX 5080環境で4分32秒（272秒）の動画生成が完了し、ComfyUIの総実行時間は7時間19分46秒（26,386秒）でした。

```text
[INFO] Prompt executed in 07:19:46
```

同日の追加報告による実行条件は次のとおりです。

* 生成解像度は0.9MP。
* Spectrumはストールする場合がまだあるため、バイパス。
* ComfyUIの起動引数に`--disable-fast-disk --disable-async-offload --disable-pinned-memory`を追加。

起動引数は、02 WF実行中にComfyUI／aimdoのモデル読み込みエラーが発生する場合があるため使用しています。先に報告された`GetOverlappedResult failed error=1450`は、Windowsの`ERROR_NO_SYSTEM_RESOURCES`（システム資源不足）です。この分類だけではRAM不足・VRAM不足などの具体的な原因や、各引数単独の改善効果までは確定できません。現状の回避設定として記録します。

これは02 WFのH3／Context Loopによる全編動画生成の所要時間の目安です。01 WFの言語生成時間とは別の測定です。step数、Scene構成、その他の高速化設定やソフトウェアのバージョンは今回の報告だけでは確認できないため、同じ長さの動画が常にこの時間で生成できるとは限りません。

このTIPSの追加では、WF、ジェネレーター、VisionのSWA設定、実行中の動画生成は変更していません。
