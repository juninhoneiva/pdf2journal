"""Casos de livro de RPG: cabeçalho repetido, recorte de imagens e fichas."""
import json
import sys
from pathlib import Path

import pytest
from PIL import Image

sys.path.insert(0, str(Path(__file__).parent))
from make_rpg_sample import build  # noqa: E402

from pdf2journal.cli import main  # noqa: E402
from pdf2journal.tables import stat_table_from_text  # noqa: E402


@pytest.fixture(scope="module")
def result(tmp_path_factory):
    tmp = tmp_path_factory.mktemp("rpg")
    pdf = build(tmp / "rpg.pdf")
    assert main([str(pdf), "-o", str(tmp / "out")]) == 0
    entry = json.loads((tmp / "out" / "rpg.json").read_text(encoding="utf-8"))
    return entry, tmp / "out" / "rpg"


def test_running_head_and_side_tab_removed(result):
    entry, _ = result
    text = json.dumps(entry, ensure_ascii=False)
    assert "CAPÍTULO 3" not in text
    assert "BESTIÁRIO" not in text
    assert [p["name"] for p in entry["pages"]] == [
        "Criaturas dos Mitos", "Página 2", "Página 3", "Página 4", "Página 5"]


def test_images_cropped_to_visible_area(result):
    entry, assets = result
    files = sorted(p.name for p in assets.iterdir())
    # o fundo de pergaminho repetido não vira imagem
    assert len(files) == 2
    sizes = {Image.open(assets / f).size for f in files}
    # ilustração mascarada: visível 220x90 pt (a imagem inteira tem 220x220)
    # PNG transparente: miolo opaco de 100x100 pt (a imagem inteira tem 200x200)
    # (folga de ~8 px: margem de 1 pt + resolução da sondagem)
    at150 = lambda pt: round(pt * 150 / 72)  # noqa: E731
    for w, h in [(220, 90), (100, 100)]:
        assert any(abs(sw - at150(w)) <= 16 and abs(sh - at150(h)) <= 16 for sw, sh in sizes), sizes
    p1 = entry["pages"][0]["text"]["content"]
    assert "O texto continua abaixo da ilustração" in p1


def test_creature_sheet(result):
    entry, _ = result
    p2 = entry["pages"][1]["text"]["content"]
    assert "<tr><th>FOR</th><th>CON</th><th>TAM</th><th>DES</th><th>INT</th></tr>" in p2
    assert "<tr><td>80</td><td>65</td><td>65</td><td>65</td><td>65</td></tr>" in p2
    assert "<p>Bônus de Dano: +1D4</p>" in p2
    assert "<p>Corpo: 1</p>" in p2
    assert "<p>Luta 40% (20/8), dano 1D6 + BD</p>" in p2


def test_shaded_table_without_grid(result):
    entry, _ = result
    p2 = entry["pages"][1]["text"]["content"]
    assert "<thead><tr><th>1D6</th><th>Encontro</th><th>Perda de SAN</th></tr></thead>" in p2
    assert "<tr><td>3-4</td><td>Bando de carniçais</td><td>@coc7.sanloss[sanMin:1,sanMax:1D8]{1/1D8}</td></tr>" in p2


def test_stat_line_formats():
    t = stat_table_from_text("FOR 50 CON 60 TAM 65 DES 70 INT 80 POD 55")
    assert t.rows == [["FOR", "CON", "TAM", "DES", "INT", "POD"], ["50", "60", "65", "70", "80", "55"]]
    t = stat_table_from_text("STR DEX CON INT WIS CHA 18 (+4) 14 (+2) 16 (+3) 10 (+0) 12 (+1) 8 (-1)")
    assert t.rows[0] == ["STR", "DEX", "CON", "INT", "WIS", "CHA"] and t.rows[1][0] == "18 (+4)"
    assert stat_table_from_text("O investigador tem FOR alta e gosta de CON.") is None


def test_chapter_title_repeated_mid_page(tmp_path):
    """Título do capítulo reimpresso fora da margem: fica só a primeira vez."""
    import pymupdf

    doc = pymupdf.open()
    for i in range(3):
        p = doc.new_page(width=612, height=792)
        p.insert_text((54, 130), "Os Mitos de Cthulhu", fontname="hebo", fontsize=20)
        p.insert_text((54, 170), f"Texto da página {i + 1} sobre os mitos.", fontsize=10)
        p.insert_text((54, 185), f"Continuação {i + 1} do texto comum.", fontsize=10)
    pdf = tmp_path / "mitos.pdf"
    doc.save(pdf)
    assert main([str(pdf), "-o", str(tmp_path / "out"), "--split", "none"]) == 0
    html = json.loads((tmp_path / "out" / "mitos.json").read_text(encoding="utf-8"))["pages"][0]["text"]["content"]
    assert html.count("Os Mitos de Cthulhu") == 1
    assert "Texto da página 3" in html


def test_single_page_ignores_flat_background(tmp_path):
    """Com uma página só não dá para ver o fundo repetido: vale a textura uniforme."""
    pdf = build(tmp_path / "rpg.pdf")
    assert main([str(pdf), "-p", "1", "-o", str(tmp_path / "out")]) == 0
    assert len(list((tmp_path / "out" / "rpg").iterdir())) == 2


