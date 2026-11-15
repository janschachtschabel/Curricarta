"""The keys under a prefix on the file system: those below it and no other, never a file no key names,
never a place outside the root."""

import os
from pathlib import Path
from typing import Any

import pytest

from app.core.storage import FileSystemStorage, InvalidKey
from tests.core.test_storage import LEAVING_KEYS


@pytest.fixture
def storage(tmp_path: Path) -> FileSystemStorage:
    return FileSystemStorage(tmp_path / "objects")


def test_the_keys_under_a_prefix_are_listed_and_no_other(storage: FileSystemStorage) -> None:
    for key in (
        "runs/a/x4/1.json",
        "runs/a/x4/3.json",
        "runs/a/x1/1.json",
        "runs/ab/x4/1.json",
        "runs/b.json",
    ):
        storage.put(key, b"{}")

    assert sorted(storage.list("runs/a/x4/")) == ["runs/a/x4/1.json", "runs/a/x4/3.json"]  # a gap and all
    assert sorted(storage.list("runs/a/")) == ["runs/a/x1/1.json", "runs/a/x4/1.json", "runs/a/x4/3.json"]


def test_a_prefix_that_holds_nothing_lists_nothing(storage: FileSystemStorage) -> None:
    storage.put("runs/a", b"{}")  # an object, no folder of keys

    assert list(storage.list("runs/none/")) == []
    assert list(storage.list("runs/a/")) == []


# each key that could leave the root, as a prefix; and one that names no folder - a prefix ends in "/"
LEAVING_PREFIXES = [
    pytest.param(f"{key.values[0]}/", id=key.id) for key in LEAVING_KEYS if key.id != "trailing-slash"
] + [
    pytest.param("/", id="root"),
    pytest.param("runs//", id="double-slash"),
    pytest.param("runs", id="no-slash"),
]


@pytest.mark.parametrize("prefix", LEAVING_PREFIXES)
def test_a_prefix_that_could_leave_the_root_is_refused(storage: FileSystemStorage, prefix: str) -> None:
    # refused at the call, before anything is read
    with pytest.raises(InvalidKey):
        storage.list(prefix)


def test_a_link_out_of_the_root_is_refused(storage: FileSystemStorage, tmp_path: Path) -> None:
    outside = tmp_path / "outside"
    (outside / "x4").mkdir(parents=True)
    (outside / "x4" / "1.json").write_bytes(b"{}")
    storage.root.mkdir(parents=True)
    try:
        (storage.root / "runs").symlink_to(outside, target_is_directory=True)
    except OSError:
        pytest.skip("this system makes no symbolic links for this user")

    with pytest.raises(InvalidKey):
        storage.list("runs/")


def test_a_half_written_file_is_no_object(storage: FileSystemStorage) -> None:
    # a process killed between writing and renaming leaves its temporary file beside the target
    storage.put("runs/a/x4/1.json", b"{}")
    (storage.root / "runs" / "a" / "x4" / ".tmp-k2j4h").write_bytes(b"{")

    assert list(storage.list("runs/a/")) == ["runs/a/x4/1.json"]


def test_a_folder_that_cannot_be_read_is_an_error_not_an_empty_place(
    storage: FileSystemStorage, monkeypatch: pytest.MonkeyPatch
) -> None:
    # listed as empty, the sweep would forget the place and leave its objects for good
    storage.put("runs/a/x4/1.json", b"{}")
    scan = os.scandir

    def refused(path: Any) -> Any:
        if Path(path).name == "x4":
            raise PermissionError(13, "refused (invented)", str(path))
        return scan(path)

    monkeypatch.setattr(os, "scandir", refused)

    with pytest.raises(PermissionError):
        list(storage.list("runs/a/"))
