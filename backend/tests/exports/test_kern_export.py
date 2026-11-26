"""The Kern export made and kept (app/exports/kern_export.py, plan M3a C1): a frozen document's graph built
under its stored IRIs and written as Turtle in a child process, kept under a key of the document, its
revision and what may change its output; asked again, the kept bytes; a build past its time or broken in its
child is none. A synthetic document (app/exports/measure_kern.py) on a store on the file system, the real
child throughout."""

import asyncio
from pathlib import Path
from typing import Any
from uuid import uuid4

import pytest
from rdflib import Graph, URIRef

from app.core.storage import FileSystemStorage
from app.core.storage_async import AsyncStorage
from app.exports import kern_export
from app.exports.kern_child import checked_under
from app.exports.kern_export import ExportUnnamed, KernExporter, export_key, fingerprint
from app.exports.kern_rdf import KERN_GRAPH_VERSION
from app.exports.measure_kern import synthetic_rows
from app.exports.mem_export import Exported, ExportUnavailable
from tests.exports import kern_children
from tests.support import loop_watch, make_settings

pytestmark = pytest.mark.anyio


def an_exporter(store: Path) -> KernExporter:
    return KernExporter(AsyncStorage(FileSystemStorage(store)), make_settings(storage_dir=store))


@pytest.fixture
def exporter(tmp_path: Path) -> KernExporter:
    return an_exporter(tmp_path / "store")


def counting(monkeypatch: pytest.MonkeyPatch) -> list[int]:
    """The children the exporter starts, counted as they go."""
    started: list[int] = []
    original = kern_export.run_in_child

    async def run(*args: Any, **kwargs: Any) -> Any:
        started.append(1)
        return await original(*args, **kwargs)

    monkeypatch.setattr(kern_export, "run_in_child", run)
    return started


def stored(store: Path) -> list[Path]:
    return [path for path in (store / "exports").rglob("*") if path.is_file()] if store.exists() else []


