"""Tabelas sem grade (alinhadas só pelo texto) e fichas de criatura.

Em livros de RPG as tabelas quase nunca têm linhas desenhadas: são linhas de
texto alinhadas em colunas, às vezes com fundo sombreado alternado. O PyMuPDF
entrega cada célula como uma "linha" separada na mesma altura, então a tabela
é reconstruída agrupando os pedaços por altura (linhas da tabela) e por
posição horizontal (colunas).
"""
from __future__ import annotations

import math
import re
from dataclasses import dataclass, field

# Abreviações de características (CoC 7e em português e inglês, D&D).
STAT_ABBR = [
    "FOR", "CON", "TAM", "DES", "INT", "POD", "APA", "EDU", "SAN", "PV", "PM", "MOV",
    "SOR", "Sorte", "BD", "Corpo",
    "STR", "SIZ", "DEX", "POW", "APP", "HP", "MP", "Luck", "DB", "Build",
    "WIS", "CHA",
]
_ABBR = "|".join(sorted(STAT_ABBR, key=len, reverse=True))
_VALUE = r"(?:[—–-]|[+−–-]?\d+(?:[.,]\d+)?%?(?:\s*\([+−–-]?\d+\))?)"
PAIR_RE = re.compile(rf"(?<![\w])({_ABBR})\s*:?\s*({_VALUE})(?![\w])")
ABBR_RE = re.compile(rf"^(?:{_ABBR})$")
VALUE_RE = re.compile(rf"^{_VALUE}$")


@dataclass
class Table:
    rows: list[list[str]]
    th_rows: frozenset = frozenset({0})     # índices das linhas de cabeçalho


@dataclass
class _Cell:
    x0: float
    y0: float
    x1: float
    y1: float
    text: str
    bold: bool


@dataclass
class _Row:
    cells: list[_Cell]
    refs: set = field(default_factory=set)   # (índice do bloco, índice da linha)

    @property
    def y0(self):
        return min(c.y0 for c in self.cells)

    @property
    def y1(self):
        return max(c.y1 for c in self.cells)

    @property
    def x0(self):
        return min(c.x0 for c in self.cells)

    @property
    def x1(self):
        return max(c.x1 for c in self.cells)

    @property
    def h(self):
        return max(1.0, self.y1 - self.y0)


# --------------------------------------------------------------------------- #
# Fichas: "FOR 80 CON 65 ..." num parágrafo comum
# --------------------------------------------------------------------------- #
def stat_table_from_text(text: str) -> Table | None:
    """Converte uma linha de características em tabela, se for uma."""
    t = re.sub(r"\s+", " ", text).strip()
    if not t:
        return None
    pairs = PAIR_RE.findall(t)
    covered = sum(len(m.group(0).replace(" ", "")) for m in PAIR_RE.finditer(t))
    if len(pairs) >= 4 and covered >= 0.8 * len(t.replace(" ", "")):
        return _pairs_table(pairs)
    # Formato D&D: "STR DEX CON INT WIS CHA 18 (+4) 14 (+2) ..."
    tokens = re.findall(rf"{_VALUE}|\S+", t)
    k = 0
    while k < len(tokens) and ABBR_RE.match(tokens[k]):
        k += 1
    values = tokens[k:]
    if k >= 4 and len(values) == k and all(VALUE_RE.match(v) for v in values):
        return Table([tokens[:k], values])
    return None


def _pairs_table(pairs) -> Table:
    n = len(pairs)
    per_row = n if n <= 6 else math.ceil(n / 2)
    rows, th = [], set()
    for i in range(0, n, per_row):
        chunk = pairs[i:i + per_row]
        th.add(len(rows))
        rows.append([a for a, _ in chunk] + [""] * (per_row - len(chunk)))
        rows.append([v for _, v in chunk] + [""] * (per_row - len(chunk)))
    return Table(rows, frozenset(th))


