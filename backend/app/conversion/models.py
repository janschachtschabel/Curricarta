"""The models the Docling engine reads (plan M1 3b), by the files that make them: Docling's layout model
(heron), its table model (TableFormer, accurate and fast) and EasyOCR's text detection and its Latin
recognition, which reads German. They lie in MODELS_DIR - the image's folder, where the converter's volume
is mounted -, fetched once by ``python -m app.conversion.fetch_models``; the converter never fetches one
(HF_HUB_OFFLINE in the image).

Each file by its size and SHA-256, as fetched on 2026-11-05 for Docling 2.117 and EasyOCR 1.7.2 - Docling
2.150 reads the same files -: a conversion checks the sizes at its start, cheaply; the fetch checks the
hashes, wholly.
"""

import hashlib
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path

MODELS_DIR = Path("/models")
_LAYOUT = "docling-project--docling-layout-heron"
_TABLES = "docling-project--docling-models/model_artifacts/tableformer"


@dataclass(frozen=True)
class ModelFile:
    path: str  # under MODELS_DIR, with / between its parts
    size: int
    sha256: str


MODEL_FILES = (
    ModelFile(
        f"{_LAYOUT}/config.json", 3268, "fdea30805ce2f5666b147fca941dcdd27ad468e27d6ed21902207d3da056a97d"
    ),
    ModelFile(
        f"{_LAYOUT}/model.safetensors",
        171658996,
        "00333a43451945aaf89db8ca9c0a17e75d1537c17db60fdb91aa95f4c7929e0c",
    ),
    ModelFile(
        f"{_LAYOUT}/preprocessor_config.json",
        444,
        "cd38cd59999e7a95d68e487fbe5132df3d4e5c32a0836add57e6126ba0c4eaf1",
    ),
    ModelFile(
        "docling-project--docling-models/config.json",
        41,
        "9c34024dc28ff47b75818f415e769809798c29bf9bde6f2ccc63a4acb62396d9",
    ),
    ModelFile(
        f"{_TABLES}/accurate/tableformer_accurate.safetensors",
        212758388,
        "2a7d6c924b3cd12fb99a09280ca9c33a89c5d60b93253617d2e088c1a40374d9",
    ),
    ModelFile(
        f"{_TABLES}/accurate/tm_config.json",
        7060,
        "984e122ceb8ccf84d84c9d2882f6f2302a44b4f1e577babd6289892c36f3cffd",
    ),
    ModelFile(
        f"{_TABLES}/fast/tableformer_fast.safetensors",
        145453276,
        "3119563aab5a7c96fda4d621119b63fd8806272b86c30936d15507616422f718",
    ),
    ModelFile(
        f"{_TABLES}/fast/tm_config.json",
        7060,
        "dca6762508dddfae6d57d6cb4ef822c6000119dff0f3b6489db7413118c2622a",
    ),
    ModelFile(
        "EasyOcr/craft_mlt_25k.pth",
        83152330,
        "4a5efbfb48b4081100544e75e1e2b57f8de3d84f213004b14b85fd4b3748db17",
    ),
    ModelFile(
        "EasyOcr/latin_g2.pth", 15406141, "aaa95be1c4a9cb3496879bed7c520886ce1164f89e026f0c54488394e74e8c55"
    ),
)


def missing(directory: Path, files: Sequence[ModelFile] = MODEL_FILES) -> list[str]:
    """The files not in ``directory`` at their size, by path."""
    return [item.path for item in files if not _sized(directory / item.path, item.size)]


def differing(directory: Path, files: Sequence[ModelFile] = MODEL_FILES) -> list[str]:
    """The files not in ``directory`` as listed - absent, of another size or other bytes -, by path."""
    return [
        item.path
        for item in files
        if not _sized(directory / item.path, item.size) or _sha256(directory / item.path) != item.sha256
    ]


def _sized(path: Path, size: int) -> bool:
    return path.is_file() and path.stat().st_size == size


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as file:
        while chunk := file.read(1 << 20):
            digest.update(chunk)
    return digest.hexdigest()
