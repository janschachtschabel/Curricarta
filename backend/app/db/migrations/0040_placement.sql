-- A node's placements (plan M3a K; cur-kern.ttl, cur:Placement, cur-shapes.ttl PlacementShape): the node - a
-- module, a learning field, a course unit - placed (cur:placedUnit) in a specification (cur:inSpecification) or a
-- variant (cur:forVariant) of its document, at a node of it (cur:inNode) where the document says one, with how
-- binding it is there (cur:obligation, of the core's list) and its weight in the grade (cur:gradeWeight); its time
-- spans and workloads in that place are values at it (time_span.placement_id, workload.placement_id). Where it came
-- from and how far it is reviewed, as a node says it (0014); ``revision`` counts its changes. Its IRI it gets when
-- the document is frozen, by the counter of its document (document.serials, <document>/placement-<n>) - kept over
-- draft copies, as an assessment's (0039). Within one document alone (plan M3a K): a placement across documents
-- needs specifications across documents. Here: what a placement must have, the vocabulary of its obligation, rows
-- of its document - a variant with its specification, which names it as one of the document's (0038), and of the
-- specification the placement names where it names both -, a weight that is a number from 0, and a place that is
-- not the node itself.
CREATE TABLE placement (
    id uuid PRIMARY KEY,
    kind text NOT NULL DEFAULT 'placement' CHECK (kind = 'placement'),
    document_id uuid NOT NULL REFERENCES document (id) ON DELETE CASCADE,
    node_id uuid NOT NULL,  -- the node placed
    specification_id uuid,
    variant_id uuid,
    variant_specification_id uuid,  -- the variant's specification, which names it as one of the document's
    in_node_id uuid,  -- where in the specification or variant, where the document says it
    position integer NOT NULL CHECK (position >= 1),  -- among the placements of its node, from 1
    obligation_scheme text NOT NULL CHECK (obligation_scheme = 'https://w3id.org/wlo/curriculum/vocab#Obligations'),
    obligation_iri text NOT NULL,
    -- numeric takes NaN and Infinity: both lie at or above Infinity, so the range refuses them
    grade_weight numeric CHECK (grade_weight >= 0 AND grade_weight < 'Infinity'),
    iri text CHECK (iri ~ '^https?://' AND length(iri) <= 2000),
    origin_scheme text NOT NULL CHECK (origin_scheme = 'https://w3id.org/wlo/curriculum/vocab#Origins'),
    origin_iri text NOT NULL,
    review_status_scheme text NOT NULL
        CHECK (review_status_scheme = 'https://w3id.org/wlo/curriculum/vocab#ReviewStatuses'),
    review_status_iri text NOT NULL,
    rule_id text CHECK (has_text(rule_id) AND length(rule_id) <= 200),
    revision integer NOT NULL DEFAULT 1 CHECK (revision >= 1),
    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now(),
    -- a time span and a workload name the placement they are of with the document
    UNIQUE (document_id, id),
    UNIQUE (document_id, iri),
    -- deferrable, so the placements of a node may change places within one transaction
    CONSTRAINT placement_position UNIQUE (node_id, position) DEFERRABLE,
    FOREIGN KEY (document_id, node_id) REFERENCES node (document_id, id) ON DELETE CASCADE,
    FOREIGN KEY (document_id, specification_id) REFERENCES specification (document_id, id) ON DELETE CASCADE,
    FOREIGN KEY (document_id, variant_specification_id)
        REFERENCES specification (document_id, id) ON DELETE CASCADE,
    FOREIGN KEY (variant_specification_id, variant_id) REFERENCES variant (specification_id, id) ON DELETE CASCADE,
    FOREIGN KEY (document_id, in_node_id) REFERENCES node (document_id, id) ON DELETE CASCADE,
    FOREIGN KEY (id, kind) REFERENCES entity (id, kind),
    FOREIGN KEY (obligation_scheme, obligation_iri) REFERENCES vocab_concept (scheme_iri, iri),
    FOREIGN KEY (origin_scheme, origin_iri) REFERENCES vocab_concept (scheme_iri, iri),
    FOREIGN KEY (review_status_scheme, review_status_iri) REFERENCES vocab_concept (scheme_iri, iri),
    CONSTRAINT placement_in_context CHECK (num_nonnulls(specification_id, variant_id) >= 1),
    CONSTRAINT placement_variant_named CHECK ((variant_id IS NULL) = (variant_specification_id IS NULL)),
    CONSTRAINT placement_variant_of_its_specification
        CHECK (specification_id IS NULL OR variant_id IS NULL OR specification_id = variant_specification_id),
    CONSTRAINT placement_not_in_itself CHECK (in_node_id <> node_id),
    CHECK ((origin_iri = 'https://w3id.org/wlo/curriculum/vocab#orig_rule') = (rule_id IS NOT NULL))
);
CREATE INDEX placement_of_document ON placement (document_id);
CREATE INDEX placement_of_specification ON placement (specification_id) WHERE specification_id IS NOT NULL;
CREATE INDEX placement_of_variant ON placement (variant_specification_id, variant_id) WHERE variant_id IS NOT NULL;
CREATE INDEX placement_of_place ON placement (in_node_id) WHERE in_node_id IS NOT NULL;

-- A placement holds time spans (the semester it is in, cur:timeSpan) and workloads (its credits there, cur:workload):
-- a holder's column each, and the one-holder CHECKs and the positions made anew with it (0035, 0037)
ALTER TABLE time_span
    ADD COLUMN placement_id uuid,
    ADD FOREIGN KEY (document_id, placement_id) REFERENCES placement (document_id, id) ON DELETE CASCADE,
    DROP CONSTRAINT time_span_one_holder,
    ADD CONSTRAINT time_span_one_holder
        CHECK (num_nonnulls(node_id, specification_id, workload_id, applicability_context_id, placement_id) = 1),
    DROP CONSTRAINT time_span_position,
    ADD CONSTRAINT time_span_position UNIQUE NULLS NOT DISTINCT
        (node_id, specification_id, workload_id, applicability_context_id, placement_id, position) DEFERRABLE;
CREATE INDEX time_span_of_placement ON time_span (placement_id) WHERE placement_id IS NOT NULL;
ALTER TABLE workload
    ADD COLUMN placement_id uuid,
    ADD FOREIGN KEY (document_id, placement_id) REFERENCES placement (document_id, id) ON DELETE CASCADE,
    DROP CONSTRAINT workload_one_holder,
    ADD CONSTRAINT workload_one_holder CHECK (num_nonnulls(node_id, specification_id, placement_id) = 1),
    DROP CONSTRAINT workload_position,
    ADD CONSTRAINT workload_position
        UNIQUE NULLS NOT DISTINCT (node_id, specification_id, placement_id, position) DEFERRABLE;
CREATE INDEX workload_of_placement ON workload (placement_id) WHERE placement_id IS NOT NULL;

-- A frozen document's placements stay as they were written (0022)
CREATE TRIGGER placement_stays_frozen BEFORE INSERT OR UPDATE OR DELETE ON placement
    FOR EACH ROW EXECUTE FUNCTION keep_frozen_rows();
