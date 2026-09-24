# Shot接続器 P1：演出候補の寄与と歌詞Shotの位置

2026-09-24。P0の[出典・時間軸追跡](shot-linkage-p0-provenance-2026-09-24.md)を受けたP1の短区間比較。候補ありの保存済み8B応答に対し、候補なしを各Scene一回だけ新規推論した。動画生成は行っていない。二つのSceneはそれぞれ別の固定fixtureなので、互いの出力を直接A/Bとしない。

## 保存済み対照の選定

| 対照 | 歌詞対象と所属Shot | 保存済み8BのEvent | 候補ありの事実 | 候補なしで確かめること |
|---|---|---|---|---|
| P1b v2、Scene 3 | `苔へと還る`はShot 2。Shot 1は`石段に積もる` | `SHOT=2｜紅葉の木々の間から、苔が石段に沿って光る` | 任意の演出候補7件を入力。**苔は採用されたが、指定候補の「大樹の根元を指で撫でる」までは採用されていない** | 候補を外しても苔・Shot 2が残るか。残れば歌詞とP1b指示だけでも対象選択可能 |
| 全前Scene状態なし、Scene 9 | `狐火へ問う`はShot 3 | `SHOT=1｜朱の空に舞う狐火が…空中を漂う` | 同じ7件を入力。狐火は選ばれたが、明示歌詞より二Shot早い | 候補を外しても狐火が出るか、またShot 1への早期配置が残るか |

花のScene 4は、保存済みP1b v2で`人は花より`がShot 2にあるにもかかわらず、EventはShot 1の紅葉と落葉だった。候補ありでも花を選んでいないため、候補なしとの差から「花の採用における候補の寄与」を測れない。まず上の成功例二つで検証し、花は次の歌詞読解単位の試験へ回す。

その後、ユーザーから「花はユーザープロンプトに書いていないため、書けば8Bが反応するかもしれない」と指摘があった。後段に示すとおり、花の演出候補を**実際にEvent入力へ追加した**別の局所比較も実施した。

別の保存済み全16 Scene対照では、Scene 3のモーション補完は歌詞「苔へと還る」と同じShot 2へ配置されていたが、原文は「後方へ大きく退かせた直後に前方へ切り返し、移動を続ける」だった。このEvent自体は苔ではなく落葉を選んでいる。Scene 4も花の歌詞を含むShot 2へ「斜め前方へ大きく移動し続ける」補完を置くが、Eventは花を選ばない。Scene 9は狐火Eventを歌詞のShot 3より前のShot 1へ置き、明示モーション補完はない。**位置がたまたま歌詞Shotと一致しても内容が適合するとは限らず、対象が合っていても開始Shotが適切とは限らない。** Shot接続器はこの二問題を別に扱う必要がある。

## 一変数比較の固定条件

`tools/offline_shot_linkage_p1_probe.py`は保存済み`scene-author-event`の**生入力**を読み、`staging_candidates_optional`だけを空配列にする。他の歌詞原文・時刻、Scene/Shot番号、背景、継続、System Prompt、モデル、temperature、実効seed 2、grammarは維持する。保存済み対照のraw payloadがcanonical JSONとバイト一致すること、System Promptが該当試験で使ったファイルと一致することを検査する。モデル`qwen3-8b-abliterated-Q4_K_M.gguf`のSHA-256 `8625E48DA4C4BE9BCBA2414FD8CAD4095FF3A538D5B0111C2B26B5F6209538B9`も既存manifestと一致した。

- 苔の対照：`docs/assets/research/scene-composition-full-sequence-2026-09-23/p1b-six-scenes-seed2-v2/summary.json`、P1b Event v2 System Prompt。
- 狐火の対照：`docs/assets/research/scene-composition-full-sequence-2026-09-23/no-previous-state-full-seed2/summary.json`、当時のP1 Event System Prompt。
- CPU事前検査：各対照で候補7件→0件以外のJSONフィールドは同値。候補なしの入力と新規応答を`docs/assets/research/shot-linkage-p1-2026-09-24/`に保存。全549件のCPU回帰は通過。

