# EMD 00012 Cue→Action転送評価

日付: 2026-09-20  
対象: `C:\Software\ComfyUI\output\mv_director\context_loop_emd_00012.md`  
実装結果: Planner v49

## 結論

EMD 00012では`苔`、`花`及び`狐火`のScene局所化自体は成功しています。
しかしActionは対象語を文頭へ置いただけで、Visual Beatが生成した具体的な
`配置`と`可視展開`を失っています。従来の合格条件が「Scene内のどれか一つの
Actionに対象tokenが完全一致で存在すること」だけだったため、
`苔 手を胸の前で大きく広げる`のような候補が検査を通過しました。

これは名詞から動詞を作る能力だけの問題ではなく、Visual Beatで作った具体情報を
Actionへ渡した後の受理契約が弱い問題です。

## 観測

- Scene 3の苔は、同じ開腕、左右振り、前傾及び背面から正面へ戻る動作へ三回
  接頭され、大樹、根元、湿った樹皮又は苔の材質状態がActionにありません。
- Scene 4の花も、頭部・胸郭の捻り、開腕及び前傾へ接頭され、参道上の位置、
  花自身の揺れ・散り方又は人物との距離関係がありません。
- Scene 9と14の狐火は一部で追視対象になりましたが、発生層から頭上を経て奥へ
  移る軌道や、石畳・空気へ生じる可視結果がありません。
- `タブ`、裸の`1`、`2`、`3`、`9`、`10`、`11`及び
  `ACTION 14 1`がAction本文へ残っています。これは演出品質ではなくline
  protocolの残骸です。
- 「手を胸の前で大きく広げる」「体を左右に振る」「前傾する」「背中姿勢から
  正面へ戻る」という身体templateが、対象だけを替えて反復しています。

## 根本原因

v48はCue Cardの九field構造を検証しましたが、Action側では対象tokenだけを
Scene単位で検査していました。`配置`と`可視展開`はprompt上の指示に留まり、
8Bが短縮しても決定論的に検出できませんでした。Action Auditも意味分類であり、
bounded retry枯渇時は最小違反候補をfail-openで保持するため、裸の名詞や内部label
が完成EMDへ到達しました。

## v49改修

1. profile優先Cue Sceneでは、Visual Beatが生成した`配置`を最初の生成Action
   slot、`可視展開`を次の生成Action slotへ割り当てます。一slotなら両方を同じ
   slotへ割り当てます。
2. Action LLMには`required_spatial_anchor`と
   `required_visible_development`を渡し、対応する句を完全一致で本文へ統合
   させます。
3. Pythonは完全一致だけを検査し、Action本文を作成・修正しません。したがって
   AS IS原則を維持します。
4. 有限retry後も二句が欠落すれば`ACTION_GROUNDING`として停止します。曖昧な
   Actionを出すより、原因とslotをログで特定できる方を優先します。
5. 裸の番号、`TAB`、`タブ`、`<TAB>`、`\\t`又は内部record labelは
   `internal_protocol_label`として再要求し、残存時は`ACTION_PROTOCOL`で
   停止します。
6. 割当Scene、slot、anchor及びdevelopmentをINFOログへ出します。

## 期待される次回確認

次のEMDでは、単に`苔`、`花`又は`狐火`が入ったかではなく、INFOの
`Action grounding transfer`に出た二句がActionへ一字列として保持されたかを
確認します。苔は具体的な大樹又は根元と材質状態、花は参道内の位置と対象自身の
時間変化、狐火は自律した空間軌道と環境結果を含む必要があります。身体反応は
それらの後に組織され、裸の対象prefixだけでは合格しません。

## v50追補: 固定辞書からScene自動認識へ

v49の`苔`、`花`、`狐火`という固定一覧は回帰確認には有効でしたが、別歌詞の
`御神木`等を扱うたびにprofileを編集する必要があり、一般化できませんでした。
v50は`anime_emotional_mv`を`lyric_cue_mode=automatic`へ変更します。既存の
Visual Beat LLMが各Sceneの原文から最も具体的な可視名詞句又は独立effectを
選び、v49の配置・可視展開の完全一致転送をその対象へ適用します。追加のLLM
呼び出しはありません。Pythonは語彙辞書を持たず、検証と転送だけを行います。
`priority_lyric_cues`は独自profileで特定語を回帰固定したい場合の任意override
として残します。
