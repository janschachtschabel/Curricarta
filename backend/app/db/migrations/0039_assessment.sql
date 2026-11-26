-- A document's assessments (plan M3a J; cur-kern.ttl, cur:Assessment, cur-shapes.ttl AssessmentShape): an
-- examination, an exam part or area, a module exam, coursework - each part of one other assessment, of a
-- specification or of a node of its document (cur:partOf), of a kind of the core's (cur:assessmentKind),
-- with its name, its duration in minutes, its weight among its siblings in percent and whether it is graded,
-- as the document says them. What it assesses (cur:assesses) are nodes and statements of its document; the
-- levels it is graded in are levels at it (level_assignment.assessment_id), and where it is found in the
-- source an anchor (anchor.assessment_id). Where it came from and how far it is reviewed, as a node says
-- it (0014); ``revision`` counts its changes. Its IRI it gets when the document is frozen, by the counter of
-- its document (document.serials, <document>/assessment-<n>) - kept over draft copies, as a node's.
-- Here: what an assessment must have, the vocabulary of its kind, a weight between 0 and 100, a parent of
-- its document and no part under itself. What the core's shapes say beside - the weights of the parts of
-- one assessment over 100 % - X5 checks.
CREATE TABLE assessment (
    id uuid PRIMARY KEY,
    kind text NOT NULL DEFAULT 'assessment' CHECK (kind = 'assessment'),
    document_id uuid NOT NULL REFERENCES document (id) ON DELETE CASCADE,
    parent_assessment_id uuid,
    specification_id uuid,
    node_id uuid,
    position integer NOT NULL CHECK (position >= 1),  -- among the parts of its parent, from 1
    assessment_kind_scheme text NOT NULL
        CHECK (assessment_kind_scheme = 'https://w3id.org/wlo/curriculum/vocab#AssessmentKinds'),
    assessment_kind_iri text NOT NULL,
    label text CHECK (has_text(label) AND length(label) <= 1000),
    duration_minutes integer CHECK (duration_minutes >= 0),
    -- numeric takes NaN and Infinity: both lie above 100, so the range refuses them
    weight_percent numeric CHECK (weight_percent >= 0 AND weight_percent <= 100),
    graded boolean,  -- none where the document does not say
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
    -- a part, a target, a level and an anchor name the assessment they are of with the document
    UNIQUE (document_id, id),
    UNIQUE (document_id, iri),
    -- deferrable, so a part may move within one transaction
    CONSTRAINT assessment_position
        UNIQUE NULLS NOT DISTINCT (parent_assessment_id, specification_id, node_id, position) DEFERRABLE,
    FOREIGN KEY (document_id, parent_assessment_id) REFERENCES assessment (document_id, id) ON DELETE CASCADE,
    FOREIGN KEY (document_id, specification_id) REFERENCES specification (document_id, id) ON DELETE CASCADE,
    FOREIGN KEY (document_id, node_id) REFERENCES node (document_id, id) ON DELETE CASCADE,
    FOREIGN KEY (id, kind) REFERENCES entity (id, kind),
    FOREIGN KEY (assessment_kind_scheme, assessment_kind_iri) REFERENCES vocab_concept (scheme_iri, iri),
    FOREIGN KEY (origin_scheme, origin_iri) REFERENCES vocab_concept (scheme_iri, iri),
    FOREIGN KEY (review_status_scheme, review_status_iri) REFERENCES vocab_concept (scheme_iri, iri),
    CONSTRAINT assessment_one_parent CHECK (num_nonnulls(parent_assessment_id, specification_id, node_id) = 1),
    CONSTRAINT assessment_not_its_own_part CHECK (parent_assessment_id <> id),
    CHECK ((origin_iri = 'https://w3id.org/wlo/curriculum/vocab#orig_rule') = (rule_id IS NOT NULL))
);
CREATE INDEX assessment_of_document ON assessment (document_id);
CREATE INDEX assessment_of_parent ON assessment (parent_assessment_id) WHERE parent_assessment_id IS NOT NULL;
CREATE INDEX assessment_of_specification ON assessment (specification_id) WHERE specification_id IS NOT NULL;
CREATE INDEX assessment_of_node ON assessment (node_id) WHERE node_id IS NOT NULL;

