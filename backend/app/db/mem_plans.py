"""The catalogue of MEM's plans (table mem_plan, plan M2 E11): what the job source.mem_catalog read, graph by
graph, and what the import picks a plan from.

A graph's plans are replaced as one: what the endpoint holds no more is dropped, a plan it moved to
another graph moves with it. Documents imported from a plan keep their own copy of its licence and
attribution, so the catalogue may change under them.
"""

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime
from typing import Any
from uuid import UUID

import psycopg

from app.db.documents import DocumentError
from app.sources.mem.tree import storable_iri

_COLUMNS = "iri, graph, land_iri, title, class_iri, subjects, school_types, licence, attribution"
_WRITE = (
    "INSERT INTO mem_plan (iri, graph, land_iri, title, class_iri, subjects, school_types, licence,"
    " attribution, read_at) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, now())"
    " ON CONFLICT (iri) DO UPDATE SET graph = EXCLUDED.graph, land_iri = EXCLUDED.land_iri,"
    " title = EXCLUDED.title, class_iri = EXCLUDED.class_iri, subjects = EXCLUDED.subjects,"
    " school_types = EXCLUDED.school_types, licence = EXCLUDED.licence,"
    " attribution = EXCLUDED.attribution, read_at = now()"
)
# None of a filter means any; the title is found as typed, LIKE's signs no patterns
_WHERE = (
    "(%(land)s::text IS NULL OR land_iri = %(land)s)"
    " AND (%(lands)s::text[] IS NULL OR land_iri = ANY(%(lands)s))"
    " AND (%(graph)s::text IS NULL OR graph = %(graph)s)"
    " AND (%(subject)s::text IS NULL OR %(subject)s = ANY(subjects))"
    " AND (%(title)s::text IS NULL OR strpos(lower(title), lower(%(title)s)) > 0)"
)


@dataclass(frozen=True)
class MemPlan:
    iri: str
    graph: str
    land_iri: str | None
    title: str
    class_iri: str
    subjects: tuple[str, ...]
    school_types: tuple[str, ...]
    licence: str | None
    attribution: str | None
    read_at: datetime | None = None  # set by the database when the plan is written


async def replace_graph(
    connection: psycopg.AsyncConnection, graph: str, plans: Sequence[MemPlan]
) -> tuple[int, int]:
    """``graph``'s plans as ``plans``, in one transaction: (written, dropped)."""
    async with connection.transaction():
        cursor = await connection.execute(
            "DELETE FROM mem_plan WHERE graph = %s AND NOT (iri = ANY(%s))",
            (graph, [plan.iri for plan in plans]),
        )
        dropped = cursor.rowcount
        async with connection.cursor() as writing:
            await writing.executemany(_WRITE, [_values(plan) for plan in plans])
    return len(plans), dropped


async def find_plans(
    connection: psycopg.AsyncConnection,
    *,
    land: str | None = None,
    subject: str | None = None,
    title: str | None = None,
    lands: Sequence[str] | None = None,
    graph: str | None = None,
    limit: int = 50,
    offset: int = 0,
) -> tuple[list[MemPlan], int]:
    """A page of the plans of ``land`` - and of one of ``lands``, of ``graph`` - with ``subject`` whose title
    holds ``title`` (any case), by title; and the number of all of them."""
    values = {
        "land": land, "lands": None if lands is None else list(lands), "graph": graph, "subject": subject,
        "title": title, "limit": limit, "offset": offset,
    }  # fmt: skip
    # the page and its number in one statement, so that a catalogue written between them cannot part them
    cursor = await connection.execute(
        f"SELECT {_COLUMNS}, read_at, count(*) OVER () FROM mem_plan WHERE {_WHERE}"  # noqa: S608 - our own text
        " ORDER BY title, iri LIMIT %(limit)s OFFSET %(offset)s",
        values,
    )
    rows = await cursor.fetchall()
    if rows or not offset:
        return [_plan(row[:-1]) for row in rows], rows[0][-1] if rows else 0
    # a page past the last: the number still counts
    counted = await connection.execute(f"SELECT count(*) FROM mem_plan WHERE {_WHERE}", values)  # noqa: S608
    return [], (await counted.fetchone() or (0,))[0]


