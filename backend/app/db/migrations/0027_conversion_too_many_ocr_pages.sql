-- A conversion by an engine that reads scans ends with too_many_ocr_pages where more of the file's pages are
-- to be read by OCR than one conversion takes (plan M1 3b-2; MAX_OCR_PAGES in app/conversion/convert.py).
ALTER TABLE conversion
    DROP CONSTRAINT conversion_error_code_check,
    ADD CONSTRAINT conversion_error_code_check CHECK (error_code IN (
        'unreadable', 'too_many_pages', 'too_dense', 'needs_ocr', 'empty', 'timed_out', 'died', 'crashed',
        'not_pdf', 'file_gone', 'no_pages', 'too_many_ocr_pages'
    ));
