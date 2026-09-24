# 簡潔Scene仕様 P4：不透明ラベルだけの対照比較

2026-09-25。[P3](compact-scene-spec-p3-8b-prompt-2026-09-24.md)で`PERFORMER`行の形式違反が見られたため、旧`ComfyUI-cl-japanese2json`の不透明プレースホルダを参考にした。ただし旧方式の主用途は参照記号・翻訳区間の**輸送と復元**であり、人物演技の意味を生成することではない。まず本番コードを変えず、ラベル単独の効果を調べた。

## 条件と結果

保存済みAudio-reference EMDのScene 6（御神木、1 Shot）とScene 9（狐火、2 Shot）、同一Event-only資料、Qwen3-8B-Abliterated Q4_K_M、seed 1・2、temperature 0.2、`/no_think`。各Scene・seedで**同一system promptと同一の歌詞・背景・Event・slot意味・順序**を使い、`output_slots[*].token`のみ変更した。自然ラベルは`SCENE`、`PERFORMER_1`、`CAMERA_1`など。不透明ラベルは`MVD06T00X`など。各ラベルを一字ずつ返す短い行形式で、意味欄はそれぞれ「場面」「人物」「撮影」とした。[スクリプト](../assets/research/audio-reference-body-isolation-2026-09-24/probe_p2_scene_spec.py)と[全8応答](../assets/research/audio-reference-body-isolation-2026-09-24/p4-8b-label-control-event-seed1-2.json)を保存した。H3は使用していない。

| 条件 | 行形式の合格 | 意味内容 |
| --- | ---: | --- |
| 自然ラベル | 4/4 | 人物・撮影欄に具体文が入る。ただし歩行、静止、足元へ戻る例もあり、振付品質の達成ではない。 |
| 不透明ラベル | 4/4 | Scene 6の人物欄2/2が木・葉の動作へ主語を移した。Scene 9の2/2は本文が単に「場面」「人物」「撮影」となり、実質的に空欄。Scene欄は4/4とも「場面」だけ。 |

例えば同じScene 9・seed 2で、自然ラベルは人物が狐火へ手を差し伸べCameraが両者を捉える文を返した。不透明ラベルは全5行のトークンを正確にコピーしたものの、本文はslot意味の復唱だけだった。**構文の成功と映像仕様としての成功は別**である。4組の小標本なので「自然ラベルが常に優れる」とは言えないが、今回の入力に対し不透明ラベルを全般導入する根拠はなく、むしろ意味欠落の明瞭な退行がある。

P3の`PERFORMER`形式が2/4だったのに今回4/4になった差は、ラベル単独の効果とは解釈しない。今回の両条件は`output_slots`の列挙と同じ短いsystem promptを持ち、P3とは契約全体が異なるからである。

## パイプラインへの判断

`Planner`、`Direction`、`Vision`、`Compiler`のプロトコルを一括して置換しない。各段階で、(1)ラベルの取り違え・欠落、(2)ラベルは正しいが本文の主語や演技が欠落、(3)翻訳時の保護span破損を分けて評価する。旧プレースホルダの考え方は(3)のような可逆な記号保護へ限定して検討できる。(2)に対して出力ラベルの不透明化は解決策にならなかった。

現行実装の初期棚卸しでは、PlannerのScene人物段は`PERFORMANCE<TAB>slot<TAB>本文｜END_STATE=...`として人物と終端状態を明示し、Camera段は別の`CAMERA`行を要求している。Directionは要求された`STYLE`・`MOTION`・`CAMERA`の有限レコード、Visionは固定観測レコード、Compilerは番号付き`TRANSLATION`と既存の保護tokenを用いる。これらは同じ「一般語ラベル」でも目的が異なる。今回の研究用`PERFORMER_1|...`応答だけから、各段階の形式・品質問題を同一原因とみなせない。

次の小範囲検証は、8Bへ渡す**意味上の役割と人物の開始状態**を短く明示する入力設計を対象にする。形式改善が必要なtaskのみ、既存の有限slot・grammar・厳密検証を調べる。Pythonが人物演技の自然文を補修したり、全パイプラインのsystem promptを同時に変更したりはしない。作者のEMD指示を優先し、実8B出力で人物の時間的変化とCamera coverageが確認できるまではH3生成を増やさない。
