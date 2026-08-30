from __future__ import annotations

from pathlib import Path
from typing import Iterable

from PIL import Image, ImageDraw, ImageFont
from docx import Document
from docx.enum.section import WD_ORIENT, WD_SECTION
from docx.enum.table import WD_ALIGN_VERTICAL, WD_TABLE_ALIGNMENT
from docx.enum.text import WD_ALIGN_PARAGRAPH
from docx.oxml import OxmlElement
from docx.oxml.ns import qn
from docx.shared import Inches, Pt, RGBColor


ROOT = Path(__file__).resolve().parents[1]
OUT_DIR = ROOT / "output" / "briefs"
ASSET_DIR = OUT_DIR / "assets"
DOCX_PATH = OUT_DIR / "Manual2AR_技术方案_师兄同步版_v0.1.docx"
DIAGRAM_PATH = ASSET_DIR / "manual2ar_detailed_architecture.png"


# standard_business_brief preset, with a named CJK fallback override.
PAGE_WIDTH_IN = 8.5
PAGE_HEIGHT_IN = 11.0
MARGIN_IN = 1.0
CONTENT_WIDTH_DXA = 9360
TABLE_INDENT_DXA = 120
CELL_MARGINS = {"top": 80, "bottom": 80, "start": 120, "end": 120}
FONT_LATIN = "Arial Unicode MS"
FONT_CJK = "Arial Unicode MS"

NAVY = "183B56"
BLUE = "2E74B5"
DARK_BLUE = "1F4D78"
TEAL = "0E7490"
INK = "1F2937"
GRAY = "5F6B76"
LIGHT_GRAY = "F2F4F7"
BLUE_GRAY = "E8EEF5"
PALE_BLUE = "EDF5FB"
PALE_GREEN = "ECF7F1"
PALE_GOLD = "FFF7E6"
PALE_RED = "FDEEEE"
GREEN = "2F6B4F"
GOLD = "8A6400"
RED = "9B1C1C"
WHITE = "FFFFFF"


def rgb(hex_value: str) -> RGBColor:
    return RGBColor.from_string(hex_value)


def set_run_font(
    run,
    *,
    size: float | None = None,
    bold: bool | None = None,
    italic: bool | None = None,
    color: str | None = None,
    latin: str = FONT_LATIN,
    cjk: str = FONT_CJK,
) -> None:
    run.font.name = latin
    run._element.get_or_add_rPr().rFonts.set(qn("w:ascii"), latin)
    run._element.get_or_add_rPr().rFonts.set(qn("w:hAnsi"), latin)
    run._element.get_or_add_rPr().rFonts.set(qn("w:eastAsia"), cjk)
    if size is not None:
        run.font.size = Pt(size)
    if bold is not None:
        run.bold = bold
    if italic is not None:
        run.italic = italic
    if color is not None:
        run.font.color.rgb = rgb(color)


def set_cell_shading(cell, fill: str) -> None:
    tc_pr = cell._tc.get_or_add_tcPr()
    shd = tc_pr.find(qn("w:shd"))
    if shd is None:
        shd = OxmlElement("w:shd")
        tc_pr.append(shd)
    shd.set(qn("w:fill"), fill)


def set_cell_margins(cell, **margins: int) -> None:
    tc = cell._tc
    tc_pr = tc.get_or_add_tcPr()
    tc_mar = tc_pr.first_child_found_in("w:tcMar")
    if tc_mar is None:
        tc_mar = OxmlElement("w:tcMar")
        tc_pr.append(tc_mar)
    for margin in ["top", "start", "bottom", "end"]:
        if margin in margins:
            node = tc_mar.find(qn(f"w:{margin}"))
            if node is None:
                node = OxmlElement(f"w:{margin}")
                tc_mar.append(node)
            node.set(qn("w:w"), str(margins[margin]))
            node.set(qn("w:type"), "dxa")


def set_repeat_table_header(row) -> None:
    tr_pr = row._tr.get_or_add_trPr()
    tbl_header = OxmlElement("w:tblHeader")
    tbl_header.set(qn("w:val"), "true")
    tr_pr.append(tbl_header)


def set_row_cant_split(row) -> None:
    tr_pr = row._tr.get_or_add_trPr()
    cant_split = OxmlElement("w:cantSplit")
    cant_split.set(qn("w:val"), "true")
    tr_pr.append(cant_split)


def set_table_geometry(table, widths_dxa: list[int], indent_dxa: int = TABLE_INDENT_DXA) -> None:
    assert sum(widths_dxa) == CONTENT_WIDTH_DXA, (widths_dxa, sum(widths_dxa))
    table.autofit = False
    table.alignment = WD_TABLE_ALIGNMENT.LEFT
    tbl_pr = table._tbl.tblPr
    tbl_w = tbl_pr.find(qn("w:tblW"))
    if tbl_w is None:
        tbl_w = OxmlElement("w:tblW")
        tbl_pr.append(tbl_w)
    tbl_w.set(qn("w:w"), str(CONTENT_WIDTH_DXA))
    tbl_w.set(qn("w:type"), "dxa")
    tbl_ind = tbl_pr.find(qn("w:tblInd"))
    if tbl_ind is None:
        tbl_ind = OxmlElement("w:tblInd")
        tbl_pr.append(tbl_ind)
    tbl_ind.set(qn("w:w"), str(indent_dxa))
    tbl_ind.set(qn("w:type"), "dxa")
    grid = table._tbl.tblGrid
    for child in list(grid):
        grid.remove(child)
    for width in widths_dxa:
        col = OxmlElement("w:gridCol")
        col.set(qn("w:w"), str(width))
        grid.append(col)
    for row in table.rows:
        for idx, cell in enumerate(row.cells):
            tc_pr = cell._tc.get_or_add_tcPr()
            tc_w = tc_pr.find(qn("w:tcW"))
            if tc_w is None:
                tc_w = OxmlElement("w:tcW")
                tc_pr.append(tc_w)
            tc_w.set(qn("w:w"), str(widths_dxa[idx]))
            tc_w.set(qn("w:type"), "dxa")
            set_cell_margins(cell, **CELL_MARGINS)


