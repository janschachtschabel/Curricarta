"""X5's plausibility checks (plan M1 8.2): what SHACL cannot see of the first layer, each a finding on
the row it is about.

- ``x5.heading_as_statement``: a statement that is a heading of the document - its node's or another's
  (a sub-heading the skeleton made a node beside it), a rejected node's title aside -, the same text
  hash, numbering aside (the statement rules say a heading is no statement).
- ``x5.label_as_statement``: a statement of unclear kind that is a fragment - a figure's label, a
  table's head, a value: three words at most, or more digits than letters, and no sentence; a value
  with its unit always ("40 Std.", "(ca. 20 Std.)", "Zeitrichtwert: 40 Std."), though it ends with a
  point (acceptance M1: 255 of unclear kind).
- ``x5.lead_in_as_statement``: a statement whose wording is a lead-in at its node - its own or
  another's -, its colon or ellipsis aside (the rules say a lead-in stands with what it leads); not one
  ending as a sentence, an action goal the model gave its steps as their lead-in too (Hochbauberufe
  BW: 8 of 8).
- ``x5.unit_without_statements``: a unit read whole that holds no statement and checked nothing absent;
  at its node, else at the document.
- ``x5.rule_bounds``: a rule of the frame whose lower bound lies above its upper one, or whose share is
  no share.
- ``x5.retired_value``: a function, node type, statement kind or subkind or obligation the vocabularies
  have retired since it was written.

What SHACL checks is not checked again here: required fields, a subkind under its kind, a node type
under its function (cur-shapes.ttl). No vocabulary says which statement kinds a node type takes, and the
first layer holds no hours or shares to sum (plan M1, Nachtrag 8a).
"""

import re
import unicodedata
from collections.abc import Collection
from typing import Any
from uuid import UUID

import psycopg
import regex

from app.db.findings import Finding
from app.domain.wording import folded, normalized, text_hash

_STATEMENTS = """
SELECT id, node_id, verbatim, lead_in, text_hash, statement_kind_iri FROM statement
WHERE document_id = %s AND review_status_iri <> 'https://w3id.org/wlo/curriculum/vocab#rev_rejected'
ORDER BY node_id, position
"""
_TITLES = """
SELECT original_title FROM node WHERE document_id = %s AND original_title IS NOT NULL
AND review_status_iri <> 'https://w3id.org/wlo/curriculum/vocab#rev_rejected'
"""
_UNCLASSIFIED = "https://w3id.org/wlo/curriculum/vocab#kind_unclassified"
LABEL_WORDS = 3  # a fragment's words at most: "Abb. 3", "Kraft (N)", "Legende"
_LEAD_ENDS = ":…. "  # what ends a lead-in written as a statement of its own ("… können:", "… können …")
# a sentence's end: its sign after a word, a closing bracket or quote before or after it ("(…,
# Segmentart).", "„Ich kann das.“"), not after an abbreviation's letter, a number or a sign ("z. B.",
# "1.", "Kraft (N).") nor as a point of an ellipsis ("können ..."); after a number only in a sentence
# of NUMBER_SENTENCE_WORDS words with letters ("… nach DIN EN 1996.", not "12 14 16 18."). Pi: German
# closes with "“"
_CLOSERS = "[\\p{Pe}\\p{Pi}\\p{Pf}\"']*"
_SENTENCE_END = regex.compile(rf"\p{{L}}{{2}}{_CLOSERS}[.!?]{_CLOSERS}$")
_NUMBER_END = regex.compile(rf"\d{_CLOSERS}[.!?]{_CLOSERS}$")
NUMBER_SENTENCE_WORDS = 4
# signs that set a text and say nothing - a zero width space; the soft hyphen too, unlike
# app/domain/wording.py, which first reads it as a word parted
_FORMAT_SIGNS = regex.compile(r"\p{Cf}")
# a value with its unit, as app/domain/wording.py folds it, its numbering kept: "40 Std.", "ca. 1,5
# Std.", "1.5 Std."; a label of LABEL_WORDS words or a numbering before it ("Zeitrichtwert: 40 Std.",
# "Lernfeld 12: 80 Std.", "1. 40 Std."), not a sentence; the brackets or quotes around it aside
# ("(ca. 20 Std.)")
_VALUE = regex.compile(
    r"(?:\p{L}[\p{L}\d]*(?: [\p{L}\d]+){0,2}:\s*)?"  # a label
    r"(?:\d{1,2}\.\s+)?(?:\p{L}{1,4}\.\s*)?\d[\d.,]*\s*\p{L}{1,4}\."
)
_OPENING = frozenset({"Ps", "Pi"})  # Unicode categories of what opens a bracket or a quote
_CLOSING = frozenset({"Pe", "Pf", "Pi"})  # and of what closes one: German closes with "“", a Pi
_QUOTES = "\"'"
# words whose point ends a fragment as an abbreviation ("siehe Abb."), though in a sentence it ends the
# sentence too ("… Maschinen usw."); a unit's (Std., Min.) ends a sentence around its value ("Es dauert
# 40 Std."), the value alone being one (_VALUE)
ABBREVIATIONS = frozenset({"abb", "bzw", "ca", "etc", "evtl", "ggf", "hrsg", "kap", "tab", "usw", "vgl"})
_WORD = re.compile(r"\w+")
_EMPTY_UNITS = """
SELECT unit_key, node_id FROM extraction_unit
WHERE document_id = %s AND statements = 0 AND cardinality(checked_absent) = 0 ORDER BY unit_key
"""
_RULES = "SELECT id, content FROM frame_part WHERE document_id = %s AND part_kind = 'rules' ORDER BY position"
_RETIRED = """
SELECT n.id, value.field, value.iri FROM node n
CROSS JOIN LATERAL (VALUES ('nodeFunction', n.function_iri), ('nodeType', n.node_type_iri),
    ('obligation', n.obligation_iri)) AS value (field, iri)
JOIN vocab_concept c ON c.iri = value.iri
WHERE n.document_id = %(document)s AND c.retired_in IS NOT NULL
UNION ALL
SELECT s.id, value.field, value.iri FROM statement s
CROSS JOIN LATERAL (VALUES ('statementKind', s.statement_kind_iri), ('statementSubkind', s.subkind_iri),
    ('obligation', s.obligation_iri)) AS value (field, iri)
JOIN vocab_concept c ON c.iri = value.iri
WHERE s.document_id = %(document)s AND c.retired_in IS NOT NULL AND s.review_status_iri <> 'https://w3id.org/wlo/curriculum/vocab#rev_rejected'
"""
_BOUNDS = (("minCount", "maxCount"), ("minAmount", "maxAmount"))


