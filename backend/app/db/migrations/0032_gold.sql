-- The gold standard (plan H-3 §3.1): a sample of a document's statements, blocks or anchors, drawn once per
-- kind and seed, and the human judgements of its items. No wording is kept: an item points at its
-- statement, node or block, and names the hash of its wording and its first block, so that a judgement
-- outlives a replaced row. Only a judgement's note may quote, and it is never exported. No entity rows
-- (nothing here is a curriculum's), and no rows seeded.
CREATE TABLE gold_sample (
    id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    kind text NOT NULL CHECK (kind IN ('statement', 'block', 'anchor')),
    document_id uuid NOT NULL REFERENCES document (id) ON DELETE CASCADE,
    label text NOT NULL CHECK (label ~ '^[a-z0-9][a-z0-9-]{0,39}$'),  -- how the report names it; never its title
    seed text NOT NULL CHECK (seed ~ '^[A-Za-z0-9._-]{1,100}$'),
    size integer NOT NULL CHECK (size BETWEEN 1 AND 2000),  -- asked for
    frame jsonb NOT NULL CHECK (jsonb_typeof(frame) = 'object'),  -- each stratum's population: {"content": 371}
    drawn_by uuid NOT NULL REFERENCES account (id),
    drawn_at timestamptz NOT NULL DEFAULT now(),
    UNIQUE (document_id, kind, seed)
);
CREATE TABLE gold_item (
    id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    sample_id bigint NOT NULL REFERENCES gold_sample (id) ON DELETE CASCADE,
    stratum text NOT NULL CHECK (stratum ~ '^[A-Za-z0-9_.:-]{1,100}$'),
    place integer NOT NULL CHECK (place >= 1),  -- its rank in the sample by the seed
    statement_id uuid,  -- no foreign key: the judgement outlives a replaced row
    node_id uuid,
    block_id text CHECK (block_id ~ '^p[0-9]+-b[0-9]+$'),
    text_hash text CHECK (text_hash ~ '^[0-9a-f]{64}$'),  -- of the statement or the node's title when drawn
    first_block text CHECK (first_block ~ '^p[0-9]+-b[0-9]+$'),
    UNIQUE (sample_id, place),
    CONSTRAINT gold_item_one_thing CHECK (num_nonnulls(statement_id, node_id, block_id) = 1)
);
CREATE TABLE gold_judgement (
    item_id bigint NOT NULL REFERENCES gold_item (id) ON DELETE CASCADE,
    judged_by uuid NOT NULL REFERENCES account (id),
    verdict text CHECK (verdict IN ('correct', 'imprecise', 'wrong')),
    reasons text[] NOT NULL DEFAULT '{}' CHECK (reasons <@ ARRAY['not_a_statement', 'not_in_document',
        'node', 'boundary', 'kind', 'fields', 'wrong_place', 'missed']::text[]),
    expected integer CHECK (expected BETWEEN 0 AND 500),  -- a block's alone: the statements it holds
    note text CHECK (length(note) BETWEEN 1 AND 500),  -- may quote; never exported
    judged_at timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (item_id, judged_by),
    CONSTRAINT gold_judgement_verdict_or_count CHECK (num_nonnulls(verdict, expected) = 1),
    CONSTRAINT gold_judgement_correct_without_reason CHECK (verdict IS DISTINCT FROM 'correct' OR reasons = '{}'),
    CONSTRAINT gold_judgement_others_with_reason
        CHECK (verdict IS NULL OR verdict = 'correct' OR cardinality(reasons) >= 1),
    CONSTRAINT gold_judgement_count_without_reason CHECK (expected IS NULL OR reasons = '{}')
    -- a verdict on a block's item or a count on a statement's: refused by the sheet's importer, across tables
);
