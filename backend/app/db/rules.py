"""A document's rules as the editors read and set them (plan M3a I, E10): a frame part of the kind rules is
the rule - its wording and parsed values in the keys of X3's schema
(ontology/schemas/x3-rahmenteile.schema.json), its unit and kind of requirement by their notations there, as
X3 writes them and X5's checks read them -, with what it applies to, its options and what it requires as links
to a node, a statement, a specification or a variant of its document (migration rule_link). Read, a unit and a
kind of requirement are named by their concepts.

An edit holds the tree's lock and refuses what every edit of the tree refuses (app/db/editing.py ``guard``):
the fields given set on the rule's revision (StaleRevision where it stands at another), a link role's targets
given replace its links, in their order, each once. Options are a selection rule's alone, required items a
prerequisite rule's (FieldError ``not_held``); a target is a row of the rule's document, a rejected statement
none (``unknown_value``); a unit and a kind of requirement an active concept of their list (``not_offered``).
A change makes the rule an editor's proposal and notes the document edited; one that changes nothing leaves it
as it was. A rule added by hand stands after the document's frame parts on the blocks an editor chose, as a
statement does (app/db/statement_editing.py), an editor's from the first: taken away it is deleted with the
findings on it, a run's is rejected and stays."""

from collections.abc import Mapping, Sequence
from typing import Any, Final, Literal, get_args
from uuid import UUID

import psycopg
from psycopg.types.json import Jsonb

from app.db.anchors import new_entity, write_anchor
from app.db.documents import DOCUMENT_VISIBLE
from app.db.editing import (
    CV,
    DOCUMENT,
    HUMAN,
    PROPOSED,
    SECTOR,
    check_revision,
    drop_findings,
    edit_query,
    guard,
    mark_edited,
    returned_revision,
    row_of,
    target_of,
)
from app.db.rule_rows import CONTENT_KEYS, Link, LinkRole, Rule, TargetKind, links_of, rules_of
from app.db.source_queries import Reader
from app.db.statement_editing import REJECTED, HandAnchor, Taken, anchor_drafts
from app.domain.text import UNSTORABLE
from app.vocab.form_values import FieldError
from app.vocab.forms import MOST_TEXT, MOST_VERBATIM

__all__ = [
    "DOCUMENT_OF_RULE", "Link", "Rule", "RuleKind", "add_rule", "drop_or_reject_rule", "edit_rule",
    "rules_of",
]  # fmt: skip

RuleKind = Literal["selection", "prerequisite", "completion", "recognition", "progression"]  # X3's ruleKind
DOCUMENT_OF_RULE = f"""
SELECT d.id, sector.notation FROM frame_part f JOIN document d ON d.id = f.document_id {SECTOR}
WHERE f.id = %(id)s AND f.part_kind = 'rules' AND {DOCUMENT_VISIBLE}
"""  # noqa: S608 - fixed parts
# the edit's link fields, by the role each sets; and the one kind of rule each but applies_to is of
LINK_FIELDS: Final[dict[str, LinkRole]] = {
    "applies_to": "applies_to",
    "options": "option",
    "requires": "requires",
}
_ROLE_OF_KIND: Final[dict[LinkRole, str]] = {"option": "selection", "requires": "prerequisite"}
_SCHEMES: Final = {"amount_unit": CV + "WorkloadUnits", "requirement_kind": CV + "RequirementKinds"}
_NOTATION = """
SELECT c.notation FROM vocab_concept c JOIN vocab_scheme s ON s.iri = c.scheme_iri
WHERE c.iri = %s AND c.scheme_iri = %s AND c.retired_in IS NULL AND s.retired_in IS NULL
"""
_RULE = "SELECT revision, content FROM frame_part WHERE id = %s FOR UPDATE"
# each target of the document by its kind - a variant with its specification -, a rejected statement none
_TARGETS = """
SELECT id, 'node', NULL::uuid FROM node WHERE document_id = %(document)s AND id = ANY(%(ids)s)
UNION ALL
SELECT id, 'statement', NULL FROM statement
WHERE document_id = %(document)s AND id = ANY(%(ids)s) AND review_status_iri <> %(rejected)s
UNION ALL
SELECT id, 'specification', NULL FROM specification WHERE document_id = %(document)s AND id = ANY(%(ids)s)
UNION ALL
SELECT v.id, 'variant', v.specification_id FROM variant v JOIN specification s ON s.id = v.specification_id
WHERE s.document_id = %(document)s AND v.id = ANY(%(ids)s)
"""
_LINK = """
INSERT INTO rule_link (frame_part_id, document_id, role, position, node_id, statement_id, specification_id,
    variant_id, variant_specification_id)
VALUES (%(rule)s, %(document)s, %(role)s, %(position)s, %(node)s, %(statement)s, %(specification)s,
    %(variant)s, %(of)s)
"""
_ADDED = """
INSERT INTO frame_part (id, document_id, part_kind, content, origin_scheme, origin_iri, review_status_scheme,
    review_status_iri, position, by_hand)
SELECT %s, %s, 'rules', %s, %s, %s, %s, %s, coalesce(max(position), 0) + 1, true FROM frame_part
WHERE document_id = %s
"""
_TAKEN = """
SELECT f.revision, f.by_hand, f.review_status_iri = %s AS rejected,
    array(SELECT id FROM anchor WHERE frame_part_id = f.id)
        || array(SELECT id FROM level_assignment WHERE frame_part_id = f.id) AS held
FROM frame_part f WHERE f.id = %s FOR UPDATE
"""


