# 新曲の身体演技 P0–P3 検証結果

作成日: 2026-09-22
前提調査: [新曲の身体振付不足](new-song-motion-choreography-review-2026-09-22.md)

## 実装した範囲

- P0: `dance_phrase`で非顔Shotの`performance_role`を一律`continuous_upper_body_phrase`へ上書きしていた処理を、`anime_emotional_mv`に限り解除した。比較用の`anime_story_mv`は従来の割当を保持する。
- P1: Motion profile metadataに`body_accent_policy=off|sparse_chorus`を追加した。開発用の`anime_emotional_mv`だけ`sparse_chorus`とし、サビ／最終サビの適格なSceneから最大一Shotを`body_phrase_accent`に指定した。歌詞対象を映すShotや顔Shotは優先しない。Action本文はLLM出力をAS ISで採用し、後編集しない。
- 既存のAction監査へ`BODY_ACCENT_MISSING`を加えた。8Bが対象外Shotにもこの判定を返したため、当該理由は対象roleにだけ適用する。修復予算が尽きても既存の非停止方針どおりLLM候補を警告付きで残す。
- profile metadataをPlanner cache keyへ入れ、profileの切替で古い結果を再利用しない。

## P2: 同一楽曲・同一API入力のEMD比較

元の実行履歴から保存したComfyUI API promptを用い、22 Scene・36 Shotの全編を2回再生成した。モデル・入力ノード・seed設定は同じ。初回は監査のrole誤判定を含み、2回目はその修正後。Vision、Direction、Lyric Segmentation、Planner、Compilerは再実行されているため、LLM由来の差まで厳密に固定した単一因子試験ではない。

| EMD | 支持脚・踏み替え・重心・骨盤・膝・脚を明記するAction | 完全重複Actionに属するShot | 判定 |
|---|---:|---:|---|
| `context_loop_emd_00001.md`（元） | 0/36 | 6/36 | 比較元 |
| `context_loop_emd_00002.md`（実験1） | 1/36 | 8/36 | 不合格 |
| `context_loop_emd_00003.md`（実験2） | 1/36 | 8/36 | 不合格 |

