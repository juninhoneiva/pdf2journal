"""Links internos do Journal para as seções citadas no texto.

Exemplos que viram link do Foundry:

    "ver capítulo 3"        -> título "Capítulo 3: ..." do Journal
    "(veja Insanidade)"     -> título "Insanidade"
    "(ver página 45)"       -> página do Journal com a página 45 impressa do livro

O link usa um UUID relativo, ``@UUID[.<id da página>#<âncora>]{texto}``,
resolvido pelo Foundry a partir da página onde o link está (páginas irmãs do
mesmo Journal). Assim ele continua valendo quando o JSON é importado num
Journal já existente, que fica com outro ID.
"""
from __future__ import annotations

import re

from .extract import Box, Para

PREFIX = (r"(?:[Vv]er|[Vv]eja|[Vv]ide|[Cc]onsulte|[Cc]onsultar|[Cc]onforme|[Rr]eferir-se a|"
          r"[Ss]ee|[Rr]efer to|[Cc]f\.)")
SPELLED = {
    "um": 1, "dois": 2, "três": 3, "tres": 3, "quatro": 4, "cinco": 5, "seis": 6, "sete": 7,
    "oito": 8, "nove": 9, "dez": 10, "onze": 11, "doze": 12,
    "one": 1, "two": 2, "three": 3, "four": 4, "five": 5, "six": 6, "seven": 7, "eight": 8,
    "nine": 9, "ten": 10, "eleven": 11, "twelve": 12,
}
_NUM = r"\d{1,3}\b|[IVXLC]{1,7}\b|" + "|".join(rf"{w}\b" for w in sorted(SPELLED, key=len, reverse=True))
CHAPTER_TITLE = re.compile(rf"^\s*(?:cap[ií]tulo|chapter)\s+(?P<num>{_NUM})", re.I)
CHAPTER_REF = re.compile(
    rf"(?:\b{PREFIX}\s+(?:o\s+|the\s+)?|\()(?P<lab>(?:[Cc]ap[ií]tulo|CAP[ÍI]TULO|[Cc]ap\.|[Cc]hapter)"
    rf"\s+(?P<num>{_NUM}))")
PAGE_REF = re.compile(
    rf"(?:\b{PREFIX}\s+(?:a\s+|the\s+)?|\(|,\s*)(?P<lab>(?:[Pp][áa]gina|[Pp][áa]gs?\.|[Pp]\.|[Pp]age|[Pp]p\.)"
    rf"\s*(?P<num>\d{{1,4}}))\b")
HEADING_REF = re.compile(
    rf"\b{PREFIX}\s+(?:também\s+|also\s+)?(?:o\s+|a\s+|os\s+|as\s+|the\s+|em\s+|no\s+|na\s+)?[\"“‘']?")


def foundry_slug(text: str) -> str:
    """Âncora que o Foundry gera para um título (JournalEntryPage.slugifyHeading)."""
    s = re.sub(r"\s+", "-", text.strip().lower())
    return re.sub(r"[\"']", "", s)[:64]


def _roman(s: str) -> int | None:
    vals = {"I": 1, "V": 5, "X": 10, "L": 50, "C": 100}
    if not re.fullmatch(r"[IVXLC]+", s):
        return None
    total = 0
    for a, b in zip(s, s[1:] + " "):
        v = vals[a]
        total += -v if b in vals and vals[b] > v else v
    return total


def chapter_number(s: str) -> int | None:
    s = s.strip()
    if s.isdigit():
        return int(s)
    return _roman(s.upper()) if re.fullmatch(r"[IVXLCivxlc]+", s) else SPELLED.get(s.lower())


def _norm(text: str) -> str:
    return re.sub(r"\s+", " ", text).strip().lower()


def _headings(blocks):
    for b in blocks:
        if isinstance(b, Para) and b.kind.startswith("h"):
            yield re.sub(r"\s+", " ", b.text).strip()
        elif isinstance(b, Box):
            yield from _headings(b.children)


class Linker:
    def __init__(self, pages, printed: dict[int, int] | None = None):
        """``pages``: páginas do Journal (com ``id``, ``title``, ``blocks`` e
        ``pdf_pages``); ``printed``: número impresso no livro -> página do PDF."""
        by_name: dict[str, list[tuple[str, str]]] = {}
        self.chapters: dict[int, tuple[str, str]] = {}
        self.pdf_to_page: dict[int, str] = {}

        def add(name, target):
            by_name.setdefault(_norm(name), []).append((name, target))
            m = CHAPTER_TITLE.match(name)
            if m:
                n = chapter_number(m.group("num"))
                if n is not None:
                    self.chapters.setdefault(n, (name, target))

        for p in pages:
            add(p.title, f".{p.id}")
            for h in _headings(p.blocks):
                add(h, f".{p.id}#{foundry_slug(h)}")
            for n in p.pdf_pages:
                self.pdf_to_page.setdefault(n, p.id)
        # Títulos repetidos (ex.: "Ataques" em várias fichas) são ambíguos.
        self.headings = sorted(
            ((k, v[0][1]) for k, v in by_name.items() if len(v) == 1 and len(k) >= 4),
            key=lambda kv: len(kv[0]), reverse=True)
        self.printed = printed or {}

    def _page_target(self, num: int) -> str | None:
        pdf_page = self.printed.get(num)
        if pdf_page is None:
            return None
        pid = self.pdf_to_page.get(pdf_page)
        return f".{pid}" if pid else None

    def find(self, text: str) -> list[tuple[int, int, str]]:
        found: list[tuple[int, int, str]] = []

        def add(a, b, target):
            if a < b and all(b <= s or a >= e for s, e, _ in found):
                label = text[a:b].replace("}", ")")
                found.append((a, b, f"@UUID[{target}]{{{label}}}"))

        for m in CHAPTER_REF.finditer(text):
            n = chapter_number(m.group("num"))
            if n in self.chapters:
                add(*m.span("lab"), self.chapters[n][1])
        for m in PAGE_REF.finditer(text):
            target = self._page_target(int(m.group("num")))
            if target:
                add(*m.span("lab"), target)
        low = text.lower()
        for m in HEADING_REF.finditer(text):
            pos = m.end()
            for name, target in self.headings:
                end = pos + len(name)
                if low.startswith(name, pos) and (end >= len(text) or not text[end].isalnum()):
                    add(pos, end, target)
                    break
        return sorted(found)
