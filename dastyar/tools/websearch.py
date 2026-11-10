"""Web search: DuckDuckGo (no key), Wikipedia, Tavily (optional key)."""
from __future__ import annotations

import html
import json
import re
import urllib.parse
import urllib.request
from typing import Any, Dict, List, Optional

from ..utils import truncate
from .base import ToolContext, ToolError, tool

UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120 Safari/537.36"


def _get(url: str, timeout: int = 20) -> str:
    req = urllib.request.Request(url, headers={"User-Agent": UA, "Accept-Language": "fa,en;q=0.8"})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return resp.read(2 * 1024 * 1024).decode("utf-8", "replace")


def _strip_tags(fragment: str) -> str:
    text = re.sub(r"(?is)<[^>]+>", "", fragment)
    return html.unescape(re.sub(r"\s+", " ", text)).strip()


def duckduckgo(query: str, count: int = 8) -> List[Dict[str, str]]:
    """Scrape the lightweight HTML endpoint (no API key, no JS)."""
    url = "https://html.duckduckgo.com/html/?q=" + urllib.parse.quote(query)
    page = _get(url)
    results: List[Dict[str, str]] = []
    blocks = re.findall(r'(?is)<a[^>]+class="result__a"[^>]+href="([^"]+)"[^>]*>(.*?)</a>', page)
    snippets = re.findall(r'(?is)<a[^>]+class="result__snippet"[^>]*>(.*?)</a>', page)
    for i, (href, title) in enumerate(blocks[:count]):
        link = href
        if "uddg=" in link:
            try:
                link = urllib.parse.unquote(urllib.parse.parse_qs(urllib.parse.urlparse(link).query)["uddg"][0])
            except Exception:
                pass
        snippet = _strip_tags(snippets[i]) if i < len(snippets) else ""
        results.append({"title": _strip_tags(title), "url": link, "snippet": snippet})
    if not results:
        # fallback: lite endpoint
        page = _get("https://lite.duckduckgo.com/lite/?q=" + urllib.parse.quote(query))
        for m in re.finditer(r'(?is)<a[^>]+class="result-link"[^>]+href="([^"]+)"[^>]*>(.*?)</a>', page):
            results.append({"title": _strip_tags(m.group(2)), "url": m.group(1), "snippet": ""})
            if len(results) >= count:
                break
    return results


def wikipedia_summary(query: str) -> Optional[Dict[str, str]]:
    lang_variants = ["fa", "en"]
    for lang in lang_variants:
        try:
            search = json.loads(
                _get(
                    "https://%s.wikipedia.org/w/api.php?action=opensearch&limit=1&format=json&search=%s"
                    % (lang, urllib.parse.quote(query))
                )
            )
            if not search or not search[1]:
                continue
            title = search[1][0]
            summary = json.loads(
                _get(
                    "https://%s.wikipedia.org/api/rest_v1/page/summary/%s"
                    % (lang, urllib.parse.quote(title.replace(" ", "_")))
                )
            )
            extract = summary.get("extract") or ""
            if extract:
                return {
                    "title": title,
                    "url": (summary.get("content_urls", {}).get("desktop", {}) or {}).get("page", ""),
                    "snippet": extract,
                }
        except Exception:
            continue
    return None


def tavily(query: str, api_key: str, count: int = 6) -> List[Dict[str, str]]:
    body = json.dumps({"api_key": api_key, "query": query, "max_results": count}).encode()
    req = urllib.request.Request(
        "https://api.tavily.com/search",
        data=body,
        headers={"Content-Type": "application/json", "User-Agent": UA},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=30) as resp:
        data = json.loads(resp.read().decode())
    return [
        {"title": r.get("title", ""), "url": r.get("url", ""), "snippet": r.get("content", "")}
        for r in data.get("results", [])
    ]


@tool(
    "web_search",
    "جست‌وجوی اینترنتی. برای پیدا کردن اطلاعات تازه، خبرها، قیمت‌ها، آموزش‌ها و هر چیز روی وب.",
    category="اینترنت",
    params={
        "query": {"type": "string", "description": "عبارت جست‌وجو"},
        "count": {"type": "integer", "description": "تعداد نتایج (۱ تا ۱۰)"},
    },
    required=["query"],
)
def web_search(query: str, count: int = 8, ctx: Optional[ToolContext] = None) -> str:
    assert ctx is not None
    count = max(1, min(10, int(count or 8)))
    provider = (ctx.settings.get("web_search") or {}).get("provider", "duckduckgo")
    key = (ctx.settings.get("web_search") or {}).get("api_key", "")
    results: List[Dict[str, str]] = []
    notes = []
    if provider == "tavily" and key:
        try:
            results = tavily(query, key, count)
        except Exception as exc:
            notes.append("Tavily خطا داد: %s" % exc)
    if not results:
        try:
            results = duckduckgo(query, count)
        except Exception as exc:
            notes.append("DuckDuckGo خطا داد: %s" % exc)
    if not results:
        wiki = wikipedia_summary(query)
        if wiki:
            results = [wiki]
            notes.append("نتیجه از ویکی‌پدیا گرفته شد.")
    if not results:
        raise ToolError(
            "جست‌وجو نتیجه نداد. " + (" ".join(notes) if notes else "اتصال اینترنت را بررسی کن.")
        )
    lines = []
    for i, r in enumerate(results, 1):
        snippet = truncate(r.get("snippet") or "", 300)
        lines.append("%d. %s\n   %s\n   %s" % (i, r.get("title") or "(بدون عنوان)", r.get("url"), snippet))
    header = "🔎 نتایج «%s»:\n" % query
    if notes:
        header += "(" + " ".join(notes) + ")\n"
    return header + "\n\n".join(lines)


@tool(
    "wikipedia",
    "خلاصه‌ی یک موضوع را از ویکی‌پدیا (فارسی یا انگلیسی) می‌خواند.",
    category="اینترنت",
    params={"topic": {"type": "string"}},
    required=["topic"],
)
def wikipedia(topic: str, ctx: Optional[ToolContext] = None) -> str:
    info = wikipedia_summary(topic)
    if not info:
        raise ToolError("در ویکی‌پدیا چیزی برای «%s» پیدا نشد." % topic)
    return "📚 %s\n%s\n\n%s" % (info["title"], info["url"], info["snippet"])


@tool(
    "google_search_open",
    "عبارت جست‌وجو را در مرورگر پیش‌فرض در گوگل باز می‌کند (سریع‌ترین راه برای دیدن نتایج واقعی).",
    category="اینترنت",
    params={"query": {"type": "string"}},
    required=["query"],
)
def google_search_open(query: str, ctx: Optional[ToolContext] = None) -> str:
    from ..utils import os_open

    url = "https://www.google.com/search?q=" + urllib.parse.quote(query)
    if not os_open(url):
        raise ToolError("مرورگر باز نشد.")
    return "🌐 جست‌وجوی «%s» در مرورگر باز شد." % query


@tool(
    "youtube_search_open",
    "جست‌وجوی ویدیو در یوتیوب را در مرورگر باز می‌کند.",
    category="اینترنت",
    params={"query": {"type": "string"}},
    required=["query"],
)
def youtube_search_open(query: str, ctx: Optional[ToolContext] = None) -> str:
    from ..utils import os_open

    os_open("https://www.youtube.com/results?search_query=" + urllib.parse.quote(query))
    return "🎬 یوتیوب باز شد: %s" % query
