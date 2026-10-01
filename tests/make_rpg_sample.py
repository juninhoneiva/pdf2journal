"""PDF sintético no estilo de livro de RPG.

Reproduz os problemas vistos em livros reais: título do capítulo repetido no
topo de toda página, fundo de pergaminho repetido, ilustração recortada por
máscara (clipping), PNG com transparência, ficha de criatura em box e tabela
de rolagem com linhas sombreadas (sem grade).
"""
from pathlib import Path

import pymupdf

W, H = 612, 792
L, R, GUT = 54, 558, 18
COLW = (R - L - GUT) / 2
C1, C2 = L, L + COLW + GUT
PARCH = (0.96, 0.92, 0.82)


def text(page, x, y, s, size=10, font="helv", color=(0, 0, 0)):
    page.insert_text((x, y), s, fontname=font, fontsize=size, color=color)


def lines(page, x, y, rows, size=10, font="helv"):
    for row in rows:
        text(page, x, y, row, size, font)
        y += size * 1.35
    return y


def parchment():
    pix = pymupdf.Pixmap(pymupdf.csRGB, pymupdf.IRect(0, 0, 60, 80), 0)
    pix.set_rect(pix.irect, tuple(int(c * 255) for c in PARCH))
    for x in range(0, 60, 7):                      # textura, para não ser cor lisa
        pix.set_rect(pymupdf.IRect(x, 0, x + 1, 80), (235, 225, 200))
    return pix


def page_frame(doc, n, bg):
    p = doc.new_page(width=W, height=H)
    p.insert_image(p.rect, pixmap=bg)             # fundo repetido
    text(p, L, 36, "CAPÍTULO 3: CRIATURAS DOS MITOS", 14, "hebo", (0.45, 0.1, 0.1))
    text(p, W / 2, H - 24, str(40 + n), 9)
    # aba lateral com texto vertical
    p.draw_rect(pymupdf.Rect(W - 22, 300, W, 420), color=None, fill=(0.45, 0.1, 0.1))
    p.insert_text((W - 8, 400), "BESTIÁRIO", fontsize=9, rotate=90, color=(1, 1, 1))
    return p


def illustration(w, h, color):
    pix = pymupdf.Pixmap(pymupdf.csRGB, pymupdf.IRect(0, 0, w, h), 0)
    pix.set_rect(pix.irect, color)
    pix.set_rect(pymupdf.IRect(w // 4, h // 4, w // 2, h // 2), (20, 20, 20))
    return pix


def transparent_art(w, h):
    """PNG com transparência: só o miolo é opaco."""
    pix = pymupdf.Pixmap(pymupdf.csRGB, pymupdf.IRect(0, 0, w, h), 1)
    pix.set_rect(pix.irect, (0, 0, 0, 0))
    pix.set_rect(pymupdf.IRect(w // 4, h // 4, 3 * w // 4, 3 * h // 4), (30, 90, 40, 255))
    return pix


def build(path: Path):
    doc = pymupdf.open()
    bg = parchment()

    # ---------------- página 1 ---------------------------------------------- #
    p = page_frame(doc, 1, bg)
    text(p, L, 90, "Criaturas dos Mitos", 24, "hebo")
    lines(p, C1, 125, [
        "As criaturas a seguir podem ser usadas em",
        "qualquer cenário. Cada uma traz uma ficha",
        "com as características e os ataques.",
    ])
    # Ilustração maior do que a área visível: recortada por um clipping path.
    # Imagem de 220x220 pt, visível só a faixa central de 220x90.
    art = pymupdf.Rect(C2, 120, C2 + 220, 340)
    xref = p.insert_image(art, pixmap=illustration(220, 220, (140, 40, 40)))
    contents = p.get_contents()
    last = contents[-1]
    stream = doc.xref_stream(last)
    y_pdf = H - 275                                   # visível: y 185..275
    doc.update_stream(last, f"q {art.x0} {y_pdf} 220 90 re W n ".encode() + stream + b" Q")
    lines(p, C2, 300, [
        "O texto continua abaixo da ilustração, na",
        "segunda coluna, sem ser engolido por ela.",
    ])
    # PNG com transparência, na coluna 1
    p.insert_image(pymupdf.Rect(C1, 190, C1 + 200, 390), pixmap=transparent_art(200, 200))
    lines(p, C1, 420, ["Um carniçal espreita nas sombras."])
    del xref

    # ---------------- página 2: ficha de criatura --------------------------- #
    p = page_frame(doc, 2, bg)
    box = pymupdf.Rect(L, 70, R, 330)
    p.draw_rect(box, color=(0.45, 0.1, 0.1), fill=(0.9, 0.84, 0.7), width=1.5)
    text(p, L + 12, 92, "CARNIÇAL, devorador de cadáveres", 12, "hebo")
    lines(p, L + 12, 110, ["Criaturas de aparência canina que vivem em túneis sob cemitérios."])
    # características em grade, cada par posicionado numa coluna
    stats = [("FOR", "80"), ("CON", "65"), ("TAM", "65"), ("DES", "65"), ("INT", "65"),
             ("POD", "65"), ("APA", "-"), ("EDU", "-"), ("SAN", "-"), ("PV", "13")]
    for i, (k, v) in enumerate(stats):
        x = L + 12 + (i % 5) * 95
        y = 140 + (i // 5) * 16
        text(p, x, y, k, 10, "hebo")
        text(p, x + 32, y, v, 10)
    y = lines(p, L + 12, 190, [
        "Bônus de Dano: +1D4",
        "Corpo: 1",
        "Movimento: 9",
    ])
    lines(p, L + 12, y + 6, [
        "Ataques por rodada: 3 (garras, mordida)",
        "Luta 40% (20/8), dano 1D6 + BD",
        "Perda de Sanidade: 0/1D6 pontos por ver um carniçal.",
    ])

    # tabela de rolagem com linhas sombreadas, sem grade
    text(p, L, 370, "Encontros no Cemitério", 14, "hebo")
    rows = [("1D6", "Encontro", "Perda de SAN"),
            ("1-2", "Carniçal solitário", "0/1D6"),
            ("3-4", "Bando de carniçais", "1/1D8"),
            ("5-6", "Nada acontece", "-")]
    for i, row in enumerate(rows):
        top = 382 + i * 18
        if i % 2 == 0:
            p.draw_rect(pymupdf.Rect(L, top, L + 360, top + 18), color=None, fill=(0.85, 0.78, 0.62))
        for x, cell in zip((L + 6, L + 70, L + 250), row):
            text(p, x, top + 13, cell, 10, "hebo" if i == 0 else "helv")
    lines(p, L, 470, ["Role na tabela sempre que o grupo cruzar o cemitério à noite."])

    # ---------------- página 3 ---------------------------------------------- #
    p = page_frame(doc, 3, bg)
    lines(p, L, 90, [
        "Os carniçais evitam a luz e fogem de chamas.",
        "Ao ver um carniçal, peça um teste de Sanidade (0/1D6).",
        "Um teste Difícil de Encontrar revela as pegadas.",
        "Para os encontros, veja Encontros no Cemitério (página 42).",
        "Uma rolagem de FOR abre a cripta.",
    ])

    doc.set_metadata({"title": "Bestiário de Teste"})
    doc.save(path)
    return path


if __name__ == "__main__":
    build(Path("rpg_sample.pdf"))
