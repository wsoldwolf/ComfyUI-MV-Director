# Load Text File

ブラウザで選択またはD&DしたUTF-8 `.txt`をworkflow JSONへ埋め込み、STRINGとして返します。歌詞ファイル入力に使います。

## 操作

1. ノードのファイル選択UIを押すか、`.txt`をノードへD&Dします。
2. 選択したファイル名がノードへ表示されたことを確認します。
3. `text`出力をLyric Segmentationの`lyrics_text`へ接続します。

内部の`file_data_base64`、`basename`、`browser_metadata_json`はfrontendが管理します。16 MiBまでのUTF-8/UTF-8 BOMを受け付け、改行をLFへ正規化します。

内容はworkflow JSONへBase64で保存されます。workflowを共有すると歌詞本文も共有されるため、権利や機密性を確認してください。backendの任意path読込、文字コード推測、ファイル監視、複数ファイル結合、本文編集は行いません。
