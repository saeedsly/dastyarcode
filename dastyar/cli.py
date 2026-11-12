"""Command line interface: ``dastyar <command>``."""
from __future__ import annotations

import argparse
import json
import os
import sys
import time
from pathlib import Path

from . import __app_name__, __version__
from .config import (
    PROVIDERS,
    Settings,
    data_dir,
    ensure_data_dir,
    find_python,
    os_label,
)
from .secret import protect, unprotect

BANNER = r"""
   ___                _
  / _ \  __ _  ___| |_ _   _  __ _ _ __
 / /_\ \/ _` |/ __| __| | | |/ _` | '__|
/ /_\\ \ (_| |\__ \ |_| |_| | (_| | |
\/_\\_/\__,_||___/\__|\__, |\__,_|_|
                       |___/   {ver}
""".format(ver="v" + __version__)

HELP_EXTRA = """
دستورها:
  run                 اجرای برنامه (پنجره‌ی برنامه + رابط وب)   [پیش‌فرض]
  chat                گفت‌وگو در ترمینال (بدون رابط گرافیکی)
  doctor              بررسی کامل سیستم و رفع مشکلات
  config KEY [VALUE]  دیدن یا تنظیم مقدار (مثال: config provider groq)
  key                 تنظیم کلید API (مخفی وارد می‌شود)
  tools               فهرست ابزارهای دستیار
  ask "..."           یک سؤال/دستور یک‌باره بدون گفت‌وگو
  serve               فقط سرور وب (بدون پنجره)
  bench               تست سرعت و اتصال مدل
  reset               پاک کردن تنظیمات و گفت‌وگوها
"""


def _settings() -> Settings:
    ensure_data_dir()
    return Settings()


def cmd_serve(args: argparse.Namespace) -> int:
    from .server import serve

    settings = _settings()
    serve(settings, port=args.port, host=args.host, open_browser=not args.no_browser)
    return 0


def cmd_run(args: argparse.Namespace) -> int:
    from .desktop import launch

    return launch(settings=_settings(), port=args.port, open_browser=not args.no_browser,
                  tray=not args.no_tray)


def cmd_chat(args: argparse.Namespace) -> int:
    from .agent import Agent

    settings = _settings()
    if not settings.has_key and settings.get("provider") != "demo":
        print("⚠️  کلید API تنظیم نشده. اول `dastyar key` را بزن یا `dastyar config provider demo`.")
    agent = Agent(settings)
    agent.headless = True   # nobody can click a confirmation dialog here
    print(BANNER)
    print("  برای خروج بنویس: exit  |  پاک کردن حافظه‌ی گفت‌وگو: /reset\n")
    while True:
        try:
            text = input("شما › ")
        except (EOFError, KeyboardInterrupt):
            print("\nخداحافظ 👋")
            return 0
        if text.strip().lower() in ("exit", "quit", "خروج"):
            return 0
        if text.strip() in ("/reset", "reset"):
            agent.reset()
            print("گفت‌وگو پاک شد.\n")
            continue
        print("دستیار › ", end="", flush=True)
        first = True
        for event in agent.run(text):
            kind = event.get("type")
            if kind == "assistant_delta":
                print(event.get("text", ""), end="", flush=True)
                first = False
            elif kind == "tool_start":
                print("\n  ⚙️  %s…" % event.get("tool"), flush=True)
            elif kind == "tool_result":
                mark = "✅" if event.get("ok") else "❌"
                preview = (event.get("output") or event.get("error") or "").strip().splitlines()
                print("  %s %s %s" % (mark, event.get("tool"),
                                      preview[0][:90] if preview else ""), flush=True)
            elif kind == "confirm_request":
                print("\n⚠️  اجازه می‌دهی؟ %s — %s" % (event.get("title"), event.get("detail")))
                answer = input("    (بله/خیر) › ").strip().lower()
                agent.resolve_confirmation(event["id"], answer in ("بله", "y", "yes", "آره", "اره", "بلی"))
            elif kind == "error":
                print("\n⚠️  " + event.get("message", ""))
            elif kind == "assistant_message" and first and not event.get("partial"):
                print(event.get("content", ""))
            elif kind == "done":
                break
        print()