def set_cell_border(cell, color: str = "D5DCE3", size: int = 6) -> None:
    tc_pr = cell._tc.get_or_add_tcPr()
    borders = tc_pr.first_child_found_in("w:tcBorders")
    if borders is None:
        borders = OxmlElement("w:tcBorders")
        tc_pr.append(borders)
    for edge in ("top", "start", "bottom", "end", "insideH", "insideV"):
        tag = borders.find(qn(f"w:{edge}"))
        if tag is None:
            tag = OxmlElement(f"w:{edge}")
            borders.append(tag)
        tag.set(qn("w:val"), "single")
        tag.set(qn("w:sz"), str(size))
        tag.set(qn("w:space"), "0")
        tag.set(qn("w:color"), color)


def add_hyperlink(paragraph, text: str, url: str, color: str = BLUE) -> None:
    part = paragraph.part
    relationship_id = part.relate_to(
        url,
        "http://schemas.openxmlformats.org/officeDocument/2006/relationships/hyperlink",
        is_external=True,
    )
    hyperlink = OxmlElement("w:hyperlink")
    hyperlink.set(qn("r:id"), relationship_id)
    run = OxmlElement("w:r")
    r_pr = OxmlElement("w:rPr")
    r_fonts = OxmlElement("w:rFonts")
    r_fonts.set(qn("w:ascii"), FONT_LATIN)
    r_fonts.set(qn("w:hAnsi"), FONT_LATIN)
    r_fonts.set(qn("w:eastAsia"), FONT_CJK)
    r_pr.append(r_fonts)
    c = OxmlElement("w:color")
    c.set(qn("w:val"), color)
    r_pr.append(c)
    u = OxmlElement("w:u")
    u.set(qn("w:val"), "single")
    r_pr.append(u)
    run.append(r_pr)
    t = OxmlElement("w:t")
    t.text = text
    run.append(t)
    hyperlink.append(run)
    paragraph._p.append(hyperlink)


def add_page_number(paragraph) -> None:
    paragraph.alignment = WD_ALIGN_PARAGRAPH.RIGHT
    run = paragraph.add_run("第 ")
    set_run_font(run, size=9, color=GRAY)
    fld_char1 = OxmlElement("w:fldChar")
    fld_char1.set(qn("w:fldCharType"), "begin")
    instr_text = OxmlElement("w:instrText")
    instr_text.set(qn("xml:space"), "preserve")
    instr_text.text = " PAGE "
    fld_char2 = OxmlElement("w:fldChar")
    fld_char2.set(qn("w:fldCharType"), "end")
    r = OxmlElement("w:r")
    r.append(fld_char1)
    r.append(instr_text)
    r.append(fld_char2)
    paragraph._p.append(r)
    run2 = paragraph.add_run(" 页")
    set_run_font(run2, size=9, color=GRAY)


def add_numbering_definition(doc: Document) -> tuple[int, int]:
    numbering = doc.part.numbering_part.element
    max_abs = max(
        [int(x.get(qn("w:abstractNumId"))) for x in numbering.findall(qn("w:abstractNum"))]
        or [0]
    )
    max_num = max([int(x.get(qn("w:numId"))) for x in numbering.findall(qn("w:num"))] or [0])

    def create_abstract(abstract_id: int, fmt: str, text: str, left: int, hanging: int) -> None:
        abstract = OxmlElement("w:abstractNum")
        abstract.set(qn("w:abstractNumId"), str(abstract_id))
        multi = OxmlElement("w:multiLevelType")
        multi.set(qn("w:val"), "singleLevel")
        abstract.append(multi)
        lvl = OxmlElement("w:lvl")
        lvl.set(qn("w:ilvl"), "0")
        start = OxmlElement("w:start")
        start.set(qn("w:val"), "1")
        lvl.append(start)
        num_fmt = OxmlElement("w:numFmt")
        num_fmt.set(qn("w:val"), fmt)
        lvl.append(num_fmt)
        lvl_text = OxmlElement("w:lvlText")
        lvl_text.set(qn("w:val"), text)
        lvl.append(lvl_text)
        suff = OxmlElement("w:suff")
        suff.set(qn("w:val"), "tab")
        lvl.append(suff)
        p_pr = OxmlElement("w:pPr")
        tabs = OxmlElement("w:tabs")
        tab = OxmlElement("w:tab")
        tab.set(qn("w:val"), "num")
        tab.set(qn("w:pos"), str(left))
        tabs.append(tab)
        p_pr.append(tabs)
        ind = OxmlElement("w:ind")
        ind.set(qn("w:left"), str(left))
        ind.set(qn("w:hanging"), str(hanging))
        p_pr.append(ind)
        spacing = OxmlElement("w:spacing")
        spacing.set(qn("w:after"), "160")
        spacing.set(qn("w:line"), "280")
        spacing.set(qn("w:lineRule"), "auto")
        p_pr.append(spacing)
        lvl.append(p_pr)
        abstract.append(lvl)
        numbering.append(abstract)

    def create_num(num_id: int, abstract_id: int) -> None:
        num = OxmlElement("w:num")
        num.set(qn("w:numId"), str(num_id))
        abstract_ref = OxmlElement("w:abstractNumId")
        abstract_ref.set(qn("w:val"), str(abstract_id))
        num.append(abstract_ref)
        numbering.append(num)

    bullet_abs = max_abs + 1
    decimal_abs = max_abs + 2
    bullet_num = max_num + 1
    decimal_num = max_num + 2
    create_abstract(bullet_abs, "bullet", "•", 720, 360)
    create_abstract(decimal_abs, "decimal", "%1.", 720, 360)
    create_num(bullet_num, bullet_abs)
    create_num(decimal_num, decimal_abs)
    return bullet_num, decimal_num


def apply_num(paragraph, num_id: int) -> None:
    p_pr = paragraph._p.get_or_add_pPr()
    num_pr = p_pr.find(qn("w:numPr"))
    if num_pr is None:
        num_pr = OxmlElement("w:numPr")
        p_pr.append(num_pr)
    ilvl = OxmlElement("w:ilvl")
    ilvl.set(qn("w:val"), "0")
    num_id_el = OxmlElement("w:numId")
    num_id_el.set(qn("w:val"), str(num_id))
    num_pr.append(ilvl)
    num_pr.append(num_id_el)


