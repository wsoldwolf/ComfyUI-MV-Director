# EMD 00013 自動歌詞Cue評価

> 再評価: [プロトタイプ8Bとの比較分析](prototype-8b-creative-regression-analysis-2026-09-20.md)で、以下の原因仮説と対策順位を見直した。対象欠落・反復の観測は維持するが、raw trace未照合のためCue失効経路は確定原因ではない。歌詞行単位の新規分類やfail-closed強化に先立ち、創作的補完を禁じる契約、Sceneをまたぐ文意、独立effectの扱いを修正する方針を推奨する。

日付: 2026-09-20  
対象: `C:\Software\ComfyUI\output\mv_director\context_loop_emd_00013.md`  
比較対象: `context_loop_emd_00012.md`  
対象実装: Planner v50 / `lyric_cue_mode=automatic`

## 結論

EMD 00013はprotocol回収とCamera構造では改善を確認できる一方、自動歌詞Cueの
目的は達成していない。歌詞に存在する`苔`、`花`、`狐火`及び`御神木`は
Action本文でいずれも0回であり、00012で残っていた苔・花・狐火も失われた。
代わりに歌詞根拠のない`透明な波紋`が24 Shotへ広がり、同じ身体templateが
54 Shot中36から40 Shotを占める。

したがって、現状のEMDを動画生成品質の合格例とはしない。固定辞書を復活させる
のではなく、Cue発見をScene単位の任意fieldから歌詞行単位の必須分類へ分離し、
発見済みCueをVisual BeatとActionのfail-closed契約へ渡す必要がある。

## 定量比較

| 指標 | EMD 00012 | EMD 00013 |
|---|---:|---:|
| Scene | 16 | 16 |
| Shot | 52 | 54 |
| Actionの一意文 | 40 | 38 |
| 2回以上出た完全一致Actionの総出現数 | 19 | 22 |
| 同一Actionの最大反復 | 5 | 10 |
| `苔`を含むAction | 3 | 0 |
| `花`を含むAction | 4 | 0 |
| `狐火`を含むAction | 4 | 0 |
| `御神木`を含むAction | 0 | 0 |
| `透明な波紋`を含むAction | 0 | 24 |
| `右手を胸の前で広げ` | 0 | 36 |
| `左手を腰に添え` | 0 | 36 |
| `体を左右に傾け` | 0 | 40 |
| `背中を向け` | 11 | 28 |

00013の最多Actionは次の一文で、10回完全一致する。

> 葉の間を通り抜ける透明な波紋に合わせて、右手を胸の前で広げながら左手を腰に添えて体を左右に傾け、背中を向けた姿勢へと自然に変化させる。

これは歌詞ごとの演技ではなく、対象、身体動作及び終端姿勢を一つのtemplateへ
固定した状態である。

## 歌詞Cue別評価

### Scene 3: 苔

原文には`苔へと還る`があるが、三つのActionは石畳の歩行又は
`葉の間を通り抜ける透明な波紋`を扱い、`苔`、大樹、根元、樹皮及び
苔自身の材質変化がない。00012で不十分ながら存在した苔tokenも失われた。

### Scene 4: 花

`人は花より / 短く咲いて`に対し、花は一度も現れない。代わりに神社建物の壁、
光の帯及び傷跡がAction目的になる。花の位置、開花、揺れ、散り又は人物の
非接触反応へ展開されていない。

### Scene 6: 御神木

`御神木は`に対し、Actionは`透明な波紋`と一般化された`木々`だけである。
`御神木`という複合名詞の完全一致保持に失敗し、固有対象の確立、幹・根・枝葉・
しめ縄等の可視状態及び人物が見上げる関係を作れていない。v50で追加した
「複合語を一般語へ短縮しない」契約が完成EMDまで到達していない。

### Scene 9 / Scene 14: 狐火

`狐火へ問う`及び`狐火は祈り`の双方で`狐火`は0回である。光の帯又は
透明な波紋へ置換され、狐火が人物から独立して前景、頭上、背景奥へ移動する
軌道、周囲を巡る演出及び石畳・木々への環境結果がない。

## Action品質

### 身体templateの支配

- `右手を胸の前で広げ`: 36/54 Shot
- `左手を腰に添え`: 36/54 Shot
- `体を左右に傾け`: 40/54 Shot
- `背中を向け`: 28/54 Shot

身体部位を使ってはいるが、感情ごとの演技差ではなく同じ骨格の反復である。
苔、花、御神木、狐火という対象が変化しても、対象との距離、視線、ためらい、
反動、伸展、沈み込み又は解放へ分化していない。

### Scene外漏洩

Scene 10には現在歌詞にない`千年鳥居をくぐるそなたよと歌うタイミングで`が
現れる。Scene 4では背景inventoryだけにある神社建物の壁が二つのAction目的に
なる。自動Cueが無効又は`なし`のSceneで、過去Scene又は背景由来の語が通常
Actionへ再流入している。

### 傷表現

`光の帯が傷跡を通り抜ける`は傷を可視物として扱い、共通Styleの
「歌詞中の傷は人物設定又は作者指示がない限り比喩」という契約と競合する。
`胸の古傷を意識`もRendererが物理的な傷を描く誘因になるため、Actionでは
胸郭、視線、呼吸又は防御的姿勢へ変換すべきである。

## Camera評価

### 良い点

- CUT 4、CONTINUE 12で、継続Scene主体の構造は保たれている。
- Arc Shotは15/54 Shotで、完全な固定Cameraには戻っていない。
- Zoom In 5、Zoom Out 4、Push In 6、Pull Out 5、Truck 7、
  Pedestal Up 4、Pan Right 3、Tracking 1を使用している。
