"""Submit the frozen Scene 2–4 audio-reference graph with Gemma body Plan."""

from __future__ import annotations

import json
from pathlib import Path
from urllib.request import Request, urlopen


ROOT = Path(__file__).resolve().parents[1]
FIXTURE = ROOT / "docs/assets/research/gemma4-31b-scene-author-s2-4-2026-09-25"
BASELINE_GRAPH = Path(
    r"C:\Software\ComfyUI\output\h3_chains\audio_ref_body_s2_4_context_20260924\api_prompt.json"
)
RUN_NAME = "gemma4_31b_body_s2_4_20260925"


def main() -> None:
    graph = json.loads(BASELINE_GRAPH.read_text(encoding="utf-8"))
    plan_text = (FIXTURE / "gemma-body-scene3-4-plan.json").read_text(encoding="utf-8")
    plan = json.loads(plan_text)
    assert len(plan["shots"]) == 16
    assert graph["48"]["class_type"] == "MVDirectorSceneDebugSplitter"
    assert graph["48"]["inputs"]["scene_start"] == 2
    assert graph["48"]["inputs"]["scene_length"] == 3
    assert graph["48"]["inputs"]["enable"] is True
    assert graph["24"]["inputs"]["plan_json_input"] == ["48", 0]
    graph["48"]["inputs"]["plan_json"] = plan_text
    graph["24"]["inputs"]["run_name"] = RUN_NAME
    graph["21"]["inputs"]["filename"] = RUN_NAME
    output = FIXTURE / "submitted-api-prompt.json"
    if output.exists():
        raise FileExistsError(output)
    output.write_text(json.dumps(graph, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    data = json.dumps({"prompt": graph, "client_id": RUN_NAME}).encode("utf-8")
    request = Request(
        "http://127.0.0.1:8188/prompt",
        data=data,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urlopen(request, timeout=120) as response:
        result = json.load(response)
    (FIXTURE / "submission-response.json").write_text(
        json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    print(json.dumps(result, ensure_ascii=False))


if __name__ == "__main__":
    main()
