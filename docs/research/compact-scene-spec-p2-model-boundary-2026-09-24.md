# 簡潔Scene仕様 P2：8Bの能力と情報受け渡しの境界

2026-09-24。P1のH3比較では手書きの短いScene概要が狐火に有利だったが、御神木では基準版が最良だった。本試験は「短い文を8Bが新規に作れるか」と「Eventを渡せば人物・Cameraも連携するか」を分ける。**本番Planner、EMD、Compiler、H3の入力は変更しない。動画も生成しない。**

## 条件

[研究スクリプト](../assets/research/audio-reference-body-isolation-2026-09-24/probe_p2_scene_spec.py)へ保存済みAudio参照EMDのScene 6・9を渡す。入力はScene番号、時刻、継続、背景Vision由来の環境・照明、Shot境界、原歌詞だけであり、**生成済みAction・Camera・Planの文は渡さない**。出力は`SCENE|...`とShotごとの`SHOT|番号|...`。本番のline protocolやCamera有限値の代替実装ではなく、研究用の短文契約である。

Qwen3-8B-Abliterated Q4_K_M、`n_ctx=8192`、temperature 0.2、seed 1・2。追加で同系列のQwen3-14B-Abliterated Q4_K_Mをseed 1で比較した。14Bは別モデルであり、パラメータ数だけを独立変数としていない。`/no_think`と共通llama.cpp応答の先頭thinkブロック除去を使用した。生成後の日本語文の修復はしていない。

| 条件 | 入力差 | 生出力 |
| --- | --- | --- |
| 8B・neutral / linked | 同じ歌詞・背景。後者のみScene内の時間的連携を指示 | [8件](../assets/research/audio-reference-body-isolation-2026-09-24/p2-scene-spec-no-action-seed1-2.json) |
| 8B・lyric_priority | 同じ入力で、歌詞の具体対象を背景より先に選ぶ指示 | [4件](../assets/research/audio-reference-body-isolation-2026-09-24/p2-scene-spec-lyric-priority-seed1-2.json) |
| 8B・linked Eventなし／あり | **同じsystem promptとseed**。あり版だけ、元EMDから人物姿勢とCameraを含めず手で抽出した[対象の変化](../assets/research/audio-reference-body-isolation-2026-09-24/p2-event-only-fixture.json)を渡す。これは保存済み構造化Event応答ではない | [なし4件](../assets/research/audio-reference-body-isolation-2026-09-24/p2-linked-no-event-seed1-2.json)、[あり4件](../assets/research/audio-reference-body-isolation-2026-09-24/p2-linked-event-only-seed1-2.json) |
| 14B・linked Eventなし／あり | 8Bと同じsystem prompt・payload・seed 1 | [なし2件](../assets/research/audio-reference-body-isolation-2026-09-24/p2-14b-linked-no-event-seed1.json)、[あり2件](../assets/research/audio-reference-body-isolation-2026-09-24/p2-14b-linked-event-only-seed1.json) |

27Bの[試行2件](../assets/research/audio-reference-body-isolation-2026-09-24/p2-27b-linked-no-event-seed1.json)は、Qwen3.8-27B-heretic-ara Q5_K_Mが回答前の自己指示文を出して`max_tokens=512`を消費し、どちらも行プロトコルに合格しなかった。異なるモデル系列・chat templateでもあり、**品質比較から除外**する。

## 観察

- 8BのEventなし12件（neutral、linked、lyric_priority）はすべて行形式を守ったが、内容は背景の鳥居・石灯籠・参道、歩行、紅葉の揺れへ流れやすい。御神木や狐火の語が現れても、可視変化と身体反応とCameraの時間的連携はほぼ書けない。`lyric_priority`の一文を加えるだけでは改善しなかった。
- 8BへEventだけ渡すと、Scene 6の御神木の葉とScene 9の狐火の旋回は各seedで保持された。しかし御神木では人物の反応がShotから消え、Cameraは鳥居・神社奥へ向かうなど対象を外した。狐火では人物は光を静かに見つめる／微笑む程度で、手・体幹を使った振付にはならない。**対象選択の回復は身体演技の回復ではない。**
- 14BのEventなしでは、Scene 6の手を胸元に当てて真剣に問う表情と低角度の追従、Scene 9の手・表情・Camera coverageが8Bより具体的だった。しかしEventありでは御神木に対して祈る表情、狐火に対して歌うだけとなり、対象の変化と身体動作の相互作用は弱い。大きいモデルだけでEvent→演技の欠落が消えるとは言えない。
- 元のP1「実8Bの再要約」は既存Actionを入力していたため、このP2より良い短文が出ても矛盾しない。既存Actionが持っていた身体動作とCameraが、P2では与えられていない。

## 判定と次段

8Bの容量・推論能力は**一因の可能性がある**。ただしこの小標本は固有の限界を証明しない。より強い観察は、**Eventの対象と現象だけでは、身体演技とCamera coverageが自然には復元されない**ことにある。背景資料が大量にある場合、歌詞の終盤にある具体語より目立つ背景物・歩行が主題を奪う。これは8Bでも14Bでも程度差を伴って起きる。

次は新しい全曲LLM段を足す前に、既存Scene Eventと人物の身体演技を別々の短い構造要素として持ち、同じSceneの時間軸とShot位置で再結合できるかを、御神木・狐火の2 Sceneだけで試す。作者の`演出`・`演技`があれば最優先する。Eventだけから自由文のActionを再生成するのではなく、すでにPlannerが持つ身体状態・表情・手の経路とCameraの対象coverageを失わずにH3向け一文へ渡す方法を測る。そこで人がEMDを見て関係を認めるまではH3比較・既定profile変更に進まない。
