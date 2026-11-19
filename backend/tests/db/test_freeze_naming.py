"""A frozen document's specifications and variants have IRIs of their own (plan M3a B1): given when it is
frozen, by their keys under the document's IRI; a draft copy brings them along and names a new one past
them. A document frozen before they had any is named once by ``python -m app.db.name_frozen``, under an
advisory lock - a second run, or one at the same time, gives none again -, its revisions alike by key; the
database lets a frozen row take its IRI and nothing else."""

import asyncio
import json
import os
import subprocess
import sys
from pathlib import Path
from typing import Any
from uuid import UUID

import psycopg
import pytest
from psycopg import errors

from app.db.anchors import new_entity
from app.db.draft_copy import copy_document
from app.db.freezing import freeze
from app.db.name_frozen import NamedFrozen, name_frozen
from tests.db.test_editing import document
from tests.db.test_freeze import BASE, DOC, checked, ready
from tests.db.test_nodes import CV, connection, url, waiting_for_a_lock
from tests.support import without_settings_variables

pytestmark = [pytest.mark.pg, pytest.mark.anyio]
__all__ = ["connection", "document", "url"]  # the fixtures, shared with test_editing

BACKEND = Path(__file__).resolve().parents[2]
_IRIS = """
SELECT s.key, s.iri, array(SELECT v.key || ' ' || coalesce(v.iri, '-') FROM variant v
                           WHERE v.specification_id = s.id ORDER BY v.key COLLATE "C")
FROM specification s WHERE s.document_id = %s ORDER BY s.key COLLATE "C"
"""


class Copy:
    def __init__(self, id: UUID) -> None:  # what checked() reads of a document
        self.id = id


async def specified(connection: psycopg.AsyncConnection, document_id: UUID, key: str, *variants: str) -> UUID:
    """A specification of the key, with variants of these keys."""
    specification = await new_entity(connection, "specification")
    await connection.execute(
        "INSERT INTO specification (id, document_id, key, spec_kind, title)"
        " VALUES (%s, %s, %s, 'curriculum', %s)",
        (specification, document_id, key, key.upper()),
    )
    for variant_key in variants:
        await connection.execute(
            "INSERT INTO variant (id, specification_id, key, label, variant_kind_scheme, variant_kind_iri)"
            " VALUES (%s, %s, %s, %s, %s, %s)",
            (await new_entity(connection, "variant"), specification, variant_key, variant_key,
             CV + "VariantKinds", CV + "var_track"),
        )  # fmt: skip
    return specification


async def named(connection: psycopg.AsyncConnection, document_id: UUID) -> list[tuple[Any, ...]]:
    cursor = await connection.execute(_IRIS, (document_id,))
    return list(await cursor.fetchall())


async def as_frozen_before(connection: psycopg.AsyncConnection, document_id: UUID) -> None:
    """The document's specifications and variants without their IRIs, as a freeze before migration 0034
    left them: the triggers held off for this test's own database alone."""
    for table, stays in (
        ("specification", "specification_stays_frozen"),
        ("variant", "variant_stays_frozen"),
    ):
        await connection.execute(f"ALTER TABLE {table} DISABLE TRIGGER {stays}")
    await connection.execute(
        "UPDATE variant SET iri = NULL WHERE specification_id IN"
        " (SELECT id FROM specification WHERE document_id = %s)",
        (document_id,),
    )
    await connection.execute("UPDATE specification SET iri = NULL WHERE document_id = %s", (document_id,))
    for table, stays in (
        ("specification", "specification_stays_frozen"),
        ("variant", "variant_stays_frozen"),
    ):
        await connection.execute(f"ALTER TABLE {table} ENABLE TRIGGER {stays}")


async def test_a_frozen_document_s_specifications_and_variants_have_their_iris(
    connection: psycopg.AsyncConnection, document: Any
) -> None:
    await ready(connection, document)
    await specified(connection, document.id, "lp", "g8", "g9")
    await specified(connection, document.id, "Sek I")

    frozen = await freeze(connection, document.id, BASE, accept_violations=False)

    assert (frozen.specifications, frozen.variants) == (2, 2)
    assert await named(connection, document.id) == [
        ("Sek I", DOC + "/spec/sek-i", []),
        ("lp", DOC + "/spec/lp", [f"g8 {DOC}/spec/lp/variant/g8", f"g9 {DOC}/spec/lp/variant/g9"]),
    ]


async def test_a_copy_brings_them_and_a_new_specification_is_named_past_them(
    connection: psycopg.AsyncConnection, document: Any
) -> None:
    await ready(connection, document)
    await specified(connection, document.id, "lp", "g8")
    await freeze(connection, document.id, BASE, accept_violations=False)
    copy = await copy_document(connection, document.id)
    assert await named(connection, copy) == await named(connection, document.id)

    # recoded in the copy, it keeps its IRI; a new key of its old slug counts on past it
    await connection.execute("UPDATE specification SET key = 'lp-alt' WHERE document_id = %s", (copy,))
    await specified(connection, copy, "LP", "G8")
    await checked(connection, Copy(copy))
    frozen = await freeze(connection, copy, BASE, accept_violations=False)

    assert (frozen.specifications, frozen.variants) == (1, 1)
    assert await named(connection, copy) == [
        ("LP", DOC + "/spec/lp-2", [f"G8 {DOC}/spec/lp-2/variant/g8"]),
        ("lp-alt", DOC + "/spec/lp", [f"g8 {DOC}/spec/lp/variant/g8"]),
    ]


