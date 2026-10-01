# pdf2journal

Converte páginas de um PDF em um **Journal do Foundry VTT** (v11–v13), com o
texto refluído em HTML editável e tentando manter a estrutura da diagramação:

| No PDF | No Journal |
|---|---|
| Títulos (por tamanho de fonte) e linhas curtas em negrito | `<h1>`–`<h4>` |
| Duas ou mais colunas | Texto lido na ordem certa (coluna a coluna) |
| Parágrafo que continua na outra coluna/página | Parágrafo único |
| Palavras hifenizadas no fim da linha | Palavra inteira |
| Negrito, itálico, sobrescrito | `<strong>`, `<em>`, `<sup>` |
| Listas com marcadores ou numeradas | `<ul>` / `<ol>` |
| Quadros com fundo, borda ou moldura (boxes, notas do mestre) | `<blockquote>` com todo o texto do quadro junto |
| Boxes cujo fundo é uma imagem (pergaminho, papel envelhecido) | `<blockquote>`, sem a imagem de fundo |
| Box que continua na página seguinte | Um box só (com `--split heading` ou `none`) |
| Ornamentos (Dingbats, vinhetas, `* * *`), arabescos, cantoneiras | Ignorados |
| Tabelas com grade | `<table>` |
| Tabelas sem grade (colunas alinhadas, linhas sombreadas) | `<table>` reconstruída pelo alinhamento |
| Fichas de criatura (`FOR 80 CON 65 …`, `STR DEX CON …`) | Tabela de características |
| Linhas "Rótulo: valor" das fichas | Um parágrafo por linha |
| Ilustrações | Imagem WebP recortada só na área visível (respeita máscaras e transparência) |
| Texto que encosta na ilustração | Fica no Journal e é apagado de dentro da imagem |
| Fundos, molduras e ornamentos repetidos | Ignorados |
| Capitulares (letra grande no início) | Juntadas ao parágrafo |
| Título do capítulo repetido em toda página, rodapés, números de página | Removidos |
| Abas laterais com texto vertical | Removidas |
| "teste Difícil de Encontrar", "rolagem de FOR", "Luck roll" | Atalho de rolagem do CoC7 (`@coc7.check`) |
| "teste de Sanidade (0/1D6)", "Perda de Sanidade: 1/1D8", coluna "Perda de SAN" | Atalho de perda de Sanidade (`@coc7.sanloss`) |
| "ver capítulo 3", "veja Insanidade", "(página 45)" | Link para o título ou a página do Journal (`@UUID`) |

### Atalhos de rolagem do CoC7

