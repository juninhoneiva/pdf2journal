"""Conversão PDF -> Journal, compartilhada pela linha de comando e pelo app."""
from __future__ import annotations

import html
import json
import re
import unicodedata
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable

import pymupdf

from .extract import Options, extract
from .foundry import journal_entry, macro_script
from .htmlout import render, split_pages

GENERIC_TITLES = ("untitled", "sem título", "document", "documento")


class ConversionError(Exception):
    """Erro com mensagem pronta para mostrar ao usuário."""


@dataclass
class Settings:
    pdf: Path
    pages: str | list[int] | None = None    # "1-5,8" (1-based) ou índices 0-based
    name: str | None = None
    out: Path = Path("saida")
    split: str = "page"                      # page | heading | none
    split_level: int = 1
    asset_prefix: str | None = None
    password: str | None = None
    options: Options = field(default_factory=Options)
    # Mundo do Foundry: com ``world`` as imagens são referenciadas em
    # worlds/<mundo>/pdf2journal/; com ``data_dir`` também os arquivos são
    # gravados direto em <Data>/worlds/<mundo>/pdf2journal/.
    world: str | None = None
    data_dir: Path | None = None


@dataclass
class Result:
    name: str
    pages: int
    images: int
    json_path: Path
    macro_path: Path
    preview_path: Path
    asset_dir: Path
    asset_prefix: str
    in_foundry: bool = False           # arquivos gravados direto na pasta Data

    def summary(self) -> list[str]:
        lines = [
            f"Journal: {self.name} — {self.pages} página(s), {self.images} imagem(ns)",
            f"  JSON (Importar Dados):  {self.json_path}",
            f"  Macro:                  {self.macro_path}",
            f"  Prévia no navegador:    {self.preview_path}",
        ]
        if self.images and self.in_foundry:
            lines.append(f"  Imagens: já estão em Data/{self.asset_prefix}")
        elif self.images:
            lines.append(f"  Imagens: copie a pasta {self.asset_dir} para "
                         f"<Data do Foundry>/{self.asset_prefix}")
        return lines


def parse_pages(spec: str | None, count: int) -> list[int]:
    """'1-3,7,10-' -> índices 0-based. Páginas contadas a partir de 1."""
    if not spec or not spec.strip():
        return list(range(count))
    out: list[int] = []
    for part in spec.replace(" ", "").split(","):
        if not part:
            continue
        m = re.fullmatch(r"(\d*)-(\d*)|(\d+)", part)
        if not m:
            raise ValueError(f"intervalo de páginas inválido: {part!r}")
        if m.group(3):
            a = b = int(m.group(3))
        else:
            a = int(m.group(1) or 1)
            b = int(m.group(2) or count)
        if a < 1 or b > count or a > b:
            raise ValueError(f"páginas {part!r} fora do PDF (1-{count})")
        out.extend(i - 1 for i in range(a, b + 1) if i - 1 not in out)
    return out


def format_pages(indices: list[int]) -> str:
    """Índices 0-based -> '1-3,7' (inverso de ``parse_pages``)."""
    parts, run = [], []
    for i in sorted(set(indices)):
        if run and i == run[-1] + 1:
            run.append(i)
            continue
        if run:
            parts.append(_fmt_run(run))
        run = [i]
    if run:
        parts.append(_fmt_run(run))
    return ",".join(parts)


def _fmt_run(run):
    return str(run[0] + 1) if len(run) == 1 else f"{run[0] + 1}-{run[-1] + 1}"


def default_data_dir() -> Path | None:
    """Pasta Data padrão do Foundry VTT, se existir nesta máquina."""
    import os
    candidates = []
    if os.environ.get("LOCALAPPDATA"):
        candidates.append(Path(os.environ["LOCALAPPDATA"]) / "FoundryVTT" / "Data")
    home = Path.home()
    candidates += [
        home / "AppData" / "Local" / "FoundryVTT" / "Data",
        home / "Library" / "Application Support" / "FoundryVTT" / "Data",
        home / ".local" / "share" / "FoundryVTT" / "Data",
    ]
    return next((c for c in candidates if c.is_dir()), None)


def list_worlds(data_dir: Path | str | None) -> list[str]:
    """Pastas de mundo dentro de <Data>/worlds, em ordem alfabética."""
    if not data_dir:
        return []
    worlds = Path(data_dir) / "worlds"
    try:
        return sorted((p.name for p in worlds.iterdir() if p.is_dir()), key=str.casefold)
    except OSError:
        return []


def world_output_dir(data_dir: Path, world: str) -> Path:
    return Path(data_dir) / "worlds" / world / "pdf2journal"


