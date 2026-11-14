"""``python -m app.conversion.fetch_models <folder>``: the models the Docling engine reads
(app/conversion/models.py) fetched into ``<folder>`` - the converter's volume, MODELS_DIR - and checked
against their list, by size and SHA-256. Once, by the operator, in the converter's image (it carries Docling):

    docker compose -f deploy/docker-compose.yml -f deploy/docker-compose.converter.yml run --rm models

The app's one command that asks the net for models: Docling's downloader from Hugging Face (the layout and
table models) and EasyOCR's releases on GitHub (German) - and only where a file is not as listed: EasyOCR's
downloader fetches its archives again each time, so run once more the command checks, offline. A file not
as listed after the fetch is removed: the converter's start checks the sizes alone (app/jobs/handlers.py),
and would take one of its size and other bytes. Exit code 0 when every file is as listed, 1 when one is not
(each named on stderr and gone), 2 for a call amiss.
"""

import logging
import sys
from collections.abc import Callable, Sequence
from pathlib import Path

from app.conversion.models import MODEL_FILES, ModelFile, differing

log = logging.getLogger("app.conversion.fetch_models")  # also when run as __main__


def download(directory: Path) -> None:
    """The models of the list, by Docling's downloader: the layout model, TableFormer and EasyOCR's German,
    nothing else it offers."""
    from docling.utils.model_downloader import download_models  # in the converter's image alone

    download_models(
        directory,
        with_layout=True,
        with_tableformer=True,
        with_code_formula=False,
        with_picture_classifier=False,
        with_rapidocr=False,
        with_easyocr=True,
        easyocr_languages=["de"],
    )


def main(
    argv: Sequence[str] | None = None,
    *,
    download: Callable[[Path], None] = download,
    files: Sequence[ModelFile] = MODEL_FILES,
) -> int:
    args = sys.argv[1:] if argv is None else list(argv)
    if len(args) != 1:
        log.error("usage: python -m app.conversion.fetch_models <folder>")
        return 2
    directory = Path(args[0])
    wrong = differing(directory, files)
    if wrong:
        download(directory)
        wrong = differing(directory, files)
    for path in wrong:
        log.error("%s is not as its list has it: absent, of another size, or other bytes", path)
        if (directory / path).is_file():
            (directory / path).unlink()
    if wrong:
        return 1
    log.info("%d model files in %s, each as listed", len(files), directory)
    return 0


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, stream=sys.stderr, format="%(levelname)s %(message)s")
    sys.exit(main())
