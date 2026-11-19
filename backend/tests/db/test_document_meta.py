"""A document's work and metadata set by the editors (plan M1 9.6, Paket 9b H3, H4): a work made or one
there is, its issuer, edition and title - under the tree's lock, not beside an open job and not once it is
frozen; issuer, edition and work no more once the document is named by its IRI, which is made of them. A
change of the metadata owes X5 a check (the Kern export carries them)."""

import asyncio
import uuid
from typing import Any

import psycopg
import pytest
from psycopg import errors

from app.db.document_meta import DocumentNamed, ExistingWork, NewWork, set_metadata, set_work
from app.db.documents import DocumentError, create_document
from app.db.draft_copy import copy_document
from app.db.editing import DocumentFrozen, JobOpen, NotExtracted
from app.db.freezing import freeze
from app.db.runs import RunStart, finish_run, start_run, x5_owed
from app.db.source_queries import Reader
from app.vocab.form_values import FieldError
from tests.db.l1 import add_conversion
from tests.db.test_editing import an_open_job, document, edited_at, extracted, one
from tests.db.test_freeze import BASE, DOC, checked, ready
from tests.db.test_nodes import connection, owner, url, waiting_for_a_lock

pytestmark = [pytest.mark.pg, pytest.mark.anyio]
__all__ = ["connection", "document", "url"]  # the fixtures, shared with test_editing

IRI = "https://example.org/kk/doc/de-nw/ministerium/lp-physik/2024"
PHYSICS = NewWork("Lehrplan Physik", "DE-NW", "lp-physik")


async def another(connection: psycopg.AsyncConnection, document: Any) -> Any:
    return await create_document(
        connection, owner(document), third_party_content=False, source_id=document.source_id,
        conversion_id=document.conversion_id, sector="school",
    )  # fmt: skip


async def test_a_work_made_is_the_editor_s_and_the_document_s(
    connection: psycopg.AsyncConnection, document: Any
) -> None:
    work = await set_work(connection, owner(document), document.id, PHYSICS)

    assert await one(
        connection,
        "SELECT w.title, w.region, w.short_title, w.owner_id, w.iri, d.work_id = w.id"
        " FROM work w JOIN document d ON d.id = %s WHERE w.id = %s",
        document.id,
        work,
    ) == ("Lehrplan Physik", "DE-NW", "lp-physik", document.owner_id, None, True)
    assert await one(connection, "SELECT kind FROM entity WHERE id = %s", work) == ("work",)


async def test_a_work_there_is_is_set_and_one_there_is_not_refused(
    connection: psycopg.AsyncConnection, document: Any
) -> None:
    made = await set_work(connection, owner(document), document.id, PHYSICS)
    assert made is not None
    other = await another(connection, document)

    assert await set_work(connection, owner(document), other.id, ExistingWork(made)) == made
    with pytest.raises(DocumentError) as raised:
        await set_work(connection, owner(document), other.id, ExistingWork(uuid.uuid4()))
    assert raised.value.code == "no_work"
    assert await one(connection, "SELECT count(*) FROM work") == (1,)


async def test_a_work_made_of_what_no_work_may_hold_is_refused_and_none_made(
    connection: psycopg.AsyncConnection, document: Any
) -> None:
    # the work's country names its IRI (app/domain/iris.py): one of the vocabulary's, not a typo of one
    for work, problem in (
        (NewWork("Lehrplan\x00Physik", "DE-NW", "lp-physik"), ("title", "not_storable")),
        (NewWork("Lehrplan Physik", "DE-XX", "lp-physik"), ("region", "not_offered")),
        # separators the API's strip leaves and the table's check (has_text) does not
        (NewWork("\x1c\x1f", "DE-NW", "lp-physik"), ("title", "required")),
    ):
        with pytest.raises(FieldError) as raised:
            await set_work(connection, owner(document), document.id, work)
        assert (raised.value.key, raised.value.problem) == problem
    assert await one(connection, "SELECT count(*) FROM work") == (0,)
    assert await one(connection, "SELECT work_id FROM document WHERE id = %s", document.id) == (None,)


