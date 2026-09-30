"""Extração do conteúdo do PDF em blocos lógicos, em ordem de leitura.

Cada página vira uma lista de blocos (Para, Table, Image, Box) que depois o
módulo ``html`` transforma em HTML refluído para o Foundry.
"""
from __future__ import annotations

import collections
import re
from dataclasses import dataclass, field
from pathlib import Path

import pymupdf

# Bits de ``span["flags"]`` no PyMuPDF.
F_SUPERSCRIPT = 1
F_ITALIC = 2
F_BOLD = 16

BULLET_RE = re.compile(r"^\s*([•●▪■◦○▸►–—*·-])\s+")
ORDERED_RE = re.compile(r"^\s*(\d{1,3}|[a-zA-Z])[.)]\s+")
SENTENCE_END = (".", "!", "?", ":", "…", '"', "”", "»", ")")


# --------------------------------------------------------------------------- #
# Estruturas
# --------------------------------------------------------------------------- #
@dataclass
class Run:
    text: str
    bold: bool = False
    italic: bool = False
    sup: bool = False

    @property
    def fmt(self):
        return (self.bold, self.italic, self.sup)


@dataclass
class Line:
    runs: list[Run]
    bbox: tuple
    size: float          # tamanho de fonte dominante (por caracteres)
    all_bold: bool

    @property
    def text(self) -> str:
        return "".join(r.text for r in self.runs)

    @property
    def x0(self):
        return self.bbox[0]


@dataclass
class Para:
    kind: str                     # p | h1..h4 | li | dropcap
    runs: list[Run] = field(default_factory=list)
    ordered: bool = False         # para li
    lines: int = 1

    @property
    def text(self) -> str:
        return "".join(r.text for r in self.runs)


@dataclass
class Table:
    rows: list[list[str]]


@dataclass
class Image:
    file: str
    width_pt: float


@dataclass
class Box:
    children: list


@dataclass
class PageBreak:
    number: int                   # número (1-based) da página do PDF


@dataclass
class _Item:
    """Item posicionado na página, usado para calcular a ordem de leitura."""
    bbox: tuple
    kind: str                     # text | table | image | box
    payload: object = None
    children: list = field(default_factory=list)

    @property
    def w(self):
        return self.bbox[2] - self.bbox[0]

    @property
    def cx(self):
        return (self.bbox[0] + self.bbox[2]) / 2

    @property
    def cy(self):
        return (self.bbox[1] + self.bbox[3]) / 2


@dataclass
class Options:
    images: bool = True
    tables: bool = True
    boxes: bool = True
    strip_headers: bool = True
    dpi: int = 150
    image_format: str = "webp"    # webp | jpg | png
    min_image_pt: float = 48.0


# --------------------------------------------------------------------------- #
# Utilitários geométricos
# --------------------------------------------------------------------------- #
def _inside(pt, rect, tol=1.0):
    x, y = pt
    return rect[0] - tol <= x <= rect[2] + tol and rect[1] - tol <= y <= rect[3] + tol


def _overlap_area(a, b):
    w = min(a[2], b[2]) - max(a[0], b[0])
    h = min(a[3], b[3]) - max(a[1], b[1])
    return w * h if w > 0 and h > 0 else 0.0


def _area(r):
    return max(0.0, r[2] - r[0]) * max(0.0, r[3] - r[1])


def _union(a, b):
    return (min(a[0], b[0]), min(a[1], b[1]), max(a[2], b[2]), max(a[3], b[3]))


def _merge_rects(rects, gap=2.0):
    rects = [tuple(r) for r in rects]
    changed = True
    while changed:
        changed = False
        out = []
        while rects:
            r = rects.pop()
            grown = (r[0] - gap, r[1] - gap, r[2] + gap, r[3] + gap)
            i = 0
            while i < len(rects):
                if _overlap_area(grown, rects[i]) > 0:
                    r = _union(r, rects.pop(i))
                    grown = (r[0] - gap, r[1] - gap, r[2] + gap, r[3] + gap)
                    changed = True
                else:
                    i += 1
            out.append(r)
        rects = out
    return rects


