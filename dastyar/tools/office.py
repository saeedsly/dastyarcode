"""Real Office files with zero dependencies.

* ``create_word``      -> .docx  (Word 2007+ / WPS / LibreOffice)
* ``create_excel``     -> .xlsx  (real formulas, formatting, column widths)
* ``create_powerpoint``-> .pptx  (title slide + bullet slides + theme)
* ``create_pdf``       -> .pdf   (Persian-friendly text drawing)
* ``extract_text_from_office`` -> read text back from docx/xlsx/pptx

The OOXML files are ZIP packages built with tiny hand-written XML, which is far
lighter than python-docx/openpyxl and works on Python 3.7 without wheels.
"""
from __future__ import annotations

import datetime as _dt
import os
import re
import zipfile
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence
from xml.sax.saxutils import escape

from ..config import IS_WINDOWS
from ..utils import ensure_dir, expand, truncate, unique_path
from .base import ToolContext, ToolError, ToolResult, tool

XML_HEAD = '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>\n'


def _resolve(path: str, ctx: ToolContext, default_name: str) -> Path:
    p = expand(path) if path else Path.home() / "Desktop" / default_name
    if p.suffix == "":
        p = p.with_suffix(Path(default_name).suffix)
    p = p.expanduser()
    ensure_dir(p.parent)
    return unique_path(p)


def _col_letter(idx: int) -> str:
    """1 -> A, 27 -> AA"""
    out = ""
    while idx > 0:
        idx, rem = divmod(idx - 1, 26)
        out = chr(65 + rem) + out
    return out


# --------------------------------------------------------------------------- #
# DOCX
# --------------------------------------------------------------------------- #
def _docx_paragraph(text: str, style: Optional[str] = None, bold: bool = False,
                    size: Optional[int] = None, align: Optional[str] = None) -> str:
    def rtl(s: str) -> bool:
        return bool(re.search(r"[\u0600-\u06FF]", s))

    ppr = ""
    if style or align or rtl(text):
        ppr = "<w:pPr>"
        if style:
            ppr += '<w:pStyle w:val="%s"/>' % style
        if align or (rtl(text) and not align):
            ppr += '<w:jc w:val="%s"/>' % ("right" if rtl(text) and not align else align)
        if rtl(text):
            ppr += "<w:bidi/>"
        ppr += "</w:pPr>"
    rpr = "<w:rPr>"
    if bold:
        rpr += "<w:b/>"
    if size:
        rpr += '<w:sz w:val="%d"/><w:szCs w:val="%d"/>' % (size * 2, size * 2)
    if rtl(text):
        rpr += '<w:rtl/><w:lang w:bidi="fa-IR"/>'
    rpr += '<w:rFonts w:ascii="Calibri" w:hAnsi="Calibri" w:cs="B Nazanin"/>'
    rpr += "</w:rPr>"
    return '<w:p>%s<w:r>%s<w:t xml:space="preserve">%s</w:t></w:r></w:p>' % (
        ppr, rpr, escape(text or ""))


def _docx_table(headers: Sequence[str], rows: Sequence[Sequence[Any]]) -> str:
    cols = len(headers)
    width = int(9000 / max(1, cols))

    def cell(text: Any, bold: bool = False) -> str:
        return (
            '<w:tc><w:tcPr><w:tcW w:w="%d" w:type="dxa"/></w:tcPr>'
            "%s</w:tc>" % (width, _docx_paragraph(str(text), bold=bold, size=10))
        )

    out = [
        '<w:tbl><w:tblPr><w:tblStyle w:val="TableGrid"/><w:tblW w:w="0" w:type="auto"/>'
        '<w:tblBorders><w:top w:val="single" w:sz="4"/><w:left w:val="single" w:sz="4"/>'
        '<w:bottom w:val="single" w:sz="4"/><w:right w:val="single" w:sz="4"/>'
        '<w:insideH w:val="single" w:sz="4"/><w:insideV w:val="single" w:sz="4"/>'
        "</w:tblBorders></w:tblPr><w:tr>" + "".join(cell(h, True) for h in headers) + "</w:tr>"
    ]
    for row in rows:
        cells = [cell("") for _ in range(cols)]
        for i, val in enumerate(list(row)[:cols]):
            cells[i] = cell(val)
        out.append("<w:tr>" + "".join(cells) + "</w:tr>")
    out.append("</w:tbl><w:p/>")
    return "".join(out)


DOCTYPE = (
    '<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main" '
    'xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships">'
)


