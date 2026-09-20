# EMD 00010 優先歌詞Cue scope評価

日付: 2026-09-20

## 対象

- EMD: `C:\Software\ComfyUI\output\mv_director\context_loop_emd_00010.md`
- 比較対象: `context_loop_emd_00009.md`
- profile: `anime_emotional_mv`

## 総評

EMD 00010は、EMD 00009で完全に欠落していた`苔`、`花`及び`狐火`を
Actionへ保持できた。一方、Cueを現在Sceneへ閉じ込める契約に違反し、苔は
歌詞の無い13 Scene、狐火は歌詞の無い6 Sceneへ漏洩した。優先Cueの保持自体は
動作したが、Scene scopeは不合格である。

Cameraと編集構造は維持又は改善した。16 Scenes、51 Shots、4 CUT、12 CONTINUE、
14 Arc Shotを持ち、顔close-upは4本から7本へ増え、Arcから顔へ入る遷移も一件
生成された。ただし、人物演技は`前傾`、`胸の前`及び`左右非対称`という別の
定型文へ収束した。

## 定量比較

| 指標 | EMD 00009 | EMD 00010 | 評価 |
|---|---:|---:|---|
| Scenes | 16 | 16 | 変化なし |
| Shots | 52 | 51 | 正常 |
| CUT / CONTINUE | 4 / 12 | 4 / 12 | 良好 |
| 固有Action | 27 / 52 | 38 / 51 | 表層多様性は改善 |
| 完全重複Action | 25 | 13 | 改善 |
| 固有Camera | 20 / 52 | 22 / 51 | 微改善 |
| 完全重複Camera | 32 | 29 | 微改善 |
| Arc Shot | 15 | 14 | ほぼ維持 |
| 顔close-up | 4 | 7 | 増加 |
| Arcから顔close-up | 0 | 1 | 改善したが不足 |
| 前傾 | 3 | 25 | 大幅悪化 |
| 胸の前 | 24 | 24 | 未改善 |
| 左右非対称という語 | 0 | 42 | planning語彙の定型コピー |

## Cue別評価

### 苔

- 正しいScene 3内: 3 Action
- Scene外: 19 Action、13 Scenes

`苔へと還る`には反応したが、`苔の還る感情`、`苔の存在に反応`及び前傾へ
抽象化された。大樹又は御神木の根元、湿った質感、人物との距離、接触可否、
触覚後の表情及びScene内の解放は存在しない。さらにScene 1及び2にも苔が現れ、
歌詞triggerより前へ漏洩している。

### 花

- 正しいScene 4内: 2 Action
- Scene外: 0

三Cue中でscopeは唯一正しい。しかし`花の還る感情`に留まり、花の位置、開花、
散花、花びらの軌道、人物の視線又は時間的反応を持たない。scopeは合格、可視の
出来事は不合格である。

### 狐火

- 正しいScene 9及び14内: 6 Action
- Scene外: 13 Action、6 Scenes

歌詞triggerより前のScene 7及び8にも出現し、その後も複数Sceneへ残る。
正しいSceneでも人物が`触れるように`手を上げる、顔を近づける又は身体を傾ける
演技が中心である。狐火自身が前景から背景へ横切る、人物を周回する、樹木間を
離れる又は環境を一時的に照らす外部自律運動は不足する。

## 原因

Planner v46はprofileの三tokenを`planner_policy_contract`へ実値で格納し、その
shared contractをVisual Beat、Action及びAuditの全Sceneへ渡していた。さらに
複数Sceneを一個のLLM requestへ入れるため、Scene 3の苔を同じrequest内の
Scene 1及び2も参照できた。Scene 9の狐火がScene 7及び8へ先行出現したことも
同じ構造で説明できる。

採用Visual BeatとActionの生本文を後続batchの履歴へ渡すため、一度出現したCueは
後続Sceneにも残留した。Pythonの現在Scene完全一致抽出は正しかったが、LLMへ渡す
prompt全体ではtokenがScene-localではなかった。

また、scene EMDはSong DirectionとShot Layoutには渡されるが、Visual Beatへは
渡されていなかった。このため`苔`を認識しても、森の`大樹の根元`という空間へ
配置する材料がなく、抽象的な感情句へ退行した。

## Planner v47実装

1. `planner_policy_contract`から実token一覧を除去し、`entity_local_only`という
   scope宣言だけを共有する。
2. 優先Cueを持つSceneはVisual Beat及びAction/AuditをScene単独requestにする。
   非Cue Sceneは従来通り`scenes_per_batch`でまとめ、5060向けのcall数を抑える。
3. Cue SceneのVisual Beat及びAction生本文を後続Sceneのrecent historyへ積まない。
   Scene境界で`previous_batch_action`と`previous_batch_beat`も空にする。
4. profileに定義されたtokenが現在Sceneの許可Cueに無いActionへ出た場合、
   `unexpected_priority_cue`として該当slotを再要求する。個別の日本語tokenを
   Pythonへ直書きせず、profile metadataを唯一のregistryとする。
5. Scene外Cueを含む不採用本文はretry promptへ再掲しない。小型LLMが禁止対象を
   そのまま模倣する経路を閉じる。
6. scene EMDをVisual Beatだけへ`scene_context`として渡す。これは歌詞で既に
   認可された対象の位置と空間関係を決める用途に限定し、背景物単独では対象、
   接触又はeffectを発火できない。
7. 狐火Actionは狐火自身の軌道又は環境変化を人物反応より先に記述し、人物による
   接触、接触するようなreach、顔からの接近、生成、保持、誘導又は解放を禁止する。
8. `左右非対称`、`silhouette`、`身体主導`、`終端`及び`胸郭を傾ける`を最終Action
   へコピーせず、時間方向の具体的な身体変化へ置換するよう生成及び監査promptを
   更新する。

LLMが返した採用Action自然文は従来通りAS ISであり、Pythonは本文を合成又は
置換しない。Pythonが所有するのはrequest境界、履歴scope及びprofile駆動の有限
token検査だけである。

## 次回EMDの合格条件

1. 苔はScene 3だけ、花はScene 4だけ、狐火はScene 9と14だけに現れる。
2. 優先CueのScene外Action数が0である。
3. 苔はscene context内の大樹、樹木の根元又は石段端等へ具体的に配置される。
4. 花は開花、散花又は花びらの移動という時間変化を持つ。
5. 狐火は自身の空間軌道又は環境への可視結果を持ち、人物が触れない。
6. `左右非対称`というplanning語彙をActionへ出力しない。
7. 前傾を主要終端poseにするActionを大幅に減らす。
8. Arcから顔又は顔からArcへの遷移を複数箇所へ分散し、同一Sceneの連続Zoom Inを
   避ける。
9. 石灯籠への接触、作者未指定の走行及び足元接写は引き続き0とする。

## 判定

- EMD構造: 合格
- CUT / CONTINUE: 合格
- Camera量: 条件付き合格
- 優先Cue保持: 合格
- 優先Cue Scene scope: 不合格
- Cueの可視Scene展開: 不合格
- 人物演技の意味的多様性: 不合格

Planner v47では最初にscopeを正し、その後の実生成EMDで可視Scene展開と身体演技を
再評価する。scopeが直る前にCueやArcの量を増やすと、誤った対象を全編で強調する
ため、動画生成よりEMD検査を先行させる。
