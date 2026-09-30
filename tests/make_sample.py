"""Gera um PDF sintético com os casos que o conversor precisa tratar."""
from pathlib import Path

import pymupdf

W, H = 612, 792
L, R, GUT = 54, 558, 18
COLW = (R - L - GUT) / 2
C1, C2 = L, L + COLW + GUT


def lines(page, x, y, rows, size=10, font="helv", lead=1.35):
    for row in rows:
        f = font
        if isinstance(row, tuple):
            row, f = row
        page.insert_text((x, y), row, fontname=f, fontsize=size)
        y += size * lead
    return y


def furniture(page, n):
    page.insert_text((L, 30), "Manual do Guardião — Suplemento", fontname="helv", fontsize=8)
    page.insert_text((W / 2, H - 24), str(n), fontname="helv", fontsize=8)


def build(path: Path):
    doc = pymupdf.open()

    # ---------------- página 1: título + duas colunas + box + lista -------- #
    p = doc.new_page(width=W, height=H)
    furniture(p, 1)
    p.insert_text((L, 80), "Capítulo Um", fontname="hebo", fontsize=24)

    y = lines(p, C1, 120, [
        "Os investigadores chegam a Arkham numa noite",
        "fria de outubro. A cidade parece adormecida,",
        "mas algo se move nas sombras da universi-",
        "dade, onde livros proibidos aguardam.",
    ])
    y = lines(p, C1 + 12, y + 2, ["O bibliotecário Armitage recebe o grupo com"])
    y = lines(p, C1, y, [
        "desconfiança e pede silêncio absoluto. Ele",
        "mostra o caminho até a sala de leitura e",
    ])
    # continua na coluna 2 (parágrafo quebrado entre colunas)
    y2 = lines(p, C2, 120, [
        "fecha a porta atrás de si.",
    ])
    y2 = lines(p, C2, y2 + 10, ["A Biblioteca Orne"], size=15, font="hebo")
    y2 = lines(p, C2, y2 + 2, [
        "Os corredores são estreitos e cheios de pó.",
        "Três coisas chamam a atenção:",
    ])
    y2 = lines(p, C2, y2 + 4, [
        "• um tomo encadernado em couro;",
        "• uma lanterna ainda quente;",
        "• pegadas molhadas no chão.",
    ])

    # box com fundo
    box = pymupdf.Rect(C1, 330, R, 420)
    p.draw_rect(box, color=(0.4, 0.2, 0.1), fill=(0.9, 0.85, 0.7))
    lines(p, C1 + 10, 350, [("Nota do Guardião", "hebo")], size=11)
    lines(p, C1 + 10, 368, [
        "Se os investigadores lerem o tomo, peça um teste de Sanidade (0/1D4).",
        "Um sucesso extremo revela a localização da cripta.",
    ])

    lines(p, C1, 450, [
        "Depois da biblioteca, o grupo segue para o cemitério.",
    ])

    # ---------------- página 2: tabela + imagem ---------------------------- #
    p = doc.new_page(width=W, height=H)
    furniture(p, 2)
    p.insert_text((L, 80), "Tabela de Encontros", fontname="hebo", fontsize=15)
    rows = [("1D6", "Encontro"), ("1-2", "Carniçal faminto"),
            ("3-4", "Cultista armado"), ("5-6", "Nada acontece")]
    x0, x1, xm, top, rh = L, L + 300, L + 60, 95, 18
    for i, (a, b) in enumerate(rows):
        yy = top + i * rh
        p.insert_text((x0 + 4, yy + 13), a, fontname="hebo" if i == 0 else "helv", fontsize=10)
        p.insert_text((xm + 4, yy + 13), b, fontname="hebo" if i == 0 else "helv", fontsize=10)
    for i in range(len(rows) + 1):
        p.draw_line((x0, top + i * rh), (x1, top + i * rh))
    for x in (x0, xm, x1):
        p.draw_line((x, top), (x, top + len(rows) * rh))

    pix = pymupdf.Pixmap(pymupdf.csRGB, pymupdf.IRect(0, 0, 200, 120), 0)
    pix.set_rect(pix.irect, (120, 30, 30))
    p.insert_image(pymupdf.Rect(L, 200, L + 200, 320), pixmap=pix)
    lines(p, L, 345, [
        "A ilustração acima mostra a entrada da cripta.",
        ("Esta frase está em itálico.", "heit"),
    ])

    # ---------------- página 3: texto simples ------------------------------ #
    p = doc.new_page(width=W, height=H)
    furniture(p, 3)
    lines(p, L, 80, [
        "Epílogo: os sobreviventes recuperam 1D6 de Sanidade.",
    ])

    doc.set_metadata({"title": "Aventura de Teste"})
    doc.save(path)
    return path


if __name__ == "__main__":
    build(Path("sample.pdf"))
