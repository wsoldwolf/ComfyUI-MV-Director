# 振付プロファイルの運用昇格と全編Plan試験

2026-09-22

## 設計判断

`anime_choreography_mv`を`profiles/motion/`へ移し、Motion profileとして選択可能にした。既定の`anime_emotional_mv`及び`anime_story_mv`には適用しない。UI項目は増やさず、profile metadataの`choreography_policy scene_palette`がある場合だけ振付候補をPlannerへ渡す。候補は身体経路の着想であり、選択、逐語的再現、均等な採用及び反復禁止を要求しない。Scene SpineとActionは候補にない独自演技も作れる。PythonはActionの自然文を合成・置換・修復しない。

最初の全編試験ではSceneごとに有限IDを選ぶ`scene_choice`を用いたが、16 Sceneすべてが`quiet_refrain`へ偏った。直前IDの機械的除外では表現を強制的に散らすだけで、歌詞適合を保証しない。そこで運用profileを`scene_palette`へ変更した。選択callは不要になり、追加LLM段階は0である。`scene_choice`は別profileが明示する場合の選択肢として残す。

また、歌詞を解釈したPlannerがEMD Shotへ明示した可視演出と、Style/Compilerの「作者のみが指定できる」という禁止が競合していた。歌詞文字列だけから身体損傷を自動追加しない方針は維持しつつ、完成EMDのShotに明示された演出を下流で尊重するようにした。傷の発光等を機械的に削除・書換えしない。

## 検証条件

保存済み`C:\Software\ComfyUI\output\mv_director\context_loop_emd_00001.md`から、Subject、Scene設定、元の歌詞とScene/Shot時刻だけを再利用した。元のAction及びCameraはPlannerへ入力していない。モデルはQwen3-8B-Abliterated Q4_K_M、seed 42、`n_ctx=16384`、`max_tokens=4096`、Scene batch 3。Vision、Direction Enhancer、Lyric Segmentation及びH3は再実行していないため、この試験は同じ素材・タイミングでのPlanner/Compiler比較である。

## 結果

最終実行は[EMD](../assets/research/choreography-full-run-v4-2026-09-22/generated.emd.md)、[Plan JSON](../assets/research/choreography-full-run-v4-2026-09-22/plan.json)、[証拠JSON](../assets/research/choreography-full-run-v4-2026-09-22/evidence.json)を出力した。PlannerとRef2VA Compilerはともに完了し、欠落slotは0。16 Scene、29 Shot、Planの`length`総和3633 frameである。候補ID選択callは0、Scene Spine stepは24。Plannerの`issue_count`は129、`repetition_warning_count`は47（Action 34、Camera 13）であり、警告は品質向上の証拠ではない。

EMDの良い点は、歌詞の苔、花、御神木、狐火へそれぞれ反応し、Scene 5では「胸の傷が光るように脈動する」という歌詞由来の意図的な可視演出をActionとして明示できたこと。最終PlanはこのShotをStyle/Compilerで一律禁止しない。CameraにはArc、Roll、顔へのZoomがあり、Scene間のカメラ移動を試みている。

一方で、Scene 2では人物が鳥居の「上部」に触れ、Scene 4では「花壇の苔」という未確立の組み合わせが現れ、Scene 14では「狐火の上部に立って」と物理的に不自然な配置になる。Scene 10は二ShotのActionが同文で、Scene 3・7は接触の反復もある。苔・花・狐火の名詞反応はできたが、身体のダンス的な振付と対象の空間的な成立はまだ弱い。候補IDの強制選択を除いたことでモデルの自由度は確保したが、それだけでは創作品質は向上しなかった。

**判定：profileの選択可能化と全編Plan生成は完了。ただし映像品質の運用昇格は未判定。** 既定profileは変更しない。高コストな全編H3レンダリング前に、Scene 2、4、10、14のPlan本文を確認する価値がある。改善を続けるなら候補数や禁止語を増やすより、Cueが選んだ対象の到達可能位置と、Scene Spineが作る始点・終端の空間的一貫性を小範囲で検証する。

この試験では動画をレンダリングしていない。H3上の実際の身体演技、構図保持及び接触位置はユーザーのレンダリング結果で判定する。EMD上での形式的成功は映像上の成功を保証しない。
