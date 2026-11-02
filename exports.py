"""Business-readable exports. Everything is generated in memory from persisted results."""
import io
from html import escape

OVERVIEW = [("summary", "内容概览"), ("background", "业务背景"), ("goals", "业务目标"),
            ("users", "用户与角色"), ("scope", "范围与边界"), ("workflow", "业务流程"), ("metrics", "指标与衡量方式")]
FIELDS = [("id", "需求编号"), ("module", "模块"), ("title", "需求名称"),
          ("description", "详细描述"), ("roles", "使用角色"), ("scenario", "使用场景"),
          ("rules", "业务规则"), ("exceptions", "异常处理"), ("acceptance", "验收标准"),
          ("priority", "原文优先级"), ("sources", "来源位置"), ("evidence", "原文摘录")]


def value(v):
    return "、".join(v) if isinstance(v, list) else str(v or "未说明")


def sections(doc):
    report = doc["report"]
    yield "来源", f"文件：{doc['name']}\n项目：{doc['project']}\n模型：{doc['provider']} / {doc['model']}\n上传时间：{doc['created']}"
    for key, label in OVERVIEW:
        yield label, report.get(key, "未说明")
    for req in report["requirements"]:
        yield f"{req['id']}  {req['title']}", "\n".join(f"{label}：{value(req.get(key))}" for key, label in FIELDS if key not in ("id", "title"))


def word(doc):
    from docx import Document
    from docx.shared import Inches, Pt, RGBColor
    from docx.oxml.ns import qn
    report = Document()
    section = report.sections[0]
    section.top_margin = section.bottom_margin = Inches(.75)
    section.left_margin = section.right_margin = Inches(.85)
    normal = report.styles["Normal"]
    normal.font.name = "Microsoft YaHei"
    normal.font.size = Pt(10.5)
    normal.element.rPr.rFonts.set(qn("w:eastAsia"), "Microsoft YaHei")
    normal.paragraph_format.space_after = Pt(6)
    for style in ("Title", "Heading 1", "Heading 2"):
        report.styles[style].font.color.rgb = RGBColor.from_string("192F39")
        report.styles[style].font.name = "Microsoft YaHei"
        report.styles[style].element.rPr.rFonts.set(qn("w:eastAsia"), "Microsoft YaHei")
    report.add_paragraph(doc["report"]["title"], "Title")
    report.add_paragraph("需求提炼报告")
    for title, body in sections(doc):
        report.add_heading(title, level=1)
        for line in body.splitlines():
            report.add_paragraph(line)
    if doc["notes"]:
        report.add_heading("文件读取说明", level=1)
        for note in doc["notes"]:
            report.add_paragraph(note)
    buffer = io.BytesIO()
    report.save(buffer)
    return buffer.getvalue()


def pdf(doc):
    from reportlab.pdfbase import pdfmetrics
    from reportlab.pdfbase.cidfonts import UnicodeCIDFont
    from reportlab.lib import colors
    from reportlab.lib.styles import ParagraphStyle
    from reportlab.lib.enums import TA_LEFT
    from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer
    from reportlab.lib.pagesizes import A4
    pdfmetrics.registerFont(UnicodeCIDFont("STSong-Light"))
    body = ParagraphStyle("body", fontName="STSong-Light", fontSize=10.5, leading=17,
                          textColor=colors.HexColor("#192F39"), wordWrap="CJK", spaceAfter=8)
    heading = ParagraphStyle("heading", parent=body, fontSize=14, leading=21, spaceBefore=13, keepWithNext=True)
    title_style = ParagraphStyle("title", parent=body, fontSize=23, leading=30, spaceAfter=14)
    story = [Paragraph(escape(doc["report"]["title"]), title_style), Paragraph("需求提炼报告", body), Spacer(1, 8)]
    for title, text in sections(doc):
        story.append(Paragraph(escape(title), heading))
        for line in text.splitlines():
            story.append(Paragraph(escape(line), body))
    if doc["notes"]:
        story.append(Paragraph("文件读取说明", heading))
        story.extend(Paragraph(escape(n), body) for n in doc["notes"])
    buffer = io.BytesIO()
    def footer(canvas, document):
        canvas.setFont("STSong-Light", 9)
        canvas.drawRightString(A4[0] - 45, 26, str(document.page))
    SimpleDocTemplate(buffer, pagesize=A4, rightMargin=45, leftMargin=45,
                      topMargin=40, bottomMargin=42, title=doc["report"]["title"]).build(story, onFirstPage=footer, onLaterPages=footer)
    return buffer.getvalue()


def excel(doc):
    # This is application export code, rather than an authored spreadsheet artifact.
    from openpyxl import Workbook
    from openpyxl.styles import Alignment, Font, PatternFill
    from openpyxl.worksheet.table import Table, TableStyleInfo
    from openpyxl.utils import get_column_letter
    wb = Workbook()
    sheet = wb.active
    sheet.title = "需求清单"
    sheet.append([label for _, label in FIELDS])
    for req in doc["report"]["requirements"]:
        sheet.append([value(req.get(key)) for key, _ in FIELDS])
    sheet.freeze_panes = "D2"
    widths = [15, 20, 30, 65, 25, 35, 60, 45, 45, 18, 35, 65]
    for i, width in enumerate(widths, 1):
        sheet.column_dimensions[get_column_letter(i)].width = width
    for row in sheet:
        for cell in row:
            cell.alignment = Alignment(vertical="top", wrap_text=True)
            cell.font = Font(name="Microsoft YaHei", size=11)
            # Treat every model/document string as plain text, never an Excel formula.
            cell.data_type = "s"
    for cell in sheet[1]:
        cell.fill = PatternFill("solid", fgColor="16786A")
        cell.font = Font(name="Microsoft YaHei", bold=True, color="FFFFFF")
    sheet.row_dimensions[1].height = 28
    for i in range(2, sheet.max_row + 1):
        sheet.row_dimensions[i].height = 105
    if sheet.max_row > 1:
        table = Table(displayName="Requirements", ref=f"A1:L{sheet.max_row}")
        table.tableStyleInfo = TableStyleInfo(name="TableStyleMedium2", showRowStripes=True)
        sheet.add_table(table)
    overview = wb.create_sheet("文档概览")
    for title, text in [("来源文件", doc["name"]), ("项目", doc["project"]), *[(label, doc["report"].get(key, "未说明")) for key, label in OVERVIEW]]:
        overview.append([title, text])
    overview.column_dimensions["A"].width = 23
    overview.column_dimensions["B"].width = 110
    for row in overview:
        overview.row_dimensions[row[0].row].height = 85
        for c in row:
            c.data_type = "s"
            c.alignment = Alignment(vertical="top", wrap_text=True)
    buffer = io.BytesIO()
    wb.save(buffer)
    return buffer.getvalue()
