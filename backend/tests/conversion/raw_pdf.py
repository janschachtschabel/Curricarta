"""Hand-built PDFs for what reportlab does not write: a page tree that lies, odd content streams,
odd fonts. Each test builds the bytes it needs; none of them is checked in."""

HELVETICA = b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica /Encoding /WinAnsiEncoding >>"
# Enough signs on a page for its text layer to count (app/conversion/text_layer.py)
SENTENCE = b"BT /F1 11 Tf 72 700 Td (Die Lernenden planen und pruefen ihre Arbeit sorgfaeltig.) Tj ET\n"


def pdf_of(objects: list[bytes]) -> bytes:
    """A PDF of these objects, numbered from 1 - the first is the catalog - with its cross-references."""
    out = bytearray(b"%PDF-1.7\n")
    offsets = []
    for number, body in enumerate(objects, start=1):
        offsets.append(len(out))
        out += b"%d 0 obj\n" % number + body + b"\nendobj\n"
    xref = len(out)
    out += b"xref\n0 %d\n0000000000 65535 f \n" % (len(objects) + 1)
    for offset in offsets:
        out += b"%010d 00000 n \n" % offset
    out += b"trailer\n<< /Size %d /Root 1 0 R >>\nstartxref\n%d\n%%%%EOF\n" % (len(objects) + 1, xref)
    return bytes(out)


def stream(content: bytes) -> bytes:
    return b"<< /Length %d >>\nstream\n" % len(content) + content + b"\nendstream"


# A grey pixel, drawn as /Im1 at any size (image)
PIXEL = b"<< /Type /XObject /Subtype /Image /Width 1 /Height 1 /ColorSpace /DeviceGray /BitsPerComponent 8"
PIXEL += b" /Length 1 >>\nstream\n\x80\nendstream"


def image(x: float, y: float, width: float, height: float) -> bytes:
    """The content that draws /Im1 over a box of the page, from its bottom left."""
    return b"q %g 0 0 %g %g %g cm /Im1 Do Q\n" % (width, height, x, y)


def pages_pdf(contents: list[bytes], *, count: int | None = None) -> bytes:
    """A PDF with an A4 page for each content stream, Helvetica as /F1 and a grey pixel as /Im1;
    ``count``: the number of pages its page tree claims, where it should claim more than it holds."""
    kids = b" ".join(b"%d 0 R" % (5 + 2 * index) for index in range(len(contents)))
    objects = [
        b"<< /Type /Catalog /Pages 2 0 R >>",
        b"<< /Type /Pages /Kids [%s] /Count %d >>" % (kids, len(contents) if count is None else count),
        HELVETICA,
        PIXEL,
    ]
    for index, content in enumerate(contents):
        objects.append(
            b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 595 842] /Resources"
            b" << /Font << /F1 3 0 R >> /XObject << /Im1 4 0 R >> >> /Contents %d 0 R >>" % (6 + 2 * index)
        )
        objects.append(stream(content))
    return pdf_of(objects)


def form_pdf(content: bytes, form: bytes, *, matrix: bytes = b"") -> bytes:
    """A PDF of one A4 page that draws ``content``, a Form XObject /Fm1 of ``form`` (its /Matrix ``matrix``)
    and the grey pixel /Im1 at hand."""
    objects = [
        b"<< /Type /Catalog /Pages 2 0 R >>",
        b"<< /Type /Pages /Kids [6 0 R] /Count 1 >>",
        HELVETICA,
        PIXEL,
        b"<< /Type /XObject /Subtype /Form /BBox [0 0 10000 10000] "
        + matrix
        + b" /Resources << /XObject << /Im1 4 0 R >> >> /Length %d >>\nstream\n" % len(form)
        + form
        + b"\nendstream",
        b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 595 842] /Resources"
        b" << /Font << /F1 3 0 R >> /XObject << /Im1 4 0 R /Fm1 5 0 R >> >> /Contents 7 0 R >>",
        stream(content),
    ]
    return pdf_of(objects)


def nested_forms_pdf(content: bytes, forms: list[bytes]) -> bytes:
    """A PDF of one A4 page that draws ``content``; /Fn is the first of ``forms``, and in each form the next,
    each with the grey pixel /Im1 at hand."""
    first = 5
    objects = [
        b"<< /Type /Catalog /Pages 2 0 R >>",
        b"<< /Type /Pages /Kids [%d 0 R] /Count 1 >>" % (first + len(forms)),
        HELVETICA,
        PIXEL,
    ]
    for at, form in enumerate(forms):
        following = b" /Fn %d 0 R" % (first + at + 1) if at + 1 < len(forms) else b""
        objects.append(
            b"<< /Type /XObject /Subtype /Form /BBox [-10000 -10000 10000 10000]"
            b" /Resources << /XObject << /Im1 4 0 R%s >> >> /Length %d >>\nstream\n"
            % (following, len(form))
            + form
            + b"\nendstream"
        )
    objects.append(
        b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 595 842] /Resources"
        b" << /Font << /F1 3 0 R >> /XObject << /Im1 4 0 R /Fn %d 0 R >> >> /Contents %d 0 R >>"
        % (first, first + len(forms) + 1)
    )
    objects.append(stream(content))
    return pdf_of(objects)
