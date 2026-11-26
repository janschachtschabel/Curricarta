"""The rows a draft copy writes (app/db/draft_copy.py): the tables whose rows are entities of their own, each
with the query of the copied document's ids, and the statements that copy every row under its new id -
``copied`` mapping each old id to its new one -, in the order that writes what a row names before the row.
"""

from typing import Final

# The tables whose rows are entities of their own, each with the query of the copied document's ids
ENTITIES: Final = {
    "specification": "SELECT id FROM specification WHERE document_id = %(old)s",
    "variant": "SELECT v.id FROM variant v JOIN specification s ON s.id = v.specification_id"
    " WHERE s.document_id = %(old)s",
    "frame_part": "SELECT id FROM frame_part WHERE document_id = %(old)s",
    "node": "SELECT id FROM node WHERE document_id = %(old)s",
    "statement": "SELECT id FROM statement WHERE document_id = %(old)s",
    "anchor": "SELECT id FROM anchor WHERE document_id = %(old)s",
    "workload": "SELECT id FROM workload WHERE document_id = %(old)s",
    "time_span": "SELECT id FROM time_span WHERE document_id = %(old)s",
    "level_assignment": "SELECT id FROM level_assignment WHERE document_id = %(old)s",
    "applicability_context": "SELECT id FROM applicability_context WHERE document_id = %(old)s",
    "assessment": "SELECT id FROM assessment WHERE document_id = %(old)s",
    "placement": "SELECT id FROM placement WHERE document_id = %(old)s",
}
# In this order: what a row names is copied before it. The profile is the frozen one's: the copy is not
# made by create_document, which would give it an empty one
ROWS: Final = (
    """
    INSERT INTO specification (id, document_id, key, spec_kind, title, field_text, applicability, iri,
        revision)
    SELECT m.new, %(new)s, s.key, s.spec_kind, s.title, s.field_text, s.applicability, s.iri, s.revision
    FROM specification s JOIN copied m ON m.old = s.id WHERE s.document_id = %(old)s
    """,
    """
    INSERT INTO variant (id, specification_id, key, label, variant_kind_scheme, variant_kind_iri, iri)
    SELECT m.new, sm.new, v.key, v.label, v.variant_kind_scheme, v.variant_kind_iri, v.iri
    FROM variant v JOIN copied m ON m.old = v.id JOIN copied sm ON sm.old = v.specification_id
    """,
    """
    INSERT INTO frame_part (id, document_id, part_kind, content, origin_scheme, origin_iri,
        review_status_scheme, review_status_iri, rule_id, revision, created_at, updated_at, position, iri,
        by_hand)
    SELECT m.new, %(new)s, f.part_kind, f.content, f.origin_scheme, f.origin_iri,
        f.review_status_scheme, f.review_status_iri, f.rule_id, f.revision, f.created_at, f.updated_at,
        f.position, f.iri, f.by_hand
    FROM frame_part f JOIN copied m ON m.old = f.id WHERE f.document_id = %(old)s
    """,
    """
    INSERT INTO node (id, document_id, parent_id, position, function_scheme, function_iri, node_type_iri,
        code, code_assigned, original_title, title_language, obligation_scheme, obligation_iri,
        scope_share_scheme, scope_share_iri, extraction_depth_scheme, extraction_depth_iri, applies_to,
        origin_scheme, origin_iri, review_status_scheme, review_status_iri, rule_id, revision, created_at,
        updated_at, iri, statement_serial, mem_iri, mem_classes, mem_properties)
    SELECT m.new, %(new)s, pm.new, n.position, n.function_scheme, n.function_iri, n.node_type_iri,
        n.code, n.code_assigned, n.original_title, n.title_language, n.obligation_scheme, n.obligation_iri,
        n.scope_share_scheme, n.scope_share_iri, n.extraction_depth_scheme, n.extraction_depth_iri,
        array(SELECT am.new FROM unnest(n.applies_to) WITH ORDINALITY a (id, place)
              JOIN copied am ON am.old = a.id ORDER BY a.place),
        n.origin_scheme, n.origin_iri, n.review_status_scheme, n.review_status_iri, n.rule_id, n.revision,
        n.created_at, n.updated_at, n.iri, n.statement_serial, n.mem_iri, n.mem_classes, n.mem_properties
    FROM node n JOIN copied m ON m.old = n.id LEFT JOIN copied pm ON pm.old = n.parent_id
    WHERE n.document_id = %(old)s
    """,
    """
    INSERT INTO statement (id, document_id, node_id, position, verbatim, language, lead_in,
        statement_kind_scheme, statement_kind_iri, subkind_iri, obligation_scheme, obligation_iri,
        origin_scheme, origin_iri, review_status_scheme, review_status_iri, rule_id, text_hash, details,
        layout_markers, revision, created_at, updated_at, iri, by_hand, mem_iri, mem_classes, mem_properties)
    SELECT m.new, %(new)s, nm.new, s.position, s.verbatim, s.language, s.lead_in,
        s.statement_kind_scheme, s.statement_kind_iri, s.subkind_iri, s.obligation_scheme, s.obligation_iri,
        s.origin_scheme, s.origin_iri, s.review_status_scheme, s.review_status_iri, s.rule_id, s.text_hash,
        s.details, s.layout_markers, s.revision, s.created_at, s.updated_at, s.iri, s.by_hand, s.mem_iri,
        s.mem_classes, s.mem_properties
    FROM statement s JOIN copied m ON m.old = s.id JOIN copied nm ON nm.old = s.node_id
    WHERE s.document_id = %(old)s
    """,
    """
    INSERT INTO statement_addressee (statement_id, addressee_scheme, addressee_iri)
    SELECT sm.new, a.addressee_scheme, a.addressee_iri
    FROM statement_addressee a JOIN copied sm ON sm.old = a.statement_id
    """,
    # an assessment's parts in the same statement: a part's foreign key is checked once all stand
    """
    INSERT INTO assessment (id, document_id, parent_assessment_id, specification_id, node_id, position,
        assessment_kind_scheme, assessment_kind_iri, label, duration_minutes, weight_percent, graded, iri,
        origin_scheme, origin_iri, review_status_scheme, review_status_iri, rule_id, revision, created_at,
        updated_at)
    SELECT m.new, %(new)s, am.new, sm.new, nm.new, a.position, a.assessment_kind_scheme,
        a.assessment_kind_iri, a.label, a.duration_minutes, a.weight_percent, a.graded, a.iri,
        a.origin_scheme, a.origin_iri, a.review_status_scheme, a.review_status_iri, a.rule_id, a.revision,
        a.created_at, a.updated_at
    FROM assessment a JOIN copied m ON m.old = a.id LEFT JOIN copied am ON am.old = a.parent_assessment_id
        LEFT JOIN copied sm ON sm.old = a.specification_id LEFT JOIN copied nm ON nm.old = a.node_id
    WHERE a.document_id = %(old)s
    """,
    """
    INSERT INTO assessment_target (document_id, assessment_id, node_id, statement_id, position)
    SELECT %(new)s, am.new, nm.new, sm.new, t.position
    FROM assessment_target t JOIN copied am ON am.old = t.assessment_id
        LEFT JOIN copied nm ON nm.old = t.node_id LEFT JOIN copied sm ON sm.old = t.statement_id
    WHERE t.document_id = %(old)s
    """,
    """
    INSERT INTO anchor (id, document_id, conversion_id, node_id, statement_id, frame_part_id,
        specification_id, page_start, page_end, printed_page, quote, match_kind_scheme, match_kind_iri,
        match_score, char_start, char_end, table_cell, section_path, created_at, assessment_id)
    SELECT m.new, %(new)s, a.conversion_id, nm.new, sm.new, fm.new, pm.new, a.page_start, a.page_end,
        a.printed_page, a.quote, a.match_kind_scheme, a.match_kind_iri, a.match_score, a.char_start,
        a.char_end, a.table_cell, a.section_path, a.created_at, asm.new
    FROM anchor a JOIN copied m ON m.old = a.id LEFT JOIN copied nm ON nm.old = a.node_id
        LEFT JOIN copied sm ON sm.old = a.statement_id LEFT JOIN copied fm ON fm.old = a.frame_part_id
        LEFT JOIN copied pm ON pm.old = a.specification_id LEFT JOIN copied asm ON asm.old = a.assessment_id
    WHERE a.document_id = %(old)s
    """,
    """
    INSERT INTO anchor_block (anchor_id, conversion_id, block_id)
    SELECT am.new, b.conversion_id, b.block_id FROM anchor_block b JOIN copied am ON am.old = b.anchor_id
    """,
    """
    INSERT INTO document_profile (document_id, term_mappings, new_terms, table_schemas)
    SELECT %(new)s, term_mappings, new_terms, table_schemas FROM document_profile WHERE document_id = %(old)s
    """,
    """
    INSERT INTO applicability_context (id, document_id, specification_id, position, sector_scheme, sector_iri,
        formality_scheme, formality_iri, institution_text, target_group_text, origin_scheme, origin_iri,
        review_status_scheme, review_status_iri, rule_id, revision, created_at, updated_at)
    SELECT m.new, %(new)s, sm.new, c.position, c.sector_scheme, c.sector_iri, c.formality_scheme,
        c.formality_iri, c.institution_text, c.target_group_text, c.origin_scheme, c.origin_iri,
        c.review_status_scheme, c.review_status_iri, c.rule_id, c.revision, c.created_at, c.updated_at
    FROM applicability_context c JOIN copied m ON m.old = c.id JOIN copied sm ON sm.old = c.specification_id
    WHERE c.document_id = %(old)s
    """,
    """
    INSERT INTO placement (id, document_id, node_id, specification_id, variant_id, variant_specification_id,
        in_node_id, position, obligation_scheme, obligation_iri, grade_weight, iri, origin_scheme, origin_iri,
        review_status_scheme, review_status_iri, rule_id, revision, created_at, updated_at)
    SELECT m.new, %(new)s, nm.new, sm.new, vm.new, vsm.new, im.new, p.position, p.obligation_scheme,
        p.obligation_iri, p.grade_weight, p.iri, p.origin_scheme, p.origin_iri, p.review_status_scheme,
        p.review_status_iri, p.rule_id, p.revision, p.created_at, p.updated_at
    FROM placement p JOIN copied m ON m.old = p.id JOIN copied nm ON nm.old = p.node_id
        LEFT JOIN copied sm ON sm.old = p.specification_id LEFT JOIN copied vm ON vm.old = p.variant_id
        LEFT JOIN copied vsm ON vsm.old = p.variant_specification_id
        LEFT JOIN copied im ON im.old = p.in_node_id
    WHERE p.document_id = %(old)s
    """,
    """
    INSERT INTO workload (id, document_id, node_id, specification_id, position, amount, amount_to,
        unit_scheme, unit_iri, workload_kind_scheme, workload_kind_iri, is_recommendation, minutes_per_unit,
        total, origin_scheme, origin_iri, review_status_scheme, review_status_iri, rule_id, revision,
        created_at, updated_at, placement_id)
    SELECT m.new, %(new)s, nm.new, sm.new, w.position, w.amount, w.amount_to, w.unit_scheme, w.unit_iri,
        w.workload_kind_scheme, w.workload_kind_iri, w.is_recommendation, w.minutes_per_unit, w.total,
        w.origin_scheme, w.origin_iri, w.review_status_scheme, w.review_status_iri, w.rule_id, w.revision,
        w.created_at, w.updated_at, pm.new
    FROM workload w JOIN copied m ON m.old = w.id LEFT JOIN copied nm ON nm.old = w.node_id
        LEFT JOIN copied sm ON sm.old = w.specification_id LEFT JOIN copied pm ON pm.old = w.placement_id
    WHERE w.document_id = %(old)s
    """,
    """
    INSERT INTO time_span (id, document_id, node_id, specification_id, workload_id,
        applicability_context_id, position, time_kind_scheme, time_kind_iri, span_from, span_to,
        time_relation_scheme, time_relation_iri, origin_scheme, origin_iri, review_status_scheme,
        review_status_iri, rule_id, revision, created_at, updated_at, placement_id)
    SELECT m.new, %(new)s, nm.new, sm.new, wm.new, cm.new, t.position, t.time_kind_scheme, t.time_kind_iri,
        t.span_from, t.span_to, t.time_relation_scheme, t.time_relation_iri, t.origin_scheme, t.origin_iri,
        t.review_status_scheme, t.review_status_iri, t.rule_id, t.revision, t.created_at, t.updated_at, pm.new
    FROM time_span t JOIN copied m ON m.old = t.id LEFT JOIN copied nm ON nm.old = t.node_id
        LEFT JOIN copied sm ON sm.old = t.specification_id LEFT JOIN copied wm ON wm.old = t.workload_id
        LEFT JOIN copied cm ON cm.old = t.applicability_context_id
        LEFT JOIN copied pm ON pm.old = t.placement_id
    WHERE t.document_id = %(old)s
    """,
    """
    INSERT INTO level_assignment (id, document_id, node_id, statement_id, specification_id, frame_part_id,
        applicability_context_id, position, level_iri, level_to_iri, relation_scheme, relation_iri,
        dimension_scheme, dimension_iri, competence_dimension_iri, origin_scheme, origin_iri,
        review_status_scheme, review_status_iri, rule_id, revision, created_at, updated_at, assessment_id)
    SELECT m.new, %(new)s, nm.new, sm.new, pm.new, fm.new, cm.new, l.position, l.level_iri, l.level_to_iri,
        l.relation_scheme, l.relation_iri, l.dimension_scheme, l.dimension_iri, l.competence_dimension_iri,
        l.origin_scheme, l.origin_iri, l.review_status_scheme, l.review_status_iri, l.rule_id, l.revision,
        l.created_at, l.updated_at, asm.new
    FROM level_assignment l JOIN copied m ON m.old = l.id LEFT JOIN copied nm ON nm.old = l.node_id
        LEFT JOIN copied sm ON sm.old = l.statement_id LEFT JOIN copied pm ON pm.old = l.specification_id
        LEFT JOIN copied fm ON fm.old = l.frame_part_id
        LEFT JOIN copied cm ON cm.old = l.applicability_context_id
        LEFT JOIN copied asm ON asm.old = l.assessment_id
    WHERE l.document_id = %(old)s
    """,
    """
    INSERT INTO rule_link (frame_part_id, document_id, role, position, node_id, statement_id,
        specification_id, variant_id, variant_specification_id)
    SELECT fm.new, %(new)s, l.role, l.position, nm.new, sm.new, pm.new, vm.new, vsm.new
    FROM rule_link l JOIN copied fm ON fm.old = l.frame_part_id LEFT JOIN copied nm ON nm.old = l.node_id
        LEFT JOIN copied sm ON sm.old = l.statement_id LEFT JOIN copied pm ON pm.old = l.specification_id
        LEFT JOIN copied vm ON vm.old = l.variant_id
        LEFT JOIN copied vsm ON vsm.old = l.variant_specification_id
    WHERE l.document_id = %(old)s
    """,
)
