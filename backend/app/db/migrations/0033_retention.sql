-- Retention (python -m app.retention): an ended job may go once its time has passed, and what named it
-- stays without it - a conversion, a run; a job holding a reservation stays (usage_reservation keeps its
-- key: the reservation is booked as spent first). The pages a conversion booked outlive it, as llm_usage
-- outlives its job: a budget is the lifetime sum of the bookings, and taking one away would fill it up.
-- Only constraints go, indexes and one table come: the image before runs on against this schema.
ALTER TABLE conversion
    DROP CONSTRAINT conversion_job_id_fkey,
    ADD CONSTRAINT conversion_job_id_fkey FOREIGN KEY (job_id) REFERENCES job (id) ON DELETE SET NULL;
ALTER TABLE extraction_run
    DROP CONSTRAINT extraction_run_job_id_fkey,
    ADD CONSTRAINT extraction_run_job_id_fkey FOREIGN KEY (job_id) REFERENCES job (id) ON DELETE SET NULL;
ALTER TABLE conversion_usage DROP CONSTRAINT conversion_usage_conversion_id_fkey;

-- what the sweep looks for past its time, and the ledger's sum of an account's costs read from the index
-- alone, under the quota row's lock, however long the table grows
CREATE INDEX job_ended ON job (finished_at) WHERE status IN ('done', 'failed', 'cancelled');
CREATE INDEX audit_log_at ON audit_log (at);
CREATE INDEX llm_usage_charged ON llm_usage (account_id) INCLUDE (charged_tokens);

-- The places in the object store whose objects are to go: a run's raw answers (runs/<run>/<stage>/), a
-- document's exports (exports/<document>/), a file no entry holds (sources/<sha256>). Noted in the
-- transaction that lets go of what named them, emptied by the sweep after it - a sweep broken between
-- the two leaves the note for the next. A prefix ends in "/", an object's key does not. Each segment is
-- one a key may have (app/core/storage.py check_key): 1 to 255 signs, neither beginning nor ending with a
-- dot - none is empty, ".", ".." - so nothing leaves the root. A device name (con, nul.json) passes here:
-- the store refuses it, and the sweep passes such a note by. The length apart: PostgreSQL's regular
-- expressions repeat at most 255 times
CREATE TABLE storage_garbage (
    prefix text PRIMARY KEY CHECK (
        prefix ~ '^(runs|exports|sources)(/[A-Za-z0-9_-]([A-Za-z0-9._-]{0,253}[A-Za-z0-9_-])?)+/?$'
        AND length(prefix) - position('/' IN prefix) <= 480
    ),
    noted_at timestamptz NOT NULL DEFAULT now()
);
