from pathlib import Path

from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER, TA_LEFT
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.platypus import (
    BaseDocTemplate,
    Frame,
    PageBreak,
    PageTemplate,
    Paragraph,
    Spacer,
    Table,
    TableStyle,
)


ROOT = Path(__file__).resolve().parents[1]
OUTPUT = ROOT / "output" / "pdf" / "BOOK-RIG-01_proxy_manual_v1.pdf"
OUTPUT.parent.mkdir(parents=True, exist_ok=True)

PAGE_W, PAGE_H = A4
MARGIN_X = 17 * mm
MARGIN_TOP = 18 * mm
MARGIN_BOTTOM = 16 * mm

NAVY = colors.HexColor("#17324D")
BLUE = colors.HexColor("#2B6F9F")
LIGHT_BLUE = colors.HexColor("#EAF4FA")
GREEN = colors.HexColor("#9BCB87")
LIGHT_GREEN = colors.HexColor("#EEF7EA")
YELLOW = colors.HexColor("#F5D76E")
RED = colors.HexColor("#C94C4C")
INK = colors.HexColor("#24313A")
GRAY = colors.HexColor("#697882")
LIGHT_GRAY = colors.HexColor("#F3F5F6")

styles = getSampleStyleSheet()
styles.add(
    ParagraphStyle(
        name="ManualTitle",
        parent=styles["Title"],
        fontName="Helvetica-Bold",
        fontSize=26,
        leading=30,
        textColor=NAVY,
        alignment=TA_LEFT,
        spaceAfter=8 * mm,
    )
)
styles.add(
    ParagraphStyle(
        name="ManualSubtitle",
        parent=styles["Normal"],
        fontName="Helvetica",
        fontSize=12,
        leading=17,
        textColor=GRAY,
        spaceAfter=6 * mm,
    )
)
styles.add(
    ParagraphStyle(
        name="Section",
        parent=styles["Heading2"],
        fontName="Helvetica-Bold",
        fontSize=17,
        leading=21,
        textColor=NAVY,
        spaceBefore=3 * mm,
        spaceAfter=4 * mm,
    )
)
styles.add(
    ParagraphStyle(
        name="Step",
        parent=styles["Heading3"],
        fontName="Helvetica-Bold",
        fontSize=13,
        leading=16,
        textColor=BLUE,
        spaceBefore=3 * mm,
        spaceAfter=2 * mm,
    )
)
styles.add(
    ParagraphStyle(
        name="Body2",
        parent=styles["BodyText"],
        fontName="Helvetica",
        fontSize=9.5,
        leading=13.5,
        textColor=INK,
        spaceAfter=2.5 * mm,
    )
)
styles.add(
    ParagraphStyle(
        name="Small",
        parent=styles["BodyText"],
        fontName="Helvetica",
        fontSize=8,
        leading=10.5,
        textColor=GRAY,
    )
)
styles.add(
    ParagraphStyle(
        name="CardLabel",
        parent=styles["BodyText"],
        fontName="Helvetica-Bold",
        fontSize=8.5,
        leading=11,
        textColor=NAVY,
        alignment=TA_CENTER,
    )
)


def footer(canvas, doc):
    canvas.saveState()
    canvas.setStrokeColor(colors.HexColor("#D8E0E5"))
    canvas.line(MARGIN_X, 12 * mm, PAGE_W - MARGIN_X, 12 * mm)
    canvas.setFont("Helvetica", 7.5)
    canvas.setFillColor(GRAY)
    canvas.drawString(MARGIN_X, 7.8 * mm, "BOOK-RIG 01 | Proxy equipment manual | BR01-MANUAL-v1")
    canvas.drawRightString(PAGE_W - MARGIN_X, 7.8 * mm, f"Page {doc.page}")
    canvas.restoreState()