async def catalog_read_at(connection: psycopg.AsyncConnection) -> datetime | None:
    """When the catalogue last read a plan of any graph; None where it never read one."""
    cursor = await connection.execute("SELECT max(read_at) FROM mem_plan")
    found = await cursor.fetchone()
    return None if found is None else found[0]


async def graph_size(connection: psycopg.AsyncConnection, graph: str) -> int:
    """The number of ``graph``'s plans in the catalogue."""
    cursor = await connection.execute("SELECT count(*) FROM mem_plan WHERE graph = %s", (graph,))
    return int((await cursor.fetchone() or (0,))[0])


def _values(plan: MemPlan) -> tuple[Any, ...]:
    return (
        plan.iri, plan.graph, plan.land_iri, plan.title, plan.class_iri, list(plan.subjects),
        list(plan.school_types), plan.licence, plan.attribution,
    )  # fmt: skip


def _plan(row: Sequence[Any]) -> MemPlan:
    iri, graph, land_iri, title, class_iri, subjects, school_types, licence, attribution, read_at = row
    return MemPlan(
        iri,
        graph,
        land_iri,
        title,
        class_iri,
        tuple(subjects),
        tuple(school_types),
        licence,
        attribution,
        read_at,
    )


# a document's title holds as many signs at most (migration of the document table)
MAX_DOCUMENT_TITLE = 1000
_RECORD = """
UPDATE document SET title = %s, mem_iri = %s, mem_subjects = %s, mem_school_types = %s, mem_licence = %s,
    mem_attribution = %s, mem_land_iri = %s, mem_class_iri = %s, updated_at = now()
WHERE id = %s
"""


async def plan_by_iri(connection: psycopg.AsyncConnection, iri: str) -> MemPlan | None:
    """The catalogue's plan of ``iri``, if it holds one."""
    cursor = await connection.execute(f"SELECT {_COLUMNS}, read_at FROM mem_plan WHERE iri = %s", (iri,))  # noqa: S608
    found = await cursor.fetchone()
    return None if found is None else _plan(found)


async def record_import(connection: psycopg.AsyncConnection, document_id: UUID, plan: MemPlan) -> None:
    """The document as one imported from ``plan``: its title, and the plan's IRI, subjects, school types,
    licence, attribution, Land and class as they stand now - the catalogue may change under it. Called in
    the transaction that made the document: it takes no lock of its own, and a frozen document the
    database refuses (migration 0022). UniqueViolation where the document's conversion took the plan
    already (index document_mem_import), DocumentError for a document that is none."""
    cursor = await connection.execute(
        _RECORD,
        (
            plan.title[:MAX_DOCUMENT_TITLE],
            plan.iri,
            list(plan.subjects),
            list(plan.school_types),
            plan.licence,
            plan.attribution,
            _storable(plan.land_iri),
            _storable(plan.class_iri),
            document_id,
        ),
    )
    if cursor.rowcount != 1:
        raise DocumentError(f"no document {document_id}")


def _storable(iri: str | None) -> str | None:
    """The IRI where the document's columns take it, else none - the catalogue keeps what MEM says."""
    return iri if iri and storable_iri(iri) else None


async def amend_licence(connection: psycopg.AsyncConnection, licence: str) -> tuple[int, int]:
    """The licence of the MEM data, checked after imports were made (E14), into every import that records
    none - frozen ones too, which take it (migration 0031) - and every plan of the catalogue that holds
    none, so that an import made before the catalogue is read again takes it; how many imports and plans.
    An import or plan that records one keeps it."""
    cursor = await connection.execute(
        "UPDATE document SET mem_licence = %s, updated_at = now()"
        " WHERE mem_iri IS NOT NULL AND mem_licence IS NULL",
        (licence,),
    )
    documents = cursor.rowcount
    cursor = await connection.execute("UPDATE mem_plan SET licence = %s WHERE licence IS NULL", (licence,))
    return documents, cursor.rowcount