async def plausibility(connection: psycopg.AsyncConnection, document_id: UUID) -> list[Finding]:
    """The document's findings of the checks."""
    return [
        *await _statements_not_so(connection, document_id),
        *await _units_without_statements(connection, document_id),
        *await _rules_out_of_bounds(connection, document_id),
        *await _retired_values(connection, document_id),
    ]


def is_label(wording: str, kind: str | None) -> bool:
    """Whether a statement of this wording and kind is a label or a value: of unclear kind, and a
    value with its unit, or a fragment - LABEL_WORDS words at most, or more digits than letters - that
    is no sentence ("Die Kinder spielen.", which the elementary profile has the model keep
    unclassified)."""
    if kind != _UNCLASSIFIED:
        return False
    if _a_value(wording):
        return True
    if _a_sentence(wording) and not _abbreviated(wording):
        return False
    digits = sum(sign.isdigit() for sign in wording)
    letters = sum(sign.isalpha() for sign in wording)
    return len(_WORD.findall(wording)) <= LABEL_WORDS or digits > letters


def is_lead_in(wording: str, lead_ins: Collection[str]) -> bool:
    """Whether a wording is one of ``lead_ins`` - the lead-ins of its node's statements - written as a
    statement of its own, its end's colon or ellipsis aside. A wording ending as a sentence is none,
    though another statement takes it for its lead-in: a learning field's action goal stands above its
    steps and is a statement itself."""
    return _leads(wording, {_plain(lead_in) for lead_in in lead_ins})


def _leads(wording: str, plain: Collection[str]) -> bool:
    # ``plain``: the lead-ins as _plain makes them, once for a node's every statement
    return _plain(wording) in plain and not _a_sentence(wording)


def _a_sentence(wording: str) -> bool:
    """Whether a wording of two words at least ends as a sentence ends (a value with its unit is
    a label whatever its end, is_label)."""
    ended = _FORMAT_SIGNS.sub("", wording).rstrip()
    words = _WORD.findall(ended)
    if _SENTENCE_END.search(ended) is not None:
        return len(words) >= 2
    worded = sum(any(sign.isalpha() for sign in word) for word in words)
    return worded >= NUMBER_SENTENCE_WORDS and _NUMBER_END.search(ended) is not None


