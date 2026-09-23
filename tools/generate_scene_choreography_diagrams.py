"""Generate proposal diagrams as editable SVG sources.

Render the SVGs to PNG with an SVG rasterizer (for example sharp).
This documents the proposed architecture, not the current runtime.
"""
from __future__ import annotations

from html import escape
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "docs" / "assets" / "research" / "scene-choreography-redesign-2026-09-23"
THEMES = {
    "input": ("#fff4df", "#b7791f", "#25364a"),
    "llm": ("#e7f1ff", "#3977b8", "#25364a"),
    "python": ("#eaf8ef", "#3a8b58", "#25364a"),
    "artifact": ("#f2eafe", "#7950a8", "#25364a"),
    "output": ("#263547", "#152232", "#ffffff"),
    "note": ("#ffffff", "#cbd5e1", "#475569"),
}
BLUE = "#3977b8"
GREEN = "#248458"
GREY = "#64748b"
PURPLE = "#7950a8"
ORANGE = "#b7791f"


class Diagram:
    def __init__(self, width: int, height: int, title: str, description: str):
        self.width, self.height = width, height
        self.rows = [
            f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" viewBox="0 0 {width} {height}" role="img" aria-labelledby="title desc">',
            f'<title id="title">{escape(title)}</title>',
            f'<desc id="desc">{escape(description)}</desc>',
            '<defs>',
            *[
                f'<marker id="arrow-{name}" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="7" markerHeight="7" orient="auto"><path d="M0 0L10 5L0 10Z" fill="{color}"/></marker>'
                for name, color in (("blue", BLUE), ("green", GREEN), ("grey", GREY), ("purple", PURPLE), ("orange", ORANGE))
            ],
            '<style>text{font-family:"Yu Gothic UI",Meiryo,"Noto Sans JP",sans-serif} .edge-label{paint-order:stroke;stroke:#f8fafc;stroke-width:10;stroke-linejoin:round}</style>',
            '</defs>',
            f'<rect width="{width}" height="{height}" fill="#f8fafc"/>',
        ]

    def text(self, x, y, value, size=24, weight=400, color="#475569", anchor="middle", label=False):
        klass = ' class="edge-label"' if label else ""
        self.rows.append(f'<text{klass} x="{x}" y="{y}" text-anchor="{anchor}" font-size="{size}" font-weight="{weight}" fill="{color}">{escape(value)}</text>')

    def box(self, x, y, w, h, kind, title, lines, *, size=23, line_height=35):
        fill, stroke, color = THEMES[kind]
        self.rows.append(f'<rect x="{x}" y="{y}" width="{w}" height="{h}" rx="16" fill="{fill}" stroke="{stroke}" stroke-width="2.5"/>')
        self.text(x+w/2, y+43, title, 28, 700, color)
        for i, line in enumerate(lines):
            self.text(x+w/2, y+84+i*line_height, line, size, 400, color)

    def path(self, points, kind="grey", dashed=False, arrow=True):
        colors = {"blue": BLUE, "green": GREEN, "grey": GREY, "purple": PURPLE, "orange": ORANGE}
        d = "M" + " L".join(f"{x},{y}" for x,y in points)
        extra = ' stroke-dasharray="10 9"' if dashed else ""
        if arrow:
            extra += f' marker-end="url(#arrow-{kind})"'
        self.rows.append(f'<path d="{d}" fill="none" stroke="{colors[kind]}" stroke-width="3.5" stroke-linecap="round" stroke-linejoin="round"{extra}/>')

    def legend(self, items, y):
        for x, kind, name in items:
            fill, stroke, _ = THEMES[kind]
            self.rows.append(f'<rect x="{x}" y="{y-18}" width="26" height="22" rx="4" fill="{fill}" stroke="{stroke}" stroke-width="2"/>')
            self.text(x+39, y, name, 22, anchor="start")

    def save(self, name):
        OUT.mkdir(parents=True, exist_ok=True)
        (OUT / name).write_text("\n".join([*self.rows, "</svg>"]) + "\n", encoding="utf-8")


