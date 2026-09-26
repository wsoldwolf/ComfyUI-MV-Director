"""Current Scene Author input and fake backend; independent of test modules."""

import json

from core.inference import LlamaRuntimeConfig

CONCEPT = "# サブジェクト\n* 一人の歌手。\n"
TEMPLATE = (
    "> `シーン` 1\n"
    "# シーン 00:00.000 --> 00:01.000\n"
    "* `H3長` 22\n"
    "## ショット 00:00.000\n"
    "* `演出` 木の根元に苔がある。\n"
    "* `演技` 人物が片手を胸元に置く。\n"
    "* `カメラ` 目と口が見える正面。\n"
    "## ショット 00:00.500\n"
    "* 未計画\n"
)


class Backend:
    def __init__(self):
        self.calls = []

    def complete_planner(self, *, task, payload, **_kwargs):
        request = json.loads(payload)
        self.calls.append((task, request))
        if task == "scene-author-composition-choice":
            return f"CHOICE\t1\t{request['current_choice']}"
        kind = {
            "scene-author-event": "EVENT",
            "scene-author-performance": "PERFORMANCE",
            "scene-author-camera": "CAMERA",
        }[task]
        return "\n".join(
            f"{kind}\t{slot['slot']}\t"
            + {
                "EVENT": (
                    "歌詞に応じて花が揺れる。"
                    if slot.get("shot") == 1 else "なし"
                ),
                "PERFORMANCE": "胸から腕へ動きを渡し、手を離す。",
                "CAMERA": "Arc Shotで腕と表情を追う。",
            }[kind]
            + {
                "EVENT": "｜END_STATE=花は風に揺れている。",
                "PERFORMANCE": "｜END_STATE=両足支持、右腕は低く、視線は前。",
                "CAMERA": "｜END_STATE=正面寄り、右回りのArc終点。",
            }[kind]
            for slot in request["slots"]
        )


def _runtime():
    return LlamaRuntimeConfig(max_tokens=512, n_ctx=8192)
