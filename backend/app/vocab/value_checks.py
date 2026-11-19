"""What a set of a holder's values asks, checked against the values' form (plan M3a E2;
app/vocab/value_forms.py) before the store is asked: each kind one the holder is offered (``not_held``);
each list's value one the form offers - active, of an active scheme -, or, at a value the set keeps by its
id, the one it holds already: a concept retired since stays until its field is changed, as an editor's
other fields do (app/vocab/form_values.py); a range's end not before its start (``out_of_order``). A
level is refused where the core's shapes never let the holder hold it (LEVEL_RULES: a qualification
level at a statement, a grading level but at a standard) and a range's end of another level system than
its start, both ``not_offered``. A problem names its field by its path in the set, ``workloads[1].unit``,
``workloads[0].periods[0].time_kind``. The store checks again (app/db/values.py); its refusals are named
here by the kind they are of.
"""

from collections.abc import Iterator, Mapping
from typing import Final
from uuid import UUID

from app.domain.l2 import HeldValues, HolderKind, LevelDraft, TimeSpanDraft, ValueDrafts, WorkloadDraft
from app.vocab.form_values import FieldError
from app.vocab.value_forms import (
    LEVEL_RULES,
    PERIODS,
    TABLE_OF,
    VALUE_FIELDS,
    VALUE_HOLDERS,
    ValueForm,
    ValueKind,
)

Draft = LevelDraft | TimeSpanDraft | WorkloadDraft
# a kind's ranges: its start's field and its end's
_RANGES: Final[Mapping[ValueKind, tuple[tuple[str, str], ...]]] = {
    "level_assignments": (),
    "time_spans": (("span_from", "span_to"),),
    "workloads": (("amount", "amount_to"),),
}


def check_values(
    form: ValueForm,
    holder: HolderKind,
    drafts: ValueDrafts,
    held: HeldValues | None,
    *,
    holder_type: str | None = None,
) -> None:
    """Check the set ``drafts`` at a holder of the kind ``holder`` - of the type ``holder_type``, a
    statement's kind -, which holds ``held`` now; FieldError for the first problem."""
    given = _given(drafts)
    for kind, entries in given.items():
        if entries and holder not in VALUE_HOLDERS[kind]:
            raise FieldError(kind, "not_held")
    kept = {draft.id: draft for draft in _stored(held)}
    for at, kind, draft in _walk(given):
        _check(form, kind, draft, at, kept.get(draft.id) if draft.id is not None else None)
        if isinstance(draft, LevelDraft):
            _check_level(form, holder, holder_type, draft, at)


def path_of(drafts: ValueDrafts, value_id: UUID) -> str:
    """The path of the id ``value_id`` in the set, first where it is named; the set's where it is not."""
    found = (at for at, _, draft in _walk(_given(drafts)) if draft.id == value_id)
    return next((f"{at}.id" for at in found), "values")


def kind_of_check(check: str | None) -> str:
    """The kind of value a refusal of the store's names by its check; the set's where none does."""
    by_table = {table: kind for kind, table in TABLE_OF.items()}
    return next((by_table[table] for table in by_table if check and check.startswith(table + "_")), "values")


def _given(drafts: ValueDrafts) -> dict[ValueKind, tuple[Draft, ...]]:
    return {
        "level_assignments": drafts.levels,
        "time_spans": drafts.time_spans,
        "workloads": drafts.workloads,
    }


def _walk(given: Mapping[ValueKind, tuple[Draft, ...]]) -> Iterator[tuple[str, ValueKind, Draft]]:
    """Each draft of the set with its path and kind, a workload's periods after it."""
    for kind, entries in given.items():
        for place, draft in enumerate(entries):
            yield f"{kind}[{place}]", kind, draft
            if isinstance(draft, WorkloadDraft):
                for at, period in enumerate(draft.periods):
                    yield f"{kind}[{place}].periods[{at}]", PERIODS, period


def _stored(held: HeldValues | None) -> Iterator[Draft]:
    """The holder's stored values as drafts, its workloads' periods among them."""
    if held is None:
        return
    yield from (level.value for level in held.levels)
    yield from (span.value for span in held.time_spans)
    for workload in held.workloads:
        yield workload.value
        yield from (period.value for period in workload.periods)


def _check_level(
    form: ValueForm, holder: HolderKind, holder_type: str | None, draft: LevelDraft, at: str
) -> None:
    """Refuse a level the holder never holds by the shapes (LEVEL_RULES) - at the level where its system's
    dimension rules it out, else at the dimension the assignment names -, and a range's end of another
    system than its start. A kept value is refused so too: the shapes reject it wherever it came from."""
    own = form.dimension_of.get(draft.level)
    for rule in LEVEL_RULES:
        if rule.holder != holder or (rule.unless is not None and rule.unless == holder_type):
            continue
        if own in rule.dimensions:
            raise FieldError(f"{at}.level", "not_offered")
        if draft.dimension in rule.dimensions:
            raise FieldError(f"{at}.dimension", "not_offered")
    if draft.level_to is not None and form.group_of.get(draft.level_to) != form.group_of.get(draft.level):
        raise FieldError(f"{at}.level_to", "not_offered")


def _check(form: ValueForm, kind: ValueKind, draft: Draft, at: str, before: Draft | None) -> None:
    for field in VALUE_FIELDS[kind]:
        value = getattr(draft, field.key)
        if field.kind != "concept" or value is None:
            continue
        offered = {concept.iri for concept in form.values.get(field.key, ())}
        if value not in offered and getattr(before, field.key, None) != value:
            raise FieldError(f"{at}.{field.key}", "not_offered")
    for start, end in _RANGES[kind]:
        least, most = getattr(draft, start), getattr(draft, end)
        if least is not None and most is not None and most < least:
            raise FieldError(f"{at}.{end}", "out_of_order")
