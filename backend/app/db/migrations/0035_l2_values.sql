-- The second layer's values (plan M3a D1; cur-kern.ttl, cur-shapes.ttl): a workload (cur:Workload), a
-- time span (cur:TimeSpan) and a level assignment (cur:LevelAssignment), each of one holder of its
-- document, which it goes with. Every value says where it came from and how far it is reviewed, as a
-- node does (0014); ``position`` orders a holder's values of a kind, ``revision`` counts a row's changes.
-- Here: what a value must have, the order of its numbers, the vocabulary of each column and that its
-- holder is of its document. What the core's shapes say beside - a qualification level never at a
-- statement, a range's end of the scheme of its start - X5 checks. The holders of later packages
-- (applicability context, assessment, placement) come with their migrations: a column each, and the
-- one-holder CHECK made anew.

-- A holder's values are set as a whole on its revision (plan M3a E11): a node and a statement count theirs
-- (0014), a specification from here on
ALTER TABLE specification ADD COLUMN revision integer NOT NULL DEFAULT 1 CHECK (revision >= 1);

CREATE TABLE workload (
    id uuid PRIMARY KEY,
    kind text NOT NULL DEFAULT 'workload' CHECK (kind = 'workload'),
    document_id uuid NOT NULL REFERENCES document (id) ON DELETE CASCADE,
    node_id uuid,
    specification_id uuid,
    position integer NOT NULL CHECK (position >= 1),
    amount numeric NOT NULL CHECK (amount >= 0),
    amount_to numeric,  -- "40-50 UStd.": amount 40, amount_to 50
    unit_scheme text NOT NULL CHECK (unit_scheme = 'https://w3id.org/wlo/curriculum/vocab#WorkloadUnits'),
    unit_iri text NOT NULL,
    workload_kind_scheme text
        CHECK (workload_kind_scheme = 'https://w3id.org/wlo/curriculum/vocab#WorkloadKinds'),
    workload_kind_iri text,
    is_recommendation boolean NOT NULL DEFAULT false,  -- cur:isRecommendation
    minutes_per_unit integer CHECK (minutes_per_unit >= 1),  -- as the document says it: "1 UE = 45 min"
    total boolean NOT NULL DEFAULT false,  -- the holder's whole (cur:totalWorkload), not a part of it
    origin_scheme text NOT NULL CHECK (origin_scheme = 'https://w3id.org/wlo/curriculum/vocab#Origins'),
    origin_iri text NOT NULL,
    review_status_scheme text NOT NULL
        CHECK (review_status_scheme = 'https://w3id.org/wlo/curriculum/vocab#ReviewStatuses'),
    review_status_iri text NOT NULL,
    rule_id text CHECK (has_text(rule_id) AND length(rule_id) <= 200),
    revision integer NOT NULL DEFAULT 1 CHECK (revision >= 1),
    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now(),
    -- a time span names the workload it is the period of with the document, as a holder (below)
    UNIQUE (document_id, id),
    CONSTRAINT workload_position UNIQUE NULLS NOT DISTINCT (node_id, specification_id, position) DEFERRABLE,
    FOREIGN KEY (document_id, node_id) REFERENCES node (document_id, id) ON DELETE CASCADE,
    FOREIGN KEY (document_id, specification_id) REFERENCES specification (document_id, id) ON DELETE CASCADE,
    FOREIGN KEY (id, kind) REFERENCES entity (id, kind),
    FOREIGN KEY (unit_scheme, unit_iri) REFERENCES vocab_concept (scheme_iri, iri),
    FOREIGN KEY (workload_kind_scheme, workload_kind_iri) REFERENCES vocab_concept (scheme_iri, iri),
    FOREIGN KEY (origin_scheme, origin_iri) REFERENCES vocab_concept (scheme_iri, iri),
    FOREIGN KEY (review_status_scheme, review_status_iri) REFERENCES vocab_concept (scheme_iri, iri),
    CONSTRAINT workload_one_holder CHECK (num_nonnulls(node_id, specification_id) = 1),
    CONSTRAINT workload_amount_order CHECK (amount <= amount_to),
    CONSTRAINT workload_workload_kind_named CHECK ((workload_kind_scheme IS NULL) = (workload_kind_iri IS NULL)),
    CHECK ((origin_iri = 'https://w3id.org/wlo/curriculum/vocab#orig_rule') = (rule_id IS NOT NULL))
);
CREATE INDEX workload_of_specification ON workload (specification_id) WHERE specification_id IS NOT NULL;

