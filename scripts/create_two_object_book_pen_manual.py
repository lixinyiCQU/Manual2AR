from pathlib import Path

from reportlab.graphics.shapes import Drawing, Line, Rect, String
from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.units import mm
from reportlab.pdfbase.pdfmetrics import registerFont
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.platypus import PageBreak, Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle


ROOT = Path(__file__).resolve().parents[1]
OUTPUT = ROOT / "output/pdf/TWO_OBJECT_BOOK_PEN_01_manual_v1.pdf"
registerFont(TTFont("ManualChinese", "/Library/Fonts/Arial Unicode.ttf"))

NAVY = colors.HexColor("#0B2539")
BLUE = colors.HexColor("#1595D3")
PALE = colors.HexColor("#EAF5FB")
INK = colors.HexColor("#152B3A")
MUTED = colors.HexColor("#526A78")
GREEN = colors.HexColor("#19A974")
RED = colors.HexColor("#D84A55")
PEN_BLUE = colors.HexColor("#226FD1")


def make_styles():
    body = ParagraphStyle("body", fontName="ManualChinese", fontSize=10.5, leading=16, textColor=INK)
    return {
        "body": body,
        "small": ParagraphStyle("small", parent=body, fontSize=8.8, leading=13, textColor=MUTED),
        "title": ParagraphStyle("title", parent=body, fontSize=25, leading=31, textColor=NAVY),
        "h1": ParagraphStyle("h1", parent=body, fontSize=18, leading=24, textColor=NAVY),
        "h2": ParagraphStyle("h2", parent=body, fontSize=14, leading=20, textColor=BLUE),
        "center": ParagraphStyle("center", parent=body, fontSize=9, leading=13, alignment=TA_CENTER),
    }


def footer(canvas, doc):
    canvas.saveState()
    canvas.setFont("ManualChinese", 8)
    canvas.setFillColor(MUTED)
    canvas.drawRightString(A4[0] - 16 * mm, 10 * mm, f"第 {doc.page} 页 / 共 3 页")
    canvas.restoreState()


def diagram(stage, width=158 * mm, height=65 * mm):
    w = float(width)
    h = float(height)
    d = Drawing(w, h)
    d.add(Rect(0, 0, w, h, rx=8, ry=8, fillColor=PALE, strokeColor=None))
    book_x = w * 0.31
    book_y = h * 0.13
    book_w = w * 0.48
    book_h = h * 0.63

    if stage == 0:
        d.add(Rect(book_x, book_y, book_w, book_h, rx=4, ry=4, fillColor=colors.white, strokeColor=NAVY, strokeWidth=2))
        d.add(Line(book_x + book_w / 2, book_y + 2, book_x + book_w / 2, book_y + book_h - 2, strokeColor=MUTED, strokeWidth=1.2))
        d.add(String(book_x + book_w / 2 - 23, book_y + book_h / 2, "书（打开）", fontName="ManualChinese", fontSize=9, fillColor=INK))
    else:
        d.add(Rect(book_x, book_y, book_w, book_h, rx=5, ry=5, fillColor=colors.HexColor("#BEDDF0"), strokeColor=NAVY, strokeWidth=2))
        d.add(String(book_x + book_w / 2 - 11, book_y + book_h / 2, "书", fontName="ManualChinese", fontSize=10, fillColor=INK))

    if stage < 2:
        x1, y1, x2, y2 = w * 0.07, h * 0.43, w * 0.26, h * 0.43
    elif stage == 2:
        x1, y1, x2, y2 = book_x + book_w * 0.18, book_y + book_h * 0.24, book_x + book_w * 0.82, book_y + book_h * 0.24
    else:
        x1, y1, x2, y2 = book_x + book_w * 0.72, book_y + book_h * 0.18, book_x + book_w * 0.72, book_y + book_h * 0.82
    d.add(Line(x1, y1, x2, y2, strokeColor=PEN_BLUE, strokeWidth=7))
    d.add(String(min(x1, x2), min(y1, y2) - 13, "蓝色笔", fontName="ManualChinese", fontSize=8, fillColor=PEN_BLUE))
    return d


def step_block(number, instruction, before, after, completion, errors, grounding, styles):
    visuals = Table(
        [[diagram(before, 73 * mm, 40 * mm), Paragraph("→", ParagraphStyle("arrow", parent=styles["title"], alignment=TA_CENTER, textColor=GREEN)), diagram(after, 73 * mm, 40 * mm)]],
        colWidths=[74 * mm, 15 * mm, 74 * mm],
        style=TableStyle([
            ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
            ("BOX", (0, 0), (0, 0), 0.6, colors.HexColor("#C2D8E4")),
            ("BOX", (2, 0), (2, 0), 0.6, colors.HexColor("#C2D8E4")),
            ("LEFTPADDING", (0, 0), (-1, -1), 2),
            ("RIGHTPADDING", (0, 0), (-1, -1), 2),
            ("TOPPADDING", (0, 0), (-1, -1), 2),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 2),
        ]),
    )
    details = Table(
        [[Paragraph(
            f"<font color='#1595D3'><b>完成条件</b></font>　{completion}<br/>"
            f"<font color='#D84A55'><b>错误状态</b></font>　{errors}<br/>"
            f"<font color='#19A974'><b>二维指引</b></font>　{grounding}",
            styles["body"],
        )]],
        colWidths=[163 * mm],
        style=TableStyle([
            ("BOX", (0, 0), (-1, -1), 0.6, colors.HexColor("#C2D8E4")),
            ("LEFTPADDING", (0, 0), (-1, -1), 8),
            ("RIGHTPADDING", (0, 0), (-1, -1), 8),
            ("TOPPADDING", (0, 0), (-1, -1), 7),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 7),
        ]),
    )
    return [Paragraph(f"步骤 {number}　{instruction}", styles["h2"]), visuals, Spacer(1, 2 * mm), details, Spacer(1, 6 * mm)]


