"""``python -m app.lexicon.export_reviews``: the editors' decisions on the research cues
(app/db/cue_review.py) and the new cues they took from the documents' terms (app/db/term_review.py) as JSON on
stdout, for the file the research's importer (ontology/werkzeuge/importiere_recherche.py) reads back into the
lexicon's files (plan M1 10.3, 10.4):

    docker compose exec -T api python -m app.lexicon.export_reviews \\
        > ontology/recherche-ergebnisse/entscheidungen.json

Every decision by its cue - a retired cue's too, or the next import would bring a rejected cue back -, with
what was judged; every new cue by its profile, regions and word, with its target, role and note - a term
peculiar to its document or misread changes no file, and no document is named. Never who decided or when:
the file goes into git, the audit log keeps them. The same decisions give the same bytes. Exit code 0, or 1
when the database refused (one line on stderr).
"""

import asyncio
import json
import logging
import sys
from typing import Any

import psycopg

from app.core.logging import configure_logging
from app.core.settings import Settings
from app.db.cue_review import Decision, decisions
from app.db.pool import CONNECTION_OPTIONS
from app.db.term_review import ROLE, TermReview, term_reviews

FORMAT = 2  # the importer refuses any other
log = logging.getLogger("app.lexicon.export_reviews")  # also when run as __main__


def document(made: list[Decision], taken: list[TermReview]) -> str:
    """The decisions and the new cues as the file holds them: keys in order, signs as they read, one field
    to a line."""
    entries = [
        {
            "cue": decision.cue,
            "decision": decision.decision,
            "strength": None if decision.strength is None else str(decision.strength),
            "evidence": decision.evidence,
            "note": decision.note,
            "content": decision.content,
        }
        for decision in made
    ]
    cues = [_new_cue(review) for review in taken if review.decision == "cue"]  # in the order of their terms
    held = {"format": FORMAT, "decisions": entries, "new_terms": cues}
    return json.dumps(held, ensure_ascii=False, indent=1, sort_keys=True) + "\n"


def _new_cue(review: TermReview) -> dict[str, Any]:
    assert review.role is not None  # noqa: S101 - a new cue has its role (term_review_cue_complete)
    return {
        "profile": review.profile,
        "regions": list(review.regions),
        "surface_form": review.surface_form,
        "maps_to": review.maps_to,
        "role": review.role.removeprefix(ROLE),
        "note": review.note,
    }


async def _decisions(url: str) -> tuple[list[Decision], list[TermReview]]:
    async with await psycopg.AsyncConnection.connect(url, **CONNECTION_OPTIONS) as connection:
        return await decisions(connection), await term_reviews(connection)


def main() -> int:
    settings = Settings()
    configure_logging(settings.log_level, settings.log_format, stream=sys.stderr)
    url = settings.database_url.get_secret_value()
    try:
        made, taken = asyncio.run(_decisions(url), loop_factory=asyncio.SelectorEventLoop)
    except psycopg.Error as error:
        log.error("no decisions exported: %s", " ".join(str(error).split()))
        return 1
    # whatever the console's code page and line ends
    sys.stdout.buffer.write(document(made, taken).encode("utf-8"))
    sys.stdout.flush()
    confirmed = sum(decision.decision == "confirmed" for decision in made)
    retired = sum(decision.retired for decision in made)
    log.info(
        "%d decisions: %d confirmed, %d rejected; %d on a retired cue; %d new cues",
        len(made),
        confirmed,
        len(made) - confirmed,
        retired,
        sum(review.decision == "cue" for review in taken),
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
