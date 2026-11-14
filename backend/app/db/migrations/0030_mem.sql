-- MEM-Schule (plan M2): the catalogue of the plans the MEM endpoint holds, read by a job (E11), and at an
-- imported document and its rows what the export writes back - the MEM IRIs, the classes as MEM gave
-- them, the properties the core has no place for (E7, E8). An IRI of MEM is a web IRI: the plans lie on
-- the Länder's hosts (lp-sachsen.org, lp-rlp.org, …), the standards' graph under w3id.org; it holds no
-- sign Turtle's IRIREF refuses (space, control signs, <>"{}|\^`), the export writing it as it stands.

CREATE TABLE mem_plan (
    iri text PRIMARY KEY CHECK (iri ~ '^https?://[^\s[:cntrl:]<>"{}|\\^`]+$' AND length(iri) <= 2000),
    graph text NOT NULL CHECK (graph ~ '^https?://[^\s[:cntrl:]<>"{}|\\^`]+$' AND length(graph) <= 2000),
    land_iri text,  -- the plan's Bundesland (LP_0000029); none for the KMK's standards
    title text NOT NULL CHECK (length(title) BETWEEN 1 AND 2000),
    class_iri text NOT NULL,  -- Lehrplan (LP_0000438), Bildungsstandard (LP_0000571) or a state's subclass
    subjects text[] NOT NULL DEFAULT '{}',  -- Schulfach (LP_0000537)
    school_types text[] NOT NULL DEFAULT '{}',  -- für Schulart (LP_0000812)
    licence text,  -- as the endpoint states it, where it does
    attribution text,
    read_at timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX mem_plan_land ON mem_plan (land_iri, title);

-- Of the plan a document was imported from: kept with the document, not read from the catalogue the job
-- rewrites - licence and attribution as they stood when it was imported
ALTER TABLE document
    ADD COLUMN mem_iri text CHECK (mem_iri ~ '^https?://[^\s[:cntrl:]<>"{}|\\^`]+$' AND length(mem_iri) <= 2000),
    ADD COLUMN mem_subjects text[] NOT NULL DEFAULT '{}',
    ADD COLUMN mem_school_types text[] NOT NULL DEFAULT '{}',
    ADD COLUMN mem_licence text,
    ADD COLUMN mem_attribution text;
-- A conversion takes a plan once; its draft copies carry the plan on (E1)
CREATE UNIQUE INDEX document_mem_import ON document (conversion_id, mem_iri)
    WHERE mem_iri IS NOT NULL AND copy_of IS NULL;

-- A row taken over from MEM: its IRI there, its classes (the state's and the base class), and what the
-- core has no column for - a reference's holder and target, a description, a number, grades, hours, the
-- plan's page, parents beyond the one it hangs at
ALTER TABLE node
    ADD COLUMN mem_iri text CHECK (mem_iri ~ '^https?://[^\s[:cntrl:]<>"{}|\\^`]+$' AND length(mem_iri) <= 2000),
    ADD COLUMN mem_classes text[] NOT NULL DEFAULT '{}',
    ADD COLUMN mem_properties jsonb NOT NULL DEFAULT '{}' CHECK (jsonb_typeof(mem_properties) = 'object');
CREATE UNIQUE INDEX node_mem_iri_once ON node (document_id, mem_iri) WHERE mem_iri IS NOT NULL;
ALTER TABLE statement
    ADD COLUMN mem_iri text CHECK (mem_iri ~ '^https?://[^\s[:cntrl:]<>"{}|\\^`]+$' AND length(mem_iri) <= 2000),
    ADD COLUMN mem_classes text[] NOT NULL DEFAULT '{}',
    ADD COLUMN mem_properties jsonb NOT NULL DEFAULT '{}' CHECK (jsonb_typeof(mem_properties) = 'object');
-- of rows taken over alone: the others, nearly all, hold none (an index of them only)
CREATE UNIQUE INDEX statement_mem_iri_once ON statement (document_id, mem_iri) WHERE mem_iri IS NOT NULL;
