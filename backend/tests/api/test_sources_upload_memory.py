"""What an upload holds in memory while it is examined and stored (audit 2026-11-14): never the
file, whatever its size - a bound per kind of file, read off the code, in both stores.

The file is 8 MiB, spooled as the form parser spools it. Each bound is the most the code keeps at
once, with a margin for the interpreter and the store's client:
- a PDF: two pieces of READ_PIECE (the one hashed, the next being read) - 2 MiB;
- a text of 4-byte signs: the same, and the decoder's output for one piece, which CPython's UTF-8
  decoder allocates as four bytes a sign for the piece's length (4 MiB) - 6 MiB;
- a DOCX whose directory is as large as allowed (thousands of parts with long entry comments):
  the pieces, the directory as zipfile reads it (up to MAX_DIRECTORY_BYTES, 1.22 MiB), each entry's
  name and comment copied out of it (the same again) and an object per entry (5,000 at most) -
  about 5 MiB;
- the worst directory the bound admits: 5,000 parts whose UTF-8 names and unicode-path fields hold
  a sign outside the BMP, which CPython keeps at four bytes a sign - the directory's 1.22 MiB held
  about four times over, the pieces and the objects - about 8 MiB.
Measured: 2.0, 6.0, 4.5 to 4.7 and 8.05 MiB, the same in both stores; under 9 MiB an upload.
"""

import hashlib
import tempfile
import tracemalloc
from collections.abc import Callable

import pytest
from starlette.datastructures import UploadFile

from app.api import sources
from app.sources.archives import MAX_DIRECTORY_BYTES
from app.sources.filetype import DOCX_MIME
from tests.api.test_sources_upload import PDF
from tests.api.upload_stores import UploadStore, upload_store
from tests.sources.zip_helpers import commented_parts, worst_names

pytestmark = pytest.mark.pg
__all__ = ["upload_store"]  # the fixture, taken over

SIZE = 8 * 2**20
MIB = 2**20
PARTS = 4900
# entry comments that fill the directory to just under its bound (an entry: 46 bytes and an 11-byte name)
COMMENT = MAX_DIRECTORY_BYTES // PARTS - 46 - 11 - 1


def heavy_directory() -> bytes:
    archive = commented_parts(PARTS, comment=COMMENT)
    return commented_parts(PARTS, comment=COMMENT, padding=SIZE - len(archive) - 200)


KINDS = [
    pytest.param(
        "lehrplan.pdf", lambda: PDF + b"x" * (SIZE - len(PDF)), "application/pdf", 3 * MIB, id="pdf"
    ),
    pytest.param(
        "lehrplan.txt", lambda: "\U0001d11e".encode() * (SIZE // 4), "text/plain", 7 * MIB, id="text"
    ),
    pytest.param("lehrplan.docx", heavy_directory, DOCX_MIME, 6 * MIB, id="docx-directory"),
    pytest.param(
        "lehrplan.docx", lambda: worst_names(MAX_DIRECTORY_BYTES), DOCX_MIME, 9 * MIB, id="docx-worst-names"
    ),
]


@pytest.mark.parametrize(("name", "make", "mime", "bound"), KINDS)
def test_an_upload_is_never_held_whole_in_memory(
    upload_store: UploadStore, name: str, make: Callable[[], bytes], mime: str, bound: int
) -> None:
    data = make()
    with tempfile.SpooledTemporaryFile(max_size=2**20) as spooled:  # as the form parser spools it
        spooled.write(data)
        spooled.seek(0)
        upload_file = UploadFile(spooled, size=len(data), filename=name)  # type: ignore[arg-type]
        digest_of_data = hashlib.sha256(data).digest()
        del data

        tracemalloc.start()
        try:
            detected, digest, examined = sources._examined(upload_file, 50 * MIB)
            upload_store.storage.put_file("sources/big", upload_file.file, examined)
            peak = tracemalloc.get_traced_memory()[1]
        finally:
            tracemalloc.stop()

    assert (detected.mime, digest) == (mime, digest_of_data)
    assert hashlib.sha256(upload_store.storage.get("sources/big")).digest() == digest
    assert peak < bound
