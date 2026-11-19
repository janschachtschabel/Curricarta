"""The settings of the service's work, by concern - what an account may start, the pipeline, the register's
requests and MEM-Schule, the conversion, what the sweep keeps, the ontology -, each a part of Settings
(app/core/settings.py)."""

from pathlib import Path
from typing import Annotated, Literal

from pydantic import BaseModel, Field, field_validator

from app.domain.iris import checked_base

# The repository's copy; the image sets ONTOLOGY_DIR to the folder it ships
REPOSITORY_ONTOLOGY = Path(__file__).resolve().parents[3] / "ontology"
# A job kind as the job table takes it (0003_job.sql): source.fetch, extract.run
_JOB_KIND = r"[a-z][a-z0-9_]*(\.[a-z][a-z0-9_]*)*"


class LimitSettings(BaseModel):
    # The largest file an upload or URL import takes, in MB (MiB): a curriculum is far smaller
    max_upload_mb: Annotated[int, Field(ge=1, le=500)] = 50
    # Uploads an account may make per minute; more are answered 429
    uploads_per_minute: Annotated[int, Field(ge=1)] = 20
    # Uploads one API process reads, checks and stores at once; one more waits up to 10 s, then
    # is answered 503 uploads_busy. Each holds up to MAX_UPLOAD_MB + 1 MiB in /tmp
    max_concurrent_uploads: Annotated[int, Field(ge=1, le=64)] = 2
    # The longest one upload's form is read while it holds one of those slots, in seconds; past
    # it, 408 upload_too_slow. Behind an edge that buffers bodies it never bites; it is what
    # keeps a client that trickles its body from holding a slot when the edge streams them
    upload_read_timeout_s: Annotated[int, Field(ge=5, le=3600)] = 120
    # Who gets the file (and later the blocks and Markdown) of an entry of no account - seed,
    # research - beside the editors and admins: nobody, every account, or anyone (visitors only
    # where PUBLIC_ACCESS is not off)
    third_party_markdown: Literal["hidden", "accounts", "public"] = "hidden"
    # Imports by URL an account may start per minute; more are answered 429
    url_imports_per_minute: Annotated[int, Field(ge=1)] = 20
    # Conversions an account may start per minute - each may take a worker for CONVERT_TIMEOUT_S;
    # more are answered 429. Asking for one that waits or is done starts none and counts none
    conversions_per_minute: Annotated[int, Field(ge=1)] = 20
    # Model jobs an account may have waiting or running at once; a start past them is answered
    # 429 (too_many_jobs), to try again in a minute (app/usage/admission.py)
    max_jobs_in_flight: Annotated[int, Field(ge=1, le=1000)] = 20
    # Model jobs an account may start per minute; more are answered 429 (too_many_starts)
    model_starts_per_minute: Annotated[int, Field(ge=1)] = 10
    # Exports of a MEM import an account asks for a minute (plan M2-6): each may check its document in a
    # child process for seconds
    exports_per_minute: Annotated[int, Field(ge=1)] = 10


class PipelineSettings(BaseModel):
    # Units X4 asks the model about at once within one job (app/pipeline/x4_statements.py); each
    # holds its reservation while it waits, so more of them spend an account's budget faster
    extract_concurrency: Annotated[int, Field(ge=1, le=16)] = 4
    # Whether a run, once X2 has cut the units, reckons what its rest is expected to charge and ends
    # (run_over_budget) before X3 asks where the account's quota has not that much left
    # (app/pipeline/watch.py); off, a run spends until a reservation finds too little
    extract_budget_watch: bool = True
    # How long X5 may validate one document against the Kern's shapes, in a child process killed at
    # its end (app/pipeline/shacl.py): 43 s measured for 2,400 rows, room for a slower machine
    shacl_timeout_s: Annotated[int, Field(ge=10, le=1800)] = 300
    # How long X5 may check one document's anchors against their blocks (app/pipeline/x5_stage.py):
    # past it no further batch begins, the rest stays unchecked with a finding, and the next check of
    # the document goes on with it - as long as the SHACL check may take
    x5_anchor_budget_s: Annotated[float, Field(ge=10, le=3600)] = 300.0
    # The address space of each child process the service starts - the conversion, the SHACL check -
    # in MiB, on Linux (app/core/child.py): opt-in, none by default, the containers' limits come first.
    # RLIMIT_AS counts virtual memory: set it to twice the virtual peak the children log, never by RSS;
    # an allocation past it that fails in Python ends the conversion "died" - Docling's models' load
    # too -; one a library fails otherwise ends it "unreadable" or "crashed" (an allocator's
    # RuntimeError, a signal), or as a handler error asked again (a model load failing otherwise)
    child_memory_limit_mb: Annotated[int, Field(ge=256, le=262144)] | None = None


