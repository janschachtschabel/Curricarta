"""The edition a document supersedes (plan M3a B2, cur:supersedes), set with its metadata before it is frozen:
a frozen edition of the same work under another IRI that the reader sees, none closing a circle through the
revisions of the editions it supersedes in turn, chosen under the work's lock; kept once frozen and by a draft
copy; let go with the work it was chosen in."""

import asyncio
import uuid
from typing import Any

import psycopg
import pytest
from psycopg import errors

from app.db.document_meta import NewWork, set_metadata, set_work
from app.db.draft_copy import copy_document
from app.db.editing import DocumentFrozen
from app.db.freezing import freeze
from app.db.runs import x5_owed
from app.db.source_queries import Reader
from app.vocab.form_values import FieldError
from tests.db.l1 import add_conversion
from tests.db.test_document_meta import another
from tests.db.test_editing import document, extracted, one
from tests.db.test_freeze import BASE, DOC, checked, ready
from tests.db.test_nodes import connection, owner, url, waiting_for_a_lock

pytestmark = [pytest.mark.pg, pytest.mark.anyio]
__all__ = ["connection", "document", "url"]  # the fixtures, shared with test_editing


async def an_edition(
    connection: psycopg.AsyncConnection,
    document: Any,
    edition: str,
    *,
    freezing: bool,
    superseding: bool = False,
) -> Any:
    """Another edition of ``document``'s work - ``ready``'s, frozen first where it is not -, extracted; with
    ``ready``'s tree, superseding ``document`` and frozen where asked."""
    if (await one(connection, "SELECT frozen_at FROM document WHERE id = %s", document.id))[0] is None:
        await ready(connection, document)
        await freeze(connection, document.id, BASE, accept_violations=False)
    other = await another(connection, document)
    await extracted(connection, other)
    if freezing:
        await ready(connection, other)  # a work of its own, set to the first's below
    await connection.execute(
        "UPDATE document SET work_id = (SELECT work_id FROM document WHERE id = %s),"
        " issuer = 'Ministerium für Schule', edition = %s WHERE id = %s",
        (document.id, edition, other.id),
    )
    if superseding:
        await set_metadata(connection, owner(document), other.id, {"supersedes": document.id})
    if freezing:
        await checked(connection, other)
        await freeze(connection, other.id, BASE, accept_violations=False)
    return other


async def supersedes(connection: psycopg.AsyncConnection, document_id: Any) -> Any:
    return (await one(connection, "SELECT supersedes_id FROM document WHERE id = %s", document_id))[0]


async def test_only_a_frozen_document_of_the_same_work_is_superseded(
    connection: psycopg.AsyncConnection, document: Any
) -> None:
    newer = await an_edition(connection, document, "2030", freezing=False)
    draft = await an_edition(connection, document, "2031", freezing=False)
    elsewhere = await another(connection, document)
    await extracted(connection, elsewhere)
    await set_work(
        connection, owner(document), elsewhere.id, NewWork("Lehrplan Chemie", "DE-NW", "lp-chemie")
    )
    await connection.execute(
        "UPDATE document SET issuer = 'Ministerium', edition = '2024' WHERE id = %s", (elsewhere.id,)
    )
    await ready(connection, elsewhere)
    await connection.execute(
        "UPDATE document SET work_id = (SELECT id FROM work WHERE short_title = 'lp-chemie') WHERE id = %s",
        (elsewhere.id,),
    )
    await checked(connection, elsewhere)
    await freeze(connection, elsewhere.id, BASE, accept_violations=False)
    workless = await another(connection, document)
    await extracted(connection, workless)

    refused = []
    for editing, target in (
        (newer, draft.id), (newer, elsewhere.id), (newer, newer.id), (newer, uuid.uuid4()),
        (workless, document.id),
    ):  # fmt: skip
        with pytest.raises(FieldError) as raised:
            await set_metadata(connection, owner(document), editing.id, {"supersedes": target})
        refused.append((raised.value.key, raised.value.problem))
    await checked(connection, newer)
    set_now = await set_metadata(connection, owner(document), newer.id, {"supersedes": document.id})
    owed = await x5_owed(connection, newer.id)
    again = await set_metadata(connection, owner(document), newer.id, {"supersedes": document.id})

    assert refused == [("supersedes", "not_offered")] * 5
    assert (set_now, owed, again) == (True, True, False)
    assert await supersedes(connection, newer.id) == document.id
    assert await set_metadata(connection, owner(document), newer.id, {"supersedes": None}) is True
    assert await supersedes(connection, newer.id) is None


