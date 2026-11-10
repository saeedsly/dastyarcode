"""Persian/Arabic text layout + PDF writing, dependency free.

Why this exists: a plain PDF writes Persian letters left-to-right without
joining, which looks broken.  This module

1. converts Arabic/Persian letters to their *presentation forms* (connected
   shapes) using the standard joining rules, handling lam-alef ligatures and
   ZWNJ,
2. reorders RTL runs into visual order (small built-in bidi), so every viewer
   shows correct Persian without needing a shaping engine,
3. embeds a Persian-capable TrueType font (Tahoma / DejaVu / Noto / Kacst /
   Arial Unicode) as a CID font and writes glyph ids.

The result: a small, valid PDF that looks right in Windows 10/11, Adobe
Reader, Chrome, and every phone.
"""
from __future__ import annotations

import os
import struct
import sys
import zlib
from pathlib import Path
from typing import Dict, List, Optional, Sequence, Tuple

# --------------------------------------------------------------------------- #
# 1. font loading
# --------------------------------------------------------------------------- #


def font_candidates() -> List[Path]:
    out: List[Path] = []
    win = os.environ.get("WINDIR") or os.environ.get("SystemRoot") or r"C:\Windows"
    out += [Path(win) / "Fonts" / f for f in ("tahoma.ttf", "segoeui.ttf", "arial.ttf")]
    out += [
        Path("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"),
        Path("/usr/share/fonts/truetype/noto/NotoNaskhArabic-Regular.ttf"),
        Path("/usr/share/fonts/truetype/freefont/FreeSerif.ttf"),
        Path("/usr/share/fonts/truetype/kacst/KacstOne.ttf"),
        Path("/usr/share/fonts/truetype/liberation/LiberationSans-Regular.ttf"),
        Path("/System/Library/Fonts/Supplemental/Tahoma.ttf"),
        Path("/Library/Fonts/Arial Unicode.ttf"),
    ]
    # the bundled Vazirmatn is a proper Persian font: prefer it over system
    # fonts.  Try every plausible location (source tree, PyInstaller onedir /
    # onefile, zip-import) before falling back to the OS.
    roots = [
        Path(__file__).resolve().parent.parent / "assets",
        Path(getattr(sys, "_MEIPASS", "")) / "dastyar" / "assets",
        Path(getattr(sys, "executable", "")).resolve().parent / "dastyar" / "assets",
        Path(getattr(sys, "executable", "")).resolve().parent / "_internal" / "dastyar" / "assets",
    ]
    for bundled in roots:
        try:
            if bundled.is_dir():
                ttfs = list(bundled.glob("*.ttf"))
                # body text should be the Regular weight, not Bold
                ttfs.sort(key=lambda p: (0 if "regular" in p.name.lower() else
                                         1 if "bold" in p.name.lower() else 2, p.name))
                if ttfs:
                    out = ttfs + out
                    break
        except OSError:
            continue
    return [p for p in out if p.exists() and p.stat().st_size < 20 * 1024 * 1024]


