"""File & folder tools (بیشتر کارهای روزمره)."""
from __future__ import annotations

import csv
import io
import os
import shutil
import stat
import time
import zipfile
from pathlib import Path
from typing import Any, Dict, List, Optional

from ..config import IS_WINDOWS
from ..utils import (
    app_files_dir,
    ensure_dir,
    expand,
    human_size,
    powershell,
    ps_quote,
    read_json,
    truncate,
    unique_path,
    write_json,
)
from .base import ToolContext, ToolError, ToolResult, tool

READ_LIMIT = 200_000  # bytes


# --------------------------------------------------------------------------- #
# sandbox helpers
# --------------------------------------------------------------------------- #
def _allowed(ctx: ToolContext) -> bool:
    return bool(ctx.settings.get("allow_all_paths"))


def check_access(ctx: ToolContext, path: Path, write: bool = False) -> Path:
    """Enforce the allowed-paths sandbox (settings -> allowed_paths)."""
    resolved = path.expanduser().resolve()
    if _allowed(ctx):
        return resolved
    for base in ctx.settings.allowed_paths:
        try:
            resolved.relative_to(base)
            return resolved
        except ValueError:
            continue
    raise ToolError(
        "دسترسی به «%s» مجاز نیست. مسیرهای مجاز: %s. "
        "برای دسترسی به همه‌جای سیستم، در تنظیمات گزینه‌ی «دسترسی آزاد به فایل‌ها» را روشن کن."
        % (resolved, "، ".join(str(p) for p in ctx.settings.allowed_paths) or "—")
    )


def _dir_listing(path: Path, show_hidden: bool = False) -> List[Dict[str, Any]]:
    items = []
    try:
        for entry in sorted(path.iterdir(), key=lambda p: (p.is_file(), p.name.lower())):
            if not show_hidden and entry.name.startswith("."):
                continue
            try:
                st = entry.stat()
                items.append(
                    {
                        "name": entry.name,
                        "dir": entry.is_dir(),
                        "size": 0 if entry.is_dir() else st.st_size,
                        "mtime": st.st_mtime,
                    }
                )
            except Exception:
                continue
    except PermissionError:
        raise ToolError("اجازه‌ی خواندن پوشه «%s» را ندارم." % path)
    return items


def _fmt_listing(items: List[Dict[str, Any]], limit: int = 200) -> str:
    lines = []
    for it in items[:limit]:
        icon = "📁" if it["dir"] else "📄"
        size = "" if it["dir"] else "  " + human_size(it["size"])
        date = time.strftime("%Y-%m-%d", time.localtime(it["mtime"]))
        lines.append("%s %s%s  (%s)" % (icon, it["name"], size, date))
    if len(items) > limit:
        lines.append("… و %d مورد دیگر" % (len(items) - limit))
    if not lines:
        lines.append("(خالی)")
    return "\n".join(lines)


# --------------------------------------------------------------------------- #
# tools
# --------------------------------------------------------------------------- #
@tool(
    "list_files",
    "فهرست فایل‌ها و پوشه‌های یک مسیر را نشان می‌دهد. مسیر می‌تواند ~ باشد (مثل ~/Desktop).",
    category="فایل",
    params={
        "path": {"type": "string", "description": "مسیر پوشه، پیش‌فرض ~/Desktop"},
        "show_hidden": {"type": "boolean", "description": "نمایش فایل‌های مخفی"},
        "pattern": {"type": "string", "description": "فیلتر نام، مثل *.jpg"},
    },
)
def list_files(path: str = "~/Desktop", show_hidden: bool = False,
               pattern: str = "", ctx: Optional[ToolContext] = None) -> str:
    assert ctx is not None
    target = check_access(ctx, expand(path))
    if not target.exists():
        # desktop may not exist (fresh Windows profile, Linux sandbox, ...)
        fallback = expand("~")
        try:
            target = check_access(ctx, fallback)
        except ToolError:
            raise ToolError("مسیر «%s» وجود ندارد." % target)
        else:
            if not target.exists():
                raise ToolError("مسیر «%s» وجود ندارد." % target)
    if target.is_file():
        return file_info(str(target), ctx=ctx)
    items = _dir_listing(target, show_hidden)
    if pattern:
        import fnmatch

        items = [i for i in items if fnmatch.fnmatch(i["name"].lower(), pattern.lower())]
    total = sum(i["size"] for i in items if not i["dir"])
    return "📂 %s\n\n%s\n\nمجموع حجم فایل‌ها: %s" % (target, _fmt_listing(items), human_size(total))