def build():
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    s = make_styles()
    doc = SimpleDocTemplate(
        str(OUTPUT), pagesize=A4, leftMargin=18 * mm, rightMargin=18 * mm,
        topMargin=16 * mm, bottomMargin=17 * mm,
        title="TWO OBJECT BOOK PEN 01 Manual", author="Manual2AR"
    )
    story = [
        Paragraph("TWO OBJECT BOOK + PEN 01", s["title"]),
        Paragraph("Manual2AR 最简家庭测试 | 一本书 - 一支蓝色笔", s["small"]),
        Table([[""]], colWidths=[168 * mm], rowHeights=[1.5 * mm], style=TableStyle([("BACKGROUND", (0, 0), (-1, -1), BLUE)])),
        Spacer(1, 7 * mm),
        Paragraph("目标", s["h1"]),
        Paragraph("用电脑摄像头在很小的画面内验证：说明书自动拆步骤、当前进度判断、书与笔的状态识别、笔的来源框、书面目标框、方向箭头、完成核验和错误阻止。", s["body"]),
        Spacer(1, 6 * mm),
        Paragraph("开始前状态 S0", s["h1"]),
        diagram(0),
        Spacer(1, 4 * mm),
        Paragraph("把一本书摊开放在画面中央；把蓝色笔水平放在书的左边。书和笔都要完整入镜，笔不要碰到书。操作后移开双手再识别。", s["body"]),
        Spacer(1, 5 * mm),
        Table([[Paragraph("摄像头不需要拍到整个桌面，只需拍到一本书及其左侧约一个笔长的空间。", s["body"])]], colWidths=[168 * mm], style=TableStyle([
            ("BACKGROUND", (0, 0), (-1, -1), colors.HexColor("#FFF4D6")),
            ("BOX", (0, 0), (-1, -1), 1, colors.HexColor("#D9A52B")),
            ("LEFTPADDING", (0, 0), (-1, -1), 10), ("RIGHTPADDING", (0, 0), (-1, -1), 10),
            ("TOPPADDING", (0, 0), (-1, -1), 8), ("BOTTOMPADDING", (0, 0), (-1, -1), 8),
        ])),
    ]

    story.append(PageBreak())
    story += step_block(
        1, "合上摊开的书。", 0, 1,
        "书完全合上；蓝色笔仍水平放在书的左边。",
        "书仍打开；只合上一部分；笔被移动。",
        "高亮整本书并显示“合上”；本步不需要移动箭头。", s,
    )
    story += step_block(
        2, "把左边的蓝色笔移动到书的下半部，保持水平。", 1, 2,
        "蓝色笔位于合上书的下半部且接近水平；书左侧不再有笔。",
        "笔仍在书左边；笔离开书；笔竖直。",
        "橙色来源框标出蓝色笔，绿色目标框标出书的下半部，并绘制箭头。", s,
    )

    story.append(PageBreak())
    story += step_block(
        3, "把蓝色笔移动到书的右半部，并旋转为竖直。", 2, 3,
        "蓝色笔位于书的右半部且接近竖直。",
        "笔仍在下半部水平放置；笔在书外；笔位于书左半部。",
        "橙色来源框标出蓝色笔，绿色目标框标出书的右半部，并绘制箭头。", s,
    )
    story += [
        Paragraph("当前进度定位", s["h1"]),
        Table([
            [Paragraph("看到的状态", s["center"]), Paragraph("建议下一步", s["center"])],
            [Paragraph("书打开，笔在左边", s["body"]), Paragraph("合上书", s["body"])],
            [Paragraph("书合上，笔仍在左边", s["body"]), Paragraph("把笔移到书下半部", s["body"])],
            [Paragraph("笔已经水平放在书下半部", s["body"]), Paragraph("把笔移到右半部并竖直", s["body"])],
            [Paragraph("画面模糊、遮挡或位置错误", s["body"]), Paragraph("不推进，重新拍摄或纠正", s["body"])],
        ], colWidths=[84 * mm, 84 * mm], style=TableStyle([
            ("BACKGROUND", (0, 0), (-1, 0), NAVY), ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
            ("GRID", (0, 0), (-1, -1), 0.5, colors.HexColor("#B8CDD8")),
            ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, PALE]),
            ("VALIGN", (0, 0), (-1, -1), "TOP"),
            ("LEFTPADDING", (0, 0), (-1, -1), 7), ("RIGHTPADDING", (0, 0), (-1, -1), 7),
            ("TOPPADDING", (0, 0), (-1, -1), 7), ("BOTTOMPADDING", (0, 0), (-1, -1), 7),
        ])),
        Spacer(1, 6 * mm),
        Paragraph("每一步由 Unity 显示为文字。语音播报不属于当前版本，后续可作为独立交互功能加入。", s["body"]),
    ]
    doc.build(story, onFirstPage=footer, onLaterPages=footer)


if __name__ == "__main__":
    build()
    print(OUTPUT)