class SourceSettings(BaseModel):
    # Who the register's requests say they are (source.fetch, source.check): the product token
    # robots.txt knows us by, then where to reach the operators; printable ASCII, as a header
    # holds it - and no space at its end, which h11 refuses in a header's value
    fetch_user_agent: Annotated[
        str, Field(pattern=r"^[A-Za-z0-9._-]+(/[!-~]+)?( [ -~]*[!-~])?$", max_length=200)
    ] = "Curricarta (+https://github.com/janschachtschabel/Curricarta)"
    # The least time between two requests of the check job to one host, across all workers
    check_host_interval_s: Annotated[float, Field(ge=0.5, le=60)] = 2.0
    # How long the MEM import looks for its wordings in the document; past it, the rest is anchored as not
    # found on an estimated page (plan M2, Nachtrag M2-4)
    mem_search_budget_s: Annotated[float, Field(ge=10, le=3600)] = 300.0
    # How long the export of a MEM import may check it against the MEM shapes, in a child process killed at
    # its end (plan M2-6): the request waits for it, so within REQUEST_S (55 s, under the edge's 75 s) with
    # room for the waits before it (app/exports/mem_export.py); 4.0 s measured in the child for 2,400 parts
    mem_export_timeout_s: Annotated[float, Field(ge=5, le=45)] = 30.0
    # How long the Kern export of a frozen document may build and write its Turtle, in a child process
    # killed at its end (plan M3a C1): the request waits for it, as for the MEM export's check, within
    # REQUEST_S (app/exports/kern_export.py)
    kern_export_timeout_s: Annotated[float, Field(ge=5, le=45)] = 30.0
    # The licence of MEM-Schule's data, once the operators checked it (plan M2, E14): an https IRI the
    # catalogue gives every plan it reads; empty while unchecked. Imports made before take it with
    # ``python -m app.sources.mem.amend_licence IRI``
    mem_data_licence: Annotated[
        str, Field(max_length=2000, pattern=r"^(https://[^\s\x00-\x1f\x7f<>\"{}|\\^\x60]+)?$")
    ] = ""
    # MEM-Schule's SPARQL endpoint (plan M2, E11): a public https address, asked by the catalogue and the
    # import alone; the client pins its address and refuses one inside the network. Host and path alone
    # (no @, ?, #): the address is written into every plan's attribution, so it carries no credentials
    mem_sparql_url: Annotated[str, Field(pattern=r'^https://[!-"$->A-~]+$', max_length=2000)] = (
        "https://sparql.mem.edufeed.org/sparql"
    )


class ConversionSettings(BaseModel):
    # The most pages of a PDF the conversion takes; a longer one is refused (too_many_pages)
    max_pdf_pages: Annotated[int, Field(ge=1, le=5000)] = 800
    # How long one conversion may take before its process is ended (timed_out)
    convert_timeout_s: Annotated[float, Field(ge=1, le=7200)] = 900.0
    # The engines a conversion may be asked of, comma-separated, the first the one asked of when none
    # is named: docling where the converter runs (Compose's service converter, plan M1 3b)
    conversion_engines: str = "pdfplumber"
    # The job kinds this worker takes, comma-separated (the conversion pods: source.convert);
    # empty for every kind it knows
    worker_kinds: Annotated[str, Field(pattern=rf"^({_JOB_KIND}(,{_JOB_KIND})*)?$")] = ""

    @property
    def worker_kind_list(self) -> tuple[str, ...]:
        return tuple(self.worker_kinds.split(",")) if self.worker_kinds else ()

    @property
    def conversion_engine_list(self) -> tuple[str, ...]:
        return tuple(self.conversion_engines.split(","))

    @field_validator("conversion_engines")
    @classmethod
    def _known_engines(cls, value: str) -> str:
        from app.conversion.base import offered_engines  # the engines' names, none of their libraries

        names = value.split(",")
        unknown = [name for name in names if name not in offered_engines()]
        if unknown:
            raise ValueError(
                f"names no engine {unknown[0]!r}; the engines are {', '.join(offered_engines())}"
            )
        if len(set(names)) < len(names):
            raise ValueError("names an engine twice")
        return value


class RetentionSettings(BaseModel):
    # What the sweep (python -m app.retention) keeps, in days; 0 keeps everything. Jobs ended longer ago go,
    # but a key's latest (it says how a document's work ended), one a conversion waits for and one holding a
    # reservation; GET /api/v1/jobs/{id} answers 404 for one gone. The ledger's bookings never go
    retention_jobs_days: Annotated[int, Field(ge=0, le=3650)] = 90
    # Audit entries older than this go
    retention_audit_days: Annotated[int, Field(ge=0, le=3650)] = 365
    # The raw model answers of runs ended longer ago leave the store, and the run says so (its key cleared):
    # measure a document's quality from its answers before (python -m app.quality.usage_report --raw)
    retention_raw_answers_days: Annotated[int, Field(ge=0, le=3650)] = 30


class OntologySettings(BaseModel):
    ontology_dir: Path = REPOSITORY_ONTOLOGY
    # The base of the IRIs a document gets when it is frozen (app/domain/iris.py), an http(s) IRI
    # ending in a slash; none until the namespace is registered (ontology/konzept.md), and then
    # nothing is frozen
    iri_base: str | None = None
    # The log's form (the level is the server's, ServerSettings): here, where the generated table of
    # settings has always listed it (app/core/config_doc.py follows the order they are declared in)
    log_format: Literal["text", "json"] = "text"

    @field_validator("iri_base")
    @classmethod
    def _iri_base(cls, value: str | None) -> str | None:
        return None if value is None else checked_base(value)
