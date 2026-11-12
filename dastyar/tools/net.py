"""Internet tools: download, fetch page, HTTP requests, DNS, ping."""
from __future__ import annotations

import ipaddress
import json
import os
import socket
import ssl
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any, Dict, Optional

from ..utils import ensure_dir, expand, human_size, powershell, run, truncate, unique_path
from .base import ToolContext, ToolError, ToolResult, tool

UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120 Safari/537.36"


def _validate_url(url: str, allow_local: bool = False) -> str:
    url = (url or "").strip()
    if not url:
        raise ToolError("آدرس خالی است.")
    if not url.startswith(("http://", "https://", "ftp://")):
        url = "https://" + url
    parsed = urllib.parse.urlparse(url)
    host = parsed.hostname or ""
    if not host:
        raise ToolError("آدرس معتبر نیست.")
    if not allow_local:
        try:
            ip = ipaddress.ip_address(host)
            if ip.is_private or ip.is_loopback:
                raise ToolError("دسترسی به آدرس‌های داخلی ممنوع است.")
        except ValueError:
            if host in ("localhost",) or host.endswith(".local"):
                raise ToolError("دسترسی به آدرس‌های داخلی ممنوع است.")
    return url


def _request(url: str, method: str = "GET", headers: Optional[Dict[str, str]] = None,
             data: Optional[bytes] = None, timeout: int = 30):
    hdrs = {"User-Agent": UA, "Accept": "*/*"}
    hdrs.update(headers or {})
    req = urllib.request.Request(url, data=data, headers=hdrs, method=method)
    ctx_ssl = ssl.create_default_context()
    return urllib.request.urlopen(req, timeout=timeout, context=ctx_ssl)


@tool(
    "download_file",
    "یک فایل از اینترنت دانلود می‌کند و در پوشه‌ی مشخصی ذخیره می‌کند. مسیر پیش‌فرض: Downloads.",
    category="اینترنت",
    dangerous=True,
    confirm="دانلود فایل از اینترنت روی دیسک",
    params={
        "url": {"type": "string"},
        "save_to": {"type": "string", "description": "پوشه یا مسیر کامل فایل (اختیاری)"},
    },
    required=["url"],
)
def download_file(url: str, save_to: str = "", ctx: Optional[ToolContext] = None) -> ToolResult:
    assert ctx is not None
    url = _validate_url(url)
    if ctx.settings.get("allow_all_paths") or not save_to:
        pass
    if not save_to:
        base = Path.home() / "Downloads"
    else:
        base = expand(save_to)
    if str(base).endswith(("/", "\\")) or base.is_dir() or not base.suffix:
        ensure_dir(base)
        name = os.path.basename(urllib.parse.urlparse(url).path) or "download.bin"
        dest = unique_path(base / name)
    else:
        ensure_dir(base.parent)
        dest = base
    try:
        with _request(url, timeout=60) as resp, dest.open("wb") as fh:
            total = 0
            while True:
                chunk = resp.read(256 * 1024)
                if not chunk:
                    break
                fh.write(chunk)
                total += len(chunk)
                if total > 2 * 1024 ** 3:
                    raise ToolError("فایل بزرگ‌تر از ۲ گیگابایت است؛ متوقف شد.")
    except urllib.error.HTTPError as exc:
        raise ToolError("دانلود ناموفق (HTTP %s)" % exc.code)
    except Exception as exc:
        raise ToolError("دانلود ناموفق: %s" % exc)
    if ctx:
        ctx.attach("file", str(dest))
    return ToolResult(
        "✅ دانلود شد: %s (%s)" % (dest, human_size(dest.stat().st_size)),
        attach={"kind": "file", "path": str(dest)},
    )


