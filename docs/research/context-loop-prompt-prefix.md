# Context Loop `prompt_prefix`調査

調査日: 2026-09-15<br>
対象: Context Loop 0.6.9、commit `9860a063784c8c23b58e00107f2180e0df3c43d9`

## 結論

Planの正しいkey名は`prompt_prefix`である。JSON object内のproperty順には依存せず、Context Loopが各Sceneのpromptより前へ機械的に連結する。MV Directorでは任意のEMD `# 共通プロンプト`をStyle、Motion、Camera、Otherへ構造分離し、見出しを除いた存在する本文をこの順でfieldへ平坦化する。全区分がなければfieldを出力しない。

```text
final prompt = prompt_prefix + "\n\n" + scene_prompt
```

Style Profileの固定英語anchorは`prompt_prefix`の先頭行へ置く。2026-09-16 20:30の実写風生成を復元する`illust_to_photoreal`は、保存Plan `context_loop_plan_00009.txt`の長い英語anchorを完全一致で使う。また各Sceneの先頭Shotへ``Shoot as a photorealistic live-action video, depicting the characters as real human actors.``を明示する。どちらも再翻訳又はLLMによる言い換えを行わない。`# サブジェクト`は顔、体格、髪、衣装設計及び配色等の媒体非依存な同一性を記述し、参照画像がイラスト、写真又はCGであることを生成先の固定条件にしない。

## 1. 入力と正規化

- Python parserは`prompt_prefix`を読み、存在しない場合だけ旧`global_prompt`をfallbackとして読む。
- 文字列と文字列配列を受理する。配列はLFで連結され、前後空白が除かれる。文字列以外を含む配列はerrorになる。
- Plan Studio frontendは編集保存時に改行を正規化し、行配列として保存する。
- MV Director Compilerは新規Planだけを出すため、`global_prompt`を出力せず、`prompt_prefix`の文字列配列へ固定する。

根拠:

- `chain_nodes.py:691-697` `_prompt_text()`
- `chain_nodes.py:7247-7250` Plan parser
- `web/h3_chain_plan_core.mjs:261-273` 文字列・行配列変換
- `web/h3_chain_plan_core.mjs:407-413` frontend正規化

## 2. 実行時の連結順

Sceneの動的promptを解決した後、次の順で完全promptを作る。

1. `prompt_prefix`
2. 空行二つ
3. 解決済みScene prompt

完全promptは`shot["prompt"]`、Scene固有部分は`shot["scene_prompt"]`として別々に保持される。Review retryでも同じ順で再構成され、共有prefixはScene編集の対象に含まれない。

根拠:

- `chain_nodes.py:7423-7437` 通常Plan実行
- `chain_nodes.py:7069-7105` Review retry

## 3. 動的prompt

`{one|two}`形式の動的選択はScene promptへだけ適用される。`prompt_prefix`は`_resolve_dynamic_prompt()`へ渡されない。Style anchorは固定値として扱うべきであり、MV Director Compilerは共通プロンプトへ動的候補を生成しない。

## 4. cacheとcheckpoint

- 完全promptのSHA-256がSceneの`prompt_hash`になる。
- 動的Scene templateのhashも、prefixとScene templateを連結した値から作られる。
- prefixを変えると全Sceneの完全prompt hashが変わるため、作品全体の再生成対象になる。
- Checkpoint Managerは選択した全Scene revisionの共有prefixが完全一致することを要求する。異なるStyle prefixで生成したSceneを一つの出力へ混在させるとerrorになる。
- archive復元時も`prompt_prefix`がPlanへ戻される。

StyleのA/B比較は同じrun内の部分Scene差し替えではなく、prefixごとに別run又は全Scene再生成として扱う。

根拠:

- `chain_nodes.py:7426-7458` prompt hash
- `chain_nodes.py:27176-27182` checkpoint共有prefix一致
- `run_manager.py:220-245` archiveからのPlan復元

## 5. Ref2VA strict schema

付属`web/h3_prompt_schema_core.mjs`へ次を入力して確認した。

| prefix | 結果 |
|---|---|
| なし | valid。Scene内Style文不足のwarning |
| 通常の英語Style文 | valid。同じwarning |
| `style:`で始まるStyle文 | valid。同じwarning |
| `subject_definitions:`をprefixにも置く | duplicate section error |

通常文のprefixは六セクション順を壊さない。ただし、analyzerは`detailed_description:`内で`[Shot 1]`より前に要求する1～2個のStyle文をprefixから数えない。これはschema診断上の性質であり、H3生成能力に対する実測結果ではない。

将来のschema変更との衝突を減らすため、prefixには`style:`等の独自セクションlabelを付けず、短い通常英文を使う。`subject_definitions:`等の正規見出し、Shot marker、音響directive又はdialogue tokenも置かない。

## 6. EMDからの写像

EMDはEasy MarkDownであり、次の四部構造を持つ。

```text
# サブジェクト
# 保持分析
# 共通プロンプト
## スタイル
## モーション
## カメラ
## その他
# シーン ...
```

Compilerの写像は次で固定する。

| EMD | Context Loop Plan |
|---|---|
| `# 共通プロンプト / ## スタイル` | 存在すれば`prompt_prefix`の先頭。翻訳後の行数と区分内順序を維持 |
| `# 共通プロンプト / ## モーション` | Style本文の後。省略可能 |
| `# 共通プロンプト / ## カメラ` | Motion本文の後。省略可能 |
| `# 共通プロンプト / ## その他` | 前三区分以外のフリーフォーム本文。最後。省略可能 |
| `# サブジェクト` | 各Scene `subject_definitions:`へ再掲 |
| `# 保持分析` | 各Scene `retention_analysis:`へ再掲 |
| `# シーン` | 各`shots[n].prompt`の六セクションとScene設定 |

`## スタイル`を使う場合は先頭list itemを目標画風のauthorityとする。CompilerはEMD subsection見出しを`prompt_prefix`へ出さず、存在する本文をStyle、Motion、Camera、Otherの順に連結するため、Styleがあればその最初の本文が完成promptの先頭になる。これはH3の画風変換に関するプロジェクト側の観察を固定契約にしたもので、Context Loop parserが意味上Style又はprefix自体を要求しているという意味ではない。Subject固有の保持条件は`# サブジェクト`又は`# 保持分析`へ置き、prefixから先に未定義`<Subject N>`を参照する必要を減らす。

## 7. 実装後のH3試験

H3でのStyle変換効果はschema analyzerでは判断できないため、同じ画像、seed、length及びScene promptを固定して次を比較する。

1. Styleを`prompt_prefix`だけに置く。
2. 同じStyleをprefixと`detailed_description:`のShot前へ置く。
3. 2に加えてSubject定義へ目標媒体を記述する。

評価対象は目標画風への変換、人物同一性、衣装設計、Scene間一貫性及び過剰なStyle反復による動作・カメラ指示の弱化である。初期契約は1とし、2又は3をCompilerが暗黙生成しない。試験で有効性が確認できた場合だけ、Plannerが明示Style文をEMDへ書く仕様として追加する。
