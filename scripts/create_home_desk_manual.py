from pathlib import Path

from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER, TA_LEFT
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.units import mm
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.pdfbase.pdfmetrics import registerFont
from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle
from reportlab.pdfgen import canvas as pdf_canvas


OUTPUT = Path(__file__).resolve().parents[1] / "output/pdf/HOME_DESK_KIT_01_manual_v1.pdf"
NAVY = colors.HexColor("#0B2539")
BLUE = colors.HexColor("#1595D3")
PALE = colors.HexColor("#EAF5FB")
INK = colors.HexColor("#152B3A")
MUTED = colors.HexColor("#526A78")
YELLOW = colors.HexColor("#F5D247")
SKY = colors.HexColor("#61BFF2")
GREEN = colors.HexColor("#19A974")
RED = colors.HexColor("#D84A55")


FONT_PATH = "/Library/Fonts/Arial Unicode.ttf"
registerFont(TTFont("ManualChinese", FONT_PATH))


def styles():
    base = ParagraphStyle(
        "base",
        fontName="ManualChinese",
        fontSize=10.5,
        leading=16,
        textColor=INK,
    )
    return {
        "title": ParagraphStyle(
            "title",
            parent=base,
            fontSize=25,
            leading=31,
            textColor=colors.white,
            alignment=TA_LEFT,
        ),
        "subtitle": ParagraphStyle(
            "subtitle",
            parent=base,
            fontSize=11,
            leading=17,
            textColor=colors.HexColor("#D7E9F4"),
        ),
        "h1": ParagraphStyle(
            "h1",
            parent=base,
            fontSize=18,
            leading=24,
            textColor=NAVY,
            spaceAfter=7,
        ),
        "h2": ParagraphStyle(
            "h2",
            parent=base,
            fontSize=14,
            leading=20,
            textColor=BLUE,
            spaceAfter=5,
        ),
        "body": base,
        "small": ParagraphStyle(
            "small",
            parent=base,
            fontSize=8.8,
            leading=13,
            textColor=MUTED,
        ),
        "center": ParagraphStyle(
            "center",
            parent=base,
            alignment=TA_CENTER,
            fontSize=10,
            leading=14,
        ),
        "warning": ParagraphStyle(
            "warning",
            parent=base,
            fontSize=9.5,
            leading=14,
            textColor=RED,
        ),
    }


def draw_footer(canvas, page_number):
    canvas.saveState()
    width, height = A4
    canvas.setFillColor(MUTED)
    canvas.setFont("ManualChinese", 8)
    canvas.drawRightString(width - 16 * mm, 10 * mm, f"第 {page_number} 页 / 共 4 页")
    canvas.restoreState()


class HeaderCanvas(pdf_canvas.Canvas):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._saved_pages = []

    def showPage(self):
        self._saved_pages.append(dict(self.__dict__))
        self._startPage()

    def save(self):
        for state in self._saved_pages:
            self.__dict__.update(state)
            draw_footer(self, self._pageNumber)
            super().showPage()
        super().save()


def footer_callback(canvas, doc):
    draw_footer(canvas, doc.page)


def banner(s):
    return Table(
        [[Paragraph("<font color='#A9D9F3'>MANUAL2AR 家庭闭环测试说明书</font><br/><font size='25' color='white'>HOME DESK KIT 01</font><br/><font color='#D7E9F4'>书本 - 黄便签 - 蓝便签 - 笔 | 版本 1.0</font>", s["body"])]],
        colWidths=[174 * mm],
        rowHeights=[35 * mm],
        style=TableStyle(
            [
                ("BACKGROUND", (0, 0), (-1, -1), NAVY),
                ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
                ("LEFTPADDING", (0, 0), (-1, -1), 12),
                ("RIGHTPADDING", (0, 0), (-1, -1), 12),
            ]
        ),
    )


def page_heading(s):
    return [
        Paragraph("HOME DESK KIT 01", ParagraphStyle("page-title", parent=s["h1"], fontSize=24, leading=29)),
        Paragraph("MANUAL2AR 家庭闭环测试说明书　|　书本 - 黄便签 - 蓝便签 - 笔　|　版本 1.0", s["small"]),
        Table([[""]], colWidths=[168 * mm], rowHeights=[1.5 * mm], style=TableStyle([("BACKGROUND", (0, 0), (-1, -1), BLUE)])),
        Spacer(1, 6 * mm),
    ]