@tool(
    "fetch_webpage",
    "محتوای متنی یک صفحه‌ی وب را می‌خواند و به متن ساده تبدیل می‌کند (برای مطالعه/خلاصه).",
    category="اینترنت",
    params={
        "url": {"type": "string"},
        "max_chars": {"type": "integer", "description": "پیش‌فرض ۱۲۰۰۰"},
    },
    required=["url"],
)
def fetch_webpage(url: str, max_chars: int = 12000, ctx: Optional[ToolContext] = None) -> str:
    url = _validate_url(url)
    try:
        with _request(url, headers={"Accept": "text/html,application/json;q=0.9,*/*;q=0.8"}) as resp:
            raw = resp.read(3 * 1024 * 1024)
            charset = resp.headers.get_content_charset() or "utf-8"
    except urllib.error.HTTPError as exc:
        raise ToolError("دریافت صفحه ناموفق (HTTP %s)" % exc.code)
    except Exception as exc:
        raise ToolError("دریافت صفحه ناموفق: %s" % exc)
    try:
        html = raw.decode(charset, "replace")
    except LookupError:
        html = raw.decode("utf-8", "replace")
    import re as _re

    html = _re.sub(r"(?is)<script.*?</script>", " ", html)
    html = _re.sub(r"(?is)<style.*?</style>", " ", html)
    html = _re.sub(r"(?is)<!--.*?-->", " ", html)
    title = ""
    m = _re.search(r"(?is)<title[^>]*>(.*?)</title>", html)
    if m:
        title = _re.sub(r"\s+", " ", m.group(1)).strip()
    text = _re.sub(r"(?is)<br\s*/?>", "\n", html)
    text = _re.sub(r"(?is)</(p|div|li|h[1-6]|tr)>", "\n", text)
    text = _re.sub(r"(?is)<[^>]+>", " ", text)
    import html as _html

    text = _html.unescape(text)
    text = _re.sub(r"[ \t\u00a0]+", " ", text)
    text = _re.sub(r"\n\s*\n+", "\n\n", text).strip()
    header = ("عنوان صفحه: %s\nآدرس: %s\n\n" % (title, url)) if title else ""
    return truncate(header + text, int(max_chars or 12000))


@tool(
    "http_request",
    "درخواست HTTP دلخواه (GET/POST/PUT/DELETE) به یک API می‌فرستد و پاسخ را برمی‌گرداند.",
    category="اینترنت",
    params={
        "url": {"type": "string"},
        "method": {"type": "string", "enum": ["GET", "POST", "PUT", "PATCH", "DELETE"]},
        "body": {"type": "string", "description": "بدنه (JSON یا متن)"},
        "content_type": {"type": "string", "description": "پیش‌فرض application/json"},
    },
    required=["url"],
)
def http_request(url: str, method: str = "GET", body: str = "",
                 content_type: str = "application/json", ctx: Optional[ToolContext] = None) -> str:
    url = _validate_url(url)
    data = (body or "").encode("utf-8") if body else None
    headers = {"Content-Type": content_type or "application/json"}
    try:
        with _request(url, method=method, headers=headers, data=data) as resp:
            raw = resp.read(1024 * 1024)
            status = resp.status
    except urllib.error.HTTPError as exc:
        raw = exc.read(1024 * 1024)
        status = exc.code
    except Exception as exc:
        raise ToolError("درخواست ناموفق: %s" % exc)
    text = raw.decode("utf-8", "replace")
    try:
        text = json.dumps(json.loads(text), ensure_ascii=False, indent=2)
    except Exception:
        pass
    return "وضعیت: %s\n\n%s" % (status, truncate(text, 8000))


@tool(
    "internet_check",
    "بررسی می‌کند اینترنت وصل است یا نه و IP عمومی را نشان می‌دهد.",
    category="اینترنت",
    params={},
)
def internet_check(ctx: Optional[ToolContext] = None) -> str:
    try:
        with _request("https://api.ipify.org?format=json", timeout=12) as resp:
            data = resp.read().decode("utf-8", "replace")
        ip = json.loads(data).get("ip", "?")
        return "✅ اینترنت وصل است. IP عمومی: %s" % ip
    except Exception as exc:
        return "❌ اینترنت متصل نیست یا دسترسی مسدود است: %s" % exc


@tool(
    "dns_lookup",
    "آدرس IP یک دامنه را پیدا می‌کند.",
    category="اینترنت",
    params={"domain": {"type": "string"}},
    required=["domain"],
)
def dns_lookup(domain: str, ctx: Optional[ToolContext] = None) -> str:
    domain = domain.replace("http://", "").replace("https://", "").split("/")[0]
    try:
        infos = socket.getaddrinfo(domain, None)
        ips = sorted({i[4][0] for i in infos})
        return "🌐 %s → %s" % (domain, ", ".join(ips))
    except Exception as exc:
        raise ToolError("دامنه پیدا نشد: %s" % exc)


@tool(
    "ping_host",
    "پینگ گرفتن از یک میزبان برای تست اتصال.",
    category="اینترنت",
    params={"host": {"type": "string"}, "count": {"type": "integer"}},
    required=["host"],
)
def ping_host(host: str, count: int = 4, ctx: Optional[ToolContext] = None) -> str:
    count = max(1, min(10, int(count or 4)))
    cmd = ["ping", "-n" if os.name == "nt" else "-c", str(count), host]
    rc, out, err = run(cmd, timeout=30)
    return out.strip() or err.strip() or "پاسخی دریافت نشد."