class TrueType:
    def __init__(self, path: Path):
        self.path = Path(path)
        self.data = self.path.read_bytes()
        self.tables = self._read_tables()
        head = self.tables["head"][0]
        self.units_per_em = struct.unpack(">H", self.data[head + 18:head + 20])[0] or 1000
        self.bbox = struct.unpack(">hhhh", self.data[head + 36:head + 44])
        hhea = self.tables["hhea"][0]
        self.ascent, self.descent = struct.unpack(">hh", self.data[hhea + 4:hhea + 8])
        self.num_hmetrics = struct.unpack(">H", self.data[hhea + 34:hhea + 36])[0]
        maxp = self.tables["maxp"][0]
        self.num_glyphs = struct.unpack(">H", self.data[maxp + 4:maxp + 6])[0]
        self.cmap = self._read_cmap()
        self.advances = self._read_advances()
        self.name = self._read_name()

    # -- helpers -------------------------------------------------------
    def _read_tables(self) -> Dict[str, Tuple[int, int]]:
        data = self.data
        num = struct.unpack(">H", data[4:6])[0]
        out = {}
        for i in range(num):
            off = 12 + i * 16
            tag = data[off:off + 4].decode("latin-1").strip()
            _, offset, length = struct.unpack(">III", data[off + 4:off + 16])
            out[tag] = (offset, length)
        return out

    def _read_name(self) -> str:
        loc = self.tables.get("name")
        if not loc:
            return "DastyarFont"
        base, _ = loc
        try:
            count, string_off = struct.unpack(">HH", self.data[base + 2:base + 6])
            for i in range(count):
                rec = base + 6 + i * 12
                pid, eid, lid, nid, ln, off = struct.unpack(">HHHHHH", self.data[rec:rec + 12])
                if nid == 6:
                    raw = self.data[base + string_off + off: base + string_off + off + ln]
                    name = raw.decode("utf-16-be") if pid in (0, 3) else raw.decode("latin-1")
                    clean = "".join(ch for ch in name if ch.isalnum())
                    if clean:
                        return clean[:32]
        except Exception:
            pass
        return "DastyarFont"

    def _read_advances(self) -> List[int]:
        off, _ = self.tables["hmtx"]
        out = []
        last = self.units_per_em // 2
        for i in range(self.num_glyphs):
            if i < self.num_hmetrics:
                addr = off + i * 4
                last = struct.unpack(">H", self.data[addr:addr + 2])[0]
            out.append(last)
        return out

    def _read_cmap(self) -> Dict[int, int]:
        data = self.data
        out: Dict[int, int] = {}
        loc = self.tables.get("cmap")
        if not loc:
            return out
        base, _ = loc
        num = struct.unpack(">H", data[base + 2:base + 4])[0]
        chosen = None
        for i in range(num):
            rec = base + 4 + i * 8
            platform, encoding, offset = struct.unpack(">HHI", data[rec:rec + 8])
            sub = base + offset
            fmt = struct.unpack(">H", data[sub:sub + 2])[0]
            if fmt == 12 and platform in (0, 3):
                chosen = (12, sub)
                break
            if fmt == 4 and (platform, encoding) in ((3, 1), (3, 0), (0, 3), (0, 4), (0, 2), (0, 1)):
                chosen = chosen or (4, sub)
        if not chosen:
            return out
        fmt, sub = chosen
        try:
            if fmt == 4:
                segx2 = struct.unpack(">H", data[sub + 6:sub + 8])[0]
                seg = segx2 // 2
                ends = struct.unpack(">%dH" % seg, data[sub + 14:sub + 14 + segx2])
                starts_off = sub + 14 + segx2 + 2
                starts = struct.unpack(">%dH" % seg, data[starts_off:starts_off + segx2])
                deltas_off = starts_off + segx2
                deltas = struct.unpack(">%dh" % seg, data[deltas_off:deltas_off + segx2])
                range_off = deltas_off + segx2
                ranges = struct.unpack(">%dH" % seg, data[range_off:range_off + segx2])
                for i in range(seg):
                    if starts[i] == 0xFFFF:
                        continue
                    for cp in range(starts[i], min(ends[i], 0xFFFE) + 1):
                        if ranges[i] == 0:
                            gid = (cp + deltas[i]) & 0xFFFF
                        else:
                            addr = range_off + i * 2 + ranges[i] + (cp - starts[i]) * 2
                            if addr + 2 > len(data):
                                continue
                            gid = struct.unpack(">H", data[addr:addr + 2])[0]
                            if gid:
                                gid = (gid + deltas[i]) & 0xFFFF
                        if gid:
                            out[cp] = gid
            else:
                ngroups = struct.unpack(">I", data[sub + 12:sub + 16])[0]
                for i in range(min(ngroups, 40000)):
                    g = sub + 16 + i * 12
                    start, end, gid = struct.unpack(">III", data[g:g + 12])
                    for cp in range(start, min(end, 0x2FFFF) + 1):
                        out[cp] = gid + (cp - start)
        except Exception:
            return out
        return out

    def gid(self, ch: str) -> int:
        return self.cmap.get(ord(ch), 0)

    def gid_any(self, *codepoints: int) -> int:
        """First glyph id that exists for any of the given codepoints."""
        for cp in codepoints:
            gid = self.cmap.get(cp)
            if gid and gid < len(self.advances) and self.advances[gid] > 0:
                return gid
        return 0

    def width(self, ch: str) -> int:
        g = self.gid(ch)
        return self.advances[g] if 0 <= g < len(self.advances) else self.units_per_em // 2


