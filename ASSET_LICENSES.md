# アセットのライセンス

Copyright © 2026 wsoldwolf

本書に列挙したアセットには、プロジェクトのソースコードとは別のライセンスを適用します。これらのアセットは[クリエイティブ・コモンズ 表示—非営利 4.0 国際](https://creativecommons.org/licenses/by-nc/4.0/deed.ja)（`CC BY-NC 4.0`）の下で提供します。

適切なクレジットを表示し、ライセンスへのリンクを示し、変更の有無を明記することを条件として、非営利目的でこれらのアセットを共有・翻案できます。このライセンスは、著作権その他の類似する権利が成立し、かつ`wsoldwolf`が管理できる範囲に限って許諾されます。

推奨クレジット表記：

> MV Director検証用アセット、制作：wsoldwolf、ライセンス：CC BY-NC 4.0。

## 楽曲と歌詞

以下のファイルはSuno Pro契約中に生成し、Sunoの正規のダウンロード機能を使用して取得したものです。歌詞アラインメント、ボーカルタイミング、字幕生成、音声パディング及びMV計画の検証素材として提供します。

- `assets/bgm/autumn_fox_shrine.mp3`
- `assets/bgm/autumn_fox_shrine_vocal.mp3`
- `assets/bgm/autumn_fox_shrine.txt`
- `assets/bgm/bgm_millennium_torii.mp3`
- `assets/bgm/bgm_millennium_torii_vocal.mp3`
- `assets/bgm/bgm_millennium_torii_lyrics.txt`
- `assets/bgm/short_bgm_millennium_torii.mp3`
- `assets/bgm/short_bgm_millennium_torii_vocal.mp3`
- `assets/bgm/short_bgm_millennium_torii_lyrics.txt`
- `assets/bgm/nameless_heart.mp3`
- `assets/bgm/nameless_heart_vocal.mp3`
- `assets/bgm/nameless_heart_lyrics.txt`

## 参照画像

参照画像は、画像認識、Subject / Scene EMD生成、参照バインディング及びH3動画生成の検証素材として提供します。現在の配布workflowでは人物と背景を別参照へ分離し、人物リファレンスシートを`<Picture 1>`、背景画像を`<Picture 2>`として使用します。

### 従来の参照画像

以下のファイルは`wsoldwolf`がAnima base v1.0を使用して生成したものです。

- `assets/image/image001_mikofox.jpg` — 従来の人物立ち絵。比較・検証用
- `assets/image/image002_keinai.jpg` — 背景・環境参照、`<Picture 2>`
- `assets/image/image003_whitewolf.jpg` — 追加の人物参照・Vision検証素材

### 人物リファレンスシートと作成用素材

以下は`wsoldwolf`が提供する、Qwen Image 2.1を利用した人物リファレンスシート作成・検証用の素材です。この2ファイルにも、本書の`CC BY-NC 4.0`を適用します。

- `assets/image/image001_mikofox_qi21_src.jpg` — リファレンスシート作成用の元画像
- `assets/image/image001_mikofox_ref.jpg` — 現行workflowの人物参照、`<Picture 1>`。全身・顔・足袋などの詳細を含むリファレンスシート

リファレンスシートは人物の識別特徴や局所形状の再現を補助するものであり、生成映像での完全な再現を保証するものではありません。

## 適用範囲

リポジトリルートの`GPL-3.0-only`ライセンスは、上記のアセットには適用されません。同様に、`CC BY-NC 4.0`はプロジェクトのソースコードには適用されません。

今後追加されるアセットには、このライセンスは自動的に適用されません。そのライセンスと出自を本書へ明示的に追記する必要があります。第三者の商標、キャラクター、肖像その他`wsoldwolf`が管理していない権利については、いかなる許諾も行いません。

Suno、WAI Illustrious、Anima、Qwen Imageその他の生成サービス又はモデルに関する名称、ソフトウェア及びサービス自体は各権利者に帰属します。本書は、それらのサービス又はモデルの利用規約を変更したり、それら自体を再許諾したりするものではありません。GGUF、mmproj、H3、TE、VAE及びLoRAなどの取得モデルには、各配布元のライセンスが適用され、本書のアセットライセンスは適用されません。