@tool(
    "file_info",
    "اطلاعات یک فایل یا پوشه را نشان می‌دهد (حجم، تاریخ، نوع).",
    category="فایل",
    params={"path": {"type": "string"}},
    required=["path"],
)
def file_info(path: str, ctx: Optional[ToolContext] = None) -> str:
    assert ctx is not None
    p = check_access(ctx, expand(path))
    if not p.exists():
        raise ToolError("«%s» وجود ندارد." % p)
    st = p.stat()
    kind = "پوشه" if p.is_dir() else "فایل"
    extra = ""
    if p.is_file() and p.suffix.lower() in (".txt", ".md", ".json", ".py", ".csv", ".log", ".ini"):
        try:
            with p.open("r", encoding="utf-8", errors="replace") as fh:
                preview = fh.read(600)
            extra = "\n\n🔎 پیش‌نمایش:\n" + preview
        except Exception:
            pass
    return (
        "📌 %s\nنوع: %s\nحجم: %s\nتاریخ ساخت: %s\nآخرین تغییر: %s%s"
        % (
            p,
            kind,
            human_size(st.st_size),
            time.strftime("%Y-%m-%d %H:%M", time.localtime(st.st_ctime)),
            time.strftime("%Y-%m-%d %H:%M", time.localtime(st.st_mtime)),
            extra,
        )
    )


@tool(
    "read_file",
    "محتوای یک فایل متنی را می‌خواند (txt, md, csv, json, py, html, log ...).",
    category="فایل",
    params={
        "path": {"type": "string"},
        "max_chars": {"type": "integer", "description": "حداکثر کاراکتر، پیش‌فرض ۲۰۰۰۰"},
    },
    required=["path"],
)
def read_file(path: str, max_chars: int = 20000, ctx: Optional[ToolContext] = None) -> str:
    assert ctx is not None
    p = check_access(ctx, expand(path))
    if not p.exists() or p.is_dir():
        raise ToolError("فایل «%s» پیدا نشد." % p)
    if p.stat().st_size > 25 * 1024 * 1024:
        raise ToolError("فایل خیلی بزرگ است (بیشتر از ۲۵ مگابایت).")
    data = p.read_bytes()
    for enc in ("utf-8", "utf-8-sig", "cp1256", "latin-1"):
        try:
            text = data.decode(enc)
            break
        except UnicodeDecodeError:
            continue
    else:  # pragma: no cover
        raise ToolError("محتوای فایل قابل خواندن نیست (شاید فایل دودویی باشد).")
    return truncate(text, int(max_chars or 20000))


@tool(
    "write_file",
    "یک فایل متنی می‌نویسد یا به آن اضافه می‌کند. پوشه‌ها در صورت نبود ساخته می‌شوند.",
    category="فایل",
    dangerous=True,
    confirm="نوشتن فایل در دیسک",
    params={
        "path": {"type": "string"},
        "content": {"type": "string"},
        "append": {"type": "boolean", "description": "افزودن به انتهای فایل"},
    },
    required=["path", "content"],
)
def write_file_tool(path: str, content: str, append: bool = False,
                    ctx: Optional[ToolContext] = None) -> str:
    assert ctx is not None
    p = check_access(ctx, expand(path), write=True)
    ensure_dir(p.parent)
    mode = "a" if append else "w"
    with p.open(mode, encoding="utf-8") as fh:
        fh.write(content or "")
    return "✅ نوشته شد: %s (%s)" % (p, human_size(len((content or "").encode("utf-8"))))