def test_coc7_rolls_and_links(result):
    entry, _ = result
    p2_id = entry["pages"][1]["_id"]
    p2 = entry["pages"][1]["text"]["content"]
    p3 = entry["pages"][2]["text"]["content"]
    assert "@coc7.sanloss[sanMin:0,sanMax:1D6]{teste de Sanidade (0/1D6)}" in p3
    assert "@coc7.check[subtype:skill,name:Encontrar,difficulty:+]{teste Difícil de Encontrar}" in p3
    assert "@coc7.check[subtype:characteristic,name:str]{rolagem de FOR}" in p3
    # título citado -> âncora do título na página 2; página impressa 42 -> página 2
    assert f"@UUID[.{p2_id}#encontros-no-cemitério]{{Encontros no Cemitério}}" in p3
    assert f"@UUID[.{p2_id}]{{página 42}}" in p3
    # coluna "Perda de SAN" da tabela de encontros
    assert "<td>@coc7.sanloss[sanMin:1,sanMax:1D8]{1/1D8}</td>" in p2
    # na ficha: "Perda de Sanidade: 0/1D6"
    assert "@coc7.sanloss[sanMin:0,sanMax:1D6]{Perda de Sanidade: 0/1D6}" in p2


def test_no_rolls_no_links(tmp_path):
    pdf = build(tmp_path / "rpg.pdf")
    assert main([str(pdf), "-o", str(tmp_path / "out"), "--no-rolls", "--no-links"]) == 0
    text = (tmp_path / "out" / "rpg.json").read_text(encoding="utf-8")
    assert "@coc7" not in text and "@UUID" not in text


def test_chapter_references():
    from pdf2journal.htmlout import JournalPage
    from pdf2journal.links import Linker
    from pdf2journal.extract import Para, Run

    pages = [JournalPage("Capítulo 3: Monstros", id="AAAAAAAAAAAAAAAA", pdf_pages=[10]),
             JournalPage("Introdução", [Para("h2", [Run("Insanidade Temporária")])],
                         id="BBBBBBBBBBBBBBBB", pdf_pages=[11])]
    linker = Linker(pages, printed={9: 10})

    def apply(text):
        for a, b, rep in reversed(linker.find(text)):
            text = text[:a] + rep + text[b:]
        return text

    assert apply("ver capítulo III.") == "ver @UUID[.AAAAAAAAAAAAAAAA]{capítulo III}."
    assert apply("(Capítulo 3)") == "(@UUID[.AAAAAAAAAAAAAAAA]{Capítulo 3})"
    assert apply("see Chapter three") == "see @UUID[.AAAAAAAAAAAAAAAA]{Chapter three}"
    assert apply("veja Insanidade Temporária, página 9") == (
        "veja @UUID[.BBBBBBBBBBBBBBBB#insanidade-temporária]{Insanidade Temporária}, "
        "@UUID[.AAAAAAAAAAAAAAAA]{página 9}")
    # capítulo que não foi convertido: fica como texto
    assert apply("ver capítulo 7") == "ver capítulo 7"


def test_glyphs_and_decorations_ignored(result):
    entry, assets = result
    p4 = entry["pages"][3]["text"]["content"]
    # ornamentos de fonte Dingbats e "* * *" não viram texto
    assert "uuu" not in p4 and "*" not in p4
    # divisória fina e cantoneira na margem não viram imagem
    assert not any(f.name.startswith("rpg-p004") for f in assets.iterdir())


def test_image_box_keeps_text_together(result):
    entry, _ = result
    p4 = entry["pages"][3]["text"]["content"]
    box = p4.split("</blockquote>")[0]
    assert box.startswith("<blockquote><h3>Nota sobre Carniçais</h3>")
    assert "preferem cercar a presa" in box and "líder do bando" in box
    # a coluna ao lado fica fora do box
    assert "coluna ao lado" not in box and "coluna ao lado" in p4


def test_line_frame_is_box(result):
    entry, _ = result
    p5 = entry["pages"][4]["text"]["content"]
    assert "<blockquote><h3>Dica para o Guardião</h3>" in p5
    assert "Fim do capítulo." not in p5.split("Dica para o Guardião")[1].split("</blockquote>")[0]


def test_box_continues_across_pages(tmp_path):
    pdf = build(tmp_path / "rpg.pdf")
    assert main([str(pdf), "-p", "4-5", "--split", "none", "-o", str(tmp_path / "out")]) == 0
    html = json.loads((tmp_path / "out" / "rpg.json").read_text(encoding="utf-8"))["pages"][0]["text"]["content"]
    assert "conhecem os atalhos e ganham um dado de bônus" in html
    assert html.count("<blockquote>") == 3


def test_glyph_filter_cases():
    from pdf2journal.extract import _without_glyphs

    def line(*spans):
        return {"bbox": (0, 0, 100, 10), "spans": [
            {"text": t, "font": f, "bbox": (i * 10, 0, i * 10 + 9, 10), "size": 10, "flags": 0}
            for i, (t, f) in enumerate(spans)]}

    def text(ln):
        r = _without_glyphs(ln)
        return None if r is None else "".join(s["text"] for s in r["spans"])

    assert text(line(("● Primeiro item", "Helvetica"))) == "• Primeiro item"
    assert text(line(("n", "ZapfDingbats"), (" item", "Helvetica"))).strip() == "•  item".strip()
    assert text(line(("❦ ❦ ❦", "Helvetica"))) is None
    assert text(line(("FOR —", "Helvetica"))) == "FOR —"          # traço de ficha fica
    assert text(line(("Texto� com lixo", "Helvetica"))) == "Texto com lixo"