# --------------------------------------------------------------------------- #
# Ordem de leitura (colunas)
# --------------------------------------------------------------------------- #
def reading_order(items: list[_Item], x0: float | None = None, x1: float | None = None):
    """Ordena itens respeitando colunas.

    Itens "largos" (>= 60% da largura da região) funcionam como separadores
    horizontais (títulos, imagens de página inteira). Entre eles, a faixa é
    dividida em colunas pelos vãos verticais e cada coluna é lida de cima
    para baixo, recursivamente.
    """
    if len(items) <= 1:
        return list(items)
    if x0 is None:
        x0 = min(it.bbox[0] for it in items)
        x1 = max(it.bbox[2] for it in items)
    width = max(1.0, x1 - x0)

    out: list[_Item] = []
    band: list[_Item] = []
    for it in sorted(items, key=lambda i: (i.bbox[1], i.bbox[0])):
        if it.w >= 0.6 * width:
            out.extend(_columns(band))
            band = []
            out.append(it)
        else:
            band.append(it)
    out.extend(_columns(band))
    return out


def _columns(band: list[_Item]):
    if len(band) <= 1:
        return band
    spans = sorted((it.bbox[0], it.bbox[2]) for it in band)
    cols = [list(spans[0])]
    for a, b in spans[1:]:
        if a <= cols[-1][1] + 2:          # sobrepõe: mesma coluna
            cols[-1][1] = max(cols[-1][1], b)
        else:
            cols.append([a, b])
    if len(cols) == 1:
        return sorted(band, key=lambda i: (i.bbox[1], i.bbox[0]))
    out = []
    for a, b in cols:
        members = [it for it in band if a - 2 <= it.cx <= b + 2]
        out.extend(reading_order(members, a, b))
    return out


