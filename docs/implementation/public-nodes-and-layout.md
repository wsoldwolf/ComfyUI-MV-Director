# 公開ノード一覧と配置

作成日: 2026-09-15<br>
状態: 初期実装で登録する公開surfaceを固定する。

## 1. 公開ノード

初期実装で登録するnode typeは次の11個だけとする。

| 区分 | node type | 表示名 | 配置 | 責務 |
|---|---|---|---|---|
| Core | `MVDirectorImageToSubjectEMD` | `MV Director - Image to Subject EMD` | `nodes/node_image_to_subject_emd/` | IMAGEを観察し、`# サブジェクト` EMD、Picture binding、同一IMAGE pass-throughを返す |
| Core | `MVDirectorDirectionEnhancer` | `MV Director - Direction Enhancer` | `nodes/node_direction_enhancer/` | user、観察、演出profileを短い全体方針へ統合する |
| Core | `MVDirectorTimelinePlanner` | `MV Director - Timeline Planner` | `nodes/node_timeline_planner/` | 確定済みScene/Shot枠へ演出とlip-sync directiveを展開する |
| Core | `MVDirectorEMDCompiler` | `MV Director - EMD Compiler (Ref2VA)` | `nodes/node_emd_compiler/` | 完全EMDをRef2VA六セクションとContext Loop Plan JSONへ変換する |
| Input | `MVDirectorLyricSegmentation` | `MV Director - Lyric Segmentation` | `nodes/node_lyric_segmentation/` | Whisper/VAD、SRT、Template EMD、H3互換length付きtimelineを返す |
| Audio | `MVDirectorAudioPadPair` | `MV Director - Audio Pad Pair (PCM Silence)` | `nodes/node_audio_pad_pair/` | full mixとvocal stemの短い側だけを共通尺へ末尾paddingする |
| Utilities | `MVDirectorH3TimingProfile` | `MV Director - H3 Timing Profile` | `nodes/node_h3_timing_profile/` | Context Loop timing contractをLyric SegmentationとCompilerへ共有する |
| Utilities | `MVDirectorSeed32` | `MV Director - 32-bit Seed` | `nodes/node_seed32/` | GGUFとH3へ同じ再現可能な正の32-bit seedを供給する |
| Utilities | `MVDirectorStringCombo` | `MV Director - String Combo` | `nodes/node_string_combo/` | 利用者定義の有限な文字列候補を選びSTRINGとして出力する |
| Utilities | `MVDirectorConnectedCombo` | `MV Director - Connected Combo` | `nodes/node_connected_combo/` | サブグラフ内部の頻繁に変更するcomboを外側へ引き出す |
| Utilities | `MVDirectorLoadTextFile` | `MV Director - Load Text File` | `nodes/node_load_text_file/` | ローカル歌詞等をブラウザで選択/D&Dし、埋め込みUTF-8本文をSTRINGとして返す |

旧`CL...` type ID、表示名又は互換aliasは登録しない。

### 1.1 Combo utilityの保持範囲

String Comboは`string_list`と`selected_value`をworkflowへ保存し、`|`を項目区切り、`||`をliteral pipeとして扱う。保存済み選択が現在の候補にない場合は黙って先頭へ戻さずvalidation errorにする。

Connected Comboは出力linkの接続先にあるSTRING COMBO metadataをfrontendで取得し、候補列を`enum_values_json`としてworkflow/API promptへ保存する。これによりサブグラフ内部の頻繁に変えるcomboを外側へ引き出せる。Python側は保存された候補と`selected_value`の一致だけを検証し、任意文字列を候補へ追加しない。

### 1.2 32-bit Seedの保持範囲

32-bit Seedは旧実装どおり`1..2147483647`を出力し、`seed=-1`、`fixed`、`random`及びrandomボタン直後の一回保持を扱う。単なる64-bit剰余変換にはせず、GGUFとH3へ同じ有効seedを分岐するworkflow-persistent sourceとする。

### 1.3 Load Text Fileの保持範囲