def build_docx(body_xml: str, title: str = "") -> bytes:
    import io

    styles = (
        XML_HEAD
        + '<w:styles xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">'
        '<w:docDefaults><w:rPrDefault><w:rPr>'
        '<w:rFonts w:ascii="Calibri" w:hAnsi="Calibri" w:cs="B Nazanin"/>'
        '<w:sz w:val="24"/><w:szCs w:val="24"/><w:lang w:bidi="fa-IR"/>'
        "</w:rPr></w:rPrDefault></w:docDefaults>"
        '<w:style w:type="paragraph" w:styleId="Title"><w:name w:val="Title"/>'
        '<w:pPr><w:jc w:val="center"/></w:pPr><w:rPr><w:b/><w:sz w:val="56"/></w:rPr></w:style>'
        '<w:style w:type="paragraph" w:styleId="Heading1"><w:name w:val="heading 1"/>'
        '<w:pPr><w:outlineLvl w:val="0"/></w:pPr><w:rPr><w:b/><w:sz w:val="36"/></w:rPr></w:style>'
        '<w:style w:type="paragraph" w:styleId="Heading2"><w:name w:val="heading 2"/>'
        '<w:pPr><w:outlineLvl w:val="1"/></w:pPr><w:rPr><w:b/><w:sz w:val="30"/></w:rPr></w:style>'
        '<w:style w:type="table" w:styleId="TableGrid"><w:name w:val="Table Grid"/></w:style>'
        "</w:styles>"
    )
    content_types = (
        XML_HEAD
        + '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">'
        '<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>'
        '<Default Extension="xml" ContentType="application/xml"/>'
        '<Override PartName="/word/document.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.document.main+xml"/>'
        '<Override PartName="/word/styles.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.styles+xml"/>'
        '<Override PartName="/docProps/core.xml" ContentType="application/vnd.openxmlformats-package.core-properties+xml"/>'
        '<Override PartName="/docProps/app.xml" ContentType="application/vnd.openxmlformats-officedocument.extended-properties+xml"/>'
        "</Types>"
    )
    rels = (
        XML_HEAD
        + '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
        '<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="word/document.xml"/>'
        '<Relationship Id="rId2" Type="http://schemas.openxmlformats.org/package/2006/relationships/metadata/core-properties" Target="docProps/core.xml"/>'
        '<Relationship Id="rId3" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/extended-properties" Target="docProps/app.xml"/>'
        "</Relationships>"
    )
    doc_rels = (
        XML_HEAD
        + '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
        '<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/styles" Target="styles.xml"/>'
        "</Relationships>"
    )
    now = _dt.datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%SZ")
    core = (
        XML_HEAD
        + '<cp:coreProperties xmlns:cp="http://schemas.openxmlformats.org/package/2006/metadata/core-properties" '
        'xmlns:dc="http://purl.org/dc/elements/1.1/" xmlns:dcterms="http://purl.org/dc/terms/" '
        'xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance">'
        "<dc:title>%s</dc:title><dc:creator>Dastyar</dc:creator><cp:lastModifiedBy>Dastyar</cp:lastModifiedBy>"
        '<dcterms:created xsi:type="dcterms:W3CDTF">%s</dcterms:created>'
        '<dcterms:modified xsi:type="dcterms:W3CDTF">%s</dcterms:modified>'
        "</cp:coreProperties>" % (escape(title or "سند"), now, now)
    )
    app = (
        XML_HEAD
        + '<Properties xmlns="http://schemas.openxmlformats.org/officeDocument/2006/extended-properties">'
        "<Application>Dastyar</Application></Properties>"
    )
    document = XML_HEAD + DOCTYPE + "<w:body>" + body_xml + (
        '<w:sectPr><w:pgSz w:w="11906" w:h="16838"/>'
        '<w:pgMar w:top="1134" w:right="1134" w:bottom="1134" w:left="1134" w:header="709" w:footer="709" w:gutter="0"/>'
        "</w:sectPr></w:body></w:document>"
    )
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr("[Content_Types].xml", content_types)
        z.writestr("_rels/.rels", rels)
        z.writestr("docProps/core.xml", core)
        z.writestr("docProps/app.xml", app)
        z.writestr("word/document.xml", document)
        z.writestr("word/styles.xml", styles)
        z.writestr("word/_rels/document.xml.rels", doc_rels)
    return buf.getvalue()


@tool(
    "create_word",
    "یک فایل Word واقعی (.docx) با عنوان، متن و جدول می‌سازد. مناسب نامه، گزارش، رزومه، قرارداد.",
    category="آفیس",
    dangerous=True,
    confirm="ساخت فایل Word روی دیسک",
    params={
        "path": {"type": "string", "description": "مسیر فایل؛ پیش‌فرض Desktop"},
        "title": {"type": "string"},
        "content": {"type": "string", "description": "متن سند؛ هر خط یک پاراگراف. خطی که با # شروع شود تیتر می‌شود."},
        "table": {
            "type": "array",
            "description": "اختیاری: لیستی از ردیف‌ها؛ ردیف اول سرستون است.",
            "items": {"type": "array", "items": {"type": "string"}},
        },
    },
    required=["content"],
)
def create_word(path: str = "", title: str = "", content: str = "",
                table: Optional[List[List[str]]] = None,
                ctx: Optional[ToolContext] = None) -> ToolResult:
    assert ctx is not None
    target = _resolve(path, ctx, "سند-دستیار.docx")
    body = []
    if title:
        body.append(_docx_paragraph(title, style="Title", bold=True, size=26))
    for line in (content or "").splitlines():
        line = line.rstrip()
        if not line:
            body.append("<w:p/>")
        elif line.startswith("## "):
            body.append(_docx_paragraph(line[3:], style="Heading2", bold=True, size=14))
        elif line.startswith("# "):
            body.append(_docx_paragraph(line[2:], style="Heading1", bold=True, size=17))
        elif line.startswith("- ") or line.startswith("* "):
            body.append(_docx_paragraph("• " + line[2:]))
        else:
            body.append(_docx_paragraph(line))
    if table:
        rows = [r for r in table if r]
        if len(rows) >= 1:
            headers = rows[0]
            body.append(_docx_table(headers, rows[1:]))
    target.write_bytes(build_docx("".join(body), title))
    ctx.attach("file", str(target))
    return ToolResult("📄 فایل Word ساخته شد: %s" % target,
                      attach={"kind": "file", "path": str(target)})