-- An assessment comes to be a part of itself nowhere, however it is written: checked once its statement has
-- written all its rows, under the tree's lock, as a node's place is (0014, node_without_cycle)
CREATE FUNCTION assessment_without_cycle() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
    IF NEW.parent_assessment_id IS NULL THEN
        RETURN NULL;
    END IF;
    IF TG_OP = 'UPDATE' THEN
        PERFORM read_committed_alone('an assessment is moved');
    END IF;
    PERFORM lock_node_tree(NEW.document_id);
    IF EXISTS (
        WITH RECURSIVE up (id) AS (
            SELECT NEW.parent_assessment_id
            UNION
            SELECT a.parent_assessment_id FROM assessment a JOIN up ON a.id = up.id
            WHERE a.parent_assessment_id IS NOT NULL
        )
        SELECT FROM up WHERE id = NEW.id
    ) THEN
        RAISE EXCEPTION 'assessment % would be a part of itself', NEW.id
            USING ERRCODE = 'check_violation', CONSTRAINT = 'assessment_without_cycle';
    END IF;
    RETURN NULL;
END
$$;
CREATE CONSTRAINT TRIGGER assessment_without_cycle AFTER INSERT OR UPDATE OF parent_assessment_id ON assessment
    FOR EACH ROW EXECUTE FUNCTION assessment_without_cycle();

-- What an assessment assesses (cur:assesses): a node or a statement of its document, each once, in the
-- order the editors named them. They go with what they name
CREATE TABLE assessment_target (
    document_id uuid NOT NULL,
    assessment_id uuid NOT NULL,
    node_id uuid,
    statement_id uuid,
    position integer NOT NULL CHECK (position >= 1),
    CONSTRAINT assessment_target_position UNIQUE (assessment_id, position) DEFERRABLE,
    CONSTRAINT assessment_target_once UNIQUE NULLS NOT DISTINCT (assessment_id, node_id, statement_id),
    FOREIGN KEY (document_id, assessment_id) REFERENCES assessment (document_id, id) ON DELETE CASCADE,
    FOREIGN KEY (document_id, node_id) REFERENCES node (document_id, id) ON DELETE CASCADE,
    FOREIGN KEY (document_id, statement_id) REFERENCES statement (document_id, id) ON DELETE CASCADE,
    CONSTRAINT assessment_target_one CHECK (num_nonnulls(node_id, statement_id) = 1)
);
CREATE INDEX assessment_target_of_document ON assessment_target (document_id);
CREATE INDEX assessment_target_of_node ON assessment_target (node_id) WHERE node_id IS NOT NULL;
CREATE INDEX assessment_target_of_statement ON assessment_target (statement_id) WHERE statement_id IS NOT NULL;

-- An assessment holds levels (cur:levelAssignment at the assessment: a grading scale, plan M3a J): a holder's
-- column, and the one-holder CHECK and the positions made anew with it (0035, 0037)
ALTER TABLE level_assignment
    ADD COLUMN assessment_id uuid,
    ADD FOREIGN KEY (document_id, assessment_id) REFERENCES assessment (document_id, id) ON DELETE CASCADE,
    DROP CONSTRAINT level_assignment_one_holder,
    ADD CONSTRAINT level_assignment_one_holder CHECK (num_nonnulls(
        node_id, statement_id, specification_id, frame_part_id, applicability_context_id, assessment_id
    ) = 1),
    DROP CONSTRAINT level_assignment_position,
    ADD CONSTRAINT level_assignment_position UNIQUE NULLS NOT DISTINCT (
        node_id, statement_id, specification_id, frame_part_id, applicability_context_id, assessment_id,
        position
    ) DEFERRABLE;
CREATE INDEX level_assignment_of_assessment ON level_assignment (assessment_id) WHERE assessment_id IS NOT NULL;

-- Where an assessment is found in its source: an anchor of it, as of a node (0015), one owner at most
ALTER TABLE anchor
    ADD COLUMN assessment_id uuid,
    ADD FOREIGN KEY (document_id, assessment_id) REFERENCES assessment (document_id, id) ON DELETE CASCADE,
    DROP CONSTRAINT anchor_check,
    ADD CONSTRAINT anchor_one_owner
        CHECK (num_nonnulls(node_id, statement_id, frame_part_id, specification_id, assessment_id) <= 1);
CREATE INDEX anchor_of_assessment ON anchor (assessment_id) WHERE assessment_id IS NOT NULL;

-- A frozen document's assessments and what they assess stay as they were written (0022)
CREATE TRIGGER assessment_stays_frozen BEFORE INSERT OR UPDATE OR DELETE ON assessment
    FOR EACH ROW EXECUTE FUNCTION keep_frozen_rows();
CREATE TRIGGER assessment_target_stays_frozen BEFORE INSERT OR UPDATE OR DELETE ON assessment_target
    FOR EACH ROW EXECUTE FUNCTION keep_frozen_rows();