# --------------------------------------------------------------------------- #
# Tabelas alinhadas por texto
# --------------------------------------------------------------------------- #
def find_text_tables(blocks: list[dict], body_size: float, page_width: float):
    """Procura tabelas sem grade nos blocos de texto da página.

    Retorna ``(tabelas, consumidas)``: lista de ``(bbox, Table)`` e o conjunto
    de ``(índice do bloco, índice da linha)`` que viraram tabela.
    """
    rows = _rows(blocks, body_size, page_width)
    tables, used = [], set()
    cands = sorted((r for r in rows if _is_candidate(r)), key=lambda r: (r.y0, r.x0))
    others = [r for r in rows if not _is_candidate(r)]
    taken: set[int] = set()
    for i, first in enumerate(cands):
        if i in taken:
            continue
        group = [first]
        taken.add(i)
        for j in range(i + 1, len(cands)):
            if j in taken:
                continue
            r = cands[j]
            last = group[-1]
            gap = r.y0 - last.y1
            if gap > 1.6 * max(last.h, r.h):
                if r.y0 > last.y1:
                    break
                continue
            if gap < -0.3 * last.h:            # mesma altura, outra coluna da página
                continue
            if not _compatible(group, r):
                continue
            group.append(r)
            taken.add(j)
        table = _build(group, others)
        if table is None:
            continue
        tbl, extra_refs = table
        refs = set().union(*(r.refs for r in group)) | extra_refs
        bbox = (min(r.x0 for r in group), min(r.y0 for r in group),
                max(r.x1 for r in group), max(r.y1 for r in group))
        tables.append((bbox, tbl))
        used |= refs
    return tables, used


def _rows(blocks, body_size, page_width) -> list[_Row]:
    """Pedaços de texto agrupados por altura dentro de cada bloco."""
    rows: list[_Row] = []
    singles: list[_Row] = []
    for bi, b in enumerate(blocks):
        pieces = []
        for li, ln in enumerate(b["lines"]):
            pieces.extend((li, c) for c in _split_line(ln, body_size))
        pieces.sort(key=lambda p: ((p[1].y0 + p[1].y1) / 2, p[1].x0))
        cur: list = []
        for p in pieces:
            if cur:
                ref = cur[0][1]
                h = max(1.0, ref.y1 - ref.y0)
                if abs((p[1].y0 + p[1].y1) / 2 - (ref.y0 + ref.y1) / 2) > 0.4 * h:
                    rows.append(_make_row(cur, bi, body_size))
                    cur = []
            cur.append(p)
        if cur:
            rows.append(_make_row(cur, bi, body_size))
    # Blocos de uma célula só, lado a lado na mesma altura: junta numa linha.
    for r in rows:
        if len(r.cells) == 1 and len({ref[0] for ref in r.refs}) == 1:
            singles.append(r)
    merged = _merge_side_by_side(singles, body_size, page_width)
    single_ids = {id(r) for r in singles}
    return [r for r in rows if id(r) not in single_ids] + merged


def _split_line(ln, body_size) -> list[_Cell]:
    """Divide uma linha do PDF nos vãos largos entre spans."""
    cells: list[_Cell] = []
    for s in ln["spans"]:
        t = s["text"].replace("\xad", "")
        if not t.strip():
            continue
        x0, y0, x1, y1 = s["bbox"]
        bold = bool(s["flags"] & 16) or bool(re.search(r"bold|black|heavy", s.get("font", ""), re.I))
        size = s["size"] or body_size
        if cells and x0 - cells[-1].x1 < 1.0 * size:
            c = cells[-1]
            sep = "" if c.text.endswith(" ") or t.startswith(" ") or x0 - c.x1 < 0.15 * size else " "
            c.text += sep + t
            c.x1, c.y0, c.y1 = max(c.x1, x1), min(c.y0, y0), max(c.y1, y1)
            c.bold = c.bold and bold
        else:
            cells.append(_Cell(x0, y0, x1, y1, t, bold))
    for c in cells:
        c.text = re.sub(r"\s+", " ", c.text).strip()
    return cells


def _make_row(pieces, bi, body_size) -> _Row:
    cells: list[_Cell] = []
    refs = set()
    for li, p in sorted(pieces, key=lambda q: q[1].x0):
        refs.add((bi, li))
        if cells and p.x0 - cells[-1].x1 < 0.6 * body_size:
            c = cells[-1]
            c.text = f"{c.text} {p.text}"
            c.x1 = max(c.x1, p.x1)
            c.bold = c.bold and p.bold
        else:
            cells.append(_Cell(p.x0, p.y0, p.x1, p.y1, p.text, p.bold))
    return _Row(cells, refs)


def _merge_side_by_side(singles, body_size, page_width) -> list[_Row]:
    out, used = [], set()
    singles = sorted(singles, key=lambda r: (r.y0, r.x0))
    for i, r in enumerate(singles):
        if i in used:
            continue
        group = [r]
        used.add(i)
        if r.x1 - r.x0 < 0.3 * page_width:
            for j in range(i + 1, len(singles)):
                s = singles[j]
                if j in used or s.x1 - s.x0 >= 0.3 * page_width:
                    continue
                yc_r, yc_s = (r.y0 + r.y1) / 2, (s.y0 + s.y1) / 2
                if abs(yc_r - yc_s) > 0.4 * r.h:
                    continue
                if s.x0 - group[-1].x1 > 4 * body_size or s.x0 < group[-1].x1:
                    continue
                group.append(s)
                used.add(j)
        if len(group) == 1:
            out.append(r)
        else:
            cells = [c for g in group for c in g.cells]
            out.append(_Row(cells, set().union(*(g.refs for g in group))))
    return out