# --------------------------------------------------------------------------- #
# XLSX
# --------------------------------------------------------------------------- #
def _cell_xml(ref: str, value: Any, style: int = 0) -> str:
    s = ' s="%d"' % style if style else ""
    if value is None or value == "":
        return '<c r="%s"%s/>' % (ref, s)
    if isinstance(value, bool):
        return '<c r="%s"%s t="b"><v>%d</v></c>' % (ref, s, 1 if value else 0)
    if isinstance(value, (int, float)):
        return '<c r="%s"%s><v>%s</v></c>' % (ref, s, repr(value))
    text = str(value)
    if text.startswith("=") and len(text) > 1:  # formula
        return '<c r="%s"%s><f>%s</f></c>' % (ref, s, escape(text[1:]))
    return '<c r="%s"%s t="inlineStr"><is><t xml:space="preserve">%s</t></is></c>' % (
        ref, s, escape(text))


def build_xlsx(sheets: List[Dict[str, Any]]) -> bytes:
    """sheets = [{"name": "Sheet1", "rows": [[...], ...], "widths": [20, ...]}]"""
    import io

    def sheet_xml(sheet: Dict[str, Any]) -> str:
        rows = sheet.get("rows") or []
        widths = sheet.get("widths") or []
        cols = ""
        if widths:
            cols = "<cols>" + "".join(
                '<col min="%d" max="%d" width="%s" customWidth="1"/>' % (i + 1, i + 1, w)
                for i, w in enumerate(widths)
            ) + "</cols>"
        body = []
        for r_idx, row in enumerate(rows, start=1):
            cells = []
            for c_idx, value in enumerate(row, start=1):
                style = 1 if r_idx == 1 else 0  # header bold
                cells.append(_cell_xml("%s%d" % (_col_letter(c_idx), r_idx), value, style))
            body.append('<row r="%d">%s</row>' % (r_idx, "".join(cells)))
        freeze = (
            '<sheetViews><sheetView workbookViewId="0" tabSelected="1">'
            '<pane ySplit="1" topLeftCell="A2" activePane="bottomLeft" state="frozen"/>'
            "</sheetView></sheetViews>"
        )
        return (
            XML_HEAD
            + '<worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">'
            + freeze + cols + "<sheetData>" + "".join(body) + "</sheetData></worksheet>"
        )

    content_types = [XML_HEAD + '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">'
        '<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>'
        '<Default Extension="xml" ContentType="application/xml"/>'
        '<Override PartName="/xl/workbook.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet.main+xml"/>'
        '<Override PartName="/xl/styles.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.styles+xml"/>'
        '<Override PartName="/docProps/core.xml" ContentType="application/vnd.openxmlformats-package.core-properties+xml"/>']
    workbook_sheets = []
    for i in range(len(sheets)):
        content_types.append(
            '<Override PartName="/xl/worksheets/sheet%d.xml" '
            'ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.worksheet+xml"/>' % (i + 1))
        workbook_sheets.append(
            '<sheet name="%s" sheetId="%d" r:id="rId%d"/>'
            % (escape(str(sheets[i].get("name") or ("Sheet%d" % (i + 1)))[:31]), i + 1, i + 1))
    content_types.append("</Types>")

    workbook = (
        XML_HEAD
        + '<workbook xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main" '
        'xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships">'
        "<sheets>" + "".join(workbook_sheets) + "</sheets></workbook>"
    )
    wb_rels = (
        XML_HEAD
        + '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
        + "".join(
            '<Relationship Id="rId%d" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/worksheet" Target="worksheets/sheet%d.xml"/>'
            % (i + 1, i + 1) for i in range(len(sheets))
        )
        + '<Relationship Id="rId%d" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/styles" Target="styles.xml"/>'
        % (len(sheets) + 1)
        + "</Relationships>"
    )
    styles = (
        XML_HEAD
        + '<styleSheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">'
        '<fonts count="2"><font><sz val="11"/><name val="Calibri"/></font>'
        '<font><b/><sz val="11"/><name val="Calibri"/></font></fonts>'
        '<fills count="2"><fill><patternFill patternType="none"/></fill>'
        '<fill><patternFill patternType="gray125"/></fill></fills>'
        '<borders count="1"><border><left/><right/><top/><bottom/><diagonal/></border></borders>'
        '<cellStyleXfs count="1"><xf numFmtId="0" fontId="0" fillId="0" borderId="0"/></cellStyleXfs>'
        '<cellXfs count="2"><xf numFmtId="0" fontId="0" fillId="0" borderId="0" xfId="0"/>'
        '<xf numFmtId="0" fontId="1" fillId="0" borderId="0" xfId="0" applyFont="1"/></cellXfs>'
        "</styleSheet>"
    )
    root_rels = (
        XML_HEAD
        + '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
        '<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="xl/workbook.xml"/>'
        '<Relationship Id="rId2" Type="http://schemas.openxmlformats.org/package/2006/relationships/metadata/core-properties" Target="docProps/core.xml"/>'
        "</Relationships>"
    )
    now = _dt.datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%SZ")
    core = (
        XML_HEAD
        + '<cp:coreProperties xmlns:cp="http://schemas.openxmlformats.org/package/2006/metadata/core-properties" '
        'xmlns:dc="http://purl.org/dc/elements/1.1/" xmlns:dcterms="http://purl.org/dc/terms/" '
        'xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance"><dc:creator>Dastyar</dc:creator>'
        '<dcterms:created xsi:type="dcterms:W3CDTF">%s</dcterms:created></cp:coreProperties>' % now
    )
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr("[Content_Types].xml", "".join(content_types))
        z.writestr("_rels/.rels", root_rels)
        z.writestr("docProps/core.xml", core)
        z.writestr("xl/workbook.xml", workbook)
        z.writestr("xl/_rels/workbook.xml.rels", wb_rels)
        z.writestr("xl/styles.xml", styles)
        for i, sheet in enumerate(sheets):
            z.writestr("xl/worksheets/sheet%d.xml" % (i + 1), sheet_xml(sheet))
    return buf.getvalue()


