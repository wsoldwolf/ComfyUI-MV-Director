# 身体演技を狭める固定プロンプト・プロファイル監査

2026-09-24。[全編動画の原因分析](shotlink-body-full-performance-cause-2026-09-24.md)の追補。現行`dev`のDirection、Visual Beat、Scene Spine、Action、監査、Cameraのシステムプロンプトと、`anime_emotional_mv`のStyle/Motion/Camera profile及び実行経路を調べた。対象動画は旧経路の23 Shotと手書き差替え6 Shotの比較であり、**現行の全固定文が当時の元23 Shotにそのまま使われたことまでは保存されたPlanner中間traceから確認できない**。以下はコードで確認できる現在の作用と、映像・Planに整合する原因候補を分けて記す。

## 実際に通る固定文

`anime_emotional_mv`では[Planner engine](../../core/planner/engine.py)がCamera profile metadataの`lyric_interpretation=bounded`によって[bounded Visual Beat prompt](../../prompts/timeline_planner_visual_beats_bounded_system_prompt.txt)を選び、Motion profile metadataの`performance_mode=dance_phrase`によって[dance-phrase Action prompt](../../prompts/timeline_planner_actions_dance_phrase_system_prompt.txt)を選ぶ。Scene Spine、[Action監査](../../prompts/timeline_planner_action_audit_system_prompt.txt)、[Camera prompt](../../prompts/timeline_planner_cameras_system_prompt.txt)も別段で作用する。[Direction Enhancer](../../core/direction/enhancer.py)は、ユーザーがMotion/Camera本文を所有しない場合、外部profile全文をPlanner用Directionへ正確に入れる。完成EMDへは[renderer](../../core/planner/renderer.py)と`render_profile_direction`が長いprofile全文を短い`render_prompt`へ置換する。したがって「Plannerを制約する全文」と「H3が直接読む短い共通文」を混同しない。

## 動きを狭める条件と強さ

| 優先 | 固定文・実装上の条件 | 身体演技への作用 | 判定 |
|---|---|---|---|
| 高 | bounded Visual Beat promptは「上半身で完結する演技を主軸にできる」「支持脚や重心は必要な時だけ補助」と明記し、身体主導の部位例も肩・胸郭・肘・前腕・手首・視線を先に列挙する | Sceneの最初の身体着想が上半身中心になりやすい。後段Actionはその`body_driver`を受け取るため、重心・骨盤・脚の経路が最初から薄いと復元しにくい | **明示的な上半身優先バイアス**。同じpromptは後半で全身の短い振付も要求しており、完全禁止ではなく内部で優先順位が競合する |
| 高 | Action監査promptは「Upper-body phrases are complete performances」「PASSは最良・最も劇的でなくてよい」と明記。全身の支持脚→体幹→両腕を要求する`BODY_ACCENT_MISSING`は`body_phrase_accent`だけ | 肩・胸・片腕で成立するActionを通常Shotでは採用できる。監査は創作上の強さを選ぶ機構ではない | **確認済みの合格基準**。過剰な不合格で止める代わりに、弱いが合法な候補も通す設計 |
| 高 | [Motion profile](../../profiles/motion/anime_emotional_mv.md)は`body_accent_policy=sparse_chorus_prechorus_verse_contact`。[engine](../../core/planner/engine.py)は主にサビ・一部プレコーラス・複数Shotの接触VerseからScene最大一Shotを選び、顔・接触event等を外す。Cue対象なしのScene Spineも同policyではスキップされる | 非接触のVerse・間奏等ではScene全体の身体進行も強いbody roleも割り当たらない場合がある。対象があるSceneでも接触と顔を先に割り当てると残余Shotの身体accentが疎になる | **コード上の明確な選択制限**。8Bの能力とは別に機会を減らす |
| 中～高 | [Camera profile](../../profiles/camera/anime_emotional_mv.md)は「全身表示は支持脚の動きそのものが確定Actionに必要な場合に限る」。Camera promptは確定Actionへ新たな姿勢・動作を追加できない。engineの強い全身coverageは`scene_phrase`等の限定条件で付く | Actionに脚・重心が書かれなければCameraも全身を選びにくい。Actionの弱さを撮影側が救えない。映像では人物よりCameraだけが大きく動く区間を作り得る | **可視化段階の増幅要因**。Camera単独の根本原因ではない |
| 中 | dance-phrase Action promptは「通常Shotは40～100字程度」「一Shotには現在の一段階だけ」「顔Shotでは新しい踏み替えを始めない」。Scene Spineは一Scene一event、接触時のSHOWを対象＋手へ寄せる | 短文・単一段階は8Bの出力を安定させるが、歌詞対象の配置と動作が同じShotにあると身体の複数部位・始点／終点が省かれる可能性。顔・接触に割いたShotでは脚の進行を別Shotへ逃がす必要がある | **圧縮圧力・役割分離**。文自体は全身演技を禁止しないため、単独の決定因ではない |
| 低～中 | Motion profile、Action prompt、Visual Beat promptは人物の全身自転・ピルエット、無根拠な走行、足元の接写を抑える | 回転や移動系の語彙は狭くなるが、横ステップ、膝の弾み、支持交代、体幹と両腕の非対称な経路は明示的に許される | **意図的な演出境界**。今回の「肩と片手だけ」の主因とみなさず、理由なく撤去しない |
| 未確定 | Style profileとH3のSubject定義は参照ポーズを再演せず各Shotの冒頭から新姿勢を使うよう求める | 参照ポーズ固定を防ぐ一方、継続Shotの初期姿勢との競合は理論上あり得る | 今回の身体量不足への寄与は証拠なし。別の連続性試験が必要 |

