from pathlib import Path

from reportlab.graphics.shapes import Drawing, Line, Rect, String
from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.units import mm
from reportlab.pdfbase.pdfmetrics import registerFont
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.platypus import (
    PageBreak,
    Paragraph,
    SimpleDocTemplate,
    Spacer,
    Table,
    TableStyle,
)


ROOT = Path(__file__).resolve().parents[1]
OUTPUT = ROOT / "output/pdf/HOME_OBJECT_RELOCATION_01_manual_v1.pdf"
FONT_PATH = "/Library/Fonts/Arial Unicode.ttf"
registerFont(TTFont("ManualChinese", FONT_PATH))

NAVY = colors.HexColor("#0B2539")
BLUE = colors.HexColor("#1595D3")
PALE = colors.HexColor("#EAF5FB")
INK = colors.HexColor("#152B3A")
MUTED = colors.HexColor("#526A78")
GREEN = colors.HexColor("#19A974")
RED = colors.HexColor("#D84A55")
PEN_BLUE = colors.HexColor("#226FD1")
CARD_GOLD = colors.HexColor("#F3C84B")
PERFUME = colors.HexColor("#B658A4")


def make_styles():
    body = ParagraphStyle(
        "body",
        fontName="ManualChinese",
        fontSize=10.5,
        leading=16,
        textColor=INK,
    )
    return {
        "body": body,
        "small": ParagraphStyle(
            "small", parent=body, fontSize=8.8, leading=13, textColor=MUTED
        ),
        "title": ParagraphStyle(
            "title", parent=body, fontSize=24, leading=30, textColor=NAVY
        ),
        "h1": ParagraphStyle(
            "h1", parent=body, fontSize=18, leading=24, textColor=NAVY
        ),
        "h2": ParagraphStyle(
            "h2", parent=body, fontSize=14, leading=20, textColor=BLUE
        ),
        "center": ParagraphStyle(
            "center", parent=body, fontSize=9, leading=13, alignment=TA_CENTER
        ),
    }


def footer(canvas, doc):
    canvas.saveState()
    canvas.setFont("ManualChinese", 8)
    canvas.setFillColor(MUTED)
    canvas.drawRightString(A4[0] - 16 * mm, 10 * mm, f"第 {doc.page} 页 / 共 4 页")
    canvas.restoreState()


def first_page_heading(styles):
    return [
        Paragraph("HOME OBJECT RELOCATION 01", styles["title"]),
        Paragraph(
            "Manual2AR 家庭状态识别与二维指引测试 | 三本书 - 蓝色笔 - 校园卡 - 香水",
            styles["small"],
        ),
        Table(
            [[""]],
            colWidths=[168 * mm],
            rowHeights=[1.5 * mm],
            style=TableStyle([("BACKGROUND", (0, 0), (-1, -1), BLUE)]),
        ),
        Spacer(1, 6 * mm),
    ]


def layout_diagram(stage, width=160 * mm, height=62 * mm):
    w = float(width)
    h = float(height)
    drawing = Drawing(w, h)
    drawing.add(Rect(0, 0, w, h, rx=8, ry=8, fillColor=PALE, strokeColor=None))

    gap = 12
    book_w = (w - gap * 4) / 3
    book_h = h * 0.42
    y = h * 0.16
    left_x = gap
    center_x = gap * 2 + book_w
    right_x = gap * 3 + book_w * 2

    def closed_book(x, label, fill):
        drawing.add(
            Rect(
                x,
                y,
                book_w,
                book_h,
                rx=4,
                ry=4,
                fillColor=fill,
                strokeColor=NAVY,
                strokeWidth=1.6,
            )
        )
        drawing.add(
            String(
                x + book_w / 2 - 15,
                y + book_h / 2 - 3,
                label,
                fontName="ManualChinese",
                fontSize=8,
                fillColor=INK,
            )
        )

    closed_book(left_x, "左书", colors.HexColor("#D7E0E5"))
    if stage == 0:
        drawing.add(
            Rect(
                center_x,
                y,
                book_w,
                book_h,
                rx=3,
                ry=3,
                fillColor=colors.white,
                strokeColor=NAVY,
                strokeWidth=1.6,
            )
        )
        drawing.add(
            Line(
                center_x + book_w / 2,
                y + 2,
                center_x + book_w / 2,
                y + book_h - 2,
                strokeColor=MUTED,
                strokeWidth=1,
            )
        )
        drawing.add(
            String(
                center_x + book_w / 2 - 22,
                y + book_h / 2 - 3,
                "中间主书（打开）",
                fontName="ManualChinese",
                fontSize=7,
                fillColor=INK,
            )
        )
    else:
        closed_book(center_x, "中间主书", colors.HexColor("#BDDDF0"))
    closed_book(right_x, "右书", colors.HexColor("#D7E0E5"))

    pen_x = left_x + book_w * 0.18 if stage < 2 else center_x + book_w * 0.16
    pen_y = y + book_h * 0.24
    drawing.add(Line(pen_x, pen_y, pen_x + book_w * 0.65, pen_y, strokeColor=PEN_BLUE, strokeWidth=5))
    drawing.add(String(pen_x, pen_y - 12, "蓝色笔", fontName="ManualChinese", fontSize=7, fillColor=PEN_BLUE))

    card_x = right_x + book_w * 0.27 if stage < 3 else center_x + book_w * 0.30
    card_y = y + book_h * 0.60
    drawing.add(Rect(card_x, card_y, book_w * 0.42, book_h * 0.25, fillColor=CARD_GOLD, strokeColor=colors.HexColor("#B58D16")))
    drawing.add(String(card_x + 3, card_y + 2, "校园卡", fontName="ManualChinese", fontSize=6.5, fillColor=INK))

    perfume_x = center_x + book_w * 0.38 if stage < 4 else right_x + book_w * 0.38
    perfume_y = h * 0.70 if stage < 4 else y + book_h * 0.36
    drawing.add(Rect(perfume_x, perfume_y, book_w * 0.25, h * 0.18, rx=3, ry=3, fillColor=PERFUME, strokeColor=colors.HexColor("#713568")))
    drawing.add(String(perfume_x - 1, perfume_y - 10, "香水", fontName="ManualChinese", fontSize=7, fillColor=PERFUME))
    return drawing


