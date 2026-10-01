"""Atalhos de rolagem do sistema Call of Cthulhu 7e (CoC7) para Foundry VTT.

Transforma menções a testes no texto do livro em links do sistema, que no
Foundry viram botões clicáveis:

    "um teste Difícil de Encontrar"  -> @coc7.check[subtype:skill,name:Encontrar,difficulty:+]{...}
    "teste de FOR"                   -> @coc7.check[subtype:characteristic,name:str]{...}
    "teste de Sorte"                 -> @coc7.check[subtype:attribute,name:lck]{...}
    "Perda de Sanidade: 0/1D6"       -> @coc7.sanloss[sanMin:0,sanMax:1D6]{...}

Sintaxe conferida no código do sistema (coc7/apps/link.js): ``subtype`` com
``characteristic | attribute | skill``, ``difficulty`` com ``0 | + | ++ | +++``
e ``poolModifier`` com o número de dados de bônus (+) ou penalidade (-).
Perícias são referenciadas pelo nome como está no livro; o CoC7 procura a
perícia com esse nome na ficha do investigador.
"""
from __future__ import annotations

import re

# Perícias do livro básico (7ª edição), em português e em inglês.
SKILLS_PT = [
    "Antropologia", "Arqueologia", "Arremessar", "Arte/Ofício", "Arte e Ofício", "Artilharia",
    "Avaliação", "Cavalgar", "Charme", "Chaveiro", "Ciência", "Consertos Elétricos",
    "Consertos Mecânicos", "Contabilidade", "Demolições", "Direito", "Dirigir Automóveis",
    "Dirigir Automóvel", "Disfarce", "Eletrônica", "Encontrar", "Escalar", "Escutar", "Esquivar",
    "Furtividade", "Hipnose", "História", "Intimidação", "Lábia", "Leitura Labial",
    "Lidar com Animais", "Treinar Animais", "Língua", "Lutar", "Medicina", "Mergulho",
    "Mitos de Cthulhu", "Mundo Natural", "Natação", "Nadar", "Navegação", "Nível de Crédito",
    "Ocultismo", "Operar Maquinário Pesado", "Operar Maquinário", "Persuasão", "Pilotar",
    "Prestidigitação", "Primeiros Socorros", "Psicanálise", "Psicologia", "Rastrear", "Saltar",
    "Sobrevivência", "Usar Bibliotecas", "Usar Computadores", "Armas de Fogo",
]
SKILLS_EN = [
    "Accounting", "Animal Handling", "Anthropology", "Appraise", "Archaeology", "Art/Craft",
    "Artillery", "Charm", "Climb", "Computer Use", "Credit Rating", "Cthulhu Mythos",
    "Demolitions", "Disguise", "Diving", "Dodge", "Drive Auto", "Electrical Repair",
    "Electronics", "Fast Talk", "Fighting", "Firearms", "First Aid", "History", "Hypnosis",
    "Intimidate", "Jump", "Language", "Law", "Library Use", "Listen", "Locksmith",
    "Mechanical Repair", "Medicine", "Natural World", "Navigate", "Occult",
    "Operate Heavy Machinery", "Persuade", "Pilot", "Psychoanalysis", "Psychology",
    "Read Lips", "Ride", "Science", "Sleight of Hand", "Spot Hidden", "Stealth", "Survival",
    "Swim", "Throw", "Track",
]
# Características: nome/abreviação -> chave do CoC7.
CHARACTERISTICS = {
    "FOR": "str", "Força": "str", "STR": "str", "Strength": "str",
    "CON": "con", "Constituição": "con", "Constitution": "con",
    "TAM": "siz", "Tamanho": "siz", "SIZ": "siz", "Size": "siz",
    "DES": "dex", "Destreza": "dex", "DEX": "dex", "Dexterity": "dex",
    "APA": "app", "Aparência": "app", "APP": "app", "Appearance": "app",
    "INT": "int", "Inteligência": "int", "Intelligence": "int",
    "POD": "pow", "Poder": "pow", "POW": "pow", "Power": "pow",
    "EDU": "edu", "Educação": "edu", "Education": "edu",
}
ATTRIBUTES = {
    "Sorte": "lck", "Luck": "lck",
    "Sanidade": "san", "SAN": "san", "Sanity": "san",
}
DIFFICULTY = {
    "regular": "0", "normal": "0",
    "difícil": "+", "dificil": "+", "hard": "+",
    "extremo": "++", "extrema": "++", "extreme": "++",
}
NUMBERS = {"um": 1, "uma": 1, "dois": 2, "duas": 2, "one": 1, "a": 1, "an": 1, "two": 2}


def _alt(names) -> str:
    return "|".join(re.escape(n) for n in sorted(names, key=len, reverse=True))


_DIFF = r"Regular|Normal|Dif[ií]cil|Extrem[oa]|Hard|Extreme"
_SPEC = rf"(?:\s*\((?!(?:{_DIFF})\))[^()]{{1,30}}\))?"            # especialização: "Ciência (Biologia)"
_NAME = (rf"(?P<name>(?:{_alt(SKILLS_PT + SKILLS_EN)}){_SPEC}"
         rf"|{_alt(CHARACTERISTICS)}|{_alt(ATTRIBUTES)})")
