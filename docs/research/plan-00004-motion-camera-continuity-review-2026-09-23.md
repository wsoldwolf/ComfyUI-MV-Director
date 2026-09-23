# Plan 00004：身体演技・Camera同期・56秒の継続段差

2026-09-23

## 対象と判定範囲

`C:\Software\ComfyUI\output\mv_director\context_loop_plan_00004.txt`と同時刻の`context_loop_emd_00004.md`を照合した。実動画は確認していないため、以下は**生成指示の評価**であり、H3が実際にどう動かしたかの断定ではない。Planの`length`には継続時の重複context 22 frameが含まれる。Scene境界の時刻は単純な`length`累積ではなくEMDのタイムラインを使う。

## 結論

大樹の根元の苔という場所はScene 3に出た。ただし、接触を歌詞「苔へと還る」より先のShotへ置き、次Shotで再び手を出すため、出来事の時間順が逆転している。身体演技は肩・胸郭・腕の似たフレーズが複数Sceneへ再登場し、CameraはArcの数こそ多いが演技の見せ場と必ずしも結び付いていない。00:56.167の段差は、Scene 7が実際にCUTでコンパイルされ、前Sceneの映像・音声contextを受け取らないことが直接原因である。

### 定量確認

| 項目 | Plan/EMDで確認した値 | 読み方 |
| --- | ---: | --- |
| Scene / Shot | 16 / 29 | Scene内のShotは硬い編集点とは限らない |
| Scene境界 | 初回CUT、以降CONTINUE 12・CUT 3 | CUTはScene 7、10、12の開始 |
| Camera Motion | Arc 16、Push In 5、Zoom In 4、Pan 3、Truck 1 | Arc不足ではなく使い方が課題 |
| Arc方向 | 左16、右0 | 右Arcも実装上は選択可能。今回の出力は左に偏った |
| Arc＋Roll | 5 | 傾きの追加だけでは演技と同期しない |
| `full-body`を明示するCamera | 2/29 Shot | 全身の荷重・足運びを見せる枠が少ない。`medium-wide`等は別扱い |

## 主要な証拠

1. **Scene 3：苔は具現化したが、行為の前後が逆。** EMD 00:20.042のShotは「大樹の根元の苔を指先で撫でる」とし、00:24.667の次Shotが「右手を軽く前へ出す」に戻る。歌詞「苔へと還る」は00:25.380–00:26.680である。接触が歌詞より約5秒先行し、Cameraも接触Shotでは一般的な対象coverageのPush In、次Shotになって初めて「対象と手を同時に見せる」Arcを指定する。大樹・苔という名詞の採用は成功したが、接近→接触→解放と撮影の順序は未達。
2. **Scene 4–6：似た身体フレーズを再使用。** Scene 4の二Shot（00:29.250、00:34.208）は片腕を斜め上、反対腕を低く通し、両腕を体側へ落として終える動きがほぼ重なる。Scene 6（00:48.375）にも胸郭を横へ送る同型の経路と同じ終端が現れる。Scene 5の二Shot（00:39.167、00:43.458）も胸を横へ送り、両腕を落とす動きを反復する。Scene 4の最初のCameraは終端が背面寄りの全身構図なのに、Actionは「顔と歌唱口が見える瞬間」を見せ場にしており、可視範囲が衝突する。
3. **Scene 6→7：00:56.167で実際のCUT。** Scene 6（00:48.375–00:56.167）はCONTINUE、左Arc＋Rollで中景の側面から前斜めへ移り、腕を体側へ収める。Scene 7の見出しには`継続`がなく、Planの`scene_0007`には`continuation_mode`がなく`context_length=0`、`audio_context_length=0`である。直前のScene 6は両方22で`continuation_mode=guide`。`generated_continuity=off`はリップシンク音響側で全Sceneに付く値なので、この判定には使わない。Scene 7は再び左Arcの中景・側面から始まり、人物が唐突に「千年鳥居の上」にいる指示へ飛ぶ。映像の段差と空間の段差が重なる。
4. **CUTが歌詞の節切替より早い。** Scene 7の開始00:56.167ではPRE-CHORUSの「ただ葉を鳴らすだけ」が続き、CHORUS「千年鳥居を」の開始は00:59.700。新しい節の冒頭はScene境界より約3.5秒後である。Shot-layout入力はScene内の`first_section_appearance`と`section_entry_shot_index`を持つが、システムプロンプトは前者が真ならCUTを要求する。Scene内の後半で新節が始まる場合にも、Scene冒頭のCUTへ引っ張る設計である可能性が高い。保存PlanだけではLLM初回出力・再試行・layout parse fallbackのいずれが最終決定したかは特定できない。ただし`anime_emotional_mv`の境界修復はCUTをCONTINUEへ変えるだけで、CONTINUEをCUTへは変えない。
5. **Scene単位の候補選択が出来事と振付を競合させる。** 現行のstaging-selectionは一Sceneにつき一候補又はNONEだけを返す。今回の入力に苔の出来事候補と汎用身体フレーズ候補を同時に並べても、同じSceneで両方を選択できない。苔Sceneで場所と接触が採用されても、別候補の身体経路はそのSceneには選ばれない。この制約は、ユーザーの求める「対象の出来事＋身体の演技＋Camera」の一体化を妨げる一因である。ただし他の共通Motion指示やLLM独自の振付は残るため、唯一の原因とは断定しない。
6. **Cameraの頻度と演技の撮影適合は別。** 29 Shot中16 ShotがArcで、すべて同じ左方向・大振幅・高速・60–120度の型を使う。Cameraが派手に動いても、Actionが肩の静止や腕の収束なら運動のアクセントを増やさない。Scene 11（01:33.417）では「石畳を触れて歩き出す」Actionを顔close-upから中景へのArcで撮り、触れる手・石畳・全身移動を同時に読ませるには厳しい。Cameraへの前後Action伝達は既にあるが、最終選択の可視性が不足している。

