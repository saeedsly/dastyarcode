"""API-key protection.

On Windows the key is encrypted with DPAPI (CryptProtectData) so it can only
be read by the same Windows user on the same machine.  Elsewhere we fall back
to a reversible obfuscation (the key is still chmod 600 on the config file).

No third-party dependency, no network call, works on Windows XP..11.
"""
from __future__ import annotations

import base64
import os
import sys

_PREFIX_DPAPI = "dpapi:"
_PREFIX_OBF = "b64:"

try:  # Windows-only DPAPI binding
    import ctypes
    from ctypes import wintypes

    class _DATA_BLOB(ctypes.Structure):
        _fields_ = [("cbData", wintypes.DWORD), ("pbData", ctypes.POINTER(ctypes.c_char))]

    _crypt32 = ctypes.windll.crypt32  # type: ignore[attr-defined]
    _kernel32 = ctypes.windll.kernel32  # type: ignore[attr-defined]

    def _blob(data: bytes) -> _DATA_BLOB:
        buf = ctypes.create_string_buffer(data, len(data))
        return _DATA_BLOB(len(data), ctypes.cast(buf, ctypes.POINTER(ctypes.c_char)))

    def _to_bytes(blob: _DATA_BLOB) -> bytes:
        return ctypes.string_at(blob.pbData, blob.cbData)

    def _dpapi_encrypt(text: str) -> bytes:
        src = _blob(text.encode("utf-8"))
        out = _DATA_BLOB()
        ok = _crypt32.CryptProtectData(
            ctypes.byref(src), "dastyar", None, None, None, 0, ctypes.byref(out)
        )
        if not ok:
            raise OSError("CryptProtectData failed")
        try:
            return _to_bytes(out)
        finally:
            _kernel32.LocalFree(out.pbData)

    def _dpapi_decrypt(data: bytes) -> str:
        src = _blob(data)
        out = _DATA_BLOB()
        ok = _crypt32.CryptUnprotectData(
            ctypes.byref(src), None, None, None, None, 0, ctypes.byref(out)
        )
        if not ok:
            raise OSError("CryptUnprotectData failed")
        try:
            return _to_bytes(out).decode("utf-8")
        finally:
            _kernel32.LocalFree(out.pbData)

    _HAS_DPAPI = sys.platform == "win32"
except Exception:  # pragma: no cover - non-Windows
    _HAS_DPAPI = False


def _machine_mask() -> bytes:
    seed = "dastyar::local::" + (os.environ.get("COMPUTERNAME") or "host") + "::" + os.environ.get(
        "USERNAME", os.environ.get("USER", "user")
    )
    return (seed * 4).encode("utf-8")


def _xor(data: bytes) -> bytes:
    mask = _machine_mask()
    return bytes(b ^ mask[i % len(mask)] for i, b in enumerate(data))


def protect(plain: str) -> str:
    """Encrypt/obfuscate an API key for storage in config.json."""
    if not plain:
        return ""
    if plain.startswith(_PREFIX_DPAPI) or plain.startswith(_PREFIX_OBF):
        return plain  # already stored
    if _HAS_DPAPI:
        try:
            return _PREFIX_DPAPI + base64.b64encode(_dpapi_encrypt(plain)).decode("ascii")
        except Exception:
            pass
    return _PREFIX_OBF + base64.b64encode(_xor(plain.encode("utf-8"))).decode("ascii")


def unprotect(stored: str) -> str:
    """Return the real key from whatever was stored (also accepts plain keys)."""
    if not stored:
        return ""
    try:
        if stored.startswith(_PREFIX_DPAPI):
            if _HAS_DPAPI:
                return _dpapi_decrypt(base64.b64decode(stored[len(_PREFIX_DPAPI) :]))
            return ""
        if stored.startswith(_PREFIX_OBF):
            return _xor(base64.b64decode(stored[len(_PREFIX_OBF) :])).decode("utf-8")
    except Exception:
        return ""
    return stored  # legacy plain-text key


def masked(stored: str) -> str:
    key = unprotect(stored)
    if not key:
        return ""
    if len(key) <= 8:
        return "•" * len(key)
    return key[:3] + "•" * 6 + key[-4:]
