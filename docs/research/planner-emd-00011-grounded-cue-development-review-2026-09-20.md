# EMD 00011評価と具体Cue展開レビュー

- 日付: 2026-09-20
- 対象: `C:\Software\ComfyUI\output\mv_director\context_loop_emd_00011.md`
- 比較対象: `context_loop_emd_00010.md`
- 実装結果: Planner v48

## 結論

Planner v47のScene-local Cue隔離により、苔、花、狐火の他Sceneへの漏洩は
大幅に解消した。一方、Actionは対象を裸の名詞として参照するだけで、
大樹の根元、参道脇、空中の軌道等へ具体化できていない。さらに前傾の
直接表現は減ったが、体の回転、反対側の肩下げ、背中を丸める、胸を
突き出すという別の身体templateへ置き換わった。後半には`ACTION 14`等の
内部labelも11件混入した。

v48ではCueの局所性を維持したまま、Visual Beatに`配置`と`可視展開`を
追加する。Pythonは構造を検証するだけで演出文を合成せず、合格したActionは
従来どおりAS ISでCompilerへ渡す。

## 定量比較

| 指標 | EMD 00010 | EMD 00011 | 評価 |
|---|---:|---:|---|
| Scene | 16 | 16 | 同等 |
| Shot | 51 | 51 | 同等 |
| unique Action | 38 | 42 | 改善 |
| exact Action duplicate | 13 | 9 | 改善 |
| 苔 | 22回、14 Scene | 3回、Scene 3のみ | scope成功 |
| 花 | 2回、Scene 4のみ | 4回、Scene 4のみ | scope成功 |
| 狐火 | 19回、8 Scene | 6回、Scenes 9/14のみ | scope成功 |
| Arc Shot | 14 | 16 | 増加 |
| unique Camera | 22 | 18 | 低下 |
| 顔close-up | 未集計 | 6 | 適量 |
| Arcから顔 | 未集計 | 2 | 改善 |
| 顔からArcで全景 | 未集計 | 1 | 改善 |
| Cut / Continue | 4 / 12 | 4 / 12 | 維持 |

## Cue別評価

### 苔

Scene 3だけへ局所化できたが、三Actionは「苔へ向き合う」「苔へ近づく」
という関係だけである。Action内には`大樹`と`根元`が一度もない。
scene EMDをVisual Beatへ渡していても、従来Cue Cardに空間anchorを保存する
専用fieldがなく、後段で裸の`苔`へ縮退していた。

### 花

Scene 4だけへ局所化できたが、四Actionすべてが視線、身体方向又は前傾である。
`参道`は一度もなく、花の位置、風、花弁又は通過後の変化がない。
対象名の保持検査は通るが、対象自身の可視述語が不足している。

### 狐火

Scenes 9/14だけへ局所化でき、人物が狐火を保持する記述もない。ただし
`宙`と`舞う`は一度もなく、狐火自身の始点、軌道、終点及び環境への光の
結果がない。Scene 14では人物が狐火へ手を振って前進するActionが二回続き、
外部effectより人物の操作に近い構図へ戻っている。

## Action反復

- `体を回転`: 23/51 Shot
- `背中を少し丸める`: 20/51 Shot
- `胸を前に突き出す`: 8/51 Shot
- `前傾`: 2/51 Shot

表層語としての前傾は25回から2回へ減ったが、意味上の身体構成は
回転、肩下げ、丸めた背中へ移っただけである。完全一致検査だけでは
左右交換や語順変更を別Actionとして扱うため、LLM audit側で同じ
choreography skeletonを明示的に分類する必要がある。

## Protocol汚染

Scenes 12から16のActionに`ACTION 14`、`ACTION 15`、`ACTION 16`、
`ACTION 17`が計11件残った。これは自然文ではなくretry又はslot labelである。
Pythonで除去するとAS IS原則を破るため、構造品質違反
`internal_protocol_label`として再生成し、Auditでも
`INTERNAL_PROTOCOL_LABEL`を返す。

## Planner v48実装

1. Visual Beat Cue Cardを七fieldから九fieldへ変更した。
   - `配置`: 認可済み対象の具体的な空間anchor。
   - `可視展開`: 対象自身の材質状態、時間変化、空間軌道又は環境結果。
2. 対象があるCue Cardでは両fieldを必須、対象がない時は両方を`なし`とする。
3. scene EMDは`配置`の選択だけに使い、新しい対象、接触又はeffectを認可しない。
4. Actionは対象名だけでなく、配置と可視展開をScene内で読める形にする。
5. external effectは始点、空間経路、終点及び環境結果を先に示し、人物は一回だけ反応する。
6. release Shotは既に展開済みの対象名を再度繰り返さず、身体状態を収束させる。
7. Action品質検査へ`internal_protocol_label`を追加した。
8. Audit理由へ`BODY_TEMPLATE_REPETITION`と`INTERNAL_PROTOCOL_LABEL`を追加した。

## AS IS境界

Pythonが行うのはCue Cardのfield順、対象有無、非空配置、非空可視展開、
既知内部label等の構造検証だけである。大樹、参道、空間経路、身体演技の
自然文はLLMが生成する。Pythonは合格Actionを削除、置換、要約又は合成しない。

## 次回EMDの受入条件

- 苔はScene 3だけに存在し、少なくとも一Actionが大樹又は樹木の根元等の
  scene contextに整合するanchorと苔の可視状態を含む。
- 花はScene 4だけに存在し、参道脇等のanchorと花又は花弁自身の変化を含む。
- 狐火はScenes 9/14だけに存在し、空中の始点、軌道、終点及び環境結果を含む。
- 狐火へ手を振って前進する人物Actionを複数Shotで反復しない。
- `ACTION N`、`BEAT N`、`CAMERA N`、`AUDIT N`をAction本文へ出さない。
- 回転、反対側の肩下げ、丸めた背中の同一templateを意味上反復しない。
- Cue局所化、4 Cut / 12 Continue及びArcから顔、顔からArcの成果を後退させない。

## 検証

- Planner集中テスト: 85件成功。
- ComfyUI venv全体テスト: 348件成功、skipなし。

