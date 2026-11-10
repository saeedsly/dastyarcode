"""Tool framework: registry, schema generation, permission policy, execution."""
from __future__ import annotations

import inspect
import json
import traceback
from typing import Any, Callable, Dict, List, Optional

from . import (
    apps,
    browser,
    code_runner,
    dev,
    docs,
    files,
    fun,
    media,
    memory,
    net,
    notes,
    office,
    registry,
    schedule,
    speak,
    system,
    vision,
    websearch,
    windows_ui,
)
from .base import ToolContext, ToolError, ToolResult, tool


MODULES = [
    files, apps, system, net, websearch, browser, vision, office, docs,
    media, speak, code_runner, windows_ui, registry, schedule, memory, notes,
    dev, fun,
]


class ToolRegistry:
    """Collects every registered tool and executes calls safely."""

    def __init__(self, settings, policy_confirm: Optional[Callable] = None,
                 emit: Optional[Callable] = None):
        self.settings = settings
        self.tools: Dict[str, Callable[..., Any]] = {}
        self.meta: Dict[str, Dict[str, Any]] = {}
        self.confirm = policy_confirm or (lambda prompt: True)
        self.emit = emit or (lambda event: None)
        self.context = ToolContext(settings=settings, emit=self.emit)
        for module in MODULES:
            self._load_module(module)

    # ------------------------------------------------------------------ #
    def _load_module(self, module) -> None:
        for name in dir(module):
            obj = getattr(module, name)
            f = getattr(obj, "__wrapped_tool__", None)
            if f is None:
                continue
            spec = f["spec"]
            self.tools[spec["name"]] = f["fn"]
            self.meta[spec["name"]] = spec

    def schemas(self, allow_names: Optional[List[str]] = None) -> List[Dict[str, Any]]:
        out = []
        for name, spec in self.meta.items():
            if allow_names and name not in allow_names:
                continue
            out.append(
                {
                    "type": "function",
                    "function": {
                        "name": name,
                        "description": spec["description"],
                        "parameters": spec["parameters"],
                    },
                }
            )
        return out

    def list_for_ui(self) -> List[Dict[str, Any]]:
        return [
            {
                "name": s["name"],
                "description": s["description"],
                "category": s.get("category", "عمومی"),
                "dangerous": s.get("dangerous", False),
                "params": s["parameters"].get("properties", {}),
            }
            for s in sorted(self.meta.values(), key=lambda x: (x.get("category", ""), x["name"]))
        ]

    # ------------------------------------------------------------------ #
    def execute(self, name: str, arguments: Any) -> Dict[str, Any]:
        """Run a tool.  Returns {"ok", "output", "error"} — never raises."""
        fn = self.tools.get(name)
        if fn is None:
            return {"ok": False, "output": "", "error": "ابزار «%s» وجود ندارد." % name}
        spec = self.meta[name]
        if isinstance(arguments, str):
            try:
                args = json.loads(arguments) if arguments.strip() else {}
            except Exception as exc:
                return {"ok": False, "output": "", "error": "آرگومان‌های JSON نامعتبر: %s" % exc}
        elif isinstance(arguments, dict):
            args = arguments
        else:
            args = {}

        # -- permission policy ------------------------------------------------
        allowed = self._policy_check(spec, args)
        if not allowed:
            return {
                "ok": False,
                "output": "",
                "error": "کاربر اجازه‌ی اجرای این ابزار را نداد (سیاست دسترسی).",
            }

        self.emit({"type": "tool_start", "tool": name, "args": _short(args), "category": spec.get("category")})
        try:
            sig = inspect.signature(fn)
            kwargs = {k: v for k, v in args.items() if k in sig.parameters and k != "ctx"}
            if "ctx" in sig.parameters:
                kwargs["ctx"] = self.context
            result = fn(**kwargs)
            if isinstance(result, ToolResult):
                payload = result.as_dict()
            else:
                payload = {"ok": True, "output": "" if result is None else str(result), "error": ""}
        except ToolError as exc:
            payload = {"ok": False, "output": exc.output or "", "error": str(exc)}
        except TypeError as exc:
            payload = {"ok": False, "output": "", "error": "پارامترهای فراخوانی اشتباه است: %s" % exc}
        except Exception as exc:  # pragma: no cover - defensive
            payload = {
                "ok": False,
                "output": "",
                "error": "%s: %s" % (type(exc).__name__, exc),
                "trace": traceback.format_exc(limit=4),
            }
        self.emit(
            {
                "type": "tool_end",
                "tool": name,
                "ok": payload.get("ok"),
                "preview": (payload.get("output") or payload.get("error") or "")[:400],
            }
        )
        return payload

    # ------------------------------------------------------------------ #
    def _policy_check(self, spec: Dict[str, Any], args: Dict[str, Any]) -> bool:
        policy = (self.settings.get("policy") or "ask").lower()
        dangerous = bool(spec.get("dangerous"))
        if policy == "auto":
            return True
        if policy == "readonly":
            return not dangerous and spec.get("category") in (
                "اطلاعات", "اینترنت", "حافظه", "نمایش", "سرگرمی"
            )
        # policy == ask
        if not dangerous:
            return True
        detail = spec.get("confirm") or "این عملیات تغییر روی سیستم ایجاد می‌کند."
        return bool(
            self.confirm(
                {
                    "tool": spec["name"],
                    "title": spec.get("title") or spec["name"],
                    "detail": detail,
                    "args": _short(args),
                }
            )
        )


def _short(args: Dict[str, Any]) -> Dict[str, Any]:
    out = {}
    for k, v in (args or {}).items():
        s = str(v)
        out[k] = s if len(s) <= 160 else s[:157] + "…"
    return out


__all__ = ["ToolRegistry", "ToolContext", "ToolError", "ToolResult", "tool"]
