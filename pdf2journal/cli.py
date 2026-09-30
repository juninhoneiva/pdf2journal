"""Linha de comando: pdf2journal livro.pdf --pages 12-20 --name "Capítulo 2"."""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

from .convert import ConversionError, Settings, convert
from .extract import Options


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
    settings = Settings(
        pdf=args.pdf,
        pages=args.pages,
        name=args.name,
        out=args.out,
        split=args.split,
        split_level=args.split_level,
        asset_prefix=args.asset_prefix,
        password=args.password,
        options=Options(
            images=not args.no_images,
            tables=not args.no_tables,
            boxes=not args.no_boxes,
            strip_headers=not args.keep_headers,
            dpi=args.dpi,
            image_format=args.image_format,
        ),
    )
    try:
        result = convert(settings, warn=lambda m: print(f"aviso: {m}", file=sys.stderr))
    except ConversionError as e:
        print(f"erro: {e}", file=sys.stderr)
        return 2
    for line in result.summary():
        print(line)
    return 0


if __name__ == "__main__":
    sys.exit(main())