def book_diagram(width=150 * mm, height=65 * mm, stage=0):
    from reportlab.graphics.shapes import Drawing, Line, Rect, String

    d = Drawing(width, height)
    d.add(Rect(0, 0, width, height, rx=7, ry=7, fillColor=PALE, strokeColor=None))
    if stage == 0:
        d.add(Rect(35, 16, 76, 42, rx=4, ry=4, fillColor=colors.HexColor("#CEDBE2"), strokeColor=NAVY, strokeWidth=2))
        d.add(String(64, 35, "合上的书", fontName="ManualChinese", fontSize=11, fillColor=INK))
        d.add(Rect(9, 37, 17, 17, fillColor=YELLOW, strokeColor=colors.HexColor("#C7A800")))
        d.add(String(4, 20, "黄便签", fontName="ManualChinese", fontSize=8, fillColor=INK))
        d.add(Rect(123, 37, 17, 17, fillColor=SKY, strokeColor=BLUE))
        d.add(String(119, 20, "蓝便签", fontName="ManualChinese", fontSize=8, fillColor=INK))
        d.add(Line(40, 8, 108, 8, strokeColor=INK, strokeWidth=5))
        d.add(Line(108, 8, 116, 8, strokeColor=BLUE, strokeWidth=2))
        d.add(String(65, 1, "笔尖向右", fontName="ManualChinese", fontSize=8, fillColor=INK))
    else:
        d.add(Rect(24, 11, 102, 47, rx=3, ry=3, fillColor=colors.white, strokeColor=NAVY, strokeWidth=2))
        d.add(Line(75, 12, 75, 57, strokeColor=colors.HexColor("#9CB0BA"), strokeWidth=1.4))
        d.add(String(44, 49, "左页", fontName="ManualChinese", fontSize=9, fillColor=MUTED))
        d.add(String(96, 49, "右页", fontName="ManualChinese", fontSize=9, fillColor=MUTED))
        if stage >= 2:
            d.add(Rect(32, 32, 17, 17, fillColor=YELLOW, strokeColor=colors.HexColor("#C7A800")))
        if stage >= 3:
            d.add(Rect(102, 32, 17, 17, fillColor=SKY, strokeColor=BLUE))
        if stage >= 4:
            d.add(Line(48, 22, 105, 22, strokeColor=INK, strokeWidth=5))
            d.add(Line(105, 22, 114, 22, strokeColor=BLUE, strokeWidth=2))
    return d


def step_card(number, instruction, completion, mistakes, source, diagram, s):
    heading = Paragraph(f"<b>步骤 {number}</b>　{instruction}", s["h2"])
    details = Paragraph(
        f"<font color='#1595D3'><b>完成条件</b></font>　{completion}<br/>"
        f"<font color='#D84A55'><b>错误状态</b></font>　{mistakes}<br/>"
        f"<font color='#526A78'><b>核验方式</b></font>　单张俯拍图中的可见状态<br/>"
        f"<font color='#526A78'><b>来源</b></font>　{source}",
        s["body"],
    )
    table = Table([[diagram, details]], colWidths=[75 * mm, 93 * mm], hAlign="LEFT")
    table.setStyle(
        TableStyle(
            [
                ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
                ("BACKGROUND", (0, 0), (-1, -1), colors.white),
                ("BOX", (0, 0), (-1, -1), 0.8, colors.HexColor("#C7D9E3")),
                ("INNERGRID", (0, 0), (-1, -1), 0.5, colors.HexColor("#DCE8EE")),
                ("LEFTPADDING", (0, 0), (-1, -1), 7),
                ("RIGHTPADDING", (0, 0), (-1, -1), 7),
                ("TOPPADDING", (0, 0), (-1, -1), 8),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 8),
            ]
        )
    )
    return [heading, table, Spacer(1, 6 * mm)]