@tool(
    "create_excel",
    "یک فایل اکسل واقعی (.xlsx) با سرستون و داده می‌سازد. فرمول هم پشتیبانی می‌شود (مثل =SUM(B2:B10)).",
    category="آفیس",
    dangerous=True,
    confirm="ساخت فایل اکسل روی دیسک",
    params={
        "path": {"type": "string"},
        "rows": {
            "type": "array",
            "description": "ردیف‌ها؛ ردیف اول سرستون. سلول‌ها عدد، متن یا فرمول.",
            "items": {"type": "array", "items": {}},
        },
        "sheet_name": {"type": "string"},
        "col_widths": {"type": "array", "items": {"type": "number"}},
    },
    required=["rows"],
)
def create_excel(rows: List[List[Any]], path: str = "", sheet_name: str = "Sheet1",
                 col_widths: Optional[List[float]] = None,
                 ctx: Optional[ToolContext] = None) -> ToolResult:
    assert ctx is not None
    if not rows:
        raise ToolError("ردیف‌ها خالی است.")
    target = _resolve(path, ctx, "گزارش-دستیار.xlsx")
    widths = col_widths or []
    if not widths:
        cols = max(len(r) for r in rows)
        widths = []
        for c in range(cols):
            longest = max([len(str(r[c])) for r in rows if c < len(r)] or [8])
            widths.append(min(45, max(10, longest + 4)))
    target.write_bytes(build_xlsx([{"name": sheet_name, "rows": rows, "widths": widths}]))
    ctx.attach("file", str(target))
    return ToolResult(
        "📊 فایل اکسل ساخته شد: %s (%d ردیف)" % (target, len(rows)),
        attach={"kind": "file", "path": str(target)},
    )


@tool(
    "create_excel_report",
    "گزارش اکسل چندشیتی از داده‌های JSON می‌سازد (خلاصه + جزئیات + نمودار داده).",
    category="آفیس",
    dangerous=True,
    confirm="ساخت فایل اکسل روی دیسک",
    params={
        "path": {"type": "string"},
        "data": {"type": "array", "items": {"type": "array", "items": {}},
                 "description": "داده‌های اصلی؛ ردیف اول سرستون"},
        "title": {"type": "string"},
    },
    required=["data"],
)
def create_excel_report(data: List[List[Any]], path: str = "", title: str = "گزارش",
                        ctx: Optional[ToolContext] = None) -> ToolResult:
    assert ctx is not None
    target = _resolve(path, ctx, "گزارش-دستیار.xlsx")
    header = data[0] if data else []
    numeric_cols = []
    for c in range(len(header)):
        vals = [r[c] for r in data[1:] if c < len(r) and isinstance(r[c], (int, float))]
        if len(vals) == len(data) - 1 and vals:
            numeric_cols.append(c)

    summary_rows: List[List[Any]] = [["شاخص", "مقدار"]]
    summary_rows.append(["تعداد ردیف‌ها", len(data) - 1])
    summary_rows.append(["تاریخ ساخت گزارش", _dt.datetime.now().strftime("%Y-%m-%d %H:%M")])
    for c in numeric_cols:
        name = header[c] if c < len(header) else "ستون %d" % (c + 1)
        summary_rows.append(["جمع " + str(name), "=SUM('داده'!%s2:%s%d)" % (
            _col_letter(c + 1), _col_letter(c + 1), len(data))])
    sheets = [
        {"name": "خلاصه", "rows": summary_rows, "widths": [28, 22]},
        {"name": "داده", "rows": data},
    ]
    target.write_bytes(build_xlsx(sheets))
    ctx.attach("file", str(target))
    return ToolResult(
        "📊 گزارش اکسل ساخته شد: %s (%d شیت)" % (target, len(sheets)),
        attach={"kind": "file", "path": str(target)},
    )


