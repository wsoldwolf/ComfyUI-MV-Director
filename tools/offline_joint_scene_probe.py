"""Exploratory joint performance/camera control, not a production Planner path."""
from __future__ import annotations
import argparse
from dataclasses import asdict, replace
import json
from pathlib import Path
import sys
import time

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from core.inference import fit_context_budget
from tools.offline_section_performance_probe import RecordingLifecycle
from core.inference import LlamaRuntimeConfig

SYSTEM = """あなたは歌唱MVの振付と撮影を一緒に設計する。原歌詞とセクションの文脈から人物の感情を読み、一つのScene全体の連続した演技を考える。歌詞の名詞を指さす説明ではなく、予備動作から主動作、反動又は解放、姿勢の立て直しへ進む身体表現を設計する。支持・体幹から腕・顔へ連動する動きを選び、明瞭に異なる終わりの姿へ至る。静けさと強いアクセントを使い分ける。各Shotを最初から演じ直さない。accepted_eventは外部の状況で、身体演技の全文指示ではない。作者固定の演出位置・時刻・演技は守る。セクション全文は理解の文脈であり、その全対象をこのSceneに登場させない。
構図、時間順の演技、カメラ経路を同時に思い描いて、各ShotにPERFORMANCEとCAMERAを一行ずつ出す。PERFORMANCEは自然な日本語で複数の時間順動作を述べる。CAMERAはその身体の変化を実際に見せる画角、始点、経路、終点を述べる。人物の自転ではなくカメラが回り込んでよい。身体を見せる時間から両目と口を含む表情へ寄ってよい。Cameraが人物の演技を隠さないようにする。
出力順はShot1のPERFORMANCE、CAMERA、Shot2のPERFORMANCE、CAMERA。各行はTYPE<TAB>slot番号<TAB>本文。出力はこの四行だけ。"""


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if args.output.exists() and any(args.output.iterdir()):
        raise ValueError("Use a fresh evidence directory")
    args.output.mkdir(parents=True, exist_ok=True)
    lifecycle = RecordingLifecycle()
    try:
        for scene in (5, 9):
            source = json.loads((args.source / f"scene{scene}-D.json").read_text(encoding="utf-8"))
            manifest = json.loads((args.source / "manifest.json").read_text(encoding="utf-8"))
            config = LlamaRuntimeConfig(**source["effective_config"])
            lifecycle.ensure_loaded(Path(manifest["model"]), config)
            payload = source["payload"]
            user = "/no_think\n" + json.dumps(payload, ensure_ascii=False, sort_keys=True)
            count = lifecycle.count_serialized_prompt(SYSTEM + "\n" + user)
            budget = fit_context_budget(count.count, config.max_tokens, config.n_ctx,
                                        minimum_output_tokens=config.max_tokens, estimated=count.estimated)
            root = ' "\\n" '.join(json.dumps(f"{kind}\t{slot}\t") + " char+"
                                  for slot in (1, 2) for kind in ("PERFORMANCE", "CAMERA"))
            grammar = "root ::= " + root + ' "\\n"?\n' + r"char ::= [^\x00-\x1f]" + "\n"
            started = time.perf_counter()
            response = lifecycle.complete_chat(
                [{"role": "system", "content": SYSTEM}, {"role": "user", "content": user}],
                replace(config, max_tokens=budget.reserved_output_tokens), grammar=grammar,
            )
            result = {"scene": scene, "system_prompt": SYSTEM, "payload": payload,
                      "effective_config": asdict(lifecycle.last_config), "prompt_tokens": count.count,
                      "elapsed_seconds": time.perf_counter() - started, "response": response,
                      "scope": "exploratory_joint_prompt_and_output_change_not_isolated_causal_test"}
            (args.output / f"scene{scene}-J.json").write_text(
                json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8",
            )
            print(f"scene={scene} tokens={count.count} elapsed={result['elapsed_seconds']:.2f}", flush=True)
    finally:
        lifecycle.clear()


if __name__ == "__main__":
    main()
