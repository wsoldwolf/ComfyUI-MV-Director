# 簡潔Scene仕様 P5：欄名を具体化すると8Bの映像文は良くなるか

2026-09-25。[P4](compact-scene-spec-p4-opaque-label-control-2026-09-25.md)では不透明ラベルが意味を失わせたため、自然語ラベルをさらに具体化して比較した。本番のプロトコル、system prompt、profile、EMD、H3出力は変更していない。

## 条件

Qwen3-8B-Abliterated Q4_K_M、保存済みAudio-reference EMDのScene 6（御神木）・Scene 9（狐火）、Event-only資料、seed 1・2、temperature 0.2。各対照は**同じsystem prompt、歌詞、Event、slot意味・順序**を使い、`output_slots[*].token`の欄名だけを替えた。全応答は[明示的な動作ラベル](../assets/research/audio-reference-body-isolation-2026-09-24/p5-8b-explicit-label-control-event-seed1-2.json)と[姿勢変化ラベル](../assets/research/audio-reference-body-isolation-2026-09-24/p5-8b-phase-label-control-event-seed1-2.json)に保存した。[研究スクリプト](../assets/research/audio-reference-body-isolation-2026-09-24/probe_p2_scene_spec.py)で再現できる。

| 欄名 | 行形式 | Scene欄の主題 | 人物・Camera |
| --- | ---: | --- | --- |
| `SCENE` / `PERFORMER` / `CAMERA` | 4/4 | 御神木・狐火より参道・紅葉へ寄る例が多い | 人物・Cameraの文は出るが歩行や静止が残る |
| `SCENE_EVENT` / `PERFORMER_BODY_ACTION` / `CAMERA_MOTION_COVERAGE` | 3/4 | 4/4で御神木又は狐火を冒頭に置いた | 御神木では人物が静止・祈る2/2。狐火でも動作連鎖は弱い。1件は区切り`|`が全角`｜`へ変化 |
| `SCENE_VISIBLE_EVENT` / `PERFORMER_POSE_CHANGE` / `CAMERA_SHOWS_EVENT_AND_PERFORMER` | 4/4 | 御神木・狐火より背景を先に書いた | 御神木2/2で人物欄の主語が木・葉へ移る。狐火は人物欄が成立するがほぼ片手と視線のみ |

欄名は確かに8Bへの**弱い意味指示**である。特に`SCENE_EVENT`は主題の選択を変えた。しかし、長く具体的な欄名ほど人物演技が豊かになるわけではない。`PERFORMER_BODY_ACTION`は静止を選び、`PERFORMER_POSE_CHANGE`はScene 6で木の変化を人物欄に書いた。`CAMERA_MOTION_COVERAGE`も人物と対象を同時に撮る保証にはならない。自然語ラベルは意味の事前分布を動かすが、原歌詞・作者指示・人物の開始状態・対象の出来事を正しく結び付ける契約の代用にはならなかった。

## 採用判断と次の焦点

今回の二案を本番プロトコルへ採用しない。現行Plannerの`PERFORMANCE`/`CAMERA`を全段階で改称する理由もない。意味上の弱点は、まず**Scene Eventと人物の演技意図を混ぜずに入力し、人物の開始状態と終端変化を同じ短い文脈で渡す**側にある。欄名は短く役割を表すものに留め、対象の可視変化・人物の身体経路・Camera coverageをそれぞれのsystem promptと入力資料で検証する。形式遵守率と創作品質は引き続き別評価とし、8Bで人物動作が回復するまでH3の比較生成は増やさない。