# --------------------------------------------------------------------------- #
# PPTX
# --------------------------------------------------------------------------- #
def build_pptx(slides: List[Dict[str, Any]], title: str = "") -> bytes:
    """slides = [{"title": str, "body": [str, ...], "notes": str}]"""
    import io

    theme = (
        XML_HEAD
        + '<a:theme xmlns:a="http://schemas.openxmlformats.org/drawingml/2006/main" name="Dastyar">'
        '<a:themeElements><a:clrScheme name="Dastyar">'
        '<a:dk1><a:srgbClr val="1F2937"/></a:dk1><a:lt1><a:srgbClr val="FFFFFF"/></a:lt1>'
        '<a:dk2><a:srgbClr val="111827"/></a:dk2><a:lt2><a:srgbClr val="F3F4F6"/></a:lt2>'
        '<a:accent1><a:srgbClr val="2563EB"/></a:accent1><a:accent2><a:srgbClr val="9333EA"/></a:accent2>'
        '<a:accent3><a:srgbClr val="10B981"/></a:accent3><a:accent4><a:srgbClr val="F59E0B"/></a:accent4>'
        '<a:accent5><a:srgbClr val="EF4444"/></a:accent5><a:accent6><a:srgbClr val="06B6D4"/></a:accent6>'
        "<a:hlink><a:srgbClr val=\"2563EB\"/></a:hlink><a:folHlink><a:srgbClr val=\"7C3AED\"/></a:folHlink>"
        "</a:clrScheme>"
        '<a:fontScheme name="Dastyar"><a:majorFont><a:latin typeface="Calibri Light"/>'
        '<a:ea typeface=""/><a:cs typeface="Tahoma"/></a:majorFont>'
        '<a:minorFont><a:latin typeface="Calibri"/><a:ea typeface=""/><a:cs typeface="Tahoma"/>'
        "</a:minorFont></a:fontScheme>"
        '<a:fmtScheme name="Dastyar"><a:fillStyleLst><a:solidFill><a:schemeClr val="phClr"/></a:solidFill>'
        "</a:fillStyleLst><a:lnStyleLst><a:ln><a:solidFill><a:schemeClr val=\"phClr\"/></a:solidFill></a:ln></a:lnStyleLst>"
        '<a:effectStyleLst><a:effectStyle><a:effectLst/></a:effectStyle></a:effectStyleLst>'
        '<a:bgFillStyleLst><a:solidFill><a:schemeClr val="phClr"/></a:solidFill></a:bgFillStyleLst>'
        "</a:fmtScheme></a:themeElements></a:theme>"
    )

    def para(text: str, size: int = 2400, bold: bool = False, color: str = "1F2937",
             bullet: bool = False, align: str = "r") -> str:
        rtl = bool(re.search(r"[\u0600-\u06FF]", text or ""))
        ppr = '<a:pPr algn="%s"%s>%s</a:pPr>' % (
            align if not rtl else "r",
            ' rtl="1"' if rtl else "",
            '<a:buChar char="•"/>' if bullet else "<a:buNone/>",
        )
        return (
            "<a:p>%s<a:r><a:rPr lang=\"fa-IR\" sz=\"%d\"%s dirty=\"0\">"
            '<a:solidFill><a:srgbClr val="%s"/></a:solidFill><a:latin typeface="Calibri"/>'
            '<a:cs typeface="Tahoma"/></a:rPr><a:t>%s</a:t></a:r></a:p>'
            % (ppr, size, ' b="1"' if bold else "", color, escape(text or ""))
        )

    ns = (
        '<p:sld xmlns:a="http://schemas.openxmlformats.org/drawingml/2006/main" '
        'xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships" '
        'xmlns:p="http://schemas.openxmlformats.org/presentationml/2006/main">'
    )

    def slide_xml(index: int, s: Dict[str, Any], first: bool) -> str:
        bg = "FFFFFF" if not first else "2563EB"
        title_color = "FFFFFF" if first else "1F2937"
        body_color = "E5E7EB" if first else "374151"
        body_items = [str(b) for b in (s.get("body") or [])]
        title_txt = str(s.get("title") or "")
        body_paras = "".join(para(b, 1800, False, body_color, bullet=True) for b in body_items[:8]) or para("", 1800)
        return (
            ns
            + "<p:cSld>"
            '<p:bg><p:bgPr><a:solidFill><a:srgbClr val="%s"/></a:solidFill><a:effectLst/></p:bgPr></p:bg>' % bg
            + "<p:spTree>"
            '<p:nvGrpSpPr><p:cNvPr id="1" name=""/><p:cNvGrpSpPr/><p:nvPr/></p:nvGrpSpPr>'
            '<p:grpSpPr><a:xfrm><a:off x="0" y="0"/><a:ext cx="0" cy="0"/>'
            '<a:chOff x="0" y="0"/><a:chExt cx="0" cy="0"/></a:xfrm></p:grpSpPr>'
            # title
            '<p:sp><p:nvSpPr><p:cNvPr id="2" name="Title"/><p:cNvSpPr><a:spLocks noGrp="1"/></p:cNvSpPr>'
            "<p:nvPr/></p:nvSpPr><p:spPr><a:xfrm>"
            '<a:off x="609600" y="457200"/><a:ext cx="10972800" cy="1143000"/></a:xfrm>'
            '<a:prstGeom prst="rect"><a:avLst/></a:prstGeom></p:spPr>'
            "<p:txBody><a:bodyPr anchor=\"ctr\"/><a:lstStyle/>%s</p:txBody></p:sp>"
            % para(title_txt, 3600 if first else 3000, True, title_color, align="ctr" if first else "r")
            # body
            + '<p:sp><p:nvSpPr><p:cNvPr id="3" name="Body"/><p:cNvSpPr><a:spLocks noGrp="1"/></p:cNvSpPr>'
            "<p:nvPr/></p:nvSpPr><p:spPr><a:xfrm>"
            '<a:off x="914400" y="1828800"/><a:ext cx="10058400" cy="3886200"/></a:xfrm>'
            '<a:prstGeom prst="rect"><a:avLst/></a:prstGeom></p:spPr>'
            "<p:txBody><a:bodyPr><a:normAutofit/></a:bodyPr><a:lstStyle/>%s</p:txBody></p:sp>"
            % body_paras
            + "</p:spTree></p:cSld>"
            '<p:clrMapOvr><a:masterClrMapping/></p:clrMapOvr></p:sld>'
        )

    n = len(slides)
    content_types = (
        XML_HEAD + '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">'
        '<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>'
        '<Default Extension="xml" ContentType="application/xml"/>'
        '<Override PartName="/ppt/presentation.xml" ContentType="application/vnd.openxmlformats-officedocument.presentationml.presentation.main+xml"/>'
        '<Override PartName="/ppt/slideMasters/slideMaster1.xml" ContentType="application/vnd.openxmlformats-officedocument.presentationml.slideMaster+xml"/>'
        '<Override PartName="/ppt/slideLayouts/slideLayout1.xml" ContentType="application/vnd.openxmlformats-officedocument.presentationml.slideLayout+xml"/>'
        '<Override PartName="/ppt/theme/theme1.xml" ContentType="application/vnd.openxmlformats-officedocument.theme+xml"/>'
        '<Override PartName="/docProps/core.xml" ContentType="application/vnd.openxmlformats-package.core-properties+xml"/>'
        + "".join(
            '<Override PartName="/ppt/slides/slide%d.xml" ContentType="application/vnd.openxmlformats-officedocument.presentationml.slide+xml"/>'
            % (i + 1) for i in range(n)
        )
        + "</Types>"
    )
    root_rels = (
        XML_HEAD
        + '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
        '<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="ppt/presentation.xml"/>'
        '<Relationship Id="rId2" Type="http://schemas.openxmlformats.org/package/2006/relationships/metadata/core-properties" Target="docProps/core.xml"/>'
        "</Relationships>"
    )
    presentation = (
        XML_HEAD
        + '<p:presentation xmlns:a="http://schemas.openxmlformats.org/drawingml/2006/main" '
        'xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships" '
        'xmlns:p="http://schemas.openxmlformats.org/presentationml/2006/main">'
        '<p:sldMasterIdLst><p:sldMasterId id="2147483648" r:id="rId1"/></p:sldMasterIdLst>'
        "<p:sldIdLst>"
        + "".join('<p:sldId id="%d" r:id="rId%d"/>' % (256 + i, i + 2) for i in range(n))
        + "</p:sldIdLst>"
        '<p:sldSz cx="12192000" cy="6858000" type="screen16x9"/>'
        '<p:notesSz cx="6858000" cy="9144000"/></p:presentation>'
    )
    pres_rels = (
        XML_HEAD
        + '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
        '<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/slideMaster" Target="slideMasters/slideMaster1.xml"/>'
        + "".join(
            '<Relationship Id="rId%d" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/slide" Target="slides/slide%d.xml"/>'
            % (i + 2, i + 1) for i in range(n)
        )
        + '<Relationship Id="rId%d" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/theme" Target="theme/theme1.xml"/>'
        % (n + 2)
        + "</Relationships>"
    )
    master = (
        XML_HEAD
        + '<p:sldMaster xmlns:a="http://schemas.openxmlformats.org/drawingml/2006/main" '
        'xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships" '
        'xmlns:p="http://schemas.openxmlformats.org/presentationml/2006/main">'
        "<p:cSld><p:spTree>"
        '<p:nvGrpSpPr><p:cNvPr id="1" name=""/><p:cNvGrpSpPr/><p:nvPr/></p:nvGrpSpPr>'
        '<p:grpSpPr><a:xfrm><a:off x="0" y="0"/><a:ext cx="0" cy="0"/>'
        '<a:chOff x="0" y="0"/><a:chExt cx="0" cy="0"/></a:xfrm></p:grpSpPr>'
        "</p:spTree></p:cSld>"
        '<p:clrMap bg1="lt1" tx1="dk1" bg2="lt2" tx2="dk2" accent1="accent1" accent2="accent2" '
        'accent3="accent3" accent4="accent4" accent5="accent5" accent6="accent6" hlink="hlink" folHlink="folHlink"/>'
        '<p:sldLayoutIdLst><p:sldLayoutId id="2147483649" r:id="rId1"/></p:sldLayoutIdLst>'
        "</p:sldMaster>"
    )
    master_rels = (
        XML_HEAD
        + '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
        '<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/slideLayout" Target="../slideLayouts/slideLayout1.xml"/>'
        '<Relationship Id="rId2" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/theme" Target="../theme/theme1.xml"/>'
        "</Relationships>"
    )
    layout = (
        XML_HEAD
        + '<p:sldLayout xmlns:a="http://schemas.openxmlformats.org/drawingml/2006/main" '
        'xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships" '
        'xmlns:p="http://schemas.openxmlformats.org/presentationml/2006/main" type="blank" preserve="1">'
        "<p:cSld name=\"Blank\"><p:spTree>"
        '<p:nvGrpSpPr><p:cNvPr id="1" name=""/><p:cNvGrpSpPr/><p:nvPr/></p:nvGrpSpPr>'
        '<p:grpSpPr><a:xfrm><a:off x="0" y="0"/><a:ext cx="0" cy="0"/>'
        '<a:chOff x="0" y="0"/><a:chExt cx="0" cy="0"/></a:xfrm></p:grpSpPr>'
        "</p:spTree></p:cSld><p:clrMapOvr><a:masterClrMapping/></p:clrMapOvr></p:sldLayout>"
    )
    layout_rels = (
        XML_HEAD
        + '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
        '<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/slideMaster" Target="../slideMasters/slideMaster1.xml"/>'
        "</Relationships>"
    )
    slide_rels = (
        XML_HEAD
        + '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
        '<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/slideLayout" Target="../slideLayouts/slideLayout1.xml"/>'
        "</Relationships>"
    )
    now = _dt.datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%SZ")
    core = (
        XML_HEAD
        + '<cp:coreProperties xmlns:cp="http://schemas.openxmlformats.org/package/2006/metadata/core-properties" '
        'xmlns:dc="http://purl.org/dc/elements/1.1/" xmlns:dcterms="http://purl.org/dc/terms/" '
        'xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance"><dc:title>%s</dc:title>'
        "<dc:creator>Dastyar</dc:creator>"
        '<dcterms:created xsi:type="dcterms:W3CDTF">%s</dcterms:created></cp:coreProperties>'
        % (escape(title or "ارائه"), now)
    )
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr("[Content_Types].xml", content_types)
        z.writestr("_rels/.rels", root_rels)
        z.writestr("docProps/core.xml", core)
        z.writestr("ppt/presentation.xml", presentation)
        z.writestr("ppt/_rels/presentation.xml.rels", pres_rels)
        z.writestr("ppt/slideMasters/slideMaster1.xml", master)
        z.writestr("ppt/slideMasters/_rels/slideMaster1.xml.rels", master_rels)
        z.writestr("ppt/slideLayouts/slideLayout1.xml", layout)
        z.writestr("ppt/slideLayouts/_rels/slideLayout1.xml.rels", layout_rels)
        z.writestr("ppt/theme/theme1.xml", theme)
        for i, s in enumerate(slides):
            z.writestr("ppt/slides/slide%d.xml" % (i + 1), slide_xml(i, s, i == 0))
            z.writestr("ppt/slides/_rels/slide%d.xml.rels" % (i + 1), slide_rels)
    return buf.getvalue()