def cmd_doctor(args: argparse.Namespace) -> int:
    from .doctor import run_doctor

    return run_doctor(_settings())


def cmd_config(args: argparse.Namespace) -> int:
    settings = _settings()
    if not args.key:
        print(json.dumps(settings.public_dict(), ensure_ascii=False, indent=2))
        return 0
    key = args.key.replace("-", ".")
    if not args.value:
        print(json.dumps(settings.get(key), ensure_ascii=False))
        return 0
    value: object = args.value
    if key in ("temperature",):
        value = float(args.value)
    elif key in ("max_steps",):
        value = int(args.value)
    elif key in ("vision", "tts_enabled", "auto_skills", "allow_all_paths"):
        value = args.value.lower() in ("1", "true", "yes", "on", "بله")
    elif key == "allowed_paths":
        value = [p.strip() for p in args.value.split(",") if p.strip()]
    elif key == "api_key":
        value = protect(args.value)
    settings.set(key, value)
    print("✅ %s = %s" % (key, json.dumps(value, ensure_ascii=False)))
    return 0


def cmd_key(args: argparse.Namespace) -> int:
    import getpass

    settings = _settings()
    print("ارائه‌دهنده‌های موجود: " + ", ".join(PROVIDERS))
    provider = args.provider or input("ارائه‌دهنده [openai]: ").strip() or "openai"
    if provider not in PROVIDERS:
        print("❌ ارائه‌دهنده ناشناخته")
        return 1
    info = PROVIDERS[provider]
    if info.get("keys_url"):
        print("کلید را از اینجا بگیر: %s" % info["keys_url"])
    if info.get("no_key"):
        print("این ارائه‌دهنده کلید لازم ندارد.")
    else:
        key = args.key or getpass.getpass("کلید API (تایپ نمی‌شود): ").strip()
        if not key:
            print("❌ کلید خالی است.")
            return 1
        settings.set("api_key", protect(key))
    settings.set("provider", provider)
    if info.get("base_url"):
        settings.set("base_url", info["base_url"])
    models = info.get("models") or []
    if models and (not args.model or args.model in models):
        settings.set("model", args.model or models[0])
    elif args.model:
        settings.set("model", args.model)
    print("✅ ذخیره شد: %s / %s" % (provider, settings.get("model")))
    return 0


def _swallow_broken_pipe() -> None:
    """Silence a closed stdout (``| head``) at the file-descriptor level."""
    import io

    try:
        devnull = os.open(os.devnull, os.O_WRONLY)
        os.dup2(devnull, 1)
        os.dup2(devnull, 2)
        os.close(devnull)
    except Exception:
        pass
    sink = io.StringIO()
    sys.stdout = sink
    sys.stderr = sink
    sys.__stdout__ = sink
    sys.__stderr__ = sink


def cmd_tools(args: argparse.Namespace) -> int:
    from .tools import ToolRegistry

    settings = _settings()
    reg = ToolRegistry(settings)
    items = reg.list_for_ui()
    by_cat: dict = {}
    for t in items:
        by_cat.setdefault(t["category"], []).append(t)
    out = sys.stdout
    try:
        print("🧰 %d ابزار در %d دسته:\n" % (len(items), len(by_cat)))
        out.flush()
    except BrokenPipeError:
        _swallow_broken_pipe()
        return 0
    for cat, tools in sorted(by_cat.items()):
        print("■ %s" % cat)
        for t in tools:
            flag = " ⚠️" if t["dangerous"] else ""
            print("   • %-26s %s%s" % (t["name"], t["description"][:60], flag))
        print()
    return 0


def cmd_ask(args: argparse.Namespace) -> int:
    from .agent import Agent

    settings = _settings()
    agent = Agent(settings)
    agent.headless = True
    for event in agent.run(args.text):
        if event.get("type") == "assistant_delta":
            print(event["text"], end="", flush=True)
        elif event.get("type") == "tool_result":
            print("\n[%s %s]" % ("✓" if event.get("ok") else "✗", event.get("tool")))
        elif event.get("type") == "error":
            print("\n⚠️ " + event["message"])
        elif event.get("type") == "assistant_message" and not event.get("partial"):
            if not getattr(cmd_ask, "_printed", False):
                print(event.get("content", ""))
    print()
    return 0