def configure_styles(doc: Document) -> None:
    styles = doc.styles
    normal = styles["Normal"]
    normal.font.name = FONT_LATIN
    normal._element.rPr.rFonts.set(qn("w:eastAsia"), FONT_CJK)
    normal.font.size = Pt(11)
    normal.font.color.rgb = rgb(INK)
    normal.paragraph_format.space_before = Pt(0)
    normal.paragraph_format.space_after = Pt(6)
    normal.paragraph_format.line_spacing = 1.10

    for name, size, color, before, after in [
        ("Heading 1", 16, BLUE, 16, 8),
        ("Heading 2", 13, BLUE, 12, 6),
        ("Heading 3", 12, DARK_BLUE, 8, 4),
    ]:
        style = styles[name]
        style.font.name = FONT_LATIN
        style._element.rPr.rFonts.set(qn("w:eastAsia"), FONT_CJK)
        style.font.size = Pt(size)
        style.font.bold = True
        style.font.color.rgb = rgb(color)
        style.paragraph_format.space_before = Pt(before)
        style.paragraph_format.space_after = Pt(after)
        style.paragraph_format.keep_with_next = True

    caption = styles["Caption"]
    caption.font.name = FONT_LATIN
    caption._element.rPr.rFonts.set(qn("w:eastAsia"), FONT_CJK)
    caption.font.size = Pt(9.5)
    caption.font.color.rgb = rgb(GRAY)
    caption.paragraph_format.space_before = Pt(4)
    caption.paragraph_format.space_after = Pt(8)


def set_section_geometry(section, *, landscape: bool = False, margin: float = MARGIN_IN) -> None:
    if landscape:
        section.orientation = WD_ORIENT.LANDSCAPE
        section.page_width = Inches(PAGE_HEIGHT_IN)
        section.page_height = Inches(PAGE_WIDTH_IN)
    else:
        section.orientation = WD_ORIENT.PORTRAIT
        section.page_width = Inches(PAGE_WIDTH_IN)
        section.page_height = Inches(PAGE_HEIGHT_IN)
    section.top_margin = Inches(margin)
    section.bottom_margin = Inches(margin)
    section.left_margin = Inches(margin)
    section.right_margin = Inches(margin)
    section.header_distance = Inches(0.492)
    section.footer_distance = Inches(0.492)


def set_header_footer(section, header_right: str = "技术同步简报") -> None:
    section.header.is_linked_to_previous = False
    section.footer.is_linked_to_previous = False
    header = section.header
    p = header.paragraphs[0]
    p.clear()
    p.alignment = WD_ALIGN_PARAGRAPH.RIGHT
    p.paragraph_format.space_after = Pt(0)
    r = p.add_run(f"Manual2AR  |  {header_right}")
    set_run_font(r, size=9, color=GRAY)
    footer = section.footer
    fp = footer.paragraphs[0]
    fp.clear()
    add_page_number(fp)


def add_para(
    doc: Document,
    text: str,
    *,
    bold_prefix: str | None = None,
    size: float | None = None,
    color: str | None = None,
    after: float | None = None,
    alignment: WD_ALIGN_PARAGRAPH | None = None,
) -> None:
    p = doc.add_paragraph()
    if alignment is not None:
        p.alignment = alignment
    if after is not None:
        p.paragraph_format.space_after = Pt(after)
    if bold_prefix and text.startswith(bold_prefix):
        r1 = p.add_run(bold_prefix)
        set_run_font(r1, size=size, bold=True, color=color or INK)
        r2 = p.add_run(text[len(bold_prefix):])
        set_run_font(r2, size=size, color=color or INK)
    else:
        r = p.add_run(text)
        set_run_font(r, size=size, color=color or INK)


def add_bullets(doc: Document, items: Iterable[str], bullet_num: int) -> None:
    for item in items:
        p = doc.add_paragraph()
        apply_num(p, bullet_num)
        p.paragraph_format.space_after = Pt(8)
        p.paragraph_format.line_spacing = 1.167
        r = p.add_run(item)
        set_run_font(r)


def add_numbered(doc: Document, items: Iterable[str], decimal_num: int) -> None:
    for item in items:
        p = doc.add_paragraph()
        apply_num(p, decimal_num)
        p.paragraph_format.space_after = Pt(8)
        p.paragraph_format.line_spacing = 1.167
        r = p.add_run(item)
        set_run_font(r)


def add_callout(doc: Document, title: str, text: str, fill: str = PALE_BLUE, accent: str = BLUE) -> None:
    table = doc.add_table(rows=1, cols=1)
    set_row_cant_split(table.rows[0])
    set_table_geometry(table, [CONTENT_WIDTH_DXA])
    cell = table.cell(0, 0)
    set_cell_shading(cell, fill)
    set_cell_border(cell, color=accent, size=10)
    cell.vertical_alignment = WD_ALIGN_VERTICAL.CENTER
    p = cell.paragraphs[0]
    p.paragraph_format.space_after = Pt(2)
    rt = p.add_run(title + "\n")
    set_run_font(rt, bold=True, color=accent, size=11)
    rb = p.add_run(text)
    set_run_font(rb, color=INK, size=10.5)
    doc.add_paragraph().paragraph_format.space_after = Pt(0)


def add_table(
    doc: Document,
    headers: list[str],
    rows: list[list[str]],
    widths_dxa: list[int],
    *,
    header_fill: str = LIGHT_GRAY,
    font_size: float = 9.2,
) -> None:
    table = doc.add_table(rows=1, cols=len(headers))
    table.alignment = WD_TABLE_ALIGNMENT.LEFT
    hdr = table.rows[0]
    set_repeat_table_header(hdr)
    set_row_cant_split(hdr)
    for idx, text in enumerate(headers):
        cell = hdr.cells[idx]
        set_cell_shading(cell, header_fill)
        set_cell_border(cell)
        cell.vertical_alignment = WD_ALIGN_VERTICAL.CENTER
        p = cell.paragraphs[0]
        p.alignment = WD_ALIGN_PARAGRAPH.CENTER
        p.paragraph_format.space_after = Pt(0)
        r = p.add_run(text)
        set_run_font(r, bold=True, size=font_size, color=NAVY)
    for row_data in rows:
        row = table.add_row()
        set_row_cant_split(row)
        for idx, text in enumerate(row_data):
            cell = row.cells[idx]
            set_cell_border(cell)
            cell.vertical_alignment = WD_ALIGN_VERTICAL.CENTER
            p = cell.paragraphs[0]
            p.paragraph_format.space_after = Pt(0)
            p.paragraph_format.line_spacing = 1.08
            r = p.add_run(text)
            set_run_font(r, size=font_size, color=INK)
    set_table_geometry(table, widths_dxa)
    doc.add_paragraph().paragraph_format.space_after = Pt(0)


def pil_font(size: int, bold: bool = False) -> ImageFont.FreeTypeFont:
    path = "/System/Library/Fonts/STHeiti Medium.ttc" if bold else "/System/Library/Fonts/STHeiti Light.ttc"
    return ImageFont.truetype(path, size=size)