-- When: a grade level, a training year, a semester - from and to, or one of them. No profile's phases
-- are a vocabulary the profiles share yet (plan M3a D1: one scheme of one profile, its concepts typed
-- skos:Concept alone), so no time span is a named phase (cv:time_phase), whose shape asks for cur:phase:
-- a column for the phase comes with such a vocabulary
CREATE TABLE time_span (
    id uuid PRIMARY KEY,
    kind text NOT NULL DEFAULT 'time_span' CHECK (kind = 'time_span'),
    document_id uuid NOT NULL REFERENCES document (id) ON DELETE CASCADE,
    node_id uuid,
    specification_id uuid,
    workload_id uuid,  -- the workload given in this period (cur:inPeriod)
    position integer NOT NULL CHECK (position >= 1),
    time_kind_scheme text NOT NULL CHECK (time_kind_scheme = 'https://w3id.org/wlo/curriculum/vocab#TimeKinds'),
    time_kind_iri text NOT NULL,
    span_from numeric CHECK (span_from >= 0),
    span_to numeric CHECK (span_to >= 0),
    time_relation_scheme text
        CHECK (time_relation_scheme = 'https://w3id.org/wlo/curriculum/vocab#TimeRelations'),
    time_relation_iri text,
    origin_scheme text NOT NULL CHECK (origin_scheme = 'https://w3id.org/wlo/curriculum/vocab#Origins'),
    origin_iri text NOT NULL,
    review_status_scheme text NOT NULL
        CHECK (review_status_scheme = 'https://w3id.org/wlo/curriculum/vocab#ReviewStatuses'),
    review_status_iri text NOT NULL,
    rule_id text CHECK (has_text(rule_id) AND length(rule_id) <= 200),
    revision integer NOT NULL DEFAULT 1 CHECK (revision >= 1),
    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now(),
    CONSTRAINT time_span_position
        UNIQUE NULLS NOT DISTINCT (node_id, specification_id, workload_id, position) DEFERRABLE,
    FOREIGN KEY (document_id, node_id) REFERENCES node (document_id, id) ON DELETE CASCADE,
    FOREIGN KEY (document_id, specification_id) REFERENCES specification (document_id, id) ON DELETE CASCADE,
    FOREIGN KEY (document_id, workload_id) REFERENCES workload (document_id, id) ON DELETE CASCADE,
    FOREIGN KEY (id, kind) REFERENCES entity (id, kind),
    FOREIGN KEY (time_kind_scheme, time_kind_iri) REFERENCES vocab_concept (scheme_iri, iri),
    FOREIGN KEY (time_relation_scheme, time_relation_iri) REFERENCES vocab_concept (scheme_iri, iri),
    FOREIGN KEY (origin_scheme, origin_iri) REFERENCES vocab_concept (scheme_iri, iri),
    FOREIGN KEY (review_status_scheme, review_status_iri) REFERENCES vocab_concept (scheme_iri, iri),
    CONSTRAINT time_span_one_holder CHECK (num_nonnulls(node_id, specification_id, workload_id) = 1),
    CONSTRAINT time_span_span_order CHECK (span_from <= span_to),
    CONSTRAINT time_span_no_phase CHECK (time_kind_iri <> 'https://w3id.org/wlo/curriculum/vocab#time_phase'),
    CONSTRAINT time_span_time_relation_named CHECK ((time_relation_scheme IS NULL) = (time_relation_iri IS NULL)),
    CHECK ((origin_iri = 'https://w3id.org/wlo/curriculum/vocab#orig_rule') = (rule_id IS NOT NULL))
);
CREATE INDEX time_span_of_specification ON time_span (specification_id) WHERE specification_id IS NOT NULL;
CREATE INDEX time_span_of_workload ON time_span (workload_id) WHERE workload_id IS NOT NULL;

