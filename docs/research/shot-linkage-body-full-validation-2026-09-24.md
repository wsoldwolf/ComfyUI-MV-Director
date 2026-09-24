# Shot接続・全身演技の全編H3検証

2026-09-24。P0で出典を確定した16 SceneのPlanに対し、Scene 3・4・9のAction/Cameraだけを手作業で差し替えた比較である。これは**8B Plannerの生成結果でも本番Compilerの出力でもない**。H3がScene内の身体連鎖とカメラの接続を描けるかを先に検証する、到達目標のサンプルとして扱う。

## 固定条件と生成物

- 元EMD: `C:\Software\ComfyUI\output\mv_director-5\context_loop_emd_00001.md` (SHA-256 `46894F43A2ACD92033076DAF081D9FEAD43CF02E36BB1F4BB39FB1C5117A0B77`)。
- 元Plan: `C:\Software\ComfyUI\output\mv_director-5\context_loop_plan_00001.txt` (SHA-256 `7A1B6307B89FC0CBFEDFC2C923EA13D7109D8A4928BDE9880A05DF771EB26EC5`)。
- [差し替え原文](../assets/research/shot-linkage-body-2026-09-24/treatment.json)、[候補EMD](../assets/research/shot-linkage-body-2026-09-24/candidate/candidate_emd.md)、[候補Plan](../assets/research/shot-linkage-body-2026-09-24/candidate/candidate_plan.json)。候補PlanのSHA-256は`caba5eaf26ee41eeed45305bd4b422c05b13d7c02c9924122a0c217cf5c43398`。
- 元動画: `C:\Software\ComfyUI\output\h3_chains\mv_director_context_loop-6\final\t2v_normal_2026-09-23.mp4`。16 Scene、139.667秒。参照画像、音声、H3設定、各Sceneのseed、8 stepは元動画の埋め込みメタデータから引き継いだ。
- 全編候補: `C:\Software\ComfyUI\output\h3_chains\shotlink-body-full-20260924\final\shotlink-body-full-20260924.mp4` (SHA-256 `163F3BEA9DA5CEA0BD0291A9C5DE16291F45B9B0173467DDDA3FEF1FA8A52D3A`)。16クリップ、3352フレーム、24 fps、864×480、139.667秒、H.264/AAC。元動画と尺が一致する。

## 中間映像と人による判定

全編前にScene 3→4とScene 9を短区間で生成した。ユーザーはScene 3→4の全身演技を「大分良い」と評価し、花が参道中央にある違和感はあるが、当初の機械的な合否条件は厳しすぎる可能性を指摘した。そこで**花の配置を記録すべき改善点とし、全編生成の停止条件にはしなかった**。以後も長時間の全編生成前に短区間の動画と観察点を示し、人が演出の良否を判定できる時点を設ける。

## 映像比較

| 対象 | 元動画 | 全編候補 | 判定 |
|---|---|---|---|
| Scene 3→4 | 顔・手の近接構図が長く、骨盤・脚・両腕の移り変わりが読みづらい | 全身の荷重・腕の位置変化が見える。Scene 3末尾とScene 4冒頭は人物位置、閉眼、腕の低い姿勢が視覚的につながる | 目的の身体演技とScene接続は改善。苔への手の接触の明瞭さはなお不足 |
| Scene 4の花 | 花が演技の主対象として十分に立たない | 花は見えるが参道中央へ寄る | 対象は可視化されたが、環境内の位置は不自然。短区間時点でユーザーも確認済み |
| Scene 9の狐火 | 人物の身体演技より顔寄りが主で、effectの空間上の移動が限定的 | 全身構図で大きな狐火の旋回が生じ、その後顔アップへ移る | 身体とeffectの連携は改善。ただし人物が一度背を向ける動きは調整候補 |

[元動画の全編コンタクトシート](../assets/research/shot-linkage-body-2026-09-24/baseline-full-contact.jpg)と[候補の同時刻シート](../assets/research/shot-linkage-body-2026-09-24/full-contact.jpg)は7秒ごとのサンプルであり、動きの質やカット境界の最終判定は動画で行う。[Scene 3末尾](../assets/research/shot-linkage-body-2026-09-24/full-scene3-end.jpg)と[Scene 4冒頭](../assets/research/shot-linkage-body-2026-09-24/full-scene4-start.jpg)は境界確認の静止フレームである。非対象SceneのPlanは不変だが、生成結果は先行Sceneの文脈を受けるため画素単位の同一性までは主張しない。

## レンダリングの停滞と再開

最初の全編投入は`between_scene_cleanup=off`のままScene 1〜3を保存し、Scene 4で約6分以上ログの`1/8`表示が更新されなかった。中断直後のログは`2/8`、平均`503.56 s/it`を示した。VRAMは約30.8/31.8 GiB、プロセスのRAM使用も約73 GiBだった。単なる進捗表示の問題ではなく、Scene間で状態を保持したまま計算速度が極端に落ちたと判断した。原因を単一要素へ確定したものではない。

自分が起動したComfyUIを停止して再起動し、[再開投入の記録](../assets/research/shot-linkage-body-2026-09-24/submission-full-resume.json)で同じrun nameとPlanの`start_clip=4`を指定した。Context Loopの既存チェックポイント検証を有効のまま使い、`between_scene_cleanup=fresh_scene`を適用した。Scene 4は約`9.8 s/it`、以後もおおむね`8〜11 s/it`で最後まで完了した。保存済み3 Sceneを作り直していない。再開側の実行時間は21分7秒。比較ツールには`--start-clip`と`--between-scene-cleanup`を追加した。

## 結論と次の境界

この比較は、同じH3条件で**身体の始点・重心移動・腕・視線・終点を一つのSceneとして指示すると、元動画より読める全身演技とeffect連携が得られる**ことを示した。一方、手作業で書いた候補が実8B Plannerから自動生成できる証拠ではなく、花の配置も未解決である。次段ではこの3 Sceneの原文と映像を目標例として、ユーザー指示を優先しつつ、Plannerがどの情報を落としたかを狭い範囲で照合する。花の位置や人物の回転のような演出判断は、即時の機械的失格ではなく、途中動画を見た人の評価とともに扱う。