def wrap_text(draw: ImageDraw.ImageDraw, text: str, font: ImageFont.FreeTypeFont, max_width: int) -> list[str]:
    lines: list[str] = []
    for paragraph in text.split("\n"):
        current = ""
        for char in paragraph:
            candidate = current + char
            if draw.textbbox((0, 0), candidate, font=font)[2] <= max_width:
                current = candidate
            else:
                if current:
                    lines.append(current)
                current = char
        if current:
            lines.append(current)
    return lines


def draw_centered_text(
    draw: ImageDraw.ImageDraw,
    box: tuple[int, int, int, int],
    text: str,
    *,
    font: ImageFont.FreeTypeFont,
    fill: str,
    padding: int = 20,
) -> None:
    x1, y1, x2, y2 = box
    lines = wrap_text(draw, text, font, max_width=x2 - x1 - 2 * padding)
    bbox = draw.textbbox((0, 0), "国Ag", font=font)
    line_h = bbox[3] - bbox[1] + 8
    total_h = line_h * len(lines)
    y = y1 + (y2 - y1 - total_h) / 2
    for line in lines:
        b = draw.textbbox((0, 0), line, font=font)
        w = b[2] - b[0]
        draw.text((x1 + (x2 - x1 - w) / 2, y), line, font=font, fill=fill)
        y += line_h


def draw_node(
    draw: ImageDraw.ImageDraw,
    box: tuple[int, int, int, int],
    title: str,
    detail: str,
    *,
    fill: str,
    outline: str,
) -> None:
    draw.rounded_rectangle(box, radius=24, fill=fill, outline=outline, width=4)
    x1, y1, x2, y2 = box
    title_font = pil_font(29, bold=True)
    detail_font = pil_font(23)
    title_box = (x1 + 14, y1 + 12, x2 - 14, y1 + 64)
    draw_centered_text(draw, title_box, title, font=title_font, fill=outline, padding=8)
    detail_box = (x1 + 16, y1 + 65, x2 - 16, y2 - 12)
    draw_centered_text(draw, detail_box, detail, font=detail_font, fill="#26313B", padding=10)


def arrow(draw: ImageDraw.ImageDraw, start: tuple[int, int], end: tuple[int, int], color: str = "#4B6072") -> None:
    draw.line([start, end], fill=color, width=8)
    x2, y2 = end
    x1, y1 = start
    if abs(x2 - x1) >= abs(y2 - y1):
        sign = 1 if x2 > x1 else -1
        pts = [(x2, y2), (x2 - sign * 24, y2 - 15), (x2 - sign * 24, y2 + 15)]
    else:
        sign = 1 if y2 > y1 else -1
        pts = [(x2, y2), (x2 - 15, y2 - sign * 24), (x2 + 15, y2 - sign * 24)]
    draw.polygon(pts, fill=color)


def build_diagram(path: Path) -> None:
    width, height = 3000, 1880
    img = Image.new("RGB", (width, height), "#F8FAFC")
    draw = ImageDraw.Draw(img)
    draw.text((90, 45), "Manual2AR 单设备闭环详细架构", font=pil_font(50, bold=True), fill="#183B56")
    draw.text((90, 112), "离线编译 + 运行时感知 + 证据融合 + 安全交互 + 自动评测", font=pil_font(28), fill="#5F6B76")

    lanes = [
        (170, 535, "阶段一　说明书编译", "#EAF3FA", "#2E74B5"),
        (560, 1045, "阶段二　现场视觉感知", "#EAF7F7", "#0E7490"),
        (1070, 1415, "阶段三　融合决策与安全交互", "#EEF7F0", "#2F6B4F"),
        (1440, 1815, "阶段四　Codex 自动评测", "#FFF6E3", "#8A6400"),
    ]
    for top, bottom, label, fill, outline in lanes:
        draw.rounded_rectangle((70, top, 2930, bottom), radius=28, fill=fill, outline=outline, width=4)
        draw.text((95, top + 12), label, font=pil_font(30, bold=True), fill=outline)

    # Lane 1
    lane1 = [
        ((120, 265, 465, 475), "输入冻结", "官方PDF + 设备配置\n+ 冷机PTFE任务"),
        ((520, 265, 865, 475), "文档解析", "PyMuPDF提取文字\n页码 + 区域坐标"),
        ((920, 265, 1265, 475), "OCR补充", "PaddleOCR读取\n扫描文字 + 图中标签"),
        ((1320, 265, 1665, 475), "AI结构化", "多模态大模型生成\n步骤 + 状态 + 查询词"),
        ((1720, 265, 2065, 475), "程序校验", "Schema检查字段\n状态衔接 + 来源"),
        ((2120, 265, 2465, 475), "人工审核", "真实性 + 可观察性\n安全性 + 现场权限"),
        ((2520, 265, 2880, 475), "冻结输出", "状态图 + 部件词典\n视角要求 + 手册出处"),
    ]
    for box, title, detail in lane1:
        draw_node(draw, box, title, detail, fill="#FFFFFF", outline="#2E74B5")
    for idx in range(len(lane1) - 1):
        arrow(draw, (lane1[idx][0][2] + 4, 370), (lane1[idx + 1][0][0] - 7, 370))

    # Lane 2 main flow
    lane2 = [
        ((120, 665, 480, 885), "手机观察", "iPhone全景 + 近景\n当前步骤 + 当前画面"),
        ((540, 665, 900, 885), "质量门", "方向校正 + 清晰度\n遮挡 + 出画检查"),
        ((960, 665, 1320, 885), "查询调度", "读取状态表中的\n移动部件 + 目标位置"),
        ((1380, 665, 1740, 885), "YOLOE定位", "文字提示 + 参考图\n输出部件框 + 置信度"),
        ((1800, 665, 2160, 885), "SAM2跟踪", "框生成精确mask\n跨帧传播 + 丢失重定位"),
    ]
    for box, title, detail in lane2:
        draw_node(draw, box, title, detail, fill="#FFFFFF", outline="#0E7490")
    for idx in range(len(lane2) - 1):
        arrow(draw, (lane2[idx][0][2] + 4, 775), (lane2[idx + 1][0][0] - 7, 775), color="#3B7B86")

    evidence_nodes = [
        ((2220, 610, 2880, 735), "几何证据", "距离 + 包含 + 接触 + 方向 + 连续性"),
        ((2220, 760, 2880, 885), "DINOv2证据", "局部图与已标注参考状态图相似度"),
        ((2220, 910, 2880, 1015), "多模态语义证据", "有限候选状态判断 + 证据说明"),
    ]
    for box, title, detail in evidence_nodes:
        draw_node(draw, box, title, detail, fill="#F9FFFF", outline="#0E7490")
    arrow(draw, (2164, 775), (2208, 672), color="#3B7B86")
    arrow(draw, (2164, 775), (2208, 822), color="#3B7B86")
    arrow(draw, (2164, 775), (2208, 960), color="#3B7B86")

    # Lane 3
    lane3 = [
        ((120, 1160, 520, 1350), "统一证据向量", "定位 + 几何 + 相似度\n语义判断 + 两帧一致性"),
        ((590, 1160, 990, 1350), "第一批数据前", "确定性规则\n明确阻断错误与不确定"),
        ((1060, 1160, 1460, 1350), "第一批数据后", "多分类逻辑回归\n推进概率逻辑回归"),
        ((1530, 1160, 1930, 1350), "安全硬门", "关键目标可见 + 无错误\n连续观察一致"),
        ((2000, 1160, 2400, 1350), "三向用户确认", "接受并推进\n纠正模型\n重新拍摄"),
        ((2470, 1160, 2880, 1350), "交互输出", "下一步文字 + 框 + 箭头\n像素高亮 + 纠错提示"),
    ]
    for box, title, detail in lane3:
        draw_node(draw, box, title, detail, fill="#FFFFFF", outline="#2F6B4F")
    arrow(draw, (524, 1255), (578, 1255), color="#4F7B5F")
    arrow(draw, (994, 1255), (1048, 1255), color="#4F7B5F")
    arrow(draw, (1464, 1255), (1518, 1255), color="#4F7B5F")
    arrow(draw, (1934, 1255), (1988, 1255), color="#4F7B5F")
    arrow(draw, (2404, 1255), (2458, 1255), color="#4F7B5F")

    # Lane 4
    lane4 = [
        ((120, 1530, 500, 1735), "试次清单", "预期状态 + 设备布置\n视角 + 重复次数"),
        ((565, 1530, 945, 1735), "独立真值", "按真实机器布置标注\n不使用模型解释"),
        ((1010, 1530, 1390, 1735), "批量运行", "固定模型版本 + 阈值\n保存全部中间证据"),
        ((1455, 1530, 1835, 1735), "ID对齐", "decision_id连接\n真值 + 预测 + 耗时"),
        ((1900, 1530, 2280, 1735), "自动指标", "状态F1 + 错误召回\n危险推进 + 跟踪漂移"),
        ((2345, 1530, 2880, 1735), "自动报告", "混淆矩阵 + 失败案例\n模块消融 + PASS和FAIL"),
    ]
    for box, title, detail in lane4:
        draw_node(draw, box, title, detail, fill="#FFFFFF", outline="#8A6400")
    for idx in range(len(lane4) - 1):
        arrow(draw, (lane4[idx][0][2] + 4, 1632), (lane4[idx + 1][0][0] - 7, 1632), color="#92762A")

    img.save(path, quality=95)


