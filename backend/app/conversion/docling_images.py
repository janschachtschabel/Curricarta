"""The page images Docling's models read, rendered as Docling 2.117 rendered them (plan M1 3b): pdfium at
1.5 times the scale asked for, scaled down to it - its text sharp, its lines smoothed.

Since Docling 2.124 its default backend for PDFs (ThreadedDoclingParseDocumentBackend) has docling-parse
render the page at the scale asked for. The layout model reads such an image otherwise: on the fixtures its
boxes come at some 0.5 to 0.6 where they came at 0.94 to 0.98, a page's paragraphs, its note and its second
heading run into one box, and a table's second part comes as a picture, its table at 0.47 below the 0.5
Docling keeps (prose.pdf, table_beside_text.pdf, measured in the converter's image: the same model files and
transformers, the same detections from either image processor on one image). The backend here is Docling's
own - docling-parse's words, lines and shapes, as the engine reads them (app/conversion/docling_blocks.py)
- with the image of a page drawn by pdfium, as before. It is built where Docling is installed: the
converter's image.
"""

from io import BytesIO
from pathlib import Path
from typing import Any

RENDER_FACTOR = 1.5  # Docling 2.117's: drawn this much larger, then scaled down, "to make it sharper"


def pdfium_image_backend() -> type[Any]:
    """Docling's threaded docling-parse backend, its page images drawn by pdfium (the module's docstring)."""
    import pypdfium2
    from docling.backend.docling_parse_backend import ThreadedDoclingParseDocumentBackend
    from docling.utils.locks import pypdfium2_lock
    from docling_core.types.doc import BoundingBox, CoordOrigin

    class PdfiumImageBackend(ThreadedDoclingParseDocumentBackend):  # type: ignore[misc]
        def __init__(self, in_doc: Any, path_or_stream: BytesIO | Path, options: Any = None) -> None:
            super().__init__(in_doc, path_or_stream, options)
            source = path_or_stream.getvalue() if isinstance(path_or_stream, BytesIO) else path_or_stream
            with pypdfium2_lock:
                self._pdfium = pypdfium2.PdfDocument(source)

        def iter_pages(self) -> Any:
            for page in super().iter_pages():
                page.get_page_image = _renderer(self._pdfium, page)
                yield page

        def unload(self) -> None:
            super().unload()
            with pypdfium2_lock:
                self._pdfium.close()

    def _renderer(document: Any, page: Any) -> Any:
        def get_page_image(scale: float = 1, cropbox: Any = None) -> Any:
            # Docling 2.117's DoclingParsePageBackend.get_page_image, word for word in what it does
            size = page.get_size()
            if not cropbox:
                cropbox = BoundingBox(l=0, r=size.width, t=0, b=size.height, coord_origin=CoordOrigin.TOPLEFT)
                padbox = BoundingBox(l=0, r=0, t=0, b=0, coord_origin=CoordOrigin.BOTTOMLEFT)
            else:
                padbox = cropbox.to_bottom_left_origin(size.height).model_copy()
                padbox.r = size.width - padbox.r
                padbox.t = size.height - padbox.t
            with pypdfium2_lock:
                drawn = document[page.page_no - 1]  # Docling counts its pages from 1
                bitmap = drawn.render(scale=scale * RENDER_FACTOR, rotation=0, crop=padbox.as_tuple())
                image = bitmap.to_pil().copy()
                bitmap.close()
                drawn.close()
            return image.resize(size=(round(cropbox.width * scale), round(cropbox.height * scale)))

        return get_page_image

    return PdfiumImageBackend