def cmd_bench(args: argparse.Namespace) -> int:
    from .llm import LLMClient

    settings = _settings()
    print("🔌 تست اتصال به %s (%s)…" % (settings.get("provider"), settings.get("model")))
    res = LLMClient(settings).test_connection()
    print(json.dumps(res, ensure_ascii=False, indent=2))
    return 0 if res.get("ok") else 1


def cmd_reset(args: argparse.Namespace) -> int:
    from .config import config_path, sessions_dir

    if not args.yes:
        answer = input("همه‌ی تنظیمات و گفت‌وگوها پاک شود؟ (بله/خیر) ")
        if answer.strip().lower() not in ("بله", "y", "yes", "اره", "آره"):
            print("لغو شد.")
            return 0
    try:
        config_path().unlink()
    except FileNotFoundError:
        pass
    for p in sessions_dir().glob("*.json"):
        p.unlink()
    print("🧹 پاک شد. دفعه‌ی بعد از نو تنظیم می‌کنی.")
    return 0


def cmd_update_check(args: argparse.Namespace) -> int:
    import urllib.request

    try:
        req = urllib.request.Request(
            "https://api.github.com/repos/saeedsly/dastyarcode/releases/latest",
            headers={"User-Agent": "Dastyar/" + __version__},
        )
        with urllib.request.urlopen(req, timeout=15) as resp:
            data = json.loads(resp.read().decode())
        latest = (data.get("tag_name") or "").lstrip("v")
        print("نسخه‌ی نصب‌شده: %s\nآخرین نسخه: %s" % (__version__, latest or "?"))
        if latest and latest != __version__:
            print("🔔 نسخه‌ی جدید موجود است: %s" % data.get("html_url"))
        else:
            print("✅ به‌روز هستی.")
    except Exception as exc:
        print("بررسی به‌روزرسانی ممکن نشد: %s" % exc)
    return 0


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="dastyar",
        description="%s — دستیار همه‌کاره‌ی هوشمند برای ویندوز %s" % (__app_name__, __version__),
        epilog=HELP_EXTRA,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    p.add_argument("--version", action="version", version="%(prog)s " + __version__)
    sub = p.add_subparsers(dest="command")

    for name in ("run", "serve"):
        sp = sub.add_parser(name)
        sp.add_argument("--port", type=int, default=None)
        sp.add_argument("--host", default=None)
        sp.add_argument("--no-browser", action="store_true")
        if name == "run":
            sp.add_argument("--no-tray", action="store_true")

    sub.add_parser("chat")
    sub.add_parser("doctor")
    sub.add_parser("tools")
    sub.add_parser("bench")
    sub.add_parser("update-check")

    sp = sub.add_parser("config")
    sp.add_argument("key", nargs="?")
    sp.add_argument("value", nargs="?")

    sp = sub.add_parser("key")
    sp.add_argument("provider", nargs="?")
    sp.add_argument("--model", default="")
    sp.add_argument("--key", default="")

    sp = sub.add_parser("ask")
    sp.add_argument("text")

    sp = sub.add_parser("reset")
    sp.add_argument("-y", "--yes", action="store_true")

    sp = sub.add_parser("reminders")
    sp.add_argument("--add", default="")
    sp.add_argument("--minutes", type=float, default=0)
    return p


def main(argv: list = None) -> int:
    try:
        from .config import enable_console_safety
        enable_console_safety()
    except Exception:
        pass
    argv = list(sys.argv[1:] if argv is None else argv)
    parser = build_parser()
    args = parser.parse_args(argv)
    command = args.command or "run"
    dispatch = {
        "run": cmd_run,
        "serve": cmd_serve,
        "chat": cmd_chat,
        "doctor": cmd_doctor,
        "config": cmd_config,
        "key": cmd_key,
        "tools": cmd_tools,
        "ask": cmd_ask,
        "bench": cmd_bench,
        "reset": cmd_reset,
        "update-check": cmd_update_check,
        "reminders": lambda a: 0,
    }
    try:
        return dispatch.get(command, cmd_run)(args)
    except KeyboardInterrupt:
        print("\nلغو شد.")
        return 130
    except BrokenPipeError:
        _swallow_broken_pipe()
        return 0


if __name__ == "__main__":
    sys.exit(main())