async def test_documents_frozen_before_are_named_by_the_command_once(
    connection: psycopg.AsyncConnection, document: Any
) -> None:
    await ready(connection, document)
    await specified(connection, document.id, "lp", "g8")
    await freeze(connection, document.id, BASE, accept_violations=False)
    expected = await named(connection, document.id)
    await as_frozen_before(connection, document.id)
    assert await named(connection, document.id) == [("lp", None, ["g8 -"])]

    first = await name_frozen(connection)
    again = await name_frozen(connection)

    assert first == NamedFrozen(documents=1, specifications=1, variants=1)
    assert again == NamedFrozen(documents=0, specifications=0, variants=0)
    assert await named(connection, document.id) == expected


async def test_two_runs_at_once_give_each_iri_once(
    url: str, connection: psycopg.AsyncConnection, document: Any
) -> None:
    # the second waits for the first's lock, then finds nothing left to name
    await ready(connection, document)
    await specified(connection, document.id, "lp", "g8")
    await freeze(connection, document.id, BASE, accept_violations=False)
    await as_frozen_before(connection, document.id)
    async with (
        await psycopg.AsyncConnection.connect(url, autocommit=True) as other,
        await psycopg.AsyncConnection.connect(url, autocommit=True) as watcher,
    ):
        waiting: asyncio.Task[NamedFrozen] | None = None
        try:
            async with other.transaction():
                first = await name_frozen(other)
                waiting = asyncio.create_task(name_frozen(connection))
                await waiting_for_a_lock(watcher, connection.info.backend_pid)
        finally:
            second = await waiting if waiting is not None else None

    assert (first.specifications, first.variants) == (1, 1)
    assert second == NamedFrozen(documents=0, specifications=0, variants=0)
    assert await named(connection, document.id) == [
        ("lp", DOC + "/spec/lp", [f"g8 {DOC}/spec/lp/variant/g8"])
    ]


async def test_the_revisions_of_a_document_frozen_before_are_named_alike_by_key(
    connection: psycopg.AsyncConnection, document: Any
) -> None:
    # revision 2 added "LP" beside "lp": "lp" names in it what it names in revision 1, "LP" counts on
    await ready(connection, document)
    await specified(connection, document.id, "lp")
    await freeze(connection, document.id, BASE, accept_violations=False)
    copy = await copy_document(connection, document.id)
    await specified(connection, copy, "LP")
    await checked(connection, Copy(copy))
    await freeze(connection, copy, BASE, accept_violations=False)
    for revision in (document.id, copy):
        await as_frozen_before(connection, revision)

    assert (await name_frozen(connection)).documents == 2

    assert await named(connection, document.id) == [("lp", DOC + "/spec/lp", [])]
    assert await named(connection, copy) == [("LP", DOC + "/spec/lp-2", []), ("lp", DOC + "/spec/lp", [])]


async def test_a_frozen_specification_takes_its_iri_and_no_other_change(
    connection: psycopg.AsyncConnection, document: Any
) -> None:
    await ready(connection, document)
    specification = await specified(connection, document.id, "lp", "g8")
    await freeze(connection, document.id, BASE, accept_violations=False)
    await as_frozen_before(connection, document.id)
    iri = DOC + "/spec/lp"

    for change in (
        "UPDATE specification SET iri = %(iri)s, title = 'Neu' WHERE id = %(id)s",
        "UPDATE variant SET iri = %(iri)s || '/variant/g8', label = 'Neu' WHERE specification_id = %(id)s",
    ):
        with pytest.raises(errors.ObjectNotInPrerequisiteState):
            await connection.execute(change, {"iri": iri, "id": specification})
    await connection.execute("UPDATE specification SET iri = %s WHERE id = %s", (iri, specification))
    await connection.execute(
        "UPDATE variant SET iri = %s WHERE specification_id = %s", (iri + "/variant/g8", specification)
    )
    for change in (
        "UPDATE specification SET iri = %(iri)s || '-2' WHERE id = %(id)s",
        "UPDATE specification SET iri = NULL WHERE id = %(id)s",
        "UPDATE variant SET iri = NULL WHERE specification_id = %(id)s",
    ):
        with pytest.raises(errors.ObjectNotInPrerequisiteState):
            await connection.execute(change, {"iri": iri, "id": specification})

    assert await named(connection, document.id) == [("lp", iri, [f"g8 {iri}/variant/g8"])]


def test_the_command_prints_counts_alone(database_url: str) -> None:
    with without_settings_variables():
        environment = {**os.environ, "DATABASE_URL": database_url, "LOG_FORMAT": "json"}

    done = subprocess.run(  # this interpreter and a fixed module
        [sys.executable, "-m", "app.db.name_frozen"],
        cwd=BACKEND, env=environment, capture_output=True, text=True, timeout=60, check=False,
    )  # fmt: skip

    assert done.returncode == 0, done.stderr
    assert [json.loads(line) for line in done.stdout.splitlines()] == [
        {"documents": 0, "specifications": 0, "variants": 0}
    ]


def test_a_database_the_command_cannot_reach_ends_it_in_one_log_line() -> None:
    with without_settings_variables():
        environment = {
            **os.environ,
            "DATABASE_URL": "postgresql://nobody@127.0.0.1:1/none",
            "LOG_FORMAT": "json",
        }

    done = subprocess.run(  # this interpreter and a fixed module
        [sys.executable, "-m", "app.db.name_frozen"],
        cwd=BACKEND, env=environment, capture_output=True, text=True, timeout=60, check=False,
    )  # fmt: skip

    assert (done.returncode, done.stdout) == (1, "")
    assert len(done.stderr.splitlines()) == 1
    assert "naming stopped" in done.stderr
