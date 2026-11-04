from workbench.config import setting
"""Structure-aware reading units; independent from model-sized processing chunks."""
import base64
import io
import os
import re
import zipfile
from pathlib import Path

PARSER_VERSION = 2


def heading_level(text, style_level=None):
    text = text.strip()
    if not text or len(text) > 85 or "\n" in text:
        return None
    if re.match(r"^[一二三四五六七八九十百]+[、．.](?!\d)\s*\S", text):
        return 1
    match = re.match(r"^(\d+(?:\.\d+)+)[.、．]?\s+\S", text)
    if match:
        return len(match[1].split("."))
    if re.match(r"^\d+[、．.)]\s*[^\d\s]", text):
        return 1
    # Word files often accidentally apply Heading styles to complete body sentences.
    if style_level and len(text) <= 32 and not re.search(r"[。；;！？!?]", text):
        return style_level
    return None


def image_block(raw, label):
    from PIL import Image, ImageOps
    try:
        with Image.open(io.BytesIO(raw)) as im:
            im = ImageOps.exif_transpose(im)
            if im.width * im.height > 60000000:
                raise ValueError("图片像素过大")
            im = im.convert("RGB")
            im.thumbnail((4096, 4096))
            out = io.BytesIO()
            im.save(out, format="PNG")
        return {"kind":"image", "text":"", "label":label, "mime":"image/png",
                "data":base64.b64encode(out.getvalue()).decode("ascii"), "recognized":False}
    except Exception:
        return {"kind":"image", "text":"", "label":label, "recognized":False,
                "error":"此图片格式暂无法转换，请将其替换为 PNG / JPEG 后重新上传。"}


def block_text(block):
    if block["kind"] == "table":
        return "\n".join(" | ".join(row) for row in block["rows"])
    return block.get("text", "")


def refresh_text(unit):
    unit["text"] = "\n\n".join(block_text(b) for b in unit["blocks"] if block_text(b).strip())
    return unit


def group_blocks(blocks):
    """Short major sections stay whole; >=3 numbered children split at depth 2.

    Small named subheadings remain inside their parent. Long sections (>8000 chars)
    may split at depth 2. Tables/images are indivisible display blocks.
    """
    majors, current = [], {"title":"文档说明", "blocks":[]}
    for block in blocks:
        if block.get("level") == 1:
            if current["blocks"]:
                majors.append(current)
            current = {"title":block["text"].strip(), "blocks":[block]}
        else:
            current["blocks"].append(block)
    if current["blocks"]:
        majors.append(current)
    units = []
    for major in majors:
        items = major["blocks"]
        children = [i for i, b in enumerate(items) if b.get("level") == 2]
        numbered = [i for i in children if re.match(r"^\d+\.\d+", items[i]["text"])]
        length = sum(len(block_text(b)) for b in items)
        split = len(numbered) >= 3 or (length > 8000 and len(children) >= 2)
        if not split:
            units.append(refresh_text({"source":major["title"], "blocks":items}))
            continue
        starts = children if children else numbered
        prefix = items[:starts[0]]
        # Keep meaningful introductory material without a separate heading-only entry.
        for n, start in enumerate(starts):
            end = starts[n+1] if n+1 < len(starts) else len(items)
            section_blocks = (prefix if n == 0 else []) + items[start:end]
            units.append(refresh_text({"source":f"{major['title']} / {items[start]['text'].strip()}", "blocks":section_blocks}))
    # Duplicate headings are disambiguated, not merged across separate parts of a document.
    counts = {}
    for unit in units:
        label = unit["source"]
        counts[label] = counts.get(label, 0) + 1
        if counts[label] > 1:
            unit["source"] += f"（第{counts[label]}处）"
    return units


def _word_blocks(raw, notes):
    from docx import Document
    from docx.table import Table
    from docx.text.paragraph import Paragraph
    from docx.oxml.ns import qn
    with zipfile.ZipFile(io.BytesIO(raw)) as archive:
        if sum(x.file_size for x in archive.infolist()) > 1024 * 1024 * 1024:
            raise ValueError("Word 解压后超过 1 GB 处理容量，请拆分。")
    doc = Document(io.BytesIO(raw))
    blocks, seen_images = [], set()

    def images(element):
        result = []
        for blip in element.iter(qn("a:blip")):
            rid = blip.get(qn("r:embed"))
            if not rid:
                notes.append("文档包含外链图片，未下载外链；请在 Word 中嵌入图片后重新上传。")
                continue
            # The same image can have separate placements; keep each placement in context.
            part = doc.part.related_parts.get(rid)
            if part:
                result.append(image_block(part.blob, f"图片{len(seen_images)+1}"))
                seen_images.add(rid)
        return result

    for child in doc.element.body:
        if child.tag.endswith("}p"):
            p = Paragraph(child, doc)
            text = p.text.strip()
            level = None
            if p.style:
                match = re.search(r"(?:Heading|标题)\s*(\d+)", p.style.name, re.I)
                if match:
                    level = int(match[1])
            if text:
                blocks.append({"kind":"paragraph", "text":text, "level":heading_level(text, level)})
            blocks.extend(images(child))
            if child.xpath(".//w:drawing") and not child.xpath(".//a:blip"):
                notes.append("文档含非图片绘图对象（如 SmartArt / 图表），建议转为 PDF 以识别完整视觉内容。")
        elif child.tag.endswith("}tbl"):
            table = Table(child, doc)
            blocks.append({"kind":"table", "rows":[[c.text for c in row.cells] for row in table.rows]})
            blocks.extend(images(child))
    return blocks