@tool(
    "make_folder",
    "یک پوشه‌ی جدید می‌سازد (پوشه‌های میانی هم ساخته می‌شوند).",
    category="فایل",
    dangerous=True,
    confirm="ساخت پوشه روی دیسک",
    params={"path": {"type": "string"}},
    required=["path"],
)
def make_folder(path: str, ctx: Optional[ToolContext] = None) -> str:
    assert ctx is not None
    p = check_access(ctx, expand(path), write=True)
    ensure_dir(p)
    return "✅ پوشه ساخته شد: %s" % p


@tool(
    "copy_file",
    "کپی کردن فایل یا پوشه (برای بکاپ گرفتن عالی است).",
    category="فایل",
    dangerous=True,
    confirm="کپی فایل",
    params={"source": {"type": "string"}, "destination": {"type": "string"}},
    required=["source", "destination"],
)
def copy_file(source: str, destination: str, ctx: Optional[ToolContext] = None) -> str:
    assert ctx is not None
    src = check_access(ctx, expand(source))
    dst = check_access(ctx, expand(destination), write=True)
    if not src.exists():
        raise ToolError("منبع «%s» پیدا نشد." % src)
    if dst.is_dir():
        dst = dst / src.name
    ensure_dir(dst.parent)
    dst = unique_path(dst)
    if src.is_dir():
        shutil.copytree(str(src), str(dst))
    else:
        shutil.copy2(str(src), str(dst))
    return "✅ کپی شد: %s → %s" % (src, dst)


@tool(
    "move_file",
    "جابه‌جا کردن یا تغییر نام یک فایل/پوشه.",
    category="فایل",
    dangerous=True,
    confirm="جابه‌جایی فایل",
    params={"source": {"type": "string"}, "destination": {"type": "string"}},
    required=["source", "destination"],
)
def move_file(source: str, destination: str, ctx: Optional[ToolContext] = None) -> str:
    assert ctx is not None
    src = check_access(ctx, expand(source))
    dst = check_access(ctx, expand(destination), write=True)
    if not src.exists():
        raise ToolError("منبع «%s» پیدا نشد." % src)
    if dst.is_dir():
        dst = dst / src.name
    ensure_dir(dst.parent)
    shutil.move(str(src), str(dst))
    return "✅ جابه‌جا شد: %s → %s" % (src, dst)


@tool(
    "delete_file",
    "حذف فایل یا پوشه. به صورت پیش‌فرض به سطل بازیافت ویندوز می‌رود تا قابل بازگردانی باشد.",
    category="فایل",
    dangerous=True,
    confirm="حذف فایل/پوشه از دیسک",
    params={
        "path": {"type": "string"},
        "permanent": {"type": "boolean", "description": "حذف کامل و غیرقابل بازگشت"},
    },
    required=["path"],
)
def delete_file(path: str, permanent: bool = False, ctx: Optional[ToolContext] = None) -> str:
    assert ctx is not None
    p = check_access(ctx, expand(path), write=True)
    if not p.exists():
        raise ToolError("«%s» وجود ندارد." % p)
    if p == Path.home() or str(p) in ("/", "C:\\"):
        raise ToolError("حذف پوشه‌ی خانه یا ریشه ممنوع است.")
    if IS_WINDOWS and not permanent:
        rc, out, err = powershell(
            "Add-Type -AssemblyName Microsoft.VisualBasic; "
            "[Microsoft.VisualBasic.FileIO.FileSystem]::DeleteFile(%s,'OnlyErrorDialogs','SendToRecycleBin')"
            % ps_quote(str(p))
            if p.is_file()
            else "Add-Type -AssemblyName Microsoft.VisualBasic; "
            "[Microsoft.VisualBasic.FileIO.FileSystem]::DeleteDirectory(%s,'OnlyErrorDialogs','SendToRecycleBin')"
            % ps_quote(str(p)),
            timeout=30,
        )
        if rc == 0:
            return "🗑️ به سطل بازیافت منتقل شد: %s" % p
    if p.is_dir():
        shutil.rmtree(str(p))
    else:
        p.unlink()
    return "🗑️ حذف شد: %s" % p