def _abbreviated(wording: str) -> bool:
    """Whether a wording ends with an abbreviation ("(siehe Abb.)"); for a label only, whose fragment
    has LABEL_WORDS words at most anyway."""
    words = _WORD.findall(wording)
    return bool(words) and words[-1].casefold() in ABBREVIATIONS


def _a_value(wording: str) -> bool:
    return _VALUE.fullmatch(folded(_unenclosed(_FORMAT_SIGNS.sub("", wording).strip()))) is not None


def _unenclosed(text: str) -> str:
    """The text without the brackets and quotes it opens and ends with; walked sign by sign, a run of
    them costs its length (a pattern anchored at the end tried at every sign of a long run)."""
    start, end = 0, len(text)
    while start < end and (text[start] in _QUOTES or unicodedata.category(text[start]) in _OPENING):
        start += 1
    while end > start and (text[end - 1] in _QUOTES or unicodedata.category(text[end - 1]) in _CLOSING):
        end -= 1
    return text[start:end]


def _plain(text: str) -> str:
    """The text as its hash takes it - a numbering or a bullet before it, a soft hyphen, the case
    aside -, its end's colon or ellipsis aside."""
    return normalized(text).rstrip(_LEAD_ENDS)


async def _statements_not_so(connection: psycopg.AsyncConnection, document_id: UUID) -> list[Finding]:
    """The statements that are none: a heading's, a label's, a lead-in's."""
    titles = {
        text_hash(title) for (title,) in await (await connection.execute(_TITLES, (document_id,))).fetchall()
    }
    rows = await (await connection.execute(_STATEMENTS, (document_id,))).fetchall()
    lead_ins: dict[UUID, set[str]] = {}  # each node's as _plain makes them, once
    for _, node_id, _, lead_in, _, _ in rows:
        if lead_in:
            lead_ins.setdefault(node_id, set()).add(_plain(lead_in))
    found: list[Finding] = []
    for statement_id, node_id, verbatim, _, hashed, kind in rows:
        if hashed in titles:
            found.append(
                Finding("x5.heading_as_statement", "warning", statement_id, "a statement that is a heading")
            )
        elif _leads(verbatim, lead_ins.get(node_id, set())):
            found.append(
                Finding("x5.lead_in_as_statement", "warning", statement_id, "a statement that is a lead-in")
            )
        elif is_label(verbatim, kind):
            found.append(
                Finding("x5.label_as_statement", "warning", statement_id, "a statement that is a label")
            )
    return found


async def _units_without_statements(connection: psycopg.AsyncConnection, document_id: UUID) -> list[Finding]:
    cursor = await connection.execute(_EMPTY_UNITS, (document_id,))
    return [
        Finding(
            "x5.unit_without_statements",
            "info",
            node_id or document_id,
            "a unit read whole holds no statement",
            details={"unit": key},
        )
        for key, node_id in await cursor.fetchall()
    ]


async def _rules_out_of_bounds(connection: psycopg.AsyncConnection, document_id: UUID) -> list[Finding]:
    cursor = await connection.execute(_RULES, (document_id,))
    found = []
    for part, content in await cursor.fetchall():
        for wrong in _contradictions(content):
            found.append(
                Finding("x5.rule_bounds", "warning", part, "a rule's bounds contradict", details=wrong)
            )
    return found


def _contradictions(content: dict[str, Any]) -> list[dict[str, Any]]:
    wrong = [
        {low: content[low], high: content[high]}
        for low, high in _BOUNDS
        if content.get(low) is not None and content.get(high) is not None and content[low] > content[high]
    ]
    share = content.get("maxShare")
    if share is not None and not 0 <= share <= 1:
        wrong.append({"maxShare": share})
    return wrong


async def _retired_values(connection: psycopg.AsyncConnection, document_id: UUID) -> list[Finding]:
    cursor = await connection.execute(_RETIRED, {"document": document_id})
    return [
        Finding(
            "x5.retired_value",
            "warning",
            found,
            "a value the vocabularies have retired",
            path=f"cur:{field}",
            details={"value": iri},
        )
        for found, field, iri in await cursor.fetchall()
    ]