def pipeline():
    d = Diagram(2260, 1650, "Scene振付の再設計：通常経路（提案）",
                "同じ8Bを順次呼び出し、出来事、最終振付原文、撮影と時間割当をScene単位で計画する。出来事と演技の原文は保存され、撮影担当は参照で割り当てる。Pythonは原文参照と時刻を検証してEMDへ出力する。採用した終端を次Sceneへ渡す。")
    d.text(1130, 57, "Scene振付の再設計 ─ 通常経路", 38, 700, "#172333")
    d.text(1130, 99, "提案・未実装  /  同じ8Bを順次使用  /  全自動時は通常3呼出しが目標  /  手書き確定範囲は生成を省略", 23)
    d.legend([(160,"input","原資料"),(490,"llm","LLM：生成・選択"),(930,"artifact","原文・計画の保存"),(1410,"python","Python：構造処理"),(1870,"output","完成物")], 158)

    d.box(100, 215, 2000, 150, "input", "Scene N の原資料（共通EMD解析・ユーザー優先の解決結果）", [
        "原歌詞・時刻・Scene尺  /  作者の共通指示・任意候補・確定本文  /  人物・背景  /  profile既定値",
        "前Sceneの採用済み終端：身体・支持位置・残る現象・Camera方向",
    ], size=25, line_height=36)
    d.path([(1100,365),(1100,435)], "blue", arrow=False)
    d.path([(350,435),(1850,435)], "blue", arrow=False)
    for x in (350,1100,1850):
        d.path([(x,435),(x,515)], "blue")
    d.text(740,418,"原文を直接入力",22,600,BLUE,label=True)

    d.box(100,515,500,220,"llm","A  出来事・解釈",[
        "歌詞をどう見せるかを決める",
        "対象の配置・変化・必要な接触",
        "出力：出来事原文 E（対象なしも可）",
        "作者の確定項目は再生成しない",
    ],size=23,line_height=36)
    d.box(850,515,500,220,"llm","B  Scene全体の振付",[
        "原歌詞 + Motion + 出来事 E を読む",
        "始点 → 身体の進行 → 終端",
        "出力：最終演技原文 B と終端状態",
        "未指定の演技だけを生成する",
    ],size=23,line_height=36)
    d.box(1600,515,500,220,"llm","C  撮影・時間割当",[
        "出来事 E と演技 B の原文を読む",
        "見せ場に合わせてShot・Cameraを設計",
        "出力：参照・時刻・Camera原文",
        "作者の固定Camera・時刻も守る",
    ],size=23,line_height=36)
    d.path([(600,622),(850,622)],"purple")
    d.text(725,593,"E を参照",22,600,PURPLE,label=True)
    d.path([(1350,622),(1600,622)],"purple")
    d.text(1475,580,"E + B を参照",22,600,PURPLE,label=True)
    d.text(1475,660,"原文のまま",21,400,PURPLE,label=True)

    d.path([(350,735),(350,865)],"green")
    d.path([(1100,735),(1100,865)],"green")
    d.text(725,809,"生成時に原文を保存",24,600,GREEN)
    d.path([(1850,735),(1850,865)],"purple")
    d.text(1850,809,"撮影・割当結果を保存",23,600,PURPLE,label=True)

    d.box(100,865,1250,165,"artifact","出来事・演技の原文ストア",[
        "E：出来事原文   /   B：演技原文   /   作者本文も保持   /   出典・範囲・revision",
        "撮影LLMの要約を経由せず、保存した文章をEMDへ直接渡す",
    ],size=25,line_height=37)
    d.box(1600,865,500,165,"artifact","SceneSchedule",[
        "Shot時刻 + E/Bの参照",
        "Camera原文 + 継続方法・終端",
    ],size=23,line_height=37)

    d.path([(725,1030),(725,1085),(1000,1085),(1000,1135)],"green")
    d.text(655,1080,"E/B原文",22,600,GREEN,label=True)
    d.path([(1850,1030),(1850,1085),(1300,1085),(1300,1135)],"purple")
    d.text(1620,1070,"参照・時刻・Camera",22,600,PURPLE,label=True)
    d.box(850,1135,600,165,"python","Python：検証・原文参照の解決",[
        "ID・順序・時刻・revisionを検証",
        "選ばれた原文をそのまま並べる（AS IS）",
    ],size=24,line_height=38)
    d.path([(1450,1217),(1600,1217)],"green")
    d.box(1600,1135,500,165,"output","Scene N を採用",[
        "EMD + trace + 採用済み終端",
        "Scene単位で保存・再開可能",
    ],size=23,line_height=38)

    d.path([(2100,1217),(2185,1217),(2185,290),(2100,290)],"grey")
    d.text(2140,815,"次",24,600)
    d.text(2140,850,"の",24,600)
    d.text(2140,885,"Scene",22,600)
    d.text(2140,920,"へ",24,600)
    d.path([(1850,1300),(1850,1345),(350,1345),(350,1395)],"grey")
    d.text(610,1334,"全Sceneが揃ったら出力",23,600,label=True)

    d.box(100,1395,500,120,"output","完成EMD",["出来事・演技・Cameraの原文"],size=23)
    d.path([(600,1455),(850,1455)],"grey")
    d.box(850,1395,500,120,"llm","Compiler（LLM + Python）",["英訳・H3 Plan JSON・翻訳trace"],size=23)
    d.path([(1350,1455),(1600,1455)],"grey")
    d.box(1600,1395,500,120,"output","H3 動画生成",["同条件の短区間比較で品質を確認"],size=23)

    d.text(1100,1575,"緑の経路：採用原文を保持して運ぶ。作者の手書き本文は別図の共通入力経路から直接採用できる。",24,600,GREEN)
    d.text(1100,1615,"全手書きならA/B/Cを省略。ユーザー優先はCompilerまで共通契約として適用する。",22)
    d.save("scene-choreography-pipeline.svg")