def add_title_block(doc: Document) -> None:
    p = doc.add_paragraph()
    p.paragraph_format.space_before = Pt(10)
    p.paragraph_format.space_after = Pt(4)
    r = p.add_run("技术同步简报")
    set_run_font(r, size=11, bold=True, color=TEAL)

    p = doc.add_paragraph()
    p.paragraph_format.space_after = Pt(5)
    r = p.add_run("Manual2AR 单设备闭环技术方案")
    set_run_font(r, size=24, bold=True, color=NAVY)

    p = doc.add_paragraph()
    p.paragraph_format.space_after = Pt(18)
    r = p.add_run("面向 Bambu Lab A1 mini Combo 的说明书结构化、状态识别与安全推进基线")
    set_run_font(r, size=13, color=GRAY)

    metadata = [
        ("用途", "供师兄核查技术合理性、项目侧重点与资源需求"),
        ("当前版本", "v0.1 讨论稿"),
        ("首轮设备", "Bambu Lab A1 mini Combo + AMS Lite"),
        ("首轮任务", "冷机 PTFE 管与外置料卷路径，需现场审核实际接线"),
    ]
    for label, value in metadata:
        p = doc.add_paragraph()
        p.paragraph_format.space_after = Pt(2)
        rl = p.add_run(label + "：")
        set_run_font(rl, bold=True, size=10.5, color=NAVY)
        rv = p.add_run(value)
        set_run_font(rv, size=10.5, color=INK)

    rule = doc.add_paragraph()
    p_pr = rule._p.get_or_add_pPr()
    p_bdr = OxmlElement("w:pBdr")
    bottom = OxmlElement("w:bottom")
    bottom.set(qn("w:val"), "single")
    bottom.set(qn("w:sz"), "18")
    bottom.set(qn("w:space"), "5")
    bottom.set(qn("w:color"), BLUE)
    p_bdr.append(bottom)
    p_pr.append(p_bdr)
    rule.paragraph_format.space_after = Pt(12)


