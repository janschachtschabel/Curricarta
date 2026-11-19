"""A document's work and metadata, set by the editors before it is frozen (plan M1 9.6; Paket 9b H3, H4).

The work is one there is or one made of a title, a country and a short title; the metadata are the issuer, the
edition and the title X1 read off the document, as an editor puts them right. Both wait for the tree's lock
and refuse a frozen document and one beside its open job (``guard_document``); the metadata also one X4 has
not read yet (``guard``, NotExtracted), as every edit of the tree: before X1 an extraction would write them
over with what it reads (once done, X1 is passed over), the work it leaves. A document named by its IRI -
frozen once, or a draft copy of one - keeps its work, issuer and edition, which the IRI is made of
(``DocumentNamed``); its title it may change. With the metadata goes the edition it supersedes (plan M3a
B2, cur:supersedes): a document the reader sees, frozen, of the same work and under another IRI - and none
whose own chain of editions, through any revision of their IRIs, comes back to this document's IRI -, else
FieldError ``supersedes`` ``not_offered``, a document the reader does not see refused as one there is not;
chosen under a lock of the work, so that two drafts do not choose each other at once. Chosen in its work, it
goes when the work changes: a document of another work supersedes none of this one's editions. A change of the
metadata owes X5 a check: the Kern export carries them.

simplify: who sees a document edits its metadata, as its tree (app/db/editing.py); the work is the
editors' alone, which the API asks (app/api/document_meta.py).
"""

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Final
from uuid import UUID

import psycopg
from psycopg import sql

from app.db.anchors import new_entity
from app.db.documents import DOCUMENT_VISIBLE, DocumentError, unknown_regions
from app.db.editing import DOCUMENT, guard, guard_document, mark_edited, target_of
from app.db.source_queries import Reader
from app.domain.text import UNSTORABLE
from app.vocab.form_values import FieldError

# the longest each may be, as the table's checks have it (migration l1_documents)
METADATA: Final = {"title": 1000, "issuer": 500, "edition": 200}
# what the document's IRI is made of: fixed once it has one
_NAMING = frozenset({"issuer", "edition"})
SUPERSEDES = "supersedes"  # the edition it supersedes, by its document's id
_SUPERSEDES_LOCK = 0x6B6B_6173  # with the work's hash: the lock of choosing what an edition supersedes
# an edition the document may supersede: one the reader sees, frozen, of its work, under another IRI, whose
# editions superseded in turn - by any revision of their IRIs - never come back to the document's IRI
_SUPERSEDABLE = f"""
WITH RECURSIVE chain (iri) AS (
    SELECT d.iri FROM document d WHERE d.id = %(target)s
    UNION
    SELECT s.iri FROM chain c JOIN document d ON d.iri = c.iri JOIN document s ON s.id = d.supersedes_id
)
SELECT FROM document d, document own
WHERE d.id = %(target)s AND own.id = %(document)s AND d.frozen_at IS NOT NULL AND d.work_id = own.work_id
    AND d.iri IS DISTINCT FROM own.iri AND {DOCUMENT_VISIBLE}
    AND NOT EXISTS (SELECT FROM chain WHERE chain.iri = own.iri)
"""  # noqa: S608 - fixed parts


class DocumentNamed(Exception):
    """The document has its IRI already: what it is made of stays."""


@dataclass(frozen=True)
class ExistingWork:
    work_id: UUID


@dataclass(frozen=True)
class NewWork:
    title: str
    region: str  # ISO 3166-1 or -2: "DE", "DE-NW"
    short_title: str  # a slug: "lp-physik"


async def set_work(
    connection: psycopg.AsyncConnection, reader: Reader, document_id: UUID, work: ExistingWork | NewWork
) -> UUID | None:
    """Set the document's work - one there is, or one made, ``reader``'s; the work's id. None where
    ``reader`` sees no such document. DocumentError ``no_work`` for a work there is not, FieldError for a
    work made of a title the database cannot hold or a country the region vocabulary does not (its IRI
    is named by it), DocumentNamed, or a refusal of ``guard_document``, and then nothing is changed."""
    async with connection.transaction():
        target = await target_of(connection, DOCUMENT, reader, document_id)
        if target is None:
            return None
        if isinstance(work, NewWork):
            if UNSTORABLE.search(work.title):
                raise FieldError("title", "not_storable")
            if not work.title.strip():  # the separators has_text trims, which the API's strip leaves
                raise FieldError("title", "required")
            if await unknown_regions(connection, [work.region]):
                raise FieldError("region", "not_offered")
        await guard_document(connection, document_id)
        await _unnamed(connection, document_id)
        if isinstance(work, ExistingWork):
            cursor = await connection.execute("SELECT id FROM work WHERE id = %s", (work.work_id,))
            if await cursor.fetchone() is None:
                raise DocumentError(f"no work {work.work_id}", code="no_work")
            work_id = work.work_id
        else:
            work_id = await new_entity(connection, "work")
            await connection.execute(
                "INSERT INTO work (id, title, region, short_title, owner_id) VALUES (%s, %s, %s, %s, %s)",
                (work_id, work.title, work.region, work.short_title, reader.account_id),
            )
        # what it superseded was an edition of its work before: another work lets go of it (plan M3a B2)
        cursor = await connection.execute(
            "SELECT work_id IS DISTINCT FROM %s AND supersedes_id IS NOT NULL FROM document WHERE id = %s",
            (work_id, document_id),
        )
        let_go = bool((await cursor.fetchone() or (False,))[0])
        await connection.execute(
            "UPDATE document SET work_id = %s, updated_at = now(),"
            " supersedes_id = CASE WHEN %s THEN NULL ELSE supersedes_id END WHERE id = %s",
            (work_id, let_go, document_id),
        )
        if let_go:
            await mark_edited(connection, document_id)  # the Kern graph said it
        return work_id