# --------------------------------------------------------------------------- #
# Extrator
# --------------------------------------------------------------------------- #
class Extractor:
    def __init__(self, doc: pymupdf.Document, pages: list[int], opts: Options,
                 asset_dir: Path | None, asset_stem: str):
        self.doc = doc
        self.pages = pages                 # índices 0-based
        self.opts = opts
        self.asset_dir = asset_dir
        self.asset_stem = asset_stem
        self._dicts = {}
        self.body_size = 10.0
        self.levels: dict[float, int] = {}
        self.furniture: set[str] = set()
        self.images_written: list[Path] = []

    # ---- análise global ------------------------------------------------- #
    def _text_dict(self, pno):
        if pno not in self._dicts:
            page = self.doc[pno]
            self._dicts[pno] = page.get_text("dict", flags=pymupdf.TEXTFLAGS_TEXT)
        return self._dicts[pno]

    def analyze(self):
        chars = collections.Counter()
        lines_per_size = collections.Counter()
        for pno in self.pages:
            for b in self._text_dict(pno)["blocks"]:
                if b.get("type") != 0:
                    continue
                for ln in b["lines"]:
                    sizes = collections.Counter()
                    for s in ln["spans"]:
                        n = len(s["text"].strip())
                        if n:
                            sizes[_round(s["size"])] += n
                    if sizes:
                        size, n = sizes.most_common(1)[0]
                        chars[size] += n
                        lines_per_size[size] += 1
        if chars:
            self.body_size = chars.most_common(1)[0][0]
        # Tamanhos de título: maiores que o corpo e com média >= 2 caracteres
        # por linha (exclui capitulares).
        heading_sizes = sorted(
            (s for s in chars
             if s >= self.body_size * 1.15 and chars[s] / lines_per_size[s] >= 2),
            reverse=True,
        )
        self.levels = {s: min(i + 1, 4) for i, s in enumerate(heading_sizes)}
        if self.opts.strip_headers:
            self.furniture = self._find_furniture()

    def _find_furniture(self):
        """Cabeçalhos/rodapés repetidos (texto na margem em >= metade das páginas)."""
        if len(self.pages) < 3:
            return set()
        seen = collections.Counter()
        for pno in self.pages:
            h = self.doc[pno].rect.height
            keys = set()
            for b in self._text_dict(pno)["blocks"]:
                if b.get("type") == 0 and _in_margin(b["bbox"], h):
                    keys.add(_furniture_key(_block_text(b)))
            seen.update(keys)
        limit = max(2, len(self.pages) // 2)
        return {k for k, n in seen.items() if n >= limit and k}

    # ---- por página ------------------------------------------------------ #
    def page_blocks(self, pno: int) -> list:
        page = self.doc[pno]
        prect = tuple(page.rect)
        parea = _area(prect)
        d = self._text_dict(pno)

        text_items: list[_Item] = []
        for b in d["blocks"]:
            if b.get("type") != 0:
                continue
            txt = _block_text(b).strip()
            if not txt:
                continue
            if _in_margin(b["bbox"], prect[3]):
                if _furniture_key(txt) in self.furniture or _is_page_number(txt):
                    continue
            text_items.append(_Item(tuple(b["bbox"]), "text", b))

        items: list[_Item] = []

        # Tabelas
        table_rects = []
        if self.opts.tables:
            try:
                tabs = page.find_tables()
            except Exception:              # noqa: BLE001 - heurística opcional
                tabs = []
            for t in getattr(tabs, "tables", tabs):
                if t.row_count < 2 or t.col_count < 2:
                    continue
                rows = [[_clean_cell(c) for c in row] for row in t.extract()]
                if sum(1 for row in rows for c in row if c) < 3:
                    continue
                r = tuple(t.bbox)
                table_rects.append(r)
                items.append(_Item(r, "table", Table(rows)))
            text_items = [it for it in text_items
                          if not any(_inside((it.cx, it.cy), r) for r in table_rects)]

        # Imagens
        if self.opts.images:
            text_items, imgs = self._images(page, pno, prect, parea, text_items, table_rects)
            items.extend(imgs)

        # Boxes (quadros com fundo ou borda)
        boxes = self._boxes(page, parea, text_items, table_rects) if self.opts.boxes else []
        loose = list(text_items) + items
        for r in boxes:
            inner = [it for it in loose if _inside((it.cx, it.cy), r)]
            if not inner:
                continue
            loose = [it for it in loose if it not in inner]
            loose.append(_Item(r, "box", children=inner))

        return self._to_blocks(reading_order(loose))

    def _images(self, page, pno, prect, parea, text_items, table_rects):
        rects = []
        for info in page.get_image_info():
            r = _clip(tuple(info["bbox"]), prect)
            w, h = r[2] - r[0], r[3] - r[1]
            if w < self.opts.min_image_pt or h < self.opts.min_image_pt:
                continue
            if _area(r) > 0.85 * parea:     # fundo de página
                continue
            if any(_overlap_area(r, t) > 0.5 * _area(r) for t in table_rects):
                continue
            rects.append(r)
        out = []
        for i, r in enumerate(sorted(_merge_rects(rects), key=lambda r: (r[1], r[0]))):
            inside = [it for it in text_items if _inside((it.cx, it.cy), r)]
            n_chars = sum(len(_block_text(it.payload)) for it in inside)
            if n_chars > 300:
                # Imagem servindo de fundo para texto: mantém o texto, ignora a arte.
                continue
            # Textos curtos dentro da imagem (legendas de mapa etc.) já saem
            # renderizados na própria imagem.
            text_items = [it for it in text_items if it not in inside]
            name = f"{self.asset_stem}-p{pno + 1:03d}-{i + 1:02d}.{self.opts.image_format}"
            self._save_clip(page, r, name)
            out.append(_Item(r, "image", Image(name, r[2] - r[0])))
        return text_items, out

    def _save_clip(self, page, rect, name):
        if self.asset_dir is None:
            return
        self.asset_dir.mkdir(parents=True, exist_ok=True)
        pix = page.get_pixmap(clip=pymupdf.Rect(rect), dpi=self.opts.dpi, alpha=False)
        path = self.asset_dir / name
        fmt = self.opts.image_format
        if fmt == "webp":
            pix.pil_save(str(path), format="WEBP", quality=82)
        elif fmt == "jpg":
            pix.save(str(path), jpg_quality=85)
        else:
            pix.save(str(path))
        self.images_written.append(path)

    def _boxes(self, page, parea, text_items, table_rects):
        cands = []
        for p in page.get_drawings():
            r = tuple(p["rect"])
            w, h = r[2] - r[0], r[3] - r[1]
            if w < 40 or h < 20 or _area(r) > 0.6 * parea:
                continue
            fill = p.get("fill")
            filled = fill is not None and not all(c > 0.96 for c in fill)
            stroked = p.get("color") is not None and any(it[0] == "re" for it in p["items"])
            if not (filled or stroked):
                continue
            if any(_overlap_area(r, t) > 0.3 * _area(r) for t in table_rects):
                continue
            cands.append(r)
        cands = _merge_rects(cands, gap=0.5)
        # Mantém só os mais externos.
        cands = [r for r in cands
                 if not any(o != r and _inside((r[0], r[1]), o) and _inside((r[2], r[3]), o)
                            for o in cands)]
        total = len(text_items)
        out = []
        for r in cands:
            n = sum(1 for it in text_items if _inside((it.cx, it.cy), r))
            if n == 0:
                continue
            if total > 3 and n >= 0.9 * total:   # moldura da página inteira
                continue
            out.append(r)
        return out

    # ---- itens -> blocos lógicos ---------------------------------------- #
    def _to_blocks(self, items):
        out = []
        for it in items:
            if it.kind == "text":
                out.extend(self._paras(it.payload))
            elif it.kind in ("table", "image"):
                out.append(it.payload)
            elif it.kind == "box":
                out.append(Box(self._to_blocks(reading_order(it.children, it.bbox[0], it.bbox[2]))))
        return out

    def _line(self, ln) -> Line | None:
        runs, sizes = [], collections.Counter()
        all_bold = True
        for s in ln["spans"]:
            t = s["text"].replace("\xad", "")
            if not t:
                continue
            font = s.get("font", "")
            bold = bool(s["flags"] & F_BOLD) or bool(re.search(r"bold|black|heavy|semibold", font, re.I))
            italic = bool(s["flags"] & F_ITALIC) or bool(re.search(r"italic|oblique", font, re.I))
            sup = bool(s["flags"] & F_SUPERSCRIPT) and s["size"] < self.body_size * 0.9
            runs.append(Run(t, bold, italic, sup))
            n = len(t.strip())
            if n:
                sizes[_round(s["size"])] += n
                all_bold &= bold
        if not sizes:
            return None
        return Line(runs, tuple(ln["bbox"]), sizes.most_common(1)[0][0], all_bold)

    def _classify(self, line: Line) -> str:
        t = line.text.strip()
        if len(t) <= 2 and t.isalpha() and line.size >= 1.8 * self.body_size:
            return "dropcap"
        lvl = self.levels.get(line.size)
        return f"h{lvl}" if lvl else "p"

    def _paras(self, block) -> list[Para]:
        lines = [l for l in (self._line(ln) for ln in block["lines"]) if l]
        if not lines:
            return []
        bx0 = min(l.bbox[0] for l in lines)
        bx1 = max(l.bbox[2] for l in lines)
        paras: list[Para] = []
        prev: Line | None = None
        for line in lines:
            kind = self._classify(line)
            text = line.text
            marker = BULLET_RE.match(text) or ORDERED_RE.match(text)
            cur = paras[-1] if paras else None
            new = cur is None or _family(kind) != _family(cur.kind) or kind == "dropcap"
            if not new and kind == "p":
                size = line.size
                gap = line.bbox[1] - prev.bbox[3]
                indented = line.x0 > bx0 + max(6, 0.8 * size)
                prev_text = prev.text.rstrip()
                if marker:
                    new = True
                elif gap > 0.7 * size:
                    new = True
                elif cur.kind == "li":
                    new = False                     # continuação do item
                elif indented:
                    new = True
                elif prev.all_bold and not line.all_bold and cur.lines == 1:
                    new = True                      # subtítulo em negrito
                elif (prev_text.endswith(SENTENCE_END) and prev.bbox[2] < bx1 - 3 * size
                      and text[:1].isupper()):
                    new = True                      # linha curta encerrando parágrafo
            if new:
                if kind == "p" and marker:
                    ordered = bool(ORDERED_RE.match(text))
                    runs = _strip_marker(line.runs, marker.end())
                    paras.append(Para("li", runs, ordered=ordered))
                else:
                    paras.append(Para(kind, list(line.runs)))
            else:
                _join_runs(cur.runs, line.runs)
                cur.lines += 1
            prev = line

        for p in paras:
            _trim(p.runs)
            if p.kind == "p" and p.lines == 1 and p.runs and all(r.bold for r in p.runs if r.text.strip()):
                t = p.text.strip()
                if len(t) < 70 and not t.endswith((".", ",", ";", ":")):
                    p.kind = "h4"
            if p.kind.startswith("h") and len(p.text) > 200:
                p.kind = "p"
        return [p for p in paras if p.text.strip()]


# --------------------------------------------------------------------------- #
# Funções auxiliares
# --------------------------------------------------------------------------- #
def _round(size):
    return round(size * 2) / 2


def _family(kind):
    return "p" if kind in ("p", "li") else kind


def _block_text(b):
    return " ".join("".join(s["text"] for s in ln["spans"]) for ln in b["lines"])


def _in_margin(bbox, height):
    return bbox[3] < height * 0.08 or bbox[1] > height * 0.92


def _furniture_key(text):
    return re.sub(r"\d+", "#", re.sub(r"\s+", " ", text.strip().lower()))


def _is_page_number(text):
    return bool(re.fullmatch(r"[\s\-–—]*(\d{1,4}|[ivxlcdm]{1,6})[\s\-–—]*", text.strip(), re.I))


def _clip(r, page):
    return (max(r[0], page[0]), max(r[1], page[1]), min(r[2], page[2]), min(r[3], page[3]))


def _clean_cell(c):
    if c is None:
        return ""
    c = c.replace("\xad", "")
    c = re.sub(r"(\w)-\n(\w)", r"\1\2", c)
    return re.sub(r"\s+", " ", c).strip()


def _strip_marker(runs, n):
    out, skip = [], n
    for r in runs:
        if skip >= len(r.text):
            skip -= len(r.text)
            continue
        out.append(Run(r.text[skip:], r.bold, r.italic, r.sup))
        skip = 0
    return out


def _join_runs(runs: list[Run], new: list[Run]):
    """Junta a próxima linha ao parágrafo, desfazendo hifenização."""
    if not new:
        return
    last = runs[-1] if runs else None
    nxt = new[0].text.lstrip()
    if last is not None:
        stripped = last.text.rstrip()
        if (stripped.endswith("-") and len(stripped) > 1 and stripped[-2].isalpha()
                and nxt[:1].islower()):
            last.text = stripped[:-1]
        elif not last.text.endswith(" "):
            last.text = stripped + " "
    first = new[0]
    runs.append(Run(nxt, first.bold, first.italic, first.sup))
    runs.extend(Run(r.text, r.bold, r.italic, r.sup) for r in new[1:])


def _trim(runs):
    if runs:
        runs[0].text = runs[0].text.lstrip()
        runs[-1].text = runs[-1].text.rstrip()


def extract(doc, pages, opts, asset_dir, asset_stem):
    """Gera o fluxo de blocos de todas as páginas, com PageBreak antes de cada uma."""
    ex = Extractor(doc, pages, opts, asset_dir, asset_stem)
    ex.analyze()
    stream = []
    for pno in pages:
        stream.append(PageBreak(pno + 1))
        stream.extend(ex.page_blocks(pno))
    return stream, ex
