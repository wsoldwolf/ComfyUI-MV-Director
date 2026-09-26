# 導入マニュアル

Windows版ComfyUIへComfyUI-MV-Directorを導入し、Text/Vision GGUFとOpenAI Whisperをローカル実行する手順です。基準環境はPython 3.13、CUDA 13.0、`llama-cpp-python 0.3.34`です。本書のコマンドは、Visual Studio専用プロンプトを含めて`cmd.exe`の構文へ統一しています。

## 1. 前提

- ComfyUIが`C:\Software\ComfyUI\`へ導入済みであること
- `C:\Software\ComfyUI\venv\`にComfyUI用Python仮想環境が構築済みであること
- ComfyUI v0.36.0 commit `ee71d5c4993f29086b27fde1629a945ae48425bf`
- ComfyUI-MiniMaxH3-Contex-Loop 0.6.9 commit `9860a063784c8c23b58e00107f2180e0df3c43d9`
- NVIDIA Driver、CUDA Toolkit 13.0
- Visual Studio 2022のDesktop development with C++とWindows SDK
- Git

異なるComfyUI / Context Loop commitでも動作する可能性はありますが、互換試験の基準外です。
本書はComfyUI本体及び`venv`の新規構築手順を扱いません。配置先が異なる場合は、以下の
`C:\Software\ComfyUI\`を実際のComfyUIルートへ読み替えてください。

### 検証環境

本プロジェクトでは、次のWindows PCを開発・動作検証に使用しています。

| GPU | CPU | メインメモリ | ストレージ | 備考 |
| --- | --- | ---: | --- | --- |
| NVIDIA GeForce RTX 5090 | AMD Ryzen 9 9950X | 256 GB | NVMe SSD 4 TB | 開発及び高負荷時の検証環境 |
| NVIDIA GeForce RTX 4070 Ti | AMD Ryzen 9 5900XT | 64 GB | NVMe SSD 4 TB | 動作検証環境 |
| NVIDIA GeForce RTX 5060 | AMD Ryzen 5 5500 | 16 GB | NVMe SSD 1 TB | Context Loop標準リップシンクは動作しません |

RTX 5060、メインメモリ16 GBの環境では、Context Loop標準リップシンクworkflowが停止することを確認しています。この構成ではAudio Reference方式又は歌詞方式のworkflowを検討してください。各方式の検証状況は[配布workflowの説明](../workflows/README.md)を参照してください。

## 2. カスタムノード本体

通常はComfyUIの`custom_nodes`へcloneします。

```bat
cd /d C:\Software\ComfyUI\custom_nodes
git clone https://github.com/wsoldwolf/ComfyUI-MV-Director.git
```

開発checkoutを別ドライブへ置く場合は、管理者権限のコマンドプロンプトでdirectory junctionを作れます。

```bat
mklink /J "C:\Software\ComfyUI\custom_nodes\ComfyUI-MV-Director" "E:\ComfyUI\projects\ComfyUI-MV-Director"
```

既存の実ディレクトリやjunctionを上書きしないでください。

動画生成workflowの`MiniMaxH3HybridLoader`を動かすには、別のカスタムノード
[ComfyUI_MinimaxH3HybridLoader](https://github.com/scottmudge/ComfyUI_MinimaxH3HybridLoader)
も必要です。`cmd.exe`でComfyUIの`custom_nodes`へcloneし、ComfyUIを再起動してください。

```bat
cd /d C:\Software\ComfyUI\custom_nodes
git clone https://github.com/scottmudge/ComfyUI_MinimaxH3HybridLoader.git
```

既にclone済みなら重複して実行しないでください。ノード検索で`MiniMax H3 Hybrid Loader`が表示されることを確認します。

## 3. `llama-cpp-python` CUDA wheelを作る

現環境のComfyUIはPython 3.13です。公式CUDA wheelのPython対応範囲と一致しない場合があるため、Vision対応を含むwheelをComfyUIのvenv用にsource buildします。

Visual Studioの「x64 Native Tools Command Prompt for VS 2022」を開き、次を実行します。Community以外のeditionでは`VsDevCmd.bat`のパスを読み替えてください。

```bat
cd /d C:\Software\ComfyUI
call "C:\Program Files\Microsoft Visual Studio\2022\Community\Common7\Tools\VsDevCmd.bat" -arch=x64 -host_arch=x64
venv\Scripts\activate