## 実8Bの候補なし結果

| Scene | 候補ありの保存済み応答 | 候補なしの新規応答 | この一試行から言えること |
|---|---|---|---|
| 3 / 苔 | `SHOT=2`で苔が石段に沿って光る | `SHOT=1`で落葉が風に揺れ、苔むした石畳へ落ちる | 候補なしでも「苔」は語として残る。ただし主題・歌詞所属Shotから背景の性質へ後退。候補は対象焦点と位置に寄与した可能性が高いが、候補原文の大樹の根元・指先の接触は候補ありでも実現していない |
| 9 / 狐火 | `SHOT=1`で狐火が朱の空に舞い、石畳を照らして漂い、終端で樹間へ広がる | `SHOT=1`で狐火が夜空に舞い上がり、石畳を照らす | 具体名詞は候補なしでも選ばれる。両条件とも明示歌詞のShot 3より前に狐火を開始し、作者候補の両手の振付・人物周囲の旋回はどちらも採用しない |

入力と生応答は[`moss-candidate-off-seed2`](../assets/research/shot-linkage-p1-2026-09-24/moss-candidate-off-seed2/scene3-candidate-off.json)と[`foxfire-candidate-off-seed2`](../assets/research/shot-linkage-p1-2026-09-24/foxfire-candidate-off-seed2/scene9-candidate-off.json)に保存した。二応答ともEventの有限形式に合致する。比較は同じseed、同じ8B、同じSystem Promptで候補欄だけを変えた**局所一試行**であり、別seedや別曲への一般化を主張しない。既存の候補あり応答は再推論していないため、ランタイムの厳密な再現性を独立には確認していない。

候補ありと候補なしの二応答が同じ対象を選んでも、そこから8Bの内部の判断理由は分からない。候補文の逐語的再利用、対象の選択、位置の選択を別々に評価する。また、Scene 9で狐火が候補なしでもShot 1へ先行するなら、候補だけでなくScene単位EventのShot配置契約が原因候補として強まる。候補なしで対象が消えた場合は作者の外部着想が対象選択へ寄与したと判断できるが、それだけでは身体の振付やCamera連動の改善を証明しない。

## 次に行う順序

1. 花と御神木について、Shot所属を固定した「完結した歌詞句を意味解釈用に渡す」短区間比較を設計する。元歌詞の時刻を別Shotへ移さない。苔や狐火も名詞の有無だけを合格条件にせず、対象の役割と開始Shotを見る。
2. Eventと8B演技原文を固定し、補完なし／既存最長Shot配置／作者又はLLMが選んだアクセントShotをCPU上で比較する。Pythonが名詞から新しい自然文を作らない。`継続`境界の終端状態とCamera到達点の受け渡しを先に検証する。
3. EMD上で対象の一回の発生、身体の準備→主動作→解放、Camera coverageが読めるまでH3全編生成をしない。

## 続く検証：花の完結句を同一Shotで読む

P1b v2のScene 4では`人は花より`と`短く咲いて`がどちらもShot 2にある。保存済み応答は花を選ばなかったため、[実験用の汎用Event指示](../../prompts/experiments/scene_author_completed_phrase_event.txt)の下で、`completed_lyric_phrase`欄を用意した。空配列、二行を連結した本文と`shot=2`・原行情報を持つ記録、そして**Shot番号を重ねず句本文だけを持つ記録**の三条件とする。後二者は同じShotの連続原歌詞だけから作り、`original_lyrics`の原文・時刻・Shot所属、候補7件、seed 2、モデルを変えない。指示文は花など個別の対象名を追加しない。三条件を同じ新System Promptで各一回推論したので、上記保存済みP1b v2応答とは直接A/Bにしない。

| 条件 | 8B Event応答 | 判定 |
|---|---|---|
| 意味句なし | `SHOT=1｜紅葉した木々の影が石畳に揺れて、光と影が揺れる` | 歌詞対象を選ばず、歌詞より早いShot 1 |
| 意味句＋`shot=2` | `SHOT=2｜紅葉した木々の影が石畳に揺れて、光と影が舞う` | 歌詞を含むShot 2へ移動したが、花は依然欠落 |
| 意味句本文のみ | `SHOT=2｜紅葉の木々が揺れ、落ち葉が石畳に積もる` | 重複したShot番号なしでもShot 2へ移動したが、花は依然欠落 |