async def test_no_work_is_set_on_a_named_or_frozen_document_or_beside_its_job(
    connection: psycopg.AsyncConnection, document: Any
) -> None:
    named, frozen, busy = [await another(connection, document) for _ in range(3)]
    await connection.execute("UPDATE document SET iri = %s WHERE id = %s", (IRI, named.id))
    await connection.execute(
        "UPDATE document SET iri = %s, frozen_at = now() WHERE id = %s", (IRI + "-alt", frozen.id)
    )
    await an_open_job(connection, busy)

    for target, refused in ((named, DocumentNamed), (frozen, DocumentFrozen), (busy, JobOpen)):
        with pytest.raises(refused):
            await set_work(connection, owner(document), target.id, PHYSICS)
    stranger = Reader(uuid.uuid4(), sees_all=False)
    assert await set_work(connection, stranger, document.id, PHYSICS) is None
    assert await one(connection, "SELECT count(*) FROM work") == (0,)


async def test_the_metadata_set_owe_x5_a_check_and_the_same_again_changes_nothing(
    connection: psycopg.AsyncConnection, document: Any
) -> None:
    given = {"issuer": "Ministerium für Schule", "edition": "2024", "title": "Kernlehrplan Physik"}

    assert await set_metadata(connection, owner(document), document.id, given) is True
    first = await edited_at(connection, document)
    assert await set_metadata(connection, owner(document), document.id, given) is False
    again = await edited_at(connection, document)
    assert await set_metadata(connection, owner(document), document.id, {"edition": "  "}) is True

    row = await one(connection, "SELECT issuer, edition, title FROM document WHERE id = %s", document.id)
    assert row == ("Ministerium für Schule", None, "Kernlehrplan Physik")  # a blank one is none
    assert first is not None and again == first  # the same again owes nothing
    assert await edited_at(connection, document) > first


async def test_a_named_document_keeps_its_issuer_and_edition_and_takes_a_title(
    connection: psycopg.AsyncConnection, document: Any
) -> None:
    await connection.execute("UPDATE document SET iri = %s WHERE id = %s", (IRI, document.id))

    for key in ("issuer", "edition"):
        with pytest.raises(DocumentNamed):
            await set_metadata(connection, owner(document), document.id, {key: "Neu"})
    assert await set_metadata(connection, owner(document), document.id, {"title": "Neu"}) is True


async def test_no_metadata_are_set_on_a_frozen_document_or_beside_its_job(
    connection: psycopg.AsyncConnection, document: Any
) -> None:
    frozen, busy = [await another(connection, document) for _ in range(2)]
    await connection.execute(
        "UPDATE document SET iri = %s, frozen_at = now() WHERE id = %s", (IRI, frozen.id)
    )
    await an_open_job(connection, busy)

    for target, refused in ((frozen, DocumentFrozen), (busy, JobOpen)):
        with pytest.raises(refused):
            await set_metadata(connection, owner(document), target.id, {"title": "Neu"})
    assert await one(connection, "SELECT count(*) FROM document WHERE title = 'Neu'") == (0,)


async def test_no_metadata_are_set_before_x4_as_no_edit_of_the_tree_is(
    connection: psycopg.AsyncConnection, document: Any
) -> None:
    # X1 reads the issuer, edition and title off the document (app/db/profile.py), a work it does not:
    # done, it is passed over, and still the metadata wait for X4, as the tree's edits do (guard)
    early = await another(connection, document)
    run = await start_run(connection, RunStart(early.id, None, None, "X1", None, None, None, None))
    await finish_run(connection, run, "done")

    with pytest.raises(NotExtracted):
        await set_metadata(connection, owner(document), early.id, {"issuer": "Ministerium"})
    made = await set_work(connection, owner(document), early.id, PHYSICS)

    assert await one(connection, "SELECT issuer, work_id FROM document WHERE id = %s", early.id) == (
        None,
        made,
    )


async def test_metadata_the_document_may_not_hold_is_refused_and_changes_nothing(
    connection: psycopg.AsyncConnection, document: Any
) -> None:
    for given, problem in (
        ({"issuer": "x" * 501}, ("issuer", "too_long")),
        ({"title": "Op\x00tik"}, ("title", "not_storable")),
        ({"edition": 2024}, ("edition", "not_text")),
        ({"short_title": "lp"}, ("short_title", "unknown")),
    ):
        with pytest.raises(FieldError) as raised:
            await set_metadata(connection, owner(document), document.id, given)
        assert (raised.value.key, raised.value.problem) == problem
    assert await edited_at(connection, document) is None


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
