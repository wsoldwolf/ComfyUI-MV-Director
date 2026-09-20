# 滝の検証アセットへ鳥居・灯籠が出現する問題

## 調査結果

**神社・鳥居に関するハードコードが残り、今回の実際のH3プロンプトにも届いている。**
特にMotionプロファイルの禁止文と、Compilerが背景参照へ付ける固定説明文は、入力の背景が滝でも鳥居・参道・石灯籠という具体語を含めてしまう。
入力画像にない物体を連想させる有力な原因候補であり、生成モデルの能力や参照画像だけの問題として扱うべきではない。

今回確認したのは語の混入経路である。各文を除去した同一seedの動画比較は実施していないため、固定文だけが唯一の原因、又は除去すれば必ず解消する、とまでは断定しない。

## 対象と確認方法

- 動画：`C:/Software/ComfyUI/output/h3_chains/mv_director_context_loop/segments/clip_0001.23d73aed915046a6b699afb5d64619ae.mp4`
- 864×480、24fps、10.125秒。0.5秒間隔の抽出フレームで確認。
- コード確認時点：`22178e74348e20b87d3ce6da8efbbf2ca0da7637`。前の分析資料の未コミット変更はそのまま保持。
- 動画の`h3_prompt`は埋め込み`h3_plan.shots[0].prompt`と完全一致。
- 実採用prompt hash：`4232fe5e12d6d4db19be73543349b76a4bb3f4d9408311d05f5301d3742c38e2`。
- 入力Plan名：`context_loop_plan_00001.txt`。埋め込みPlan全体は30 Scene。

動画WFでは人物が`ref_images.ref_image_0`、背景が`ref_images.ref_image_1`へ接続されている。
実ファイルを開いた範囲では、人物画像は白背景の立ち絵、背景画像は滝・紅葉・岩・水面・手前の地面であり、鳥居・社殿・灯籠は見当たらない。

- 人物：`C:/Software/ComfyUI/input/000027-847492889117644-5.0-2026-09-20 10-00-27.webp`
- 背景：`C:/Software/ComfyUI/input/000029-847492889117644-5.0-2026-09-20 10-03-53.webp`

生成映像には、滝と紅葉を残したまま、赤い鳥居・石灯籠・看板・舗装された参道状の空間が追加されている。
背景参照が完全に失われたのではなく、別の場所の要素が上乗せされた状態。
元歌詞に神社・鳥居がない点はユーザー申告であり、今回の動画メタデータだけから元歌詞全文との紐付けまでは検証していない。

## H3へ直接届いた二つの経路

| 発生源 | 固定された語 | 実際の伝達 |
|---|---|---|
| [Motion `anime_emotional_mv`](../../profiles/motion/anime_emotional_mv.md) | 「鳥居などの構造物の上部を足場にせず」 | DirectionのMotion本文→EMD共通文→英訳prefixの`structures such as torii` |
| [背景参照の固定説明](../../core/h3_contract/environment_reference.py) | `shrine approaches`、`stone lanterns` | [Compiler](../../core/compiler/ref2va.py)の背景定義生成→`<Picture 2>`説明→Scene prompt |

今回のH3入力には次の文が存在する。

```text
Do not use the upper parts of structures such as torii as a foothold ...
Preserve functional spatial topology: keep paths, shrine approaches, stairs, doorways ...
Fixed fixtures such as stone lanterns, lamps, posts, signs, and statues remain beside ...
```

これらは本来、鳥居に乗る・参道中央に灯籠を移動させる問題への対処だった。
しかし、舞台に存在することを確認せず、特定の物体を例示する固定文を全アセットへ適用している。
禁止・配置制約として書いたつもりでも、H3へ渡すテキストに具体物の名前を提示している点は変わらない。

一方、今回の環境本文は`A waterfall that is always flowing`、`surrounding of an autumn waterfall`、
`autumn clear sky`、`soft sunset light`。Scene 1の局所Action/Cameraには`torii`・`shrine`・`lantern`はない。
実採用prompt内の三語の出現は、上記固定文の各一回に対応する。
したがって、このクリップでは「Plannerが局所Actionで新たに神社を選んだ」より、共通文・背景定義からの漏洩が直接確認できる問題である。

