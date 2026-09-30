import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent))
from make_sample import build  # noqa: E402

from pdf2journal.cli import main, parse_pages  # noqa: E402


@pytest.fixture(scope="module")
def sample(tmp_path_factory):
    return build(tmp_path_factory.mktemp("pdf") / "sample.pdf")


def run(sample, tmp_path, *extra):
    assert main([str(sample), "-o", str(tmp_path), *extra]) == 0
    return json.loads((tmp_path / "sample.json").read_text(encoding="utf-8"))


def test_parse_pages():
    assert parse_pages(None, 3) == [0, 1, 2]
    assert parse_pages("1-2,5,7-", 8) == [0, 1, 4, 6, 7]
    with pytest.raises(ValueError):
        parse_pages("9", 3)


def test_page_mode(sample, tmp_path):
    entry = run(sample, tmp_path)
    assert entry["name"] == "Aventura de Teste"
    names = [p["name"] for p in entry["pages"]]
    assert names == ["Capítulo Um", "Tabela de Encontros", "Página 3"]
    p1 = entry["pages"][0]["text"]["content"]
    # colunas lidas na ordem certa, hifenização desfeita, parágrafo unido entre colunas
    assert "sombras da universidade, onde" in p1
    assert "sala de leitura e fecha a porta" in p1
    assert p1.index("Armitage") < p1.index("A Biblioteca Orne")
    assert "<h2>A Biblioteca Orne</h2>" in p1
    assert "<li>um tomo encadernado em couro;</li>" in p1
    assert "<blockquote><h4>Nota do Guardião</h4>" in p1
    # cabeçalho repetido e número de página removidos
    assert "Suplemento" not in json.dumps(entry, ensure_ascii=False)
    p2 = entry["pages"][1]["text"]["content"]
    assert "<th>1D6</th>" in p2 and "<td>Carniçal faminto</td>" in p2
    assert '<img src="pdf2journal/sample/sample-p002-01.webp"' in p2
    assert "<em>Esta frase está em itálico.</em>" in p2
    assert (tmp_path / "sample" / "sample-p002-01.webp").is_file()
    assert (tmp_path / "sample.macro.js").read_text(encoding="utf-8").startswith("//")


def test_page_range_and_none_split(sample, tmp_path):
    entry = run(sample, tmp_path, "-p", "2-3", "--split", "none", "--no-images",
                "--asset-prefix", "worlds/x")
    assert len(entry["pages"]) == 1
    html = entry["pages"][0]["text"]["content"]
    assert "Arkham" not in html and "Epílogo" in html and "<img" not in html


def test_heading_split(sample, tmp_path):
    entry = run(sample, tmp_path, "--split", "heading", "--split-level", "2")
    names = [p["name"] for p in entry["pages"]]
    assert names == ["Capítulo Um", "A Biblioteca Orne", "Tabela de Encontros"]