生入力・応答・prompt hashは[花の最初の2条件](../assets/research/shot-linkage-p1-2026-09-24/flower-completed-phrase-seed2/manifest.json)と[Shot番号なしの追加条件](../assets/research/shot-linkage-p1-2026-09-24/flower-text-only-seed2/manifest.json)に保存した。**この一seedでは完結句を追加した二条件で時間上の割当がShot 2へ変わったが、対象の選択は改善しなかった。** 単なる入力長や乱数列の変化を一試行では排除できず、句の意味理解が原因と断定しない。8Bに歌詞全体をさらに積めば花が出る、という根拠にもならない。

## CPU照合：補完を別Shotへ移すだけで十分か

[全16 Scene保存物](../assets/research/scene-composition-full-sequence-2026-09-23/no-previous-state-full-seed2/summary.json)の生Event・生Performance・Camera・補完原文を固定して、自然文を作り直さず、補完なし／採用位置／仮の強調Shot位置の三条件を読み比べた。これは別fixtureの**文章上の照合**であり、新EMD・H3の品質評価ではない。

| 区間 | 補完なし | 既存位置 | 仮に別Shotへ配置 |
|---|---|---|---|
| Scene 12 | 生演技はShot 1で後退、Shot 2で前進・頭上への腕、Shot 3で再び後退。身体の反復は残る | Profile補完はShot 1に「後方へ大きく退く→前方へ切り返す」を追記。生演技の後退と重なり、一Shot内で往復が増える | 歌詞`今この刹那を`を含むShot 2へ仮移動すると、大きな全身往復が`Zoom In on the face`のCameraと競合し、主動作を撮れない |
| Scene 4 | 生Eventは花ではなく歩行・石畳の足音。生演技も歩行と腕の上げ下げ | Profile補完は花の歌詞を含むShot 2に「斜め前方へ大きく移動し続ける」を追記。**Shot位置だけは合っても花のEventを回復しない** | 他Shotへ移しても花の対象欠落は変わらず、歩行の重複又は歌詞からの離脱が増える |

したがって既存の「最長Shotから歌詞アクセントShotへ機械的に移す」だけでは解決しない。**補完を採用しない選択肢、原文が選択済みEvent・生演技・Cameraで読めるか、作者が明示した位置の優先**が先に必要である。Pythonが日本語文を意味分類して自動修復する案ではなく、作者又はLLMが短い位相と採否を選び、接続器はそのID・順序・時刻・画角coverageを検査する案を維持する。Scene 12については三条件のいずれも「連続した豊かな振付」の合格証拠にならないため、現時点で本番Shot再配置を実装しない。

## 追加検証：花をユーザーの演出候補として渡す

花の候補が元入力に無かったという交絡を取り除いた。Scene 4の保存済み生Event入力に、[実験用候補原文](../assets/research/shot-linkage-p1-2026-09-24/flower-staging-candidate.txt)を`staging_candidates_optional`の8件目として追加した。候補は歌詞「人は花より」「短く咲いて」を明示し、参道脇の花を一度確立して人物の視線・表情で受ける内容である。さらに既存7件による希釈を区別するため、候補欄を花1件だけにした条件も比較した。その他の歌詞原文・Shot所属・Scene情報・背景・System Prompt・モデル・推論パラメータは固定した。`tools/offline_shot_linkage_p1_candidate_addition_probe.py`が入力を生成し、追加以外のJSONフィールドが同値であることをCPUテストで確認した。動画生成・本番Planner変更は行っていない。