set "CUDA_PATH=C:\Program Files\NVIDIA GPU Computing Toolkit\CUDA\v13.0"
set "PATH=%CUDA_PATH%\bin;%CUDA_PATH%\libnvvp;%PATH%"
set "CMAKE_GENERATOR=Visual Studio 17 2022"
set "CMAKE_GENERATOR_PLATFORM=x64"
set "CMAKE_ARGS=-DGGML_CUDA=ON -DCMAKE_CUDA_ARCHITECTURES=89;120 -DGGML_NATIVE=OFF -DGGML_AVX=ON -DGGML_AVX2=ON -DGGML_FMA=ON -DGGML_F16C=ON -DGGML_AVX512=OFF -DGGML_AVX512_VBMI=OFF -DGGML_AVX512_VNNI=OFF -DGGML_AVX512_BF16=OFF -DGGML_AMX_TILE=OFF -DGGML_AMX_INT8=OFF -DGGML_AMX_BF16=OFF"
set "FORCE_CMAKE=1"

python -m pip install --upgrade pip setuptools wheel
if not exist dist mkdir dist
python -m pip -vvv wheel "llama-cpp-python==0.3.34" --no-deps --no-cache-dir --no-binary=llama-cpp-python -w dist
```

`89;120`はこのプロジェクトの検証環境向けです。別GPUでは対応compute capabilityへ変更してください。

### wheelを完全なファイル名でインストールする

まず生成名を確認します。

```bat
dir /b dist\llama_cpp_python-0.3.34-*.whl
```

検証環境で生成された完全名は次です。

```bat
python -m pip install --force-reinstall --no-deps "dist\llama_cpp_python-0.3.34-py3-none-win_amd64.whl"
```

`pip install dist\llama_cpp_python-0.3.34-*.whl`は使わないでください。Windowsの`cmd.exe`はこの位置のワイルドカードを`pip`用ファイル名へ展開せず、インストールに失敗します。表示された名前が上記と異なる場合は、`dir /b`の結果を省略せず引用符内へコピーします。

### TextとVisionのimportを検証する

```bat
python -c "import llama_cpp; from llama_cpp.llama_chat_format import MTMDChatHandler; print(llama_cpp.__version__); print(MTMDChatHandler.__name__); print(llama_cpp.llama_print_system_info().decode())"
```

`0.3.34`、`MTMDChatHandler`、CUDAを含むsystem infoが表示されれば、Text GGUFとVision GGUFの双方に必要なbindingを読み込めています。

上流の一般的なビルド説明は[llama-cpp-python公式README](https://github.com/abetlen/llama-cpp-python#installation-with-hardware-acceleration)を参照してください。

## 4. OpenAI Whisper

ComfyUIのvenvへOpenAI Whisperを導入します。検証済み版は`20250625`です。

```bat
cd /d C:\Software\ComfyUI
venv\Scripts\activate
python -m pip install "openai-whisper==20250625"
```

このプロジェクトは実行時にpackageやcheckpointを自動ダウンロードしません。OpenAI Whisperの`.pt` checkpointを次へ置きます。

```text
C:\Software\ComfyUI\models\whisper\
```

サブディレクトリ内も再帰探索します。

## 5. GGUFモデル配置

Text GGUFとVision GGUFは次へ置きます。

```text
C:\Software\ComfyUI\models\LLM\GGUF\
```

`extra_model_paths.yaml`等でComfyUIへ登録した`LLM` rootも探索します。

- Textノードは`.gguf`を再帰探索し、名前に`mmproj`を含むファイルを除外します。
- Visionノードは本体GGUFと`mmproj` GGUFが同じディレクトリにある組だけを候補にします。
- 同じディレクトリに複数`mmproj`があり一意に選べない組は表示しません。モデル系列名を含む`mmproj`、次いでF16/BF16/Q8の順で一意に解決します。
- 絶対パスをwidgetへ貼り付ける方式ではありません。配置後にComfyUIを再起動しcomboから選択します。

Text生成と英訳は8B級を推奨します。Visionだけは4B級でも比較的実用になります。

### `01_plan_compiler_context_loop.json`の既定モデル

配布workflowの`01_plan_compiler_context_loop.json`は、次のモデルを選択した状態で保存されています。Visionは本体GGUFだけでなく、同じディレクトリに対応する`mmproj-F16.gguf`も必要です。

| 用途 / 使用ノード | workflowで選択されるファイル | 取得元 |
| --- | --- | --- |
| 人物・背景の画像認識 / Image to Subject EMD | `gemma-4-31b-it-heretic-ara-GGUF/gemma-4-31b-it-heretic-ara.Q4_K_S.gguf`と同じフォルダの`gemma-4-31b-it-heretic-ara.mmproj-f16.gguf` | [mradermacher配布ページ](https://huggingface.co/mradermacher/gemma-4-31b-it-heretic-ara-GGUF)、[mmprojを取得](https://huggingface.co/mradermacher/gemma-4-31b-it-heretic-ara-GGUF/resolve/main/gemma-4-31b-it-heretic-ara.mmproj-f16.gguf?download=true) |
| Direction生成・Timeline計画・EMD英訳 / Direction Enhancer、Timeline Planner、EMD Compiler (Ref2VA) | `gemma-4-31b-it-heretic-ara-GGUF/gemma-4-31b-it-heretic-ara.Q4_K_S.gguf` | [mradermacher配布ページ](https://huggingface.co/mradermacher/gemma-4-31b-it-heretic-ara-GGUF)、[GGUFを取得](https://huggingface.co/mradermacher/gemma-4-31b-it-heretic-ara-GGUF/resolve/main/gemma-4-31b-it-heretic-ara.Q4_K_S.gguf?download=true) |
| 歌詞と音声の同期 / Lyric Segmentation | `medium.pt` | [OpenAI Whisper公式リポジトリ](https://github.com/openai/whisper)、[medium.ptを取得](https://openaipublic.azureedge.net/main/whisper/models/345ae4da62f9b3d59415adc60127b97c714f32e89e936602e85993674d08dcb1/medium.pt) |

次の配置にすると、workflowに保存された選択値を変更せず使用できます。

```text
C:\Software\ComfyUI\models\
├─ LLM\GGUF\
│  └─ gemma-4-31b-it-heretic-ara-GGUF\
│     ├─ gemma-4-31b-it-heretic-ara.Q4_K_S.gguf
│     └─ gemma-4-31b-it-heretic-ara.mmproj-f16.gguf
└─ whisper\
   └─ medium.pt
