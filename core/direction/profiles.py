"""Small fixed profile set for the first Direction Enhancer version."""

from __future__ import annotations


STYLE_PROFILES = {
    "reference_anime": (
        "参照画像の顔・体格・衣装・配色を同じ設計で保ち、整理された線、"
        "明瞭な色面、セル影、繊細な光で手描き2Dアニメとして描く。"
    ),
    "anime_mv": (
        "参照画像から人物の識別要素、髪型、髪色、瞳色、衣装、配色、装飾及び身体的特徴を保持する。"
        "参照画像の線質、塗り、陰影、ブラシ表現及び画面構成は継承せず、映画的な手描きセルアニメーションとして再設計する。"
        "整理された強弱のある輪郭線、明瞭な色面、制御されたセル影、背景と統合された撮影処理及びアニメ映画的な照明で描く。"
    ),
    "reference_cinematic": (
        "参照画像の人物設計を保ち、自然な皮膚・布・材質、映画照明、"
        "レンズによる奥行きで実写映画として描く。"
    ),
    "illust_to_photoreal": (
        "Shoot as a scene from a photorealistic live-action movie. Express all "
        "subjects as physically existing in a real filming location. The characters "
        "are to be portrayed as real human actors with natural facial bone structure, "
        "typical human eye proportions, realistic human body proportions, skin visible "
        "with pores and fine hairs, hair that can be individually identified, and "
        "fabric made from actual physical materials. Maintain hair color, eye color, "
        "outfit colors and shapes, and accessories as consistent identifying elements, "
        "and embody them as movie makeup, special effects, and real clothing. Animal "
        "ears and tails should be expressed with real fur texture, natural weight, and "
        "movement integrated with the body. Shoot using movie lighting, realistic "
        "dynamic range, and depth from an optical lens. Apply this physical live-action "
        "portrayal to subsequent subject definitions and preservation analysis."
    ),
    "reference_painterly": (
        "参照画像の形と配色を保ち、紙目、透明な色層、柔らかな境界を持つ"
        "手描き絵画として描く。"
    ),
}

# This profile controls a medium conversion.  Its STYLE output is kept
# deterministic so a small LLM cannot reintroduce source-medium vocabulary or
# invert the selected target medium while paraphrasing it.
LOCKED_STYLE_PROFILES = frozenset({"anime_mv", "illust_to_photoreal"})

STYLE_RETENTION_POLICIES = {
    "illust_to_photoreal": (
        "`partially_preserved` Maintain described identifying elements. For "
        "characters, maintain hairstyle, hair color, eye color, outfit, color scheme, "
        "and accessories, and embody them as a physical realistic portrayal in a "
        "common prompt."
    ),
}

STYLE_SCENE_REINFORCEMENTS = {
    "illust_to_photoreal": (
        "Shoot as a photorealistic live-action video, depicting the characters as "
        "real human actors."
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
    "anime_mv": (
        "手描きセルアニメーションとして、二コマ打ち又は三コマ打ち、明瞭なキーポーズ、"
        "ポーズ・トゥ・ポーズ、短いポーズ保持及び必要部分だけの中割りを使う。各Shot固有の"
        "仕草は予備動作、主動作、反動、収束が読める身体演技とし、髪、衣装及び可動する"
        "身体付属物は主動作より少し遅れて追従する。リップシンクと身体のコマ打ちは独立させる。"
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
    "anime_mv": (
        "アニメMVのcutごとに歌詞、身体演技及び感情へ適した画角、視点及び撮影方法を選ぶ。"
        "establishing、full、medium、close-up、detail、over-shoulder及び後方三分の四の構図を"
        "使い分け、static、pan、tilt、push、pull、truck、pedestal、tracking又はarcはShotの"
        "目的が必要とする場合だけ使う。連続Shotで同じ画角、方向又は移動形式を反復せず、"
        "移動が不要なら静止構図とcutを選ぶ。arc又はclose-upを全体へ一律に要求しない。"
    ),
}

DIRECTION_PRESETS = {
    "anime_emotional": (
        "reference_anime",
        "anime_mv",
        "anime_mv",
    ),
    "cinematic_anime_mv": (
        "anime_mv",
        "anime_mv",
        "anime_mv",
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
