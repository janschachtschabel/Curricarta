-- A block of a file without pages - a DOCX, an HTML page (plan M1 3b-3) - has no place on one: its box is
-- none, all four numbers, rather than one made up (app/conversion/base.py, Block.bbox).
ALTER TABLE document_block
    ALTER COLUMN x0 DROP NOT NULL,
    ALTER COLUMN top DROP NOT NULL,
    ALTER COLUMN x1 DROP NOT NULL,
    ALTER COLUMN bottom DROP NOT NULL,
    ADD CONSTRAINT document_block_place_whole CHECK (
        (x0 IS NULL) = (top IS NULL) AND (top IS NULL) = (x1 IS NULL) AND (x1 IS NULL) = (bottom IS NULL)
    );
