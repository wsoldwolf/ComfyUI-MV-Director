# モーションテンプレート入力：実装前の低コスト検証

2026-09-22

## 状態

入力・キャッシュのCPU試験、保存済みtraceの再現、8Bによる直接投入・Scene単位の選択適応・Cue身体指定の切り分け試験を完了した。**候補をそのまま渡す案も、選択適応callを加える案も、現条件で期待する身体演技と歌詞上の出来事を安定して両立できなかった。** Cueの身体指定を実験上で除くと候補は効くが、接触や狐火の出来事が抜ける。本番Planner、EMD仕様、ワークフローは変更していない。

## 検証対象と再現条件

提案形式の[モーションテンプレート断片](../assets/research/motion-template-input-probe-2026-09-22/motion_templates.emd.md)を使用した。意味付きIDを持たない`# モーションテンプレート`の2箇条で、各行を一候補として保持する。[オフライン比較スクリプト](../../tools/offline_motion_template_input_probe.py)は本番Plannerを改変せず、[既存の全編試験trace](../assets/research/choreography-full-run-v4-2026-09-22/evidence.json)から入力を固定した。モデルは同試験と同じQwen3-8B-Abliterated Q4_K_M、seed 42及び43、`n_ctx=16384`、Scene Spine/Actionの最大出力512 tokenとした。H3動画、Vision、Direction、歌詞解析、全曲Plannerは再実行していない。

Scene Spineは、接触対象を伴うScene 2・11、感情・外部現象を扱うScene 5・14を使用する。単一Shotの経路はScene 16のAction入力を切り出して検証する。比較は候補なし、既存palette、2件のユーザー候補をScene局所の着想として渡す案の三条件とし、同じ歌詞・Cue・Shot枠・seedで行う。既存paletteのScene Spine応答は保存済み本番traceを利用し、重複推論を節約する。Scene 16のActionは三条件を新規推論する。

## CPU検証結果

- 実験用パーサーは、未接続相当の空文字と見出しのみを空配列にし、1件以上の候補を原文順で保持した。BOM、CRLF、空行を扱い、壊れた見出し・箇条書き・空候補は明示的に拒否した。`unittest` 4件が通過した。
- 候補本文の変更は`build_cache_key`の結果を変え、CRLFとLFだけの違いは同一キーになった。これは**実験用の入力契約**の確認であり、本番Plannerの新socketとcache keyはまだ実装されていない。
- 保存済みtraceから対象4 SceneとScene 16単一Shotの入力を再現できた。4 Sceneの保存済みpalette応答は、LLM行プロトコルとScene Spineの構造検証をいずれも通過した。これは**形式上の成功**で、身体演技の品質や空間的な自然さを意味しない。
- 二つの実験スクリプトは構文検査を通過した。新規4件を含むリポジトリ全体の`unittest` 460件が通過した。

## 8B小範囲比較

[seed 42の全応答](../assets/research/motion-template-input-probe-2026-09-22/run-seed42/evidence.json)と[seed 43の全応答](../assets/research/motion-template-input-probe-2026-09-22/run-seed43/evidence.json)を保存した。4 Scene×三条件×2 seedと単一Shot×三条件×2 seedの計30応答はすべて行プロトコル・既存構造検証に成功した。うち4応答は保存済みpalette traceの再利用で、新規26呼出しの推論時間合計は76.59秒（モデル読込を除く）。形式上の成功と創作品質は別である。

| 対象 | ユーザー候補を直接渡した場合の観察 |
| --- | --- |
| Scene 2、鳥居 | 両seedとも、右手を上げて鳥居を押す既存Cueの経路が中心。支持・骨盤・胸郭・左右の腕という候補の身体連鎖は出ない。Cue自体が「鳥居の上部」と不自然な接触位置を指定しており、これは候補方式だけの責任ではない。 |
| Scene 5、古傷 | 両seedとも、左胸を押し右手を腰に添えるCue主導の身振りと発光。候補から新しい身体経路を展開できていない。歌詞由来の発光そのものを失敗とは数えない。 |
| Scene 11、社 | 両seedで肩・腕のCue動作を前後Shotにほぼ反復し、候補で期待した始点→アクセント→終端の差が弱い。生成文には文字列の崩れもある。 |
| Scene 14、狐火 | 肩を軽く動かし、狐火が上がる／消える記述が中心。人物の全身表現は増えない。Cueの「狐火の上部」という配置も不自然で、候補だけでは修正されない。 |
| Scene 16、単一Shot | ユーザー候補ありのActionは、両seedとも候補なしのActionと**完全に同文**。既存paletteはseed 42で候補文に近い動きを増やしたが、seed 43では候補なしと同文。 |

