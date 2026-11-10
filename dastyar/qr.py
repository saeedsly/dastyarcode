"""A tiny, dependency-free QR Code encoder (byte mode, versions 1-10, EC level M).

It is a deliberately compact implementation good enough for links, wifi
passwords and contact cards.  Output is an SVG string.

Based on the public-domain algorithm description in ISO/IEC 18004 (simplified).
"""
from __future__ import annotations

from typing import List, Tuple

# --- capacity table (bytes) for EC level M: version -> data codewords ----------
_DATA_CODEWORDS_M = {
    1: 16, 2: 28, 3: 44, 4: 64, 5: 86, 6: 108, 7: 124, 8: 154, 9: 182, 10: 216,
}
_EC_CODEWORDS_M = {
    1: 10, 2: 16, 3: 26, 4: 36, 5: 48, 6: 64, 7: 72, 8: 88, 9: 110, 10: 130,
}
# blocks per version (M): list of (count, data_per_block)
_BLOCKS_M = {
    1: [(1, 16)], 2: [(1, 28)], 3: [(1, 44)], 4: [(2, 32)], 5: [(2, 43)],
    6: [(4, 27)], 7: [(4, 31)], 8: [(2, 38), (2, 39)], 9: [(3, 36), (2, 37)],
    10: [(4, 43), (1, 44)],
}


def _gf_mul(x: int, y: int) -> int:
    z = 0
    for i in range(7, -1, -1):
        if (y >> i) & 1:
            z ^= x << i
    for i in range(z.bit_length() - 1, 7, -1):
        if (z >> i) & 1:
            z ^= 0x11D << (i - 8)
    return z & 0xFF


def _gf_pow(x: int, n: int) -> int:
    r = 1
    for _ in range(n):
        r = _gf_mul(r, x)
    return r


def _rs_generator(n: int) -> List[int]:
    g = [1]
    for i in range(n):
        new = [0] * (len(g) + 1)
        for j, coef in enumerate(g):
            new[j] ^= _gf_mul(coef, _gf_pow(2, i))
            new[j + 1] ^= coef
        g = new
    return g


def _rs_encode(data: List[int], ec_len: int) -> List[int]:
    gen = _rs_generator(ec_len)
    res = [0] * ec_len
    for byte in data:
        factor = byte ^ res[0]
        res = res[1:] + [0]
        for i, g in enumerate(gen[1:]):
            res[i] ^= _gf_mul(g, factor)
    return res


def _bits(value: int, length: int) -> List[int]:
    return [(value >> i) & 1 for i in range(length - 1, -1, -1)]


def _choose_version(n: int) -> int:
    for v in sorted(_DATA_CODEWORDS_M):
        if n + 4 <= _DATA_CODEWORDS_M[v]:
            return v
    raise ValueError("متن برای QR کد خیلی بلند است (حداکثر ~۲۰۰ کاراکتر).")


def _matrix_size(v: int) -> int:
    return 17 + 4 * v


