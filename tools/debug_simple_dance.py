"""Research dance comparisons: short author-written sentences, no LLM or Compiler."""
from __future__ import annotations
import argparse
from copy import deepcopy
import hashlib
from pathlib import Path
import shutil
import sys
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from tools.prepare_beat_motion_h3 import read, save, replace_scene_prose, finalize
from tools.prepare_instrumental_h3 import render

JAPANESE = "人物は伴奏に合わせて、剣を右手に保持したまま踊る。"
ENGLISH = "The character dances to the music while keeping the sword held in the right hand."
EXPANSIVE_JAPANESE = "人物は大きな横への踏み替え、明確な全身の荷重移動、左腕の広い弧の動きで力強く踊る。剣は右手でしっかり保持する。"
EXPANSIVE_ENGLISH = "The character performs an energetic full-body dance with broad side steps, clear weight shifts, and sweeping movements of the left arm, while keeping the sword firmly held in the right hand."
TORSO_JAPANESE = "人物は感情を込めて踊り、体幹を捻りながら肩と骨盤を連動させて流れるように向きを変える。左腕を弧状に動かし、剣は右手でしっかり保持する。"
TORSO_ENGLISH = "The character dances expressively, twisting the torso and letting the shoulders and hips turn in coordinated flowing motions, while sweeping the left arm and holding the sword firmly in the right hand."
PIVOT_JAPANESE = "人物は感情を込めて踊り、流れる体幹の捻りとピボットを伴う踏み替えで身体の向きを滑らかに変える。肩・骨盤・足が連動し、左腕を弧状に動かしながら剣を右手でしっかり保持する。"
PIVOT_ENGLISH = "The character dances expressively with flowing torso twists and pivoting steps, smoothly turning the body and changing direction as the shoulders, hips, and feet move together, while sweeping the left arm and holding the sword firmly in the right hand."
GRACEFUL_JAPANESE = "人物はゆっくり優雅に踊り、落ち着いた踏み替えと穏やかな足のピボットで全身を滑らかに回す。腰と肩が流れるように続き、左腕をゆったり弧状に動かしながら剣を右手でしっかり保持する。"
GRACEFUL_ENGLISH = "The character performs a slow, graceful dance, using measured steps and gentle foot pivots to turn the whole body smoothly. The hips and shoulders follow in flowing motion, and the left arm sweeps unhurriedly while the sword remains firmly held in the right hand."
CONCRETE_JAPANESE = "人物は正面を向いて始め、右足へ体重を移し、左足を小さく踏み替えて身体をゆっくり斜め向きに回す。腰に続いて肩が向きを変え、左腕が弧を描く。剣は右手でしっかり保持する。"
CONCRETE_ENGLISH = "Starting facing the camera, the character shifts weight onto the right foot, takes a small step with the left foot, and slowly turns into a three-quarter stance. The hips turn first, followed by the shoulders, while the left arm traces an arc. The sword stays firmly held in the right hand."
CONTINUOUS_JAPANESE = "人物はShot全体でゆっくり踊り続ける。左右の足へ体重を受け渡し、落ち着いた踏み替えを連ねながら緩い弧に沿って全身の向きを変える。各踏み替えが次へつながり、腰と肩が続き、左腕が連続した弧を描く。剣は右手でしっかり保持する。"
CONTINUOUS_ENGLISH = "The character keeps dancing slowly throughout the shot. Weight flows from one foot to the other as successive measured steps turn the whole body along a gentle arc. Each step leads into the next, with the hips and shoulders following and the left arm tracing a continuous sweep. The sword remains firmly held in the right hand."
TURNING_JAPANESE = "人物はShot全体でゆっくり踊り続ける。小さな踏み替えを連ね、足の動きによって全身が正面から横向きへ徐々に回る。各踏み替えが次へつながり、腰と肩が同じ方向へ続き、左腕が連続した弧を描く。剣は右手でしっかり保持する。"
TURNING_ENGLISH = "The character keeps dancing slowly throughout the shot. With successive small steps, the feet progressively turn the whole body from facing the camera toward a side-on view. Each step leads into the next, with the hips and shoulders following in the same direction and the left arm tracing a continuous sweep. The sword remains firmly held in the right hand."
HALF_TURN_JAPANESE = "人物はShot全体でゆっくりと回転するダンスを踊る。小さな踏み替えを連ね、一方向へ滑らかに半回転し、正面、横顔、背中が順に見える。腰と肩が一緒に回り、左腕が流れる弧を描き、回転中も踏み替えを続ける。剣は右手でしっかり保持する。"
HALF_TURN_ENGLISH = "The character performs a slow turning dance throughout the shot. Successive small steps carry the body through a smooth half-turn in one direction, showing the front, then the profile, then the back. The hips and shoulders turn together while the left arm traces a flowing arc, and the stepping continues throughout the turn. The sword remains firmly held in the right hand."
MOMENTUM_JAPANESE = "人物は短く膝を曲げて荷重を溜め、踏み替えを連ねて一方向へ勢いよく半回転し、正面、横顔、背中が順に見える。腰が先行して肩が続き、左腕が弧を描き、袖と袴が回転に遅れて流れる。回転の動きをその後の踏み替えにつなぎ、踊り続ける。剣は右手でしっかり保持する。"
MOMENTUM_ENGLISH = "The character briefly bends the knees and settles the weight, then drives successive steps into a decisive half-turn in one direction, showing the front, then the profile, then the back. The hips lead and the shoulders follow, while the left arm sweeps and the sleeves and hakama skirt trail the turn. The character carries the motion into continued dancing steps after the turn. The sword remains firmly held in the right hand."