@tool(
    "create_powerpoint",
    "یک پاورپوینت واقعی (.pptx) می‌سازد؛ اسلاید عنوان + اسلایدهای متن. مناسب ارائه، پرزنتیشن، آموزش.",
    category="آفیس",
    dangerous=True,
    confirm="ساخت فایل پاورپوینت روی دیسک",
    params={
        "path": {"type": "string"},
        "title": {"type": "string"},
        "subtitle": {"type": "string"},
        "slides": {
            "type": "array",
            "description": "اسلایدها: [{title, bullets:[...]}]",
            "items": {"type": "object"},
        },
    },
    required=["slides"],
)
def create_powerpoint(slides: List[Dict[str, Any]], path: str = "", title: str = "",
                      subtitle: str = "", ctx: Optional[ToolContext] = None) -> ToolResult:
    assert ctx is not None
    if not slides:
        raise ToolError("اسلایدها خالی است.")
    target = _resolve(path, ctx, "ارائه-دستیار.pptx")
    all_slides = [{"title": title or "ارائه", "body": [subtitle] if subtitle else []}]
    for s in slides:
        if not isinstance(s, dict):
            raise ToolError("هر اسلاید باید آبجکت {title, bullets} باشد.")
        lines = s.get("bullets") or s.get("body") or s.get("lines") or []
        if isinstance(lines, str):
            lines = [l for l in lines.splitlines() if l.strip()]
        all_slides.append({"title": s.get("title") or "", "body": lines})
    target.write_bytes(build_pptx(all_slides, title))
    ctx.attach("file", str(target))
    return ToolResult(
        "📽️ پاورپوینت ساخته شد: %s (%d اسلاید)" % (target, len(all_slides)),
        attach={"kind": "file", "path": str(target)},
    )


