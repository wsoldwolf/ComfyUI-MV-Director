# 導入マニュアル

Windows版ComfyUIへComfyUI-MV-Directorを導入し、Text/Vision GGUFとOpenAI Whisperをローカル実行する手順です。基準環境はPython 3.13、CUDA 13.0、`llama-cpp-python 0.3.34`です。

## 1. 前提

- ComfyUI v0.36.0 commit `ee71d5c4993f29086b27fde1629a945ae48425bf`
- ComfyUI-MiniMaxH3-Contex-Loop 0.6.9 commit `9860a063784c8c23b58e00107f2180e0df3c43d9`
- NVIDIA Driver、CUDA Toolkit 13.0
- Visual Studio 2022のDesktop development with C++とWindows SDK
- Git

異なるComfyUI / Context Loop commitでも動作する可能性はありますが、互換試験の基準外です。

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

```powershell
Set-Location C:\Software\ComfyUI\custom_nodes
git clone https://github.com/wsoldwolf/ComfyUI-MV-Director.git
```

開発checkoutを別ドライブへ置く場合は、管理者権限のコマンドプロンプトでdirectory junctionを作れます。

```bat
mklink /J "C:\Software\ComfyUI\custom_nodes\ComfyUI-MV-Director" "E:\ComfyUI\projects\ComfyUI-MV-Director"
```

既存の実ディレクトリやjunctionを上書きしないでください。

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
| 人物・背景の画像認識 / Image to Subject EMD | `Qwen3-VL-4B-Instruct/Qwen3-VL-4B-Instruct-Q4_K_M.gguf`と`mmproj-F16.gguf` | [Unsloth配布ページ](https://huggingface.co/unsloth/Qwen3-VL-4B-Instruct-GGUF)、[本体GGUFを取得](https://huggingface.co/unsloth/Qwen3-VL-4B-Instruct-GGUF/resolve/main/Qwen3-VL-4B-Instruct-Q4_K_M.gguf?download=true)、[mmprojを取得](https://huggingface.co/unsloth/Qwen3-VL-4B-Instruct-GGUF/resolve/main/mmproj-F16.gguf?download=true) |
| Direction生成・Timeline計画・EMD英訳 / Direction Enhancer、Timeline Planner、EMD Compiler (Ref2VA) | `Qwen3-8B-Abliterated/qwen3-8b-abliterated-Q4_K_M.gguf` | [richardyoung配布ページ](https://huggingface.co/richardyoung/Qwen3-8B-Abliterated-GGUF)、[GGUFを取得](https://huggingface.co/richardyoung/Qwen3-8B-Abliterated-GGUF/resolve/main/qwen3-8b-abliterated-Q4_K_M.gguf?download=true) |
| 歌詞と音声の同期 / Lyric Segmentation | `medium.pt` | [OpenAI Whisper公式リポジトリ](https://github.com/openai/whisper)、[medium.ptを取得](https://openaipublic.azureedge.net/main/whisper/models/345ae4da62f9b3d59415adc60127b97c714f32e89e936602e85993674d08dcb1/medium.pt) |

次の配置にすると、workflowに保存された選択値を変更せず使用できます。

```text
C:\Software\ComfyUI\models\
├─ LLM\GGUF\
│  ├─ Qwen3-VL-4B-Instruct\
│  │  ├─ Qwen3-VL-4B-Instruct-Q4_K_M.gguf
│  │  └─ mmproj-F16.gguf
│  └─ Qwen3-8B-Abliterated\
│     └─ qwen3-8b-abliterated-Q4_K_M.gguf
└─ whisper\
   └─ medium.pt
```

配置先のサブディレクトリ名を変更した場合は、ComfyUI再起動後に各ノードのcomboで実ファイルを選び直し、workflowを保存してください。

ダウンロードの破損や同名の別quantを判別する場合は、PowerShellの`Get-FileHash -Algorithm SHA256 <ファイル>`で次の値と比較できます。

| ファイル | SHA-256 |
| --- | --- |
| `Qwen3-VL-4B-Instruct-Q4_K_M.gguf` | `d4dcd426bfba75752a312b266b80fec8136fbaca13c62d93b7ac41fa67f0492b` |
| `mmproj-F16.gguf` | `1b9f4e92f0fbda14d7d7b58baed86039b8a980fe503d9d6a9393f25c0028f1fc` |
| `qwen3-8b-abliterated-Q4_K_M.gguf` | `8625e48da4c4be9bcba2414fd8cad4095ff3a538d5b0111c2b26b5f6209538b9` |
| `medium.pt` | `345ae4da62f9b3d59415adc60127b97c714f32e89e936602e85993674d08dcb1` |

## 6. 起動確認

ComfyUIを再起動し、ノード検索で`MV Director`を確認します。11ノードがCore、Input、Audio、Utilitiesに表示されます。

まず[配布workflow](../workflows/README.md)のPlan/Compiler側を開き、次を確認してください。

1. Load Text FileでUTF-8 lyrics `.txt`を選べる。
2. Lyric SegmentationでWhisper `.pt`が選べる。
3. Image to Subject EMDでVision GGUF pairが選べる。
4. Enhancer、Planner、CompilerでText GGUFが選べる。
5. 実行logに各ノード名付きの`started`と`completed`が一度ずつ出る。

見つからない場合は[トラブルシューティング](troubleshooting.md)を参照してください。