対象SceneのCue `body_driver`には、右手で鳥居を押す、胸を押し腰に手を添える、肩を前に出し腕を振る、肩を軽く振る、といった具体動作が既に入っている。候補が単なる任意の追加文脈として渡されると、この既定動作が優先されることが今回の**有力な推定**である。ただし小標本なので因果を断定できない。現行paletteも候補を渡しており、形式成功にもかかわらず空間的な不自然さと反復が残る。候補の件数を増やすだけでは解決しない。

## 追加のScene選択・適応呼出し案

直接投入案が改善しなかったため、候補をSceneごとにLLMが選択・適応して短い`scene_motion_brief`を作り、それだけをScene Spineへ渡す[追加実験スクリプト](../../tools/offline_motion_template_selection_probe.py)を試した。形式的な候補IDの強制選択ではなく、独自生成も許す。初回は8Bが`MOTION　実TAB　...`と文字列そのものを返して転送形式に失敗した。**構造だけ**を固定するgrammarを加え、[Scene 11・14、seed 42・43の4応答](../assets/research/motion-template-input-probe-2026-09-22/selection-seeds42-43-scenes11-14/evidence.json)を得た。全4件でbriefと後段Scene Spineの形式は成立した。8回の新規LLM呼出しは合計30.31秒（モデル読込を除く）で、同じ4件の直接投入4呼出し約14.64秒より重い。

Scene 11では両seedともCueの肩・腕動作をbriefで再掲し、後段では接触を映す`SHOW=lyric_target_hands`なのに、`ADVANCE`は足を進めるか肩・腕を振るだけで、対象への接触を描いていない。Scene 14では一方のseedで狐火が上がる出来事を保持したが、もう一方は候補由来の手差し出しがeventになり、狐火の可視変化が消えた。どちらも既存の**構造**検証は通る。追加callで候補由来の身振りは増え得るものの、現8B・現Cueでは歌詞イベントを置き換える危険がある。今回の2 Sceneから全曲品質を断定はできないが、追加callの一律導入を支持する結果ではない。

なお最初の追加実験時だけGPUが32,464/32,607 MiB使用中でGGUFを読み込めなかった。後にVRAMが解放されたため、上記の比較は実施できた。占有プロセスを終了・再起動していない。

なお、以前の有限ID選択`scene_choice`は16 Sceneすべてで`quiet_refrain`へ偏った。新しい自由生成つきの選択・適応案と同一ではないが、8Bでの選択バイアスと追加call費用の懸念材料である。[既存の全編試験](choreography-operational-full-run-2026-09-22.md)参照。

## Cue身体指定の切り分け

因果を確かめるため、**保存済み入力の実験コピーだけ**でCueの`body_driver`と`final_state`を空にし、他の歌詞、対象、接触、Shot枠を保持した。[seed 42](../assets/research/motion-template-input-probe-2026-09-22/cue-body-ablation-seed42/evidence.json)と[seed 43](../assets/research/motion-template-input-probe-2026-09-22/cue-body-ablation-seed43/evidence.json)の各2 Scene×三条件、計12応答は構造上すべて有効だった。ユーザー候補を与えたScene 11では両seedで「骨盤に遅れる胸郭」「低い手を弧状に差し出す」という候補由来の連鎖が明瞭に出た。これはCueの具体的な身体文が候補の反映を弱めているという推定を強める。

ただし、Scene 11では対象への物理接触そのものが消え、Scene 14では狐火の上昇が手の身振りに置き換わった。`SHOW`欄だけは接触・顔のcoverageとして正しくても、自然文が必要な出来事を実行していない。**Cue身体文を単純に削除する案も採用できない。**

## 判定と次の最小手

入力形式とキャッシュ契約は実装可能。しかし現在の8B・Planner構造では、候補の直接投入にも追加選択callにも、全曲へ採用する根拠がない。候補の反映と歌詞イベントの保持が競合している。次に設計するなら、Cueの**出来事・対象・接触・可視結果**と、LLMが選ぶ**身体の支持・体幹・腕・顔の経路**を役割として分け、同一Sceneで両方を満たす小範囲のPlanを先に作る。Cue身体文を削る、候補を強制選択する、Pythonが自然文を書き換える、という近道は今回の結果に合わない。将来モデルを制限しないため、選択や創作の意味判断はLLMに残し、Pythonは構造と出典の検査に限定する。

この検証はPlanner文面のみで、H3による動作・カメラの映像品質は判定していない。
