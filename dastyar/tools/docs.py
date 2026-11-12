"""Documents: markdown reports, resumes, letters, PDF from Markdown, HTML."""
from __future__ import annotations

import re
from pathlib import Path
from typing import Any, Dict, List, Optional

from ..utils import ensure_dir, expand, unique_path
from .base import ToolContext, ToolError, ToolResult, tool
from .office import build_docx, build_pdf, create_word, _docx_paragraph, _docx_table, _resolve


@tool(
    "create_markdown_report",
    "یک گزارش Markdown (با ساختار تیتر/لیست/جدول) می‌نویسد. برای فایل‌های GitHub و Obsidian عالی است.",
    category="اسناد",
    dangerous=True,
    confirm="ساخت فایل Markdown",
    params={
        "path": {"type": "string"},
        "title": {"type": "string"},
        "sections": {
            "type": "array",
            "description": "[{heading, bullets:[...], text}]",
            "items": {"type": "object"},
        },
    },
    required=["title"],
)
def create_markdown_report(title: str, sections: List[Dict[str, Any]], path: str = "",
                           ctx: Optional[ToolContext] = None) -> ToolResult:
    assert ctx is not None
    target = _resolve(path or "~/Documents/گزارش.md", ctx, "گزارش.md")
    lines = ["# " + title, ""]
    for sec in sections or []:
        if sec.get("heading"):
            lines += ["## " + str(sec["heading"]), ""]
        if sec.get("text"):
            lines += [str(sec["text"]), ""]
        for b in sec.get("bullets") or []:
            lines.append("- " + str(b))
        if sec.get("bullets"):
            lines.append("")
    target.write_text("\n".join(lines), encoding="utf-8")
    ctx.attach("file", str(target))
    return ToolResult("📝 گزارش ساخته شد: %s" % target, attach={"kind": "file", "path": str(target)})


@tool(
    "markdown_to_html",
    "یک فایل Markdown را به HTML زیبا (قابل باز شدن در مرورگر) تبدیل می‌کند.",
    category="اسناد",
    dangerous=True,
    confirm="ساخت فایل HTML",
    params={"path": {"type": "string"}, "output": {"type": "string"}, "title": {"type": "string"}},
    required=["path"],
)
def markdown_to_html(path: str, output: str = "", title: str = "",
                     ctx: Optional[ToolContext] = None) -> ToolResult:
    assert ctx is not None
    src = expand(path)
    if not src.exists():
        raise ToolError("فایل «%s» پیدا نشد." % src)
    md = src.read_text(encoding="utf-8", errors="replace")
    html_body = _md_to_html(md)
    out = expand(output) if output else src.with_suffix(".html")
    out = unique_path(out)
    page_title = title or src.stem
    out.write_text(_HTML_TEMPLATE % (page_title, page_title, html_body), encoding="utf-8")
    ctx.attach("file", str(out))
    return ToolResult("🌐 HTML ساخته شد: %s" % out, attach={"kind": "file", "path": str(out)})


_HTML_TEMPLATE = """<!doctype html>
<html lang="fa" dir="rtl"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>%s</title>
<style>
:root{--bg:#0b1020;--card:#121a33;--fg:#e8ecf7;--muted:#9aa7c7;--accent:#5b8cff}
@media (prefers-color-scheme: light){:root{--bg:#f6f8ff;--card:#fff;--fg:#131a2b;--muted:#5b6480}}
*{box-sizing:border-box}
body{margin:0;background:var(--bg);color:var(--fg);
 font:16px/1.9 "Vazirmatn","Segoe UI",Tahoma,sans-serif;padding:32px 16px}
main{max-width:860px;margin:0 auto;background:var(--card);border-radius:18px;padding:40px 44px;
 box-shadow:0 20px 60px rgba(0,0,0,.18)}
h1{font-size:2rem;margin:.2em 0 .6em;border-bottom:2px solid var(--accent);padding-bottom:.3em}
h2{margin-top:1.6em;color:var(--accent)}
h3{margin-top:1.2em}
p,li{color:var(--fg)}
code{background:rgba(127,127,127,.15);padding:2px 6px;border-radius:6px;font-size:.92em}
pre{background:rgba(127,127,127,.12);padding:16px;border-radius:12px;overflow:auto}
pre code{background:none;padding:0}
blockquote{border-right:4px solid var(--accent);margin:0;padding:.2em 1em;color:var(--muted)}
table{border-collapse:collapse;width:100%%;margin:1em 0}
th,td{border:1px solid rgba(127,127,127,.3);padding:8px 12px;text-align:right}
th{background:rgba(127,127,127,.12)}
a{color:var(--accent)}
hr{border:none;border-top:1px solid rgba(127,127,127,.3);margin:2em 0}
</style></head><body><main><h1>%s</h1>%s</main></body></html>"""


