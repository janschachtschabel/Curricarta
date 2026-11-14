-- The export of a MEM import (plan M2-6): the plan's Land and class kept at the document, as the export
-- states them - the catalogue rewrites mem_plan and may drop the plan -, web IRIs as every MEM IRI here.
ALTER TABLE document
    ADD COLUMN mem_land_iri text
        CHECK (mem_land_iri ~ '^https?://[^\s[:cntrl:]<>"{}|\\^`]+$' AND length(mem_land_iri) <= 2000),
    ADD COLUMN mem_class_iri text
        CHECK (mem_class_iri ~ '^https?://[^\s[:cntrl:]<>"{}|\\^`]+$' AND length(mem_class_iri) <= 2000);

-- A document imported before: its plan's as the catalogue holds it now, where it still does - frozen ones
-- too, so the trigger that keeps them is held off for this update alone
ALTER TABLE document DISABLE TRIGGER document_stays_frozen;
UPDATE document d SET
    mem_land_iri = CASE WHEN p.land_iri ~ '^https?://[^\s[:cntrl:]<>"{}|\\^`]+$'
        AND length(p.land_iri) <= 2000 THEN p.land_iri END,
    mem_class_iri = CASE WHEN p.class_iri ~ '^https?://[^\s[:cntrl:]<>"{}|\\^`]+$'
        AND length(p.class_iri) <= 2000 THEN p.class_iri END
FROM mem_plan p
WHERE p.iri = d.mem_iri;
ALTER TABLE document ENABLE TRIGGER document_stays_frozen;

-- Frozen, a document changes its rights status alone, and an import besides the licence of its MEM data,
-- checked after it was made (E14): who may reuse it may change with its source's terms
CREATE OR REPLACE FUNCTION keep_frozen_document() RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE
    open_keys text[] := CASE WHEN OLD.mem_iri IS NOT NULL
        THEN ARRAY['rights_status', 'updated_at', 'mem_licence']
        ELSE ARRAY['rights_status', 'updated_at'] END;
BEGIN
    IF OLD.frozen_at IS NOT NULL AND (
        TG_OP = 'DELETE'
        OR to_jsonb(OLD) - open_keys IS DISTINCT FROM to_jsonb(NEW) - open_keys
    ) THEN
        RAISE EXCEPTION 'document % is frozen: it changes its rights status and its MEM licence alone', OLD.id
            USING ERRCODE = 'object_not_in_prerequisite_state';
    END IF;
    IF TG_OP = 'DELETE' THEN
        RETURN OLD;
    END IF;
    RETURN NEW;
END
$$;
