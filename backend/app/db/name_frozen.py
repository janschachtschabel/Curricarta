"""``python -m app.db.name_frozen``: the IRIs of the specifications and variants of documents frozen before
they had any (migration 0034; plan M3a B1), and of their rules (migration 0038; plan M3a I), once per instance
after those migrations.

Each frozen document whose specification or variant lacks its IRI is named as a freeze names it now
(app/db/freezing.py, app/domain/naming.py): by the keys under the document's IRI, its revisions in their
order, so a key names in a later revision what it named in an earlier one. Its nodes and statements have
theirs; the database lets a frozen specification, variant or frame part take its IRI and nothing else
(migrations 0034, 0038). A rule is numbered past every number the document's revisions gave; the frozen
document's counter stays as it was, a later freeze reads the numbers its revisions hold. A rule a later
revision copied takes the name of the rule it corresponds to (app/db/freezing.py), and so does a rule of a
draft copy open meanwhile, named here too: its freeze keeps what it holds.
All in one transaction under the advisory lock every freeze shares (``NAMING_LOCK``): a second run waits for
the first, then finds nothing left, and a freeze waits for it meanwhile and then reads what it named.
Idempotent: a run with nothing to name changes nothing.

Prints one line of JSON, counts alone - ``documents``, ``specifications``, ``variants``, ``rules`` named - and
ends with exit code 0; a failure ends it with one log line and exit code 1, nothing named.
"""

import asyncio
import json
import logging
import sys
from dataclasses import asdict, dataclass

import psycopg

from app.db.freezing import NAMING_LOCK, name_document, write_names
from app.db.pool import CONNECTION_OPTIONS

log = logging.getLogger("app.db.name_frozen")  # also when run as __main__

_UNNAMED = """
SELECT d.id, d.iri FROM document d
WHERE d.frozen_at IS NOT NULL AND (
    EXISTS (SELECT FROM specification s WHERE s.document_id = d.id AND s.iri IS NULL)
    OR EXISTS (SELECT FROM variant v JOIN specification s ON s.id = v.specification_id
               WHERE s.document_id = d.id AND v.iri IS NULL)
    OR EXISTS (SELECT FROM frame_part f WHERE f.document_id = d.id AND f.part_kind = 'rules' AND f.iri IS NULL
               AND f.review_status_iri <> 'https://w3id.org/wlo/curriculum/vocab#rev_rejected')
)
ORDER BY d.iri, d.revision
"""
# the rules of open draft copies, each by the rule it corresponds to in the revision it copies, where that one
# is named and no rule of the copy holds the name yet
_OPEN_COPIES = """
UPDATE frame_part f SET iri = c.iri
FROM document d, frame_part c
WHERE f.document_id = d.id AND d.frozen_at IS NULL AND d.copy_of IS NOT NULL AND f.part_kind = 'rules'
    AND f.iri IS NULL AND c.document_id = d.copy_of AND c.part_kind = 'rules' AND c.iri IS NOT NULL
    AND c.position = f.position AND c.content = f.content AND c.created_at = f.created_at
    AND NOT EXISTS (SELECT FROM frame_part o WHERE o.document_id = d.id AND o.iri = c.iri)
"""


@dataclass(frozen=True)
class NamedFrozen:
    documents: int
    specifications: int
    variants: int
    rules: int = 0


async def name_frozen(connection: psycopg.AsyncConnection) -> NamedFrozen:
    """Name what the frozen documents lack, as above, in one transaction of its own; how many of each."""
    documents = specifications = variants = rules = 0
    async with connection.transaction():
        await connection.execute("SELECT pg_advisory_xact_lock(%s)", (NAMING_LOCK,))
        cursor = await connection.execute(_UNNAMED)
        for document_id, iri in await cursor.fetchall():
            named = await name_document(connection, document_id, iri)
            if named.nodes or named.statements:  # a frozen document names all of its tree when it is frozen
                raise RuntimeError(f"the frozen document {document_id} lacks IRIs of its tree")
            await write_names(connection, named)
            documents += 1
            specifications += len(named.specifications)
            variants += len(named.variants)
            rules += len(named.rules)
        cursor = await connection.execute(_OPEN_COPIES)
        rules += max(cursor.rowcount, 0)
    return NamedFrozen(documents, specifications, variants, rules)


async def _run(url: str) -> NamedFrozen:
    options = {**CONNECTION_OPTIONS, "application_name": "curricarta-name-frozen"}
    async with await psycopg.AsyncConnection.connect(url, autocommit=True, **options) as connection:
        return await name_frozen(connection)


def main() -> int:
    from app.core.logging import configure_logging
    from app.core.settings import Settings

    settings = Settings()
    configure_logging(settings.log_level, settings.log_format, stream=sys.stderr)
    try:
        named = asyncio.run(
            _run(settings.database_url.get_secret_value()), loop_factory=asyncio.SelectorEventLoop
        )
    except Exception as error:  # any failure ends the command in one line, never a traceback
        message = error.diag.message_primary if isinstance(error, psycopg.Error) else None
        log.error("naming stopped: %s", " ".join((message or str(error) or type(error).__name__).split()))
        return 1
    sys.stdout.write(json.dumps(asdict(named)) + "\n")
    sys.stdout.flush()
    return 0


if __name__ == "__main__":
    sys.exit(main())
