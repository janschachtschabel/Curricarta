-- The budget counts tokens weighed by their price beside an uncached input token (plan M1 11b-4,
-- app/llm/metering.py Weights): a cached input token and an output token at the weights the
-- request was held at, kept with each row, so a weight changed later changes no cost booked. What
-- was booked before is charged as it was, every token alike - and so is what a worker of the
-- release before writes while the rollout replaces it, the migration running first (a Helm hook):
-- the weights default to 1, the app names them always. ``charged_tokens`` is what the ledger sums:
-- of a cost, its uncached input and the weighed rest, a part of a token a token; of a reservation,
-- its input whole - nobody knows what the cache will hold - and its output weighed.
ALTER TABLE llm_usage
    ADD COLUMN cached_input_weight numeric NOT NULL DEFAULT 1 CHECK (cached_input_weight BETWEEN 0 AND 1),
    ADD COLUMN output_weight numeric NOT NULL DEFAULT 1 CHECK (output_weight > 0 AND output_weight <= 100);
ALTER TABLE llm_usage
    ADD COLUMN charged_tokens bigint GENERATED ALWAYS AS (
        input_tokens - cached_input_tokens
        + ceil(cached_input_tokens * cached_input_weight + output_tokens * output_weight)::bigint
    ) STORED;

ALTER TABLE usage_reservation
    ADD COLUMN cached_input_weight numeric NOT NULL DEFAULT 1 CHECK (cached_input_weight BETWEEN 0 AND 1),
    ADD COLUMN output_weight numeric NOT NULL DEFAULT 1 CHECK (output_weight > 0 AND output_weight <= 100);
ALTER TABLE usage_reservation
    ADD COLUMN charged_tokens bigint GENERATED ALWAYS AS (
        input_tokens + ceil(output_tokens * output_weight)::bigint
    ) STORED;
