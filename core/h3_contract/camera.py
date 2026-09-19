"""Stable EMD editorial phrases and their deterministic H3 renderings."""

FACE_PERFORMANCE_CUT_ACTION = (
    "顔の演技だけを行い、歩行、足運び、走行又は全身移動を行わない。"
    "主役一人だけが歌詞に対応する表情で歌い、両目、眉及び口全体を使う。"
    "手、小物及び髪は顔を隠さない。既に定義された眉の個数、短さ、形、配置及び色を維持し、"
    "特殊な眉を通常の長い線状又は弓状眉へ置換しない。"
)
FACE_PERFORMANCE_CUT_CAMERA = (
    "Zoom In with large amplitude at fast speed 正面又は斜め正面の頭肩歌唱構図から、"
    "Shotの大部分を使って主役一人の極端な顔close-upへ進む。全行程で両目、両眉、鼻、"
    "完全な歌唱口及び表情を読める顔輪郭を同時に残す。終端では両目を上半分、完全な歌唱口を"
    "下半分へ収め、胴体、足及び背景の大部分は終端近くでだけframe外へ出す。"
)
ANIME_EMOTIONAL_FACE_PERFORMANCE_CUT_CAMERA = (
    "Zoom In with large amplitude at fast speed 正面又は斜め正面の頭肩歌唱構図から、"
    "Shotの35%から55%で主役一人の読み取れる顔close-upへ進む。全行程で両目、両眉、鼻、"
    "完全な歌唱口及び表情を読める顔輪郭を同時に残す。短い閉眼、半開き、伏し目又は再開眼を"
    "読めるようにし、両目を常に全開へ固定しない。終端scaleは短い表情accentだけ保持し、"
    "目だけ又は口だけのcropで終えない。"
)

FACE_PERFORMANCE_CUT_ACTION_H3 = (
    "Facial performance only; no walking, stepping, running, or full-body "
    "locomotion. Only the primary subject sings with a lyric-matched expression "
    "through both eyes, eyebrows, and the complete mouth; hands, props, and hair "
    "remain below or outside the face. Animate the already-described eyebrows "
    "without changing their count, compactness, shape, placement, or color; never "
    "replace unusual eyebrow marks with conventional long, curved, arched, or "
    "line-shaped eyebrows."
)
FACE_PERFORMANCE_CUT_CAMERA_H3 = (
    "Zoom In with large amplitude at fast speed from a frontal or three-quarter "
    "head-and-shoulders singing composition to an extreme facial close-up of only "
    "the primary subject over most of the Shot; both eyes, both eyebrows, the nose, "
    "the complete singing mouth, and enough facial contour remain visible throughout; "
    "finish with both eyes in the upper half and the complete singing mouth in the "
    "lower half; crop out the torso, feet, and most of the background only near the end."
)
ANIME_EMOTIONAL_FACE_PERFORMANCE_CUT_CAMERA_H3 = (
    "Zoom In with large amplitude at fast speed from a frontal or three-quarter "
    "head-and-shoulders singing composition to a tight readable facial close-up of "
    "only the primary subject during 35-55% of the Shot; both eyes, both eyebrows, "
    "the nose, the complete singing mouth, and enough facial contour remain visible "
    "throughout; a brief close, half-open gaze, lowered gaze, or reopening remains "
    "readable without requiring both eyes to stay fully open; hold the final close "
    "scale only for a short expression accent and do not end at an eye-only or "
    "mouth-only crop."
)

__all__ = [
    "ANIME_EMOTIONAL_FACE_PERFORMANCE_CUT_CAMERA",
    "ANIME_EMOTIONAL_FACE_PERFORMANCE_CUT_CAMERA_H3",
    "FACE_PERFORMANCE_CUT_ACTION",
    "FACE_PERFORMANCE_CUT_ACTION_H3",
    "FACE_PERFORMANCE_CUT_CAMERA",
    "FACE_PERFORMANCE_CUT_CAMERA_H3",
]