# --------------------------------------------------------------------------- #
# 2. Persian shaping
# --------------------------------------------------------------------------- #

# char: (isolated, final, initial, medial) presentation forms; None = not applicable
FORMS: Dict[str, Tuple[Optional[int], Optional[int], Optional[int], Optional[int]]] = {
    "ء": (0xFE80, None, None, None),
    "آ": (0xFE81, 0xFE82, None, None),
    "أ": (0xFE83, 0xFE84, None, None),
    "ؤ": (0xFE85, 0xFE86, None, None),
    "إ": (0xFE87, 0xFE88, None, None),
    "ئ": (0xFE89, 0xFE8A, 0xFE8B, 0xFE8C),
    "ا": (0xFE8D, 0xFE8E, None, None),
    "ب": (0xFE8F, 0xFE90, 0xFE91, 0xFE92),
    "ة": (0xFE93, 0xFE94, None, None),
    "ت": (0xFE95, 0xFE96, 0xFE97, 0xFE98),
    "ث": (0xFE99, 0xFE9A, 0xFE9B, 0xFE9C),
    "ج": (0xFE9D, 0xFE9E, 0xFE9F, 0xFEA0),
    "ح": (0xFEA1, 0xFEA2, 0xFEA3, 0xFEA4),
    "خ": (0xFEA5, 0xFEA6, 0xFEA7, 0xFEA8),
    "د": (0xFEA9, 0xFEAA, None, None),
    "ذ": (0xFEAB, 0xFEAC, None, None),
    "ر": (0xFEAD, 0xFEAE, None, None),
    "ز": (0xFEAF, 0xFEB0, None, None),
    "س": (0xFEB1, 0xFEB2, 0xFEB3, 0xFEB4),
    "ش": (0xFEB5, 0xFEB6, 0xFEB7, 0xFEB8),
    "ص": (0xFEB9, 0xFEBA, 0xFEBB, 0xFEBC),
    "ض": (0xFEBD, 0xFEBE, 0xFEBF, 0xFEC0),
    "ط": (0xFEC1, 0xFEC2, 0xFEC3, 0xFEC4),
    "ظ": (0xFEC5, 0xFEC6, 0xFEC7, 0xFEC8),
    "ع": (0xFEC9, 0xFECA, 0xFECB, 0xFECC),
    "غ": (0xFECD, 0xFECE, 0xFECF, 0xFED0),
    "ف": (0xFED1, 0xFED2, 0xFED3, 0xFED4),
    "ق": (0xFED5, 0xFED6, 0xFED7, 0xFED8),
    "ك": (0xFED9, 0xFEDA, 0xFEDB, 0xFEDC),
    "ک": (0xFB8E, 0xFB8F, 0xFB90, 0xFB91),
    "ل": (0xFEDD, 0xFEDE, 0xFEDF, 0xFEE0),
    "م": (0xFEE1, 0xFEE2, 0xFEE3, 0xFEE4),
    "ن": (0xFEE5, 0xFEE6, 0xFEE7, 0xFEE8),
    "ه": (0xFEE9, 0xFEEA, 0xFEEB, 0xFEEC),
    "و": (0xFEED, 0xFEEE, None, None),
    "ى": (0xFEEF, 0xFEF0, None, None),
    "ي": (0xFEF1, 0xFEF2, 0xFEF3, 0xFEF4),
    "ی": (0xFBFC, 0xFBFD, 0xFBFE, 0xFBFF),
    "پ": (0xFB56, 0xFB57, 0xFB58, 0xFB59),
    "چ": (0xFB7A, 0xFB7B, 0xFB7C, 0xFB7D),
    "ژ": (0xFB8A, 0xFB8B, None, None),
    "گ": (0xFB92, 0xFB93, 0xFB94, 0xFB95),
    "ۀ": (0xFB90, 0xFB91, None, None),
}