def _md_to_html(md: str) -> str:
    import html as _html

    lines = md.splitlines()
    out: List[str] = []
    in_code = False
    in_list: Optional[str] = None
    table_rows: List[List[str]] = []

    def flush_table() -> None:
        nonlocal table_rows
        if not table_rows:
            return
        head = table_rows[0]
        body = table_rows[2:] if len(table_rows) > 1 and set("".join(table_rows[1])) <= set("-:| ") else table_rows[1:]
        out.append("<table><thead><tr>" + "".join("<th>%s</th>" % c for c in head) + "</tr></thead><tbody>")
        for row in body:
            out.append("<tr>" + "".join("<td>%s</td>" % c for c in row) + "</tr>")
        out.append("</tbody></table>")
        table_rows = []

    for line in lines:
        if line.strip().startswith("```"):
            if in_code:
                out.append("</code></pre>")
                in_code = False
            else:
                if in_list:
                    out.append("</%s>" % in_list)
                    in_list = None
                out.append("<pre><code>")
                in_code = True
            continue
        if in_code:
            out.append(_html.escape(line))
            continue
        if "|" in line and line.strip().startswith("|"):
            table_rows.append([c.strip() for c in line.strip().strip("|").split("|")])
            continue
        flush_table()
        stripped = line.strip()
        if not stripped:
            if in_list:
                out.append("</%s>" % in_list)
                in_list = None
            continue
        m = re.match(r"^(#{1,6})\s+(.*)$", stripped)
        if m:
            if in_list:
                out.append("</%s>" % in_list)
                in_list = None
            level = len(m.group(1))
            out.append("<h%d>%s</h%d>" % (level, _inline(m.group(2)), level))
            continue
        if re.match(r"^[-*+]\s+", stripped):
            if in_list != "ul":
                if in_list:
                    out.append("</%s>" % in_list)
                out.append("<ul>")
                in_list = "ul"
            out.append("<li>%s</li>" % _inline(re.sub(r"^[-*+]\s+", "", stripped)))
            continue
        if re.match(r"^\d+\.\s+", stripped):
            if in_list != "ol":
                if in_list:
                    out.append("</%s>" % in_list)
                out.append("<ol>")
                in_list = "ol"
            out.append("<li>%s</li>" % _inline(re.sub(r"^\d+\.\s+", "", stripped)))
            continue
        if stripped.startswith(">"):
            out.append("<blockquote>%s</blockquote>" % _inline(stripped.lstrip("> ")))
            continue
        if set(stripped) <= set("-*_ ") and len(stripped) >= 3:
            out.append("<hr>")
            continue
        out.append("<p>%s</p>" % _inline(stripped))
    flush_table()
    if in_list:
        out.append("</%s>" % in_list)
    if in_code:
        out.append("</code></pre>")
    return "\n".join(out)


def _inline(text: str) -> str:
    import html as _html

    text = _html.escape(text)
    text = re.sub(r"`([^`]+)`", r"<code>\1</code>", text)
    text = re.sub(r"\*\*([^*]+)\*\*", r"<strong>\1</strong>", text)
    text = re.sub(r"(?<!\*)\*([^*]+)\*(?!\*)", r"<em>\1</em>", text)
    text = re.sub(r"\[([^\]]+)\]\(([^)]+)\)", r'<a href="\2">\1</a>', text)
    return text


@tool(
    "markdown_to_pdf",
    "یک فایل Markdown را به PDF تبدیل می‌کند (ساده و بدون کتابخانه‌ی خارجی).",
    category="اسناد",
    dangerous=True,
    confirm="ساخت فایل PDF",
    params={"path": {"type": "string"}, "output": {"type": "string"}},
    required=["path"],
)
def markdown_to_pdf(path: str, output: str = "", ctx: Optional[ToolContext] = None) -> ToolResult:
    assert ctx is not None
    src = expand(path)
    if not src.exists():
        raise ToolError("فایل پیدا نشد: %s" % src)
    lines: List[str] = []
    for raw in src.read_text(encoding="utf-8", errors="replace").splitlines():
        line = re.sub(r"^\s*#{1,6}\s*", "", raw)          # headings
        line = re.sub(r"^\s*>\s?", "", line)             # quotes
        line = re.sub(r"^\s*[-*+]\s+", "• ", line)       # bullets
        line = re.sub(r"\*\*(.+?)\*\*", r"\1", line)     # bold
        line = re.sub(r"`([^`]*)`", r"\1", line)         # inline code
        lines.append(line)
    out = expand(output) if output else src.with_suffix(".pdf")
    out = unique_path(out)
    out.write_bytes(build_pdf(lines, src.stem))
    ctx.attach("file", str(out))
    return ToolResult("📕 PDF ساخته شد: %s" % out, attach={"kind": "file", "path": str(out)})


