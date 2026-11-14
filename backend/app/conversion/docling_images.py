"""The page images Docling's models read, rendered as Docling 2.117 rendered them (plan M1 3b): pdfium at
1.5 times the scale asked for, scaled down to it - its text sharp, its lines smoothed.

Since Docling 2.124 its default backend for PDFs (ThreadedDoclingParseDocumentBackend) has docling-parse
render the page at the scale asked for. The layout model reads such an image otherwise: on the fixtures its
boxes come at some 0.5 to 0.6 where they came at 0.94 to 0.98, a page's paragraphs, its note and its second
heading run into one box, and a table's second part comes as a picture, its table at 0.47 below the 0.5
Docling keeps (prose.pdf, table_beside_text.pdf, measured in the converter's image: the same model files and
transformers, the same detections from either image processor on one image). The backend here is Docling's
own - docling-parse's words, lines and shapes, as the engine reads them (app/conversion/docling_blocks.py)
- with the image of a page drawn by pdfium, as before. The backend is built where Docling is installed: the
converter's image; ``render`` and ``draw_with_pdfium`` need only pypdfium2 and Pillow.
"""

import logging
import weakref
from contextlib import AbstractContextManager, nullcontext
from io import BytesIO
from pathlib import Path
from typing import Any

from PIL import Image

log = logging.getLogger(__name__)

RENDER_FACTOR = 1.5  # Docling 2.117's: drawn this much larger, then scaled down, "to make it sharper"
# How far pdfium's size of a page may lie from docling-parse's, in points, for the two to be one page:
# both round the crop box's edges, neither by more than a fraction of a point
SIZE_TOLERANCE = 0.5


def render(
    document: Any,
    index: int,
    size: tuple[float, float],
    scale: float,
    crop: tuple[float, float, float, float] | None = None,
    *,
    lock: AbstractContextManager[Any] | None = None,
) -> Image.Image | None:
    """Page ``index`` (counted from 0) of the pypdfium2 ``document`` - ``size`` its width and height in
    points as docling-parse measured it - at ``scale``, as Docling 2.117's DoclingParsePageBackend drew it:
    its region ``crop`` (left, top, right, bottom in points from the top left; None for all of it) drawn
    at RENDER_FACTOR times the scale, then scaled down to it. ``lock`` is held while pdfium draws.

    None where pdfium measures the page otherwise than ``size`` (more than SIZE_TOLERANCE either way): the
    crop and the scaling would then squeeze the page into the other's shape, and its image would not lie
    under docling-parse's words."""
    width, height = size
    left, top, right, bottom = crop if crop else (0.0, 0.0, width, height)
    with lock or nullcontext():
        page = document[index]
        try:
            drawn_width, drawn_height = page.get_size()
            if abs(drawn_width - width) > SIZE_TOLERANCE or abs(drawn_height - height) > SIZE_TOLERANCE:
                return None
            # pdfium's crop: what is cut off on the left, bottom, right and top
            bitmap = page.render(
                scale=scale * RENDER_FACTOR, rotation=0, crop=(left, height - bottom, width - right, top)
            )
            try:
                image: Image.Image = bitmap.to_pil().copy()
            finally:
                bitmap.close()
        finally:
            page.close()
    return image.resize(size=(round((right - left) * scale), round((bottom - top) * scale)))


def draw_with_pdfium(page: Any, document: Any, lock: AbstractContextManager[Any]) -> None:
    """Has Docling's page backend ``page`` draw its images by ``render`` from the pypdfium2 ``document``,
    and where pdfium measures the page otherwise, by its own ``get_page_image``, with one warning.

    The renderer holds the page's number and size, not the page: the page holds the renderer, and a page
    held back would be let go only by the cyclic collector, with its words and docling-parse's own image.
    Its own renderer it reaches by a weak reference, for the same reason."""
    number = page.page_no  # counted from 1
    measured = page.get_size()
    size = (measured.width, measured.height)
    native = weakref.WeakMethod(page.get_page_image)
    warned = False

    def get_page_image(scale: float = 1, cropbox: Any = None) -> Image.Image:
        nonlocal warned
        crop = cropbox.to_top_left_origin(size[1]).as_tuple() if cropbox else None
        image = render(document, number - 1, size, scale, crop, lock=lock)
        if image is not None:
            return image
        if not warned:
            warned = True
            log.warning(
                "pdfium measures page %d otherwise than docling-parse; docling-parse draws it", number
            )
        own = native()
        if own is None:  # the page that calls is alive; this is no call from it
            raise RuntimeError(f"the page backend of page {number} is gone")
        result: Image.Image = own(scale, cropbox)
        return result

    page.get_page_image = get_page_image


def pdfium_image_backend() -> type[Any]:
    """Docling's threaded docling-parse backend, its page images drawn by pdfium (the module's docstring)."""
    import pypdfium2
    from docling.backend.docling_parse_backend import ThreadedDoclingParseDocumentBackend
    from docling.utils.locks import pypdfium2_lock

    class PdfiumImageBackend(ThreadedDoclingParseDocumentBackend):  # type: ignore[misc]
        def __init__(self, in_doc: Any, path_or_stream: BytesIO | Path, options: Any = None) -> None:
            super().__init__(in_doc, path_or_stream, options)
            source = path_or_stream.getvalue() if isinstance(path_or_stream, BytesIO) else path_or_stream
            try:
                with pypdfium2_lock:
                    self._pdfium = pypdfium2.PdfDocument(source)
            except Exception:
                super().unload()
                raise

        def iter_pages(self) -> Any:
            for page in super().iter_pages():
                draw_with_pdfium(page, self._pdfium, pypdfium2_lock)
                yield page

        def unload(self) -> None:
            try:
                super().unload()
            finally:
                with pypdfium2_lock:
                    self._pdfium.close()

    return PdfiumImageBackend