# --------------------------------------------------------------------------- #
# PDF
# --------------------------------------------------------------------------- #
def build_pdf(lines: Sequence[str], title: str = "") -> bytes:
    """PDF with real Persian shaping + embedded font (see ``pdfkit``)."""
    from .pdfkit import build_pdf as _build

    return _build(lines, title)


@tool(
    "create_pdf",
    "یک فایل PDF از متن می‌سازد؛ فارسی را درست می‌چیند (شکل‌دهی حروف) و فونت را داخل فایل جاسازی می‌کند.",
    category="آفیس",
    dangerous=True,
    confirm="ساخت فایل PDF روی دیسک",
    params={
        "path": {"type": "string"},
        "content": {"type": "string", "description": "متن؛ هر خط یک خط در PDF"},
        "title": {"type": "string"},
    },
    required=["content"],
)
def create_pdf(content: str, path: str = "", title: str = "",
               ctx: Optional[ToolContext] = None) -> ToolResult:
    assert ctx is not None
    target = _resolve(path, ctx, "سند-دستیار.pdf")
    target.write_bytes(build_pdf((content or "").splitlines(), title))
    ctx.attach("file", str(target))
    return ToolResult("📕 PDF ساخته شد: %s" % target, attach={"kind": "file", "path": str(target)})


