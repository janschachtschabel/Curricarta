"""A MEM export made and kept (app/exports/mem_export.py, plan M2-6, Nachtrag M2-1): the graph built, checked
against the MEM shapes in a child process, kept as Turtle under a key of the document and what may change
its output; asked again, the kept bytes, nothing checked; a state the shapes refuse is no export and leaves
nothing; a check that does not end is none either. Saxony's frozen plan, as the gate's tests build it; a
store on the file system; the real child for the refused state, the check in the test's process
(in_process_shacl) for the rest."""

import asyncio
import shutil
from pathlib import Path
from typing import Any

import pytest
from rdflib import Graph, URIRef

from app.core.storage import FileSystemStorage
from app.core.storage_async import AsyncStorage
from app.exports import mem_export, mem_gate
from app.exports.mem_export import Exported, ExportUnavailable, Invalid, MemExporter, export_key, fingerprint
from app.pipeline.shacl import ShaclCrashed, ShaclTimeout
from app.sources.mem import classes
from tests.exports.test_mem_gate import DOC, imported
from tests.support import ONTOLOGY, make_settings

pytestmark = pytest.mark.anyio


@pytest.fixture
def exporter(tmp_path: Path) -> MemExporter:
    settings = make_settings(storage_dir=tmp_path / "store")
    return MemExporter(AsyncStorage(FileSystemStorage(tmp_path / "store")), settings)


def counting(monkeypatch: pytest.MonkeyPatch) -> list[int]:
    """The checks the exporter asks the child for, counted as they go."""
    asked: list[int] = []
    original = mem_export.shacl_check

    async def check(*args: Any, **kwargs: Any) -> Any:
        asked.append(1)
        return await original(*args, **kwargs)

    monkeypatch.setattr(mem_export, "shacl_check", check)
    return asked


async def test_a_sound_frozen_import_is_exported_and_its_bytes_kept(
    in_process_shacl: None, exporter: MemExporter, tmp_path: Path
) -> None:
    rows = imported()

    made = await exporter.export(rows)

    assert isinstance(made, Exported)
    kept = (tmp_path / "store" / made.key).read_bytes()
    graph = Graph().parse(data=kept, format="turtle")
    assert (URIRef(DOC), None, None) in graph
    assert made.key == export_key(rows.document["id"], fingerprint(rows.document, ONTOLOGY))


async def test_a_second_export_reads_the_kept_bytes_and_checks_nothing(
    in_process_shacl: None, exporter: MemExporter, monkeypatch: pytest.MonkeyPatch
) -> None:
    asked = counting(monkeypatch)
    rows = imported()

    first, second = await exporter.export(rows), await exporter.export(rows)

    assert first == second and asked == [1]


async def test_two_exports_of_one_document_at_once_check_once(
    in_process_shacl: None, exporter: MemExporter, monkeypatch: pytest.MonkeyPatch
) -> None:
    asked = counting(monkeypatch)
    rows = imported()

    made = await asyncio.gather(exporter.export(rows), exporter.export(rows))

    assert made[0] == made[1] and isinstance(made[0], Exported) and asked == [1]


async def test_a_changed_rights_status_or_licence_is_another_export(
    in_process_shacl: None, exporter: MemExporter, tmp_path: Path
) -> None:
    rows = imported()
    first = await exporter.export(rows)
    rows.document["rights_status"] = "amtlich"
    second = await exporter.export(rows)
    rows.document["mem_licence"] = "https://creativecommons.org/licenses/by-sa/4.0/"
    third = await exporter.export(rows)

    assert isinstance(first, Exported) and isinstance(second, Exported) and isinstance(third, Exported)
    assert len({first.key, second.key, third.key}) == 3
    assert b"amtlich" in (tmp_path / "store" / second.key).read_bytes()


async def test_a_state_the_shapes_refuse_is_no_export_and_leaves_its_violations_alone(
    exporter: MemExporter, tmp_path: Path
) -> None:
    rows = imported(mem_land_iri=None)

    made = await exporter.export(rows)

    assert isinstance(made, Invalid)
    assert [violation.shape for violation in made.violations] == ["LPBundeslandShape"]
    kept = [path.name for path in (tmp_path / "store" / "exports").rglob("*") if path.is_file()]
    assert len(kept) == 1 and kept[0].endswith(".invalid.json")  # no Turtle


@pytest.mark.parametrize("failure", [ShaclTimeout("past its time"), ShaclCrashed("broke")])
async def test_a_check_past_its_time_or_broken_in_its_child_is_no_export(
    exporter: MemExporter, monkeypatch: pytest.MonkeyPatch, tmp_path: Path, failure: Exception
) -> None:
    async def failing(*_: Any, **__: Any) -> Any:
        raise failure

    monkeypatch.setattr(mem_export, "shacl_check", failing)

    with pytest.raises(ExportUnavailable):
        await exporter.export(imported())
    assert not (tmp_path / "store" / "exports").exists()


def test_the_key_names_the_document_the_exporter_s_version_and_what_may_change() -> None:
    rows = imported()

    key = export_key(rows.document["id"], fingerprint(rows.document, ONTOLOGY))

    assert key.startswith(f"exports/{rows.document['id']}/mem-1-") and key.endswith(".ttl")
    assert len(key.rsplit("-", 1)[1]) == len("0123456789abcdef.ttl")