@tool(
    "find_files",
    "جست‌وجوی فایل بر اساس نام یا الگو در یک پوشه (مثل *.pdf).",
    category="فایل",
    params={
        "root": {"type": "string", "description": "پوشه‌ی شروع، پیش‌فرض خانه"},
        "pattern": {"type": "string", "description": "الگوی نام، مثل *.jpg"},
        "max_results": {"type": "integer"},
    },
    required=["pattern"],
)
def find_files(pattern: str, root: str = "~", max_results: int = 50,
               ctx: Optional[ToolContext] = None) -> str:
    assert ctx is not None
    base = check_access(ctx, expand(root))
    if not base.exists():
        raise ToolError("پوشه «%s» وجود ندارد." % base)
    import fnmatch

    hits: List[Path] = []
    for dirpath, dirnames, filenames in os.walk(str(base)):
        dirnames[:] = [d for d in dirnames if not d.startswith(".") and d not in
                       ("node_modules", "__pycache__", "AppData", "Windows", "$Recycle.Bin")]
        for name in filenames:
            if fnmatch.fnmatch(name.lower(), pattern.lower()):
                hits.append(Path(dirpath) / name)
                if len(hits) >= int(max_results):
                    break
        if len(hits) >= int(max_results):
            break
    if not hits:
        return "چیزی با الگوی «%s» در %s پیدا نشد." % (pattern, base)
    return "🔍 %d نتیجه:\n" % len(hits) + "\n".join("• %s (%s)" % (h, human_size(h.stat().st_size)) for h in hits)


@tool(
    "search_inside_files",
    "در محتوای فایل‌های متنی یک پوشه، عبارت مشخصی را جست‌وجو می‌کند.",
    category="فایل",
    params={
        "query": {"type": "string"},
        "root": {"type": "string", "description": "پیش‌فرض ~/Documents"},
        "max_results": {"type": "integer"},
    },
    required=["query"],
)
def search_inside_files(query: str, root: str = "~/Documents", max_results: int = 30,
                        ctx: Optional[ToolContext] = None) -> str:
    assert ctx is not None
    base = check_access(ctx, expand(root))
    exts = {".txt", ".md", ".csv", ".json", ".py", ".js", ".html", ".css", ".log", ".ini", ".xml"}
    hits = []
    for dirpath, dirnames, filenames in os.walk(str(base)):
        dirnames[:] = [d for d in dirnames if not d.startswith(".")]
        for name in filenames:
            p = Path(dirpath) / name
            if p.suffix.lower() not in exts or p.stat().st_size > 3 * 1024 * 1024:
                continue
            try:
                text = p.read_text(encoding="utf-8", errors="ignore")
            except Exception:
                continue
            idx = text.lower().find(str(query).lower())
            if idx >= 0:
                line_no = text[:idx].count("\n") + 1
                snippet = text[max(0, idx - 60): idx + 120].replace("\n", " ")
                hits.append("• %s:%d — …%s…" % (p, line_no, snippet))
                if len(hits) >= int(max_results):
                    break
        if len(hits) >= int(max_results):
            break
    return "🔎 %d نتیجه برای «%s»:\n%s" % (len(hits), query, "\n".join(hits) or "چیزی پیدا نشد.")


