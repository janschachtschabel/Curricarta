"""The editor's form schema (plan M1 9.1, Paket 9 G10): the fields of a node and of a statement, each
no laxer than the core's shapes demand, with the active values of their lists - a profile's node types
and subkinds with label, definition, note and examples."""

from collections.abc import AsyncIterator
from pathlib import Path

import psycopg
import pytest
from rdflib import Graph, Namespace, URIRef

from app.db.migrate import migrate
from app.db.value_rows import COLUMN_OF, HOLDERS_OF
from app.domain.l1 import WORDING_FIELDS
from app.domain.l2 import HolderKind
from app.vocab.forms import NODE_FIELDS, STATEMENT_FIELDS, FormField, form_of
from app.vocab.store import load_vocabulary
from app.vocab.value_forms import TABLE_OF, VALUE_FIELDS, VALUE_HOLDERS, ValueKind, value_form_of
from tests.support import ontology_vocabulary

ONTOLOGY = Path(__file__).resolve().parents[3] / "ontology"
CV = "https://w3id.org/wlo/curriculum/vocab#"
LVL = "https://w3id.org/wlo/curriculum/level/"
KD = "https://w3id.org/wlo/curriculum/dimension/"
SCHOOL = "https://w3id.org/wlo/curriculum/profile/school#"
SH = Namespace("http://www.w3.org/ns/shacl#")
CUR = Namespace("https://w3id.org/wlo/curriculum/core#")
SHS = Namespace("https://w3id.org/wlo/curriculum/shapes#")


def shape_counts(shapes: Graph, shape: URIRef) -> dict[str, tuple[int, int | None]]:
    """The cardinality the shape demands of each property, where a violation follows from it."""
    found: dict[str, tuple[int, int | None]] = {}
    for prop in shapes.objects(shape, SH.property):
        if shapes.value(prop, SH.severity) not in (None, SH.Violation):
            continue  # a warning asks, it does not demand
        path = shapes.value(prop, SH.path)
        least, most = shapes.value(prop, SH.minCount), shapes.value(prop, SH.maxCount)
        found["cur:" + str(path).removeprefix(str(CUR))] = (
            0 if least is None else int(str(least)),
            None if most is None else int(str(most)),
        )
    return found


@pytest.mark.parametrize(
    ("shape", "fields"),
    [("CurriculumNodeShape", NODE_FIELDS), ("StatementShape", STATEMENT_FIELDS)],
    ids=["node", "statement"],
)
def test_a_field_is_no_laxer_than_the_shapes_demand(shape: str, fields: tuple[FormField, ...]) -> None:
    shapes = Graph().parse(ONTOLOGY / "ontologie" / "cur-shapes.ttl", format="turtle")
    counts = shape_counts(shapes, SHS[shape])

    checked = [(field, field.path) for field in fields if field.path is not None]
    assert checked  # the shapes know most of them
    for field, path in checked:
        least, most = counts[path]  # a field's path is one the shape names
        assert field.required or least == 0, field.key
        assert not field.many or most is None, field.key


def test_a_statement_offers_its_wording_fields_as_texts() -> None:
    offered = {field.key: field for field in STATEMENT_FIELDS}

    for name in WORDING_FIELDS:
        assert (offered[name].kind, offered[name].required, offered[name].many) == ("text", False, False)
    assert offered["verbatim"].kind == "longtext" and offered["verbatim"].required
    assert offered["addressees"].many and offered["addressees"].required


@pytest.fixture
async def connection(database_url: str, preloaded_vocabulary: None) -> AsyncIterator[psycopg.AsyncConnection]:
    migrate(database_url)
    load_vocabulary(database_url, ontology_vocabulary())
    async with await psycopg.AsyncConnection.connect(database_url, autocommit=True) as opened:
        yield opened


@pytest.mark.pg
@pytest.mark.anyio
async def test_a_profile_s_form_offers_its_active_values_with_their_texts(
    connection: psycopg.AsyncConnection,
) -> None:
    await connection.execute(
        "UPDATE vocab_concept SET retired_in = 1 WHERE iri = ANY(%s)",
        ([SCHOOL + "Inhaltsbereich", CV + "addr_family"],),
    )

    form = await form_of(connection, "school")

    assert form is not None and form.sector == "school" and form.profile == SCHOOL + "Terminology"
    offered = {key: [value.iri for value in values] for key, values in form.values.items()}
    assert len(offered["node_type"]) == 9  # the school's ten node types but the retired one
    assert SCHOOL + "Inhaltsbereich" not in offered["node_type"]
    assert len(offered["subkind"]) == 13 and len(offered["statement_kind"]) == 8
    assert len(offered["function"]) == 7 and len(offered["obligation"]) == 8
    assert CV + "addr_family" not in offered["addressees"] and len(offered["addressees"]) == 5
    staged = next(value for value in form.values["node_type"] if value.iri == SCHOOL + "Stufenabschnitt")
    assert (staged.label, staged.broader) == ("Stufenabschnitt", (CV + "fn_grouping",))
    assert staged.examples and staged.definition and staged.delimitation
    labels = [value.label for value in form.values["function"]]
    assert labels == sorted(labels, key=str.casefold)  # in the order of their labels
    assert set(form.values) == {
        field.key for field in (*NODE_FIELDS, *STATEMENT_FIELDS) if field.kind in ("concept", "concepts")
    }