def replace_body(plan, old, new):
    if not old or not new or old == new or len(plan["shots"]) != 1:
        raise ValueError("Expected a distinct body in an isolated Scene")
    result = deepcopy(plan)
    lines = result["shots"][0]["prompt"]
    if sum(line.count(old) for line in lines) != 1:
        raise ValueError("Performance is not unique in delivered prompt")
    result["shots"][0]["prompt"] = [line.replace(old, new) for line in lines]
    normalized = deepcopy(result)
    normalized["shots"][0]["prompt"] = [line.replace(new, old) for line in normalized["shots"][0]["prompt"]]
    if normalized != plan:
        raise ValueError("Body replacement changed other data")
    return result


def prepare(args):
    source, dest = args.source.resolve(strict=True), args.output.resolve()
    if dest.exists() and any(dest.iterdir()):
        raise ValueError("Use a fresh destination")
    manifest = read(source / "h3-manifest.json")
    evidence = read(source / "media-checks.json")
    expansive = args.expansive
    torso = args.torso
    pivot = args.pivot
    graceful = args.graceful
    concrete = args.concrete
    continuous = args.continuous
    turning = args.turning
    half_turn = args.half_turn
    momentum = args.momentum
    base_label = "dance" if expansive or torso or pivot or graceful or concrete or continuous or turning or half_turn or momentum else "baseline"
    if not manifest.get("subject_only_correction_verified") or not Path(evidence["videos"][base_label]["path"]).is_file():
        raise ValueError("Requires completed clothing-corrected baseline")
    baseline = read(source / f"{base_label}-plan.json")
    if momentum:
        old, english, japanese = HALF_TURN_ENGLISH, MOMENTUM_ENGLISH, MOMENTUM_JAPANESE
        titles = ["Half Turn Dance", "Momentum Turn"]
        run = "momentum-turn-b12-momiji2-s11-20261004"
    elif half_turn:
        old, english, japanese = CONTINUOUS_ENGLISH, HALF_TURN_ENGLISH, HALF_TURN_JAPANESE
        titles = ["Continuous Dance", "Half Turn Dance"]
        run = "half-turn-dance-b11-momiji2-s11-20261004"
    elif turning:
        old, english, japanese = CONTINUOUS_ENGLISH, TURNING_ENGLISH, TURNING_JAPANESE
        titles = ["Continuous Dance", "Turning Dance"]
        run = "turning-dance-b10-momiji2-s11-20261004"
    elif continuous:
        old, english, japanese = CONCRETE_ENGLISH, CONTINUOUS_ENGLISH, CONTINUOUS_JAPANESE
        titles = ["Concrete Turn", "Continuous Dance"]
        run = "continuous-dance-b9-momiji2-s11-20261004"
    elif concrete:
        old, english, japanese = GRACEFUL_ENGLISH, CONCRETE_ENGLISH, CONCRETE_JAPANESE
        titles = ["Graceful Dance", "Concrete Turn"]
        run = "concrete-turn-b8-momiji2-s11-20261004"
    elif graceful:
        old, english, japanese = PIVOT_ENGLISH, GRACEFUL_ENGLISH, GRACEFUL_JAPANESE
        titles = ["Pivot Dance", "Graceful Dance"]
        run = "graceful-dance-b7-momiji2-s11-20261003"
    elif pivot:
        old, english, japanese = TORSO_ENGLISH, PIVOT_ENGLISH, PIVOT_JAPANESE
        titles = ["Torso Dance", "Pivot Dance"]
        run = "pivot-dance-b6-momiji2-s11-20261003"
    elif torso:
        old, english, japanese = EXPANSIVE_ENGLISH, TORSO_ENGLISH, TORSO_JAPANESE
        titles = ["Expansive Dance", "Torso Dance"]
        run = "torso-dance-b5-momiji2-s11-20261003"
    elif expansive:
        old, english, japanese = ENGLISH, EXPANSIVE_ENGLISH, EXPANSIVE_JAPANESE
        titles = ["Simple Dance", "Expansive Dance"]
        run = "expansive-dance-b4-momiji2-s11-20261003"
    else:
        old = next(row["restored"] for row in read(source / "baseline-translation.json")
                   if row["field_id"] == "scene.10.shot.0.body.1")
        english, japanese = ENGLISH, JAPANESE
        titles = ["Baseline", "Simple Dance"]
        run = "simple-dance-b3-momiji2-s11-20261003"
    candidate = replace_body(baseline, old, english)
    camera = read(Path(manifest["source_b1"]) / "input-contract.json")["camera"]
    dest.mkdir(parents=True)
    for source_name, target_name in ((f"{base_label}.md", "baseline.md"),
                                   (f"{base_label}-plan.json", "baseline-plan.json"),
                                   (f"h3-{base_label}.json", "h3-baseline.json"),
                                   (f"render-{base_label}.json", "render-baseline.json")):
        shutil.copy2(source / source_name, dest / target_name)
    display_emd = replace_scene_prose((source / f"{base_label}.md").read_text(encoding="utf-8"), japanese, camera)
    (dest / "dance.md").write_text(display_emd, encoding="utf-8")
    (dest / "dance-excerpt.md").write_text(
        f"# Scene 11の研究用演技\n\n* `演技` {japanese}\n* `カメラ` {camera}\n\n"
        f"## H3へ実際に渡した演技文\n\n{english}\n\n"
        "研究側が記述してPlanへ直接置換した文。LLM出力・Compiler翻訳結果ではない。\n", encoding="utf-8")
    save(dest / "dance-plan.json", candidate)
    graph = read(source / f"h3-{base_label}.json")
    import json
    for key in ("24", "37", "48"):
        graph[key]["inputs"]["plan_json"] = json.dumps(candidate, ensure_ascii=False)
    graph["24"]["inputs"]["run_name"] = run
    graph["21"]["inputs"]["filename"] = run
    save(dest / "h3-dance.json", graph)
    names = {"baseline": manifest["run_names"][base_label], "dance": run}
    save(dest / "h3-manifest.json", {**manifest, "source_baseline": str(source), "run_names": names,
        "comparison_labels": ["baseline", "dance"],
        "comparison_titles": titles,
        "comparison": "body-only direct English replacement; no beat timestamps",
        "research_authored_prose": True, "planner_rerun": False, "compiler_used": False,
        "new_render_count": 1, "baseline_render_reused": True})
    save(dest / "input-contract.json", {"old_performance_english": old, "new_performance_english": english,
        "japanese_display_only": japanese, "plan_body_only_verified": True,
        "baseline_plan_sha256": hashlib.sha256((source / f"{base_label}-plan.json").read_bytes()).hexdigest(),
        "held_fixed": ["Subject including hakama", "Event", "Camera", "seed", "PCM", "length", "render settings"]})
    print("Dance comparison prepared on CPU; baseline reused; one new render only", flush=True)