async def set_metadata(
    connection: psycopg.AsyncConnection, reader: Reader, document_id: UUID, given: Mapping[str, object]
) -> bool | None:
    """Set the metadata ``given`` (``METADATA``'s keys; a blank text, or None, none) and the edition it
    supersedes (``SUPERSEDES``: a document's id, or None) - whether any changed; None where ``reader`` sees
    no such document. FieldError, DocumentNamed for the issuer or edition of a named document, or a refusal
    of ``guard``, and then nothing is changed."""
    async with connection.transaction():
        target = await target_of(connection, DOCUMENT, reader, document_id)
        if target is None:
            return None
        values: dict[str, object] = {
            key: value if key == SUPERSEDES else _text(key, value) for key, value in given.items()
        }
        if SUPERSEDES in values and not (values[SUPERSEDES] is None or isinstance(values[SUPERSEDES], UUID)):
            raise FieldError(SUPERSEDES, "not_offered")
        await guard(connection, document_id)
        cursor = await connection.execute(
            "SELECT title, issuer, edition, supersedes_id, iri IS NOT NULL FROM document WHERE id = %s",
            (document_id,),
        )
        found = await cursor.fetchone()
        assert found is not None  # noqa: S101 - the tree's lock holds the document, which target_of found
        current = dict(zip(("title", "issuer", "edition", SUPERSEDES), found[:4], strict=True))
        changed = {key: value for key, value in values.items() if value != current[key]}
        if not changed:
            return False
        if changed.get(SUPERSEDES) is not None:
            await _supersedable(connection, reader, document_id, changed[SUPERSEDES])
        if found[4] and _NAMING & changed.keys():
            raise DocumentNamed(f"the document {document_id} is named by its IRI: its {sorted(changed)} stay")
        columns = sql.SQL(", ").join(
            sql.SQL("{} = %s").format(sql.Identifier("supersedes_id" if key == SUPERSEDES else key))
            for key in changed
        )
        await connection.execute(
            sql.SQL("UPDATE document SET {}, updated_at = now() WHERE id = %s").format(columns),
            (*changed.values(), document_id),
        )
        await mark_edited(connection, document_id)
        return True


async def _supersedable(
    connection: psycopg.AsyncConnection, reader: Reader, document_id: UUID, target: object
) -> None:
    # one choice at a time within a work: two drafts choosing each other's editions at once make a circle
    await connection.execute(
        "SELECT pg_advisory_xact_lock(%s, hashtext(work_id::text)) FROM document WHERE id = %s",
        (_SUPERSEDES_LOCK, document_id),
    )
    cursor = await connection.execute(
        _SUPERSEDABLE,
        {"target": target, "document": document_id, "me": reader.account_id, "all": reader.sees_all},
    )
    if await cursor.fetchone() is None:
        raise FieldError(SUPERSEDES, "not_offered")


async def _unnamed(connection: psycopg.AsyncConnection, document_id: UUID) -> None:
    cursor = await connection.execute("SELECT iri FROM document WHERE id = %s", (document_id,))
    found = await cursor.fetchone()
    if found is not None and found[0] is not None:
        raise DocumentNamed(f"the document {document_id} is named by its IRI {found[0]}: its work stays")


def _text(key: str, value: object) -> str | None:
    most = METADATA.get(key)
    if most is None:
        raise FieldError(key, "unknown")
    if value is not None and not isinstance(value, str):
        raise FieldError(key, "not_text")
    if value is None or not value.strip():
        return None
    if UNSTORABLE.search(value):
        raise FieldError(key, "not_storable")
    if len(value) > most:
        raise FieldError(key, "too_long")
    return value