LIGATURES = {
    ("ل", "ا"): (0xFEFB, 0xFEFC),
    ("ل", "آ"): (0xFEF5, 0xFEF6),
    ("ل", "أ"): (0xFEF7, 0xFEF8),
    ("ل", "إ"): (0xFEF9, 0xFEFA),
}

DIACRITICS = set(
    "\u064b\u064c\u064d\u064e\u064f\u0650\u0651\u0652\u0653\u0654\u0655\u0670"
    "\u200f\u200e\ufeff\u061c"
)
ZWNJ = "\u200c\u200d"
NORMALIZE = {"\u064a": "\u06cc", "\u0643": "\u06a9", "\u0629": "\u0629", "\u0649": "\u06cc"}


def _can_join_prev(ch: Optional[str]) -> bool:
    """Does ``ch`` connect to the following letter (i.e. has initial/medial)?"""
    if not ch:
        return False
    forms = FORMS.get(ch)
    return bool(forms and forms[2] is not None)


def _can_join_next(ch: Optional[str]) -> bool:
    """Does ``ch`` connect to the previous letter (i.e. has final form)?"""
    if not ch:
        return False
    forms = FORMS.get(ch)
    return bool(forms and forms[1] is not None)


def shape_arabic(text: str) -> str:
    """Return presentation-form characters (still in logical order)."""
    # normalise + strip diacritics (kept visible? they are non-joining marks)
    chars: List[str] = []
    for ch in text:
        ch = NORMALIZE.get(ch, ch)
        if ch in DIACRITICS:
            continue
        chars.append(ch)

    out: List[str] = []
    i = 0
    while i < len(chars):
        ch = chars[i]
        if ch not in FORMS:
            out.append(ch)
            i += 1
            continue

        # lam + alef ligature
        if ch == "ل" and i + 1 < len(chars) and (ch, chars[i + 1]) in LIGATURES:
            iso, fin = LIGATURES[(ch, chars[i + 1])]
            prev = chars[i - 1] if i > 0 else None
            out.append(chr(fin if _can_join_prev(prev) else iso))
            i += 2
            continue

        prev = chars[i - 1] if i > 0 else None
        nxt = chars[i + 1] if i + 1 < len(chars) else None
        # ZWNJ / spaces break joining
        joins_prev = _can_join_prev(prev) and prev not in ZWNJ
        joins_next = _can_join_next(nxt) and nxt not in ZWNJ
        iso, fin, ini, med = FORMS[ch]
        if joins_prev and joins_next and med:
            code = med
        elif joins_prev and fin:
            code = fin
        elif joins_next and ini:
            code = ini
        else:
            code = iso
        out.append(chr(code) if code else ch)
        i += 1
    return "".join(out)


RTL_RANGES = [(0x0590, 0x08FF), (0xFB1D, 0xFDFF), (0xFE70, 0xFEFF)]


DIGITS = set("0123456789\u06f0\u06f1\u06f2\u06f3\u06f4\u06f5\u06f6\u06f7\u06f8\u06f9")


def is_rtl_char(ch: str) -> bool:
    if ch.isdigit():
        return False          # numbers keep their own order inside RTL text
    cp = ord(ch)
    return any(a <= cp <= b for a, b in RTL_RANGES)


def _is_neutral(ch: str) -> bool:
    return not ch.isalnum() and ch not in DIGITS


