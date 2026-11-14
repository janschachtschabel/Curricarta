"""``python -m app.quality.judge --sample <id> --account <name> < data/gold-local/<label>-<kind>.csv``: the
judgements of a judging sheet (``python -m app.quality.sheet``) go in as the account's (plan H-3 §3.3) - all
of them in one transaction, or none where one row breaks a rule. On stdout as JSON how many rows were
judged (new, changed, unchanged), left empty, refused; on stderr the line and rule of each refused row,
never a cell's content.

A row names its item and mark: the mark must be the item's in this database, else the sheet is another
database's. A statement's or anchor's item is judged by a verdict with its reasons from the fixed list
(plan H-3 §1.2), a block's by a count alone; a row whose judging cells are empty (or ``n/a``) is not judged
yet and takes nothing away. A note longer than the table holds refuses the sheet; one alone, too."""

import argparse
import asyncio
import json
import logging
import re
import sys
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import cast

import psycopg

from app.core.logging import configure_logging
from app.core.settings import Settings
from app.db.gold import Item, Judgement, Reason, SampleKind, Verdict, items_of, judge_all, sample_by_id
from app.db.pool import CONNECTION_OPTIONS
from app.quality.sheet import NOT_ASKED, mark
from app.quality.sheet_read import SheetLine, SheetRefused, read_sheet

log = logging.getLogger(__name__)

__all__ = ["SheetRefused", "Taken", "take_in"]

NOTE_LONGEST = 500  # signs, as migration gold holds a note
COUNT_MOST = 500
# The reasons each verdict takes (plan H-3 §1.2), by the kind of sample; correct takes none
STATEMENT_REASONS: dict[str, frozenset[str]] = {
    "imprecise": frozenset({"boundary", "kind", "fields"}),
    "wrong": frozenset({"not_a_statement", "not_in_document", "node"}),
}
ANCHOR_REASONS: dict[str, frozenset[str]] = {
    "imprecise": frozenset({"boundary"}),
    "wrong": frozenset({"wrong_place"}),
}
NOT_FOUND_REASONS: dict[str, frozenset[str]] = {"wrong": frozenset({"missed"})}  # the wording is there
_REASON_ORDER = (
    "not_a_statement", "not_in_document", "node", "boundary", "kind", "fields", "wrong_place", "missed",
)  # fmt: skip
_SPLIT = re.compile(r"[\s,;|]+")
_BY_NAME = "SELECT id FROM account WHERE name = %s"
_OF_ITEM, _OF_ACCOUNT = "gold_judgement_item_id_fkey", "gold_judgement_judged_by_fkey"  # migration gold's


class Refused(Exception):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(f"{code}: {message}")
        self.code = code


@dataclass(frozen=True)
class Taken:
    judged: int  # rows with a judgement: new, changed and unchanged
    new: int
    changed: int
    unchanged: int
    left_empty: int


def _reasons_taken(kind: SampleKind, stratum: str) -> Mapping[str, frozenset[str]]:
    if kind == "statement":
        return STATEMENT_REASONS
    return NOT_FOUND_REASONS if stratum.startswith("notFound:") else ANCHOR_REASONS


def _judged(line: SheetLine, item: Item, kind: SampleKind) -> Judgement | str | None:
    """The row's judgement of its item, None where it is left empty, else the rule it breaks."""
    cells = {name: "" if value == NOT_ASKED else value for name, value in line.cells.items()}
    verdict, count, note = cells.get("verdict", ""), cells.get("expected", ""), line.cells.get("note", "")
    named = set(_SPLIT.split(cells.get("reasons", ""))) - {""}
    if not named <= set(_REASON_ORDER):
        return "reasons_amiss"
    reasons = tuple(sorted(named, key=_REASON_ORDER.index))
    if len(note) > NOTE_LONGEST:
        return "note_too_long"
    if item.block_id is not None:
        if verdict or reasons:
            return "verdict_not_asked"
        if not count:
            return "note_alone" if note else None
        if not count.isdigit() or int(count) > COUNT_MOST:
            return "count_amiss"
        return Judgement(None, (), int(count), note or None)
    if count:
        return "count_not_asked"
    if not verdict:
        return "reasons_amiss" if reasons else "note_alone" if note else None
    taken = _reasons_taken(kind, item.stratum)
    if verdict != "correct" and verdict not in taken:
        return "verdict_unknown"
    if (verdict == "correct") != (not reasons) or not set(reasons) <= taken.get(verdict, frozenset()):
        return "reasons_amiss"
    return Judgement(cast(Verdict, verdict), cast(tuple[Reason, ...], reasons), None, note or None)


