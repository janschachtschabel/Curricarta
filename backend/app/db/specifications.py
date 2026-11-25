"""A document's specifications, as the editors put them right (plan M3a H1): read by document with their
variants and values - the applicability contexts among them (app/db/value_rows.py) -, and a
specification's title and field (cur:fieldText) set on its revision. Its kind, X1's, and its key stay: the
key is what its IRI is made of (app/domain/naming.py). Its contexts and values are set as a whole with
app/db/values.py.

An edit holds the tree's lock and refuses what every edit of the tree refuses (app/db/editing.py
``guard``); StaleRevision where the specification stands at another revision. A change counts its revision
one up and notes the document edited, which owes X5 a check; one that changes nothing leaves it as it was.
A specification has no origin of its own: the edit says nothing of where its title came from.
"""

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Final
from uuid import UUID

import psycopg
from psycopg import sql
from psycopg.rows import dict_row

from app.db.editing import StaleRevision, guard, mark_edited, target_of
from app.db.source_queries import Reader
from app.db.value_rows import values_of
from app.db.values import DOCUMENT_OF_SPECIFICATION
from app.domain.l2 import HeldValues, Holder
from app.domain.text import UNSTORABLE
from app.vocab.form_values import FieldError

# the longest each may be, as the table's checks have it (migration l1_documents); a title it must have
FIELDS: Final = {"title": 1000, "field_text": 2000}
_SPECIFICATIONS = """
SELECT id, key, spec_kind, title, field_text, revision FROM specification WHERE document_id = %s ORDER BY key
"""
_VARIANTS = """
SELECT v.id, v.specification_id, v.key, v.label, v.variant_kind_iri FROM variant v
JOIN specification s ON s.id = v.specification_id WHERE s.document_id = %s ORDER BY v.key
"""


@dataclass(frozen=True)
class VariantRow:
    id: UUID
    key: str
    label: str
    variant_kind: str  # cv:VariantKinds


@dataclass(frozen=True)
class SpecificationRow:
    id: UUID
    key: str
    spec_kind: (
        str  # X1's: curriculum, competencyFramework, qualificationSpecification, assessmentSpecification
    )
    title: str
    field_text: str | None
    revision: int
    variants: Sequence[VariantRow]
    values: HeldValues  # its own levels, time spans and workloads, and its applicability contexts


async def specifications_of(connection: psycopg.AsyncConnection, document_id: UUID) -> list[SpecificationRow]:
    """The document's specifications by key, each with its variants and values, in one snapshot - of a
    read-only transaction of its own, or of the caller's (as app/db/value_rows.py reads)."""
    if connection.info.transaction_status != psycopg.pq.TransactionStatus.IDLE:
        return await _read(connection, document_id)
    async with connection.transaction():
        await connection.execute("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ, READ ONLY")
        return await _read(connection, document_id)


async def _read(connection: psycopg.AsyncConnection, document_id: UUID) -> list[SpecificationRow]:
    async with connection.cursor(row_factory=dict_row) as rows:
        await rows.execute(_SPECIFICATIONS, (document_id,))
        specifications = await rows.fetchall()
        await rows.execute(_VARIANTS, (document_id,))
        variants = await rows.fetchall()
    values = await values_of(connection, document_id)
    return [
        SpecificationRow(
            id=row["id"], key=row["key"], spec_kind=row["spec_kind"], title=row["title"],
            field_text=row["field_text"], revision=row["revision"],
            variants=[
                VariantRow(each["id"], each["key"], each["label"], each["variant_kind_iri"])
                for each in variants if each["specification_id"] == row["id"]
            ],
            values=values.get(Holder("specification", row["id"]), HeldValues()),
        )
        for row in specifications
    ]  # fmt: skip


async def edit_specification(
    connection: psycopg.AsyncConnection,
    reader: Reader,
    specification_id: UUID,
    revision: int,
    given: Mapping[str, object],
) -> int | None:
    """Set the specification's ``given`` fields (``FIELDS``' keys; a blank field text, or None, none), on its
    revision ``revision``; its revision after, None where ``reader`` sees no such specification.
    FieldError, StaleRevision or a refusal of ``guard``, and then nothing is changed."""
    values = {key: _text(key, value) for key, value in given.items()}
    async with connection.transaction():
        target = await target_of(connection, DOCUMENT_OF_SPECIFICATION, reader, specification_id)
        if target is None:
            return None
        await guard(connection, target.document_id)
        cursor = await connection.execute(
            "SELECT revision, title, field_text FROM specification WHERE id = %s FOR UPDATE",
            (specification_id,),
        )
        found = await cursor.fetchone()
        if found is None:  # taken away meanwhile
            return None
        if found[0] != revision:
            raise StaleRevision(found[0])
        current = dict(zip(FIELDS, found[1:], strict=True))
        changed = {key: value for key, value in values.items() if value != current[key]}
        if not changed:
            return revision
        cursor = await connection.execute(
            sql.SQL(
                "UPDATE specification SET {}, revision = revision + 1 WHERE id = %s RETURNING revision"
            ).format(sql.SQL(", ").join(sql.SQL("{} = %s").format(sql.Identifier(key)) for key in changed)),
            (*changed.values(), specification_id),
        )
        raised = await cursor.fetchone()
        assert raised is not None  # noqa: S101 - the row locked above
        await mark_edited(connection, target.document_id)
        return int(raised[0])


def _text(key: str, value: object) -> str | None:
    """A field's text as the store keeps it; FieldError where it may not be set so."""
    most = FIELDS.get(key)
    if most is None:
        raise FieldError(key, "unknown")
    if value is not None and not isinstance(value, str):
        raise FieldError(key, "not_text")
    if value is None or not value.strip():
        if key == "title":
            raise FieldError(key, "required")
        return None
    if UNSTORABLE.search(value):
        raise FieldError(key, "not_storable")
    if len(value) > most:
        raise FieldError(key, "too_long")
    return value
