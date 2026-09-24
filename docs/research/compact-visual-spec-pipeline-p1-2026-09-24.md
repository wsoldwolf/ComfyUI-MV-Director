# Scene概要とActionの短文化 P1（2026-09-24）

## 判定

**一律の短文化は採用しない。** 御神木では元の基準版が最良だった。一方、狐火ではScene概要だけを短くした版が最良だった。短い文がH3に常に有利なのではなく、対象の置き方、人物との因果関係、発生源など、削った情報の種類が効いている。P0で実装したCameraの`compact`は引き続きopt-inとし、付属profileの既定は`detailed`のままにする。

## 比較条件と出典

保存済みAudio参照Plan `C:\Software\ComfyUI\output\mv_director\audio_reference_plan_00001.txt`（SHA-256 `3dce5133ab8f42aa12e2762439793fb4ed08863c99ce48689f8d3eeb1035eda9`）を基準に、[研究専用ビルダー](../assets/research/audio-reference-body-isolation-2026-09-24/build_p1_scene_prose_variants.py)でScene 6と9だけを変えた。比較文は[先行する手書き短縮実験](audio-reference-compact-tree-fire-stability-2026-09-24.md)の英文であり、**実8Bの生成文ではない**。

| 版 | 変更箇所 | Plan SHA-256 |
| --- | --- | --- |
| 基準版 | なし | `3dce5133ab8f42aa12e2762439793fb4ed08863c99ce48689f8d3eeb1035eda9` |
| [概要のみ短縮](../assets/research/audio-reference-body-isolation-2026-09-24/p1-summary-only-scene6-9-plan.json) | Scene 6・9の`[reference generation]`各1行 | `102bebcd53ac8ba4c31216f4135492025bdfd642c2c289549bbe74c03bfa0e35` |
| [概要＋Action短縮](../assets/research/audio-reference-body-isolation-2026-09-24/p1-summary-action-scene6-9-plan.json) | 上記と、Scene 6のShot 1、Scene 9のShot 1・2のAction部分 | `13c83f60e03758e16180b419163f06d826c0c1032a58bb84c7fd7e4254e65e35` |

後者でもCameraの英文は基準版とバイト単位で一致する。Scene 6の概要は343→180文字、Scene 9は169→138文字。Actionを含むShot行はScene 6が1000→807文字、Scene 9の2行が549→502、805→719文字となった。ほかのScene、seed、参照、音声、Plan metadataは保持した。いずれも前Scene Guideを共通にしたH3の短区間比較であり、前Sceneの243フレームは基準版とのSSIMが1.000だった。SSIMは入力条件の一致確認であり、作品の得点ではない。

## ユーザーによる連続視聴判定

| 対象 | 基準版 | 概要のみ短縮 | 概要＋Action短縮 | 判定 |
| --- | --- | --- | --- | --- |
| 御神木 Scene 6 | [動画](<C:/Software/ComfyUI/output/h3_chains/audio_ref_tree_s5_6_base_20260924/segments/clip_0002.4293b91780604c14809ff17a72b36edc.mp4>) | [動画](<C:/Software/ComfyUI/output/h3_chains/audio_ref_tree_s5_6_summary_only_p1_20260924/segments/clip_0002.e53cc4c4c5a8456c8afa469c1586e386.mp4>) | [動画](<C:/Software/ComfyUI/output/h3_chains/audio_ref_tree_s5_6_summary_action_p1_20260924/segments/clip_0002.bdf525571c6b420b9c2345561faca9a1.mp4>) | **基準版が最良**。御神木が中央に立ち柵に囲まれ、人物が腕を広げると葉が舞う。概要のみ版は木が参道の端でメッセージが弱く、概要＋Action版はCameraが複雑でも木の位置が良くない。ただし3本とも成立する水準。 |
| 狐火 Scene 9 | [動画](<C:/Software/ComfyUI/output/h3_chains/audio_ref_fire_s8_9_base_20260924/segments/clip_0002.94563a301a484b0a91c72e30509f9686.mp4>) | [動画](<C:/Software/ComfyUI/output/h3_chains/audio_ref_fire_s8_9_summary_only_p1_20260924/segments/clip_0002.9a646a5bee194117bce7980d9c4793bd.mp4>) | [動画](<C:/Software/ComfyUI/output/h3_chains/audio_ref_fire_s8_9_summary_action_p1_20260924/segments/clip_0002.5c7db6b92ed1406f8b31d1cc02dd6f96.mp4>) | **概要のみ短縮が最良**。3本ともeffectは良い。基準版には歌詞と脈絡のない手の仕草があり、概要＋Action版は狐火が地面から発生して違和感がある。 |

一回ずつのH3生成なので、変更文と結果の因果を統計的に確定していない。特に概要＋Actionを短くすると狐火の発生源が変わったが、「短いActionは常に地面から出す」と一般化できない。Camera-only P0と今回P1も、手書きの**全体短縮版**で得た良さを一様には再現しなかった。

## 実8Bによる小さな追加検査

[8B検査スクリプト](../assets/research/audio-reference-body-isolation-2026-09-24/probe_p1_real_8b.py)で、保存済み[EMD](<C:/Software/ComfyUI/output/mv_director/audio_reference_emd_00001.md>)のScene 6・9の歌詞と元Actionを渡し、各Sceneをseed 1・2で短い日本語Scene/Action文へ再要約させた。[生出力と入力](../assets/research/audio-reference-body-isolation-2026-09-24/p1-real-8b-probe.json)を保存した。これはQwen3-8B-Abliterated Q4_K_Mの**実推論**だが、上表のH3用Planとは別であり、英訳・Compiler・H3へはまだ投入していない。また入力に元の8B製Actionを含むため、新規の演出発案能力を試したものではない。

4回とも必要な`SCENE`/`ACTION`内容レコードは揃った一方、空の`<think>`タグが先行して厳密な行プロトコルは4/4で不合格だった。この検証を受け、llama.cppの共通応答境界で**先頭にある閉じたthinkブロックだけ**を除去するようにした。[同じseedの再試験](../assets/research/audio-reference-body-isolation-2026-09-24/p1-real-8b-probe-normalized.json)では4/4で行プロトコルが合格し、4件の`SCENE`/`ACTION`本文レコードは修正前と一致した。閉じていないタグや本文途中のタグは残し、別の規約違反を隠さない。除去件数はINFOログに記録する。

内容は概ね歌詞対象を保持するが、御神木では「葉を指す」「目を閉じる」と「木が葉を揺らす」の列挙に寄り、ユーザーが評価した**正面で腕を広げた瞬間に葉が舞う**演技の同期を自発的に作っていない。狐火では旋回と両手を残すが、発生源は固定できない。したがって「8Bにも短文化は可能」と「手書き短縮版と同水準の映像設計を生成できる」は別の主張であり、後者は未証明である。

## 次段の判断

生産系へ短縮を昇格させない。もし進めるなら、作者EMDのScene記述があるときはそれを優先し、無いSceneについてのみ、既存のScene Event・Action・有限Cameraから**場所、可視変化、人物の反応の順序**を一度で示す契約を小範囲で検証する。追加LLM段の費用と行プロトコル問題を測る。御神木の中央配置・柵、狐火の発生源は曖昧に削れない映像情報として評価項目にする。全曲の文章を機械的に短くする、H3結果の点数だけで自動選択する、という実装はこの証拠からは支持できない。