def slugify(text: str) -> str:
    text = unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode()
    return re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-") or "journal"


def open_pdf(path: Path, password: str | None = None) -> pymupdf.Document:
    if hasattr(pymupdf, "no_recommend_layout"):
        pymupdf.no_recommend_layout()
    if not Path(path).is_file():
        raise ConversionError(f"arquivo não encontrado: {path}")
    try:
        doc = pymupdf.open(path)
    except Exception as e:  # noqa: BLE001
        raise ConversionError(f"não foi possível abrir o PDF: {e}") from e
    if doc.needs_pass and not doc.authenticate(password or ""):
        raise ConversionError("PDF protegido por senha")
    return doc


def default_name(doc: pymupdf.Document, path: Path) -> str:
    title = ((doc.metadata or {}).get("title") or "").strip()
    return "" if title.lower() in GENERIC_TITLES else title or Path(path).stem


def convert(s: Settings, warn: Callable[[str], None] = lambda m: None) -> Result:
    doc = open_pdf(s.pdf, s.password)
    if isinstance(s.pages, list):
        pages = [p for p in s.pages if 0 <= p < doc.page_count]
    else:
        try:
            pages = parse_pages(s.pages, doc.page_count)
        except ValueError as e:
            raise ConversionError(str(e)) from e
    if not pages:
        raise ConversionError("nenhuma página selecionada")

    name = (s.name or "").strip() or default_name(doc, s.pdf) or Path(s.pdf).stem
    slug = slugify((s.name or "").strip() or Path(s.pdf).stem)
    world = (s.world or "").strip().strip("/\\")
    if world and not re.fullmatch(r"[\w.-]+", world):
        raise ConversionError(f"nome de pasta de mundo inválido: {world!r}")
    default_prefix = f"worlds/{world}/pdf2journal/{slug}" if world else f"pdf2journal/{slug}"
    prefix = ((s.asset_prefix or "").strip() or default_prefix).strip("/")
    out = Path(s.out)
    in_foundry = bool(world and s.data_dir)
    if in_foundry:
        out = world_output_dir(Path(s.data_dir), world)

    opts = s.options
    if opts.image_format == "webp":
        try:
            import PIL  # noqa: F401
        except ImportError:
            warn("Pillow não instalado; usando JPG em vez de WebP")
            opts = Options(**{**opts.__dict__, "image_format": "jpg"})

    out.mkdir(parents=True, exist_ok=True)
    asset_dir = out / slug

    stream, ex = extract(doc, pages, opts, asset_dir, slug)
    jpages = split_pages(stream, s.split, s.split_level, name)

    entry = journal_entry(
        name, [(p.title, render(p.blocks, lambda f: f"{prefix}/{f}")) for p in jpages],
        source=Path(s.pdf).name,
    )
    json_path = out / f"{slug}.json"
    json_path.write_text(json.dumps(entry, ensure_ascii=False, indent=2), encoding="utf-8")
    macro_path = out / f"{slug}.macro.js"
    macro_path.write_text(macro_script(entry), encoding="utf-8")
    preview_path = out / f"{slug}.preview.html"
    preview_path.write_text(
        preview_html(name, [(p.title, render(p.blocks, lambda f: f"{slug}/{f}")) for p in jpages]),
        encoding="utf-8",
    )
    return Result(name, len(jpages), len(ex.images_written), json_path, macro_path,
                  preview_path, asset_dir, prefix, in_foundry)


def preview_html(name: str, pages: list[tuple[str, str]]) -> str:
    body = "\n".join(
        f'<article><h1 class="page-title">{html.escape(t)}</h1>\n{c}\n</article>' for t, c in pages
    )
    return f"""<!doctype html>
<html lang="pt-BR"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>{html.escape(name)}</title>
<style>
body{{margin:0;background:#2b2b2b;font:15px/1.5 Signika,system-ui,sans-serif;color:#191813}}
article{{max-width:820px;margin:24px auto;padding:24px 32px;background:#f4f1e9;border-radius:4px}}
.page-title{{border-bottom:2px solid #782e22;color:#782e22}}
h1,h2,h3,h4{{font-family:"Modesto Condensed",Georgia,serif}}
img{{max-width:100%;height:auto}}
blockquote{{margin:1em 0;padding:.5em 1em;background:#e6dfcd;border-left:4px solid #782e22}}
table{{border-collapse:collapse;width:100%}}
th,td{{border:1px solid #b5ab94;padding:3px 6px;text-align:left}}
th{{background:#d8cfb8}}
</style></head><body>
{body}
</body></html>
"""
