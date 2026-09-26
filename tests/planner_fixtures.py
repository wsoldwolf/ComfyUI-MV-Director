"""Shared input fixtures; no test module or legacy strategy imports."""

from core.inference import LlamaRuntimeConfig

TEMPLATE = """> `シーン` 1
# シーン 00:00.000 --> 00:10.125
* `H3長` 243
> `セクション` VERSE1
> `歌詞開始` 00:02.300
> `歌詞終了` 00:05.800
> `歌詞` 千年鳥居をくぐるそなたよ
## ショット 00:00.000
* 未計画
## ショット 00:05.000
* 未計画
"""

CONCEPT = """# サブジェクト
* `画像1` 主人公。長い黒髪と白い衣装を持つ人物。
"""

INSTRUMENTAL_TAIL = """
> `シーン` 2
# シーン 00:10.125 --> 00:11.833 継続
* `H3長` 56
## ショット 00:10.125
* 未計画
"""

LATE_SECTION_TEMPLATE = """> `シーン` 1
# シーン 00:00.000 --> 00:06.000
* `H3長` 158
## ショット 00:00.000
* 未計画
## ショット 00:02.000
* 未計画
> `セクション` VERSE2
> `歌詞開始` 00:02.200
> `歌詞終了` 00:04.500
> `歌詞` 新しい節を歌う
## ショット 00:04.000
* 未計画
"""


def runtime() -> LlamaRuntimeConfig:
    return LlamaRuntimeConfig(max_tokens=512, n_ctx=4096)