async def edit_rule(
    connection: psycopg.AsyncConnection,
    reader: Reader,
    rule_id: UUID,
    revision: int,
    given: Mapping[str, Any],
) -> int | None:
    """Set the rule's fields and links ``given`` - by CONTENT_KEYS' and LINK_FIELDS' keys - on its revision
    ``revision``; its revision after, None where ``reader`` sees no such rule. FieldError, StaleRevision or a
    refusal of ``guard``, and then nothing is changed."""
    for key in given:
        if key not in CONTENT_KEYS and key not in LINK_FIELDS:
            raise FieldError(key, "unknown")
    async with connection.transaction():
        target = await target_of(connection, DOCUMENT_OF_RULE, reader, rule_id)
        if target is None:
            return None
        await guard(connection, target.document_id)
        row = await row_of(connection, _RULE, rule_id)
        if row is None:  # taken away meanwhile
            return None
        content: dict[str, Any] = check_revision(row, revision)["content"]
        merged = content | {CONTENT_KEYS[key]: await _stored(connection, key, value)
                            for key, value in given.items() if key in CONTENT_KEYS}  # fmt: skip
        current = await links_of(connection, rule_id)
        links = {role: current.get(role, ()) for role in get_args(LinkRole)}
        for field, role in LINK_FIELDS.items():
            if field in given:
                links[role] = await _targets(connection, target.document_id, field, given[field])
        for role, kind in _ROLE_OF_KIND.items():
            if links[role] and merged.get("ruleKind") != kind:
                raise FieldError(next(key for key, named in LINK_FIELDS.items() if named == role), "not_held")
        if merged == content and all(links[role] == current.get(role, ()) for role in links):
            return revision
        cursor = await connection.execute(
            edit_query("frame_part", ["content = %(content)s"]),
            {"id": rule_id, "content": Jsonb(merged), "human": HUMAN, "proposed": PROPOSED},
        )
        for role, targets in links.items():
            if targets != current.get(role, ()):
                await _set_links(connection, target.document_id, rule_id, role, targets)
        await mark_edited(connection, target.document_id)
        return await returned_revision(cursor)


async def add_rule(
    connection: psycopg.AsyncConnection,
    reader: Reader,
    document_id: UUID,
    kind: str,
    verbatim: str,
    anchors: Sequence[HandAnchor],
) -> UUID | None:
    """A new rule of ``kind`` worded ``verbatim`` on ``anchors`` - one at least - after the document's frame
    parts, an editor's proposal; its id. None where ``reader`` sees no such document. FieldError or a refusal
    of ``guard``."""
    content = {
        "ruleKind": _kind(kind),
        "verbatim": _text("verbatim", verbatim, MOST_VERBATIM),
    } | dict.fromkeys(
        ("minCount", "maxCount", "minAmount", "maxAmount", "amountUnit", "requirementKind", "maxShare")
    )
    async with connection.transaction():
        target = await target_of(connection, DOCUMENT, reader, document_id)
        if target is None:
            return None
        drafts = await anchor_drafts(connection, document_id, anchors)
        await guard(connection, document_id)
        made = await new_entity(connection, "frame_part")
        await connection.execute(
            _ADDED,
            (made, document_id, Jsonb(content | {"optionTexts": []}), CV + "Origins", HUMAN,
             CV + "ReviewStatuses", PROPOSED, document_id),
        )  # fmt: skip
        cursor = await connection.execute("SELECT conversion_id FROM document WHERE id = %s", (document_id,))
        conversion = await cursor.fetchone()
        assert conversion is not None  # noqa: S101 - the document seen above, under the tree's lock
        for draft in drafts:
            await write_anchor(connection, document_id, conversion[0], draft, frame_part_id=made)
        await mark_edited(connection, document_id)
        return made