def repair():
    d=Diagram(2060,1120,"Scene振付の再設計：診断・局所修正（提案）",
              "構造検証は必須、意味診断は任意。Sceneの原文と計画を保存して構造を検証する。意味診断の指摘は関係する担当へ一回だけ戻し、revisionと依存する計画を更新する。品質のみで再生成を続けない。")
    d.text(1030,57,"Scene振付の再設計 ─ 診断・局所修正",38,700,"#172333")
    d.text(1030,100,"提案・未実装  /  必須の構造検証と、必要時だけの意味診断を分ける",24)
    d.legend([(140,"artifact","保存済みの原文・計画"),(710,"python","必須の構造検証"),(1300,"llm","任意のLLM診断・修正")],161)
    d.box(100,245,430,200,"artifact","Sceneの候補一式",[
        "出来事 E・演技 B・撮影計画",
        "同じrevisionの組として保存",
        "過去の採用候補も保持する",
    ],size=23,line_height=37)
    d.box(730,245,530,200,"python","構造検証",[
        "参照ID・時刻・原文保持・revision",
        "不成立：そのSceneを停止・保存",
        "成立：採用へ進む",
    ],size=23,line_height=37)
    d.box(1470,245,470,200,"output","採用・次Sceneへ",[
        "構造上の完成を確認",
        "品質の懸念は理由付きで記録",
        "完成映像の品質とは別に扱う",
    ],size=23,line_height=37)
    d.path([(530,345),(730,345)],"grey")
    d.path([(1260,345),(1470,345)],"green")
    d.text(1365,319,"構造成立",22,600,GREEN,label=True)

    d.box(650,620,610,210,"llm","意味診断LLM（必要なSceneのみ）",[
        "関連する原文・作者指示を比較",
        "不足・衝突の箇所を短く指摘",
        "PASSだけを品質保証には使わない",
        "演技の豊かさ・比喩は参考評価",
    ],size=23,line_height=35)
    d.path([(315,445),(315,725),(650,725)],"orange",dashed=True)
    d.text(315,543,"任意の診断",23,600,ORANGE,label=True)
    d.box(1470,620,470,210,"llm","関係する担当へ一回修正",[
        "出来事の問題 → A",
        "身体演技の不足 → B",
        "画角・尺の問題 → C",
        "作者の確定本文は変更しない",
    ],size=23,line_height=35)
    d.path([(1260,725),(1470,725)],"orange",dashed=True)
    d.text(1365,696,"修正する場合",21,600,ORANGE,label=True)

    d.path([(1705,830),(1705,910),(55,910),(55,345),(100,345)],"orange",dashed=True)
    d.text(965,895,"revision更新 → 変更に依存する計画だけ再生成 → 構造検証へ",24,600,ORANGE,label=True)
    d.text(1030,1000,"意味修正はSceneあたり一回を初期値にする。品質指摘だけで全曲の再生成を繰り返さない。",25,600)
    d.text(1030,1048,"構造有効で懸念が残る場合は quality_degraded と理由を保存。8Bの意味判定は参考情報。",23)
    d.text(1030,1090,"変更に依存する生成計画は失効。作者が固定したCamera等は保持して再検証する。",23)
    d.save("scene-choreography-repair.svg")


