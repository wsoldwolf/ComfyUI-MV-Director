"""Extract the saved ComfyUI prompt, workflow and H3 plan from one MP4."""

import argparse
import json
from pathlib import Path
import subprocess


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--video", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--ffprobe", default="ffprobe")
    args = parser.parse_args()
    if args.output.exists():
        raise ValueError("Use a new metadata output path")
    completed = subprocess.run(
        [args.ffprobe, "-v", "error", "-show_entries",
         "format_tags=prompt,workflow,h3_plan", "-of", "json", str(args.video)],
        capture_output=True, text=True, encoding="utf-8", check=True,
    )
    tags = json.loads(completed.stdout)["format"]["tags"]
    result = {name: json.loads(tags[name]) for name in ("prompt", "workflow", "h3_plan")}
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"saved metadata: {args.output}; scenes={len(result['h3_plan']['shots'])}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
