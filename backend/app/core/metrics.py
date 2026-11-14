"""Prometheus metrics of the process, rendered for a scrape of /metrics on the internal port.

One process per pod keeps the values in memory; the cluster sums over the pods - but for the
queue's gauges, which every API replica reads alike from the database. Label values
come from fixed sets - route templates, known methods, status codes - never from raw input,
so the number of series stays bounded.
"""

from collections.abc import Collection, Iterable, Mapping

from prometheus_client import REGISTRY, Counter, Gauge, Histogram
from prometheus_client.exposition import choose_encoder

from app import __revision__, __version__

# The method is caller input: anything else (PROPFIND, invented verbs) shares one label
HTTP_METHODS = frozenset({"GET", "HEAD", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"})
OTHER_METHOD = "other"
# Requests are short; long work runs as a job in the worker
DURATION_BUCKETS = (0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1, 2.5, 5, 10, 30, 60)

HTTP_REQUESTS = Counter(
    "curricarta_http_requests_total",
    "HTTP requests by method, route template and status",
    ["method", "route", "status"],
)
HTTP_DURATION = Histogram(
    "curricarta_http_request_duration_seconds",
    "Duration of HTTP requests by method and route template",
    ["method", "route"],
    buckets=DURATION_BUCKETS,
)


# Jobs run from a second to an hour (a conversion with OCR, an extraction of many units)
JOB_DURATION_BUCKETS = (1, 5, 15, 30, 60, 120, 300, 600, 1200, 1800, 3600)
# outcome, as the worker saw the run end and wrote it: done, failed (PermanentError), error
# (retried while attempts remain), cancelled, released (handed back at a shutdown), lost (its
# lease, seen at a heartbeat, by the handler or at the end - or an outcome that could not be
# written: either way the job runs again once its lease expires)
JOBS = Counter("curricarta_jobs_total", "Job runs by kind and how they ended", ["kind", "outcome"])
JOB_DURATION = Histogram(
    "curricarta_job_duration_seconds",
    "Duration of job runs by kind",
    ["kind"],
    buckets=JOB_DURATION_BUCKETS,
)
# Leases no worker renewed, handed on by a sweep (a worker died, or its loop was held): outcome
# is what became of the job - queued (attempts remain), failed (lease_lost) or cancelled
JOB_LEASES_EXPIRED = Counter(
    "curricarta_job_leases_expired_total", "Expired job leases by what became of the job", ["outcome"]
)


# Conversions (X0) by engine and how they ended: done, or the reason they failed
# (app/db/conversions.py FailureCode); and the pages of those done
CONVERSIONS = Counter(
    "curricarta_conversions_total", "Conversions by engine and how they ended", ["engine", "outcome"]
)
CONVERSION_PAGES = Counter("curricarta_conversion_pages_total", "Pages converted, by engine", ["engine"])


# Requests to the language model by how they ended: answered, refused (an HTTP error),
# unanswered (sent, never answered) or unsent (the provider never reached); and their tokens by
# kind - input (of it, cached_input), output, as the provider reported them, and estimated: what
# was held for one unanswered, or for an answer that reported no usage
LLM_REQUESTS = Counter(
    "curricarta_llm_requests_total", "Requests to the language model by how they ended", ["outcome"]
)
LLM_TOKENS = Counter(
    "curricarta_llm_tokens_total", "Tokens of the language model's requests by kind", ["kind"]
)
# Reservations of an account's budget by what became of them: held, refused (the budget did not
# hold them), booked, late (booked already: as abandoned with its job, or by a booking asked
# again after its commit's answer was lost) or abandoned
USAGE_RESERVATIONS = Counter(
    "curricarta_usage_reservations_total",
    "Reservations of the model's budget by what became of them",
    ["outcome"],
)


# The queue as the API reads it from the job table at a scrape (app/api/internal.py), not the worker:
# with every worker gone the queue stays in sight. Each replica reads the same table and says the
# same values, so a rule takes their max, never their sum. kind is one the workers have a handler
# for, or "other"; status queued or running
QUEUE_STATUSES = ("queued", "running")
OTHER_KIND = "other"
QUEUE_JOBS = Gauge("curricarta_queue_jobs", "Waiting and running jobs by kind", ["kind", "status"])
QUEUE_OLDEST_WAITING = Gauge(
    "curricarta_queue_oldest_waiting_seconds",
    "How long the oldest due waiting job has waited, by kind",
    ["kind"],
)
QUEUE_READS_FAILED = Counter(
    "curricarta_queue_reads_failed_total", "Reads of the queue at a scrape that failed; the last values stand"
)
# The process's connection pool, as psycopg_pool counts it at the scrape
DB_POOL_SIZE = Gauge("curricarta_db_pool_size", "Connections the pool holds, in use or free")
DB_POOL_AVAILABLE = Gauge("curricarta_db_pool_available", "Connections of the pool free to be taken")
DB_POOL_WAITING = Gauge(
    "curricarta_db_pool_requests_waiting", "Requests waiting for a connection of the pool"
)
# Which build runs: the series' labels say it, the value is 1
BUILD_INFO = Gauge(
    "curricarta_build_info", "The running build's version and revision", ["version", "revision"]
)
BUILD_INFO.labels(__version__, __revision__).set(1)


def observe_queue(depth: Iterable[tuple[str, str, int, float]], kinds: Collection[str]) -> None:
    """``depth`` as app.jobs.queue.queue_depth reads it; ``kinds`` those with a handler. Every kind
    is set, one without jobs to 0, not left at its last value; any other kind is counted as other."""
    counts = {(kind, status): 0 for kind in (*kinds, OTHER_KIND) for status in QUEUE_STATUSES}
    oldest = dict.fromkeys((*kinds, OTHER_KIND), 0.0)
    for kind, status, count, age in depth:
        label = kind if kind in oldest else OTHER_KIND
        counts[label, status] += count
        oldest[label] = max(oldest[label], age)
    for (kind, status), count in counts.items():
        QUEUE_JOBS.labels(kind, status).set(count)
    for kind, age in oldest.items():
        QUEUE_OLDEST_WAITING.labels(kind).set(age)


def observe_pool(stats: Mapping[str, int]) -> None:
    """``stats`` as psycopg_pool's ``get_stats()`` gives them."""
    DB_POOL_SIZE.set(stats.get("pool_size", 0))
    DB_POOL_AVAILABLE.set(stats.get("pool_available", 0))
    DB_POOL_WAITING.set(stats.get("requests_waiting", 0))


def observe_llm_request(
    outcome: str,
    *,
    input_tokens: int = 0,
    cached_input_tokens: int = 0,
    output_tokens: int = 0,
    estimated_tokens: int = 0,
) -> None:
    """``outcome`` is answered, refused, unanswered or unsent: a fixed set."""
    LLM_REQUESTS.labels(outcome).inc()
    tokens = {
        "input": input_tokens,
        "cached_input": cached_input_tokens,
        "output": output_tokens,
        "estimated": estimated_tokens,
    }
    for kind, count in tokens.items():
        if count:
            LLM_TOKENS.labels(kind).inc(count)


def observe_reservations(outcome: str, count: int = 1) -> None:
    """``outcome`` is held, refused, booked, late or abandoned: a fixed set."""
    if count:
        USAGE_RESERVATIONS.labels(outcome).inc(count)


def observe_conversion(engine: str, outcome: str, pages: int = 0) -> None:
    """``engine`` is an offered one and ``outcome`` done or a FailureCode: fixed sets."""
    CONVERSIONS.labels(engine, outcome).inc()
    if pages:
        CONVERSION_PAGES.labels(engine).inc(pages)


def observe_job(kind: str, outcome: str, seconds: float) -> None:
    """``kind`` is a kind the worker has a handler for: a fixed set, so the series stay few."""
    JOBS.labels(kind, outcome).inc()
    JOB_DURATION.labels(kind).observe(seconds)


def observe_expired_leases(outcomes: Iterable[str]) -> None:
    """``outcomes`` are job statuses a sweep set: a fixed set."""
    for outcome in outcomes:
        JOB_LEASES_EXPIRED.labels(outcome).inc()


def bounded_method(method: str) -> str:
    """The method as a label or a log field: one of the known ones, or ``other``."""
    return method if method in HTTP_METHODS else OTHER_METHOD


def observe_request(method: str, route: str, status: int, seconds: float) -> None:
    method = bounded_method(method)
    HTTP_REQUESTS.labels(method, route, str(status)).inc()
    HTTP_DURATION.labels(method, route).observe(seconds)


def render(accept: str) -> tuple[bytes, str]:
    """The process's metrics in the format the scraper's Accept header asks for, and its media type."""
    encoder, content_type = choose_encoder(accept)
    return encoder(REGISTRY), content_type
