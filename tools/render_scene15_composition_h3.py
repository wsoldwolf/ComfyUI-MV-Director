"""Submit the frozen Scene 15 three-way H3 comparison sequentially."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import time
from urllib.request import Request, urlopen


DEST = Path(
    r"E:\ComfyUI\projects\ComfyUI-MV-Director-research\docs\assets\research"
    r"\gemma4-31b-composition-audit-h3-s15-2026-09-25"
)
BASE = "http://127.0.0.1:8188"
VARIANTS = ("current", "retry_choice", "without_composition")


def get_json(path: str) -> dict:
    with urlopen(BASE + path, timeout=30) as response:
        return json.load(response)


def write_json(path: Path, value: object) -> None:
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=DEST)
    parser.add_argument("--variants", nargs="+", default=VARIANTS)
    args = parser.parse_args()
    for variant in args.variants:
        target = args.root / variant
        manifest = json.loads((target / "h3-manifest.json").read_text(encoding="utf-8"))
        graph = json.loads((target / "h3-api-prompt.json").read_text(encoding="utf-8"))
        run_name = manifest["run_name"]
        request = Request(
            BASE + "/prompt",
            data=json.dumps({"prompt": graph, "client_id": run_name},
                            ensure_ascii=False).encode("utf-8"),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urlopen(request, timeout=120) as response:
            submission = json.load(response)
        write_json(target / "h3-submission.json", submission)
        print(f"submitted {variant}: {submission}", flush=True)
        if submission.get("node_errors"):
            raise RuntimeError(f"Node errors for {variant}: {submission['node_errors']}")
        prompt_id = submission["prompt_id"]
        started = time.monotonic()
        last_update = 0.0
        while True:
            history = get_json(f"/history/{prompt_id}")
            if prompt_id in history:
                record = history[prompt_id]
                write_json(target / "h3-history.json", record)
                status = record.get("status", {})
                print(f"finished {variant}: status={status.get('status_str')} "
                      f"elapsed={time.monotonic()-started:.1f}s", flush=True)
                if status.get("status_str") != "success":
                    raise RuntimeError(f"H3 failed for {variant}: {status}")
                break
            elapsed = time.monotonic() - started
            if elapsed > 1800:
                raise TimeoutError(f"H3 timed out for {variant}")
            if elapsed - last_update > 30:
                queue = get_json("/queue")
                print(f"waiting {variant}: elapsed={elapsed:.0f}s "
                      f"running={len(queue.get('queue_running', []))}", flush=True)
                last_update = elapsed
            time.sleep(5)


if __name__ == "__main__":
    main()
