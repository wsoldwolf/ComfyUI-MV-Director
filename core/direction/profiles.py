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
LOCKED_STYLE_PROFILES = frozenset({"illust_to_photoreal"})

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
    "arc_closeup": (
        "大半のShotで、被写体を中心に前方斜めから側面へ回り込む緩やかなarcを使い、"
        "Sceneごとに時計回り・反時計回り、半径、高さを変える。歌唱の要点や表情の変化を"
        "扱うShotでは顔のclose-upを選び、目線と口元を画面内に保ちながら小さなarcで"
        "立体感を出す。その他のShotではmedium又は全身のarcで動作と背景視差を見せる。"
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
