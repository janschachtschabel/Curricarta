-- The editors' decisions on the research cues (plan M1 10.3; app/db/cue_review.py): one for each cue, made
-- again over the last, each in the audit log. A confirmed cue is raised to the strength the editors give, up
-- to 0.9, only with where they found it; a rejected one leaves the lexicon. The decisions go back into the
-- files by python -m app.lexicon.export_reviews and the research's importer - the cue's IRI is their key,
-- and the cue's row stays when a release retires it. `content` is what was judged, as the cue said it then.
CREATE TABLE cue_review (
    cue_iri text PRIMARY KEY REFERENCES lexical_cue (iri),
    decision text NOT NULL CHECK (decision IN ('confirmed', 'rejected')),
    strength numeric(3, 2) CHECK (strength BETWEEN 0.5 AND 0.9),
    evidence text CHECK (length(evidence) BETWEEN 1 AND 500),
    note text CHECK (length(note) BETWEEN 1 AND 2000),
    content jsonb NOT NULL CHECK (jsonb_typeof(content) = 'object'),
    decided_by uuid NOT NULL REFERENCES account (id),
    decided_at timestamptz NOT NULL DEFAULT now(),
    CONSTRAINT cue_review_confirmed_with_evidence
        CHECK (decision = 'rejected' OR (strength IS NOT NULL AND evidence IS NOT NULL)),
    CONSTRAINT cue_review_strength_only_confirmed CHECK (decision = 'confirmed' OR strength IS NULL)
);