def step_block(number, instruction, before_stage, after_stage, completion, errors, grounding, styles):
    before = layout_diagram(before_stage, 73 * mm, 39 * mm)
    after = layout_diagram(after_stage, 73 * mm, 39 * mm)
    visual = Table(
        [[before, Paragraph("→", ParagraphStyle("arrow", parent=styles["title"], alignment=TA_CENTER, textColor=GREEN)), after]],
        colWidths=[74 * mm, 15 * mm, 74 * mm],
        style=TableStyle(
            [
                ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
                ("BOX", (0, 0), (0, 0), 0.6, colors.HexColor("#C2D8E4")),
                ("BOX", (2, 0), (2, 0), 0.6, colors.HexColor("#C2D8E4")),
                ("LEFTPADDING", (0, 0), (-1, -1), 2),
                ("RIGHTPADDING", (0, 0), (-1, -1), 2),
                ("TOPPADDING", (0, 0), (-1, -1), 2),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 2),
            ]
        ),
    )
    detail = Table(
        [[Paragraph(
            f"<font color='#1595D3'><b>完成条件</b></font>　{completion}<br/>"
            f"<font color='#D84A55'><b>错误状态</b></font>　{errors}<br/>"
            f"<font color='#19A974'><b>二维指引</b></font>　{grounding}",
            styles["body"],
        )]],
        colWidths=[163 * mm],
        style=TableStyle(
            [
                ("BACKGROUND", (0, 0), (-1, -1), colors.white),
                ("BOX", (0, 0), (-1, -1), 0.6, colors.HexColor("#C2D8E4")),
                ("LEFTPADDING", (0, 0), (-1, -1), 8),
                ("RIGHTPADDING", (0, 0), (-1, -1), 8),
                ("TOPPADDING", (0, 0), (-1, -1), 7),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 7),
            ]
        ),
    )
    return [
        Paragraph(f"步骤 {number}　{instruction}", styles["h2"]),
        visual,
        Spacer(1, 2 * mm),
        detail,
        Spacer(1, 6 * mm),
    ]