def _alignment_positions(v: int) -> List[int]:
    if v == 1:
        return []
    if v <= 6:
        return [6, _matrix_size(v) - 7]
    step = 2 * ((v // 7) + 1)
    pos = [6]
    cur = _matrix_size(v) - 7
    while cur > 6:
        pos.insert(1, cur)
        cur -= step
    return sorted(pos)


def _format_bits(mask: int) -> List[int]:
    data = (0b00 << 3) | mask  # EC level M = 00
    rem = data << 10
    for _ in range(10):
        if rem.bit_length() >= 11 and (rem >> (rem.bit_length() - 11)) & 1:
            rem ^= 0b10100110111 << (rem.bit_length() - 11)
    fmt = ((data << 10) | rem) ^ 0b101010000010010
    return _bits(fmt, 15)


def _mask_fn(mask: int, r: int, c: int) -> bool:
    if mask == 0:
        return (r + c) % 2 == 0
    if mask == 1:
        return r % 2 == 0
    if mask == 2:
        return c % 3 == 0
    if mask == 3:
        return (r + c) % 3 == 0
    if mask == 4:
        return (r // 2 + c // 3) % 2 == 0
    if mask == 5:
        return ((r * c) % 2) + ((r * c) % 3) == 0
    if mask == 6:
        return (((r * c) % 2) + ((r * c) % 3)) % 2 == 0
    return (((r + c) % 2) + ((r * c) % 3)) % 2 == 0


def _build(text: str) -> List[List[bool]]:
    payload = text.encode("utf-8")
    version = _choose_version(len(payload))
    size = _matrix_size(version)
    total_data = _DATA_CODEWORDS_M[version]

    # --- bit stream ------------------------------------------------------
    stream: List[int] = _bits(0b0100, 4)  # byte mode
    stream += _bits(len(payload), 8 if version <= 9 else 16)
    for b in payload:
        stream += _bits(b, 8)
    capacity = total_data * 8
    terminator = min(4, capacity - len(stream))
    stream += [0] * terminator
    while len(stream) % 8:
        stream.append(0)
    codewords = [int("".join(map(str, stream[i:i + 8])), 2) for i in range(0, len(stream), 8)]
    pad = [0xEC, 0x11]
    i = 0
    while len(codewords) < total_data:
        codewords.append(pad[i % 2])
        i += 1

    # --- split into blocks & compute EC ---------------------------------
    blocks = _BLOCKS_M[version]
    data_blocks: List[List[int]] = []
    idx = 0
    for count, per in blocks:
        for _ in range(count):
            data_blocks.append(codewords[idx: idx + per])
            idx += per
    ec_per_block = _EC_CODEWORDS_M[version] // len(data_blocks)
    ec_blocks = [_rs_encode(b, ec_per_block) for b in data_blocks]

    final: List[int] = []
    max_len = max(len(b) for b in data_blocks)
    for i in range(max_len):
        for b in data_blocks:
            if i < len(b):
                final.append(b[i])
    for i in range(ec_per_block):
        for b in ec_blocks:
            final.append(b[i])

    bits: List[int] = []
    for cw in final:
        bits += _bits(cw, 8)

    # --- place modules ---------------------------------------------------
    matrix = [[False] * size for _ in range(size)]
    reserved = [[False] * size for _ in range(size)]

    def finder(r0: int, c0: int) -> None:
        for dr in range(-1, 8):
            for dc in range(-1, 8):
                r, c = r0 + dr, c0 + dc
                if 0 <= r < size and 0 <= c < size:
                    dark = (0 <= dr <= 6 and 0 <= dc <= 6 and
                            (dr in (0, 6) or dc in (0, 6) or (2 <= dr <= 4 and 2 <= dc <= 4)))
                    matrix[r][c] = dark
                    reserved[r][c] = True

    finder(0, 0)
    finder(0, size - 7)
    finder(size - 7, 0)

    # timing
    for i in range(8, size - 8):
        dark = i % 2 == 0
        matrix[6][i] = dark
        reserved[6][i] = True
        matrix[i][6] = dark
        reserved[i][6] = True

    # alignment
    for ar in _alignment_positions(version):
        for ac in _alignment_positions(version):
            if (ar < 8 and ac < 8) or (ar < 8 and ac > size - 9) or (ar > size - 9 and ac < 8):
                continue
            for dr in range(-2, 3):
                for dc in range(-2, 3):
                    r, c = ar + dr, ac + dc
                    dark = max(abs(dr), abs(dc)) in (0, 2)
                    matrix[r][c] = dark
                    reserved[r][c] = True

    # reserve format areas
    for i in range(9):
        if not reserved[8][i]:
            reserved[8][i] = True
        if not reserved[i][8]:
            reserved[i][8] = True
    for i in range(8):
        reserved[8][size - 1 - i] = True
        reserved[size - 1 - i][8] = True

    # dark module
    matrix[size - 8][8] = True
    reserved[size - 8][8] = True

    # data placement, right columns, zig-zag upward
    bit_idx = 0
    col = size - 1
    upward = True
    while col > 0:
        if col == 6:
            col -= 1
        rows = range(size - 1, -1, -1) if upward else range(size)
        for row in rows:
            for c in (col, col - 1):
                if not reserved[row][c]:
                    bit = bits[bit_idx] if bit_idx < len(bits) else 0
                    matrix[row][c] = bool(bit)
                    bit_idx += 1
        upward = not upward
        col -= 2

    # --- choose best mask ------------------------------------------------
    def apply_mask(m: int) -> List[List[bool]]:
        out = [row[:] for row in matrix]
        for r in range(size):
            for c in range(size):
                if not reserved[r][c] and _mask_fn(m, r, c):
                    out[r][c] = not out[r][c]
        return out

    def penalty(mat: List[List[bool]]) -> int:
        score = 0
        for mat2 in (mat, [list(x) for x in zip(*mat)]):
            for row in mat2:
                run = 1
                for i in range(1, len(row)):
                    if row[i] == row[i - 1]:
                        run += 1
                    else:
                        if run >= 5:
                            score += 3 + (run - 5)
                        run = 1
                if run >= 5:
                    score += 3 + (run - 5)
        return score

    best = None
    best_score = None
    for m in range(8):
        cand = apply_mask(m)
        sc = penalty(cand)
        if best_score is None or sc < best_score:
            best, best_score, best_mask = cand, sc, m

    # --- write format info ----------------------------------------------
    fmt = _format_bits(best_mask)
    positions_1 = [(8, i) for i in range(6)] + [(8, 7), (8, 8), (7, 8)] + [(i, 8) for i in range(5, -1, -1)]
    for (r, c), bit in zip(positions_1, fmt):
        best[r][c] = bool(bit)
    positions_2 = [(size - 1 - i, 8) for i in range(7)] + [(8, size - 8 + i) for i in range(8)]
    for (r, c), bit in zip(positions_2, fmt):
        if 0 <= r < size and 0 <= c < size:
            best[r][c] = bool(bit)
    return best


def make_qr_svg(text: str, size: int = 320, dark: str = "#0f172a", light: str = "#ffffff") -> str:
    matrix = _build(text or " ")
    n = len(matrix)
    rects: List[str] = []
    for r, row in enumerate(matrix):
        for c, val in enumerate(row):
            if val:
                # merge horizontal runs to keep the SVG small
                run = 1
                while c + run < n and row[c + run]:
                    run += 1
                rects.append('<rect x="%d" y="%d" width="%d" height="1"/>' % (c, r, run))
                for k in range(1, run):
                    row[c + k] = False
    quiet = 4
    view = n + quiet * 2
    return (
        '<svg xmlns="http://www.w3.org/2000/svg" width="%d" height="%d" '
        'viewBox="0 0 %d %d" shape-rendering="crispEdges">'
        '<rect width="100%%" height="100%%" fill="%s"/>'
        '<g fill="%s" transform="translate(%d,%d)">%s</g></svg>'
        % (size, size, view, view, light, dark, quiet, quiet, "".join(rects))
    )
