# Connected Combo

サブグラフ内部にある既存STRING COMBOの候補をfrontendで取得し、外側から同じ候補を選べるようにします。

| 入力 | 説明 |
|---|---|
| `selected_value` | UIで選択する値 |
| `enum_values_json` | frontendが接続先comboから取得して保存する候補JSON |

通常は`enum_values_json`を手編集しません。先に出力を対象comboへ接続すると、frontendが候補を同期します。backendは保存候補と選択値の一致だけを検証し、任意文字列を追加しません。

頻繁に変更するPlannerの`lip_sync_mode`等をサブグラフ外へ公開する用途を想定しています。