def judgements_in(
    lines: Sequence[SheetLine], items: Mapping[int, Item], kind: SampleKind
) -> tuple[list[tuple[int, Judgement]], int]:
    """The sheet's judgements by item, and how many rows were left empty; SheetRefused naming each row
    that breaks a rule."""
    problems: list[str] = []
    judgements: list[tuple[int, Judgement]] = []
    seen: set[int] = set()
    left_empty = 0
    for line in lines:
        number = line.cells["item"]
        item = items.get(int(number)) if number.isdigit() else None
        if item is None:
            problems.append(f"line {line.line}: item_unknown")
            continue
        if line.cells["mark"] != mark(item):
            problems.append(f"line {line.line}: mark_differs")
            continue
        if item.id in seen:
            problems.append(f"line {line.line}: item_twice")
            continue
        seen.add(item.id)
        found = _judged(line, item, kind)
        if isinstance(found, str):
            problems.append(f"line {line.line}: {found}")
        elif found is None:
            left_empty += 1
        else:
            judgements.append((item.id, found))
    if problems:
        raise SheetRefused(problems)
    return judgements, left_empty


async def take_in(connection: psycopg.AsyncConnection, sample_id: int, account: str, data: bytes) -> Taken:
    """The sheet's judgements, as the account's, in one transaction; SheetRefused where a row breaks a
    rule, Refused where the sample or the account is not there - nothing written either way."""
    cursor = await connection.execute(_BY_NAME, (account,))
    found = await cursor.fetchone()
    if found is None:
        raise Refused("unknown_account", "no account of that name")
    sample = await sample_by_id(connection, sample_id)
    if sample is None:
        raise Refused("unknown_sample", f"no sample {sample_id}")
    lines = read_sheet(data)
    items = {item.id: item for item in await items_of(connection, sample_id)}
    judgements, left_empty = judgements_in(lines, items, sample.kind)
    try:  # in the items' order: two imports at once take their rows' locks in one order, and deadlock not
        judged = await judge_all(connection, found[0], sorted(judgements, key=lambda judged: judged[0]))
    except psycopg.errors.ForeignKeyViolation as violated:  # taken away meanwhile
        if violated.diag.constraint_name == _OF_ACCOUNT:
            raise Refused("unknown_account", "the account went while the sheet was read") from None
        if violated.diag.constraint_name == _OF_ITEM:  # with its sample, with its document
            raise Refused("unknown_sample", f"no sample {sample_id}") from None
        raise
    return Taken(len(judgements), judged.new, judged.changed, judged.unchanged, left_empty)


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="python -m app.quality.judge", description=__doc__.splitlines()[0])
    parser.add_argument("--sample", required=True, type=int)
    parser.add_argument("--account", required=True)
    return parser


async def _taken(settings: Settings, sample_id: int, account: str, data: bytes) -> Taken:
    url = settings.database_url.get_secret_value()
    async with await psycopg.AsyncConnection.connect(
        url, autocommit=True, **CONNECTION_OPTIONS
    ) as connection:
        return await take_in(connection, sample_id, account, data)


def _print(printed: dict[str, int]) -> None:
    sys.stdout.buffer.write((json.dumps(printed) + "\n").encode("utf-8"))
    sys.stdout.flush()


def main(argv: Sequence[str] | None = None) -> int:
    args = _parser().parse_args(sys.argv[1:] if argv is None else list(argv))  # a call amiss exits with 2
    settings = Settings()
    configure_logging(settings.log_level, settings.log_format, stream=sys.stderr)
    data = sys.stdin.buffer.read()
    try:
        taken = asyncio.run(
            _taken(settings, args.sample, args.account, data), loop_factory=asyncio.SelectorEventLoop
        )
    except Refused as refused:
        log.error("%s", refused)
        return 1
    except SheetRefused as refused:
        log.error("sheet refused, nothing written: %s", refused)
        _print(dict.fromkeys(("sample", "judged", "new", "changed", "unchanged", "left_empty"), 0)
               | {"sample": args.sample, "refused": len(refused.problems)})  # fmt: skip
        return 1
    _print({"sample": args.sample, **vars(taken), "refused": 0})
    return 0


if __name__ == "__main__":
    sys.exit(main())