def visual_order(line: str) -> Tuple[str, bool]:
    """Reorder a logical line for painting LTR.  Returns (text, is_rtl_para)."""
    if not line:
        return "", False
    first_strong = next((c for c in line if c.isalpha()), "")
    rtl_para = is_rtl_char(first_strong)

    # split into runs of the same direction; neutrals stick to neighbours
    runs: List[Tuple[bool, List[str]]] = []
    for ch in line:
        if _is_neutral(ch):
            kind = runs[-1][0] if runs else rtl_para
        else:
            kind = is_rtl_char(ch)
        if runs and runs[-1][0] == kind:
            runs[-1][1].append(ch)
        else:
            runs.append((kind, [ch]))

    # merge single-space runs between same-direction runs
    merged: List[Tuple[bool, List[str]]] = []
    for kind, chars in runs:
        if (len(chars) <= 2 and all(_is_neutral(c) for c in chars)
                and merged and len(merged) >= 1):
            merged[-1][1].extend(chars)
        else:
            merged.append((kind, chars))

    # inside a run: RTL text is shaped + reversed, LTR text stays as-is;
    # the runs themselves are placed right-to-left for RTL paragraphs.
    runs_visual: List[str] = []
    for kind, chars in merged:
        s = "".join(chars)
        runs_visual.append(shape_arabic(s)[::-1] if kind else s)
    if rtl_para:
        runs_visual.reverse()
    return "".join(runs_visual), rtl_para


# --------------------------------------------------------------------------- #
# 3. PDF writing
# --------------------------------------------------------------------------- #

PAGE_W, PAGE_H = 595, 842
MARGIN_L, MARGIN_R, MARGIN_T, MARGIN_B = 62, 62, 70, 64


