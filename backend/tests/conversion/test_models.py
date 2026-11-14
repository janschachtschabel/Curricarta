"""The models the Docling engine reads (plan M1 3b): the files that make them, by size and SHA-256, checked
cheaply at a conversion's start and wholly after a fetch; and the one command that fetches them
(python -m app.conversion.fetch_models), with Docling's downloader standing in."""

import hashlib
import logging
from pathlib import Path
from typing import Any

import pytest

from app.conversion import fetch_models
from app.conversion.models import MODEL_FILES, ModelFile, differing, missing


def made(directory: Path, path: str, content: bytes) -> ModelFile:
    target = directory / path
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(content)
    return ModelFile(path, len(content), hashlib.sha256(content).hexdigest())


def test_the_list_names_the_layout_the_table_and_the_ocr_models() -> None:
    paths = {item.path for item in MODEL_FILES}

    assert "docling-project--docling-layout-heron/model.safetensors" in paths
    assert (
        "docling-project--docling-models/model_artifacts/tableformer/accurate/tableformer_accurate.safetensors"
        in paths
    )
    assert {
        "EasyOcr/craft_mlt_25k.pth",
        "EasyOcr/latin_g2.pth",
    } <= paths  # detection, Latin (German) recognition
    assert all(len(item.sha256) == 64 and item.size > 0 for item in MODEL_FILES)


def test_a_file_absent_or_of_another_size_is_missing(tmp_path: Path) -> None:
    there = made(tmp_path, "a/weights.bin", b"weights")
    short = made(tmp_path, "b/config.json", b"{}")
    (tmp_path / short.path).write_bytes(b"{ }")  # another size

    files = (there, short, ModelFile("c/gone.pth", 5, "0" * 64))

    assert missing(tmp_path, files) == ["b/config.json", "c/gone.pth"]


def test_a_file_of_its_size_but_other_bytes_differs_only_by_its_hash(tmp_path: Path) -> None:
    right = made(tmp_path, "a/weights.bin", b"weights")
    wrong = made(tmp_path, "b/weights.bin", b"abcdefg")
    (tmp_path / wrong.path).write_bytes(b"gfedcba")  # the same size

    assert missing(tmp_path, (right, wrong)) == []
    assert differing(tmp_path, (right, wrong)) == ["b/weights.bin"]


def test_the_command_fetches_into_its_folder_and_checks_what_came(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    content = {"x/model.bin": b"model", "x/config.json": b"{}"}
    files = tuple(made(tmp_path / "list", path, data) for path, data in content.items())
    target = tmp_path / "models"
    asked: list[Path] = []

    def download(directory: Path) -> None:
        asked.append(directory)
        for path, data in content.items():
            made(directory, path, data)

    with caplog.at_level(logging.INFO, logger="app.conversion.fetch_models"):
        code = fetch_models.main([str(target)], download=download, files=files)

    assert (code, asked) == (0, [target])
    assert "2 model files" in caplog.text


def test_the_command_says_which_file_came_wrong(tmp_path: Path, caplog: pytest.LogCaptureFixture) -> None:
    files = (made(tmp_path / "list", "x/model.bin", b"model"),)

    def download(directory: Path) -> None:
        made(directory, "x/model.bin", b"mod3l")

    code = fetch_models.main([str(tmp_path / "models")], download=download, files=files)

    assert code == 1
    assert "x/model.bin" in caplog.text
    # gone: the converter's start checks the sizes alone, and would take a file of its size, other bytes
    assert not (tmp_path / "models" / "x" / "model.bin").exists()


def test_the_command_fetches_nothing_where_every_file_is_as_listed(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    # EasyOCR's downloader fetches its archives again each time; run once more, the command only checks
    files = (made(tmp_path / "models", "x/model.bin", b"model"),)
    asked: list[Path] = []

    with caplog.at_level(logging.INFO, logger="app.conversion.fetch_models"):
        code = fetch_models.main([str(tmp_path / "models")], download=asked.append, files=files)

    assert (code, asked) == (0, [])
    assert "1 model files" in caplog.text


def test_the_command_hashes_the_models_once_where_it_fetches_nothing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    files = (made(tmp_path / "models", "x/model.bin", b"model"),)
    checked: list[Path] = []

    def counted(directory: Path, listed: Any) -> list[str]:
        checked.append(directory)
        return differing(directory, listed)

    monkeypatch.setattr("app.conversion.fetch_models.differing", counted)

    assert fetch_models.main([str(tmp_path / "models")], download=lambda _: None, files=files) == 0
    assert len(checked) == 1


@pytest.mark.parametrize("arguments", [[], ["a", "b"]])
def test_the_command_takes_one_folder(arguments: list[str], caplog: pytest.LogCaptureFixture) -> None:
    assert fetch_models.main(arguments, download=lambda _: None, files=()) == 2
    assert "usage: python -m app.conversion.fetch_models" in caplog.text


def test_every_listed_model_file_lies_within_the_models_folder() -> None:
    # the fetch removes a listed file that came wrong: none may name a place outside the folder
    for listed in MODEL_FILES:
        parts = listed.path.split("/")
        assert not listed.path.startswith("/") and ".." not in parts and "" not in parts, listed.path
        assert "\\" not in listed.path and ":" not in listed.path, listed.path


def test_the_command_removes_no_folder_at_a_listed_place(tmp_path: Path) -> None:
    files = (made(tmp_path / "list", "x/model.bin", b"model"),)
    (tmp_path / "models" / "x" / "model.bin").mkdir(parents=True)

    assert fetch_models.main([str(tmp_path / "models")], download=lambda _: None, files=files) == 1
    assert (tmp_path / "models" / "x" / "model.bin").is_dir()
