-- Rules (plan M3a I, E10; cur-kern.ttl cur:Rule, cur-shapes.ttl RuleShape): a frame part of the kind rules is the
-- rule - its wording, its parsed values, its anchor, where it came from and how far it is reviewed are there
-- (0015). Here: its IRI, what it applies to, its options and what it requires.

-- Its IRI, <document>/rule-<n>, given when the document is frozen (app/domain/naming.py), counted on past the
-- names its revisions gave (document.serials, 0034) and kept over draft copies as a node's. A rule of a document
-- frozen before this migration keeps it NULL until python -m app.db.name_frozen names it once. ``by_hand``: an
-- editor made it - taken away it is deleted; a run's is rejected and stays, as a statement's (0014)
ALTER TABLE frame_part
    ADD COLUMN iri text CHECK (iri ~ '^https?://' AND length(iri) <= 2000),
    ADD UNIQUE (document_id, iri),
    ADD COLUMN by_hand boolean NOT NULL DEFAULT false;

-- a link names a variant with its specification, so it names one of its document's (below)
ALTER TABLE variant ADD UNIQUE (specification_id, id);

-- What a rule applies to (cur:ruleAppliesTo), its options (cur:option) and what it requires (cur:requiresItem):
-- a node, a statement, a specification or a variant of the rule's own document, each role's in its order and
-- each target once a role. Set by the editors; X3 reads options as text (content.optionTexts) alone
CREATE TABLE rule_link (
    frame_part_id uuid NOT NULL,
    document_id uuid NOT NULL,
    role text NOT NULL CHECK (role IN ('applies_to', 'option', 'requires')),
    position integer NOT NULL CHECK (position >= 1),
    node_id uuid,
    statement_id uuid,
    specification_id uuid,
    variant_id uuid,
    variant_specification_id uuid,  -- the variant's specification, which names it as one of the document's
    PRIMARY KEY (frame_part_id, role, position),
    FOREIGN KEY (document_id, frame_part_id) REFERENCES frame_part (document_id, id) ON DELETE CASCADE,
    FOREIGN KEY (document_id, node_id) REFERENCES node (document_id, id) ON DELETE CASCADE,
    FOREIGN KEY (document_id, statement_id) REFERENCES statement (document_id, id) ON DELETE CASCADE,
    FOREIGN KEY (document_id, specification_id) REFERENCES specification (document_id, id) ON DELETE CASCADE,
    FOREIGN KEY (document_id, variant_specification_id)
        REFERENCES specification (document_id, id) ON DELETE CASCADE,
    FOREIGN KEY (variant_specification_id, variant_id) REFERENCES variant (specification_id, id) ON DELETE CASCADE,
    CONSTRAINT rule_link_one_target CHECK (num_nonnulls(node_id, statement_id, specification_id, variant_id) = 1),
    CONSTRAINT rule_link_variant_named CHECK ((variant_id IS NULL) = (variant_specification_id IS NULL)),
    CONSTRAINT rule_link_target
        UNIQUE NULLS NOT DISTINCT (frame_part_id, role, node_id, statement_id, specification_id, variant_id)
);
CREATE INDEX rule_link_of_document ON rule_link (document_id);
CREATE INDEX rule_link_of_node ON rule_link (node_id) WHERE node_id IS NOT NULL;
CREATE INDEX rule_link_of_statement ON rule_link (statement_id) WHERE statement_id IS NOT NULL;
CREATE INDEX rule_link_of_specification ON rule_link (specification_id) WHERE specification_id IS NOT NULL;
CREATE INDEX rule_link_of_variant
    ON rule_link (variant_specification_id, variant_id) WHERE variant_id IS NOT NULL;

-- A frozen document's links stay as they were written (0022)
CREATE TRIGGER rule_link_stays_frozen BEFORE INSERT OR UPDATE OR DELETE ON rule_link
    FOR EACH ROW EXECUTE FUNCTION keep_frozen_rows();

-- A frozen document's rows stay as they were written; a specification, a variant or a frame part frozen before
-- it had an IRI may take one, and change nothing else with it - the one write python -m app.db.name_frozen
-- makes (0034, the frame part from here on)
CREATE OR REPLACE FUNCTION keep_frozen_rows() RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE
    of_document uuid;
BEGIN
    IF TG_OP = 'UPDATE' AND TG_TABLE_NAME IN ('specification', 'variant', 'frame_part')
        AND to_jsonb(OLD) ->> 'iri' IS NULL AND to_jsonb(NEW) ->> 'iri' IS NOT NULL
        AND to_jsonb(OLD) - 'iri' = to_jsonb(NEW) - 'iri'
    THEN
        RETURN NEW;
    END IF;
    IF TG_OP <> 'INSERT' THEN
        of_document := row_document(TG_TABLE_NAME, to_jsonb(OLD));
        IF document_frozen(of_document) THEN
            RAISE EXCEPTION 'document % is frozen: its % rows stay as they are', of_document, TG_TABLE_NAME
                USING ERRCODE = 'object_not_in_prerequisite_state';
        END IF;
    END IF;
    IF TG_OP <> 'DELETE' THEN
        of_document := row_document(TG_TABLE_NAME, to_jsonb(NEW));
        IF document_frozen(of_document) THEN
            RAISE EXCEPTION 'document % is frozen: its % rows stay as they are', of_document, TG_TABLE_NAME
                USING ERRCODE = 'object_not_in_prerequisite_state';
        END IF;
        RETURN NEW;
    END IF;
    RETURN OLD;
END
$$;