@tool(
    "make_resume",
    "یک رزومه‌ی حرفه‌ای Word می‌سازد از نام، عنوان، اطلاعات تماس، مهارت‌ها و سوابق.",
    category="اسناد",
    dangerous=True,
    confirm="ساخت فایل رزومه",
    params={
        "path": {"type": "string"},
        "name": {"type": "string"},
        "headline": {"type": "string", "description": "عنوان شغلی، مثل «مهندس نرم‌افزار»"},
        "contact": {"type": "string", "description": "ایمیل | تلفن | شهر | لینکدین"},
        "summary": {"type": "string"},
        "skills": {"type": "array", "items": {"type": "string"}},
        "experience": {"type": "array", "items": {"type": "string"},
                       "description": "هر آیتم: «عنوان — شرکت (۲۰۲۰-۲۰۲۴): توضیح»"},
        "education": {"type": "array", "items": {"type": "string"}},
    },
    required=["name"],
)
def make_resume(name: str, headline: str = "", contact: str = "", summary: str = "",
                skills: Optional[List[str]] = None, experience: Optional[List[str]] = None,
                education: Optional[List[str]] = None, path: str = "",
                ctx: Optional[ToolContext] = None) -> ToolResult:
    assert ctx is not None
    safe = re.sub(r"[^\w\-]+", "-", name or "resume")
    target = _resolve(path or ("~/Documents/رزومه-%s.docx" % safe), ctx, "resume.docx")
    body: List[str] = [_docx_paragraph(name, style="Title", bold=True, size=28)]
    if headline:
        body.append(_docx_paragraph(headline, size=14, align="center"))
    if contact:
        body.append(_docx_paragraph(contact, size=10, align="center"))
    body.append("<w:p/>")
    if summary:
        body += [_docx_paragraph("درباره من", style="Heading1", bold=True, size=15),
                 _docx_paragraph(summary)]
    if skills:
        body += [_docx_paragraph("مهارت‌ها", style="Heading1", bold=True, size=15),
                 _docx_paragraph(" • ".join(skills))]
    if experience:
        body.append(_docx_paragraph("سوابق کاری", style="Heading1", bold=True, size=15))
        for item in experience:
            body.append(_docx_paragraph("• " + item))
    if education:
        body.append(_docx_paragraph("تحصیلات", style="Heading1", bold=True, size=15))
        for item in education:
            body.append(_docx_paragraph("• " + item))
    target.write_bytes(build_docx("".join(body), name))
    ctx.attach("file", str(target))
    return ToolResult("📄 رزومه ساخته شد: %s" % target, attach={"kind": "file", "path": str(target)})


@tool(
    "make_letter",
    "یک نامه‌ی رسمی Word می‌سازد (فرستنده، گیرنده، موضوع، متن).",
    category="اسناد",
    dangerous=True,
    confirm="ساخت فایل نامه",
    params={
        "path": {"type": "string"},
        "sender": {"type": "string"},
        "recipient": {"type": "string"},
        "subject": {"type": "string"},
        "body": {"type": "string"},
        "date": {"type": "string"},
    },
    required=["body"],
)
def make_letter(body: str, sender: str = "", recipient: str = "", subject: str = "",
                date: str = "", path: str = "", ctx: Optional[ToolContext] = None) -> ToolResult:
    assert ctx is not None
    target = _resolve(path or "~/Documents/نامه.docx", ctx, "نامه.docx")
    parts = []
    if sender:
        parts.append(_docx_paragraph("از: " + sender, size=11))
    if date:
        parts.append(_docx_paragraph("تاریخ: " + date, size=11))
    if recipient:
        parts.append(_docx_paragraph("به: " + recipient, size=11))
    parts.append("<w:p/>")
    if subject:
        parts.append(_docx_paragraph("موضوع: " + subject, bold=True))
    parts.append(_docx_paragraph("با سلام و احترام،", size=12))
    for line in (body or "").splitlines():
        parts.append(_docx_paragraph(line))
    parts.append("<w:p/>")
    if sender:
        parts.append(_docx_paragraph("با احترام،\n" + sender, align="left"))
    target.write_bytes(build_docx("".join(parts), subject or "نامه"))
    ctx.attach("file", str(target))
    return ToolResult("✉️ نامه ساخته شد: %s" % target, attach={"kind": "file", "path": str(target)})
