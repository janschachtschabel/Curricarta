-- A conversion by an engine that costs ends with no_pages where its asker has fewer pages left than the
-- file holds (plan M1 3b; app/conversion/job.py, FailureCode in app/db/conversions.py).
ALTER TABLE conversion
    DROP CONSTRAINT conversion_error_code_check,
    ADD CONSTRAINT conversion_error_code_check CHECK (error_code IN (
        'unreadable', 'too_many_pages', 'too_dense', 'needs_ocr', 'empty', 'timed_out', 'died', 'crashed',
        'not_pdf', 'file_gone', 'no_pages'
    ));
