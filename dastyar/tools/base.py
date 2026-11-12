"""Tool decorator + result types.

Tool signature convention
-------------------------
    @tool(name="read_file", description="...", category="فایل", dangerous=False,
          params={"path": {"type": "string", "description": "..."}},
          required=["path"])
    def read_file(path: str, ctx) -> str:
        ...

``params`` is a JSON-Schema ``properties`` map.  The decorated function accepts
an optional ``ctx: ToolContext`` keyword which the registry fills in.
"""
from __future__ import annotations

import functools
from typing import Any, Callable, Dict, List, Optional


class ToolError(Exception):
    def __init__(self, message: str, output: str = ""):
        super().__init__(message)
        self.output = output


class ToolResult:
    """Rich tool output: text for the model + optional attachment for the UI."""

    def __init__(self, output: str = "", ok: bool = True, error: str = "",
                 attach: Optional[Dict[str, Any]] = None):
        self.output = output
        self.ok = ok
        self.error = error
        self.attach = attach

    def as_dict(self) -> Dict[str, Any]:
        d: Dict[str, Any] = {"ok": self.ok, "output": self.output, "error": self.error}
        if self.attach:
            d["attach"] = self.attach
        return d


class ToolContext:
    """Per-registry helpers passed to tools (emit events, settings, confirm)."""

    def __init__(self, settings, emit: Callable[[Dict[str, Any]], None]):
        self.settings = settings
        self.emit = emit

    def attach(self, kind: str, path: str = "", **extra: Any) -> None:
        payload = {"type": "attachment", "kind": kind, "path": path}
        payload.update(extra)
        self.emit(payload)


_PARAM_TYPES = {
    "string": "string",
    "integer": "integer",
    "number": "number",
    "boolean": "boolean",
    "array": "array",
    "object": "object",
    str: "string",
    int: "integer",
    float: "number",
    bool: "boolean",
    list: "array",
    dict: "object",
}


def tool(
    name: str,
    description: str,
    category: str = "عمومی",
    dangerous: bool = False,
    confirm: str = "",
    params: Optional[Dict[str, Any]] = None,
    required: Optional[List[str]] = None,
) -> Callable[[Callable[..., Any]], Callable[..., Any]]:
    if params is None:
        params = {}
    clean: Dict[str, Any] = {}
    for key, spec in params.items():
        spec = dict(spec or {})
        t = _PARAM_TYPES.get(spec.get("type", "string"), "string")
        new = {"type": t}
        if spec.get("description"):
            new["description"] = spec["description"]
        if spec.get("enum"):
            new["enum"] = spec["enum"]
        if t == "array":
            new["items"] = spec.get("items") or {"type": "string"}
        if "default" in spec:
            new["default"] = spec["default"]
        clean[key] = new
    schema = {
        "type": "object",
        "properties": clean,
        "required": list(required or []),
        "additionalProperties": False,
    }
    spec = {
        "name": name,
        "description": description,
        "parameters": schema,
        "category": category,
        "dangerous": dangerous,
        "confirm": confirm,
        "title": name,
    }

    def decorator(fn: Callable[..., Any]) -> Callable[..., Any]:
        @functools.wraps(fn)
        def wrapper(*args: Any, **kwargs: Any) -> Any:
            return fn(*args, **kwargs)

        wrapper.__wrapped_tool__ = {"fn": fn, "spec": spec}  # type: ignore[attr-defined]
        return wrapper

    return decorator