@tool(
    "zip_folder",
    "یک فایل/پوشه را فشرده (zip) می‌کند — مناسب برای بکاپ.",
    category="فایل",
    dangerous=True,
    confirm="ساخت فایل zip",
    params={"path": {"type": "string"}, "output": {"type": "string", "description": "اختیاری"}},
    required=["path"],
)
def zip_folder(path: str, output: str = "", ctx: Optional[ToolContext] = None) -> str:
    assert ctx is not None
    src = check_access(ctx, expand(path))
    if not src.exists():
        raise ToolError("«%s» وجود ندارد." % src)
    out = expand(output) if output else src.with_suffix(".zip")
    if src.is_file() and not output:
        out = src.with_name(src.stem + ".zip")
    out = check_access(ctx, out, write=True)
    ensure_dir(out.parent)
    out = unique_path(out)
    with zipfile.ZipFile(str(out), "w", zipfile.ZIP_DEFLATED) as zf:
        if src.is_dir():
            for dirpath, _, filenames in os.walk(str(src)):
                for name in filenames:
                    full = Path(dirpath) / name
                    zf.write(str(full), str(full.relative_to(src.parent)))
        else:
            zf.write(str(src), src.name)
    return "🗜️ فایل فشرده ساخته شد: %s (%s)" % (out, human_size(out.stat().st_size))


@tool(
    "unzip_archive",
    "یک فایل zip را باز می‌کند.",
    category="فایل",
    dangerous=True,
    confirm="باز کردن فایل فشرده",
    params={"path": {"type": "string"}, "destination": {"type": "string"}},
    required=["path"],
)
def unzip_archive(path: str, destination: str = "", ctx: Optional[ToolContext] = None) -> str:
    assert ctx is not None
    src = check_access(ctx, expand(path))
    if not src.exists():
        raise ToolError("«%s» وجود ندارد." % src)
    dest = check_access(ctx, expand(destination) if destination else src.with_suffix(""), write=True)
    ensure_dir(dest)
    with zipfile.ZipFile(str(src)) as zf:
        zf.extractall(str(dest))
    return "📦 باز شد در: %s" % dest


@tool(
    "disk_usage",
    "فضای خالی و کل درایوها/دیسک‌ها را نشان می‌دهد.",
    category="فایل",
    params={},
)
def disk_usage(ctx: Optional[ToolContext] = None) -> str:
    lines = []
    if IS_WINDOWS:
        drives = [chr(c) + ":\\" for c in range(65, 91) if os.path.exists(chr(c) + ":\\")]
    else:
        drives = ["/"]
    for d in drives:
        try:
            usage = shutil.disk_usage(d)
            pct = 100.0 * usage.used / usage.total if usage.total else 0
            lines.append(
                "💽 %s  کل: %s • آزاد: %s • مصرف: %.1f%%"
                % (d, human_size(usage.total), human_size(usage.free), pct)
            )
        except Exception:
            continue
    return "\n".join(lines) or "اطلاعات دیسک در دسترس نیست."


@tool(
    "create_csv",
    "یک فایل CSV (قابل باز شدن در اکسل) با سرستون و ردیف‌ها می‌سازد.",
    category="فایل",
    dangerous=True,
    confirm="ساخت فایل CSV",
    params={
        "path": {"type": "string"},
        "headers": {"type": "array", "items": {"type": "string"}},
        "rows": {"type": "array", "items": {"type": "array", "items": {"type": "string"}}},
    },
    required=["path", "headers", "rows"],
)
def create_csv(path: str, headers: List[str], rows: List[List[Any]],
               ctx: Optional[ToolContext] = None) -> str:
    assert ctx is not None
    p = check_access(ctx, expand(path), write=True)
    ensure_dir(p.parent)
    with p.open("w", encoding="utf-8-sig", newline="") as fh:
        writer = csv.writer(fh)
        writer.writerow(headers)
        for row in rows:
            writer.writerow(row)
    return "📊 فایل CSV ساخته شد: %s (%d ردیف)" % (p, len(rows))