Menções a testes no texto viram botões do sistema
[Call of Cthulhu 7e](https://github.com/Miskatonic-Investigative-Society/CoC7-FoundryVTT):

- **Perícias:** `teste de Escutar`, `teste Difícil de Encontrar`, `teste de Ciência (Biologia)`,
  `Hard Spot Hidden roll` → `@coc7.check[subtype:skill,name:Encontrar,difficulty:+]`.
  O nome da perícia é o que está no livro; o CoC7 procura a perícia com esse
  nome na ficha do investigador.
- **Características e atributos:** `teste de FOR`, `rolagem de Sorte (Extremo)`,
  `Luck roll`.
- **Dificuldade e dados extras:** Regular/Difícil/Extremo e "com um dado de
  bônus/penalidade".
- **Perda de Sanidade:** `teste de Sanidade (0/1D6)`, `Perda de Sanidade: 1/1D8`,
  `1D3/1D10 de Sanidade`, e as células de colunas "Perda de SAN" em tabelas
  → `@coc7.sanloss[sanMin:0,sanMax:1D6]`.

Desligue com `--no-rolls` ou desmarcando **Atalhos de rolagem (CoC7)** no app.

### Links para seções citadas

Referências como "ver capítulo 3", "(Capítulo III)", "veja Insanidade
Temporária", "see Chapter three" e "(página 45)" viram links do Foundry para o
título ou a página do Journal correspondente. Só vira link o que estiver dentro
das páginas convertidas; o resto fica como texto. Para "página 45" o app usa o
número impresso no rodapé do livro, não o número da página do PDF.

Os links são relativos (`@UUID[.<id da página>#<âncora>]`), então continuam
funcionando ao importar o `.json` num Journal existente. Desligue com
`--no-links` ou desmarcando **Links para seções citadas**.

## App para Windows

Baixe o `pdf2journal.exe` na página de
[Releases](https://github.com/juninhoneiva/pdf2journal/releases) (ou, para a
versão mais recente em desenvolvimento, no artefato `pdf2journal-windows` da
última execução do workflow **App Windows** na aba *Actions*). Não precisa
instalar Python.

1. **Abrir PDF…** (ou arraste o PDF sobre o `pdf2journal.exe`).
2. Marque as páginas nas miniaturas: clique para marcar, Shift+clique para um
   intervalo. Também dá para digitar no campo *Páginas* (`12-20,25`).
3. Em **Foundry**, confira a **Pasta Data** (detectada sozinha quando o
   Foundry está instalado no lugar padrão) e escolha a **Pasta do mundo** na
   lista (ou digite o nome da pasta, como aparece em `Data/worlds`).
4. Ajuste o nome e a divisão e clique em **Gerar Journal**. Tudo é salvo em
   `Data/worlds/<mundo>/pdf2journal/`: o `.json`, a macro, a prévia e a pasta
   com as imagens, que já ficam no lugar certo para o Foundry.
5. No Foundry, crie um Journal vazio → botão direito → **Importar Dados** →
   escolha o `.json` (ou use **Copiar macro** e cole numa macro do tipo Script).

Use **Ver prévia** para conferir antes de importar. O app lembra a pasta Data,
o mundo e as opções da última conversão.

Se o Foundry roda em outro computador ou num serviço de hospedagem, aponte a
**Pasta Data** para uma pasta qualquer no seu computador e depois envie a pasta
`worlds/<mundo>/pdf2journal` para o mesmo caminho no servidor.

Para publicar uma versão, crie uma release no GitHub (*Releases → Draft a new
release*, com uma tag nova como `v0.2.0`): o workflow compila o `.exe`, testa e
anexa à release.

## Instalação (linha de comando)

Requer Python 3.9 ou superior.

```bash
pip install .
```

Isso instala também o app de janela, que abre com `pdf2journal-gui`.

## Uso

```bash
# Capítulo 2 (páginas 12 a 20), uma página do Journal por página do PDF
pdf2journal livro.pdf --pages 12-20 --name "Capítulo 2"

# Uma página do Journal por título de nível 1 ou 2, juntando o texto entre páginas
pdf2journal livro.pdf -p 12-40 -n "Cenário" --split heading --split-level 2

# Grava direto na pasta do mundo: Data/worlds/meu-mundo/pdf2journal/
pdf2journal livro.pdf -p 5 -n "Handout" --world meu-mundo --data "C:/Users/eu/AppData/Local/FoundryVTT/Data"
```

Com `--world` e `--data`, o `.json` e as imagens vão direto para
`<Data>/worlds/<mundo>/pdf2journal/` e não é preciso copiar nada. Só com
`--world`, os arquivos saem em `-o` e as imagens devem ser copiadas para
`Data/worlds/<mundo>/pdf2journal/<nome>`.

A saída vai para `./saida` (mude com `-o`):

```
saida/
  capitulo-2.json          # Journal no formato de exportação do Foundry
  capitulo-2.macro.js      # alternativa: macro que cria o Journal
  capitulo-2.preview.html  # prévia para abrir no navegador antes de importar
  capitulo-2/              # imagens
```

### Importando no Foundry

1. **Imagens:** copie a pasta `saida/capitulo-2` para
   `<pasta Data do Foundry>/pdf2journal/capitulo-2` (ou para o caminho que você
   passou em `--asset-prefix`). Também dá para enviar os arquivos pelo
   navegador de arquivos do Foundry, desde que o caminho fique o mesmo.
2. **Journal:** use uma das opções:
   - Na aba *Journal*, crie um Journal vazio, clique nele com o botão direito
     → **Importar Dados** e escolha o `capitulo-2.json`;
   - ou crie uma macro do tipo **Script**, cole o conteúdo de
     `capitulo-2.macro.js` e execute como GM.

### Opções

| Opção | Descrição |
|---|---|
| `-p, --pages` | Páginas do PDF, contadas a partir de 1: `1-5,8,10-` (padrão: todas) |
| `-n, --name` | Nome do Journal (padrão: título do PDF ou nome do arquivo) |
| `-w, --world` | Pasta do mundo (`Data/worlds/<mundo>`): imagens em `worlds/<mundo>/pdf2journal/<nome>` |
| `--data` | Pasta Data do Foundry; com `--world`, grava tudo direto na pasta do mundo |
| `-o, --out` | Pasta de saída quando não se usa `--data` (padrão: `./saida`) |
| `--split page\|heading\|none` | Divisão em páginas do Journal (padrão: `page`) |
| `--split-level 1-3` | Com `--split heading`: nível de título que abre página nova |
| `--asset-prefix` | Caminho das imagens dentro da pasta Data do Foundry |
| `--dpi` | Resolução das imagens (padrão: 150) |
| `--image-format webp\|jpg\|png` | Formato das imagens (padrão: webp) |
| `--no-images`, `--no-tables`, `--no-boxes` | Desliga cada detecção |
| `--no-rolls` | Não cria atalhos de rolagem do CoC7 |
| `--no-links` | Não cria links para seções citadas |
| `--keep-headers` | Mantém cabeçalhos, rodapés e números de página |
| `--password` | Senha de PDF protegido |

## Limitações

- **PDFs escaneados** não têm texto: passe antes por um OCR (por exemplo,
  `ocrmypdf livro.pdf livro-ocr.pdf`).
- Ilustrações desenhadas em **vetor** (mapas, diagramas) não viram imagem;
  apenas as imagens bitmap são recortadas.
- Tabelas sem grade são reconhecidas pelo alinhamento das colunas; tabelas
  muito irregulares (células com várias linhas em colunas diferentes) podem
  sair como parágrafos.
- A detecção de títulos usa o tamanho da fonte. Em livros com muitos estilos
  parecidos, confira a prévia e ajuste com `--split-level`.
- Texto sobre uma ilustração grande (mais de 300 caracteres) é mantido como
  texto e a ilustração é descartada; textos curtos inteiramente dentro da
  imagem (legendas de mapa) ficam só na imagem.

## Desenvolvimento

```bash
pip install -e .[dev]
pytest
```

Os testes geram um PDF sintético (`tests/make_sample.py`) com duas colunas,
box, lista, tabela, imagem, hifenização e cabeçalho/rodapé.