async def test_the_export_is_kept_and_not_built_again(
    exporter: KernExporter, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    started = counting(monkeypatch)
    rows = synthetic_rows(nodes=3, statements=6)

    first, second = await exporter.export(rows), await exporter.export(rows)

    assert first == second and started == [1]
    assert first.key == export_key(rows.document["id"], 1, fingerprint(rows))
    graph = Graph().parse(data=(tmp_path / "store" / first.key).read_bytes(), format="turtle")
    assert (URIRef(rows.document["iri"]), None, None) in graph


async def test_two_requests_at_once_build_it_once(
    exporter: KernExporter, monkeypatch: pytest.MonkeyPatch
) -> None:
    started = counting(monkeypatch)
    rows = synthetic_rows(nodes=3, statements=6)

    made = await asyncio.gather(exporter.export(rows), exporter.export(rows))

    assert made[0] == made[1] and isinstance(made[0], Exported) and started == [1]


async def test_two_builds_give_the_same_bytes(tmp_path: Path) -> None:
    # two processes, each its own hash seed and blank nodes: the bytes stay the same - a statement of
    # several anchors too, whose blank nodes the serializer sorts
    rows = synthetic_rows(nodes=4, statements=12)
    first = rows.anchors[-1]
    rows.anchors.extend(first | {"id": uuid4(), "page_start": page} for page in range(2, 12))

    one, other = await asyncio.gather(
        an_exporter(tmp_path / "one").export(rows), an_exporter(tmp_path / "other").export(rows)
    )

    assert one.key == other.key
    assert (tmp_path / "one" / one.key).read_bytes() == (tmp_path / "other" / other.key).read_bytes()


async def test_two_builds_of_what_x1_read_of_the_applicability_give_the_same_bytes(tmp_path: Path) -> None:
    # the contexts of what X1 read are blank nodes of no row (app/exports/kern_scope.py): two of them, each
    # build its own process, the same bytes
    cv = "https://w3id.org/wlo/curriculum/vocab#"
    rows = synthetic_rows(nodes=2, statements=4)
    [first] = rows.specifications
    read = {
        "sector": cv + "sec_school",
        "formality": cv + "form_formal",
        "timeText": "Klasse 5",
        "levelText": "B",
    }
    rows.specifications[:] = [
        first | {"applicability": read},
        first | {"id": uuid4(), "iri": first["iri"] + "-2", "applicability": read | {"timeText": "Klasse 7"}},
    ]

    one, other = await asyncio.gather(
        an_exporter(tmp_path / "one").export(rows), an_exporter(tmp_path / "other").export(rows)
    )

    made = (tmp_path / "one" / one.key).read_bytes()
    assert made == (tmp_path / "other" / other.key).read_bytes()
    assert made.count(b"cur:ApplicabilityContext") == 2


async def test_two_exporters_on_one_store_keep_one_export(tmp_path: Path) -> None:
    # two replicas build the same key: the same bytes, the second put writes them again
    rows = synthetic_rows(nodes=2, statements=4)
    store = tmp_path / "store"

    made = await asyncio.gather(an_exporter(store).export(rows), an_exporter(store).export(rows))

    assert made[0] == made[1] and len(stored(store)) == 1


async def test_a_changed_rights_status_makes_another_export(exporter: KernExporter, tmp_path: Path) -> None:
    rows = synthetic_rows(nodes=2, statements=2)
    first = await exporter.export(rows)
    rows.document["rights_status"] = "amtlich"

    second = await exporter.export(rows)

    assert first.key != second.key
    assert b"amtlich" in (tmp_path / "store" / second.key).read_bytes()
    assert b"amtlich" not in (tmp_path / "store" / first.key).read_bytes()


@pytest.mark.parametrize(
    ("column", "value"),
    [("mem_licence", "https://creativecommons.org/licenses/by-sa/4.0/"),
     ("mem_attribution", "MEM-Schule, neu"), ("source_url", "https://example.org/neu.pdf")],
)  # fmt: skip
async def test_what_may_change_on_a_frozen_document_is_never_served_stale(
    exporter: KernExporter, tmp_path: Path, column: str, value: str
) -> None:
    # a frozen import's licence may still be recorded (migration 0031), a register entry's address edited
    rows = synthetic_rows(nodes=1, statements=1, mem_iri="https://example.org/mem/plan-1")
    first = await exporter.export(rows)
    rows.document[column] = value

    second = await exporter.export(rows)

    assert first.key != second.key
    assert value.encode() in (tmp_path / "store" / second.key).read_bytes()


def test_the_key_names_the_document_its_revision_and_the_builder_s_version() -> None:
    rows = synthetic_rows(nodes=1, statements=1, revision=3)

    key = export_key(rows.document["id"], 3, fingerprint(rows))

    assert key.startswith(f"exports/{rows.document['id']}/kern-5-r3-") and key.endswith(".ttl")
    assert len(key.rsplit("-", 1)[1]) == len("0123456789abcdef.ttl")


def test_the_fingerprint_is_of_what_may_change_after_the_freeze_not_of_the_iris(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    rows = synthetic_rows(nodes=1, statements=1)
    renamed = synthetic_rows(nodes=1, statements=1, base="https://example.org/other/doc/1")
    before = fingerprint(rows)

    assert fingerprint(renamed) == before  # the key names the document and its revision
    rows.document["violations"] = 2
    assert fingerprint(rows) != before
    rows.document["violations"] = 0
    monkeypatch.setattr(kern_export, "_RDFLIB", "0.0.0")
    assert fingerprint(rows) != before
    monkeypatch.undo()
    monkeypatch.setattr(kern_export, "KERN_GRAPH_VERSION", KERN_GRAPH_VERSION + 1)
    assert fingerprint(rows) != before  # the graph's builder


async def test_the_file_says_its_document_revision_and_accepted_violations(
    exporter: KernExporter, tmp_path: Path
) -> None:
    rows = synthetic_rows(nodes=2, statements=2, revision=2)
    rows.document["violations"] = 3

    made = await exporter.export(rows)

    text = (tmp_path / "store" / made.key).read_text(encoding="utf-8")
    head = text.splitlines()[:4]
    assert head[1:4] == [
        f"# document: <{rows.document['iri']}>", "# revision: 2", "# accepted violations: 3",
    ]  # fmt: skip
    assert "urn:uuid:" not in text
    assert "@prefix cur: <https://w3id.org/wlo/curriculum/core#> ." in text
    assert "# checked under" not in text  # X5 checked the graph this builder writes


@pytest.mark.parametrize(("checked", "said"), [(None, "unknown"), (KERN_GRAPH_VERSION + 1, "newer")])
async def test_a_document_checked_under_another_graph_says_so_in_its_head(
    exporter: KernExporter, tmp_path: Path, checked: int | None, said: str
) -> None:
    # frozen, it is checked no more: the file says which graph X5 checked, and keeps the count it accepted
    rows = synthetic_rows(nodes=1, statements=1)
    rows.document.update(checked_graph=checked, violations=2)
    version = said if checked is None else str(checked)

    made = await exporter.export(rows)

    head = (tmp_path / "store" / made.key).read_text(encoding="utf-8").splitlines()[:5]
    assert head[3:] == [
        "# accepted violations: 2",
        f"# checked under graph version: {version}, built with graph version: {KERN_GRAPH_VERSION}",
    ]
    assert checked_under(rows.document) == f"checked={version}; built={KERN_GRAPH_VERSION}"


async def test_a_document_with_a_row_of_no_iri_is_unnamed_and_nothing_is_built(
    exporter: KernExporter, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    started = counting(monkeypatch)
    rows = synthetic_rows(nodes=2, statements=2)
    rows.specifications[0]["iri"] = None  # frozen before specifications were named

    with pytest.raises(ExportUnnamed):
        await exporter.export(rows)
    assert started == [] and stored(tmp_path / "store") == []


async def test_a_build_past_its_time_is_none_and_leaves_nothing(
    exporter: KernExporter, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setattr(kern_export, "build_child", kern_children.sleeping)
    exporter._timeout_s = 0.5

    with pytest.raises(ExportUnavailable):
        await exporter.export(synthetic_rows(nodes=1, statements=1))
    assert stored(tmp_path / "store") == []


async def test_a_build_broken_in_its_child_is_none(
    exporter: KernExporter, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setattr(kern_export, "build_child", kern_children.breaking)

    with pytest.raises(ExportUnavailable):
        await exporter.export(synthetic_rows(nodes=1, statements=1))
    assert stored(tmp_path / "store") == []


async def test_the_build_runs_beside_the_loop(exporter: KernExporter) -> None:
    rows = synthetic_rows(nodes=60, statements=600)

    async with loop_watch() as longest:
        made = await exporter.export(rows)

    assert isinstance(made, Exported)
    assert longest[0] < 0.25, longest  # the build takes seconds: in the loop it would halt it that long


async def test_the_child_opens_no_socket(
    exporter: KernExporter, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setattr(kern_export, "build_child", kern_children.without_sockets)

    made = await exporter.export(synthetic_rows(nodes=2, statements=4))

    assert (tmp_path / "store" / made.key).is_file()


async def test_a_wait_for_a_build_past_the_request_s_time_is_none(
    exporter: KernExporter, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(kern_export, "REQUEST_S", 0.0)
    monkeypatch.setattr(kern_export, "MIN_WAIT_S", 0.05)
    exporter._children = asyncio.Semaphore(0)  # both children of the process are taken

    with pytest.raises(ExportUnavailable):
        await exporter.export(synthetic_rows(nodes=1, statements=1))


def test_the_build_s_time_leaves_the_wait_a_part_of_the_request_s() -> None:
    settings = make_settings(kern_export_timeout_s=45)

    assert settings.kern_export_timeout_s + kern_export.MIN_WAIT_S <= kern_export.REQUEST_S
    with pytest.raises(ValueError):
        make_settings(kern_export_timeout_s=46)
    with pytest.raises(ValueError):
        make_settings(kern_export_timeout_s=4)
