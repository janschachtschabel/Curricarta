"""``python -m app.quality.sheet --sample <id> --base-url <url> > ../data/gold-local/<label>-<kind>.csv``
(run from ``backend/``; the folder lies at the repository's root): the judging sheet of a gold sample (plan
H-3 §3.3) - one row per item with its wording and where to look, the cells to judge (``verdict``,
``reasons``, ``expected``, ``note``) empty, ``n/a`` where a cell is not asked: a block is judged by a count,
a statement or anchor by a verdict; an item no longer what was drawn says so (app/quality/stale.py:
``kind`` = ``gone`` where its row is gone since the draw, ``changed`` where its wording, origin or first
block changed), its verdict ``n/a``. ``shown`` proves what the judge saw: the item's mark where its row was
as drawn when the sheet was written, empty where it was not. ``python -m app.quality.judge`` reads it back.

The sheet holds the document's wordings: it is written to stdout alone. Where the code lies in a working
tree and stdout is a file, the file must lie under ``data/gold-local/`` (ignored by git and the images) -
any other file, in the repository or outside it, is refused. That sees a direct redirection only: behind
``docker compose exec``, a pipe or ``tee`` the shell writes the file where it is told, and the bar there is
the tree guard (``tests/quality/test_instance_data_guard.py``: no sheet lies in the repository). UTF-8
with a BOM, ``;`` between the cells, CRLF: as a spreadsheet opens it. A cell that starts like a formula is
written as text."""

import argparse
import asyncio
import csv
import io
import logging
import os
import re
import stat
import sys
from collections.abc import Mapping, Sequence
from pathlib import Path
from uuid import UUID

import psycopg

from app.core.logging import configure_logging
from app.core.settings import Settings
from app.db.documents import document_for_job
from app.db.gold import Item, items_of, sample_by_id
from app.db.gold_rows import Shown, blocks_shown, node_names, nodes_shown, statements_shown
from app.db.pool import CONNECTION_OPTIONS
from app.quality.stale import stale_items

log = logging.getLogger(__name__)

SHEET_HEADER = (
    "item", "mark", "shown", "stratum", "page", "path", "kind", "wording", "lead_in", "quote", "link",
    "verdict", "reasons", "expected", "note",
)  # fmt: skip
NOT_ASKED = "n/a"  # in a judging cell the item's kind does not ask for
BOM = "\N{ZERO WIDTH NO-BREAK SPACE}"  # by name: an invisible literal is lost without a diff
LOCAL_FOLDER = Path("data") / "gold-local"
WARNING = (
    "the sheet holds the document's wordings: keep it - and a copy saved as a workbook - under"
    " data/gold-local/, never in the repository"
)
_FORMULA = ("=", "+", "-", "@", "\t", "\r")  # what a spreadsheet would read as the start of a formula
_URL = re.compile(r"https?://[A-Za-z0-9.:\[\]-]+(/[A-Za-z0-9._~/-]*)?")

Row = dict[str, str]


class Refused(Exception):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(f"{code}: {message}")
        self.code = code


def mark(item: Item) -> str:
    """What ties a sheet's row to its item in this database: a block's id, else ``m`` and the first twelve
    signs of the hash of its wording when drawn. Each begins with a letter, so that a spreadsheet keeps it
    as text: twelve hex signs may be digits alone, which it would turn into a number."""
    if item.block_id is not None:
        return item.block_id
    return f"m{item.text_hash[:12]}" if item.text_hash is not None else "none"


def _page_of(block_id: str | None) -> int | None:
    return None if block_id is None else int(block_id[1 : block_id.index("-")])


def _path(names: Mapping[UUID, tuple[UUID | None, str]], node: UUID | None) -> str:
    """The names of the node and those above it, the root's first."""
    found: list[str] = []
    while node is not None and node in names and len(found) < len(names):
        node, name = names[node]
        found.append(name)
    return " > ".join(reversed(found))


