-- A specification's applicability (plan M3a H1; cur-kern.ttl, cur:ApplicabilityContext): the contexts it
-- is declared for, each an AND of what it states - an education sector, a formality, the institution and
-- the target group as written - and of the time spans and levels it holds. An editor's, set with the
-- specification's values as a whole (app/db/values.py); where it came from and how far it is reviewed, as
-- a value says it (0035). What X1 read into specification.applicability stays there, and the Kern graph
-- states it for a specification without contexts: its vocabulary is Python's, and frozen documents keep
-- what they were frozen with. An OR of contexts (cur:alternativeContext) is not stored yet.
CREATE TABLE applicability_context (
    id uuid PRIMARY KEY,
    kind text NOT NULL DEFAULT 'applicability_context' CHECK (kind = 'applicability_context'),
    document_id uuid NOT NULL REFERENCES document (id) ON DELETE CASCADE,
    specification_id uuid NOT NULL,
    position integer NOT NULL CHECK (position >= 1),
    sector_scheme text CHECK (sector_scheme = 'https://w3id.org/wlo/curriculum/vocab#EducationSectors'),
    sector_iri text,
    formality_scheme text CHECK (formality_scheme = 'https://w3id.org/wlo/curriculum/vocab#Formalities'),
    formality_iri text,
    -- as written: the profiles' institution types and target groups are no vocabulary the profiles share
    institution_text text CHECK (has_text(institution_text) AND length(institution_text) <= 2000),
    target_group_text text CHECK (has_text(target_group_text) AND length(target_group_text) <= 2000),
    origin_scheme text NOT NULL CHECK (origin_scheme = 'https://w3id.org/wlo/curriculum/vocab#Origins'),
    origin_iri text NOT NULL,
    review_status_scheme text NOT NULL
        CHECK (review_status_scheme = 'https://w3id.org/wlo/curriculum/vocab#ReviewStatuses'),
    review_status_iri text NOT NULL,
    rule_id text CHECK (has_text(rule_id) AND length(rule_id) <= 200),
    revision integer NOT NULL DEFAULT 1 CHECK (revision >= 1),
    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now(),
    -- a time span and a level name the context they stand in with the document, as a holder
    UNIQUE (document_id, id),
    CONSTRAINT applicability_context_position UNIQUE (specification_id, position) DEFERRABLE,
    FOREIGN KEY (document_id, specification_id) REFERENCES specification (document_id, id) ON DELETE CASCADE,
    FOREIGN KEY (id, kind) REFERENCES entity (id, kind),
    FOREIGN KEY (sector_scheme, sector_iri) REFERENCES vocab_concept (scheme_iri, iri),
    FOREIGN KEY (formality_scheme, formality_iri) REFERENCES vocab_concept (scheme_iri, iri),
    FOREIGN KEY (origin_scheme, origin_iri) REFERENCES vocab_concept (scheme_iri, iri),
    FOREIGN KEY (review_status_scheme, review_status_iri) REFERENCES vocab_concept (scheme_iri, iri),
    CONSTRAINT applicability_context_sector_named CHECK ((sector_scheme IS NULL) = (sector_iri IS NULL)),
    CONSTRAINT applicability_context_formality_named
        CHECK ((formality_scheme IS NULL) = (formality_iri IS NULL)),
    CHECK ((origin_iri = 'https://w3id.org/wlo/curriculum/vocab#orig_rule') = (rule_id IS NOT NULL))
);

-- A context holds time spans and levels of its own (cur:timeSpan, cur:levelAssignment at the context): a
-- holder's column each, and the one-holder CHECK and the positions made anew with it (0035)
ALTER TABLE time_span
    ADD COLUMN applicability_context_id uuid,
    ADD FOREIGN KEY (document_id, applicability_context_id)
        REFERENCES applicability_context (document_id, id) ON DELETE CASCADE,
    DROP CONSTRAINT time_span_one_holder,
    ADD CONSTRAINT time_span_one_holder
        CHECK (num_nonnulls(node_id, specification_id, workload_id, applicability_context_id) = 1),
    DROP CONSTRAINT time_span_position,
    ADD CONSTRAINT time_span_position UNIQUE NULLS NOT DISTINCT
        (node_id, specification_id, workload_id, applicability_context_id, position) DEFERRABLE;
CREATE INDEX time_span_of_applicability_context
    ON time_span (applicability_context_id) WHERE applicability_context_id IS NOT NULL;

ALTER TABLE level_assignment
    ADD COLUMN applicability_context_id uuid,
    ADD FOREIGN KEY (document_id, applicability_context_id)
        REFERENCES applicability_context (document_id, id) ON DELETE CASCADE,
    DROP CONSTRAINT level_assignment_one_holder,
    ADD CONSTRAINT level_assignment_one_holder CHECK (
        num_nonnulls(node_id, statement_id, specification_id, frame_part_id, applicability_context_id) = 1
    ),
    DROP CONSTRAINT level_assignment_position,
    ADD CONSTRAINT level_assignment_position UNIQUE NULLS NOT DISTINCT
        (node_id, statement_id, specification_id, frame_part_id, applicability_context_id, position) DEFERRABLE;
CREATE INDEX level_assignment_of_applicability_context
    ON level_assignment (applicability_context_id) WHERE applicability_context_id IS NOT NULL;

-- A frozen document's contexts stay as they were written (0022)
CREATE TRIGGER applicability_context_stays_frozen BEFORE INSERT OR UPDATE OR DELETE ON applicability_context
    FOR EACH ROW EXECUTE FUNCTION keep_frozen_rows();