def build():
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    styles = make_styles()
    doc = SimpleDocTemplate(
        str(OUTPUT),
        pagesize=A4,
        leftMargin=18 * mm,
        rightMargin=18 * mm,
        topMargin=16 * mm,
        bottomMargin=17 * mm,
        title="HOME OBJECT RELOCATION 01 Manual",
        author="Manual2AR",
    )
    story = first_page_heading(styles)
    story += [
        Paragraph("目标", styles["h1"]),
        Paragraph(
            "在没有真实实验设备时，用稳定可见的家庭物品验证：说明书解析、当前进度判断、物体二维定位、来源到目标的方向指引、操作完成核验、错误阻止与继续推进。",
            styles["body"],
        ),
        Spacer(1, 5 * mm),
        Paragraph("开始前摆放 S0", styles["h1"]),
        layout_diagram(0),
        Spacer(1, 3 * mm),
        Paragraph(
            "三本书从左到右横向排列：左书合上，中间主书摊开，右书合上。蓝色笔横放在左书上；校园卡放在右书上；香水直立放在中间主书上方。所有物体之间留出空隙。",
            styles["body"],
        ),
        Spacer(1, 4 * mm),
        Table(
            [[Paragraph("识别时采用俯拍或接近俯拍角度。三本书必须全部入镜；操作完成后移开双手。香水不需要打开或喷洒。", styles["body"])]],
            colWidths=[168 * mm],
            style=TableStyle(
                [
                    ("BACKGROUND", (0, 0), (-1, -1), colors.HexColor("#FFF4D6")),
                    ("BOX", (0, 0), (-1, -1), 1, colors.HexColor("#D9A52B")),
                    ("LEFTPADDING", (0, 0), (-1, -1), 10),
                    ("RIGHTPADDING", (0, 0), (-1, -1), 10),
                    ("TOPPADDING", (0, 0), (-1, -1), 8),
                    ("BOTTOMPADDING", (0, 0), (-1, -1), 8),
                ]
            ),
        ),
    ]

    story.append(PageBreak())
    story += step_block(
        1,
        "合上中间摊开的主书。",
        0,
        1,
        "中间主书完全合上；左书与右书位置不变；笔、校园卡和香水仍在原位置。",
        "中间主书仍打开；只合上一部分；移动了其他物品。",
        "高亮中间主书并显示“合上”动作标签；本步没有跨区域移动箭头。",
        styles,
    )
    story += step_block(
        2,
        "把左书上的蓝色笔移动到中间主书下半部，保持水平。",
        1,
        2,
        "蓝色笔位于中间主书下半部且接近水平；左书上不再有笔。",
        "笔仍在左书；笔放到右书；笔竖直；笔离开三本书。",
        "橙色来源框标出蓝色笔，绿色目标框标出中间主书下半部，并绘制方向箭头。",
        styles,
    )

    story.append(PageBreak())
    story += step_block(
        3,
        "把右书上的校园卡移动到中间主书上半部，不遮住蓝色笔。",
        2,
        3,
        "校园卡位于中间主书上半部；蓝色笔仍在下半部；二者不重叠。",
        "校园卡仍在右书；校园卡放到左书；校园卡遮住蓝色笔。",
        "橙色来源框标出校园卡，绿色目标框标出中间主书上半部，并绘制方向箭头。",
        styles,
    )
    story += step_block(
        4,
        "把中间主书上方的香水移动到右书中央，并保持直立。",
        3,
        4,
        "香水位于右书中央并保持直立；校园卡和蓝色笔仍在中间主书正确区域。",
        "香水仍在原处；香水放到左书；香水倾倒；香水遮住校园卡或蓝色笔。",
        "橙色来源框标出香水，绿色目标框标出右书中央，并绘制方向箭头。",
        styles,
    )

    story.append(PageBreak())
    story += [
        Paragraph("系统应该如何判断", styles["h1"]),
        Table(
            [
                [Paragraph("现场状态", styles["center"]), Paragraph("建议下一步", styles["center"]), Paragraph("系统行为", styles["center"])],
                [Paragraph("中间书打开，三个物体在初始位置", styles["body"]), Paragraph("合上中间主书", styles["body"]), Paragraph("定位到步骤 1", styles["body"])],
                [Paragraph("中间书已合上，笔仍在左书", styles["body"]), Paragraph("移动蓝色笔", styles["body"]), Paragraph("跳过已完成的合书步骤", styles["body"])],
                [Paragraph("笔已在中间书下半部", styles["body"]), Paragraph("移动校园卡", styles["body"]), Paragraph("定位到步骤 3", styles["body"])],
                [Paragraph("卡片已在中间书上半部", styles["body"]), Paragraph("移动香水", styles["body"]), Paragraph("定位到步骤 4", styles["body"])],
                [Paragraph("位置错误、遮挡或画面模糊", styles["body"]), Paragraph("不推进", styles["body"]), Paragraph("wrong_operation 或 uncertain", styles["body"])],
            ],
            colWidths=[67 * mm, 48 * mm, 53 * mm],
            style=TableStyle(
                [
                    ("BACKGROUND", (0, 0), (-1, 0), NAVY),
                    ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
                    ("GRID", (0, 0), (-1, -1), 0.5, colors.HexColor("#B8CDD8")),
                    ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, PALE]),
                    ("VALIGN", (0, 0), (-1, -1), "TOP"),
                    ("LEFTPADDING", (0, 0), (-1, -1), 7),
                    ("RIGHTPADDING", (0, 0), (-1, -1), 7),
                    ("TOPPADDING", (0, 0), (-1, -1), 7),
                    ("BOTTOMPADDING", (0, 0), (-1, -1), 7),
                ]
            ),
        ),
        Spacer(1, 8 * mm),
        Paragraph("二维指引验收", styles["h1"]),
        Paragraph(
            "移动步骤开始前，模型应同时返回 source 与 target 两个归一化二维框。界面用橙色表示当前操作物体，用绿色表示目标书或目标区域，并从来源框中心向目标框中心绘制箭头。完成后再次识别：只有完成条件满足且 safe_to_advance=true 才进入下一步。",
            styles["body"],
        ),
        Spacer(1, 6 * mm),
        Paragraph("建议依次拍摄：S0 初始状态、S1 合书后、S2 移笔后、S3 移卡后、S4 移香水后，以及每一步至少一张错误状态和一张遮挡状态。", styles["body"]),
    ]
    doc.build(story, onFirstPage=footer, onLaterPages=footer)


if __name__ == "__main__":
    build()
    print(OUTPUT)