if __name__ == "__main__":
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("task", choices=("prepare", "render", "finalize"))
    p.add_argument("--source", type=Path)
    p.add_argument("--output", type=Path, required=True)
    p.add_argument("--url", default="http://127.0.0.1:8191")
    variants = p.add_mutually_exclusive_group()
    variants.add_argument("--expansive", action="store_true", help="Compare larger movements against completed simple dance")
    variants.add_argument("--torso", action="store_true", help="Compare torso turns against completed expansive dance")
    variants.add_argument("--pivot", action="store_true", help="Compare pivoting steps against completed torso dance")
    variants.add_argument("--graceful", action="store_true", help="Compare slow graceful turns against completed pivot dance")
    variants.add_argument("--concrete", action="store_true", help="Compare a concrete weight shift and turn against completed graceful dance")
    variants.add_argument("--continuous", action="store_true", help="Compare ongoing connected steps against completed concrete turn")
    variants.add_argument("--turning", action="store_true", help="Compare a foot-driven turn toward side-on against completed continuous dance")
    variants.add_argument("--half-turn", action="store_true", help="Compare a front-profile-back turning sequence against completed continuous dance")
    variants.add_argument("--momentum", action="store_true", help="Compare a prepared, accented half-turn against completed half-turn dance")
    args = p.parse_args()
    if args.task == "prepare":
        if not args.source:
            p.error("prepare requires --source")
        prepare(args)
    elif args.task == "render":
        render(args.output, "dance", args.url)
    else:
        finalize(args)
