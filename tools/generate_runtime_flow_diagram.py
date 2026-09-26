"""Generate the documented current Scene Author flow (not a proposal)."""
from html import escape
from pathlib import Path

OUT = Path(__file__).resolve().parents[1] / "docs/assets/direction-planner-flow.svg"
COLORS = {
    "input": ("#fff4df", "#b7791f"),
    "llm": ("#e7f1ff", "#3977b8"),
    "python": ("#eaf8ef", "#3a8b58"),
    "artifact": ("#f2eafe", "#7950a8"),
}


def build() -> str:
    rows = ['<svg xmlns="http://www.w3.org/2000/svg" width="2000" height="1220" viewBox="0 0 2000 1220" role="img" aria-labelledby="title desc">',
            '<title id="title">Gemma4によるDirectionとScene Authorの現行処理フロー</title>',
            '<desc id="desc">共通指示と演出候補を分離し、SceneごとにEvent、Performance、Cameraを順に生成する。明示Shot指示を保持し、profileによる補完と再選択を区別する。終端状態は継続Sceneだけへ引き継ぐ。</desc>',
            '<defs><marker id="arrow" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="7" markerHeight="7" orient="auto"><path d="M0 0L10 5L0 10Z" fill="#526273"/></marker></defs>',
            '<style>text{font-family:"Yu Gothic UI",Meiryo,sans-serif;fill:#25364a;text-anchor:middle} .edge{fill:none;stroke:#526273;stroke-width:3;marker-end:url(#arrow)} .dash{stroke-dasharray:9 7}</style>',
            '<rect width="2000" height="1220" fill="#f8fafc"/>']

    def text(x, y, value, size=19, weight=400):
        rows.append(f'<text x="{x}" y="{y}" font-size="{size}" font-weight="{weight}">{escape(value)}</text>')

    def box(x, y, w, h, kind, title, lines):
        fill, stroke = COLORS[kind]
        rows.append(f'<rect x="{x}" y="{y}" width="{w}" height="{h}" rx="14" fill="{fill}" stroke="{stroke}" stroke-width="2"/>')
        text(x+w/2, y+34, title, 23, 700)
        for i, line in enumerate(lines):
            text(x+w/2, y+64+27*i, line)

    def edge(path, dashed=False):
        rows.append(f'<path class="edge{" dash" if dashed else ""}" d="{path}"/>')

    text(1000, 44, "Direction Enhancer → Scene Author → EMD Compiler", 30, 700)
    text(1000, 78, "現行dev WF：Gemma4 31B Q4_K_S / Motion = anime_scene_composed_mv", 21)
    text(1000, 112, "橙：入力　青：LLM　緑：Python　紫：保存・受け渡す成果", 18)
    box(40, 150, 370, 165, "input", "入力とprofile", ["人物Concept / 背景Scene EMD", "# 共通プロンプト / # 演出候補", "Style / Motion / Camera profile"])
    box(470, 150, 400, 165, "python", "構文・authorityを分離", ["共通指示はDirectionへ", "演出候補は原文のまま迂回", "明示指示をVision baselineより優先"])
    box(930, 150, 410, 165, "llm", "Direction Enhancer · 31B", ["未固定の全体方針だけを生成", "locked profileはPythonが保持", "行protocol検証・欠落の局所retry"])
    box(1400, 150, 550, 165, "artifact", "MVD_DIRECTION_V4", ["全体方針 / profile / provenance", "演出候補の原文を別フィールドで保持", "+ 編集用Direction preview EMD"])
    edge("M410 232H470")
    edge("M870 232H930")
    edge("M1340 232H1400")
    edge("M670 315V345H1675V315", True)
    text(1110, 338, "演出候補はDirection LLMへ投入しない", 17)

    box(40, 410, 370, 210, "input", "Scene入力", ["歌詞整列済みTemplate EMD", "Scene / Shot / 歌詞時刻", "Concept / Scene EMD / Direction", "ユーザー確定Shot指示", "H3 Timing Profile / seed"])
    box(470, 410, 400, 210, "python", "Sceneごとに準備", ["現在Scene + 歌詞section文脈", "Shot位置と時刻を保持", "固定の演出・演技・Cameraを保護", "CONTINUE時だけ前Scene状態", "候補：optional / prefer_matched"])
    edge("M410 515H470")
    edge("M1675 315V370H670V410", True)

    box(930, 410, 410, 210, "llm", "1. EVENT · 31B", ["出来事・対象・外部effectを計画", "歌詞と演出候補を参照", "全Shotを一Sceneとして要求", "採用Eventを後段へ明示", "末尾END_STATEを分離・記録"])
    box(1400, 410, 550, 210, "llm", "2. PERFORMANCE · 31B", ["Eventを読んで身体・表情を計画", "演出候補とMotion方針も参照", "固定演技のShotは生成しない", "LLM原文は保持", "演技の終端状態を記録"])
    edge("M870 515H930")
    edge("M1340 515H1400")

    box(1400, 710, 550, 190, "llm", "3. CAMERA · 31B", ["採用Eventと演技に合わせて撮影", "Camera方針 / 演出候補を参照", "固定CameraのShotは生成しない", "Cameraの終端状態を記録"])
    box(930, 710, 410, 190, "python", "任意のモーション補完", ["profileが有効化したSceneだけ", "pre_author / post_authorを区別", "必要時だけLLMで候補を再選択", "直接指定された確定演技は保護"])
    box(470, 710, 400, 190, "python", "検証・Renderer", ["構造grammar + 有限retry", "LLM原文と補完の出所を区別", "時刻 / 参照 / 歌詞を構造統合", "歌唱・lip-sync directiveを配置"])
    box(40, 710, 370, 190, "artifact", "完成EMD", ["演出 / 演技 / Camera", "モーション補完注釈・歌詞時刻", "Subject / Scene / Direction", "利用者が確認・編集可能"])
    edge("M1675 620V710")
    edge("M1400 805H1340")
    edge("M930 805H870")
    edge("M470 805H410")
    edge("M1950 805H1975V950H445V390H670V410", True)
    text(915, 940, "CONTINUE：Event / Performance / Cameraの終端状態を次Sceneへ", 18)

    box(40, 1000, 830, 150, "llm", "EMD Compiler · 31B", ["翻訳対象fieldのみ英訳 / 予約directiveは機械処理", "構造検証 → Context Loop Plan JSON → .txt保存境界", "Video段階：H3 Hybrid Loader + Context Loop標準Lip Sync"])
    edge("M225 900V1000")
    box(930, 1000, 1020, 150, "artifact", "経路の区別", ["図は現行Scene Author経路。旧Cue / Visual Beat / Actions / Auditは別経路", "任意の候補再選択は監査分類器ではなく、既存の補完候補を選び直す処理", "必須protocol回復不能時は停止。自然さ・演出・同期の最終判定は人間"])
    text(1000, 1190, "時刻契約：Context Loop 0.7.0 @ d80304f / ComfyUI 0.37.2 @ 830232b", 18)
    return "\n".join(rows + ["</svg>"]) + "\n"


if __name__ == "__main__":
    OUT.write_text(build(), encoding="utf-8")
