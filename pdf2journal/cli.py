"""Linha de comando: pdf2journal livro.pdf --pages 12-20 --name "Capítulo 2"."""
from __future__ import annotations

import argparse
import html
import json
import re
import sys
import unicodedata
from pathlib import Path

import pymupdf

from .extract import Options, extract
from .foundry import journal_entry, macro_script
from .htmlout import render, split_pages


def parse_pages(spec: str | None, count: int) -> list[int]:
    """'1-3,7,10-' -> índices 0-based. Páginas contadas a partir de 1."""
    if not spec:
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


def slugify(text: str) -> str:
    text = unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode()
    return re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-") or "journal"


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="pdf2journal",
        description="Converte páginas de um PDF em um Journal do Foundry VTT (HTML refluído).",
    )
    p.add_argument("pdf", type=Path, help="arquivo PDF de origem")
    p.add_argument("-p", "--pages", help="páginas, ex.: 1-5,8,10- (padrão: todas)")
    p.add_argument("-n", "--name", help="nome do Journal (padrão: título do PDF ou nome do arquivo)")
    p.add_argument("-o", "--out", type=Path, default=Path("saida"), help="pasta de saída (padrão: ./saida)")
    p.add_argument("--split", choices=["page", "heading", "none"], default="page",
                   help="uma página do Journal por página do PDF (page), por título (heading) "
                        "ou tudo numa página só (none). Padrão: page")
    p.add_argument("--split-level", type=int, default=1, choices=[1, 2, 3],
                   help="com --split heading: nível máximo de título que abre página nova (padrão: 1)")
    p.add_argument("--asset-prefix",
                   help="caminho das imagens dentro da pasta Data do Foundry "
                        "(padrão: pdf2journal/<slug>)")
    p.add_argument("--dpi", type=int, default=150, help="resolução das imagens (padrão: 150)")
    p.add_argument("--image-format", choices=["webp", "jpg", "png"], default="webp")
    p.add_argument("--no-images", action="store_true", help="não extrair imagens")
    p.add_argument("--no-tables", action="store_true", help="não detectar tabelas")
    p.add_argument("--no-boxes", action="store_true", help="não converter quadros em citações")
    p.add_argument("--keep-headers", action="store_true",
                   help="manter cabeçalhos/rodapés repetidos e números de página")
    p.add_argument("--password", help="senha do PDF, se houver")
    return p


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if not args.pdf.is_file():
        print(f"erro: arquivo não encontrado: {args.pdf}", file=sys.stderr)
        return 2

    if hasattr(pymupdf, "no_recommend_layout"):
        pymupdf.no_recommend_layout()
    doc = pymupdf.open(args.pdf)
    if doc.needs_pass and not doc.authenticate(args.password or ""):
        print("erro: PDF protegido por senha (use --password)", file=sys.stderr)
        return 2
    try:
        pages = parse_pages(args.pages, doc.page_count)
    except ValueError as e:
        print(f"erro: {e}", file=sys.stderr)
        return 2

    meta_title = ((doc.metadata or {}).get("title") or "").strip()
    if meta_title.lower() in ("untitled", "sem título", "document", "documento"):
        meta_title = ""
    name = args.name or meta_title or args.pdf.stem
    slug = slugify(args.name or args.pdf.stem)
    prefix = (args.asset_prefix or f"pdf2journal/{slug}").strip("/")
    fmt = args.image_format
    if fmt == "webp":
        try:
            import PIL  # noqa: F401
        except ImportError:
            print("aviso: Pillow não instalado; usando JPG em vez de WebP", file=sys.stderr)
            fmt = "jpg"

    opts = Options(
        images=not args.no_images,
        tables=not args.no_tables,
        boxes=not args.no_boxes,
        strip_headers=not args.keep_headers,
        dpi=args.dpi,
        image_format=fmt,
    )
    out = args.out
    out.mkdir(parents=True, exist_ok=True)
    asset_dir = out / slug

    stream, ex = extract(doc, pages, opts, asset_dir, slug)
    jpages = split_pages(stream, args.split, args.split_level, name)

    foundry_pages = [(p.title, render(p.blocks, lambda f: f"{prefix}/{f}")) for p in jpages]
    entry = journal_entry(name, foundry_pages, source=args.pdf.name)

    json_path = out / f"{slug}.json"
    json_path.write_text(json.dumps(entry, ensure_ascii=False, indent=2), encoding="utf-8")
    macro_path = out / f"{slug}.macro.js"
    macro_path.write_text(macro_script(entry), encoding="utf-8")
    preview_path = out / f"{slug}.preview.html"
    preview_path.write_text(
        preview_html(name, [(p.title, render(p.blocks, lambda f: f"{slug}/{f}")) for p in jpages]),
        encoding="utf-8",
    )

    print(f"Journal: {name} — {len(jpages)} página(s), {len(ex.images_written)} imagem(ns)")
    print(f"  JSON (Importar Dados):  {json_path}")
    print(f"  Macro:                  {macro_path}")
    print(f"  Prévia no navegador:    {preview_path}")
    if ex.images_written:
        print(f"  Imagens: copie a pasta {asset_dir} para <Data do Foundry>/{prefix}")
    return 0


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


if __name__ == "__main__":
    sys.exit(main())
