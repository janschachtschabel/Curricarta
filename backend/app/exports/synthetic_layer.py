"""The second layer of the measurement's synthetic document (app/exports/measure_kern.py, plan M3a L1):
values, rules, assessments and placements as the editors state them, accepted, each of a form X5 takes
without a violation - so that the measurement times a document the editors could freeze. Every wording is
made of the measurement's word list, every IRI lies under the document's."""

import uuid
from collections.abc import Callable
from dataclasses import replace
from decimal import Decimal

from app.db.rule_rows import Link, Rule, RuleAnchor
from app.domain.assessments import AssessmentRow, Target
from app.domain.l2 import (
    HeldValues,
    Holder,
    HolderKind,
    Level,
    LevelDraft,
    Stated,
    TimeSpan,
    TimeSpanDraft,
    Workload,
    WorkloadDraft,
)
from app.domain.placements import PlacementRow
from app.exports.kern_rows import KernRows, Row

CV = "https://w3id.org/wlo/curriculum/vocab#"
LVL = "https://w3id.org/wlo/curriculum/level/"
_STATED = Stated(CV + "orig_human", CV + "rev_accepted", None, 1)
_NO_PLACE = dict.fromkeys(("page_end", "printed_page", "match_score", "char_start", "char_end", "table_cell"))


def second_layer(
    rows: KernRows, values: int, next_id: Callable[[], uuid.UUID], words: Callable[[int, int], str]
) -> KernRows:
    """The rows with ``values`` level assignments - every other one at a statement (a language level), the
    rest at nodes (a qualification level) -, as many time spans of a grade level and workloads in lessons at
    the nodes, each in turn; and, a tenth of the nodes each, completion rules that apply to a node, graded
    exams of the specification that assess one, and placements of a node in the specification for a grade
    level. ``next_id`` names each row, ``words`` makes its wording."""
    base, nodes, statements = rows.document["iri"], rows.nodes, rows.statements
    [specification] = rows.specifications
    held: dict[Holder, HeldValues] = {}

    def add(kind: HolderKind, row: Row | uuid.UUID, value: Level | TimeSpan | Workload) -> None:
        holder = Holder(kind, row if isinstance(row, uuid.UUID) else row["id"])
        before = held.get(holder, HeldValues())
        name = {Level: "levels", TimeSpan: "time_spans", Workload: "workloads"}[type(value)]
        held[holder] = replace(before, **{name: (*getattr(before, name), value)})

    def level(name: str) -> Level:
        return Level(LevelDraft(level=LVL + name, id=next_id()), _STATED)

    def grade(at: int) -> TimeSpan:
        draft = TimeSpanDraft(time_kind=CV + "time_gradeLevel", span_from=Decimal(at % 13 + 1), id=next_id())
        return TimeSpan(draft, _STATED)

    for at in range(values):
        if at % 2:
            add("node", nodes[at // 2 % len(nodes)], level("EQF-4"))
        else:
            add("statement", statements[at // 2 % len(statements)], level("cefr-B1"))
        add("node", nodes[at % len(nodes)], grade(at))
        lessons = WorkloadDraft(amount=Decimal(at % 80 + 1), unit=CV + "unit_lesson", id=next_id())
        add("node", nodes[at % len(nodes)], Workload(lessons, _STATED))
    rules, anchors, assessments, placements = [], [], [], []
    for at in range(max(1, len(nodes) // 10)):
        node, block = nodes[at * 10 % len(nodes)], f"p1-b{at + 1}"
        rule = Rule(
            id=next_id(), iri=f"{base}/rule-{at + 1}", kind="completion", verbatim=words(at, 12),
            min_count=1, max_count=None, min_amount=None, max_amount=None, amount_unit=None,
            requirement_kind=None, max_share=None, option_texts=(), applies_to=(Link(node["id"], "node"),),
            options=(), requires=(), origin=_STATED.origin, review_status=_STATED.review_status, revision=1,
            by_hand=True, anchors=(RuleAnchor(1, None, (block,)),),
        )  # fmt: skip
        rules.append(rule)
        anchors.append({
            "id": next_id(), "node_id": None, "statement_id": None, "frame_part_id": rule.id, "page_start": 1,
            "quote": None, "match_kind_iri": None, "section_path": None, "blocks": [block],
            **_NO_PLACE,
        })  # fmt: skip
        exam = AssessmentRow(
            id=next_id(), parent_kind="specification", parent_id=specification["id"], position=at + 1,
            assessment_kind=CV + "ak_exam", label=words(at, 3), duration_minutes=90, weight_percent=None,
            graded=True, iri=f"{base}/assessment-{at + 1}", stated=_STATED,
            targets=(Target("node", node["id"], None),),
        )  # fmt: skip
        assessments.append(exam)
        add("assessment", exam.id, level("grade-2"))
        placement = PlacementRow(
            id=next_id(), node_id=node["id"], position=1, specification_id=specification["id"],
            variant_id=None, in_node_id=None, obligation=CV + "obl_binding", grade_weight=None,
            iri=f"{base}/placement-{at + 1}", stated=_STATED,
        )  # fmt: skip
        placements.append(placement)
        add("placement", placement.id, grade(at))
    return replace(
        rows, values=held, rules=rules, assessments=assessments, placements=placements,
        anchors=[*rows.anchors, *anchors],
    )  # fmt: skip