async def test_a_document_another_account_alone_reads_is_none_to_supersede(
    url: str, connection: psycopg.AsyncConnection, document: Any
) -> None:
    # refused as a document there is not: nothing tells the caller it is there
    newer = await an_edition(connection, document, "2030", freezing=False)
    with psycopg.connect(url, autocommit=True) as sync:
        stranger = add_conversion(sync, digest=b"\x09" * 32)["owner"]
    await connection.execute("UPDATE document SET owner_id = %s WHERE id = %s", (stranger, newer.id))
    reader = Reader(stranger, sees_all=False)

    with pytest.raises(FieldError) as hidden:
        await set_metadata(connection, reader, newer.id, {"supersedes": document.id})
    with pytest.raises(FieldError) as none:
        await set_metadata(connection, reader, newer.id, {"supersedes": uuid.uuid4()})

    assert (hidden.value.key, hidden.value.problem) == (none.value.key, none.value.problem)
    assert await set_metadata(
        connection, Reader(stranger, sees_all=True), newer.id, {"supersedes": document.id}
    )


async def test_a_frozen_document_keeps_what_it_supersedes(
    connection: psycopg.AsyncConnection, document: Any
) -> None:
    newer = await an_edition(connection, document, "2030", freezing=True, superseding=True)

    with pytest.raises(DocumentFrozen):
        await set_metadata(connection, owner(document), newer.id, {"supersedes": None})
    with pytest.raises(errors.ObjectNotInPrerequisiteState):
        await connection.execute("UPDATE document SET supersedes_id = NULL WHERE id = %s", (newer.id,))
    # its draft copy, the next revision of the same edition, supersedes what it superseded
    copy = await copy_document(connection, newer.id)

    assert await supersedes(connection, newer.id) == document.id
    assert await supersedes(connection, copy) == document.id


async def test_no_two_editions_supersede_each_other_through_their_revisions(
    connection: psycopg.AsyncConnection, document: Any
) -> None:
    # B superseded the first revision of DOC: a revision of DOC may not supersede B in turn
    later = await an_edition(connection, document, "2030", freezing=True, superseding=True)
    copy = await copy_document(connection, document.id)
    assert (await one(connection, "SELECT iri FROM document WHERE id = %s", copy))[0] == DOC

    with pytest.raises(FieldError) as cycle:
        await set_metadata(connection, owner(document), copy, {"supersedes": later.id})

    assert (cycle.value.key, cycle.value.problem) == ("supersedes", "not_offered")


async def test_of_two_drafts_choosing_each_other_s_editions_at_once_the_second_is_refused(
    url: str, connection: psycopg.AsyncConnection, document: Any
) -> None:
    # neither sees the other's choice before it commits: the work's lock has the second wait and look again
    later = await an_edition(connection, document, "2030", freezing=True)
    first_copy, later_copy = (
        await copy_document(connection, document.id),
        await copy_document(connection, later.id),
    )
    async with (
        await psycopg.AsyncConnection.connect(url, autocommit=True) as other,
        await psycopg.AsyncConnection.connect(url, autocommit=True) as watcher,
    ):
        waiting: asyncio.Task[bool | None] | None = None
        try:
            async with other.transaction():
                await set_metadata(other, owner(document), first_copy, {"supersedes": later.id})
                waiting = asyncio.create_task(
                    set_metadata(connection, owner(document), later_copy, {"supersedes": document.id})
                )
                await waiting_for_a_lock(watcher, connection.info.backend_pid)
        finally:
            with pytest.raises(FieldError) as circle:
                if waiting is not None:
                    await waiting

    assert (circle.value.key, circle.value.problem) == ("supersedes", "not_offered")
    assert (await supersedes(connection, first_copy), await supersedes(connection, later_copy)) == (
        later.id,
        None,
    )


async def test_a_work_changed_lets_go_of_the_edition_it_superseded(
    connection: psycopg.AsyncConnection, document: Any
) -> None:
    # chosen in its work, it is none of another's: frozen after, the document supersedes nothing
    newer = await an_edition(connection, document, "2030", freezing=False)
    await ready(connection, newer)  # a work of its own: the first's again below
    work = (await one(connection, "SELECT work_id FROM document WHERE id = %s", document.id))[0]
    await connection.execute(
        "UPDATE document SET work_id = %s, edition = '2030' WHERE id = %s", (work, newer.id)
    )
    await set_metadata(connection, owner(document), newer.id, {"supersedes": document.id})
    await checked(connection, newer)

    await set_work(connection, owner(document), newer.id, NewWork("Lehrplan Chemie", "DE-NW", "lp-chemie"))
    owed = await x5_owed(connection, newer.id)
    await checked(connection, newer)
    await freeze(connection, newer.id, BASE, accept_violations=False)

    assert owed is True
    assert await one(
        connection, "SELECT supersedes_id, work_id <> %s FROM document WHERE id = %s", work, newer.id
    ) == (None, True)
