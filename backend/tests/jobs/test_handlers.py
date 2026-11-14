"""Which handlers a worker runs: all it knows, or the kinds WORKER_KINDS names (conversions get
pods of their own, one job each)."""

from pathlib import Path
from typing import Any, cast

import pytest
from pydantic import ValidationError

from app.api.app import create_app
from app.conversion import job as convert_job
from app.conversion.models import ModelFile
from app.jobs import handlers
from app.jobs.context import JobContext
from app.jobs.handlers import ModelsMissing, check_models, handlers_for, make_handlers, select_handlers
from app.jobs.queue import Job
from tests.support import make_settings


async def anything(job: Job) -> Any:
    return None


KNOWN = {"source.fetch": anything, "source.convert": anything, "extract.run": anything}


def test_without_worker_kinds_a_worker_runs_every_kind() -> None:
    assert select_handlers(KNOWN, ()) == KNOWN


def test_worker_kinds_leave_the_others_to_other_workers() -> None:
    assert set(select_handlers(KNOWN, ("source.convert",))) == {"source.convert"}


def test_a_kind_no_handler_has_stops_the_start() -> None:
    # a typo would leave a pod idle that looks busy in the deployment
    with pytest.raises(ValueError, match=r"source\.convrt"):
        select_handlers(KNOWN, ("source.convrt",))


def test_the_settings_read_worker_kinds_as_a_comma_separated_list() -> None:
    assert make_settings(worker_kinds="source.fetch,source.convert").worker_kind_list == (
        "source.fetch",
        "source.convert",
    )
    assert make_settings().worker_kind_list == ()


@pytest.mark.parametrize("kinds", ["Source.fetch", "source.fetch, extract.run", "a,,b", ",", "source.fetch,"])
def test_worker_kinds_are_job_kinds_and_nothing_else(kinds: str) -> None:
    with pytest.raises(ValidationError, match="worker_kinds"):
        make_settings(worker_kinds=kinds)


NO_CONTEXT = cast(JobContext, object())  # the handlers are bound to it, not run


def installed(*packages: str) -> Any:
    return lambda name: object() if name in packages else None


def test_docling_s_conversions_are_a_kind_where_docling_is_installed(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(handlers, "find_spec", installed("docling"))

    assert {convert_job.KIND, convert_job.DOCLING_KIND} <= set(make_handlers(NO_CONTEXT))


def test_a_worker_without_docling_knows_no_docling_conversion(monkeypatch: pytest.MonkeyPatch) -> None:
    # the API's image: a worker taking every kind never claims one, one told to take them does not start
    monkeypatch.setattr(handlers, "find_spec", installed())

    known = make_handlers(NO_CONTEXT)

    assert convert_job.KIND in known and convert_job.DOCLING_KIND not in known
    with pytest.raises(ValueError, match=r"source\.convert_docling"):
        select_handlers(known, (convert_job.DOCLING_KIND,))


def test_every_kind_a_worker_has_a_handler_for_is_a_kind_the_gauges_name(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # the API's image has no Docling, yet the converter's workers queue its kind: the queue's
    # gauges name it all the same, not as "other"
    monkeypatch.setattr(handlers, "find_spec", installed())
    named = create_app(make_settings()).state.job_kinds
    monkeypatch.setattr(handlers, "find_spec", installed("docling"))

    assert set(make_handlers(NO_CONTEXT)) <= named


MODEL = ModelFile("layout/model.safetensors", 3, "0" * 64)


def test_a_worker_taking_docling_s_conversions_without_their_models_does_not_start(tmp_path: Path) -> None:
    with pytest.raises(ModelsMissing, match=r"1 of 1 .*python -m app\.conversion\.fetch_models"):
        check_models({convert_job.DOCLING_KIND: anything}, tmp_path, files=(MODEL,))


def test_a_worker_with_the_models_or_without_docling_s_conversions_starts(tmp_path: Path) -> None:
    (tmp_path / "layout").mkdir()
    (tmp_path / "layout" / "model.safetensors").write_bytes(b"abc")

    check_models({convert_job.DOCLING_KIND: anything}, tmp_path, files=(MODEL,))
    check_models({convert_job.KIND: anything}, tmp_path / "none", files=(MODEL,))


def test_a_worker_s_start_checks_the_models_of_the_kinds_it_takes(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    # the start's own sequence (app/jobs/worker.py): the kinds selected, then their models checked
    monkeypatch.setattr(handlers, "find_spec", installed("docling"))

    with pytest.raises(ModelsMissing):
        handlers_for(NO_CONTEXT, (convert_job.DOCLING_KIND,), tmp_path)
    assert set(handlers_for(NO_CONTEXT, (convert_job.KIND,), tmp_path)) == {convert_job.KIND}
