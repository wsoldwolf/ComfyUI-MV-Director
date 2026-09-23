# Scene author経路：実装と8B短区間の第一次判定

2026-09-23、devで実施。[設計](scene-choreography-architecture-redesign-2026-09-23.md)と[実装順](../implementation/scene-choreography-execution-2026-09-23.md)の第一次結果。これは保存Sceneを零時刻に置き直した**EMD段階の試験**であり、全曲Plan又はH3動画の品質証明ではない。

## 実装した境界

- 共通プロンプトの作者指定は同じEMD構造解析に通し、選択profileの該当本文だけを置換する。Motion本文とPlanner方式IDは別に保持する。
- Shot本文の`演出`、`演技`、`カメラ`は作者が固定できる。未指定分だけ、Scene出来事→人物演技→撮影の順にLLMが埋める。Cameraは採用された人物演技文そのものを読む。
- 元TemplateのShot境界・継続フラグを保持し、次Sceneへ直前の**採用済み**演技・カメラ終端を渡す。完成済み全文EMDはPlanner推論をバイパスできる。
- Compilerは用途tokenを映像promptへ混ぜずに訳し、局所の`演技`／`カメラ`があるShotへ全曲共通の対応文を二重適用しない。任意の演出候補は出来事担当だけが読む。
- 小モデルの余剰行を防ぐ構造grammarを追加した。自由な日本語本文の意味修復は行わない。

既定の`anime_emotional_mv`及び従来Planner経路は変更していない。新経路は
[anime_scene_author_mv](../../profiles/motion/anime_scene_author_mv.md)選択時だけ有効。

## 実8Bの短区間結果

Qwen3-8B-Abliterated Q4_K_M、`n_ctx=16384`、seed 1、保存fixtureからScene 5と9を局所時刻へ再配置した。最終試験は各Sceneで出来事・演技・カメラ各一回、計3呼出し、形式再試行なし。旧経路の保存Scene 5は12呼出しだったが、入力方針とpromptが異なるため単純な速度／品質A/Bではない。再実行は[スクリプト](../../tools/offline_scene_author_probe.py)、[fixture](../assets/research/scene-phrase-2026-09-23/fixture.json)と下記の原文・要約を参照。

| 区間 | 構造 | 内容の評価 |
|---|---|---|
| [Scene 5](../assets/research/scene-author-2026-09-23/scene5-v5/summary.json)・[EMD](../assets/research/scene-author-2026-09-23/scene5-v5/planned.md) | 3呼出しで完成 | 出来事が「口を閉じる」へ縮み、人物演技も口と胸への手、前傾に寄った。別れの歌詞に対する連続した全身振付には達していない。 |
| [Scene 9](../assets/research/scene-author-2026-09-23/scene9-v5/summary.json)・[EMD](../assets/research/scene-author-2026-09-23/scene9-v5/planned.md) | 3呼出しで完成 | 狐火は記述されたが、明示的な「狐火へ問う」が後Shotにあるのに前Shotへ置いた。人物は右手を上げ、次Shotで下げる定型に戻り、効果と身体演技の連携が弱い。 |

初版は出来事と演技へCamera文が混入した。[初版Scene 5](../assets/research/scene-author-2026-09-23/scene5/summary.json)で確認し、入力を担当別に分けた。その後、8Bがslot数を超える余分な行を出したため、輸送だけを制約するgrammarを加えた。形式は安定したが、意味的な改善は限定的だった。作者が`演出`をShot 2に固定すればその位置は保たれるが、全自動の選択はまだ保証できない。

## 判定と次の順序

追記：下記は第一次試験直後の順序であり、[入力経路の再分析と改善計画](scene-author-8b-input-recovery-plan-2026-09-23.md)で更新した。身体演技の生成を優先し、歌詞の文意・全曲文脈と演技briefを比較する。「朱の空に舞う／狐火へ問う」は一文なので、名詞の出現Shotだけを自動演出の一律失格条件にはしない。

第一次判定は**実装境界は成立、創作品質は不合格**。新経路を既定に昇格しない。現状のEMDでは身体差が十分でないため、H3の重い比較へ進まない。GPUのモデルは試験後に解放した。

1. Scene 5の「独立した外部出来事なし」を8Bが選べるよう、出来事担当の歌詞根拠と`なし`判断を短く再検証する。口・手など人物演技を出来事にしない。
2. Scene 9では、出来事の根拠歌詞と開始Shotを同じ構造内で拘束する。`狐火`の明示歌詞より前への出現を、辞書でなく引用元のShot番号で検出する。人間の比喩的演出を一律に禁止しない。
3. その後、全身の始点→重心・体幹・両腕→終端が旧結果より明確になるか、Scene 5・9を同条件で再比較する。成功した場合だけ別曲と継続二Sceneへ広げる。
4. 最終H3の短区間比較は、EMD上で採用済み身体演技が明瞭で、Cameraがそのアクセントを実際に捉える場合だけ行う。

この判定はAS IS原則を維持する。Pythonが「口」を「身体動作」へ書き換えたり、狐火の位置を自然文辞書で補正したりしない。作者が構造を固定できる経路と、8Bの自動判断の品質は別の評価軸である。
