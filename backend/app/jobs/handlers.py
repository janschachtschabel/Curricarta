"""The job kinds the worker runs, each with its handler bound to the job context; the pipeline
stages register in ``make_handlers`` (M1).

Docling's conversions are a kind of their own (app/conversion/job.py), known only where Docling is
installed - the converter's image -, so a worker of the API's image never claims one; one that takes
them does not start without Docling's models (``check_models``): every conversion would fail.
"""

from collections.abc import Collection, Mapping, Sequence
from functools import partial
from importlib.util import find_spec
from pathlib import Path

from app.conversion.models import MODEL_FILES, MODELS_DIR, ModelFile, missing
from app.jobs.context import JobContext
from app.jobs.worker import Handler


class UnknownJobKind(ValueError):
    """WORKER_KINDS names a kind no handler has."""


class ModelsMissing(RuntimeError):
    """The worker takes Docling's conversions, and Docling's models are not in their folder."""


def make_handlers(context: JobContext) -> dict[str, Handler]:
    from app.conversion import job as convert_job
    from app.pipeline import run as extract_run
    from app.pipeline import x5_check, x6_repair
    from app.sources import check_job, fetch_job
    from app.sources.mem import catalog as mem_catalog
    from app.sources.mem import import_job as mem_import

    handlers: dict[str, Handler] = {
        fetch_job.KIND: partial(fetch_job.fetch_source, context),
        check_job.KIND: partial(check_job.check_sources, context),
        mem_catalog.KIND: partial(mem_catalog.read_catalog, context),
        mem_import.KIND: partial(mem_import.import_document, context),
        convert_job.KIND: partial(convert_job.convert_source, context),
        extract_run.KIND: partial(extract_run.extract_document, context),
        x6_repair.REPAIR_KIND: partial(x6_repair.repair_document, context),
        x5_check.CHECK_KIND: partial(x5_check.check_document, context),
    }
    if find_spec("docling") is not None:  # found, not imported: the child that converts imports it
        handlers[convert_job.DOCLING_KIND] = partial(convert_job.convert_source, context)
    return handlers


def select_handlers(handlers: Mapping[str, Handler], kinds: Collection[str]) -> dict[str, Handler]:
    """The handlers of ``kinds``, or all of them for none. A kind without a handler stops the start:
    a typo would leave a pod idle that looks busy in the deployment."""
    if not kinds:
        return dict(handlers)
    unknown = sorted(set(kinds) - set(handlers))
    if unknown:
        raise UnknownJobKind(f"WORKER_KINDS names kinds no handler has: {', '.join(unknown)}")
    return {kind: handler for kind, handler in handlers.items() if kind in kinds}


def handlers_for(
    context: JobContext, kinds: Collection[str], models: Path = MODELS_DIR
) -> dict[str, Handler]:
    """The handlers a worker starts with: those of ``kinds`` (all for none), their models there.
    UnknownJobKind or ModelsMissing stop its start."""
    handlers = select_handlers(make_handlers(context), kinds)
    check_models(handlers, models)
    return handlers


def check_models(
    handlers: Mapping[str, Handler], directory: Path = MODELS_DIR, *, files: Sequence[ModelFile] = MODEL_FILES
) -> None:
    """ModelsMissing where the worker takes Docling's conversions and a model file is missing from
    ``directory`` or of another size; their hashes the fetch checks (app/conversion/fetch_models.py)."""
    from app.conversion.job import DOCLING_KIND

    if DOCLING_KIND not in handlers:
        return
    gone = missing(directory, files)
    if gone:
        raise ModelsMissing(
            f"{len(gone)} of {len(files)} of Docling's model files are missing from {directory}: "
            f"fetch them once with python -m app.conversion.fetch_models {directory}"
        )
