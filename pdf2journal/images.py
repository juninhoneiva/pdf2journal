"""Recorte de ilustrações pela área realmente visível na página.

A caixa que o PDF informa para uma imagem é a da imagem inteira, mesmo quando
ela está recortada por uma máscara (clipping) ou tem bordas transparentes. Para
achar a área visível, a página é renderizada em baixa resolução com e sem as
imagens candidatas, e a diferença entre as duas mostra onde elas aparecem de
fato.
"""
from __future__ import annotations

import math
import re

import pymupdf
from PIL import Image as PILImage
from PIL import ImageChops, ImageStat

PROBE_DPI = 48


def _pil(pix) -> PILImage.Image:
    return PILImage.frombytes("RGB", (pix.width, pix.height), pix.samples)


def _copy_page(doc, pno):
    d = pymupdf.open()
    d.insert_pdf(doc, from_page=pno, to_page=pno)
    return d


def _without_images(doc, pno, names: set[str]):
    """Cópia da página sem os comandos que desenham as imagens indicadas.

    Retorna a cópia e os nomes que de fato foram removidos.
    """
    d = _copy_page(doc, pno)
    page = d[0]
    targets: dict[int, set[str]] = {}
    for item in page.get_images(full=True):
        name, referencer = item[7], item[9]
        if name in names:
            targets.setdefault(referencer, set()).add(name)
    removed: set[str] = set()
    for ref, nms in targets.items():
        xrefs = page.get_contents() if ref == 0 else [ref]
        pattern = re.compile(rb"/(" + b"|".join(re.escape(n.encode()) for n in nms) + rb")\s+Do\b")
        for x in xrefs:
            stream = d.xref_stream(x)
            if not stream:
                continue
            removed |= {m.group(1).decode() for m in pattern.finditer(stream)}
            d.update_stream(x, pattern.sub(b"", stream))
    return d, removed


def visible_rects(doc, pno, infos) -> list[tuple | None]:
    """Área visível de cada imagem (``None`` se não aparece).

    ``infos`` vem de ``page.get_image_info(xrefs=True)``. Imagens embutidas
    no conteúdo (xref 0) mantêm a caixa informada.

    As imagens grandes (fundos, molduras) são analisadas uma a uma; as
    pequenas, todas juntas com as grandes no lugar. Assim um fundo de página
    não faz as ilustrações sobre ele parecerem ocupar a página inteira.
    """
    page = doc[pno]
    names = {}
    for item in page.get_images(full=True):
        names.setdefault(item[0], item[7])
    out: list = [tuple(i["bbox"]) for i in infos]
    known = [k for k, i in enumerate(infos) if i.get("xref") in names]
    if not known:
        return out
    parea = max(1.0, page.rect.width * page.rect.height)

    def area(r):
        return max(0.0, r[2] - r[0]) * max(0.0, r[3] - r[1])

    big = [k for k in known if area(infos[k]["bbox"]) > 0.3 * parea]
    small = [k for k in known if k not in big]
    groups = [[k] for k in big] + ([small] if small else [])
    try:
        with_imgs = _pil(page.get_pixmap(dpi=PROBE_DPI, alpha=False))
    except Exception:  # noqa: BLE001 - PDF estranho: usa a caixa informada
        return out
    for group in groups:
        wanted = {names[infos[k]["xref"]] for k in group}
        # Mesma imagem desenhada também fora do grupo: não dá para separar.
        if any(names[infos[k]["xref"]] in wanted for k in known if k not in group):
            continue
        try:
            stripped, removed = _without_images(doc, pno, wanted)
            without = _pil(stripped[0].get_pixmap(dpi=PROBE_DPI, alpha=False))
        except Exception:  # noqa: BLE001
            continue
        if with_imgs.size != without.size:
            continue
        mask = ImageChops.difference(with_imgs, without).convert("L").point(lambda v: 255 if v > 10 else 0)
        for k in group:
            if names[infos[k]["xref"]] in removed:
                out[k] = _visible(mask, infos[k]["bbox"], page.rect)
    return out


def _visible(mask, r, prect):
    z = PROBE_DPI / 72
    ox, oy = prect.x0, prect.y0
    box = (max(0, int((r[0] - ox) * z)), max(0, int((r[1] - oy) * z)),
           min(mask.width, math.ceil((r[2] - ox) * z)), min(mask.height, math.ceil((r[3] - oy) * z)))
    if box[2] <= box[0] or box[3] <= box[1]:
        return None
    bb = mask.crop(box).getbbox()
    if not bb:
        return None
    return (
        max(r[0], ox + (box[0] + bb[0]) / z - 1),
        max(r[1], oy + (box[1] + bb[1]) / z - 1),
        min(r[2], ox + (box[0] + bb[2]) / z + 1),
        min(r[3], oy + (box[1] + bb[3]) / z + 1),
    )


def is_flat(doc, pno, xref, rect) -> bool:
    """Imagem quase uniforme (textura de fundo, papel), sem ilustração.

    Olha os pixels da própria imagem; para imagens embutidas no conteúdo
    (sem xref), olha a região renderizada da página.
    """
    try:
        if xref:
            pix = pymupdf.Pixmap(doc, xref)
            while pix.width * pix.height > 250_000:
                pix.shrink(1)
            if pix.n - pix.alpha != 3:
                pix = pymupdf.Pixmap(pymupdf.csRGB, pix)
            if pix.alpha:
                pix = pymupdf.Pixmap(pix, 0)
        else:
            pix = doc[pno].get_pixmap(clip=pymupdf.Rect(rect), dpi=24, alpha=False)
    except Exception:  # noqa: BLE001
        return False
    if pix.width < 2 or pix.height < 2:
        return True
    return ImageStat.Stat(_pil(pix).convert("L")).stddev[0] < 8


def render(doc, pno, rect, dpi, erase: list[tuple]):
    """Renderiza o recorte, apagando antes o texto que já vai para o Journal."""
    if not erase:
        return doc[pno].get_pixmap(clip=pymupdf.Rect(rect), dpi=dpi, alpha=False)
    d = _copy_page(doc, pno)
    page = d[0]
    for r in erase:
        page.add_redact_annot(pymupdf.Rect(r[0], r[1] + 1, r[2], r[3] - 1), fill=False)
    page.apply_redactions(images=pymupdf.PDF_REDACT_IMAGE_NONE,
                          graphics=pymupdf.PDF_REDACT_LINE_ART_NONE,
                          text=pymupdf.PDF_REDACT_TEXT_REMOVE)
    return page.get_pixmap(clip=pymupdf.Rect(rect), dpi=dpi, alpha=False)
