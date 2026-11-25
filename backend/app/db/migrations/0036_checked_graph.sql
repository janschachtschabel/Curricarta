-- The version of the Kern graph a run of X5 checked (app/exports/kern_rdf.py, KERN_GRAPH_VERSION): a draft
-- whose last check ran under an older one is owed a check (app/db/runs.py, x5_owed), and the export of a
-- frozen document says when it was checked under another than the builder's now. NULL: a run before this
-- migration, or one an image that knows no version made - its graph is unknown, a draft so checked is owed
-- a check. Additive: the image before runs on against this schema.
ALTER TABLE extraction_run ADD COLUMN graph_version integer CHECK (graph_version >= 1);
