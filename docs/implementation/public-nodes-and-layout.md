# 公開ノード一覧と配置

作成日: 2026-09-15<br>
状態: 初期実装で登録する公開surfaceを固定する。

## 1. 公開ノード

初期実装で登録するnode typeは次の11個だけとする。

| 区分 | node type | 表示名 | 配置 | 責務 |
|---|---|---|---|---|
| Core | `MVDirectorImageToSubjectEMD` | `MV Director - Image to Subject EMD` | `nodes/node_image_to_subject_emd/` | IMAGEを観察し、`# サブジェクト` EMD、Picture binding、同一IMAGE pass-throughと読み取り専用Picture表示を返す |
| Core | `MVDirectorDirectionEnhancer` | `MV Director - Direction Enhancer` | `nodes/node_direction_enhancer/` | 空でもよいuser・概念EMDと演出profileを短いStyle／Motion／Camera／Other方針へ統合し、利用者記述なしでも動作する |
| Core | `MVDirectorTimelinePlanner` | `MV Director - Timeline Planner` | `nodes/node_timeline_planner/` | 確定済みScene/Shot枠へ演出とlip-sync directiveを展開する |
| Core | `MVDirectorEMDCompiler` | `MV Director - EMD Compiler (Ref2VA)` | `nodes/node_emd_compiler/` | 完全EMDをRef2VA六セクションとContext Loop Plan JSONへ変換する |
| Input | `MVDirectorLyricSegmentation` | `MV Director - Lyric Segmentation` | `nodes/node_lyric_segmentation/` | Whisper/VAD、SRT、Template EMD、H3互換length付きtimelineを返す |
| Audio | `MVDirectorAudioPadPair` | `MV Director - Audio Pad Pair (PCM Silence)` | `nodes/node_audio_pad_pair/` | full mixとvocal stemの短い側だけを共通尺へ末尾paddingする |
| Utilities | `MVDirectorH3TimingProfile` | `MV Director - H3 Timing Profile` | `nodes/node_h3_timing_profile/` | Context Loop timing contractをLyric SegmentationとCompilerへ共有する |
| Utilities | `MVDirectorSeed32` | `MV Director - 32-bit Seed` | `nodes/node_seed32/` | GGUFとH3へ同じ再現可能な正の32-bit seedを供給する |
| Utilities | `MVDirectorStringCombo` | `MV Director - String Combo` | `nodes/node_string_combo/` | 利用者定義の有限な文字列候補を選びSTRINGとして出力する |
| Utilities | `MVDirectorConnectedCombo` | `MV Director - Connected Combo` | `nodes/node_connected_combo/` | サブグラフ内部の頻繁に変更するcomboを外側へ引き出す |
| Utilities | `MVDirectorLoadTextFile` | `MV Director - Load Text File` | `nodes/node_load_text_file/` | plain lyrics `.txt`をブラウザで選択/D&Dし、埋め込みUTF-8本文をSTRINGとして返す |

旧`CL...` type ID、表示名又は互換aliasは登録しない。

### 1.1 Combo utilityの保持範囲

String Comboは`string_list`と`selected_value`をworkflowへ保存し、`|`を項目区切り、`||`をliteral pipeとして扱う。保存済み選択が現在の候補にない場合は黙って先頭へ戻さずvalidation errorにする。

Connected Comboは出力linkの接続先にあるSTRING COMBO metadataをfrontendで取得し、候補列を`enum_values_json`としてworkflow/API promptへ保存する。これによりサブグラフ内部の頻繁に変えるcomboを外側へ引き出せる。Python側は保存された候補と`selected_value`の一致だけを検証し、任意文字列を候補へ追加しない。

### 1.2 32-bit Seedの保持範囲

32-bit Seedは旧実装どおり`1..2147483647`を出力し、`seed=-1`、`fixed`、`random`及びrandomボタン直後の一回保持を扱う。単なる64-bit剰余変換にはせず、GGUFとH3へ同じ有効seedを分岐するworkflow-persistent sourceとする。

### 1.3 Load Text Fileの保持範囲

Load Text Fileはブラウザの`.txt`ファイル選択とD&D、UTF-8/UTF-8 BOM復号、LF改行正規化、16 MiB上限、workflowへのBase64埋込及び内容ベースのcache invalidationを再利用する。LRC、SRT、VTT又は他形式を選択候補へ加えない。backendから任意pathを開く機能、文字コード推測、元ファイル監視、複数ファイル結合、本文編集又はpreviewは追加しない。ファイル本文がworkflow JSONへ保存されることをUIへ明示する。

