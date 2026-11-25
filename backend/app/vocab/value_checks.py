"""What a set of a holder's values asks, checked against the values' form (plan M3a E2;
app/vocab/value_forms.py) before the store is asked: each kind one the holder is offered (``not_held``);
each list's value one the form offers - active, of an active scheme -, or, at a value the set keeps by its
id, the one it holds already: a concept retired since stays until its field is changed, as an editor's
other fields do (app/vocab/form_values.py); a range's end not before its start (``out_of_order``). A
level is refused where the core's shapes never let the holder hold it (LEVEL_RULES: a qualification
level at a statement, a grading level but at a standard) and a range's end of another level system than
its start, both ``not_offered``. A problem names its field by its path in the set, ``workloads[1].unit``,
``workloads[0].periods[0].time_kind``. A specification's applicability contexts (plan M3a H1) are checked
so too - a context at another holder is ``not_held``, its sector and formality ones the form offers, its
levels by the rules of a context (LEVEL_RULES) -, by paths under ``contexts[0]``. The store checks again
(app/db/values.py); its refusals are named here by the kind they are of.
"""

from collections.abc import Iterator, Mapping, Sequence
from typing import Final
from uuid import UUID

from app.domain.l2 import (
    ContextDraft,
    HeldValues,
    HolderKind,
    LevelDraft,
    TimeSpanDraft,
    ValueDrafts,
    WorkloadDraft,
)
from app.vocab.form_values import FieldError
from app.vocab.forms import FormField
from app.vocab.value_forms import (
    CONTEXT_FIELDS,
    CONTEXT_HOLDERS,
    LEVEL_RULES,
    PERIODS,
    TABLE_OF,
    VALUE_FIELDS,
    VALUE_HOLDERS,
    RuleHolder,
    ValueForm,
    ValueKind,
)

Draft = LevelDraft | TimeSpanDraft | WorkloadDraft | ContextDraft
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
    if drafts.contexts and holder not in CONTEXT_HOLDERS:
        raise FieldError("contexts", "not_held")
    kept = {draft.id: draft for draft in _stored(held)}
    for at, kind, draft, within in _walk(drafts):
        before = kept.get(draft.id) if draft.id is not None else None
        fields = CONTEXT_FIELDS if isinstance(draft, ContextDraft) else VALUE_FIELDS[kind]
        _check(form, fields, kind, draft, at, before)
        if isinstance(draft, LevelDraft):  # a context's by a context's rules, which no type of it lifts
            _check_level(form, within or holder, None if within else holder_type, draft, at)


def check_held_levels(
    form: ValueForm, holder: HolderKind, holder_type: str | None, levels: Sequence[LevelDraft]
) -> None:
    """Check the levels a holder holds against the type ``holder_type`` it is to have - a statement's kind
    changed -, as a set of them at a holder of that type is checked (LEVEL_RULES); FieldError at the first
    level that stands in the way, by its path among the holder's values."""
    for place, level in enumerate(levels):
        _check_level(form, holder, holder_type, level, f"level_assignments[{place}]")


def path_of(drafts: ValueDrafts, value_id: UUID) -> str:
    """The path of the id ``value_id`` in the set, first where it is named; the set's where it is not."""
    found = (at for at, _, draft, _ in _walk(drafts) if draft.id == value_id)
    return next((f"{at}.id" for at in found), "values")


def kind_of_check(check: str | None) -> str:
    """The kind of value a refusal of the store's names by its check; the set's where none does."""
    by_table = {table: str(kind) for kind, table in TABLE_OF.items()} | {"applicability_context": "contexts"}
    return next((by_table[table] for table in by_table if check and check.startswith(table + "_")), "values")


def _given(drafts: ValueDrafts) -> dict[ValueKind, tuple[Draft, ...]]:
    return {
        "level_assignments": drafts.levels,
        "time_spans": drafts.time_spans,
        "workloads": drafts.workloads,
    }


def _walk(drafts: ValueDrafts) -> Iterator[tuple[str, ValueKind, Draft, RuleHolder | None]]:
    """Each draft of the set with its path, kind and the holder its level rules are of, a workload's periods
    after it, a context's levels and time spans after it."""
    for kind, entries in _given(drafts).items():
        for place, draft in enumerate(entries):
            yield f"{kind}[{place}]", kind, draft, None
            if isinstance(draft, WorkloadDraft):
                for at, period in enumerate(draft.periods):
                    yield f"{kind}[{place}].periods[{at}]", PERIODS, period, None
    for place, context in enumerate(drafts.contexts):
        yield f"contexts[{place}]", "level_assignments", context, None  # its own fields: CONTEXT_FIELDS
        inner: dict[ValueKind, tuple[Draft, ...]] = {
            "level_assignments": context.levels,
            "time_spans": context.time_spans,
        }
        for kind, entries in inner.items():
            for at, draft in enumerate(entries):
                yield f"contexts[{place}].{kind}[{at}]", kind, draft, "applicability_context"


def _stored(held: HeldValues | None) -> Iterator[Draft]:
    """The holder's stored values as drafts, its workloads' periods among them."""
    if held is None:
        return
    yield from (level.value for level in held.levels)
    yield from (span.value for span in held.time_spans)
    for workload in held.workloads:
        yield workload.value
        yield from (period.value for period in workload.periods)
    for context in held.contexts:
        yield context.value
        yield from (level.value for level in context.levels)
        yield from (span.value for span in context.time_spans)


def _check_level(
    form: ValueForm, holder: RuleHolder, holder_type: str | None, draft: LevelDraft, at: str
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


def _check(
    form: ValueForm, fields: Sequence[FormField], kind: ValueKind, draft: Draft, at: str, before: Draft | None
) -> None:
    for field in fields:
        value = getattr(draft, field.key)
        if field.kind != "concept" or value is None:
            continue
        offered = {concept.iri for concept in form.values.get(field.key, ())}
        if value not in offered and getattr(before, field.key, None) != value:
            raise FieldError(f"{at}.{field.key}", "not_offered")
    for start, end in () if isinstance(draft, ContextDraft) else _RANGES[kind]:
        least, most = getattr(draft, start), getattr(draft, end)
        if least is not None and most is not None and most < least:
            raise FieldError(f"{at}.{end}", "out_of_order")
