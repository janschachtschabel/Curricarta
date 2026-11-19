-- IRIs for specifications and variants, and what an edition supersedes (plan M3a B1, B2).

-- Given when the document is frozen, by their keys under its IRI (app/domain/naming.py), and kept over draft
-- copies as a node's. A document frozen before this migration keeps them NULL here - the slug of a key is
-- Python's (app/domain/iris.py), not rebuilt in SQL - until python -m app.db.name_frozen names them once
ALTER TABLE specification
    ADD COLUMN iri text CHECK (iri ~ '^https?://' AND length(iri) <= 2000),
    ADD UNIQUE (document_id, iri);
ALTER TABLE variant
    ADD COLUMN iri text CHECK (iri ~ '^https?://' AND length(iri) <= 2000),
    ADD UNIQUE (specification_id, iri);

-- The edition of the same work this one supersedes (cur:supersedes), set by the editors before it is frozen;
-- and the counters of the names given under the document (rule-<n> …), kept over draft copies as
-- statement_serial is
ALTER TABLE document
    ADD COLUMN supersedes_id uuid REFERENCES document (id),
    ADD CHECK (supersedes_id IS DISTINCT FROM id),
    ADD COLUMN serials jsonb NOT NULL DEFAULT '{}' CHECK (jsonb_typeof(serials) = 'object');
CREATE INDEX document_supersedes ON document (supersedes_id) WHERE supersedes_id IS NOT NULL;

-- A frozen document's rows stay as they were written; a specification or a variant frozen before it had an
-- IRI may take one, and change nothing else with it - the one write python -m app.db.name_frozen makes
CREATE OR REPLACE FUNCTION keep_frozen_rows() RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE
    of_document uuid;
BEGIN
    IF TG_OP = 'UPDATE' AND TG_TABLE_NAME IN ('specification', 'variant')
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
