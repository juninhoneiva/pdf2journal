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
| Quadros com fundo ou borda (boxes, notas do mestre) | `<blockquote>` |
| Tabelas | `<table>` |
| Ilustrações | Imagem WebP recortada da página |
| Capitulares (letra grande no início) | Juntadas ao parágrafo |
| Cabeçalhos, rodapés e números de página repetidos | Removidos |

## App para Windows

Baixe o `pdf2journal.exe` na página de
[Releases](https://github.com/juninhoneiva/pdf2journal/releases) (ou, para a
versão mais recente em desenvolvimento, no artefato `pdf2journal-windows` da
última execução do workflow **App Windows** na aba *Actions*). Não precisa
instalar Python.

1. **Abrir PDF…** (ou arraste o PDF sobre o `pdf2journal.exe`).
2. Marque as páginas nas miniaturas: clique para marcar, Shift+clique para um
   intervalo. Também dá para digitar no campo *Páginas* (`12-20,25`).
3. Ajuste o nome, a divisão e a pasta de saída e clique em **Gerar Journal**.
4. Use **Ver prévia** para conferir, **Abrir pasta** para pegar o `.json` e as
   imagens, ou **Copiar macro** para colar direto numa macro do Foundry.

O app lembra a pasta de saída e as opções da última conversão.

Para gerar uma versão publicada, crie uma tag `v*` (ex.: `v0.2.0`): o workflow
compila o `.exe`, testa e anexa à release.

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

# Tudo numa página só, com as imagens salvas dentro da pasta do mundo
pdf2journal livro.pdf -p 5 -n "Handout" --split none --asset-prefix worlds/meumundo/handouts
```

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
| `-o, --out` | Pasta de saída (padrão: `./saida`) |
| `--split page\|heading\|none` | Divisão em páginas do Journal (padrão: `page`) |
| `--split-level 1-3` | Com `--split heading`: nível de título que abre página nova |
| `--asset-prefix` | Caminho das imagens dentro da pasta Data do Foundry |
| `--dpi` | Resolução das imagens (padrão: 150) |
| `--image-format webp\|jpg\|png` | Formato das imagens (padrão: webp) |
| `--no-images`, `--no-tables`, `--no-boxes` | Desliga cada detecção |
| `--keep-headers` | Mantém cabeçalhos, rodapés e números de página |
| `--password` | Senha de PDF protegido |

## Limitações

- **PDFs escaneados** não têm texto: passe antes por um OCR (por exemplo,
  `ocrmypdf livro.pdf livro-ocr.pdf`).
- Ilustrações desenhadas em **vetor** (mapas, diagramas) não viram imagem;
  apenas as imagens bitmap são recortadas.
- A detecção de títulos usa o tamanho da fonte. Em livros com muitos estilos
  parecidos, confira a prévia e ajuste com `--split-level`.
- Texto sobre uma ilustração grande (mais de 300 caracteres) é mantido como
  texto e a ilustração é descartada; textos curtos (legendas de mapa) ficam só
  na imagem.

## Desenvolvimento

```bash
pip install -e .[dev]
pytest
```

Os testes geram um PDF sintético (`tests/make_sample.py`) com duas colunas,
box, lista, tabela, imagem, hifenização e cabeçalho/rodapé.
