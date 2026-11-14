-- The engine docling beside pdfplumber (plan M1 3b; app/conversion/base.py, EngineName): a file converted by
-- either, and its pages counted for either.
ALTER TABLE conversion
    DROP CONSTRAINT conversion_engine_check,
    ADD CONSTRAINT conversion_engine_check CHECK (engine IN ('pdfplumber', 'docling'));
ALTER TABLE conversion_usage
    DROP CONSTRAINT conversion_usage_engine_check,
    ADD CONSTRAINT conversion_usage_engine_check CHECK (engine IN ('pdfplumber', 'docling'));
