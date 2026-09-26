# Timeline Planner

確定済みTemplate EMDから、Sceneの出来事、人物演技、撮影を順に生成し、完成EMDを返します。現行devはGemma4 31Bを既定とし、Scene Authorだけを使います。旧8B向けPlanner／監査経路はありません。

## 処理と作者所有

1. Eventが出来事・対象・外部effectを計画します。
2. PerformanceがEventと現在歌詞に対応する身体・表情の演技を計画します。
3. CameraがEventと演技を読んで撮影を計画します。

各要求はScene内の対象Shotをまとめて扱います。元TemplateのScene/Shot時刻と継続指定を保持し、歌詞sectionを読み取り文脈として渡します。歌詞区間全体を現在Sceneへ描写する義務は作りません。

Shotへ直接書いた`演出`、`演技`、`カメラ`は固定し、そのfieldの生成を省略します。ラベルなし作者本文も保持します。完成`# サブジェクト`から始まる全文EMDは検証後に生成を省略できます。Compilerへの直接接続も可能です。

`END_STATE`は本文から分離した輸送metadataです。継続Sceneへだけ引き継ぎ、CUTでは引き継ぎません。映像上の完全な接続を保証する機能ではありません。

## 接続

| 入力 | 内容 |
|---|---|
| template_emd | Lyric Segmentationの時間枠と歌詞、又は作者EMD |
| concept_emd | 人物Visionのemd_fragment |
| scene_emd | 背景Visionのemd_fragment |
| direction | Enhancerのtyped Direction。preview本文は接続しない |
| model_name_override | モデル選択を文字列で上書きする任意socket |

出力は`emd_text`、typed `emd`、`status`です。背景IMAGEをPlannerへ直接渡しません。同じ背景画像は動画WFのPicture 2へ渡します。

## 演出候補と補完

Enhancerの`user_request`に`# 演出候補`を記述します。最大12件、各500文字。候補は現在Sceneの計画に渡す着想で、H3の全Scene共通prefixへ複製しません。

`staging_candidate_policy`は次の二種類です。

- `optional`: 任意の着想として扱う。
- `prefer_matched`: 現在歌詞に適合する候補を優先して検討する。強制採用ではない。

`# モーション補完`は候補とは別の明示合成です。リスト省略はprofileを継承、空リストは無効、非空リストは全候補置換となります。単一人物、作者演技／一般本文なし、Camera未固定、4秒以上等の適格条件を満たすShotだけを対象にします。

`pre_author`では予定補完を演技生成前に示し、Cameraへ合成済み演技を渡します。`post_author`では三段生成後に合成します。`guarded_no_drop`は生成結果を見て既存候補をLLMが再選択します。不正選択は一度再試行し、回復不能なら元の候補を保持します。作者確定演技・Cameraを変更する監査ではありません。

補完の適用理由・出所と選択番号はINFO／debugへ残ります。LLMの演技原文は書き換えず、完成EMDでは別行として合成します。

## runtimeと再実行

配布WFはGemma4 31B Q4_K_S、chat_format=auto、n_ctx=24576、max_tokens=4096、temperature=0.2、top_p=0.9、repetition_penalty=1.05、n_batch=256、flash_attn=true、KV=q8_0です。UIにはモデル、出力長、sampling、GPU層、context、保持、seed、cache等の調整値を残します。型・範囲はnodeのINPUT_TYPESが正本です。

`scenes_per_batch`はScene Authorでは使われないため削除しました。旧WFはジェネレーターの`--sync-planner-schema`で更新します。配線済みの旧widgetは黙って消さず、手動移行を要求します。

cache_modeはreuse / refresh / disabled。生成条件を変えないlip-sync mode切替は生成済み演技・Cameraを再利用し、描画directiveを更新します。旧Planner cacheは使用しません。

lip_sync_modeはoff / context_loop / audio_reference / lyrics。対象と音声slotは`lip_sync_target`、`lip_sync_audio_slot`で指定します。標準lip-syncの実音声配線は対応Video WFで設定します。

## エラーと進捗

必須slotの欠落は局所再要求と一件隔離要求で有限回復します。回復不能なら不完全EMDをCompilerへ流しません。grammarは型・slot・行構造を拘束し、自然文の意味を決めません。

contextは実効値と出力予約・安全余白から事前検査します。履歴を縮小し、必要なら同じSceneのslotを分割します。必須の固定指示・現在slot内容を削除して成功扱いにはしません。

進捗は必要なEvent / Performance / Camera / 補完再選択の主呼出し数とモデル準備を基準にします。retry、cache、モデルload時間により実時間との比例は保証しません。`save_debug_output=true`ではtask、要求payload、応答等を保存します。

[EMD仕様](../spec/emd-spec.md)／[処理フロー](../architecture/direction-planner-flow.md)／[profile仕様](../../profiles/README.md)