def draw_book(canvas, x, y, w, h, disk="left", module="holder", cover_open=True):
    canvas.saveState()
    book_w = w - 9 * mm

    def draw_marker():
        marker_size = 6 * mm
        marker_x = x + book_w + 2 * mm
        marker_y = y + 3 * mm
        cell = marker_size / 3
        canvas.setStrokeColor(NAVY)
        canvas.rect(marker_x, marker_y, marker_size, marker_size, fill=0, stroke=1)
        for row in range(3):
            for col in range(3):
                canvas.setFillColor(
                    NAVY if (row + col) % 2 == 0 else colors.white
                )
                canvas.rect(
                    marker_x + col * cell,
                    marker_y + row * cell,
                    cell,
                    cell,
                    fill=1,
                    stroke=0,
                )
        canvas.setFillColor(NAVY)
        canvas.setFont("Helvetica-Bold", 4.8)
        canvas.drawCentredString(
            marker_x + marker_size / 2,
            marker_y + marker_size + 1.2 * mm,
            "FIXED",
        )

    if not cover_open:
        canvas.setFillColor(NAVY)
        canvas.roundRect(x, y, book_w, h, 4 * mm, fill=1, stroke=0)
        canvas.setFillColor(colors.white)
        canvas.setFont("Helvetica-Bold", 10)
        canvas.drawCentredString(
            x + book_w / 2, y + h / 2, "ACCESS COVER CLOSED"
        )
        draw_marker()
        canvas.restoreState()
        return

    gap = 3 * mm
    page_w = (book_w - gap) / 2
    canvas.setFillColor(colors.HexColor("#FFFDF5"))
    canvas.setStrokeColor(colors.HexColor("#B7C0C5"))
    canvas.roundRect(x, y, page_w, h, 3 * mm, fill=1, stroke=1)
    canvas.roundRect(x + page_w + gap, y, page_w, h, 3 * mm, fill=1, stroke=1)
    canvas.setStrokeColor(colors.HexColor("#D2D8DC"))
    canvas.line(x + page_w + gap / 2, y + 2 * mm, x + page_w + gap / 2, y + h - 2 * mm)

    # Module holder
    holder_x = x + 6 * mm
    holder_y = y + 8 * mm
    holder_w = page_w - 12 * mm
    holder_h = 12 * mm
    canvas.setDash(3, 2)
    canvas.setStrokeColor(BLUE)
    canvas.rect(holder_x, holder_y, holder_w, holder_h, fill=0, stroke=1)
    canvas.setDash()
    canvas.setFont("Helvetica-Bold", 6.5)
    canvas.setFillColor(BLUE)
    canvas.drawString(holder_x, holder_y + holder_h + 2 * mm, "MODULE HOLDER")

    # Module
    module_w = 16 * mm
    module_h = 7 * mm
    if module == "holder":
        mx = holder_x + (holder_w - module_w) / 2
        my = holder_y + (holder_h - module_h) / 2
    elif module == "target":
        mx = x + page_w + gap + 8 * mm
        my = y + 6.5 * mm
    else:
        mx = x + page_w - 5 * mm
        my = y + h / 2 - 7 * mm
    canvas.setFillColor(YELLOW)
    canvas.setStrokeColor(colors.HexColor("#B58D18"))
    canvas.roundRect(mx, my, module_w, module_h, 1.5 * mm, fill=1, stroke=1)
    canvas.setFillColor(NAVY)
    canvas.setFont("Helvetica-Bold", 5.5)
    canvas.drawCentredString(
        mx + module_w / 2, my + 2.2 * mm, "MODULE A"
    )

    # Target slot
    slot_x = x + page_w + gap + 6 * mm
    slot_y = y + 5 * mm
    slot_w = page_w - 12 * mm
    slot_h = 10 * mm
    canvas.setFillColor(LIGHT_GREEN)
    canvas.setStrokeColor(GREEN)
    canvas.setLineWidth(1.5)
    canvas.roundRect(slot_x, slot_y, slot_w, slot_h, 2 * mm, fill=1, stroke=1)
    canvas.setFillColor(colors.HexColor("#447C37"))
    canvas.setFont("Helvetica-Bold", 6.5)
    canvas.drawString(slot_x, slot_y + slot_h + 2 * mm, "TARGET SLOT")
    if module == "target":
        canvas.setFillColor(YELLOW)
        canvas.setStrokeColor(colors.HexColor("#B58D18"))
        canvas.roundRect(
            mx, my, module_w, module_h, 1.5 * mm, fill=1, stroke=1
        )
        canvas.setFillColor(NAVY)
        canvas.setFont("Helvetica-Bold", 5.5)
        canvas.drawCentredString(
            mx + module_w / 2, my + 2.2 * mm, "MODULE A"
        )

    # Control disk
    cx = x + page_w + gap + page_w / 2
    cy = y + h - 11 * mm
    r = 8 * mm
    canvas.setFillColor(LIGHT_BLUE)
    canvas.setStrokeColor(BLUE)
    canvas.circle(cx, cy, r, fill=1, stroke=1)
    if disk == "up":
        dx, dy = 0, r - 2 * mm
    elif disk == "down":
        dx, dy = 0, -r + 2 * mm
    elif disk == "right":
        dx, dy = r - 2 * mm, 0
    else:
        dx, dy = -r + 2 * mm, 0
    canvas.setStrokeColor(RED)
    canvas.setFillColor(RED)
    canvas.setLineWidth(3)
    canvas.line(cx, cy, cx + dx, cy + dy)
    canvas.circle(cx + dx, cy + dy, 1.2 * mm, fill=1, stroke=0)
    canvas.setFont("Helvetica-Bold", 6.5)
    canvas.setFillColor(RED)
    canvas.drawCentredString(cx, cy + r + 3 * mm, f"CONTROL: {disk.upper()}")
    draw_marker()
    canvas.restoreState()