## LLM入力側に残る関連記述

| ファイル | 記述とリスク |
|---|---|
| [Direction Enhancerシステムプロンプト](../../prompts/direction_enhancer_system_prompt.txt) | `shrine approach`の例示。さらにOTHERの推奨例として`wind through a torii`・`foxfire associated with a fox spirit`を挙げ、人物の属性から特定の背景・effectを連想させ得る |
| [bounded Beat](../../prompts/timeline_planner_visual_beats_bounded_system_prompt.txt) | 鳥居を地面から通る・見上げる対象として例示 |
| [dance_phrase Action](../../prompts/timeline_planner_actions_dance_phrase_system_prompt.txt) | 鳥居の上部へ乗せないという具体的禁止例 |
| [通常Beat](../../prompts/timeline_planner_visual_beats_system_prompt.txt) | 空間配置の説明に`shrine approaches` |
| [通常Action](../../prompts/timeline_planner_actions_system_prompt.txt) | 空間配置の説明に`shrine approach` |
| [Action audit](../../prompts/timeline_planner_action_audit_system_prompt.txt) | incidental fixtureの例として`lantern`等を列挙 |

検索対象は`prompts/`、`profiles/`、`core/`、`nodes/`、`web/`の実装・設定。
テストや過去の分析資料にも多数の具体語があるが、それらを実行時にプロンプトへ読み込む経路とは区別する。
上表のLLM入力側の記述が今回実際に新規の鳥居文を生成したことまでは確認していない。直接の混入が確認できた二経路を最優先にする。

## 古い映像・背景の取り違えについて

対象クリップはScene 1で、`context_length=0`、`audio_context_length=0`。
`generated_continuity=off`と`source_reference=off`は音声方針の項目であり、人物・背景の画像参照が無効という意味ではない。
今回の画像参照接続は別に確認済み。前回の神社動画を視覚コンテキストとして継続する設定は確認されなかった。
環境説明も実画像も滝へ切り替わっており、「旧背景ファイルがそのまま指定されている」という説明を支持しない。
人物の衣装・狐耳からのモデル側の連想は別の可能性として残るが、現在はまず実装が明示的に与えている不要語を解消すべきである。

## 推奨する対策

1. **背景の固定文を、入力にある物体だけへ作用する表現にする。** 参道・石灯籠等を列挙せず、「観測又は指定された通行可能領域を保ち、既存の固定物の位置を変えず、演技のために新しい設備を追加しない」という関係を記述する。
2. **MotionとPlannerから特定の舞台名を外す。** 鳥居を例示せず、「指定された支持面を維持し、接触許可から登攀・踏み付けへ拡張しない」という一般的条件にする。
3. **EnhancerのOTHERを人物属性だけから舞台やeffectを発明する入口にしない。** 固有の例を削り、作者指示・現在の歌詞・背景に根拠がある場合だけ選ぶ方針に揃える。
4. 作者の入力に実際に鳥居や灯籠がある場合は、その情報をそのまま扱う。出力全文から単語を機械削除する方式にはしない。AS IS原則と両立する修正は、入力前の固定テンプレート・契約の改善である。
5. 同じ保存Plan・参照・seed・H3設定で、まず不要な固定文だけを除いたScene 1を比較する。その後、改訂したDirection→Planner→Compilerで再生成したものを比較する。既存の保存Planには旧文が残るため、コード更新だけで動画WFを再実行しても比較にならない。

回帰確認には、滝・室内等の背景から不要な神社語が固定出力されないことと、作者が明示した神社語は保存されることを含める。
調査時点ではGPUによる比較生成を行っていない。

## 修正と回帰確認

背景固定文・Motion・Planner・Enhancerから上記の旧舞台に固有な例示を除去した。配置の規則は入力に存在する対象だけへ適用し、作者の背景情報や生成された本文を単語置換・削除する処理は追加していない。
Direction・Planner・Compilerのキャッシュ識別子も更新した。既に保存したPlan JSONは更新されないため、新しい文で比較する際はプロンプト生成段階を再実行する。
全412テストが成功。滝・室内・空の背景への不要語混入の防止と、作者が指定した神社情報の保持を回帰試験に追加した。映像モデル自体の連想を完全に防ぐ保証ではない。
