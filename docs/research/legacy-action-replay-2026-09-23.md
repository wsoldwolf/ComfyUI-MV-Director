# 旧8B動作生成の再現実験：歌詞単位・生成開始方式・身体補完

2026-09-23。[前回の「次の判断」](section-performance-p0-p2-2026-09-23.md#次の判断)を実行した。
GPUの許可を受け、動画生成なしで32回の短い推論を行った。既定profile・本番Planner・Compilerは今回変更していない。

## 結論

**旧プロンプトを戻すだけでは、求める連続した身体振付は再現しなかった。**
ただし「8Bには不可能」という結果ではない。次の三点を切り分けられた。

1. **歌詞の切り方と選択規則が、演技の内容を変えている。**
   旧Scene 9の先頭は「朱の空に舞う　狐火へ問う」で、現行Scene 9の先頭は「永遠と呼べるなら」。
   同じ旧promptでも、前者は跳躍・上昇、後者は手の上げ下げへ偏った。
   尺を入れ替えても傾向は残った。少なくとも今回の二seedでは、単なる長さ不足では説明できない。
2. **旧版の全身演技の一部は、Pythonの補完文だった。**
   保存された旧EMD Scene 6・9の強い全身移動は旧 `_motion_phase_additions` と一致する。
   旧LLMの素の出力だけと現行AS IS経路を比べるのは公平でない。
3. **Qwen3の生成開始方法にも実装差があった。**
   旧版は空のthinkingブロックをassistant開始位置へ置く。
   現在のchat APIだけで旧messagesを送ると、8件ともthinking中に512 tokenへ到達した。
   旧prefill又は現行Planner同様の `/no_think` を使うと全件完了するが、これだけでは演技は改善しなかった。

**判断：旧前段の単純移植とH3比較は見送る。**
身体振付は「歌詞の最初の物理動詞を忠実に可視化する仕事」から離し、
作者・profileの身体フレーズ候補を直接使える設計を優先する。
出来事・歌詞対象は保持するが、それを人物の全ての動作へ機械的に対応させない。

## 再現したもの／していないもの

- 実験ツール：[offline_legacy_action_probe.py](../../tools/offline_legacy_action_probe.py)。
- 旧repoは読み取りのみ。commit `992fa8b` の原文モジュールを隔離namespaceへ読み込み、
  人物brief解析、参照placeholder、歌詞解析、Scene入力構築、Qwen非thinking wrapperを使用した。
  prototypeのcheckout・本番コードは書き換えていない。
- 旧動画は `千年鳥居-prototype/ref2v_2026-09-12-8b.mp4`。
  埋め込みgraphのPlanner入力から人物・保持条件を取得した。
  共通の背景・Camera文は、旧lyric-action契約に従いこの前段へ渡していない。
- 旧systemは `node_mv_prompt_planner/prompts/core/lyric_action_system_prompt.txt`。
  前回調査でmetadataのhashと一致したもの。
  profile `lyric_visuals_light_8b` の `lyric_action_preplan=true` も確認した。
- 旧歌詞構成は、ユーザーが環境復旧後に保存した `emd/v2p_plan_prompt_00001.md` のScene 6・9。
  **これは9月12日の動画を生成した入力そのものと確認できていない。**
  現行側は前回固定済みScene 5・9の歌詞断片。
- 全曲Song Bible、後段Scene生成、旧retry・動作補完、Compiler及びH3は実行していない。
  したがって、旧パイプライン全体の優劣を確定する試験ではない。

[出典・原文抜粋・hash](../assets/research/legacy-action-2026-09-23/provenance/manifest.json)に
入力brief、原prompt、旧profile、補完関数の原文と行番号を保存した。
各試験のJSONにはpayload、raw response、実効設定、終了理由を残した。
旧モデル名・サイズは一致するが、当時のGGUF内容hashと現在の同一性、当時のllama.cpp binary、
実呼出しseedまでは証明していない。

## 条件と計測

現在の Qwen3-8B-Abliterated Q4_K_M、n_ctx=16384、max_tokens=512、
temperature=0.1、top_p=0.9、repeat_penalty=1.05、n_batch=256、KV=q8_0。
seed 1・2を固定。grammarなし、各条件一回、内容修正・監査・再試行なし。
旧動画のbase seedは1646588668だが、呼出し順を含む実効seedが未保存のため再現seedとはしていない。

| 実験 | 回数 | 推論時間合計 | 結果 |
|---|---:|---:|---|
| 旧messages→現在のchat API、soft switchなし | 8 | 33.81秒 | 全件thinking中にlength終了。演技の品質評価から除外 |
| 旧wrapperのassistant prefill | 8 | 7.65秒 | 全件stop終了、2 ACTIONずつ。身体振付は不十分 |
| 現行Planner同様の `/no_think` 付与 | 8 | 5.99秒 | 全件stop終了。空thinkタグを伴うが内容の弱さは残る |
| 旧prefill、歌詞を固定して尺だけ交差 | 8 | 7.11秒 | 全件stop終了。長くした断片でも振付は戻らない |

合計約54.6秒はモデルload・調査・テストを含まない。
計測したraw prompt token数はchat-templateの特殊tokenを含まない。
実験のframing欄は単純な行構造の観察であり、旧版validatorの合否ではない。
soft条件の `expected_open=false` は空thinkタグも原文保存しているためで、
8件が本文を返さなかったという意味ではない。
最初の試験 `run1` はtransport選択の追加前に保存した、`current-chat` 条件の記録である。

証跡：
[初回](../assets/research/legacy-action-2026-09-23/run1/manifest.json) /
[旧prefill](../assets/research/legacy-action-2026-09-23/prefill/manifest.json) /
[soft switch](../assets/research/legacy-action-2026-09-23/soft/manifest.json) /
[尺交差](../assets/research/legacy-action-2026-09-23/duration-cross/manifest.json)。

## 原文から見た結果

### 現行Scene 5相当：口・眉の演技から抜けない

旧Scene 6（14秒）の先頭は「それでも永遠を　口にする」。
現行Scene 5（9.208秒）は「口にする」から始まる。

旧prefillの旧歌詞条件では、両seedとも丸眉を唇へ近づけ、
唇から「永遠」の文字を出すような応答になった。
現行断片では口の開閉・笑み・口元の光が中心。
現行soft switchでも唇・眉・耳へ偏る。

- [旧歌詞 seed 1](../assets/research/legacy-action-2026-09-23/prefill/scene5-legacy-seed1.json)
- [現行断片 seed 1](../assets/research/legacy-action-2026-09-23/prefill/scene5-fragment-seed1.json)

長さを14秒へ揃えた断片でも、発語・髪・唇であり、支持・体幹・腕が連動する振付にはならなかった。
旧シスプロ自体は発語、文字、識別特徴の変形を禁じているが守られない。
**指示の追加量や形式上の完了は、振付の質を保証しない。**
人物条件に細かな眉・髪・耳が多い影響も疑われるが、今回はその有無を独立比較していないので原因とは断定しない。

### 現行Scene 9相当：歌詞のまとまりによって全身動作は出る

旧Scene 9（14秒）は「朱の空に舞う　狐火へ問う」で始まる。
旧prefillでは、seed 1が足を上げ空中へ跳ぶ、seed 2が跳び上がり両腕を広げて上昇する。
ただし連続した地上の振付ではなく、跳躍・飛行という大きい一出来事である。
それ自体をMVの不正解とはしないが、ユーザーの求める身体演技の回復とは別に評価する。

現行Scene 9（9.916秒）は「永遠と呼べるなら」から始まり、
「この手を離すことも」「愛なのだろうか」「朱の空に舞う」「狐火へ問う」へ続く。
旧promptは最初の完結した述語を選ぶよう強く指示するため、後半の狐火より
「永遠を呼ぶ／手を離す」へ引かれ、手の上下中心になった。

- [旧歌詞 seed 2](../assets/research/legacy-action-2026-09-23/prefill/scene9-legacy-seed2.json)
- [現行断片 seed 2](../assets/research/legacy-action-2026-09-23/prefill/scene9-fragment-seed2.json)

当初は歌詞と尺を同時に変えていたため、追加で尺だけ交差させた。
旧歌詞を9.916秒へ短縮しても上昇・跳躍が残り、現行断片を14秒へ延長しても手の上下・発語が残った。
これは「10秒以上では二つの全身phase」という旧指示の閾値だけが原因ではない証拠になる。
ただし、**行を結合した効果と、冒頭・含まれる歌詞が変わった効果までは分離していない。**
単に行を連結すれば改善するとの結論にはしない。

## 旧Python補完の意味

旧 `validation.py` には次の経路がある。

- `_motion_phase_additions`（934行）：斜め前方への大移動、横方向への加速、後退後の前方切返しという三つの固定文。
- `repair_lyric_action_motion`：不足した身体phaseをACTIONへ追加。行数上限では既存行と結合する。
- `repair_subject_motion`：preplanを使わない経路でも全身motionの下限を補う。
- `_apply_lyric_action_blueprint`：補完を含む動作列を後段Shotへ再配分する。

復旧版EMD Scene 6・9には、後退→前方切返し等の固定文が実際に存在する。
今回のLLM応答には出ていない。この差を「8Bが当時は全ての振付を独力で生成していた」
という説明に含めることはできない。
一方、当時の動画全体がこの補完だけで良くなったとも断定できない。
復旧EMDと9月12日動画の同一生成系統は未確認であり、
共通prompt、Camera、長い継続、H3による補間の寄与は残る。

現プロジェクトへこのPython自然文追加をそのまま持ち込むことはしない。
AS ISと作者優先を維持するなら、**補完の役割を、作者又はprofileが提示する任意の身体フレーズとして明示し、
LLMが選択・展開した原文を採用する**のが整合的である。
候補をPythonが強制挿入する仕様へ変更したわけではない。

## 次の設計判断

旧動作前段の逐語的な述語分解を本番へ移植するより、次を優先する。

1. **演技担当が「歌詞を説明する動作」だけを作る状態を避ける。**
   現Sceneで歌われる範囲と、読解用の完結した歌詞・セクションを分けて渡す。
   意味解釈には全文を使い、演技の時間割はSceneに収める。
   最初の物理動詞を必ず演じる規則を、人物振付へ輸入しない。
2. **既存の演出候補を短絡的な禁止・修復ではなく、身体フレーズの足場として直接使う。**
   ユーザーの明示演技を最優先にし、任意候補は不採用も認める。
   候補がある条件／ない条件の二Scene比較を次の最小試験とする。
   物への接触候補と身体振付候補は責務を説明して共存させ、狐火等の出来事を身体動詞へ潰さない。
3. **改善した演技原文が得られてからCameraを合わせる。**
   主体の踏み替え・体幹・腕のアクセントに対する画角とArc/Rollを計画し、
   身体動作をカメラ旋回や顔アップだけで置き換えない。
   不成功な演技をそのまま全編H3へ送り、seed変更で比較回数を増やすことはしない。

2の候補入力は前回P0で実装済みだが、実8Bでの創作品質はまだ未判定。
今回は旧前段再現を優先し、候補の有無、Scene共同設計、全曲main planまで検証を拡張していない。
新しいLLM段、汎用監査、既定profileの変更、現行runtimeのprefill化は未実施。
非thinking差は実行効率の別課題として扱い、振付不足の根本原因と混同しない。

## 試験・終了状態

- CPU回帰：**530件成功、skipなし**（従来526件＋実験ツール4件）。
- `git diff --check` 成功。改行変換の通知のみ。
- 32回分のraw responseを保存。途中失敗を隠した応答選別はしていない。
- 全推論が終了し、各実験のfinallyでモデルを解放。ComfyUIの起動・停止、H3生成はしていない。
- 既存の未コミット実装を保持。今回の追加は実験ツール、テスト、証跡、レポートのみ。