def diagram_flowable(label, disk="left", module="holder", cover_open=True):
    from reportlab.platypus import Flowable

    class Diagram(Flowable):
        def __init__(self):
            super().__init__()
            self.width = 76 * mm
            self.height = 48 * mm

        def draw(self):
            draw_book(
                self.canv,
                0,
                0,
                self.width,
                self.height - 7 * mm,
                disk=disk,
                module=module,
                cover_open=cover_open,
            )
            self.canv.setFont("Helvetica-Bold", 7.5)
            self.canv.setFillColor(NAVY)
            self.canv.drawCentredString(self.width / 2, self.height - 5 * mm, label)

    return Diagram()


def info_box(title, body, background=LIGHT_BLUE, border=BLUE):
    table = Table(
        [[Paragraph(f"<b>{title}</b><br/>{body}", styles["Body2"])]],
        colWidths=[PAGE_W - 2 * MARGIN_X],
    )
    table.setStyle(
        TableStyle(
            [
                ("BACKGROUND", (0, 0), (-1, -1), background),
                ("BOX", (0, 0), (-1, -1), 0.8, border),
                ("LEFTPADDING", (0, 0), (-1, -1), 8),
                ("RIGHTPADDING", (0, 0), (-1, -1), 8),
                ("TOPPADDING", (0, 0), (-1, -1), 7),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
            ]
        )
    )
    return table


def step_block(number, title, instruction, expected, wrong, diagram):
    text = [
        Paragraph(f"Step {number} - {title}", styles["Step"]),
        Paragraph(instruction, styles["Body2"]),
        Paragraph(f"<b>Expected:</b> {expected}", styles["Body2"]),
        Paragraph(f"<b>Wrong or uncertain:</b> {wrong}", styles["Body2"]),
    ]
    left = Table([[item] for item in text], colWidths=[88 * mm])
    left.setStyle(TableStyle([("VALIGN", (0, 0), (-1, -1), "TOP")]))
    table = Table([[left, diagram]], colWidths=[92 * mm, 76 * mm], hAlign="LEFT")
    table.setStyle(
        TableStyle(
            [
                ("VALIGN", (0, 0), (-1, -1), "TOP"),
                ("BOX", (0, 0), (-1, -1), 0.6, colors.HexColor("#D6E0E5")),
                ("BACKGROUND", (0, 0), (-1, -1), colors.white),
                ("LEFTPADDING", (0, 0), (-1, -1), 7),
                ("RIGHTPADDING", (0, 0), (-1, -1), 7),
                ("TOPPADDING", (0, 0), (-1, -1), 6),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
            ]
        )
    )
    return table


doc = BaseDocTemplate(
    str(OUTPUT),
    pagesize=A4,
    rightMargin=MARGIN_X,
    leftMargin=MARGIN_X,
    topMargin=MARGIN_TOP,
    bottomMargin=MARGIN_BOTTOM,
    title="BOOK-RIG 01 Proxy Equipment Manual",
    author="Manual2AR Project",
    subject="Proxy manual for manual-scene alignment testing",
)
frame = Frame(
    MARGIN_X,
    MARGIN_BOTTOM,
    PAGE_W - 2 * MARGIN_X,
    PAGE_H - MARGIN_TOP - MARGIN_BOTTOM,
    id="normal",
)
doc.addPageTemplates([PageTemplate(id="manual", frames=frame, onPage=footer)])

