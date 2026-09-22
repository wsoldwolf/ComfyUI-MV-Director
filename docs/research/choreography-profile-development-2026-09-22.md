# Scene別振付プロファイル：開発開始と採用判定

2026-09-22

## 目的と変更範囲

[前段の実装前検証](character-choreography-implementation-probe-2026-09-22.md)で、詳細なScene固有briefがあれば8Bは支持・体幹・腕・顔をShotへ展開できた一方、8B自身に無制約でbriefを書かせる方式は失敗した。そこで、具体物に依存しない複数の身体経路をMotion profileに定義し、Sceneごとに一つ選んで固定Shotへ具体化する方式を試す。

`profiles/motion/development/anime_choreography_mv.md`を新設した。現行の`anime_emotional_mv`と`anime_story_mv`は変更していない。`development/`はUIから読まれず、未検証の振付候補が全曲PlannerやH3へ偶発的に流れない。新設の`# 振付候補`は型付きで読み、IDの重複、単一候補、Motion以外への記述及び`dance_phrase`以外での使用を拒否する。候補は計画用の運動語彙であり、歌詞対象、接触、場所、Camera、動画用の共通指示を所有しない。

## 8Bの短区間試験

Qwen3-8B-Abliterated Q4_K_Mを使用。保存されたScene 11–12の歌詞、Cue、Shot境界とCamera coverageを固定し、候補IDだけを返す選択callと、選択した候補を用いるShot連鎖callを実行した。元のActionは入力していない。H3及び全曲Plannerは実行していない。入力・生応答・モデル設定は[証拠JSON](../assets/research/choreography-profile-probe-2026-09-22/evidence.json)に保存した。

初回は二Sceneとも`resolve_diagonal`を選び、Scene 12がScene 11の踏み替えを再演した。そこで直前IDだけを有限候補から除外し、継続時は前Scene終端を開始姿勢にする指示を追加した。3 seedの再試験では、候補IDは6/6件で形式どおり選べた。しかしShot連鎖の構造は4/6件しか通らず、残り2件は1 ShotのScene 12へ2 Shotを書いた。Scene 12には「守ってゆこう」に対して`hesitation_recovery`を選び、感情の方向も十分に適合していない。通過例にも前Sceneの体勢から再び膝を緩める定型や、語の破損があった。候補を一つ外せば多様性が保証されるわけではなく、継続性と歌詞適合を損なう可能性がある。

**判定：本番Plannerへの接続は保留。** プロファイルの器と検証ツールは作ったが、振付が改善したとは判定しない。固定Shot数違反を機械的に補正したり、自然文ActionをPythonで置換したりしない。`anime_emotional_mv`を比較基準として保持する。

## 次の検証課題

1. Scene 11–12だけでは感情の幅が狭い。保存EMDの対照的な歌詞（例えば苔と花、決意と喪失）を追加し、実Shot境界・Camera coverageを固定した複数Sceneで試す。合成の歌詞を成功証拠にしない。
2. 選択を単なるID当てにせず、歌詞の感情、Cueの接触可否、前Scene終端、全身／顔の可視範囲で候補の適合を判定する。ただし対象・場所を候補から輸入しない。前候補の一律除外だけに頼らず、継続中は既存フレーズの未使用部分又は新しい動きへの明示的な橋渡しを選ぶ。
3. 候補の長文をそのままShot生成へ渡すとコピーや開始姿勢のリセットを誘発する。選択後はScene固有の始点、可視アクセント、終端を短い契約としてLLMに具体化させる方法と、既存Scene Spineに候補を渡す方法を同じ固定fixtureで比較する。追加callの数、16k文脈及び5060での時間を記録する。
4. 採用ゲートは、複数の異なる実歌詞Scene・複数seedで固定Shot数100%、前Scene終端の保持、候補の全文コピーや同じ踏み替えの再演なし、歌詞にない対象・接触なし、Cameraから見える身体accentの成立とする。テキストで通るまでH3短区間比較へ進まず、全曲既定にも昇格しない。

最終的なActionは引き続きLLMの採用文をAS ISでEMDへ出す。Pythonは候補ID・Shot数・前後接続の有限契約だけを扱い、演技の自然文を書き換えない。
