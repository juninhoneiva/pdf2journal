"""Extração do conteúdo do PDF em blocos lógicos, em ordem de leitura.

Cada página vira uma lista de blocos (Para, Table, Image, Box) que depois o
módulo ``html`` transforma em HTML refluído para o Foundry.
"""
from __future__ import annotations

import collections
import math
import re
from dataclasses import dataclass, field
from pathlib import Path

import pymupdf

from . import images as img
from .tables import Table, find_text_tables, stat_table_from_text

# Bits de ``span["flags"]`` no PyMuPDF.
F_SUPERSCRIPT = 1
F_ITALIC = 2
F_BOLD = 16

BULLET_RE = re.compile(r"^\s*([•●▪■◦○▸►–—*·-])\s+")
ORDERED_RE = re.compile(r"^\s*(\d{1,3}|[a-zA-Z])[.)]\s+")
SENTENCE_END = (".", "!", "?", ":", "…", '"', "”", "»", ")")
# "Rótulo: valor", típico de fichas ("Bônus de Dano: +1D4", "Corpo: 1").
LABEL_RE = re.compile(r"^[A-ZÀ-Ý][\wÀ-ÿ%/()' -]{1,32}:\s*\S")


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
    rolls: bool = True            # atalhos de rolagem do CoC7
    links: bool = True            # links para seções citadas ("ver capítulo 3")


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
        # texto normalizado -> (altura típica, só na margem?, 1ª página em que aparece)
        self.furniture: dict[str, tuple[float, bool, int]] = {}
        self.repeated_images: set[str] = set()     # digests de imagens decorativas
        self.printed: dict[int, int] = {}          # número impresso -> página do PDF (1-based)
        self.images_written: list[Path] = []

    # ---- análise global ------------------------------------------------- #
    def _text_dict(self, pno):
        if pno not in self._dicts:
            page = self.doc[pno]
            self._dicts[pno] = page.get_text("dict", flags=pymupdf.TEXTFLAGS_TEXT)
        return self._dicts[pno]

    def analyze(self):
        if self.opts.strip_headers:
            self.furniture = self._find_furniture()
        chars = collections.Counter()
        lines_per_size = collections.Counter()
        for pno in self.pages:
            rect = self.doc[pno].rect
            for b in self._text_dict(pno)["blocks"]:
                if b.get("type") != 0:
                    continue
                for ln in b["lines"]:
                    if not _horizontal(ln) or self._is_furniture(ln, rect, pno):
                        continue
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
        # por linha (exclui capitulares). Cabeçalhos repetidos não contam.
        heading_sizes = sorted(
            (s for s in chars
             if s >= self.body_size * 1.15 and chars[s] / lines_per_size[s] >= 2),
            reverse=True,
        )
        self.levels = {s: min(i + 1, 4) for i, s in enumerate(heading_sizes)}
        if self.opts.images:
            self.repeated_images = self._find_repeated_images()

    def _find_furniture(self) -> dict[str, tuple[float, bool, int]]:
        """Textos repetidos na mesma posição em várias páginas.

        Pega o título do capítulo impresso no alto de toda página, rodapés,
        nomes do livro etc. Na margem (alto, pé ou laterais) basta aparecer em
        2 páginas e em 25% das selecionadas; no miolo da página precisa
        aparecer em 3 páginas, em metade delas, sempre na mesma altura, e a
        primeira ocorrência é mantida (costuma ser o título de verdade).
        """
        n = len(self.pages)
        if n < 2:
            return {}
        occ: dict[str, dict[int, tuple[float, bool]]] = collections.defaultdict(dict)
        for pno in self.pages:
            rect = self.doc[pno].rect
            for b in self._text_dict(pno)["blocks"]:
                if b.get("type") != 0:
                    continue
                for ln in b["lines"]:
                    if not _horizontal(ln):
                        continue
                    text = _line_text(ln)
                    if not 2 <= len(text.strip()) <= 120:
                        continue
                    y = ((ln["bbox"][1] + ln["bbox"][3]) / 2 - rect.y0) / rect.height
                    margin = _in_margin(ln["bbox"], rect)
                    # Na margem os números variam (página); no miolo, texto exato.
                    key = _furniture_key(text) if margin else "=" + _exact_key(text)
                    occ[key].setdefault(pno, (y, margin))
        out = {}
        for key, per in occ.items():
            c = len(per)
            ys = sorted(y for y, _ in per.values())
            margin = all(m for _, m in per.values())
            first = min(per)
            if margin and c >= max(2, math.ceil(0.25 * n)):
                out[key] = (ys[len(ys) // 2], True, first)
            elif c >= max(3, math.ceil(0.5 * n)) and ys[-1] - ys[0] <= 0.02:
                out[key] = (ys[len(ys) // 2], False, first)
        return out

    def _find_repeated_images(self) -> set[str]:
        """Imagens que se repetem em várias páginas (fundos, molduras, ornamentos)."""
        n = len(self.pages)
        seen = collections.Counter()
        for pno in self.pages:
            try:
                infos = self.doc[pno].get_image_info(hashes=True)
            except Exception:  # noqa: BLE001
                continue
            seen.update({i["digest"] for i in infos if i.get("digest")})
        return {d for d, c in seen.items() if c >= 3 or (c >= 2 and c >= 0.5 * n)}

    def _is_furniture(self, ln, rect, pno) -> bool:
        text = _line_text(ln).strip()
        in_margin = _in_margin(ln["bbox"], rect)
        if in_margin and _is_page_number(text):
            if text.strip().isdigit():
                self.printed.setdefault(int(text.strip()), pno + 1)
            return True
        entry = self.furniture.get(_furniture_key(text)) if in_margin else None
        if entry is None:
            entry = self.furniture.get("=" + _exact_key(text))
        if entry is None:
            return False
        y, margin_only, first = entry
        if not margin_only and pno == first:
            return False
        yc = ((ln["bbox"][1] + ln["bbox"][3]) / 2 - rect.y0) / rect.height
        return (margin_only and in_margin) or abs(yc - y) <= 0.03

    def _clean_blocks(self, pno) -> list[dict]:
        """Blocos de texto sem texto girado (abas laterais), sem glifos decorativos
        e sem cabeçalhos repetidos."""
        rect = self.doc[pno].rect
        out = []
        for b in self._text_dict(pno)["blocks"]:
            if b.get("type") != 0:
                continue
            lines = []
            for ln in b["lines"]:
                if not _horizontal(ln):
                    continue
                ln = _without_glyphs(ln)
                if ln is None:
                    continue
                if self.opts.strip_headers and self._is_furniture(ln, rect, pno):
                    continue
                lines.append(ln)
            if lines:
                bbox = (min(l["bbox"][0] for l in lines), min(l["bbox"][1] for l in lines),
                        max(l["bbox"][2] for l in lines), max(l["bbox"][3] for l in lines))
                out.append({**b, "lines": lines, "bbox": bbox})
        return out

    # ---- por página ------------------------------------------------------ #
    def page_blocks(self, pno: int) -> list:
        page = self.doc[pno]
        prect = tuple(page.rect)
        parea = _area(prect)
        blocks = self._clean_blocks(pno)
        items: list[_Item] = []

        # Tabelas com grade desenhada
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
                cells = [c for row in rows for c in row]
                filled = [c for c in cells if c]
                if len(filled) < 3 or len(filled) < 0.4 * len(cells):
                    continue
                if max(len(c) for c in filled) > 250:   # parágrafo capturado por engano
                    continue
                r = tuple(t.bbox)
                table_rects.append(r)
                items.append(_Item(r, "table", Table(rows)))
            blocks = [b for b in blocks
                      if not any(_inside(_center(b["bbox"]), r) for r in table_rects)]

            # Tabelas sem grade (alinhadas pelo texto) e fichas
            found, used = find_text_tables(blocks, self.body_size, prect[2] - prect[0])
            for bbox, tbl in found:
                table_rects.append(bbox)
                items.append(_Item(bbox, "table", tbl))
            if used:
                blocks = _drop_lines(blocks, used)

        text_items = [_Item(tuple(b["bbox"]), "text", b) for b in blocks]

        # Imagens
        backgrounds = []
        if self.opts.images:
            text_items, imgs, backgrounds = self._images(page, pno, prect, parea, text_items, table_rects)
            items.extend(imgs)

        # Boxes: quadros desenhados (fundo ou moldura) e imagens de fundo com texto.
        boxes = (self._boxes(page, parea, text_items + items, table_rects, backgrounds)
                 if self.opts.boxes else [])
        loose = list(text_items) + items
        for r in boxes:
            inner = [it for it in loose if _belongs(it, r)]
            if not inner:
                continue
            loose = [it for it in loose if it not in inner]
            loose.append(_Item(_union_all([r] + [it.bbox for it in inner]), "box", children=inner))

        return self._to_blocks(reading_order(loose))

    def _images(self, page, pno, prect, parea, text_items, table_rects):
        """Ilustrações da página.

        Retorna ``(text_items, imagens, fundos)``: ``fundos`` são as áreas de
        imagens que servem de fundo para texto (pergaminho de um box, por
        exemplo), usadas depois como boxes.
        """
        try:
            infos = page.get_image_info(hashes=True, xrefs=True)
        except Exception:  # noqa: BLE001
            return text_items, [], []
        infos = [i for i in infos if i.get("digest") not in self.repeated_images]
        if not infos:
            return text_items, [], []

        content = _content_rect(text_items) or prect

        def inside(r):
            # Texto inteiro dentro da imagem = legenda/rótulo que já sai na arte.
            return [it for it in text_items if _overlap_area(it.bbox, r) >= 0.8 * _area(it.bbox)]

        def is_background(r):
            # Parágrafos sobre a imagem: ela é fundo do texto, não ilustração.
            over = [it for it in text_items if _overlap_area(it.bbox, r) >= 0.5 * _area(it.bbox)]
            lens = [len(_block_text(it.payload)) for it in over]
            return sum(lens) > 300 or any(n > 80 for n in lens)

        rects, backgrounds = [], []
        for info, r in zip(infos, img.visible_rects(self.doc, pno, infos)):
            if r is None:
                continue
            r = _clip(tuple(r), prect)
            w, h = r[2] - r[0], r[3] - r[1]
            if w < self.opts.min_image_pt or h < self.opts.min_image_pt:
                if max(w, h) > 4 * max(1.0, min(w, h)):
                    continue                # fio ou arabesco fino
                continue
            if max(w, h) > 6 * min(w, h):
                continue                    # divisória / arabesco comprido
            if any(_overlap_area(r, t) > 0.5 * _area(r) for t in table_rects):
                continue
            if _area(r) < 0.06 * parea and _overlap_area(r, content) < 0.3 * _area(r):
                continue                    # ornamento na margem (cantoneira, vinheta)
            if is_background(r):
                backgrounds.append(r)
                continue
            if _area(r) > 0.4 * parea and img.is_flat(self.doc, pno, info.get("xref"), r):
                continue                    # textura de fundo (papel, pergaminho)
            rects.append(r)

        out = []
        for i, r in enumerate(sorted(_merge_rects(rects), key=lambda r: (r[1], r[0]))):
            if is_background(r):
                backgrounds.append(r)
                continue
            labels = inside(r)
            text_items = [it for it in text_items if it not in labels]
            # Texto do Journal que encosta na imagem é apagado do recorte.
            erase = [tuple(ln["bbox"]) for it in text_items for ln in it.payload["lines"]
                     if _overlap_area(tuple(ln["bbox"]), r) > 0]
            name = f"{self.asset_stem}-p{pno + 1:03d}-{i + 1:02d}.{self.opts.image_format}"
            self._save_clip(pno, r, name, erase)
            out.append(_Item(r, "image", Image(name, r[2] - r[0])))
        return text_items, out, backgrounds

    def _save_clip(self, pno, rect, name, erase):
        if self.asset_dir is None:
            return
        self.asset_dir.mkdir(parents=True, exist_ok=True)
        pix = img.render(self.doc, pno, rect, self.opts.dpi, erase)
        path = self.asset_dir / name
        fmt = self.opts.image_format
        if fmt == "webp":
            pix.pil_save(str(path), format="WEBP", quality=82)
        elif fmt == "jpg":
            pix.save(str(path), jpg_quality=85)
        else:
            pix.save(str(path))
        self.images_written.append(path)

    def _boxes(self, page, parea, text_items, table_rects, backgrounds=()):
        cands = [tuple(r) for r in backgrounds if _area(r) <= 0.7 * parea]
        for p in page.get_drawings():
            r = tuple(p["rect"])
            w, h = r[2] - r[0], r[3] - r[1]
            if w < 40 or h < 20 or _area(r) > 0.6 * parea:
                continue
            fill = p.get("fill")
            filled = fill is not None and not all(c > 0.96 for c in fill)
            # moldura: retângulo ou contorno fechado feito de várias linhas/curvas
            stroked = p.get("color") is not None and (
                any(it[0] in ("re", "qu") for it in p["items"]) or len(p["items"]) >= 3)
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
            n = sum(1 for it in text_items if _belongs(it, r))
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
        prev_x1 = None
        for s in ln["spans"]:
            t = s["text"].replace("\xad", "")
            if not t:
                continue
            if (runs and prev_x1 is not None and s["bbox"][0] - prev_x1 > 0.2 * s["size"]
                    and not runs[-1].text.endswith(" ") and not t.startswith(" ")):
                runs[-1].text += " "
            prev_x1 = s["bbox"][2]
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

    def _paras(self, block) -> list:
        lines = [l for l in (self._line(ln) for ln in _same_row_merged(block["lines"])) if l]
        if not lines:
            return []
        bx0 = min(l.bbox[0] for l in lines)
        bx1 = max(l.bbox[2] for l in lines)
        # Bloco de ficha: várias linhas "Rótulo: valor" -> uma linha por parágrafo.
        labels = sum(1 for l in lines if LABEL_RE.match(l.text.strip()))
        sheet = labels >= 2 and labels >= 0.4 * len(lines)
        paras: list[Para] = []
        prev: Line | None = None
        for line in lines:
            kind = self._classify(line)
            text = line.text
            stripped = text.strip()
            marker = BULLET_RE.match(text) or ORDERED_RE.match(text)
            cur = paras[-1] if paras else None
            new = cur is None or _family(kind) != _family(cur.kind) or kind == "dropcap"
            if not new and kind == "p":
                size = line.size
                gap = line.bbox[1] - prev.bbox[3]
                indented = line.x0 > bx0 + max(6, 0.8 * size)
                prev_text = prev.text.rstrip()
                starts_upper = stripped[:1].isupper() or stripped[:1].isdigit()
                if marker:
                    new = True
                elif gap > 0.7 * size:
                    new = True
                elif cur.kind == "li":
                    new = False                     # continuação do item
                elif sheet:
                    new = starts_upper and not prev_text.endswith(("-", ",", "("))
                elif indented:
                    new = True
                elif prev.all_bold and not line.all_bold and cur.lines == 1:
                    new = True                      # subtítulo em negrito
                elif LABEL_RE.match(stripped) and LABEL_RE.match(prev.text.strip()):
                    new = True                      # "Rótulo: valor" em sequência
                elif (starts_upper and prev_text.endswith(SENTENCE_END)
                      and prev.bbox[2] < bx1 - 3 * size):
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

        out: list = []
        for p in paras:
            _trim(p.runs)
            if not p.text.strip():
                continue
            if p.kind == "p":
                stat = stat_table_from_text(p.text)
                if stat:
                    out.append(stat)
                    continue
            if p.kind == "p" and p.lines == 1 and p.runs and all(r.bold for r in p.runs if r.text.strip()):
                t = p.text.strip()
                if len(t) < 70 and not t.endswith((".", ",", ";", ":")):
                    p.kind = "h4"
            if p.kind.startswith("h") and len(p.text) > 200:
                p.kind = "p"
            out.append(p)
        return out


# --------------------------------------------------------------------------- #
# Funções auxiliares
# --------------------------------------------------------------------------- #
# Fontes de ornamentos e símbolos (Wingdings, Zapf Dingbats, fleurons...).
SYMBOL_FONT_RE = re.compile(
    r"dingbat|wingding|webding|zapf|^symbol|[-+]symbol|ornament|fleur|glyph|icon|awesome|"
    r"marlett|bullets|decor|border|frame", re.I)


def _is_decor_char(ch: str) -> bool:
    """Caractere de enfeite: ornamentos, símbolos, uso privado, glifo não mapeado."""
    o = ord(ch)
    return (0x2600 <= o <= 0x27BF or 0x2B00 <= o <= 0x2BFF or 0x25A0 <= o <= 0x25FF
            or 0x1F300 <= o <= 0x1FAFF or 0xE000 <= o <= 0xF8FF or 0xF0000 <= o
            or o == 0xFFFD or ch in "⁂※❧☙⸙⁕⁜")


def _without_glyphs(ln):
    """Tira da linha os glifos decorativos; ``None`` se não sobrar texto.

    Um marcador de lista no começo da linha (•, ●, ▪) é mantido como "•".
    """
    spans = []
    changed = False
    for i, s in enumerate(ln["spans"]):
        text = s["text"]
        symbol_font = bool(SYMBOL_FONT_RE.search(s.get("font", "")))
        if symbol_font or any(_is_decor_char(c) for c in text):
            rest = "".join(c for c in text if not _is_decor_char(c)) if not symbol_font else ""
            lead = text.lstrip()
            # marcador de lista no começo da linha: vira "•"
            if i == 0 and len(lead.strip()) == 1 and len(ln["spans"]) > 1:
                rest = "• "
            elif (i == 0 and not symbol_font and len(lead) > 2 and _is_decor_char(lead[0])
                  and lead[1] == " " and rest.strip()):
                rest = "• " + rest.lstrip()
            changed = True
            if not rest.strip():
                continue
            s = {**s, "text": rest}
        spans.append(s)
    text = "".join(s["text"] for s in spans)
    if not text.strip():
        return None
    # linha só de enfeite tipográfico ("* * *", "~ ~", "• • •")
    stripped = re.sub(r"\s", "", text)
    if re.fullmatch(r"[*~•·°=_]+", stripped) and (len(stripped) >= 2 or stripped == "•"):
        return None
    if not changed:
        return ln
    bbox = (min(s["bbox"][0] for s in spans), min(s["bbox"][1] for s in spans),
            max(s["bbox"][2] for s in spans), max(s["bbox"][3] for s in spans))
    return {**ln, "spans": spans, "bbox": bbox}


def _round(size):
    return round(size * 2) / 2


def _family(kind):
    return "p" if kind in ("p", "li") else kind


def _line_text(ln):
    return "".join(s["text"] for s in ln["spans"])


def _block_text(b):
    return " ".join(_line_text(ln) for ln in b["lines"])


def _horizontal(ln):
    dx, dy = ln.get("dir", (1, 0))
    return dx > 0.99 and abs(dy) < 0.05


def _center(bbox):
    return ((bbox[0] + bbox[2]) / 2, (bbox[1] + bbox[3]) / 2)


def _in_margin(bbox, rect):
    """Faixa de 12% no alto e no pé da página, ou 10% nas laterais."""
    x0, y0, x1, y1 = rect
    w, h = x1 - x0, y1 - y0
    return (bbox[3] < y0 + 0.12 * h or bbox[1] > y1 - 0.12 * h
            or bbox[2] < x0 + 0.10 * w or bbox[0] > x1 - 0.10 * w)


def _same_row_merged(lines):
    """Junta linhas do PDF que estão na mesma altura (texto quebrado em pedaços)."""
    out: list[dict] = []
    for ln in lines:
        if out:
            last = out[-1]
            h = max(1.0, last["bbox"][3] - last["bbox"][1])
            same = abs((ln["bbox"][1] + ln["bbox"][3]) / 2 - (last["bbox"][1] + last["bbox"][3]) / 2) < 0.4 * h
            if same and ln["bbox"][0] >= last["bbox"][2] - 1:
                out[-1] = {**last, "spans": last["spans"] + ln["spans"],
                           "bbox": (last["bbox"][0], min(last["bbox"][1], ln["bbox"][1]),
                                    ln["bbox"][2], max(last["bbox"][3], ln["bbox"][3]))}
                continue
        out.append(ln)
    return out


def _drop_lines(blocks, used):
    out = []
    for bi, b in enumerate(blocks):
        lines = [ln for li, ln in enumerate(b["lines"]) if (bi, li) not in used]
        if not lines:
            continue
        if len(lines) != len(b["lines"]):
            bbox = (min(l["bbox"][0] for l in lines), min(l["bbox"][1] for l in lines),
                    max(l["bbox"][2] for l in lines), max(l["bbox"][3] for l in lines))
            b = {**b, "lines": lines, "bbox": bbox}
        out.append(b)
    return out


def _furniture_key(text):
    return re.sub(r"\d+", "#", re.sub(r"\s+", " ", text.strip().lower()))


def _exact_key(text):
    return re.sub(r"\s+", " ", text.strip().casefold())


def _is_page_number(text):
    return bool(re.fullmatch(r"[\s\-–—]*(\d{1,4}|[ivxlcdm]{1,6})[\s\-–—]*", text.strip(), re.I))


def _belongs(it, box, tol=3.0):
    """O item está dentro do box (centro dentro, com folga, ou maior parte sobreposta)."""
    return (_inside((it.cx, it.cy), box, tol)
            or _overlap_area(it.bbox, box) >= 0.6 * max(1.0, _area(it.bbox)))


def _union_all(rects):
    out = rects[0]
    for r in rects[1:]:
        out = _union(out, r)
    return out


def _content_rect(items):
    """Área ocupada pelo texto da página (ignora o que está fora: margens)."""
    texts = [it.bbox for it in items if it.kind == "text"]
    return _union_all(texts) if texts else None


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