@tool(
    "read_csv",
    "محتوای یک فایل CSV را می‌خواند و به صورت جدول برمی‌گرداند.",
    category="فایل",
    params={"path": {"type": "string"}, "max_rows": {"type": "integer"}},
    required=["path"],
)
def read_csv(path: str, max_rows: int = 50, ctx: Optional[ToolContext] = None) -> str:
    assert ctx is not None
    p = check_access(ctx, expand(path))
    if not p.exists():
        raise ToolError("«%s» پیدا نشد." % p)
    with p.open("r", encoding="utf-8-sig", errors="replace", newline="") as fh:
        rows = list(csv.reader(fh))
    if not rows:
        return "(فایل خالی است)"
    head = rows[0]
    body = rows[1 : 1 + int(max_rows)]
    widths = [max(len(str(head[i])), *(len(str(r[i])) for r in body if i < len(r))) for i in range(len(head))]
    line = lambda r: " | ".join(str(r[i]).ljust(widths[i]) for i in range(min(len(r), len(head))))
    out = [line(head), "-+-".join("-" * w for w in widths)]
    out += [line(r) for r in body]
    if len(rows) - 1 > int(max_rows):
        out.append("… %d ردیف دیگر" % (len(rows) - 1 - int(max_rows)))
    return "\n".join(out)


@tool(
    "recent_files",
    "فایل‌های اخیراً تغییرکرده در پوشه‌های مهم را فهرست می‌کند.",
    category="فایل",
    params={"hours": {"type": "integer"}, "limit": {"type": "integer"}},
)
def recent_files(hours: int = 24, limit: int = 25, ctx: Optional[ToolContext] = None) -> str:
    assert ctx is not None
    cutoff = time.time() - int(hours) * 3600
    roots = [expand(p) for p in ctx.settings.allowed_paths]
    found = []
    for root in roots:
        if not root.exists():
            continue
        for dirpath, dirnames, filenames in os.walk(str(root)):
            dirnames[:] = [d for d in dirnames if not d.startswith(".")]
            for name in filenames:
                full = Path(dirpath) / name
                try:
                    st = full.stat()
                except Exception:
                    continue
                if st.st_mtime >= cutoff:
                    found.append((st.st_mtime, full, st.st_size))
    found.sort(reverse=True)
    if not found:
        return "در %d ساعت گذشته فایلی تغییر نکرده است." % hours
    return "🕒 %d فایل اخیر:\n%s" % (
        len(found[:limit]),
        "\n".join(
            "• %s  (%s — %s)" % (p, human_size(s), time.strftime("%m-%d %H:%M", time.localtime(m)))
            for m, p, s in found[:limit]
        ),
    )


@tool(
    "backup_folder",
    "از یک پوشه بکاپ zip با تاریخ می‌گیرد (در پوشه‌ی Downloads/Dastyar-Backups).",
    category="فایل",
    dangerous=True,
    confirm="ساخت بکاپ",
    params={"path": {"type": "string"}},
    required=["path"],
)
def backup_folder(path: str, ctx: Optional[ToolContext] = None) -> str:
    assert ctx is not None
    src = check_access(ctx, expand(path))
    if not src.exists():
        raise ToolError("«%s» وجود ندارد." % src)
    dest_dir = ctx.settings.allowed_paths[2] if len(ctx.settings.allowed_paths) > 2 else Path.home()
    out_dir = ensure_dir(dest_dir / "Dastyar-Backups")
    stamp = time.strftime("%Y%m%d-%H%M%S")
    out = out_dir / ("%s-backup-%s.zip" % (src.name, stamp))
    with zipfile.ZipFile(str(out), "w", zipfile.ZIP_DEFLATED) as zf:
        for dirpath, _, filenames in os.walk(str(src)):
            for name in filenames:
                full = Path(dirpath) / name
                try:
                    zf.write(str(full), str(full.relative_to(src.parent)))
                except Exception:
                    continue
    return "💾 بکاپ ساخته شد: %s (%s)" % (out, human_size(out.stat().st_size))