Load Text Fileはブラウザのファイル選択とD&D、UTF-8/UTF-8 BOM復号、LF改行正規化、16 MiB上限、workflowへのBase64埋込及び内容ベースのcache invalidationを再利用する。`.lrc`を選択候補へ加える。backendから任意pathを開く機能、文字コード推測、元ファイル監視、複数ファイル結合、本文編集又はpreviewは追加しない。ファイル本文がworkflow JSONへ保存されることをUIへ明示する。

## 2. 初期実装で登録しないノード

| 旧又は候補ノード | 判断 | 代替 |
|---|---|---|
| Prompt Merger | 登録しない | Direction Enhancerがauthority付き統合を担当 |
| Scene Limiter | 登録しない | Planner内部の有限batchと対象Scene cacheで扱う |
| 単体Audio Pad | 登録しない | Audio Pad Pairだけを使う |
| Prompt Translator | 登録しない | EMD Compiler内部adapter |
| EMD Validator | 登録しない | Compiler parserの最小文法エラー |
| Picture Slot Resolver | 登録しない | Image to Subject EMDの`auto_h3` |
| GGUF Model Loader | 登録しない | 各利用nodeと共通inference backend |
| Model Unloader / VRAM Cleanup | 登録しない | `keep_model_loaded=false`とbackend lifecycle |
| SRT Saver / JSON Viewer | 登録しない | STRING出力を既存汎用nodeへ接続 |
| T2VA/I2VA mode switch | 登録しない | 必要時に別Compilerとして設計 |

## 3. repository配置

Pythonの公開node packageをrepository rootへ散在させない。root `__init__.py`は`nodes`からmappingを集約するだけにし、node固有コードは必ず`nodes/node_*/`へ置く。

```text
ComfyUI-MV-Director/
├─ __init__.py
├─ nodes/
│  ├─ __init__.py
│  ├─ node_image_to_subject_emd/
│  │  ├─ __init__.py
│  │  ├─ node.py
│  │  ├─ graph_binding.py
│  │  └─ schema.py
│  ├─ node_direction_enhancer/
│  ├─ node_timeline_planner/
│  ├─ node_emd_compiler/
│  ├─ node_lyric_segmentation/
│  ├─ node_audio_pad_pair/
│  ├─ node_h3_timing_profile/
│  ├─ node_seed32/
│  ├─ node_string_combo/
│  ├─ node_connected_combo/
│  └─ node_load_text_file/
├─ core/
│  ├─ artifacts/
│  ├─ audio/
│  ├─ emd/
│  ├─ h3_contract/
│  ├─ inference/
│  └─ timing/
├─ prompts/
├─ profiles/
├─ web/
│  └─ js/
├─ tests/
└─ docs/
```

ComfyUI frontend拡張が必要な32-bit Seed、String Combo、Connected Combo及びLoad Text FileのJavaScriptは`web/js/`へ置く。Python node packageを`web/`又はrepository rootへ追加しない。

## 4. Picture自動取得

`MVDirectorImageToSubjectEMD`の`picture_reference_mode=auto_h3`はhidden `PROMPT`と`UNIQUE_ID`から、自身のIMAGE出力に直接接続されたH3 Ref2VA画像入力を探す。基準contractでは`ref_image_0..8`及びnested `ref_images.ref_image_0..8`を`<Picture 1..9>`へ写す。

- 同じPicture番号への複数分岐は許可する。
- 異なるPicture番号へ分岐した場合は曖昧エラーにする。
- H3接続がなければ観察は成功させ、bindingを`unbound`にする。
- `manual`は明示`picture_index`を使い、`none`はPicture関連を出さない。
- 解決したnode ID、class type、input名、Picture番号をbinding fingerprintと`IS_CHANGED`へ含める。
- H3 class type一覧は`core/h3_contract/`のversioned adapterが所有する。

Compilerはworkflow graphを探索しない。Image to Subject EMDがEMDへ書いた`<Subject N>`と`<Picture N>`の関係だけを処理する。