def user_emd():
    d = Diagram(2100, 1590, "ユーザーEMD優先の共通解析と部分生成（提案）",
                "既存ユーザーEMD、profile、観測と歌詞を共通構造で解析し、項目と適用範囲ごとに優先を解決する。確定本文は直接保持し、未指定項目だけを生成する。任意の演出候補は選択対象であり強制命令ではない。Compilerも同じ解決結果を使う。")
    d.text(1050, 56, "ユーザーEMDを中心にした共通契約", 38, 700, "#172333")
    d.text(1050, 98, "提案・未実装  /  既存の入力口を共通化  /  部分手書きと全自動を併用  /  内部IDの記入は不要", 23)
    d.box(100, 175, 500, 205, "input", "ユーザーEMD", [
        "共通指示 / 任意の演出候補",
        "Scene・Shotの確定本文と時刻",
        "既存入力・passthrough・再編集",
    ], size=23, line_height=38)
    d.box(800, 175, 500, 205, "input", "profile", [
        "共通する本文は同じ文法で解析",
        "画風・Motion・Cameraの既定値",
        "計画用メタデータは専用検証",
    ], size=23, line_height=38)
    d.box(1500, 175, 500, 205, "input", "歌詞・観測・継続状態", [
        "原歌詞 / 時刻 / Visionの観測",
        "前Sceneの採用済み終端",
        "観測を作者の演出命令と混同しない",
    ], size=23, line_height=38)
    for x in (350, 1050, 1750):
        d.path([(x, 380), (x, 475)], "grey")
    d.box(100, 475, 1900, 215, "python", "共通EMD parser + 用途別validator + 項目・適用範囲ごとの優先解決", [
        "競合する演出項目：作者の明示指定 ＞ profileの既定値 ＞ LLM補完　（構造・H3契約は別に検証）",
        "出典・範囲・本文の用途を保持。確定本文 / 生成指示 / 任意候補を区別する。",
        "構造化項目の本文ブロックで上書き。自然文の意味をPythonで推測して切り貼りしない。",
    ], size=24, line_height=39)
    d.path([(400, 690), (400, 820)], "green")
    d.text(400, 761, "確定済みの本文", 24, 600, GREEN, label=True)
    d.path([(1650, 690), (1650, 820)], "blue")
    d.text(1650, 754, "有効指示・候補・固定条件", 23, 600, BLUE, label=True)
    d.text(1650, 786, "未指定項目がある場合だけ", 22, 400, BLUE, label=True)
    d.box(100, 820, 600, 225, "artifact", "作者の原文を直接保持", [
        "演技だけ / Cameraだけの固定も可能",
        "LLM監査でも無断で書き換えない",
        "全手書きなら生成A/B/Cを省略",
        "再生成したい項目を未指定へ戻せる",
    ], size=24, line_height=38)
    d.box(1300, 820, 700, 225, "llm", "未指定部分の生成", [
        "A：出来事 / B：振付 / C：撮影・割当",
        "全担当が作者の固定条件を先に読む",
        "任意候補は選択・展開・不採用が可能",
        "生成結果は作者の確定欄を置き換えない",
    ], size=24, line_height=38)
    d.path([(400, 1045), (400, 1115), (850, 1115), (850, 1175)], "green")
    d.path([(1650, 1045), (1650, 1115), (1250, 1115), (1250, 1175)], "blue")
    d.box(650, 1175, 800, 150, "artifact", "共通のScene成果物 → 完成EMD", [
        "採用原文・出典・範囲・revision・hashを保存",
        "再編集時は依存する生成部分だけを再計画",
    ], size=24, line_height=37)
    d.path([(1050, 1325), (1050, 1400)], "green")
    d.box(200, 1400, 1700, 140, "output", "Compilerも同じ優先解決を使用 → H3 Plan", [
        "局所上書きと競合するprofile文を共通prefixへ残さない。翻訳・最終promptまで出典を追跡する。",
        "語義の完全な一致と映像での再現は別途検証する。原文保持だけで品質を保証しない。",
    ], size=24, line_height=34)
    d.save("scene-choreography-user-emd.svg")


if __name__ == "__main__":
    pipeline()
    repair()
    user_emd()
    print(OUT)

