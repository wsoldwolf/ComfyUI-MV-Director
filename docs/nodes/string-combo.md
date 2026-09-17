# String Combo

利用者が定義した有限の文字列候補をComfyUI comboとして選び、STRINGへ出力します。

| 入力 | 既定 | 説明 |
|---|---|---|
| `string_list` | `context_loop|audio_reference|lyrics` | `|`区切りの候補列。literal `|`は`||` |
| `selected_value` | `lyrics` | 候補内から選ぶ値 |

`selected_value`が候補にない場合は先頭へ黙って戻さずvalidation errorにします。リップシンク方式等、workflow固有の短い選択値をサブグラフへ渡す用途に向きます。