@pytest.mark.pg
@pytest.mark.anyio
async def test_a_sector_without_a_profile_has_no_form(connection: psycopg.AsyncConnection) -> None:
    assert await form_of(connection, "kindergarten") is None


# a kind of value: the property its holder names it by, the class of the value, the shape of that class
VALUE_SHAPES: dict[ValueKind, tuple[str, str, str]] = {
    "workloads": ("workload", "Workload", "WorkloadShape"),
    "time_spans": ("timeSpan", "TimeSpan", "TimeSpanShape"),
    "level_assignments": ("levelAssignment", "LevelAssignment", "LevelAssignmentShape"),
}
HOLDER_SHAPES: dict[HolderKind, str] = {
    "node": "CurriculumNodeShape", "statement": "StatementShape", "specification": "SpecificationShape",
}  # fmt: skip


@pytest.mark.parametrize("kind", list(VALUE_SHAPES))
def test_a_value_s_field_is_no_laxer_than_the_shapes_demand(kind: ValueKind) -> None:
    shapes = Graph().parse(ONTOLOGY / "ontologie" / "cur-shapes.ttl", format="turtle")
    counts = shape_counts(shapes, SHS[VALUE_SHAPES[kind][2]])
    fields = VALUE_FIELDS[kind]

    for field in fields:
        if field.path is not None:
            least, most = counts[field.path]  # a field's path is one the shape names
            assert field.required or least == 0, field.key
            assert not field.many or most is None, field.key
    demanded = {path for path, (least, _) in counts.items() if least > 0}
    assert demanded == {field.path for field in fields if field.required}  # each a field the form asks
    numbers = {field.key for field in fields if field.kind == "number"}
    assert numbers == {"workloads": {"amount", "amount_to", "minutes_per_unit"},
                       "time_spans": {"span_from", "span_to"}, "level_assignments": set()}[kind]  # fmt: skip


def test_a_holder_is_offered_only_what_the_shapes_let_it_hold() -> None:
    shapes = Graph().parse(ONTOLOGY / "ontologie" / "cur-shapes.ttl", format="turtle")

    for kind, (prop, value_class, _) in VALUE_SHAPES.items():
        for holder in VALUE_HOLDERS[kind]:
            shape = SHS[HOLDER_SHAPES[holder]]
            # a shape that closes its holder names what it may hold; one open lets it hold more
            assert shapes.value(shape, SH.closed) is None, holder
            named = [
                each
                for each in shapes.objects(shape, SH.property)
                if shapes.value(each, SH.path) == CUR[prop]
            ]
            assert all(shapes.value(each, SH["class"]) == CUR[value_class] for each in named), (kind, holder)
            # and the store has a column for it: a statement's time span has none (plan M3a D1)
            assert COLUMN_OF[holder] in HOLDERS_OF[TABLE_OF[kind]], (kind, holder)
    assert VALUE_HOLDERS == {
        "level_assignments": ("node", "statement", "specification"),
        "time_spans": ("node", "specification"),
        "workloads": ("node", "specification"),
    }
    keys = [field.key for fields in VALUE_FIELDS.values() for field in fields]
    assert len(keys) == len(set(keys))  # a field's key names it among every kind's


@pytest.mark.pg
@pytest.mark.anyio
async def test_levels_come_grouped_by_their_scheme_active_ones_alone(
    connection: psycopg.AsyncConnection,
) -> None:
    await connection.execute(
        "UPDATE vocab_concept SET retired_in = 1 WHERE iri = ANY(%s)", ([LVL + "EQF-8", CV + "unit_week"],)
    )
    await connection.execute(
        "UPDATE vocab_scheme SET retired_in = 1 WHERE iri = ANY(%s)",
        ([LVL + "SchoolLeaving", CV + "WorkloadKinds"],),
    )

    form = await value_form_of(connection)

    levels = form.values["level"]
    assert [level.iri for level in levels if form.group_of[level.iri] == LVL + "EQF"] == [
        LVL + f"EQF-{rank}" for rank in range(1, 8)
    ]  # in their rank, the retired one left out
    assert not [level for level in levels if level.iri.startswith(LVL + "school-")]  # its scheme retired
    groups = [form.group_of[level.iri] for level in levels]
    together = [group for group in dict.fromkeys(groups) for _ in range(groups.count(group))]
    assert groups == together and len(set(groups)) > 10  # each group's levels together
    assert [form.groups[group] for group in dict.fromkeys(groups)] == sorted(
        (form.groups[group] for group in set(groups)), key=str.casefold
    )  # the groups in the order of their labels
    assert form.groups[LVL + "EQF"] == "Europäischer Qualifikationsrahmen (EQR)"
    assert form.values["level_to"] == levels
    assert {form.group_of[value.iri] for value in form.values["competence_dimension"]} >= {KD + "Bridge"}
    assert CV + "unit_week" not in {unit.iri for unit in form.values["unit"]}
    assert CV + "unit_lesson" in {unit.iri for unit in form.values["unit"]}
    assert form.values["workload_kind"] == ()  # its scheme retired
    assert CV + "time_phase" not in {kind.iri for kind in form.values["time_kind"]}  # no phase yet
    assert all(value.iri not in form.group_of for value in form.values["unit"])  # a scheme's are no group's
    concepts = {field.key for fields in VALUE_FIELDS.values() for field in fields if field.kind == "concept"}
    assert set(form.values) == concepts
