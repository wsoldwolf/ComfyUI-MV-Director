"""Prepare the loop-2 P0 comparison fixture; no runtime prompt repair.

Only the two known profile-owned prefix fields are replaced. The full saved
plan, identity, environment, local actions/cameras and timing stay unchanged.
"""
import argparse
import copy
import hashlib
import json
from pathlib import Path

parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument("--plan", type=Path, required=True)
parser.add_argument("--translation-evidence", type=Path, required=True)
parser.add_argument("--output", type=Path, required=True)
args = parser.parse_args()
plan = json.loads(args.plan.read_text(encoding="utf-8-sig"))
trace = json.loads(args.translation_evidence.read_text(encoding="utf-8-sig"))["translation_trace"]
by_field = {row["field_id"]: row for row in trace}
prefix = plan["prompt_prefix"]
if len(prefix) != 13 or not prefix[11].startswith("Hand-drawn cel animation") or not prefix[12].startswith("As an animated MV"):
    raise ValueError("not the reviewed loop-2 prefix fixture")
revised = copy.deepcopy(plan)
changes = []
for index, field in ((11, "common.モーション.0"), (12, "common.カメラ.0")):
    text = by_field[field]["restored"]
    revised["prompt_prefix"][index] = text
    changes.append({"prefix_index": index, "translation_field": field,
                    "before_sha256": hashlib.sha256(prefix[index].encode()).hexdigest(),
                    "before_chars": len(prefix[index]), "after_chars": len(text)})
args.output.parent.mkdir(parents=True, exist_ok=True)
args.output.write_text(json.dumps(revised, ensure_ascii=False, indent=2), encoding="utf-8")
print(json.dumps(changes, ensure_ascii=False))