async def sheet_rows(connection: psycopg.AsyncConnection, sample_id: int, base_url: str) -> list[Row]:
    """The sheet's rows, one per item by its place; Refused where the sample is not there."""
    sample = await sample_by_id(connection, sample_id)
    document = None if sample is None else await document_for_job(connection, sample.document_id)
    if sample is None or document is None:
        raise Refused("unknown_sample", f"no sample {sample_id}")
    items = await items_of(connection, sample_id)
    statements = await statements_shown(
        connection, document.id, [i.statement_id for i in items if i.statement_id is not None]
    )
    nodes = await nodes_shown(connection, document.id, [i.node_id for i in items if i.node_id is not None])
    blocks = await blocks_shown(
        connection, document.conversion_id, [i.block_id for i in items if i.block_id is not None]
    )
    names = await node_names(connection, document.id)
    stales = await stale_items(connection, sample, items)  # none of a block
    base = base_url.rstrip("/")
    rows: list[Row] = []
    for item in items:
        row = dict.fromkeys(SHEET_HEADER, "") | {
            "item": str(item.id),
            "mark": mark(item),
            "shown": mark(item) if item.id not in stales else "",
            "stratum": item.stratum,
        }
        if item.block_id is not None:
            shown = blocks.get(item.block_id)
            page = _page_of(item.block_id)
            row |= {"kind": shown.kind if shown else "", "wording": shown.text if shown else ""}
            row |= {"link": f"{base}/quellen/{document.source_id}/bloecke?seite={page}"}
            row |= {"verdict": NOT_ASKED, "reasons": NOT_ASKED}
        else:
            found: Shown | None
            key: UUID | None
            if item.statement_id is not None:
                what, key, found = "statement", item.statement_id, statements.get(item.statement_id)
            else:  # an item points at one thing (migration gold): a node's
                what, key = "node", item.node_id
                found = nodes.get(item.node_id) if item.node_id is not None else None
            page = _page_of(item.first_block) or (found.page if found else None)
            at = f"seite={page}" if page is not None else ""
            stale = stales.get(item.id)
            if found is not None:
                row |= {"kind": found.kind, "wording": found.wording or "", "lead_in": found.lead_in or ""}
                row |= {"quote": found.quote or "", "path": _path(names, found.under)}
                address = f"zeile={what}:{key}" + (f"&{at}" if at else "")
            else:  # replaced or taken away since the draw: the item names it still, the tree no more
                address = at
            if stale is not None:  # no longer what was drawn: nothing to judge
                row |= {"kind": stale, "verdict": NOT_ASKED, "reasons": NOT_ASKED}
            row |= {
                "link": f"{base}/dokumente/{document.id}/baum" + (f"?{address}" if address else ""),
                "expected": NOT_ASKED,
            }
        row["page"] = "" if page is None else str(page)
        rows.append(row)
    return rows


def _as_text(value: str) -> str:
    return f"'{value}" if value.startswith(_FORMULA) else value


def encoded(rows: Sequence[Row]) -> bytes:
    """The sheet as a file: UTF-8 with a BOM, ``;`` between cells, CRLF; formula-like cells as text."""
    out = io.StringIO(newline="")
    writer = csv.writer(out, delimiter=";", lineterminator="\r\n")
    writer.writerow(SHEET_HEADER)
    writer.writerows([_as_text(row[column]) for column in SHEET_HEADER] for row in rows)
    return (BOM + out.getvalue()).encode("utf-8")


def repository() -> Path | None:
    """The working tree this code lies in, where it lies in one (not in an image)."""
    return next((folder for folder in Path(__file__).resolve().parents if (folder / ".git").exists()), None)


def destination_refused(root: Path | None, fd: int) -> bool:
    """Whether ``fd`` is a file a sheet must not go to: one of the repository at ``root`` outside its local
    folder. A pipe, a terminal, or a file where no repository is around cannot be told: allowed."""
    if root is None:
        return False
    written = os.fstat(fd)
    if not stat.S_ISREG(written.st_mode):
        return False
    for folder, _, names in os.walk(root / LOCAL_FOLDER):
        for name in names:
            there = os.stat(os.path.join(folder, name))
            if (there.st_dev, there.st_ino) == (written.st_dev, written.st_ino):
                return False
    return True


def _url(value: str) -> str:
    if _URL.fullmatch(value) is None:
        raise argparse.ArgumentTypeError("the base URL is http(s)://host[:port][/path]")
    return value


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="python -m app.quality.sheet", description=__doc__.splitlines()[0])
    parser.add_argument("--sample", required=True, type=int)
    parser.add_argument("--base-url", required=True, type=_url)
    return parser


async def _rows(settings: Settings, sample_id: int, base_url: str) -> list[Row]:
    url = settings.database_url.get_secret_value()
    async with await psycopg.AsyncConnection.connect(
        url, autocommit=True, **CONNECTION_OPTIONS
    ) as connection:
        return await sheet_rows(connection, sample_id, base_url)


def main(argv: Sequence[str] | None = None) -> int:
    args = _parser().parse_args(sys.argv[1:] if argv is None else list(argv))  # a call amiss exits with 2
    settings = Settings()
    configure_logging(settings.log_level, settings.log_format, stream=sys.stderr)
    if destination_refused(repository(), sys.stdout.fileno()):
        log.error(
            "refused: a judging sheet goes to data/gold-local/ or down a pipe, nowhere else in the tree"
        )
        return 1
    try:
        rows = asyncio.run(
            _rows(settings, args.sample, args.base_url), loop_factory=asyncio.SelectorEventLoop
        )
    except Refused as refused:
        log.error("%s", refused)
        return 1
    sys.stderr.write(WARNING + "\n")
    sys.stdout.buffer.write(encoded(rows))
    sys.stdout.flush()
    return 0


if __name__ == "__main__":
    sys.exit(main())