class PdfBuilder:
    def __init__(self, font: Optional[TrueType] = None):
        self.font = font
        self.objects: List[bytes] = []

    # -- object helpers ------------------------------------------------
    def add(self, body: bytes) -> int:
        self.objects.append(body)
        return len(self.objects)

    def stream(self, payload: bytes, extra: str = "") -> int:
        comp = zlib.compress(payload, 6)
        body = ("<< /Length %d /Filter /FlateDecode %s>>\nstream\n"
                % (len(comp), extra)).encode("latin-1") + comp + b"\nendstream"
        return self.add(body)

    # -- fonts ---------------------------------------------------------
    def embed_font(self) -> Tuple[int, Dict[int, int]]:
        """Embed the TTF; return (font object number, gid->codepoint map)."""
        assert self.font is not None
        f = self.font
        file_num = self.stream(f.data, "/Length1 %d " % len(f.data))
        scale = 1000.0 / f.units_per_em
        xmin, ymin, xmax, ymax = (int(v * scale) for v in f.bbox)
        descriptor = (
            "<< /Type /FontDescriptor /FontName /%s /Flags 4 "
            "/FontBBox [%d %d %d %d] /ItalicAngle 0 /Ascent %d /Descent %d "
            "/CapHeight %d /StemV 80 /FontFile2 %d 0 R >>"
            % (f.name, xmin, ymin, xmax, ymax, int(f.ascent * scale),
               int(f.descent * scale), int(f.ascent * scale), file_num)
        )
        desc_num = self.add(descriptor.encode("latin-1"))

        used = sorted(set(f.cmap.values()))
        w_parts = ["[%d [%d]]" % (g, int(f.advances[g] * scale)) for g in used if g < len(f.advances)]
        cid_font = (
            "<< /Type /Font /Subtype /CIDFontType2 /BaseFont /%s "
            "/CIDSystemInfo << /Registry (Adobe) /Ordering (Identity) /Supplement 0 >> "
            "/FontDescriptor %d 0 R /DW 1000 /W [%s] /CIDToGIDMap /Identity >>"
            % (f.name, desc_num, " ".join(w_parts[:4000]))
        )
        cid_num = self.add(cid_font.encode("latin-1"))

        # ToUnicode from the cmap (glyph id -> unicode)
        inv = {}
        for cp, gid in f.cmap.items():
            inv.setdefault(gid, cp)
        lines = [
            "/CIDInit /ProcSet findresource begin", "12 dict begin", "begincmap",
            "/CIDSystemInfo << /Registry (Adobe) /Ordering (UCS) /Supplement 0 >> def",
            "/CMapName /Adobe-Identity-UCS def", "/CMapType 2 def",
            "1 begincodespacerange", "<0000> <FFFF>", "endcodespacerange",
        ]
        items = ["<%04X> <%04X>" % (gid, cp) for gid, cp in sorted(inv.items())[:4000]]
        for i in range(0, len(items), 100):
            chunk = items[i:i + 100]
            lines.append("%d beginbfchar" % len(chunk))
            lines += chunk
            lines.append("endbfchar")
        lines += ["endcmap", "CMapName currentdict /CMap defineresource pop", "end", "end"]
        to_unicode_num = self.stream("\n".join(lines).encode("latin-1"))

        type0 = (
            "<< /Type /Font /Subtype /Type0 /BaseFont /%s /Encoding /Identity-H "
            "/DescendantFonts [%d 0 R] /ToUnicode %d 0 R >>"
            % (f.name, cid_num, to_unicode_num)
        )
        font_num = self.add(type0.encode("latin-1"))
        return font_num, inv

    # -- text ----------------------------------------------------------
    def text_width(self, text: str, size: float) -> float:
        if not self.font:
            return len(text) * size * 0.5
        total = sum(self.font.width(ch) for ch in text)
        return total * size / self.font.units_per_em

    def wrap(self, text: str, size: float, max_width: float) -> List[str]:
        out: List[str] = []
        for raw in (text or "").splitlines():
            if not raw:
                out.append("")
                continue
            words = raw.split(" ")
            cur = ""
            for w in words:
                cand = (cur + " " + w) if cur else w
                if self.text_width(cand, size) <= max_width or not cur:
                    cur = cand
                else:
                    out.append(cur)
                    cur = w
            out.append(cur)
        return out

    def render_text(self, text: str, font_num: int, size: float, x: float, y: float) -> bytes:
        """Draw one line; every glyph is positioned explicitly (robust in all viewers)."""
        if not self.font:
            safe = text.encode("latin-1", "replace").decode("latin-1")
            esc = safe.replace("\\", r"\\").replace("(", r"\(").replace(")", r"\)")
            return ("BT /F1 %.1f Tf 1 0 0 1 %.1f %.1f Tm (%s) Tj ET\n"
                    % (size, x, y, esc)).encode("latin-1")
        out = ["BT", "/F1 %.2f Tf" % size, "1 0 0 1 %.2f %.2f Tm" % (x, y)]
        upem = float(self.font.units_per_em)
        for ch in text:
            gid = self.font.gid(ch)
            if not gid or gid >= len(self.font.advances):
                gid = self.font.gid_any(0x20, 0x41)
                if not gid:
                    continue
            width = self.font.advances[gid] * size / upem
            out.append("<%04X> Tj" % gid)
            if width > 0:
                out.append("%.2f 0 Td" % width)
        out.append("ET")
        return ("\n".join(out) + "\n").encode("latin-1")

    def text_width_glyphs(self, text: str, size: float) -> float:
        if not self.font:
            return len(text) * size * 0.5
        upem = float(self.font.units_per_em)
        total = 0.0
        for ch in text:
            gid = self.font.gid(ch) or self.font.gid_any(0x20)
            if 0 <= gid < len(self.font.advances):
                total += self.font.advances[gid] * size / upem
        return total

    # -- document ------------------------------------------------------
    def build(self, lines: Sequence[str], title: str = "", size: float = 12.0,
              leading: float = 20.0) -> bytes:
        usable = PAGE_W - MARGIN_L - MARGIN_R
        font_num = 0
        if self.font:
            font_num, _ = self.embed_font()
            # reserve the placeholder for the fallback Helvetica pair
        helv1 = self.add(b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica "
                         b"/Encoding /WinAnsiEncoding >>")
        helv2 = self.add(b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica-Bold "
                         b"/Encoding /WinAnsiEncoding >>")
        font_refs = (f"/F1 %d 0 R /F2 %d 0 R" % (font_num, helv2) if self.font
                     else "/F1 %d 0 R /F2 %d 0 R" % (helv1, helv2))

        wrapped: List[Tuple[str, bool]] = []
        if title:
            wrapped.append(("TITLE", True))
        for ln in lines:
            for piece in self.wrap(ln, size, usable):
                wrapped.append((piece, False))

        per_page = int((PAGE_H - MARGIN_T - MARGIN_B) / leading)
        pages = [wrapped[i:i + per_page] for i in range(0, max(1, len(wrapped)), per_page)] or [[]]

        page_objects: List[int] = []
        content_nums: List[int] = []
        for page in pages:
            ops = b""
            y = PAGE_H - MARGIN_T
            for text, is_title in page:
                if is_title:
                    vis, rtl = visual_order(title)
                    w = self.text_width(vis, size + 6)
                    x = (PAGE_W - w) / 2 if rtl else MARGIN_L
                    ops += self.render_text(vis, font_num, size + 6, x, y)
                    y -= leading * 1.9
                    continue
                vis, rtl = visual_order(text)
                w = self.text_width(vis, size)
                x = (PAGE_W - MARGIN_R - w) if rtl else MARGIN_L
                ops += self.render_text(vis, font_num, size, x, y)
                y -= leading
            content_nums.append(self.stream(ops))

        # pages need the /Pages number, which we only know at the end -> placeholder
        pages_num_placeholder = len(self.objects) + 2 * len(content_nums) + 1
        for cnum in content_nums:
            page_objects.append(self.add(
                ("<< /Type /Page /Parent %d 0 R /MediaBox [0 0 %d %d] "
                 "/Resources << /Font << %s >> >> /Contents %d 0 R >>"
                 % (pages_num_placeholder, PAGE_W, PAGE_H, font_refs, cnum)).encode("latin-1")))
        pages_num = self.add(
            ("<< /Type /Pages /Count %d /Kids [%s] >>"
             % (len(page_objects), " ".join("%d 0 R" % p for p in page_objects))).encode("latin-1"))
        if pages_num != pages_num_placeholder:  # fix the parent refs
            for p in page_objects:
                self.objects[p - 1] = self.objects[p - 1].replace(
                    b"/Parent %d 0 R" % pages_num_placeholder, b"/Parent %d 0 R" % pages_num)
        catalog = self.add(("<< /Type /Catalog /Pages %d 0 R >>" % pages_num).encode("latin-1"))

        out = bytearray(b"%PDF-1.4\n%\xe2\xe3\xcf\xd3\n")
        offsets: List[int] = []
        for i, body in enumerate(self.objects, 1):
            offsets.append(len(out))
            out += b"%d 0 obj\n" % i + body + b"\nendobj\n"
        xref = len(out)
        out += b"xref\n0 %d\n0000000000 65535 f \n" % (len(self.objects) + 1)
        for off in offsets:
            out += b"%010d 00000 n \n" % off
        out += (b"trailer\n<< /Size %d /Root %d 0 R >>\nstartxref\n%d\n%%%%EOF\n"
                % (len(self.objects) + 1, catalog, xref))
        return bytes(out)


def build_pdf(lines: Sequence[str], title: str = "", font_path: Optional[Path] = None) -> bytes:
    """Create a ready-to-save PDF from plain lines."""
    font: Optional[TrueType] = None
    try:
        path = Path(font_path) if font_path else next(iter(font_candidates()), None)
        if path is not None:
            font = TrueType(path)
    except Exception:
        font = None
    return PdfBuilder(font).build(list(lines), title)