# --------------------------------------------------------------------------- #
# reading office files back
# --------------------------------------------------------------------------- #
@tool(
    "extract_text_from_office",
    "متن فایل Word/Excel/PowerPoint را می‌خواند (docx, xlsx, pptx).",
    category="آفیس",
    params={"path": {"type": "string"}, "max_chars": {"type": "integer"}},
    required=["path"],
)
def extract_text_from_office(path: str, max_chars: int = 15000,
                             ctx: Optional[ToolContext] = None) -> str:
    assert ctx is not None
    p = expand(path)
    if not p.exists():
        raise ToolError("فایل «%s» پیدا نشد." % p)
    suffix = p.suffix.lower()
    texts: List[str] = []
    try:
        with zipfile.ZipFile(str(p)) as z:
            names = z.namelist()
            if suffix == ".docx":
                xml = z.read("word/document.xml").decode("utf-8", "replace")
                xml = re.sub(r"</w:p>", "\n", xml)
                texts.append(re.sub(r"(?is)<[^>]+>", "", xml))
            elif suffix == ".pptx":
                for name in sorted(n for n in names if re.match(r"ppt/slides/slide\d+\.xml$", n)):
                    xml = z.read(name).decode("utf-8", "replace")
                    parts = re.findall(r"(?is)<a:t>(.*?)</a:t>", xml)
                    texts.append("--- %s ---\n%s" % (name, "\n".join(parts)))
            elif suffix == ".xlsx":
                shared = []
                if "xl/sharedStrings.xml" in names:
                    xml = z.read("xl/sharedStrings.xml").decode("utf-8", "replace")
                    shared = re.findall(r"(?is)<t[^>]*>(.*?)</t>", xml)
                for name in sorted(n for n in names if re.match(r"xl/worksheets/sheet\d+\.xml$", n)):
                    xml = z.read(name).decode("utf-8", "replace")
                    rows = []
                    for row in re.findall(r"(?is)<row[^>]*>(.*?)</row>", xml):
                        cells = []
                        for cell in re.findall(r"(?is)<c[^>]*>(.*?)</c>", row):
                            v = re.search(r"(?is)<v>(.*?)</v>", cell)
                            is_t = re.search(r"(?is)<is>.*?<t[^>]*>(.*?)</t>", cell)
                            if is_t:
                                cells.append(is_t.group(1))
                            elif v:
                                val = v.group(1)
                                if 't="s"' in cell:
                                    try:
                                        val = shared[int(val)]
                                    except Exception:
                                        pass
                                cells.append(val)
                        if cells:
                            rows.append(" | ".join(cells))
                    texts.append("--- %s ---\n%s" % (name, "\n".join(rows)))
            else:
                raise ToolError("فقط docx, xlsx, pptx پشتیبانی می‌شوند.")
    except zipfile.BadZipFile:
        raise ToolError("فایل خراب است یا فرمت قدیمی (doc/xls) است؛ آن را با Office به فرمت جدید ذخیره کن.")
    import html as _html

    return truncate(_html.unescape("\n".join(texts)), int(max_chars or 15000))