def test_a_shape_changed_by_a_deployment_is_another_fingerprint(tmp_path: Path) -> None:
    rows = imported()
    copied = tmp_path / "ontology"
    shutil.copytree(ONTOLOGY / "mem", copied / "mem")
    same = fingerprint(rows.document, copied)
    with (copied / "mem" / "shapes" / "verweis.ttl").open("a", encoding="utf-8") as shape:
        shape.write("\n# changed\n")

    assert same == fingerprint(rows.document, ONTOLOGY)
    assert fingerprint(rows.document, copied) != same


async def test_a_refused_state_is_kept_refused_and_checked_once(
    in_process_shacl: None, exporter: MemExporter, monkeypatch: pytest.MonkeyPatch
) -> None:
    asked = counting(monkeypatch)
    rows = imported(mem_land_iri=None)

    first, second = await exporter.export(rows), await exporter.export(rows)

    assert isinstance(first, Invalid) and second == first and asked == [1]


async def test_a_wait_for_a_check_past_the_request_s_time_is_no_export(
    in_process_shacl: None, exporter: MemExporter, monkeypatch: pytest.MonkeyPatch
) -> None:
    # both checks of the process are taken: the request does not wait past what the proxy gives it
    monkeypatch.setattr(mem_export, "REQUEST_S", 0.0)
    monkeypatch.setattr(mem_export, "MIN_WAIT_S", 0.05)
    exporter._checks = asyncio.Semaphore(0)
    rows = imported()

    with pytest.raises(ExportUnavailable):
        await exporter.export(rows)

    # its key's lock went with it: the next export, its check free, is made
    monkeypatch.setattr(mem_export, "REQUEST_S", 55.0)
    exporter._checks = asyncio.Semaphore(1)
    assert isinstance(await exporter.export(rows), Exported)


async def test_a_wait_for_the_key_another_export_holds_is_bounded(
    exporter: MemExporter, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(mem_export, "REQUEST_S", 0.0)
    monkeypatch.setattr(mem_export, "MIN_WAIT_S", 0.05)
    rows = imported()
    held = asyncio.Lock()
    await held.acquire()  # another export of the document, past its time
    exporter._making[export_key(rows.document["id"], fingerprint(rows.document, ONTOLOGY))] = held

    with pytest.raises(ExportUnavailable):
        await exporter.export(rows)


def test_the_check_s_time_leaves_the_wait_a_part_of_the_request_s() -> None:
    # the check and the waits before it share what the proxy gives a request
    settings = make_settings(mem_export_timeout_s=45)

    assert settings.mem_export_timeout_s + mem_export.MIN_WAIT_S <= mem_export.REQUEST_S
    with pytest.raises(ValueError):
        make_settings(mem_export_timeout_s=46)


def test_a_stricter_gate_is_another_fingerprint(monkeypatch: pytest.MonkeyPatch) -> None:
    rows = imported()
    before = fingerprint(rows.document, ONTOLOGY)
    monkeypatch.setattr(mem_gate, "GATE_VERSION", "mem-gate/next")

    assert fingerprint(rows.document, ONTOLOGY) != before


def test_another_checker_is_another_fingerprint(monkeypatch: pytest.MonkeyPatch) -> None:
    rows = imported()
    before = fingerprint(rows.document, ONTOLOGY)
    monkeypatch.setattr(mem_export, "_PYSHACL", "0.0.0")

    assert fingerprint(rows.document, ONTOLOGY) != before


async def test_no_graph_is_built_while_the_checks_are_busy(
    exporter: MemExporter, monkeypatch: pytest.MonkeyPatch
) -> None:
    built: list[int] = []
    original = mem_export.mem_graph

    def building(*args: Any) -> Any:
        built.append(1)
        return original(*args)

    monkeypatch.setattr(mem_export, "mem_graph", building)
    monkeypatch.setattr(mem_export, "REQUEST_S", 0.0)
    monkeypatch.setattr(mem_export, "MIN_WAIT_S", 0.05)
    exporter._checks = asyncio.Semaphore(0)

    with pytest.raises(ExportUnavailable):
        await exporter.export(imported())
    assert built == []


async def test_a_check_broken_in_its_child_is_logged_with_its_document(
    exporter: MemExporter, monkeypatch: pytest.MonkeyPatch
) -> None:
    said: list[str] = []

    async def broken(*_: Any, **__: Any) -> Any:
        raise ShaclCrashed("the child died")

    monkeypatch.setattr(mem_export, "shacl_check", broken)
    monkeypatch.setattr(mem_export.log, "warning", lambda message, *args: said.append(message % args))
    rows = imported()

    with pytest.raises(ExportUnavailable):
        await exporter.export(rows)
    assert len(said) == 1 and str(rows.document["id"]) in said[0] and "the child died" in said[0]


def test_other_rules_are_another_fingerprint(monkeypatch: pytest.MonkeyPatch) -> None:
    rows = imported()
    before = fingerprint(rows.document, ONTOLOGY)
    monkeypatch.setattr(classes, "RULES", "mem-rules/next")

    assert fingerprint(rows.document, ONTOLOGY) != before