def _pdf_blocks(raw, notes):
    import pymupdf
    blocks = []
    with pymupdf.open(stream=raw, filetype="pdf") as doc:
        if doc.needs_pass and not doc.authenticate(""):
            raise ValueError("PDF 已加密，请先解除密码。")
        for number, page in enumerate(doc, 1):
            page_label = f"第{number}页"
            tables = page.find_tables().tables
            events, rectangles = [], [t.bbox for t in tables]
            for table in tables:
                rows = [[str(c or "") for c in row] for row in table.extract()]
                events.append((table.bbox[1], 0, {"kind":"table", "rows":rows, "page":page_label}))
            for box in page.get_text("dict")["blocks"]:
                if box.get("type") != 0:
                    continue
                for line in box["lines"]:
                    x0,y0,x1,y1 = line["bbox"]
                    if any(r[0] <= (x0+x1)/2 <= r[2] and r[1] <= (y0+y1)/2 <= r[3] for r in rectangles):
                        continue
                    text = "".join(s["text"] for s in line["spans"]).strip()
                    if text:
                        events.append((y0, x0, {"kind":"paragraph", "text":text, "level":heading_level(text), "page":page_label}))
            page_blocks = [b for _,_,b in sorted(events, key=lambda item:(item[0],item[1]))]
            blocks.extend(page_blocks)
            # Render page for scans, raster images, and vector diagrams. Table-only lines do not need a second OCR pass.
            drawings = page.get_drawings()
            non_table_drawings = any(not any(pymupdf.Rect(r).contains(d["rect"]) for r in rectangles) for d in drawings)
            if page.get_images() or non_table_drawings or not page_blocks:
                pix = page.get_pixmap(matrix=pymupdf.Matrix(1.75,1.75), alpha=False)
                block = image_block(pix.tobytes("png"), f"{page_label} 视觉内容")
                block["page"] = page_label
                blocks.append(block)
    return blocks


def parse_document(name, raw):
    suffix = Path(name).suffix.lower()
    max_mb = int(setting("MAX_FILE_MB", "200"))
    if max_mb > 0 and len(raw) > max_mb * 1024 * 1024:
        raise ValueError(f"文件超过当前 {max_mb} MB 大小上限。")
    if not raw:
        raise ValueError("文件为空。")
    notes = []
    if suffix == ".docx":
        blocks = _word_blocks(raw, notes)
    elif suffix == ".pdf":
        blocks = _pdf_blocks(raw, notes)
    elif suffix in (".txt", ".md"):
        blocks = [{"kind":"paragraph", "text":p, "level":heading_level(p)} for p in raw.decode("utf-8-sig").splitlines() if p.strip()]
    else:
        raise ValueError("支持 PDF、DOCX、TXT、Markdown；旧版 DOC 请先另存为 DOCX。")
    if not blocks:
        raise ValueError("未读取到正文、表格或图片，请确认文件内容。")
    if any(b["kind"] == "image" for b in blocks):
        notes.append("图片已保存；后台配置好支持视觉的模型后，可识别图片文字、表格和流程图，并纳入提炼。")
    units = group_blocks(blocks)
    # When PDF has no headings, pages are the conservative fallback, never paragraphs.
    if suffix == ".pdf" and not any(b.get("level") == 1 for b in blocks):
        pages = {}
        for block in blocks:
            pages.setdefault(block["page"], []).append(block)
        units = [refresh_text({"source":label, "blocks":items}) for label,items in pages.items()]
    max_chars = int(setting("MAX_DOCUMENT_CHARS", "600000"))
    if max_chars > 0 and sum(len(u["text"]) for u in units) > max_chars:
        raise ValueError("文档文字超过后台处理容量，请按章节拆分；未截断任何内容。")
    return units, list(dict.fromkeys(notes))


def pending_images(units):
    return [(u,b) for u in units for b in u.get("blocks", []) if b["kind"] == "image" and not b.get("recognized")]


def display_units(units):
    if all("blocks" in u for u in units):
        return units
    # Existing completed reports keep their source IDs; regroup only the reading view.
    blocks = []
    for unit in units:
        text = unit["text"]
        if " | " in text:
            blocks.append({"kind":"table", "rows":[row.split(" | ") for row in text.splitlines()]})
        else:
            blocks.append({"kind":"paragraph", "text":text, "level":heading_level(text)})
    return group_blocks(blocks)