### 特に重要な「上流では任意、下流では不在」

bounded Visual Beatの「支持脚や重心は必要時だけ」と、Action監査の「通常roleでは上半身だけでも完成」、Camera profileの「脚が確定Actionにある時だけ全身」の三段を合わせると、8Bが一度上半身だけのScene像を選んだ後に、後段で全身フレーズへ戻す必須経路がない。Motion profileの「ダンスのような全身演技」という肯定文はあるが、具体Shotでは役割・Cue・監査・Cameraの局所条件に負けやすい。対象の出来事は配置・可視変化の全文保持で強く保護される一方、身体経路は同程度には保護されない。この非対称は、苔・狐火の対象表現が改善しても人物演技が追いつかない状況と整合する。

さらに`scene_phrase`用の[身体専用Spine prompt](../../prompts/timeline_planner_scene_spine_body_system_prompt.txt)は支持交代→骨盤・胸郭→両腕のeventと`SHOW=whole_body`を要求するが、今回の`anime_emotional_mv`はそのpolicyではない。[Scene作者用profile](../../profiles/motion/anime_scene_author_mv.md)も別のオプトイン経路であり、今回の完成動画で検証されたものではない。

## 変更すべき文と残すべき文

1. 最初の少数Scene比較では、bounded Visual Beatの「上半身を主軸」「支持脚は補助」を、身体部位の上下関係を決めない文へ変更する。静かな歌詞で上半身だけを許す余地は残し、全Sceneの全Shotへ足運びを強制しない。変更前後のCue本文と採用Actionを保存する。
2. 監査のPASS定義を「派手でないから拒否」へ変えるのは危険。通常roleの上半身PASSを保ちつつ、別の比較尺度でScene全体の始点・動作の進行・終点を選ぶか、body roleを与えるSceneを増やす。監査を無制限に再試行させない。
3. Cameraの全身条件は、Actionが強くなってから「身体のアクセントを映す間は中広角又は全身、反応で顔へ寄る」に緩めて比較する。Actionが薄いまま全身率だけ上げても立位を大きく映すだけになる。
4. 参照ポーズ防止、一人だけ、足袋の保護、対象物の無根拠な接触防止、急なカメラ反転防止は今回の原因を切り分けずに削除しない。全身自転禁止も、カメラArcで回り込む既存の演出意図に沿っている。

以上により、固定文に**実際の演技量を下げ得る条件は存在する**と結論する。ただし個々の文が今回の23 Shotを何件弱くしたかは保存された8B中間応答がないため未確定である。先に[原因分析レポート](shotlink-body-full-performance-cause-2026-09-24.md)のP0–P1を、上記の固定文を一つずつ変える比較として実行すれば、モデル出力の限界とシステム側の誘導を切り分けられる。ここまでが削除前の監査結果である。

## 監査後に実施した固定文の削除

次回検証で上半身優先の誘導が残らないよう、bounded Visual Beatの上半身部位列挙・支持脚を補助扱いする文と「40〜90字」の目安、dance-phrase Actionの「一Shot一段階」と「40〜100字」の目安、Action監査の上半身だけで完成と断定する文、Camera promptの顔・肩・手への無条件の優先文、現用Camera profileの「脚の動きが確定Actionに必要な場合だけ全身」という制限を除去した。`anime_story_mv`のCamera本文も現用profileと同一に保つため同じ一文を除去した。`tools/offline_action_phases.py`の旧文一致検査は新しい基準文へ追従させた。

`body_accent_policy=sparse_chorus_prechorus_verse_contact`は本文でなく配分ポリシーである。行だけ削ると省略時の`off`になり、身体accentの機会がかえって減るため今回は残した。これを緩めるなら`scene_phrase`等の別設計と比較が必要であり、固定文削除の効果とは分ける。自転・走行・足元接写・参照ポーズ反復・多人数化・急なArc反転の防止も、今回の身体量不足と同定できていないため維持した。

静的検証として既存の単体試験571件がすべて成功した。これはプロンプトの構文・既存契約の確認であり、8Bが実際により強い身体演技を生成すること、H3映像が改善することはまだ示さない。次回は同じ歌詞・Scene・seedで旧版とのAction及びCamera出力を保存し、人物の支持／体幹／両腕の時間順、全身coverage、対象eventの保持を人手で比較する。
