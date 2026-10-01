"""Pós-processamento do fluxo de blocos e geração de HTML."""
from __future__ import annotations

import html
import re
from dataclasses import dataclass, field

from .coc7 import SAN_HEADER, san_cell
from .extract import SENTENCE_END, Box, Image, PageBreak, Para, Run, Table


@dataclass
class JournalPage:
    title: str
    blocks: list = field(default_factory=list)
    pdf_pages: list = field(default_factory=list)   # páginas do PDF (1-based) incluídas
    id: str = ""


# --------------------------------------------------------------------------- #
# Limpeza do fluxo
# --------------------------------------------------------------------------- #
def tidy(blocks: list, across_pages: bool) -> list:
    """Aplica capitulares e junta parágrafos quebrados entre colunas/páginas."""
    out: list = []
    pending_drop = ""
    last_para_idx = None
    last_heading = None          # (nível, texto) do último título emitido
    page_start = False
    for b in blocks:
        if isinstance(b, Box):
            out.append(Box(tidy(b.children, across_pages=False)))
            last_para_idx = None
            page_start = False
            continue
        if isinstance(b, PageBreak):
            out.append(b)
            page_start = True
            if not across_pages:
                last_para_idx = None
            continue
        if isinstance(b, Para) and b.kind.startswith("h"):
            key = (b.kind, _norm(b.text))
            # Título do capítulo reimpresso no topo da página seguinte: descarta.
            if page_start and key == last_heading:
                continue
            last_heading = key
        page_start = False
        if not isinstance(b, Para):
            out.append(b)
            last_para_idx = None
            continue
        if b.kind == "dropcap":
            pending_drop += b.text.strip()
            continue
        if pending_drop and b.runs:
            b.runs.insert(0, Run(pending_drop, b.runs[0].bold, b.runs[0].italic))
            pending_drop = ""
        if b.kind == "p" and last_para_idx is not None:
            prev = out[last_para_idx]
            if _continues(prev, b):
                prev.runs.append(Run(" "))
                prev.runs.extend(b.runs)
                continue
        out.append(b)
        last_para_idx = len(out) - 1 if b.kind in ("p", "li") else None
    return out


def _norm(text: str) -> str:
    return re.sub(r"\s+", " ", text).strip().casefold()


def _continues(prev: Para, cur: Para) -> bool:
    t = prev.text.rstrip()
    nxt = cur.text.lstrip()
    return bool(t) and bool(nxt) and not t.endswith(SENTENCE_END) and nxt[0].islower()


# --------------------------------------------------------------------------- #
# Divisão em páginas do Journal
# --------------------------------------------------------------------------- #
def split_pages(stream: list, mode: str, split_level: int, name: str) -> list[JournalPage]:
    if mode == "page":
        pages, cur = [], None
        for b in tidy(stream, across_pages=False):
            if isinstance(b, PageBreak):
                cur = JournalPage(f"Página {b.number}", pdf_pages=[b.number])
                pages.append(cur)
            elif cur is not None:
                cur.blocks.append(b)
        for p in pages:
            first = p.blocks[0] if p.blocks else None
            if isinstance(first, Para) and first.kind.startswith("h"):
                p.title = _plain(first)
                p.blocks.pop(0)
        return [p for p in pages if p.blocks or p.title]

    blocks = tidy(stream, across_pages=True)
    if mode == "none":
        return [JournalPage(name, [b for b in blocks if not isinstance(b, PageBreak)],
                            [b.number for b in blocks if isinstance(b, PageBreak)])]

    # mode == "heading"
    pages: list[JournalPage] = []
    cur = JournalPage(name)
    for b in blocks:
        if isinstance(b, PageBreak):
            cur.pdf_pages.append(b.number)
            continue
        if isinstance(b, Para) and b.kind.startswith("h") and int(b.kind[1]) <= split_level:
            if cur.blocks or cur.title != name:
                pages.append(cur)
            cur = JournalPage(_plain(b), pdf_pages=cur.pdf_pages[-1:])
            continue
        cur.blocks.append(b)
    if cur.blocks or cur.title != name or not pages:
        pages.append(cur)
    return pages


def _plain(p: Para) -> str:
    return re.sub(r"\s+", " ", p.text).strip()