EMDはすべて`C:\Software\ComfyUI\output\mv_director\`に保存された。

実験1と2では、身体動作の唯一の該当例も「膝を軽く揺らし、足先を地面につけたまま…足を軽く前へ進める」であり、支持脚→骨盤→体幹→腕の連鎖ではない。両実験とも「右手を腰に添え、目を閉じる」が4 Shotに反復し、鳥居の上部に立つ指示及び足袋を滑らせる指示が混入した。元のEMDにも動作不足はあるが、今回の実験出力を品質改善として採用できない。

Plannerは両実験とも`complete=yes`、22 Scene・36 Shot。初回のログは`repetition_warnings=69 (action=48)`、監査修正後は`64 (action=43)`だった。監査誤判定の削減は確認したが、採用Actionの反復と身体表現は改善しなかった。身体accentは`scene11:shot1`、`scene12:shot1`の2 Shotに選ばれたものの、その指定だけでは8Bが要求した身体フレーズを出力できず、既存の限定再要求でも改善しなかった。

## P3: 短区間H3比較

実施しない。P3はP2のEMDで身体演技の明確な改善が見られた場合だけ、28–36秒、84–92秒、124–132秒を同一モデル・seed・参照・ステップ数で比較する計画だった。今回はその前提を満たさず、動画に存在しない身体動作をH3で補わせる検証は時間とGPUを浪費する。全編H3も実行していない。

## 結論と次の実験

roleの多様化と疎なaccent指定だけでは、現行8Bの長いAction入力に対し十分な効果がない。監査LLMは対象外roleへ身体accent不足を誤適用し、対象roleでは再要求後も小さな手・顔動作を採用した。AS IS原則を守りつつ次に試すなら、選択済みの2 Shotだけについて、現在Sceneの歌詞・前Shot終端・必要な身体連鎖へ入力を絞った**既存Action再要求**を行い、LLM自身に別のActionを書かせる。成功判定は「支持脚／重心から体幹と腕へ至る時間順の動作が実際にEMDに残る」「反復Actionと不自然な足場が増えない」とする。この局所試験が通るまで、全曲への追加LLM stageや全編動画生成には進まない。

現状の`anime_emotional_mv`は開発用の未合格profileであり、`anime_story_mv`を比較用基準として保つ。検証後、ComfyUIの実行キューが空であることを確認してモデル解放を要求した。

## 次の実験の実施結果：対象2 Shotの局所Action再要求

上記の「次の実験」を実施した。選択済みの`scene11:shot1`と`scene12:shot1`だけ、現在Sceneの歌詞、作者本文、直前の身体状態・Action、必要なCue及び根拠句へ入力を縮小し、既存の`actions`を最大3回再要求した。候補は後編集せず、品質条件、支持→体幹→腕の構造条件、局所Action監査及び反復検査を通ったときだけ差し替えた。第3試行では出力文法でもこの順序を要求した。実モデルは元のComfyUI API graphと同じQwen3 8B GGUFを使用し、22 Scene・36 Shotの全編EMDまで生成した。上流のVision、Direction、Lyric Segmentationも再実行したため、厳密な単一因子比較ではない。

| EMD | 実験条件 | 支持・重心・膝等の語を含むAction | 支持＋体幹＋腕の語を含むAction | 完全重複Actionに属するShot | 鳥居上に立つAction |
|---|---|---:|---:|---:|---:|
| `_00001.md` | 元の出力 | 0/36 | 0/36 | 6/36 | 0 |
| `_00004.md` | 小入力・監査のみ | 1/36 | 0/36 | 7/36 | 1 |
| `_00005.md` | 小入力・構造採用条件 | 1/36 | 0/36 | 6/36 | 1 |
| `_00006.md` | 小入力・出力文法・構造採用条件 | 3/36 | 1/36 | 7/36 | 1 |

EMDは`C:\Software\ComfyUI\output\mv_director\context_loop_emd_00001.md`等に保存されている。第3試行では`scene11:shot1`の3候補がすべて`generic_hand_raise_or_lower`で不採用となり、元の「右手を腰に添え、目を閉じる」を保持した。`scene12:shot1`は一回目に形式上採用されたが、「首を戻したまま、目を開きながら体を前傾し膝を軽く曲げ、手は腰に添える。心地よい風を感じるような自然な動きで、歌詞のに左手を添える。足は軽く踏み出し、体幹を前へ向けながら、胸をやさしく揺らす。」となった。支持・体幹・手の語はあるものの、文法破綻、前傾・腰に手を添える旧パターン、左右腕の経路不明があり、求める身体演技ではない。監査の`PASS`は画としての品質を保証していない。

第3試行はPlannerとCompilerまで正常完了したが、EMD品質の合格条件を満たさない。文法は指定語の出現順を保証できても、空間的に一貫した振付や自然な日本語、前後Shotとの演技連続性は保証できない。語彙の機械的な増加を改善と誤認してH3を全編生成することはしない。局所再要求、専用prompt、文法及び採用条件は実装から撤回し、P0–P3の開発用`anime_emotional_mv`と比較用`anime_story_mv`だけを残した。Planner cacheのalgorithm versionは撤回後の内容へ更新した。

次はShot単位の語彙制約を積み増さず、**一つのSceneの始点姿勢、重心・体幹・腕の進行、終端姿勢を一回で計画し、その連続した動きを既存Shot枠へ割り当てられるか**を小範囲で検証する。まずScene 11–12の固定済み歌詞・Scene構造・Cueだけを入力するオフライン実験とし、8Bの出力を元のAction及びプロトタイプの相当箇所と比較する。新たな全曲LLM段階やPythonによる自然文修復は先に導入しない。自然で重複しない身体連鎖がEMD上で示されるまでH3比較へ進まない。