### 1.4 Timeline Plannerのリップシンク操作

`MVDirectorTimelinePlanner`は外部接続可能なSTRING COMBO `lip_sync_mode`を持ち、表示候補と保存値を次に固定する。

| 表示 | 保存値 |
|---|---|
| 使用しない | `off` |
| Context Loop | `context_loop` |
| Audio参照 | `audio_reference` |
| 歌詞 | `lyrics` |

既定は`lyrics`とする。あわせてSTRING `lip_sync_target`、INT `lip_sync_audio_slot`（1～3）を外部接続可能にする。`lip_sync_audio_slot`は`audio_reference`の時だけ意味を持つが、widgetを動的に消さず保存値を維持する。Connected Comboから`lip_sync_mode`をサブグラフ外へ引き出せるよう、通常のComfyUI STRING COMBO metadataを公開する。完成動画の音声選択は下流の動画生成WFにあるChain Policyの責務なので、Plannerに`lock_source_audio`は設けない。

歌詞annotationは全modeで出力EMDへ保持し、人物動作の入力にも使う。comboは口形directiveのmaterializeだけを切り替え、mode変更だけでLLM人物動作・カメラtaskを再実行しない。

### 1.5 Timeline Plannerの全socket

Plannerの入力は表示順に、必須`template_emd`、任意`concept_emd`、任意`MV_DIRECTOR_DIRECTION`、lip-sync三項目、GGUF model選択とoverride、`chat_format`、`max_tokens`、`temperature`、`top_p`、`repetition_penalty`、`gpu_layers`、`n_batch`、`n_ctx`、`flash_attn`、`kv_cache_type`、`op_offload`、`keep_model_loaded`、`seed`、`scenes_per_batch`、`cache_mode`、任意`save_debug_output`とする。型、範囲、既定値の正本は最小コア仕様7.4の表を使う。

旧Plannerにあったllama.cpp調整値は維持する。旧camera/vocal guard、visual enrichment profile、semantic guard及び可変retry回数は新Plannerへ持ち込まない。出力は編集可能な`emd_text`、内部typed `emd`、`status`の順とする。

Direction artifactは新しい公開node又はユーザー記述形式ではなく、EnhancerからPlannerへ四方向と最小provenanceを曖昧なく渡すcustom socket値である。Enhancerは同内容の`direction_emd_preview`も返すが、Plannerはpreviewを再parseしない。artifactが未接続でも動作する。

### 1.6 EMD Compilerのsocket

`MVDirectorEMDCompiler`は必須`emd_text`、`translation_mode`、GGUF `model_name`、`chat_format`、`steps`、`max_tokens`、`temperature`、`top_p`、`repetition_penalty`、`gpu_layers`、`n_batch`、`n_ctx`、`flash_attn`、`kv_cache_type`、`op_offload`、`keep_model_loaded`、`seed`と、任意`MV_DIRECTOR_H3_TIMING_PROFILE`を受ける。`translation_mode`は`ja_to_en`を既定とし、`already_english`ではmodel選択値が空又はstaleでもGGUFをresolve又はloadしない。Compiler独自のcache、repair、retry、意味監査又はgraph inspectionは設けない。

出力は`plan_json: STRING`、`required_references: MV_DIRECTOR_REQUIRED_REFERENCES`、`status: STRING`の順とする。文法不正は行番号を持つ`EMDParseError`として停止し、空Plan又は補正文を返さない。日本語翻訳応答は`TRANSLATION<TAB>SLOT<TAB>TEXT`だけを受理し、contextに収まる最大の連続unit群へ有限分割する。欠落、重複、未知行又は破損行はretryせず停止する。

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

ノード内の`resolved_picture_reference`は読み取り専用の一行表示とし、成功時は`<Picture N>`、未接続時は`unbound`、異番号への複数分岐時は`ambiguous`を示す。編集可能widget又は出力socketにはせず、backendのgraph解決結果を次回実行後に表示する。

初期adapterは通常Ref2VAへの固定番号直接接続だけを対象とする。画像は`ref_images.ref_image_N`、音声は`ref_audios.ref_audio_N`へ接続し、Tagged Referenceの`@tag`再番号付けは扱わない。

Compilerはworkflow graphを探索しない。Image to Subject EMD又は人間がEMDへ書いた`<Subject N>`と任意の`<Picture N>`関係だけを処理する。Picture関連がなくてもH3内蔵概念としてコンパイルする。