# --------------------------------------------------------------------------- #
# HTML
# --------------------------------------------------------------------------- #
def render(blocks: list, img_src, annotate=None) -> str:
    """``img_src(file) -> str`` resolve o caminho de cada imagem.

    ``annotate(texto) -> [(início, fim, substituição)]``, se dado, troca
    trechos do texto (atalhos de rolagem, links) em parágrafos, itens de
    lista e células de tabela.
    """
    parts: list[str] = []
    ann = annotate or (lambda t: [])
    i = 0
    while i < len(blocks):
        b = blocks[i]
        if isinstance(b, Para) and b.kind == "li":
            tag = "ol" if b.ordered else "ul"
            items = []
            while (i < len(blocks) and isinstance(blocks[i], Para)
                   and blocks[i].kind == "li" and blocks[i].ordered == b.ordered):
                items.append(f"<li>{runs_html(_annotate_runs(blocks[i].runs, ann))}</li>")
                i += 1
            parts.append(f"<{tag}>{''.join(items)}</{tag}>")
            continue
        if isinstance(b, Para):
            tag = b.kind if b.kind.startswith("h") else "p"
            runs = b.runs if tag != "p" else _annotate_runs(b.runs, ann)
            parts.append(f"<{tag}>{runs_html(runs, in_heading=tag != 'p')}</{tag}>")
        elif isinstance(b, Table):
            parts.append(_table(b, ann))
        elif isinstance(b, Image):
            w = round(b.width_pt * 96 / 72)
            parts.append(f'<p><img src="{html.escape(img_src(b.file))}" width="{w}"></p>')
        elif isinstance(b, Box):
            parts.append(f"<blockquote>{render(b.children, img_src, annotate)}</blockquote>")
        i += 1
    return "\n".join(parts)


def runs_html(runs: list[Run], in_heading: bool = False) -> str:
    merged: list[Run] = []
    for r in runs:
        if not r.text:
            continue
        bold = r.bold and not in_heading
        run = Run(r.text, bold, r.italic, r.sup)
        # Espaços não mudam a formatação visível: evita <strong> </strong>.
        if merged and (merged[-1].fmt == run.fmt or not r.text.strip()):
            merged[-1].text += r.text
        else:
            merged.append(run)
    out = []
    for r in merged:
        lead = r.text[: len(r.text) - len(r.text.lstrip())]
        trail = r.text[len(r.text.rstrip()):]
        core = html.escape(r.text.strip(), quote=False)
        if core:
            if r.sup:
                core = f"<sup>{core}</sup>"
            if r.italic:
                core = f"<em>{core}</em>"
            if r.bold:
                core = f"<strong>{core}</strong>"
        out.append(f"{lead}{core}{trail}")
    return re.sub(r"\s+", " ", "".join(out)).strip()


def _apply(text: str, spans) -> str:
    for a, b, rep in sorted(spans, reverse=True):
        text = text[:a] + rep + text[b:]
    return text


def _annotate_runs(runs: list[Run], ann) -> list[Run]:
    """Aplica as substituições no texto corrido, mesmo que cruzem formatações."""
    text = "".join(r.text for r in runs)
    spans = ann(text)
    if not spans:
        return runs
    out: list[Run] = []
    pos = 0
    bounds = []                                    # (início, fim, run)
    for r in runs:
        bounds.append((pos, pos + len(r.text), r))
        pos += len(r.text)
    cut = 0
    for a, b, rep in sorted(spans):
        for s, e, r in bounds:                     # texto antes do trecho
            lo, hi = max(s, cut), min(e, a)
            if lo < hi:
                out.append(Run(text[lo:hi], r.bold, r.italic, r.sup))
        first = next((r for s, e, r in bounds if s <= a < e), runs[0])
        out.append(Run(rep, first.bold, first.italic, first.sup))
        cut = b
    for s, e, r in bounds:
        lo = max(s, cut)
        if lo < e:
            out.append(Run(text[lo:e], r.bold, r.italic, r.sup))
    return out


def _table(t: Table, ann=lambda t: []) -> str:
    rows = [(i, r) for i, r in enumerate(t.rows) if any(c for c in r)]
    if not rows:
        return ""
    th_rows = getattr(t, "th_rows", frozenset({0}))

    # Colunas cujo cabeçalho fala de Sanidade: "0/1D6" vira atalho de perda.
    san_cols = set()
    if getattr(ann, "rolls", False) and rows[0][0] in th_rows:
        san_cols = {k for k, c in enumerate(rows[0][1]) if SAN_HEADER.search(c)}

    def cell(c, tag, k):
        if tag == "th":
            return html.escape(c, quote=False)
        if k in san_cols and san_cell(c):
            return html.escape(san_cell(c), quote=False)
        return html.escape(_apply(c, ann(c)), quote=False)

    def tr(i, r):
        tag = "th" if i in th_rows else "td"
        return "<tr>" + "".join(f"<{tag}>{cell(c, tag, k)}</{tag}>" for k, c in enumerate(r)) + "</tr>"

    head = ""
    if rows[0][0] in th_rows and not any(i in th_rows for i, _ in rows[1:]):
        head = f"<thead>{tr(*rows[0])}</thead>"
        rows = rows[1:]
    body = "".join(tr(i, r) for i, r in rows)
    return f"<table>{head}<tbody>{body}</tbody></table>"