_DICE = r"\d*[dD]\d+(?:\s*[+-]\s*\d+)?|\d+"
_POOL = (r"(?:\s*,?\s*(?:com|with)\s+(?P<pool_n>um|uma|dois|duas|one|a|an|two|\d)\s+"
         r"(?P<pool_kind>dados?\s+de\s+b[ôo]nus|dados?\s+de\s+penalidade|bonus\s+dic?e|penalty\s+dic?e))?")

# "teste Difícil de Encontrar", "rolagem de FOR", "teste de Sorte (Difícil)"
CHECK_PT = re.compile(
    rf"\b(?P<kw>[Tt]este|[Rr]olagem|[Jj]ogada)(?:\s+(?P<d1>{_DIFF}))?\s+(?:de|em)\s+{_NAME}"
    rf"(?:\s*\((?P<d2>{_DIFF})\))?{_POOL}(?![\w/])")
# "Hard Spot Hidden roll", "Luck roll", "an Extreme DEX check"
CHECK_EN = re.compile(
    rf"\b(?:(?P<d1>{_DIFF})\s+)?{_NAME}\s+(?:roll|check)(?:\s*\((?P<d2>{_DIFF})\))?{_POOL}\b")
# Perda de Sanidade com os dois valores ("0/1D6")
SAN_BEFORE = re.compile(
    rf"\b(?P<kw>[Pp]erda\s+de\s+(?:Sanidade|SAN)|[Tt]este\s+de\s+(?:Sanidade|SAN)|"
    rf"[Rr]olagem\s+de\s+(?:Sanidade|SAN)|Sanity\s+(?:loss|roll|check)|SAN\s+(?:loss|roll)|SAN|Sanidade)"
    rf"\s*[:\-–]?\s*\(?\s*(?P<min>{_DICE})\s*/\s*(?P<max>{_DICE})\s*\)?"
    rf"(?:\s+(?:pontos\s+de\s+)?(?:Sanidade|SAN))?")
SAN_AFTER = re.compile(
    rf"\(?(?<![\w/])(?P<min>{_DICE})\s*/\s*(?P<max>{_DICE})\)?\s+(?:de\s+|pontos\s+de\s+)?"
    rf"(?:Sanidade|SAN|Sanity)(?:\s+(?:loss|perdid[oa]s?))?\b")


def _norm_dice(s: str) -> str:
    return re.sub(r"\s+", "", s).upper()


def _pool(m) -> str | None:
    if not m.groupdict().get("pool_n"):
        return None
    n = m.group("pool_n").lower()
    n = int(n) if n.isdigit() else NUMBERS.get(n, 1)
    sign = "-" if re.search(r"penal", m.group("pool_kind"), re.I) else "+"
    return f"{sign}{n}"


def _check_link(m) -> str | None:
    name = re.sub(r"\s+", " ", m.group("name")).strip()
    diff = m.group("d1") or m.group("d2")
    opts = []
    key = CHARACTERISTICS.get(name)
    if key:
        opts += ["subtype:characteristic", f"name:{key}"]
    elif name in ATTRIBUTES:
        opts += ["subtype:attribute", f"name:{ATTRIBUTES[name]}"]
    else:
        if any(c in name for c in ",[]{}:"):
            return None
        opts += ["subtype:skill", f"name:{name}"]
    if diff:
        opts.append(f"difficulty:{DIFFICULTY[diff.lower()]}")
    pool = _pool(m)
    if pool:
        opts.append(f"poolModifier:{pool}")
    label = m.group(0).replace("}", ")")
    return f"@coc7.check[{','.join(opts)}]{{{label}}}"


def _san_link(m, label: str) -> str:
    label = label.strip().replace("}", ")")
    return f"@coc7.sanloss[sanMin:{_norm_dice(m.group('min'))},sanMax:{_norm_dice(m.group('max'))}]{{{label}}}"


def find_rolls(text: str) -> list[tuple[int, int, str]]:
    """Trechos do texto que viram atalhos de rolagem: (início, fim, substituição)."""
    found: list[tuple[int, int, str]] = []

    def free(a, b):
        return all(b <= s or a >= e for s, e, _ in found)

    for rx in (SAN_BEFORE, SAN_AFTER):
        for m in rx.finditer(text):
            a, b = m.span()
            # Parêntese sem par fica fora do link: "(0/1D6 SAN" -> "0/1D6 SAN".
            seg = text[a:b]
            if seg.startswith("(") and seg.count("(") > seg.count(")"):
                a += 1
            elif seg.endswith(")") and seg.count(")") > seg.count("("):
                b -= 1
            while b > a and text[b - 1].isspace():
                b -= 1
            if free(a, b):
                found.append((a, b, _san_link(m, text[a:b])))
    for rx in (CHECK_PT, CHECK_EN):
        for m in rx.finditer(text):
            a, b = m.span()
            if not free(a, b):
                continue
            link = _check_link(m)
            if link:
                found.append((a, b, link))
    return sorted(found)


SAN_HEADER = re.compile(r"\b(?:SAN|Sanidade|Sanity)\b", re.I)
SAN_CELL = re.compile(rf"^\s*(?P<min>{_DICE})\s*/\s*(?P<max>{_DICE})\s*$")


def san_cell(text: str) -> str | None:
    """Célula "0/1D6" numa coluna de perda de Sanidade -> atalho sanloss."""
    m = SAN_CELL.match(text)
    return _san_link(m, text) if m else None
