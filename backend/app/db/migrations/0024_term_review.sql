-- The editors' decisions on the terms X1 found no type for (document_profile.new_terms, plan M1 10.4;
-- app/db/term_review.py, app/lexicon/new_terms.py): one for each term - a sector, its regions sorted, the word
-- as the lexicon compares words -, however many documents name it, made again over the last, each in the audit
-- log. A new cue ('cue') names the node type of the sector's profile it points to and its role; it goes into
-- the files, unverified, by python -m app.lexicon.export_reviews and the research's importer. A term peculiar
-- to its document ('document') or misread ('error') goes nowhere. A decision stays when no document names its
-- term any more; `content` is what was judged: the functions X1 suggested and how many documents named it.
CREATE TABLE term_review (
    sector_scheme text NOT NULL CHECK (sector_scheme = 'https://w3id.org/wlo/curriculum/vocab#EducationSectors'),
    sector_iri text NOT NULL,
    regions text[] NOT NULL
        CHECK (cardinality(regions) >= 1 AND all_match(regions, '^[A-Z]{2}(-[A-Z0-9]{1,3})?$')),
    term_key text CHECK (length(term_key) BETWEEN 1 AND 500),
    surface_form text NOT NULL CHECK (has_text(surface_form) AND length(surface_form) <= 500),
    decision text NOT NULL CHECK (decision IN ('cue', 'document', 'error')),
    profile_iri text REFERENCES terminology_profile (iri),
    maps_to text REFERENCES vocab_concept (iri),
    role_scheme text CHECK (role_scheme = 'https://w3id.org/wlo/curriculum/vocab#CueRoles'),
    role_iri text,
    note text CHECK (length(note) BETWEEN 1 AND 2000),
    content jsonb NOT NULL CHECK (jsonb_typeof(content) = 'object'),
    decided_by uuid NOT NULL REFERENCES account (id),
    decided_at timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (sector_iri, regions, term_key),
    FOREIGN KEY (sector_scheme, sector_iri) REFERENCES vocab_concept (scheme_iri, iri),
    FOREIGN KEY (role_scheme, role_iri) REFERENCES vocab_concept (scheme_iri, iri),
    CONSTRAINT term_review_role_in_scheme CHECK ((role_scheme IS NULL) = (role_iri IS NULL)),
    CONSTRAINT term_review_cue_complete
        CHECK (decision <> 'cue' OR (profile_iri IS NOT NULL AND maps_to IS NOT NULL AND role_iri IS NOT NULL)),
    CONSTRAINT term_review_only_cue_targets CHECK (decision = 'cue' OR (maps_to IS NULL AND role_iri IS NULL))
);
