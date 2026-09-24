# 簡潔なH3 Camera文のパイプライン化 P0（2026-09-24）

## 目的と範囲

[手動Plan A/B](audio-reference-compact-tree-fire-stability-2026-09-24.md)では、狐火・御神木の簡潔版がユーザーの総合評価で優位だった。元のEMDを変更せず、完成JSONの局所文を手で置換したため、この比較だけでは本番パイプラインの再現性を証明しない。P0はそのうち**Cameraの長文展開だけ**を、既存のPlanner→EMD→Compiler→Plan経路へ移す。

## 実装

- Camera profileに`camera_render_style=detailed|compact`を追加した。省略時は従来の`detailed`。当初は開発用`anime_emotional_mv`に`compact`を明示したが、下記H3比較で御神木の不自然な揺れが見つかったため既定へは昇格せず、付属profileはすべて`detailed`へ戻した。`compact`はカスタムprofileで明示した場合のみ使える。
- LLMが選ぶ有限Cameraレコード、Camera幾何の接続、Arc方向、Roll割当、coverage及びActionは変えない。`core/planner/engine.py`の最終直列化で、開始・終端の画角と視点、Motion、経路、可視対象を短い英文にする。Cameraの内部監査と候補の重複判定は従来の有限値・詳細文を使用する。
- 元EMDの作者Action、歌詞、Scene概要及び自由文Cameraは短縮しない。Compilerは従来どおりEMDを翻訳・組立てする。追加LLM呼出し、正規表現での事後書換え、完成JSONパッチは導入しない。
- profile metadataとPlanner algorithm versionを更新し、旧cacheが新しいCamera文を隠さないようにした。INFOには`Camera render style=compact`を出す。

## CPUで確認したこと

`test_camera_continuity.py`でprofileの省略値／不正値と、Arc＋Rollの簡潔直列化を確認した。`test_timeline_planner.py`ではFakePlannerBackendが選んだ有限Cameraを試験内で`compact`指定し、Planner→EMD→Compiler→Planまで届くことを確認した。元の`detailed` rendererと付属profileの既定値は維持する。

保存済み元Plan（SHA-256 `3dce5133ab8f42aa12e2762439793fb4ed08863c99ce48689f8d3eeb1035eda9`）から、[研究用スクリプト](../assets/research/audio-reference-body-isolation-2026-09-24/build_camera_only_compact_plan.py)でScene 6・9の**有限Camera部分だけ**をproductionのcompact rendererに通した[Camera-only比較Plan](../assets/research/audio-reference-body-isolation-2026-09-24/camera-only-compact-scene6-9-plan.json)を作った（SHA-256 `ed11a24465f655c020ddda37eb0815c336a331df23381cc3756ba5715449466c`）。Action、Scene概要、前Scene、音声、seed、参照、全域promptは元Planのままである。Scene 6の対象Shotは1,000→588文字、Scene 9の二Shot合計は1,354→833文字となった。

これは手動の簡潔版とは異なり、Scene 6の元Actionにある「葉が御神木を追う」ように読める英訳の曖昧さも残す。Camera文だけ短くしても、対象の動作と人物の反応の時間関係が自動的に直るわけではない。この差を明示した上でH3を比較する。

このCPU試験は実8Bによる全曲生成でも、H3によるCamera-onlyの画質比較でもない。手動A/BではScene概要とActionも短くしたため、P0だけで御神木・狐火の優位性を再現できると断定しない。

ComfyUIのvenvによる全件実行は573件すべて通過した。システムPythonでは`llama_cpp`が無いため、同じテスト群の文法コンパイル5件が依存不足でエラーになる。

## Camera-only短区間H3比較

保存済み元Planと上記Camera-only比較Planを使い、同じH3 graph・seed・参照・音声で御神木Scene 5–6と狐火Scene 8–9を生成した。変更対象はScene 6・9の有限Camera文だけで、Scene概要・Action・作者prompt・前Sceneは保持した。両組とも前Scene Guideは243フレームでSSIM 1.000となり、対象Sceneの入力Guideが一致している。SSIMは前Scene一致の検査にだけ使い、作品の良し悪しを数値で決めない。

| 対象 | 基準版 | Camera-only簡潔版 | ユーザーの連続視聴評価 |
| --- | --- | --- | --- |
| 御神木 | [Scene 6](<C:/Software/ComfyUI/output/h3_chains/audio_ref_tree_s5_6_base_20260924/segments/clip_0002.4293b91780604c14809ff17a72b36edc.mp4>) | [Scene 6](<C:/Software/ComfyUI/output/h3_chains/audio_ref_tree_s5_6_camera_only_20260924/segments/clip_0002.e40a2eda501c4fc78b1a0e06f058d77a.mp4>) | **Camera-only簡潔版では御神木が左右にデフォルメして動き、コミカル過ぎて本MVには不向き**。 |
| 狐火 | [Scene 9](<C:/Software/ComfyUI/output/h3_chains/audio_ref_fire_s8_9_base_20260924/segments/clip_0002.94563a301a484b0a91c72e30509f9686.mp4>) | [Scene 9](<C:/Software/ComfyUI/output/h3_chains/audio_ref_fire_s8_9_camera_only_20260924/segments/clip_0002.fc9c3b35c78643dd9a20d0739ccc814b.mp4>) | **双方に良さがある**。基準版では狐火が人物の手から、Camera-only簡潔版では宙から現れるように見え、どちらも演出として成立する。 |

御神木の一秒間隔フレームでは、Camera-only版は冒頭の人物と木をやや大きく示し、終盤は参道と木を正面寄りに見せる。基準版にも似た構図はあるが、木の不自然な左右運動は静止フレームだけで判定できず、上記ユーザーの連続視聴評価を優先する。狐火のCamera-only版では、基準版より人物に近い構図で火と両手が見える時間がある。ただし火の発生源の違いを**Camera文だけの決定論的効果**とは断定しない。同一seed等を固定した一回ずつの生成比較であり、再現性の統計試験ではない。

## 判定と次の一手

P0の「有限Cameraだけを短くする」実装は接続・互換性の面では成立したが、[手書き簡潔版](audio-reference-compact-tree-fire-stability-2026-09-24.md)の御神木の良さを再現しなかった。手書き版はScene概要とActionも同時に変更しており、人物が腕を広げて葉が舞う因果関係をより明瞭にした。今回の比較から、それらのどちらが主因かはまだ分離できない。Cameraの簡潔化だけを全域へ適用しない。

次に試すなら、元の歌詞対象と場所、対象の変化、人物の一つの反応、Cameraが同時に映す関係を**一Sceneの短い映像仕様として**8Bに作らせる。まず保存済みScene 6・9だけで、元の有限Camera・元Actionを維持したままScene概要の短文化、次にScene概要＋Actionの組合せを個別に比較し、手書き版の利点がどこにあるか切り分ける。追加の全曲LLM段や作者EMDの事後書換えは行わず、作者指定があるfieldを優先する。8B出力とH3の短区間A/Bで、御神木の過剰な変形、狐火の人物・effect・Cameraの連携を人が判定する。共通前Sceneの足運びは別課題であり、Shotに移動又はその場の演技のどちらかを局所的に指定する比較を先に行う。全域の歩行禁止にはしない。