-- Which level, of a level system's (cur:LevelConcept): at a node, a statement, a specification, or a rule
-- (the frame part of the rules X3 reads, plan M3a E10). A level's scheme is a profile's, so its column
-- names a concept, and the trigger below that it is a level
CREATE TABLE level_assignment (
    id uuid PRIMARY KEY,
    kind text NOT NULL DEFAULT 'level_assignment' CHECK (kind = 'level_assignment'),
    document_id uuid NOT NULL REFERENCES document (id) ON DELETE CASCADE,
    node_id uuid,
    statement_id uuid,
    specification_id uuid,
    frame_part_id uuid,
    position integer NOT NULL CHECK (position >= 1),
    level_iri text NOT NULL REFERENCES vocab_concept (iri),
    level_to_iri text REFERENCES vocab_concept (iri),  -- a range's end
    relation_scheme text CHECK (relation_scheme = 'https://w3id.org/wlo/curriculum/vocab#LevelRelations'),
    relation_iri text,
    dimension_scheme text CHECK (dimension_scheme = 'https://w3id.org/wlo/curriculum/vocab#LevelDimensions'),
    dimension_iri text,  -- where it is not the level system's own
    competence_dimension_iri text REFERENCES vocab_concept (iri),  -- a competency model's area it is of
    origin_scheme text NOT NULL CHECK (origin_scheme = 'https://w3id.org/wlo/curriculum/vocab#Origins'),
    origin_iri text NOT NULL,
    review_status_scheme text NOT NULL
        CHECK (review_status_scheme = 'https://w3id.org/wlo/curriculum/vocab#ReviewStatuses'),
    review_status_iri text NOT NULL,
    rule_id text CHECK (has_text(rule_id) AND length(rule_id) <= 200),
    revision integer NOT NULL DEFAULT 1 CHECK (revision >= 1),
    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now(),
    CONSTRAINT level_assignment_position
        UNIQUE NULLS NOT DISTINCT (node_id, statement_id, specification_id, frame_part_id, position) DEFERRABLE,
    FOREIGN KEY (document_id, node_id) REFERENCES node (document_id, id) ON DELETE CASCADE,
    FOREIGN KEY (document_id, statement_id) REFERENCES statement (document_id, id) ON DELETE CASCADE,
    FOREIGN KEY (document_id, specification_id) REFERENCES specification (document_id, id) ON DELETE CASCADE,
    FOREIGN KEY (document_id, frame_part_id) REFERENCES frame_part (document_id, id) ON DELETE CASCADE,
    FOREIGN KEY (id, kind) REFERENCES entity (id, kind),
    FOREIGN KEY (relation_scheme, relation_iri) REFERENCES vocab_concept (scheme_iri, iri),
    FOREIGN KEY (dimension_scheme, dimension_iri) REFERENCES vocab_concept (scheme_iri, iri),
    FOREIGN KEY (origin_scheme, origin_iri) REFERENCES vocab_concept (scheme_iri, iri),
    FOREIGN KEY (review_status_scheme, review_status_iri) REFERENCES vocab_concept (scheme_iri, iri),
    CONSTRAINT level_assignment_one_holder
        CHECK (num_nonnulls(node_id, statement_id, specification_id, frame_part_id) = 1),
    CONSTRAINT level_assignment_relation_named CHECK ((relation_scheme IS NULL) = (relation_iri IS NULL)),
    CONSTRAINT level_assignment_dimension_named CHECK ((dimension_scheme IS NULL) = (dimension_iri IS NULL)),
    CHECK ((origin_iri = 'https://w3id.org/wlo/curriculum/vocab#orig_rule') = (rule_id IS NOT NULL))
);
CREATE INDEX level_assignment_of_statement ON level_assignment (statement_id) WHERE statement_id IS NOT NULL;
CREATE INDEX level_assignment_of_specification
    ON level_assignment (specification_id) WHERE specification_id IS NOT NULL;
CREATE INDEX level_assignment_of_frame_part ON level_assignment (frame_part_id) WHERE frame_part_id IS NOT NULL;
-- the document's values by kind, as the copy and the export read them (a workload's by its key above)
CREATE INDEX time_span_of_document ON time_span (document_id);
CREATE INDEX level_assignment_of_document ON level_assignment (document_id);

-- A level and a range's end are levels (cur:LevelConcept), a competence dimension one of a competency
-- model (cur:CompetenceDimension), as document_type_fits checks a document's type (0013); one the
-- vocabularies do not hold the foreign key refuses. Each refusal names its column's check
CREATE FUNCTION level_assignment_fits() RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE
    checked record;
BEGIN
    FOR checked IN
        SELECT * FROM (VALUES
            ('level', NEW.level_iri, 'https://w3id.org/wlo/curriculum/core#LevelConcept'),
            ('level_to', NEW.level_to_iri, 'https://w3id.org/wlo/curriculum/core#LevelConcept'),
            ('competence_dimension', NEW.competence_dimension_iri,
                'https://w3id.org/wlo/curriculum/core#CompetenceDimension')
        ) AS c (column_name, iri, type)
    LOOP
        IF EXISTS (SELECT FROM vocab_concept WHERE iri = checked.iri AND NOT checked.type = ANY (types)) THEN
            RAISE EXCEPTION '% is no %', checked.iri, checked.type USING ERRCODE = 'check_violation',
                CONSTRAINT = 'level_assignment_' || checked.column_name || '_fits';
        END IF;
    END LOOP;
    RETURN NEW;
END
$$;
CREATE TRIGGER level_assignment_fits
    BEFORE INSERT OR UPDATE OF level_iri, level_to_iri, competence_dimension_iri ON level_assignment
    FOR EACH ROW EXECUTE FUNCTION level_assignment_fits();

-- A frozen document's values stay as they were written (0022)
CREATE TRIGGER workload_stays_frozen BEFORE INSERT OR UPDATE OR DELETE ON workload
    FOR EACH ROW EXECUTE FUNCTION keep_frozen_rows();
CREATE TRIGGER time_span_stays_frozen BEFORE INSERT OR UPDATE OR DELETE ON time_span
    FOR EACH ROW EXECUTE FUNCTION keep_frozen_rows();
CREATE TRIGGER level_assignment_stays_frozen BEFORE INSERT OR UPDATE OR DELETE ON level_assignment
    FOR EACH ROW EXECUTE FUNCTION keep_frozen_rows();
