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
    assert [p["name"] for p in entry["pages"]] == ["Criaturas dos Mitos", "Página 2", "Página 3"]


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
    assert "<tr><td>3-4</td><td>Bando de carniçais</td><td>1/1D8</td></tr>" in p2


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