- Action本文に`ACTION`、`AUDIT`、裸のslot番号又はseparator labelは残って
  おらず、直前のtransport wrapper正規化は機能した。
- 石灯籠は環境inventoryにあるがAction接触対象にはなっていない。

### 残る問題

Camera文は54本中17種類しかなく、2回以上の完全一致Cameraの総出現数は50である。
特に同じPush Inが6回、同じ右Arc、Pull Outが各5回使われる。有限Camera protocol
として物理的には妥当だが、Actionが同じため編集上の意味も同型化する。

顔close-upは5 Shotあるが、少なくとも二つはActionが`右手を腰に添える`、
`体を左右に傾ける`又は`背中を向ける`ことを中心にしており、Cameraが要求する
目、眉、口及び顔輪郭の表情accentと一致しない。Camera本数を増減する前に、
顔slotのAction契約を修復する必要がある。

## 根本原因

### 1. automatic Cueには無効時の保証がない

現在の実装はCue Cardが`valid=true`かつ対象が`なし`以外の場合だけ
`action_cue_scopes`、Scene位相及び配置・可視展開の完全一致転送を有効にする。
無効Cue CardはWARNINGにしてAction contextから隔離するが、automatic modeでは
そのSceneを停止も再発見もせず通常Actionへ進める。

v49の`priority_lyric_cues`にはCue Cardが不正でも原文tokenをActionへ渡す
退避経路があった。固定一覧を外したv50ではこの退避経路も消えたため、8Bが
対象を`なし`にするかCue Cardを不正にした時点で、歌詞Cueの存在そのものが
失われる。

### 2. 一つのSceneに対してCue Cardが一つしかない

Scene 3、4、6、9等は一Scene内に4から6行の歌詞を持つ。Visual Beatはその集合
から対象を一つだけ選ぶため、`幼い手`、`瞳`等の身体語又は別の可視語を選ぶと、
同じScene内の`苔`、`花`、`御神木`、`狐火`は契約対象にならない。

### 3. 現在の検証は「最重要の具体語」を判定しない

parserは根拠がScene原文の部分文字列であること、対象が根拠内にあること及び
配置・可視展開が非空であることを検証する。しかし対象が最も具体的で映像価値の
高い名詞句か、身体部位や抽象語を避けたか、配置・可視展開が対象自身を実際に
説明するかは意味検証しない。このため形式的に有効でも弱いCueが成立し得る。

### 4. Action Auditが反復に対してfail-openである

意味監査と表層反復は有限retry後に最小違反候補をAS IS採用できる。この方針は
小型LLMで処理を完走させる一方、10回完全一致するActionも完成EMDへ残す。
自動Cueが失われたSceneでは、履歴中の`透明な波紋`と身体templateが安全な既定値
として反復される。

## 推奨する次の改修

### P0: 歌詞行単位のCue Discoveryを独立させる

Scene全体のVisual Beatから対象を推測させるのではなく、各歌詞行に必ず一つの
`CUE` recordを返す小型の分類段を置く。

- 入力: 一つの歌詞行と作者本文だけ
- 出力: `NONE`又は`根拠 / exact target / kind / contact permission`
- 対象: 物理的具体物、場所要素、可視の象徴又は独立effect
- 除外: 人称、身体部位、時制、感情だけの抽象語及び一般的performance語
- `御神木`等の複合語を原文のまま保持する
- 全歌詞行を一つ又は少数のbatchで処理し、5060向けの呼び出し増加を抑える

これは歌ごとの語彙辞書ではなく、LLMによる行単位の意味分類である。Sceneへ複数
Cueがある場合はShot数まで保持し、Visual Beatが各Cueへ配置・可視展開を与える。

### P0: Cue Discovery後はfail-closedにする

発見済みCueのVisual Beatが不正、又はActionでexact target、配置、可視展開が
欠落した場合は、そのCueに限って再要求する。retry後も欠落する場合は
`CUE_DISCOVERY`又は`ACTION_GROUNDING`で停止する。Cue Cardが不正だから通常
Actionへ降格する経路を廃止する。

### P1: Cue SceneをVisual Beat前から隔離する

現在はvalid Cue Card生成後にAction Sceneを隔離する。Cue Discoveryを先に行い、
発見済みCue SceneをVisual Beat requestでも単独又はCue専用batchへ分ける。
これにより`透明な波紋`等が隣接Sceneへ複製される経路を閉じる。

### P1: 完全一致Action反復を構造エラーにする

意味類似は引き続きadvisoryにできるが、同一Actionの完全一致が別Sceneで再出現
した場合はAS IS採用せず、該当slotだけを再要求する。有限retry後も同一なら
`ACTION_REPETITION`で停止する。Pythonは文章を変更せず比較だけを行うため、
AS IS原則を維持できる。

### P1: 顔slotのActionをCameraと整合させる

顔close-up slotでは、まぶた、視線、眉、口又は明確な表情変化を必須にし、
腰の手、左右傾斜又は背面への転換だけの候補を`FACE_PERFORMANCE_MISSING`として
fail-closedにする。

## 判定

| 項目 | 評価 |
|---|---|
| 自動歌詞Cue | 1/5 |
| 対象から具体動作への展開 | 1/5 |
| Action多様性 | 1/5 |
| Cameraの勢い | 3/5 |
| CUT/CONTINUE構成 | 4/5 |
| 顔ActionとCameraの整合 | 2/5 |
| protocol衛生 | 5/5 |
| 総合 | 2/5 |

次の実装ではCameraを先に調整せず、歌詞行単位Cue Discovery、Cueのfail-closed化、
完全一致Action反復ゲートの順に着手する。これらが直らない限り、Cameraを動かして
も同じ身体templateを異なる方向から撮るだけになる。