| 実効seed | 候補条件 | 実8B Event応答 | 花の採用 |
|---|---|---|---|
| 2 | 元の7件を同一実行で再推論 | `SHOT=1｜紅葉の木々から落ちる葉が、狐巫女の足元に積もる` | なし |
| 2 | 元の7件＋花1件 | `SHOT=1｜紅葉の木々が風に揺れ、一枚の紅葉が石畳の道へ落ちる` | なし |
| 2 | 花1件だけ | `SHOT=2｜紅葉した木々の一枚が風に揺れて、地へ落ちる` | なし |
| 3 | 元の7件を同一実行で再推論 | `SHOT=2｜紅葉の木々から落ちる紅葉が、狐巫女の足元に積もる` | なし |
| 3 | 花1件だけ | `SHOT=2｜紅葉した木々の一枚が風に揺れて、地へ落ちる` | なし |

生入力・応答・hashは[seed 2の7件対8件](../assets/research/shot-linkage-p1-2026-09-24/flower-candidate-added-seed2/manifest.json)、[seed 2の花1件](../assets/research/shot-linkage-p1-2026-09-24/flower-candidate-only-seed2/manifest.json)、[seed 3の7件対花1件](../assets/research/shot-linkage-p1-2026-09-24/flower-candidate-only-seed3/manifest.json)に保存した。保存済み旧応答と同seedの再推論も細部が異なるため、判定は同一実行の対照を優先する。候補だけにするとseed 2では歌詞のあるShot 2へ移ったが、seed 3では候補なしもShot 2だった。**この二seedでは候補追加だけで花を選ばせることはできず、候補数の多さだけを原因とする説明も支持されない。** 8Bが別seed・別文面なら花を選ぶ可能性まで否定しない。

ここで直接変更したのはScene Eventへの候補欄であり、Direction Enhancerへユーザー文を入力して候補を選別する全経路のE2E試験ではない。しかし、後段に届いた花候補を8Bがどう使うかは検証できる。`# 演出候補`は仕様上も任意の着想であって必須命令ではない。花を**必ず**映す必要がある場合には、Template EMDの対象Shotに``* `演出` 参道脇の花が一度咲き、花びらが風を受けて揺れる。``を作者指示として記述する既存経路がある。`tests/test_scene_author.py`は作者の`演出`を固定し、Event生成をスキップすることを検証している。ただしこれはユーザーが当該Shotを選ぶ方式であり、8Bの自動選択が改善した証拠ではない。

### 「歌詞の一節」ではなく「花という単語」をトリガーにする

ユーザーの指摘に従い、候補の冒頭だけを`歌詞「人は花より」「短く咲いて」を扱うSceneで`から`単語「花」が現れるSceneで`へ変更した。[変更後の候補](../assets/research/shot-linkage-p1-2026-09-24/flower-word-trigger-candidate.txt)のそれ以降の演出本文、保存済みScene Event入力、P1b v2 System Prompt、モデル、推論設定は同じである。既存7件に追加した条件と、花候補1件だけの条件を実8Bで比較した。

| 実効seed | 候補条件 | 8B Event応答 |
|---|---|---|
| 2 | 元の7件＋単語トリガー1件 | `SHOT=2｜紅葉した木々の一枚が風に揺れて、葉が舞い上がる` |
| 2 | 単語トリガー1件だけ | `SHOT=2｜紅葉の木々から落ちる紅葉が、狐巫女の足元に積もる` |
| 3 | 単語トリガー1件だけ | `SHOT=2｜紅葉した木々の一枚が風に揺れて、地へ落ちる` |

生応答は[追加8件・seed 2](../assets/research/shot-linkage-p1-2026-09-24/flower-word-added-seed2/manifest.json)、[単独・seed 2](../assets/research/shot-linkage-p1-2026-09-24/flower-word-only-seed2/manifest.json)、[単独・seed 3](../assets/research/shot-linkage-p1-2026-09-24/flower-word-only-seed3/manifest.json)に保存した。単語トリガーの三応答はいずれも歌詞のあるShot 2を選んだが、花は一度も選ばなかった。以前の「歌詞の一節」候補と同seedでも自然文は揺れており、Shot位置の変化を語句変更の因果効果と断定しない。少なくとも**この局所比較ではトリガーを単語へ短縮しても対象欠落は解消しない**。任意候補の文言を増やす前に、Eventに求める対象採用の設計と、作者固定指示との差を検討する必要がある。
