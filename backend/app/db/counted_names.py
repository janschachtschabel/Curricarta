"""Names given by a document's counter when it is frozen (app/db/freezing.py): a row of the document's without
an IRI gets ``<document>/<kind>-<n>``, in the order the rows were made, counting on from the document's
counter of the kind (document.serials), which a draft copy takes along - no number is given twice under one
document IRI. An assessment (plan M3a J) and a placement (plan M3a K) are named so."""

from typing import Literal, LiteralString
from uuid import UUID

import psycopg
from psycopg import sql

CountedKind = Literal["assessment", "placement"]  # each its table's name and the key of its counter


async def name_by_counter(
    connection: psycopg.AsyncConnection, kind: CountedKind, document_id: UUID, iri: str
) -> int:
    """Give each row of ``kind`` of the document without an IRI its own under the document's IRI ``iri``, as
    the module says; how many were named. Within the freeze, under the tree's lock, before the document is
    frozen."""
    table: LiteralString = kind
    cursor = await connection.execute(
        sql.SQL("SELECT id FROM {} WHERE document_id = %s AND iri IS NULL ORDER BY created_at, id").format(
            sql.Identifier(table)
        ),
        (document_id,),
    )
    unnamed = [row for (row,) in await cursor.fetchall()]
    if not unnamed:
        return 0
    cursor = await connection.execute(
        "SELECT coalesce((serials ->> %s)::integer, 0) FROM document WHERE id = %s", (kind, document_id)
    )
    found = await cursor.fetchone()
    given = 0 if found is None else int(found[0])
    async with connection.cursor() as writing:
        await writing.executemany(
            sql.SQL("UPDATE {} SET iri = %s WHERE id = %s").format(sql.Identifier(table)),
            [(f"{iri}/{kind}-{given + place}", row) for place, row in enumerate(unnamed, start=1)],
        )
    await connection.execute(
        "UPDATE document SET serials = serials || jsonb_build_object(%s::text, %s::integer) WHERE id = %s",
        (kind, given + len(unnamed), document_id),
    )
    return len(unnamed)