story = []
story.append(Paragraph("BOOK-RIG 01", styles["ManualTitle"]))
story.append(
    Paragraph(
        "Proxy Equipment Manual for Manual-Scene Alignment Testing",
        styles["ManualSubtitle"],
    )
)
story.append(
    info_box(
        "Scope notice",
        "This document is for pre-laboratory model testing only. It is not an "
        "instruction for operating a real 3D printer or any other equipment.",
        background=colors.HexColor("#FFF5E8"),
        border=colors.HexColor("#D58B2B"),
    )
)
story.append(Spacer(1, 7 * mm))
story.append(diagram_flowable("REFERENCE LAYOUT", disk="left", module="holder"))
story.append(Spacer(1, 5 * mm))
story.append(Paragraph("Components", styles["Section"]))
component_rows = [
    ["ID", "Component", "Required visual property"],
    ["A", "Fixed marker", "Stationary and visible beside the book"],
    ["B", "Access cover", "Clearly open or fully closed"],
    ["C", "Control disk", "Arrow points LEFT or UP"],
    ["D", "Module A", "Yellow card with readable label"],
    ["E", "Module holder", "Outlined region on the left page"],
    ["F", "Target slot", "Green pocket on the right page"],
]
component_table = Table(component_rows, colWidths=[12 * mm, 47 * mm, 109 * mm])
component_table.setStyle(
    TableStyle(
        [
            ("BACKGROUND", (0, 0), (-1, 0), NAVY),
            ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
            ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
            ("FONTNAME", (0, 1), (-1, -1), "Helvetica"),
            ("FONTSIZE", (0, 0), (-1, -1), 8),
            ("LEADING", (0, 0), (-1, -1), 10),
            ("GRID", (0, 0), (-1, -1), 0.35, colors.HexColor("#CAD4DA")),
            ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, LIGHT_GRAY]),
            ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
            ("TOPPADDING", (0, 0), (-1, -1), 5),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
        ]
    )
)
story.append(component_table)
story.append(Spacer(1, 3 * mm))
story.append(
    Paragraph(
        "Initial state: cover closed; disk LEFT; Module A in holder; target slot empty.",
        styles["Small"],
    )
)

story.append(PageBreak())
story.append(Paragraph("Procedure - Part 1", styles["Section"]))
story.append(
    step_block(
        1,
        "Open the access cover",
        "Open the front cover until both marked pages are visible.",
        "Control disk, module holder, Module A, and target slot are visible.",
        "Any required component is hidden or the view is too oblique.",
        diagram_flowable("S1: COVER OPEN", disk="left", module="holder"),
    )
)
story.append(Spacer(1, 4 * mm))
story.append(
    step_block(
        2,
        "Set the control disk",
        "Rotate the control disk clockwise until the arrow points UP.",
        "The arrow tip overlaps the UP mark.",
        "Arrow points LEFT, RIGHT, DOWN, or remains between marks.",
        diagram_flowable("S2: DISK UP", disk="up", module="holder"),
    )
)
story.append(Spacer(1, 4 * mm))
story.append(
    step_block(
        3,
        "Remove Module A",
        "Remove the yellow Module A from the outlined holder.",
        "The holder is empty and Module A is visible outside it.",
        "Module A is partly inside, another object is removed, or the holder is hidden.",
        diagram_flowable("S3: MODULE REMOVED", disk="up", module="outside"),
    )
)

story.append(PageBreak())
story.append(Paragraph("Procedure - Part 2", styles["Section"]))
story.append(
    step_block(
        4,
        "Insert Module A",
        "Place yellow Module A fully inside the green target slot.",
        "Module A is centered inside the target slot with no large boundary crossing.",
        "Wrong object, wrong region, partial insertion, or severe occlusion.",
        diagram_flowable("S4: MODULE IN SLOT", disk="up", module="target"),
    )
)
story.append(Spacer(1, 5 * mm))
story.append(
    step_block(
        5,
        "Close the access cover",
        "After Step 4 has been verified, close the front cover completely.",
        "The cover is closed and the fixed marker remains visible.",
        "Step 4 was not verified, the cover is partly open, or the marker is missing.",
        diagram_flowable("S5: COVER CLOSED", cover_open=False),
    )
)
story.append(Spacer(1, 6 * mm))
story.append(Paragraph("Uncertainty and recovery", styles["Section"]))
story.append(
    info_box(
        "Conservative verification rule",
        "If a target component is hidden, blurred, or outside the image, request "
        "another view and do not advance. If a prerequisite is missing, return "
        "to the first unmet step. Never infer a hidden success from hand motion.",
        background=colors.HexColor("#FDEEEE"),
        border=RED,
    )
)
story.append(Spacer(1, 5 * mm))
verification_rows = [
    ["Observed condition", "Required output"],
    ["Clear expected state", "completed; advance may be allowed"],
    ["Visible wrong state", "wrong_operation; show recovery"],
    ["Incomplete transition", "in_progress; remain on current step"],
    ["Occluded or unsupported", "uncertain; request another view"],
]
verification_table = Table(verification_rows, colWidths=[83 * mm, 85 * mm])
verification_table.setStyle(
    TableStyle(
        [
            ("BACKGROUND", (0, 0), (-1, 0), NAVY),
            ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
            ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
            ("FONTNAME", (0, 1), (-1, -1), "Helvetica"),
            ("FONTSIZE", (0, 0), (-1, -1), 8),
            ("GRID", (0, 0), (-1, -1), 0.35, colors.HexColor("#CAD4DA")),
            ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, LIGHT_GRAY]),
            ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
            ("TOPPADDING", (0, 0), (-1, -1), 5),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
        ]
    )
)
story.append(verification_table)

doc.build(story)
print(OUTPUT)