async def drop_or_reject_rule(
    connection: psycopg.AsyncConnection, reader: Reader, rule_id: UUID, revision: int
) -> Taken | None:
    """Take the rule away on its revision ``revision``: delete it where an editor made it, with the findings
    on it, its anchors and levels; else reject it, where it is not so already. Which was done; None where
    ``reader`` sees no such rule. StaleRevision or a refusal of ``guard``, and then nothing is changed."""
    async with connection.transaction():
        target = await target_of(connection, DOCUMENT_OF_RULE, reader, rule_id)
        if target is None:
            return None
        await guard(connection, target.document_id)
        cursor = await connection.execute(_TAKEN, (REJECTED, rule_id))
        found = await cursor.fetchone()
        if found is None:
            return None
        current, by_hand, rejected, held = found
        check_revision({"revision": current}, revision)
        if by_hand:
            await drop_findings(connection, target.document_id, [rule_id, *held])
            await connection.execute("DELETE FROM frame_part WHERE id = %s", (rule_id,))
            taken = Taken("deleted", None)
        elif rejected:
            return Taken("rejected", current, changed=False)
        else:
            cursor = await connection.execute(
                "UPDATE frame_part SET review_status_iri = %s, revision = revision + 1, updated_at = now()"
                " WHERE id = %s RETURNING revision",
                (REJECTED, rule_id),
            )
            taken = Taken("rejected", await returned_revision(cursor))
        await mark_edited(connection, target.document_id)
        return taken


async def _stored(connection: psycopg.AsyncConnection, key: str, value: Any) -> Any:
    """A field's value as the rule's content keeps it; FieldError where it may not be set so."""
    if key == "kind":
        return _kind(value)
    if key == "verbatim":
        return _text(key, value, MOST_VERBATIM)
    if key == "option_texts":  # None empties them
        return [_text(key, text, MOST_TEXT) for text in value or ()]
    if key in _SCHEMES:
        if value is None:
            return None
        cursor = await connection.execute(_NOTATION, (value, _SCHEMES[key]))
        found = await cursor.fetchone()
        if found is None or found[0] is None:
            raise FieldError(key, "not_offered")
        return found[0]
    if value is None or key in ("min_count", "max_count"):
        return value
    return int(value) if value == int(value) else float(value)  # JSON keeps a number, as X3 gave it


async def _targets(
    connection: psycopg.AsyncConnection, document_id: UUID, field: str, given: Sequence[UUID] | None
) -> tuple[Link, ...]:
    """The targets ``given`` of a link field, each once in their order; FieldError ``unknown_value`` where one
    is no row of the document a rule may name. None names none."""
    ids = list(dict.fromkeys(given or ()))
    cursor = await connection.execute(_TARGETS, {"document": document_id, "ids": ids, "rejected": REJECTED})
    found: dict[UUID, tuple[TargetKind, UUID | None]] = {
        row_id: (kind, of) for row_id, kind, of in await cursor.fetchall()
    }
    if len(found) != len(ids):
        raise FieldError(field, "unknown_value")
    return tuple(Link(row_id, found[row_id][0], found[row_id][1]) for row_id in ids)


async def _set_links(
    connection: psycopg.AsyncConnection,
    document_id: UUID,
    rule_id: UUID,
    role: LinkRole,
    links: Sequence[Link],
) -> None:
    await connection.execute("DELETE FROM rule_link WHERE frame_part_id = %s AND role = %s", (rule_id, role))
    async with connection.cursor() as cursor:
        await cursor.executemany(
            _LINK,
            [
                {"rule": rule_id, "document": document_id, "role": role, "position": place,
                 **{kind: link.target if link.kind == kind else None
                    for kind in ("node", "statement", "specification", "variant")},
                 "of": link.of}
                for place, link in enumerate(links, start=1)
            ],
        )  # fmt: skip


def _kind(value: Any) -> str:
    if value not in get_args(RuleKind):
        raise FieldError("kind", "not_offered")
    return str(value)


def _text(key: str, value: Any, most: int) -> str:
    """A text as the content keeps it; FieldError where it may not be set so."""
    if not isinstance(value, str):
        raise FieldError(key, "not_text")
    if not value.strip():
        raise FieldError(key, "required")
    if UNSTORABLE.search(value):
        raise FieldError(key, "not_storable")
    if len(value) > most:
        raise FieldError(key, "too_long")
    return value