def build():
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    s = styles()
    doc = SimpleDocTemplate(
        str(OUTPUT),
        pagesize=A4,
        leftMargin=18 * mm,
        rightMargin=18 * mm,
        topMargin=16 * mm,
        bottomMargin=17 * mm,
        title="HOME DESK KIT 01 Manual",
        author="Manual2AR",
    )
    story = page_heading(s)

    story += [
        Paragraph("任务目标", s["h1"]),
        Paragraph(
            "把普通桌面物品组成一个视觉状态明确的代理设备，用来测试说明书解析、当前进度定位、逐步指导、完成验证、错误阻止和重新识别。它不是工业设备，也不包含任何真实设备安全结论。",
            s["body"],
        ),
        Spacer(1, 5 * mm),
        Paragraph("所需物品", s["h1"]),
        Table(
            [
                [Paragraph("物品", s["center"]), Paragraph("要求", s["center"])],
                [Paragraph("书或笔记本", s["body"]), Paragraph("能平放并清楚打开左右两页", s["body"])],
                [Paragraph("黄便签", s["body"]), Paragraph("一张，颜色明显", s["body"])],
                [Paragraph("蓝便签", s["body"]), Paragraph("一张，颜色明显；没有便签可用蓝纸片", s["body"])],
                [Paragraph("笔", s["body"]), Paragraph("笔尖方向清楚，建议笔身与桌面颜色不同", s["body"])],
            ],
            colWidths=[46 * mm, 122 * mm],
            style=TableStyle(
                [
                    ("BACKGROUND", (0, 0), (-1, 0), NAVY),
                    ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
                    ("GRID", (0, 0), (-1, -1), 0.5, colors.HexColor("#B8CDD8")),
                    ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
                    ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, PALE]),
                    ("LEFTPADDING", (0, 0), (-1, -1), 7),
                    ("RIGHTPADDING", (0, 0), (-1, -1), 7),
                    ("TOPPADDING", (0, 0), (-1, -1), 7),
                    ("BOTTOMPADDING", (0, 0), (-1, -1), 7),
                ]
            ),
        ),
        Spacer(1, 6 * mm),
        Paragraph("开始前状态 S0", s["h1"]),
        book_diagram(stage=0),
        Spacer(1, 3 * mm),
        Paragraph(
            "俯拍视角下：书合上并位于中央；黄便签在书的左侧；蓝便签在书的右侧；笔在书的下方水平摆放，笔尖向右。四种物品互不遮挡。",
            s["body"],
        ),
        Spacer(1, 3 * mm),
        Paragraph("注意：每次识别前先移开双手，保持相机稳定，并让整本书和三个配件全部入镜。", s["warning"]),
    ]

    from reportlab.platypus import PageBreak

    story.append(PageBreak())
    story += step_card(
        1,
        "打开书，使左页和右页都完整可见。",
        "书保持打开；中缝可见；左右两页均未被手遮挡。",
        "书仍合上；只打开一小部分；页面大面积离开画面。",
        "第 2 页 - 步骤 1",
        book_diagram(width=72 * mm, height=38 * mm, stage=1),
        s,
    )
    story += step_card(
        2,
        "把黄便签放到左页的左上区域。",
        "黄便签完整位于左页，靠近左上角；蓝便签仍在书外。",
        "黄便签在右页、跨过中缝、被遮挡，或颜色无法辨认。",
        "第 2 页 - 步骤 2",
        book_diagram(width=72 * mm, height=38 * mm, stage=2),
        s,
    )
    story += [
        Paragraph("进度定位规则", s["h1"]),
        Paragraph(
            "如果开始使用系统时书已经打开且黄便签已经正确放置，模型可以建议从步骤 3 开始。但只有连续的前置完成条件都清晰可见时才允许跳过；建议起点必须由用户确认。",
            s["body"],
        ),
    ]

    story.append(PageBreak())
    story += step_card(
        3,
        "把蓝便签放到右页的右上区域。",
        "蓝便签完整位于右页，靠近右上角；黄便签仍保持在左页左上区域。",
        "蓝便签在左页、跨过中缝、遮住黄便签，或黄便签已移位。",
        "第 3 页 - 步骤 3",
        book_diagram(width=72 * mm, height=38 * mm, stage=3),
        s,
    )
    story += step_card(
        4,
        "把笔水平放在打开书页的下半部，笔尖朝右。",
        "笔横跨书的下半部且笔尖向右；黄便签在左上；蓝便签在右上；三者互不遮挡。",
        "笔尖向左；笔竖直；笔遮住任一便签；任一便签位于错误页面。",
        "第 3 页 - 步骤 4",
        book_diagram(width=72 * mm, height=38 * mm, stage=4),
        s,
    )
    story += [
        Paragraph("任务完成状态", s["h1"]),
        Paragraph(
            "步骤 4 的四项可见条件同时满足后，任务结束。系统不得仅凭手部运动、上一帧或高置信度文字说明自动判定完成。",
            s["body"],
        ),
    ]

    story.append(PageBreak())
    story += [
        Paragraph("纠错与不确定处理", s["h1"]),
        Table(
            [
                [Paragraph("观察结果", s["center"]), Paragraph("系统行为", s["center"]), Paragraph("用户恢复操作", s["center"])],
                [Paragraph("完成条件清晰满足", s["body"]), Paragraph("标记 completed；满足安全门槛后进入下一步", s["body"]), Paragraph("无需恢复", s["body"])],
                [Paragraph("部件在错误位置或方向错误", s["body"]), Paragraph("标记 wrong_operation；禁止推进", s["body"]), Paragraph("按当前步骤说明重新摆放，再识别", s["body"])],
                [Paragraph("模糊、反光、遮挡或部件不全", s["body"]), Paragraph("标记 uncertain；禁止推进", s["body"]), Paragraph("移开手、调整角度、让全部物品入镜", s["body"])],
                [Paragraph("模型离线或返回无效数据", s["body"]), Paragraph("保留当前步骤，不猜测", s["body"]), Paragraph("检查本地服务后重新识别", s["body"])],
            ],
            colWidths=[50 * mm, 66 * mm, 52 * mm],
            style=TableStyle(
                [
                    ("BACKGROUND", (0, 0), (-1, 0), NAVY),
                    ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
                    ("GRID", (0, 0), (-1, -1), 0.5, colors.HexColor("#B8CDD8")),
                    ("VALIGN", (0, 0), (-1, -1), "TOP"),
                    ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, PALE]),
                    ("LEFTPADDING", (0, 0), (-1, -1), 7),
                    ("RIGHTPADDING", (0, 0), (-1, -1), 7),
                    ("TOPPADDING", (0, 0), (-1, -1), 7),
                    ("BOTTOMPADDING", (0, 0), (-1, -1), 7),
                ]
            ),
        ),
        Spacer(1, 8 * mm),
        Paragraph("拍摄检查清单", s["h1"]),
        Paragraph(
            "1. 使用俯拍或接近俯拍角度。<br/>"
            "2. 书的四条边尽量都在画面内。<br/>"
            "3. 黄便签、蓝便签和笔都不被手遮挡。<br/>"
            "4. 环境光均匀，页面不过曝，笔尖方向可见。<br/>"
            "5. 每完成一步后移开手，再点击识别当前状态。",
            s["body"],
        ),
        Spacer(1, 7 * mm),
        Table(
            [[Paragraph("本说明书专门用于 Manual2AR 原型基线测试。它证明的是一个受控任务的端到端流程，不代表系统已经能可靠处理任意设备或任意网上说明书。", s["body"])]],
            colWidths=[168 * mm],
            style=TableStyle(
                [
                    ("BACKGROUND", (0, 0), (-1, -1), colors.HexColor("#FFF4D6")),
                    ("BOX", (0, 0), (-1, -1), 1, colors.HexColor("#D9A52B")),
                    ("LEFTPADDING", (0, 0), (-1, -1), 12),
                    ("RIGHTPADDING", (0, 0), (-1, -1), 12),
                    ("TOPPADDING", (0, 0), (-1, -1), 10),
                    ("BOTTOMPADDING", (0, 0), (-1, -1), 10),
                ]
            ),
        ),
    ]
    doc.build(story, onFirstPage=footer_callback, onLaterPages=footer_callback)


if __name__ == "__main__":
    build()
    print(OUTPUT)
