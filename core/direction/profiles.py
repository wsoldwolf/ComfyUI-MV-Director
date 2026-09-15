"""Small fixed profile set for the first Direction Enhancer version."""

from __future__ import annotations


STYLE_PROFILES = {
    "reference_anime": (
        "参照画像の顔・体格・衣装・配色を同じ設計で保ち、整理された線、"
        "明瞭な色面、セル影、繊細な光で手描き2Dアニメとして描く。"
    ),
    "reference_cinematic": (
        "参照画像の人物設計を保ち、自然な皮膚・布・材質、映画照明、"
        "レンズによる奥行きで実写映画として描く。"
    ),
    "reference_painterly": (
        "参照画像の形と配色を保ち、紙目、透明な色層、柔らかな境界を持つ"
        "手描き絵画として描く。"
    ),
}

MOTION_PROFILES = {
    "natural_performance": (
        "歌詞と音の強弱へ反応する全身動作を、接地、重心、手と対象の接触、"
        "髪と衣装の追従が読める連続動作として描く。"
    ),
    "expressive_mv": (
        "静かな区間は小さな重心と手の動き、強い区間は踏み込み、胴体のひねり、"
        "腕の広い軌道へ変化させる。"
    ),
    "limited_animation": (
        "大きく読めるキーポーズとポーズ間の移行を使い、身体と口形のタイミングを"
        "別々に保つ。"
    ),
}

CAMERA_PROFILES = {
    "readable_depth": (
        "顔、全身動作、接触点を読める距離を保ち、安定した構図、緩やかな接近・"
        "後退・横移動を使い分ける。"
    ),
    "cinematic_depth": (
        "開始視点、被写体の側面を通る経路、終了視点、前景・中景・遠景の視差を"
        "明示する。"
    ),
    "rhythmic_mv": (
        "楽曲強度に合わせて移動量と構図保持を変え、Scene間で角度、高さ、距離、"
        "移動方向を展開する。"
    ),
}

DIRECTION_PRESETS = {
    "anime_emotional": (
        "reference_anime",
        "expressive_mv",
        "cinematic_depth",
    ),
    "cinematic_performance": (
        "reference_cinematic",
        "natural_performance",
        "readable_depth",
    ),
    "painterly_mv": (
        "reference_painterly",
        "natural_performance",
        "cinematic_depth",
    ),
}

