"""``python -m app.sources.mem.amend_licence IRI``: the licence of MEM-Schule's data, checked by the operators
after imports were made (plan M2, E14), into every import that records none - frozen ones too - and every
plan of the catalogue that holds none (app/db/mem_plans.amend_licence). First set MEM_DATA_LICENCE to the same
IRI and restart the API and the workers - a catalogue read without it writes the plans' licence back to
none -, then run this; not while the catalogue is being read (its writes and these may wait on each other
until one is refused): on a failure, run it again - and once more after imports that were being made
meanwhile, which may have read their plan before; a second run changes nothing else. The licence is an
https IRI (a Creative Commons deed, say); anything else is refused before anything is read. Prints how
many imports and plans took it; exit code 1 on a failure.
"""

import asyncio
import logging
import sys

import psycopg

from app.core.logging import configure_logging
from app.core.settings import Settings
from app.db.mem_plans import amend_licence
from app.db.pool import CONNECTION_OPTIONS
from app.sources.mem.tree import storable_iri

log = logging.getLogger("app.sources.mem.amend_licence")  # also when run as __main__


async def amend(settings: Settings, licence: str) -> tuple[int, int]:
    url = settings.database_url.get_secret_value()
    connection = await psycopg.AsyncConnection.connect(url, **CONNECTION_OPTIONS)
    async with connection, connection.transaction():
        return await amend_licence(connection, licence)


def main(arguments: list[str]) -> int:
    if len(arguments) != 1 or not arguments[0].startswith("https://") or not storable_iri(arguments[0]):
        print("usage: python -m app.sources.mem.amend_licence IRI (an https IRI, one)", file=sys.stderr)
        return 1
    settings = Settings()
    configure_logging(settings.log_level, settings.log_format, stream=sys.stderr)
    if settings.mem_data_licence != arguments[0]:
        log.error("set MEM_DATA_LICENCE to the same IRI first, and restart the API and the workers")
        return 1
    try:
        documents, plans = asyncio.run(amend(settings, arguments[0]), loop_factory=asyncio.SelectorEventLoop)
    except psycopg.Error as error:
        log.error("no licence amended: %s", " ".join(str(error).split()))
        return 1
    print(documents, plans)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