## 改善順位と低コスト検証

| 優先 | 改善案 | オフライン合格条件 |
| --- | --- | --- |
| P0 | Shot-layoutの「`first_section_appearance`ならScene CUT」を、**節の初出がScene冒頭にある場合**へ限定する。Scene中途の節転換は内部Shotの演出的アクセントとして扱い、Scene 6→7の継続可否は前後の歌詞・身体・Camera経路で再判断する。Pythonが完成Action/Cameraの自然文を修復しない。 | 00:56.167はCONTINUE、節の見せ場は00:59.700付近の内部Shotで成立。Scene 10/12の意図的なCUTは保持 |
| P1 | Scene 3の既存二Shotで、先に大樹と根元の苔・人物の位置を示し、歌詞時点の後Shotで手と苔の接触・解放・顔反応へ進める。ActionとCameraの局所的な生成・監査入力に歌詞発話時刻と前Shot完了状態を明示する。 | 接触が歌詞より不自然に先行せず、手と対象が接触瞬間に同じ画角へ入る。次Shotが準備姿勢へ戻らない |
| P1 | 演出候補の選択を一Scene一件でよいか小範囲で再評価する。候補を「出来事」と「身体」にLLM自身が分けて各最大一件選ぶ一行応答などを、Scene 3・4だけで比較する。候補の全文は下流へ一括注入しない。 | 苔の場所・接触と、独立した身体フレーズの両立をEMDに示す。対象を他Sceneへ流用せず、8Bの形式違反や時間増が許容範囲 |
| P2 | CameraはArc件数を増やすのでなく、身体accentでは支持脚・体幹・両腕の見えるscale、接触時は手＋対象、解放時は顔、という撮影目的との整合を確認する。左Arc一辺倒も維持すべき物理連続区間と新CUTを分けて評価する。 | 代表Sceneの一連の動きがCameraから見え、顔・手・対象の必要coverageがShotごとに適切。旋回方向の急反転なし |

P0は既存のScene/Shot境界と歌詞だけで再現でき、H3なしで検証できる。P1の候補二系統化は8Bの追加負担とプロトコル不安定化を招く恐れがあるため、まず保存されたScene 3・4の小範囲比較に留める。全編H3生成は、EMD上で苔の出来事の時間順、Scene 6→7の継続、身体accentとCamera coverageが改善した後に一回実施する。

## 改善実装の進捗（2026-09-23）

P0として、Shot-layoutへ新節の実際の歌詞開始時刻と`new_section_at_scene_start`を渡した。Scene中途に新節が現れる場合はScene冒頭のCUTを要求せず、内部Shotで節の転換を表すようシステムプロンプトを変更した。CONTINUEの既存の身体・Camera状態を優先し、独立した演出的理由があるCUTまで禁止しない。Scene 7に相当する時刻配置の回帰テストを追加した。

P1として、歌詞の`start_ms`/`end_ms`とShot時間をScene Spine、Action、Cameraへ渡した。Scene Spineに、対象の発話前は準備、発話時は一回の接触又は変化、その後は解放・反応という順序を求める。`# 演出候補`に対象の出来事と身体フレーズが両方ある場合、対象候補をVisual Beatへ、追加で選んだ身体候補をScene SpineとActionへ渡す。自然文はPythonで書き換えない。候補追加選択には該当Sceneあたり一段の小さなLLM要求が増え、形式違反時は一度だけ再要求する。

P2として、Cameraには接触中の手と対象、身体accent中の全身、反応時の顔という撮影目的を明示した。`whole_body_emotion`又は`whole_body_hands`のSpine coverageを指定したShotは、少なくとも開始又は終了scaleに`wide`、`medium_wide`、`full_body`のいずれかを必要とする。CUT後は新しい配置からArc方向を選べる一方、CONTINUE中の急反転を避ける指示を加えた。

これらは入力契約とCPU回帰テストの改善であり、保存Planを8Bで再生成した結果やH3動画の改善をまだ証明しない。次の確認では同じ歌詞・音源・参照でPlan/EMDを生成し、Scene 3の苔の時間順、Scene 6→7の境界、身体accentの画角を先に比較する。全編H3はその後の一回に絞る。
