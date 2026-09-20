# EMD 00007評価と歌詞根拠境界

## 対象

- EMD: `C:\Software\ComfyUI\output\mv_director\context_loop_emd_00007.md`
- 比較対象: `context_loop_emd_00006.md`
- 評価日: 2026-09-19
- 対象profile: `anime_emotional_mv`

## 結論

EMD 00007は、00006のArc過多を抑え、Camera familyを増やした点では改善した。しかし、人物演技とCamera目的の双方へ背景インベントリが漏れ、歌詞に無い石灯籠が反復して主題化した。Actionは前傾、胸前の手、交互の腕振り、腕を広げる動作、足上げ及び左右傾斜へ収束し、Cameraも確定Actionに無い身体動作や対象を約半数のShotへ追加した。この状態では全編動画の再生成コストに見合わない。

## 定量結果

| 指標 | EMD 00006 | EMD 00007 | 評価 |
|---|---:|---:|---|
| Scene | - | 16 | 構造は成立 |
| Shot | 52 | 53 | 同程度 |
| CUT / CONTINUE | - | 4 / 12 | 継続中心で良好 |
| Arc Shot | 43 (82.7%) | 22 (41.5%) | 大幅改善 |
| Tracking Shot | - | 13 | family追加 |
| Push In | 1 | 8 | family追加 |
| Zoom In | 8 | 7 | 顔accent量は妥当 |
| Static / Pull Out | 0 | 2 / 1 | 少数だが対照を形成 |

Camera familyの配分だけを見ると、00007は00006より明確に良い。問題は各Shotの意味とAction整合性である。

## 主な問題

### 1. 歌詞に無い背景物が演技対象になった

- `石灯籠`: Action 16件、Camera 13件。Scene 2、7、8、10、11、13、14、15へ分散。
- `狐火`: Action 0件、Camera 0件。歌詞に存在するScene 9、14でも欠落。
- `苔`: Action 0件、Camera 0件。Scene 3の歌詞cueを未使用。

これは対象語ごとの禁止漏れではない。Visual Beat、Action、CameraへEnvironment inventoryが渡り、8Bが「背景に存在する物」を「現在歌詞の演技対象」と再解釈したことが原因である。

### 2. 身体演技がテンプレートへ収束した

Action内の主な反復は、`前傾` 18件、`胸の前` 28件、`交互に振る` 16件、`大きく広げる` 13件、`足を高く` 15件、`左右に傾く` 28件、`後ろへ引く` 12件であった。完全一致Actionも6種類が各2回反復した。

身体部位を列挙するpromptは、演技の多様性ではなく「全身を使った定型文」を増幅した。次段では身体部位数ではなく、歌詞根拠、身体主導、終端silhouetteを有限fieldとして固定する必要がある。

### 3. CameraがActionを書き足した

確定Actionに無い対象又は身体動作をCameraが追加したShotは26/53件、約49%であった。例:

- Scene 4 00:32.375: Actionは紅葉した樹木、Cameraは石灯籠を追加。
- Scene 6 00:51.500: Actionは御神木、Cameraは足上げを追加。
- Scene 12 01:45.667: Actionは千年鳥居、Cameraは石灯籠、足上げ、前傾を追加。

Camera promptの禁止文だけでは、自由文を返す8Bが`locked_action`を要約・補完する傾向を止められない。

### 4. 短尺Arcと顔Zoomの構図矛盾

2.5秒未満の長尺Arcが5件残った。品質retry後のfail-openにより、`arc_permission=forbidden`違反がそのまま採用されたためである。顔Zoom 7件のうち少なくとも3件は、全身移動や大きな手足動作を要求するActionと競合した。

### 5. 時刻・照明との競合

共通環境は夜間である一方、歌詞語`朱の空`を文字通りの空色としてAction/Cameraへ展開している。比喩又は歌詞cueを可視化する場合も、明示された時刻・照明を置換してはならない。

## 評価

| 観点 | 10点満点 |
|---|---:|
| 構造・継続性 | 8 |
| Camera family配分 | 7 |
| Camera文の多様性 | 2 |
| Action/Camera整合性 | 2 |
| 歌詞cue整合性 | 1 |
| 身体演技の多様性 | 2 |
| 総合 | 3 |

## 採用した最小改修

### 歌詞根拠付きCue Card

Visual Beatを次の固定形式へ変更した。

```text
感情=...｜根拠=...｜対象=...｜接触=...｜現象=...｜身体主導=...｜終端=...
```

- `根拠`: 現在Sceneの原文歌詞又は作者本文からの完全一致引用、又は`なし`。
- `対象`: `根拠`内の完全一致部分文字列、又は`なし`。
- `接触`: `禁止|許可`。
- `現象`: `なし|外部自律|身体操作`。
- Pythonはfield順、列挙値、原文包含だけを検証し、LLM本文を修正しない。
- 無効なCue CardはAction/Cameraの対象、接触、effect sourceから隔離し、Scene番号と理由をWARNINGへ出す。

### 環境責務の分離

- Visual Beat、Action、Action audit、Cameraへscene EMD、背景Picture及びDirectionのEnvironment inventoryを渡さない。
- Environmentは最終EMD rendererで従来どおり独立合成する。
- ActionはStyle、Time/Lighting、Motion、Otherだけを受ける。
- CameraはStyle、Time/Lighting、Camera、Otherだけを受ける。

これにより、背景に石灯籠が存在しても、現在Sceneの歌詞又は作者本文に石灯籠が無ければ演技対象又はCamera目的にならない。対象語固有のPython規則は追加していない。

## 次の検証

同一入力でPlannerを再実行し、次を確認する。

1. Cue Cardの`根拠`が各Sceneの原文に完全一致する。
2. 歌詞に無い`石灯籠`がAction/Cameraから消える。
3. `苔`及び`狐火`が該当Sceneだけで一回ずつ対象又は外部自律現象として現れる。
4. Cameraがlocked Actionに無い対象・身体動作を追加しない。
5. 前傾、胸前の手、腕広げ、足上げ、左右傾斜の反復数が減る。
6. 2.5秒未満のShotでArcが残る場合、Camera自由文protocolを有限fieldへ移す次段改修を行う。

## 続行改修: Camera有限field化

歌詞根拠境界に続き、`anime_emotional_mv`の通常Cameraを次の固定protocolへ移した。

```text
MOTION=...｜START_SCALE=...｜END_SCALE=...｜START_VIEW=...｜END_VIEW=...｜PATH=...｜COVERAGE=...
```

- 非MOTION fieldはrequestに列挙した有限値だけを許す。
- Camera LLMは対象名、人物動作及び説明文を出力しない。
- PythonはMotion/PATH一致、短尺Arc禁止、Arc割当、顔Zoom可視範囲及び顔Arc handoffを検証する。
- 有効な選択値は、対象語や新しい人物動作を一切加えない固定英語H3 Camera文へ直列化する。
- 一度の該当slot retry後も不正な場合は、同じslot role、Shot尺、Arc割当及び顔割当から決定論的fallbackを選ぶ。
- `cinema_mv`、`anime_story_mv`その他のprofileは、比較可能性を保つため従来のCamera自由文を維持する。

これにより、Cameraが`locked_action`を言い換える過程で石灯籠、足上げ、前傾等を追加する経路を構造的に閉じた。次のEMDではCamera行が固定英語形式になり、人物演技の評価をAction側へ切り分けられる。