def _is_candidate(r: _Row) -> bool:
    if len(r.cells) < 2 or len(r.cells) > 14:
        return False
    lens = [len(c.text) for c in r.cells]
    return max(lens) <= 160 and min(lens) <= 30


def _anchors(rows) -> list[float]:
    xs = sorted(c.x0 for r in rows for c in r.cells)
    anchors: list[list[float]] = []
    for x in xs:
        if anchors and x - anchors[-1][-1] <= 8:
            anchors[-1].append(x)
        else:
            anchors.append([x])
    return [sum(a) / len(a) for a in anchors]


def _compatible(group, r: _Row) -> bool:
    anchors = _anchors(group)
    hits = sum(1 for c in r.cells if any(abs(c.x0 - a) <= 8 for a in anchors))
    overlap = min(r.x1, max(g.x1 for g in group)) - max(r.x0, min(g.x0 for g in group))
    return hits >= min(2, len(r.cells)) and overlap > 0


def _build(group: list[_Row], others: list[_Row]):
    extra = set()
    if len(group) == 1:
        # Uma linha só vira tabela apenas se for uma linha de características.
        texts = [c.text for c in group[0].cells]
        t = stat_table_from_text(" ".join(texts))
        return (t, extra) if t else None

    # Continuações de célula (texto quebrado numa coluna que não é a primeira).
    anchors = _anchors(group)
    for o in sorted(others, key=lambda r: r.y0):
        if len(o.cells) != 1:
            continue
        c = o.cells[0]
        for idx, row in enumerate(group):
            nxt = group[idx + 1].y0 if idx + 1 < len(group) else row.y1 + 1.4 * row.h
            if row.y1 - 1 <= c.y0 < nxt and c.y0 - row.y1 < 1.2 * row.h:
                col = [a for a in anchors if abs(c.x0 - a) <= 8]
                if col and col[0] != anchors[0]:
                    target = min(row.cells, key=lambda k: abs(k.x0 - col[0]))
                    if abs(target.x0 - col[0]) <= 8:
                        target.text += " " + c.text
                        target.y1 = max(target.y1, c.y1)
                        extra |= o.refs
                break

    grid = []
    for row in group:
        line = [""] * len(anchors)
        for c in row.cells:
            k = min(range(len(anchors)), key=lambda i: abs(anchors[i] - c.x0))
            line[k] = f"{line[k]} {c.text}".strip()
        grid.append(line)

    stat = _stat_grid(grid)
    if stat:
        return stat, extra
    # descarta colunas vazias
    keep = [i for i in range(len(anchors)) if any(r[i] for r in grid)]
    grid = [[r[i] for i in keep] for r in grid]
    if len(keep) < 2:
        return None
    # Cabeçalho: 1ª linha em negrito (e as outras não), ou 1ª linha sem
    # números enquanto a coluna de baixo é numérica ("1D6 / 1-2 / 3-4").
    first_bold = all(c.bold for c in group[0].cells)
    rest_bold = all(c.bold for r in group[1:] for c in r.cells)
    numeric_below = any(re.match(r"^[\d+−–-]", r[0]) for r in grid[1:] if r[0])
    first_numeric = bool(re.match(r"^[+−–-]?\d+([-–]\d+)?$", grid[0][0]))
    header = (first_bold and not rest_bold) or (numeric_below and not first_numeric)
    return Table(grid, frozenset({0}) if header else frozenset()), extra


def _stat_grid(grid) -> Table | None:
    """Linhas no formato ABBR valor ABBR valor ... viram pares cabeçalho/valor."""
    pairs_rows = []
    for row in grid:
        cells = [c for c in row if c]
        if len(cells) < 4 or len(cells) % 2:
            return None
        pairs = list(zip(cells[0::2], cells[1::2]))
        if not all(ABBR_RE.match(a) and VALUE_RE.match(v) for a, v in pairs):
            return None
        pairs_rows.append(pairs)
    width = max(len(p) for p in pairs_rows)
    rows, th = [], set()
    for pairs in pairs_rows:
        th.add(len(rows))
        rows.append([a for a, _ in pairs] + [""] * (width - len(pairs)))
        rows.append([v for _, v in pairs] + [""] * (width - len(pairs)))
    return Table(rows, frozenset(th))