```

配置先のサブディレクトリ名を変更した場合は、ComfyUI再起動後に各ノードのcomboで実ファイルを選び直し、workflowを保存してください。

現在のdev workflowはテキスト推論3ノードと人物・背景Visionを同一のGemma4 31B Q4_K_Sへ揃えている。Visionはさらに対応mmprojを必要とする。これはRTX 5090級の開発環境向けで、RTX 5060の8GB VRAM向け設定ではない。各ノードのコンテキスト・サンプリング設定と検証上の注意は[workflow設定](../workflows/README.md#共通入力)を参照する。以前の8GB向け構成では[Qwen3-VL-4B](https://huggingface.co/unsloth/Qwen3-VL-4B-Instruct-GGUF)と[Qwen3 8B](https://huggingface.co/richardyoung/Qwen3-8B-Abliterated-GGUF)を使用していた。これらのハッシュは下表に比較用として残している。

ダウンロードの破損や同名の別quantを判別する場合は、`cmd.exe`で次のようにSHA-256を表示し、表の値と比較できます。

```bat
certutil -hashfile "C:\Software\ComfyUI\models\LLM\GGUF\gemma-4-31b-it-heretic-ara-GGUF\gemma-4-31b-it-heretic-ara.Q4_K_S.gguf" SHA256
```

`certutil`はハッシュ値の前後に説明行を表示します。中央の64桁の16進数を比較してください。

| ファイル | SHA-256 |
| --- | --- |
| `Qwen3-VL-4B-Instruct-Q4_K_M.gguf` | `d4dcd426bfba75752a312b266b80fec8136fbaca13c62d93b7ac41fa67f0492b` |
| `mmproj-F16.gguf` | `1b9f4e92f0fbda14d7d7b58baed86039b8a980fe503d9d6a9393f25c0028f1fc` |
| `qwen3-8b-abliterated-Q4_K_M.gguf` | `8625e48da4c4be9bcba2414fd8cad4095ff3a538d5b0111c2b26b5f6209538b9` |
| `gemma-4-31b-it-heretic-ara.Q4_K_S.gguf` | `2fa55d46083775b3b308b41b0c255f1d44466fd9f9df8308f7545b369494e858` |
| `gemma-4-31b-it-heretic-ara.mmproj-f16.gguf` | `6e3ba7c2d16bebe91812b3ce03ac819b3fc988093021f10388e5ddef141dd695` |
| `medium.pt` | `345ae4da62f9b3d59415adc60127b97c714f32e89e936602e85993674d08dcb1` |

### 動画workflowの既定H3 Hybrid Loader

配布workflowの動画生成側（`02_video_context_loop.json`、`04_video_audio_reference.json`、`06_video_lyrics.json`）は`MiniMaxH3HybridLoader`を使用します。FL2VAをベースに、Ref2VAの一部のAdaLN変調重みをオーバーレイします。これはFL2VAの画質・動きとRef2VAの参照条件付けを併用するための構成で、[Hybrid Loader作者の説明](https://github.com/scottmudge/ComfyUI_MinimaxH3HybridLoader)もこの組合せを提案しています。本workflowはユーザーが`02_video_context_loop.json`で設定した`block_range_adaln`、開始block `25`、終了block `49`、`final_adaln_from_overlay=false`をそのまま既定値とします。

モデルファイルの配布元は[Comfy-Org/MiniMax-H3](https://huggingface.co/Comfy-Org/MiniMax-H3)です。FL2VAとRef2VAの両方をダウンロードし、表の配置先へ保存してください。Turbo LoRAはHybrid Loaderの出力へ適用します。

| 用途 | workflowで選択されるファイル | ComfyUIモデルルートからの配置先 | 取得元 |
| --- | --- | --- | --- |
| FL2VA diffusion model | `minimax_h3_fl2va_pruned_int8_convrot.safetensors` | `diffusion_models\MiniMaxH3\` | [ダウンロード](https://huggingface.co/Comfy-Org/MiniMax-H3/resolve/main/diffusion_models/minimax_h3_fl2va_pruned_int8_convrot.safetensors?download=true) |
| Ref2VA overlay model | `minimax_h3_ref2va_pruned_int8_convrot.safetensors` | `diffusion_models\MiniMaxH3\` | [ダウンロード](https://huggingface.co/Comfy-Org/MiniMax-H3/resolve/main/diffusion_models/minimax_h3_ref2va_pruned_int8_convrot.safetensors?download=true) |
| Text Encoder (TE) | `qwen3vl_32b_minimax_h3_nvfp4_awq.safetensors` | `text_encoders\MiniMaxH3\` | [ダウンロード](https://huggingface.co/Comfy-Org/MiniMax-H3/resolve/main/text_encoders/qwen3vl_32b_minimax_h3_nvfp4_awq.safetensors?download=true) |
| Video VAE | `minimax_h3_video_vae_fp16.safetensors` | `vae\MiniMaxH3\` | [ダウンロード](https://huggingface.co/Comfy-Org/MiniMax-H3/resolve/main/vae/minimax_h3_video_vae_fp16.safetensors?download=true) |
| Audio VAE | `minimax_h3_audio_vae_fp32.safetensors` | `vae\MiniMaxH3\` | [ダウンロード](https://huggingface.co/Comfy-Org/MiniMax-H3/resolve/main/vae/minimax_h3_audio_vae_fp32.safetensors?download=true) |
| Turbo LoRA | `minimax_h3_ref2v_turbo_4step_v0.1_comfyui_bf16.safetensors` | `loras\MiniMaxH3\` | [ダウンロード](https://huggingface.co/Comfy-Org/MiniMax-H3/resolve/main/loras/minimax_h3_ref2v_turbo_4step_v0.1_comfyui_bf16.safetensors?download=true) |

取得後は、例えば次のように各ファイルのSHA-256を確認できます。

```bat
certutil -hashfile "C:\Software\ComfyUI\models\diffusion_models\MiniMaxH3\minimax_h3_fl2va_pruned_int8_convrot.safetensors" SHA256
```

| ファイル | SHA-256 |
| --- | --- |
| `minimax_h3_fl2va_pruned_int8_convrot.safetensors` | `e889202c41dafb67b10d67b97f0d8541508036a6090af23425a5c2615d03c47a` |
| `minimax_h3_ref2va_pruned_int8_convrot.safetensors` | `9255f52b6677845ad238f20dfaafa94727053694127ab7f255c048f0f9365779` |
| `qwen3vl_32b_minimax_h3_nvfp4_awq.safetensors` | `35a88d51044231fe332301d7a62aa81e3f2cba62febeb446e2c1e3e0ef76f2c6` |
| `minimax_h3_video_vae_fp16.safetensors` | `7c1f131492e7eddacaac9069a61b81bdd39de5cc96561e677c5eab1cdce5e522` |
| `minimax_h3_audio_vae_fp32.safetensors` | `8e505d95dd1561d47abd43d4238fd40d9bb1ae9e147ed0a4cba778d76ae4db48` |
| `minimax_h3_ref2v_turbo_4step_v0.1_comfyui_bf16.safetensors` | `5b9ab5ade15d0775676d01a907268a69a1468dc6033b3b0d3ded5502f3ebb84c` |

## 6. 起動確認

ComfyUIを再起動し、ノード検索で`MV Director`を確認します。11ノードがCore、Input、Audio、Utilitiesに表示されます。

まず[配布workflow](../workflows/README.md)のPlan/Compiler側を開き、次を確認してください。

1. Load Text FileでUTF-8 lyrics `.txt`を選べる。
2. Lyric SegmentationでWhisper `.pt`が選べる。
3. Image to Subject EMDでVision GGUF pairが選べる。
4. Enhancer、Planner、CompilerでText GGUFが選べる。
5. 実行logに各ノード名付きの`started`と`completed`が一度ずつ出る。

次に動画workflowを開き、`MiniMax H3 Hybrid Loader`が未定義ノードにならず、FL2VAが`base_model`、Ref2VAが`overlay_model`、presetが`block_range_adaln`、block範囲が`25`～`49`であることを確認してください。Hybrid Loaderの`MODEL`出力はTurbo LoRAへ接続されています。

見つからない場合は[トラブルシューティング](troubleshooting.md)を参照してください。