def build_document() -> None:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    ASSET_DIR.mkdir(parents=True, exist_ok=True)
    build_diagram(DIAGRAM_PATH)

    doc = Document()
    configure_styles(doc)
    bullet_num, decimal_num = add_numbering_definition(doc)
    set_section_geometry(doc.sections[0])
    set_header_footer(doc.sections[0])
    add_title_block(doc)

    add_callout(
        doc,
        "本轮核心决策",
        "先针对一款真实设备和一个短任务完成可测闭环，再评估迁移。第一阶段以说明书自动结构化和状态错误识别为重点，AR作为交互呈现层；系统给出建议后由用户确认，不做完全自动推进。",
        fill=PALE_BLUE,
        accent=BLUE,
    )

    doc.add_heading("1. 项目目标与范围", level=1)
    add_para(
        doc,
        "Manual2AR 的首轮目标是建立“说明书状态 → 预期视觉证据 → 现场观察 → 状态核验 → 推进、纠错或拒答”的完整闭环。首轮不声称支持任意设备，也不把一次多模态大模型调用当作可靠状态识别。",
    )
    add_bullets(
        doc,
        [
            "设备范围：Bambu Lab A1 mini Combo，现场带 AMS Lite。",
            "任务范围：冷机 PTFE 管与外置料卷路径；正式执行前需根据 Combo 实际接线和实验室权限重审。",
            "研究与工程重点：说明书自动结构化，以及当前步骤、完成状态、错误状态和不确定状态识别。",
            "交互策略：系统建议 + 用户三向确认；用户可以接受、纠正或要求重新拍摄。",
            "阶段边界：先完成单设备基线与自动评测，再考虑视觉算法融合、模型微调和跨设备迁移。",
        ],
        bullet_num,
    )

    doc.add_heading("2. 方法论：把“模型是否正确”转化为可复现实验", level=1)
    add_para(
        doc,
        "方法论的核心是把程序真值、现场真值和模型预测分离。模型不得使用自己的解释给自己标注。每个试次在采集前就规定设备布置与预期标签，预测完成后再用 decision_id 将结果与独立真值对齐。",
    )
    add_numbered(
        doc,
        [
            "操作化：把“完成”改写为可观察部件、空间关系、时序一致性和不可见条件。",
            "控制采集：先用固定视角、稳定光照和简化背景建立可工作基线，再加入手持视角和杂乱背景。",
            "独立标注：依据真实机器布置标记 not_started、in_progress、completed、wrong_operation 和 uncertain。",
            "冻结测试：模型版本、提示词、状态表、阈值和测试集在最终评测前冻结。",
            "自动评价：计算状态 F1、错误召回、危险误推进、定位、跟踪和延迟，并输出失败案例。",
        ],
        decimal_num,
    )

    doc.add_heading("3. Predefine 的生成与审核责任", level=1)
    add_table(
        doc,
        ["责任主体", "主要工作", "不能做什么"],
        [
            ["多模态 AI", "从说明书生成候选原子步骤、前置条件、完成条件、错误条件、部件查询词、视角要求和来源。", "不能独自决定真实设备安全规则，不能将猜测写成事实。"],
            ["Schema 校验器", "检查字段完整性、状态衔接、唯一 ID、说明书出处和不可见条件路由。", "不能判断现场是否真的允许操作。"],
            ["设备与项目人员", "确认真实操作、可观察性、现场权限、安全条件和人工确认通道。", "不能用模型输出替代现场真值。"],
            ["冻结状态图", "作为运行时唯一任务边界，向查询调度器提供明确的 source、target 和状态谓词。", "运行时不得被大模型随意改写步骤顺序和安全条件。"],
        ],
        [1600, 4800, 2960],
        header_fill=BLUE_GRAY,
        font_size=9.2,
    )

    # Detailed architecture on a dedicated landscape page.
    landscape = doc.add_section(WD_SECTION.NEW_PAGE)
    set_section_geometry(landscape, landscape=True, margin=0.45)
    set_header_footer(landscape, "详细架构图")
    p = doc.add_paragraph()
    p.paragraph_format.space_after = Pt(4)
    r = p.add_run("4. 详细系统架构图")
    set_run_font(r, size=16, bold=True, color=BLUE)
    p = doc.add_paragraph()
    p.alignment = WD_ALIGN_PARAGRAPH.CENTER
    p.paragraph_format.space_after = Pt(3)
    architecture_picture = p.add_run().add_picture(str(DIAGRAM_PATH), width=Inches(9.9))
    architecture_picture._inline.docPr.set(
        "descr",
        "Manual2AR详细架构图，包含说明书离线编译、现场视觉感知、证据融合与安全交互、Codex自动评测四个阶段。",
    )
    architecture_picture._inline.docPr.set("title", "Manual2AR单设备闭环详细架构")
    cap = doc.add_paragraph(style="Caption")
    cap.alignment = WD_ALIGN_PARAGRAPH.CENTER
    r = cap.add_run("图 1　Manual2AR 单设备闭环：离线编译、运行时感知、证据融合、安全交互与自动评测")
    set_run_font(r, size=9.5, color=GRAY)

    portrait = doc.add_section(WD_SECTION.NEW_PAGE)
    set_section_geometry(portrait)
    set_header_footer(portrait)

    doc.add_heading("5. 分层技术架构", level=1)
    doc.add_heading("5.1 离线说明书编译", level=2)
    add_table(
        doc,
        ["步骤", "输入与基础处理", "选定工具", "结构化输出"],
        [
            ["PDF解析", "读取可复制文字、页码、文字区域和插图区域；同时渲染页面图片。", "PyMuPDF", "page_id、region、text、image"],
            ["OCR补充", "仅对扫描页面和图中标签识别文字，避免对已有文本重复 OCR。", "PaddleOCR", "文字、置信度和区域坐标"],
            ["步骤拆分", "结合文字、插图和任务范围，将复合指令拆成可验证原子步骤。", "多模态大模型", "候选步骤、前置与后置状态"],
            ["状态编译", "生成错误状态、不确定状态、部件查询词、所需视角、说明书来源。", "多模态大模型 + Schema", "候选状态图 JSON"],
            ["冻结审核", "人工确认真实性、可观察性、安全性和现场权限。", "审核清单", "版本化正式状态图"],
        ],
        [1100, 3850, 1900, 2510],
        header_fill=BLUE_GRAY,
        font_size=9.0,
    )

    doc.add_heading("5.2 运行时视觉感知", level=2)
    add_table(
        doc,
        ["模块", "责任边界", "输入", "输出与用途"],
        [
            ["状态控制器", "读取冻结状态，确定当前只需要验证哪些部件和条件。", "当前 step_id", "明确的 source、target、候选状态"],
            ["质量门", "先检查方向、清晰度、遮挡和关键区域是否出画。", "iPhone图像", "clear、occluded、blurred、out_of_frame"],
            ["查询调度器", "将状态表中的部件名称转换为明确查询；不是大模型直接画框。", "部件词典和当前状态", "YOLOE文字提示和参考图提示"],
            ["YOLOE", "计算部件在哪里，输出初始框和置信度。", "图像 + 查询", "source框、target框、置信度"],
            ["SAM2", "将初始框细化为像素 mask，并在视频中跟踪与丢失重定位。", "图像 + 初始框", "mask、polygon、quality、lost"],
            ["几何证据", "计算端点距离、进入比例、包含、接触、方向和路径连续性。", "框、mask、关键点", "可解释数值特征"],
            ["DINOv2", "比较当前局部图与人工确认的参考状态图。", "局部图 + 参考图", "参考状态相似度"],
            ["多模态判断", "只在当前步骤和有限候选状态中判断语义，不允许自由发明步骤。", "状态表 + 图像 + 视觉证据", "状态标签和证据说明"],
        ],
        [1300, 3310, 2200, 2550],
        header_fill="E7F3F3",
        font_size=8.75,
    )

    doc.add_heading("5.3 融合与安全推进", level=2)
    add_para(
        doc,
        "第一批数据前使用确定性规则建立可解释基线。有了独立标注数据后，再训练逻辑回归融合器。模型预测不直接控制推进，最终仍由硬安全门和用户确认控制。",
    )
    add_table(
        doc,
        ["阶段", "融合输入", "模型或规则", "推进条件"],
        [
            ["数据前基线", "目标可见性、几何关系、遮挡、语义判断和两帧一致性。", "确定性规则", "所有完成谓词满足，且没有错误或不确定证据。"],
            ["数据后融合", "YOLOE置信度、几何特征、SAM2稳定度、DINOv2相似度、MLLM状态和时序。", "多分类逻辑回归 + 二分类推进模型", "概率达到冻结阈值，硬条件全部满足。"],
            ["最终安全门", "融合结果、关键目标可见性、错误证据、连续观察和用户选择。", "不可学习硬规则", "completed候选 + 两帧一致 + 无错误 + 用户接受。"],
        ],
        [1500, 3300, 2400, 2160],
        header_fill="EAF3EC",
        font_size=9.0,
    )

    add_callout(
        doc,
        "用户确认不是形式按钮",
        "界面提供“判断正确并进入下一步”“判断错误，我还没有完成”“当前看不清，重新拍摄”三个分支。用户纠正会与模型预测一起保存，用作后续标注和失败分析。",
        fill=PALE_GREEN,
        accent=GREEN,
    )

    doc.add_heading("6. 自动评测与验收", level=1)
    add_para(
        doc,
        "计划将现有日志、人工真值和评测脚本包装为一条实验命令。Codex负责运行、检查模块失败、汇总结果和生成报告；运行时检测仍由后端模型服务完成。",
    )
    add_callout(
        doc,
        "拟议的一条命令",
        "python scripts/run_a1_study.py --manifest experiments/a1_ptfe_v1.yaml\n自动执行环境检查、批量预测、证据保存、真值对齐、逻辑回归训练、冻结测试、混淆矩阵和失败画廊。",
        fill=LIGHT_GRAY,
        accent=DARK_BLUE,
    )
    add_table(
        doc,
        ["指标", "回答的问题", "首轮使用方式"],
        [
            ["Step Recall@1", "当前进度是否定位到正确步骤？", "按独立试次标签计算。"],
            ["State macro-F1", "各状态是否均衡识别，而非只偏向多数类？", "覆盖 not_started、in_progress、completed、wrong_operation、uncertain。"],
            ["错误操作召回率", "真实错误中有多少被发现？", "作为高优先级安全指标。"],
            ["危险误推进率", "不应推进时是否错误推进？", "首轮目标为所有错误和不确定均被硬门阻断。"],
            ["定位与分割", "框和mask是否落在正确部件上？", "大部件看框重合；小接口看点是否进入人工区域。"],
            ["跟踪丢失率", "手机移动后高亮是否漂移或转移到干扰物？", "按session计算lost和重新定位。"],
            ["延迟", "现场交互是否可接受？", "报告中位延迟和P95延迟，不先伪设实时门槛。"],
        ],
        [1800, 4430, 3130],
        header_fill=BLUE_GRAY,
        font_size=9.0,
    )

    doc.add_heading("7. 首轮采集协议", level=1)
    add_para(
        doc,
        "先用固定视角和简化背景建立工程基线，再增加手持视角、遮挡和杂乱背景。每个试次提前规定设备布置和真实标签，避免采集后根据模型解释补标签。",
    )
    add_table(
        doc,
        ["试次类型", "真实布置示例", "预期标签", "目的"],
        [
            ["未开始", "PTFE管未接入目标接口。", "not_started", "验证基本状态区分。"],
            ["未完成", "PTFE管只搭在接口上，没有插入。", "not_started或in_progress，需状态表冻结", "验证细粒度关系。"],
            ["完成", "PTFE管正确插入，路径连续，关键位置清晰。", "completed", "验证完成识别。"],
            ["安全错误", "连接到允许模拟的错误位置，且不产生设备风险。", "wrong_operation", "验证错误召回与阻断。"],
            ["遮挡", "手遮住工具头接口。", "uncertain", "验证拒答。"],
            ["出画", "接口或管端离开画面。", "uncertain", "验证重拍提示。"],
        ],
        [1600, 3640, 1900, 2220],
        header_fill="FFF4DF",
        font_size=9.0,
    )

    doc.add_heading("8. 设备与计算资源要求", level=1)
    add_table(
        doc,
        ["资源", "当前条件", "首轮要求", "后续用途"],
        [
            ["真实设备", "项目可用 A1 mini Combo + AMS Lite。", "确认现有接线和实验室允许的冷机操作。", "未来少样本迁移和设备信号接入。"],
            ["移动端", "iPhone 15 Pro Max。", "1080p短视频、全景与接口近景、本地网络权限。", "ARKit注册与物理证据。"],
            ["开发机", "M2 MacBook Air。", "文档处理、Unity、API、数据采集、轻量MPS推理和自动评测。", "分析与工程维护。"],
            ["拍摄附件", "暂无三脚架、补光和固定背景。", "优先借用桌面手机支架、稳定补光和纯色背景。", "控制条件与手持条件对照。"],
            ["NVIDIA服务器", "待确认。", "优先申请至少24GB显存用于CUDA视觉基线；实际以模型和分辨率测试为准。", "多模态LoRA建议优先申请48GB以上显存，避免在M2上承担正式训练。"],
            ["存储", "待确认。", "至少100GB可用空间，保存视频、图片、mask、日志和版本记录。", "模型训练与可复现实验。"],
            ["网络", "需现场确认。", "iPhone与Mac在允许互访的同一局域网；云API按数据政策使用。", "可选云GPU和模型服务。"],
        ],
        [1600, 2800, 2900, 2060],
        header_fill=BLUE_GRAY,
        font_size=8.9,
    )

    doc.add_heading("9. API要求与服务边界", level=1)
    doc.add_heading("9.1 外部多模态大模型 API", level=2)
    add_bullets(
        doc,
        [
            "用途：说明书图文理解、原子步骤拆分、状态条件初稿、有限候选状态判断和失败分析。",
            "调用策略：先用少量样本验证输出结构和能力边界，再决定调用量；不在架构未冻结时大规模消费额度。",
            "需要师兄确认：API提供方、账号与Key、可用模型、额度、并发限制、费用报销方式和调用留痕。",
            "数据要求：确认官方说明书、设备照片和现场视频是否允许上传外部服务；受限数据改用本地模型。",
        ],
        bullet_num,
    )

    doc.add_heading("9.2 内部模型无关 API", level=2)
    add_table(
        doc,
        ["接口", "输入", "输出", "设计要求"],
        [
            ["说明书编译", "PDF、设备配置、任务范围", "带来源的状态图JSON", "AI输出必须通过Schema和人工审核。"],
            ["当前状态定位", "全景图、候选状态图", "当前步骤、可见事实、不确定原因", "不得从整个手册自由猜步骤。"],
            ["部件定位", "图像、明确部件查询、参考图", "框、置信度、provider", "YOLOE和后续对照模型可替换。"],
            ["分割跟踪", "首帧、初始框、后续帧", "mask、polygon、quality、lost", "一个session固定provider，丢失必须重定位。"],
            ["步骤核验", "当前步骤、图像、视觉证据", "状态、证据、safe_to_advance", "错误和不确定永不推进。"],
            ["人工确认", "decision_id、用户选择", "推进、纠正或重拍记录", "保留模型结果和人工纠正，不覆盖原预测。"],
            ["自动评测", "预测日志、独立真值、版本清单", "指标、混淆矩阵、失败画廊", "按session切分，避免相邻帧泄漏。"],
        ],
        [1650, 2500, 2500, 2710],
        header_fill="E7F3F3",
        font_size=8.8,
    )

    add_callout(
        doc,
        "暂不要求打印机控制 API",
        "首轮任务是冷机视觉识别，不依赖Bambu控制接口和MQTT。只有当后续需要验证内部送料、温度、打印状态等不可见条件时，才接入设备状态信号。",
        fill=PALE_GOLD,
        accent=GOLD,
    )

    doc.add_heading("10. 主要风险与应对", level=1)
    add_table(
        doc,
        ["风险", "可能表现", "首轮应对"],
        [
            ["AMS Lite配置不匹配", "现有状态图与真机管路不同。", "先拍摄与审核，不自行拆管；必要时更换首轮任务。"],
            ["细小接口难定位", "YOLOE只能找到工具头，找不到进料口。", "增加接口近景、参考图提示和人工标注区域；证据不足时拒答。"],
            ["单张图无法证明插入", "管端看似接触但并未真正插入。", "要求近景 + 全景两个观察节点，并使用前后帧与用户确认。"],
            ["手和背景干扰", "遮挡、同色物体和反光导致漂移。", "先固定背景与补光，再单独测杂乱背景；遮挡直接进入uncertain。"],
            ["小数据融合过拟合", "逻辑回归在训练集好、测试集差。", "按session分组切分，保留规则基线和独立冻结测试集。"],
            ["把AR显示当作识别成功", "框在屏幕上但没有真实世界注册。", "分别报告2D跟踪和ARKit物理注册，不混为一个指标。"],
            ["范围膨胀", "同时做多设备、训练和用户研究。", "先交付单任务工程闭环和可评测数据包。"],
        ],
        [1950, 3300, 4110],
        header_fill="F8EAEA",
        font_size=9.0,
    )

    doc.add_heading("11. 请师兄重点核查与协调", level=1)
    _, review_num = add_numbering_definition(doc)
    add_numbered(
        doc,
        [
            "先预定义单设备状态图，再逐步加入模型能力的方向是否合理？",
            "第一阶段把重点放在说明书自动结构化和状态错误识别，是否符合项目当前交付目标？",
            "主链路采用 YOLOE 定位、SAM2 跟踪、几何证据、DINOv2参考相似度和多模态判断，模块职责是否合理？",
            "有标注数据后使用逻辑回归融合，是否符合 high-level 和 low-level blend 的设想？",
            "A1 mini Combo带AMS Lite时，冷机 PTFE 管和外置料卷路径是否适合作为首轮任务？",
            "实验室是否有可用NVIDIA服务器？预计显存、使用周期和数据迁移方式如何？",
            "多模态API使用哪个账号、模型和额度？费用如何报销？现场图像是否允许上传？",
            "本阶段更优先交付稳定工程闭环，还是需要同步设计可形成研究贡献的对照实验？",
        ],
        review_num,
    )

    doc.add_heading("附录A　当前实现基础与参考资料", level=1)
    add_para(doc, "当前项目已有状态样本Schema、数据切分规则、人工真值格式和自动指标脚本，可在此基础上包装一条命令的实验流水线：")
    add_bullets(
        doc,
        [
            "schemas/manual_scene_sample.schema.json：训练样本与状态标签结构。",
            "data/README.md：原始数据、标注与session级切分规则。",
            "backend/data/ground_truth/README.md：独立人工真值格式。",
            "backend/scripts/summarize_baseline_events.py：状态、错误、安全和跟踪指标汇总。",
        ],
        bullet_num,
    )
    sources = [
        ("YOLOE 官方文档", "https://docs.ultralytics.com/models/yoloe"),
        ("SAM2 官方仓库", "https://github.com/facebookresearch/sam2"),
        ("DINOv2 官方仓库", "https://github.com/facebookresearch/dinov2"),
        ("PaddleOCR 官方仓库", "https://github.com/PaddlePaddle/PaddleOCR"),
        ("RAG-Anything 官方仓库", "https://github.com/HKUDS/RAG-Anything"),
        ("Guided Reality", "https://arxiv.org/abs/2508.03547"),
        ("JARVIS", "https://arxiv.org/abs/2604.10108"),
        ("Chain-of-Procedure", "https://arxiv.org/abs/2605.14928"),
        ("CheckManual", "https://arxiv.org/abs/2506.09343"),
        ("IndustReal", "https://arxiv.org/abs/2310.17323"),
    ]
    for label, url in sources:
        p = doc.add_paragraph()
        apply_num(p, bullet_num)
        p.paragraph_format.space_after = Pt(4)
        add_hyperlink(p, label, url)

    doc.core_properties.title = "Manual2AR 单设备闭环技术方案"
    doc.core_properties.subject = "供师兄技术核查与资源协调"
    doc.core_properties.author = "Manual2AR Project"
    doc.core_properties.keywords = "Manual2AR, A1 mini, YOLOE, SAM2, 状态识别, 说明书结构化"
    doc.save(DOCX_PATH)


if __name__ == "__main__":
    build_document()
    print(DOCX_PATH)
