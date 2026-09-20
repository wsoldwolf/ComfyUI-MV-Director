# Planner v52：顔Shotとgroundingの割り当て衝突

## 症状と原因

ユーザーログではscene12:slot1で`missing_spatial_anchor`と
`face_performance_missing`が併発し、監査後に`ACTION_GROUNDING`で停止した。
前者が停止条件、後者とREFERENCE_POSE等は品質上の問題である。

`_with_grounding_transfer_requirements`は生成対象リストの先頭に配置fragment、
次に可視展開fragmentを割り当てていた。旧profileでは固定の顔Actionが
生成対象から外れていたが、emotionalの顔ActionはLLM生成なのでリストに入る。
この違いを考慮しておらず、顔を撮るShotへ環境の配置を同時に要求していた。
ログの顔品質判定から、この経路に該当することが分かる。

ただし当該実行のLLM応答全文は取得していない。語句の欠落にこの衝突以外の
原因がなかった、あるいは全てのgroundingエラーがなくなるとは断定しない。

## 修正

- 通常coverageが存在する場合、顔accentをfragment割り当てから除外する。
- 通常coverageだけの順序で出来事のphaseを再配分する。顔はphaseを空にして表情を担当する。
- 通常slotが一つなら、その一つに配置と可視展開をまとめる。
- 通常slotがない特殊な構成では従来の必須契約を残す。対象描写を捨てて成功扱いにはしない。
- INFOの`Action grounding transfer`に担当roleとphaseを追加する。
- algorithm versionをv52へ変更し、古い生成キャッシュとの混同を防ぐ。

新しいLLM task、出力field、監査回数の追加はない。変更するのは要求先と
既存phaseの割り当てであり、Cue CardのfragmentとAction本文はLLMの出力を
AS ISで保持する。配置欠落の停止条件と顔表情の品質検査は維持する。

## 検証

`tests/test_planner_grounding_roles.py`に以下の回帰試験を追加した。

- 先頭が顔、残り3Shotが通常coverageの構成。
- 顔が途中、又は複数ある構成。automaticとpriorityの双方。
- 通常slotが一つ、及び全slotが顔の境界条件。
- 無効Cue、機能非適用、複数Sceneと入力順の保持。
- 配置が欠落すれば検出され、顔表情も引き続き検査されること。
- リップシンク有効のPlanner結合試験で完了し、顔・出来事の本文が一字も変わらないこと。

結合試験は固定応答backendを使用する。実8Bによる当該楽曲全編の再生成や
映像品質の確認を代替するものではない。

全372テスト成功、skipなし。修正前と同等の先頭二slot割り当てを一時的に
注入した対照試験では、同じ結合ケースがPlanner不完全で失敗することを確認した。
`git diff --check`も成功（既存のLF/CRLF変換警告のみ）。
