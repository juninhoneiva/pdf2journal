"""Pós-processamento do fluxo de blocos e geração de HTML."""
from __future__ import annotations

import html
import re
from dataclasses import dataclass, field

from .extract import SENTENCE_END, Box, Image, PageBreak, Para, Run, Table


@dataclass
class JournalPage:
    title: str
    blocks: list = field(default_factory=list)


# --------------------------------------------------------------------------- #
# Limpeza do fluxo
# --------------------------------------------------------------------------- #
def tidy(blocks: list, across_pages: bool) -> list:
    """Aplica capitulares e junta parágrafos quebrados entre colunas/páginas."""
    out: list = []
    pending_drop = ""
    last_para_idx = None
    for b in blocks:
        if isinstance(b, Box):
            out.append(Box(tidy(b.children, across_pages=False)))
            last_para_idx = None
            continue
        if isinstance(b, PageBreak):
            out.append(b)
            if not across_pages:
                last_para_idx = None
            continue
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
                cur = JournalPage(f"Página {b.number}")
                pages.append(cur)
            elif cur is not None:
                cur.blocks.append(b)
        for p in pages:
            first = p.blocks[0] if p.blocks else None
            if isinstance(first, Para) and first.kind.startswith("h"):
                p.title = _plain(first)
                p.blocks.pop(0)
        return [p for p in pages if p.blocks or p.title]

    blocks = [b for b in tidy(stream, across_pages=True) if not isinstance(b, PageBreak)]
    if mode == "none":
        return [JournalPage(name, blocks)]

    # mode == "heading"
    pages: list[JournalPage] = []
    cur = JournalPage(name)
    for b in blocks:
        if isinstance(b, Para) and b.kind.startswith("h") and int(b.kind[1]) <= split_level:
            if cur.blocks or cur.title != name:
                pages.append(cur)
            cur = JournalPage(_plain(b))
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
def render(blocks: list, img_src) -> str:
    """``img_src(file) -> str`` resolve o caminho de cada imagem."""
    parts: list[str] = []
    i = 0
    while i < len(blocks):
        b = blocks[i]
        if isinstance(b, Para) and b.kind == "li":
            tag = "ol" if b.ordered else "ul"
            items = []
            while (i < len(blocks) and isinstance(blocks[i], Para)
                   and blocks[i].kind == "li" and blocks[i].ordered == b.ordered):
                items.append(f"<li>{runs_html(blocks[i].runs)}</li>")
                i += 1
            parts.append(f"<{tag}>{''.join(items)}</{tag}>")
            continue
        if isinstance(b, Para):
            tag = b.kind if b.kind.startswith("h") else "p"
            parts.append(f"<{tag}>{runs_html(b.runs, in_heading=tag != 'p')}</{tag}>")
        elif isinstance(b, Table):
            parts.append(_table(b))
        elif isinstance(b, Image):
            w = round(b.width_pt * 96 / 72)
            parts.append(f'<p><img src="{html.escape(img_src(b.file))}" width="{w}"></p>')
        elif isinstance(b, Box):
            parts.append(f"<blockquote>{render(b.children, img_src)}</blockquote>")
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


def _table(t: Table) -> str:
    rows = [r for r in t.rows if any(c for c in r)]
    if not rows:
        return ""
    head = "".join(f"<th>{html.escape(c, quote=False)}</th>" for c in rows[0])
    body = "".join(
        "<tr>" + "".join(f"<td>{html.escape(c, quote=False)}</td>" for c in r) + "</tr>"
        for r in rows[1:]
    )
    return f"<table><thead><tr>{head}</tr></thead><tbody>{body}</tbody></table>"
