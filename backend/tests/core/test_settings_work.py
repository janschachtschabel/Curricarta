"""The settings of the service's work (app/core/settings_work.py): what an account may start, the
pipeline, the register's requests, the conversion, the sweep, the ontology. Invented values only, as in
test_settings.py."""

import pytest
from pydantic import ValidationError

from app.core.settings import Settings
from tests.core.test_settings import no_settings_variables
from tests.support import FAKE_DATABASE_URL as FAKE_URL
from tests.support import make_settings

__all__ = ["no_settings_variables"]  # the fixture, shared with test_settings


def test_the_iri_base_is_none_or_an_http_iri_ending_in_a_slash(monkeypatch: pytest.MonkeyPatch) -> None:
    # none until the namespace is registered (ontology/konzept.md): freezing asks for one
    monkeypatch.setenv("DATABASE_URL", FAKE_URL)
    assert Settings().iri_base is None

    monkeypatch.setenv("IRI_BASE", "https://example.org/kk/")
    assert Settings().iri_base == "https://example.org/kk/"

    monkeypatch.setenv("IRI_BASE", "https://example.org/kk")
    with pytest.raises(ValidationError, match="iri_base"):
        Settings()


def test_the_ontology_folder_defaults_to_the_repository_copy(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("DATABASE_URL", FAKE_URL)

    assert (Settings().ontology_dir / "ontologie" / "cur-kern.ttl").is_file()


@pytest.mark.parametrize(
    "agent",
    [
        "Curricarta/1 (x) ",
        "Curricarta/1 (x)\tmore",
        " Curricarta/1",
        "Curricarta/1  ",
        "(no token)",
        "Curricarta/1 (Grüße)",
    ],
)
def test_a_user_agent_a_header_cannot_carry_is_refused(agent: str) -> None:
    # h11 refuses a header value ending in a space: every request of the register would fail
    with pytest.raises(ValidationError):
        make_settings(fetch_user_agent=agent)


@pytest.mark.parametrize(
    "agent",
    ["Curricarta", "Curricarta/1", "Curricarta/1 (+https://example.org/curricarta; mail@example.org)"],
)
def test_a_user_agent_of_its_token_and_a_contact_is_taken(agent: str) -> None:
    assert make_settings(fetch_user_agent=agent).fetch_user_agent == agent


def test_model_jobs_are_limited_by_default() -> None:
    # as the old app: twenty waiting or running for an account, and ten starts a minute
    settings = make_settings()

    assert (settings.max_jobs_in_flight, settings.model_starts_per_minute) == (20, 10)


def test_a_replica_takes_two_uploads_at_once_by_default() -> None:
    assert make_settings().max_concurrent_uploads == 2


@pytest.mark.parametrize("value", [0, 65])
def test_the_uploads_a_replica_takes_at_once_are_bounded(value: int) -> None:
    with pytest.raises(ValueError):
        make_settings(max_concurrent_uploads=value)


@pytest.mark.parametrize("value", [1, 64])
def test_a_replica_takes_one_to_sixty_four_uploads_at_once(value: int) -> None:
    assert make_settings(max_concurrent_uploads=value).max_concurrent_uploads == value


def test_an_upload_s_form_is_read_for_two_minutes_at_most_by_default() -> None:
    assert make_settings().upload_read_timeout_s == 120


@pytest.mark.parametrize("value", [4, 3601])
def test_the_time_an_upload_s_form_is_read_is_bounded(value: int) -> None:
    # no 0 for off: an operator with slow uplinks raises it
    with pytest.raises(ValueError, match="than or equal to"):
        make_settings(upload_read_timeout_s=value)


@pytest.mark.parametrize("value", [5, 3600])
def test_an_upload_s_form_is_read_for_five_seconds_to_an_hour(value: int) -> None:
    assert make_settings(upload_read_timeout_s=value).upload_read_timeout_s == value


def test_the_time_an_upload_s_form_is_read_comes_from_its_variable(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("DATABASE_URL", FAKE_URL)
    monkeypatch.setenv("UPLOAD_READ_TIMEOUT_S", "300")

    assert Settings().upload_read_timeout_s == 300


def test_x4_asks_four_units_at_once_by_default() -> None:
    assert make_settings().extract_concurrency == 4


@pytest.mark.parametrize("value", [1, 16])
def test_x4_asks_one_to_sixteen_units_at_once(value: int) -> None:
    assert make_settings(extract_concurrency=value).extract_concurrency == value


def test_a_run_watches_its_budget_after_x2_by_default() -> None:
    assert make_settings().extract_budget_watch is True


def test_the_budget_watch_is_turned_off_by_its_variable(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("DATABASE_URL", FAKE_URL)
    monkeypatch.setenv("EXTRACT_BUDGET_WATCH", "false")

    assert Settings().extract_budget_watch is False


def test_x5_gives_its_shacl_check_five_minutes_by_default() -> None:
    # 43 s measured for a document of 2,400 rows (plan M1, Nachtrag 8a)
    assert make_settings().shacl_timeout_s == 300


@pytest.mark.parametrize("value", [10, 1800])
def test_x5_gives_its_shacl_check_ten_seconds_to_half_an_hour(value: int) -> None:
    assert make_settings(shacl_timeout_s=value).shacl_timeout_s == value


def test_x5_gives_its_anchors_five_minutes_by_default() -> None:
    # as long as its SHACL check: past it the rest is left to the next check (audit 2026-11-14)
    assert make_settings().x5_anchor_budget_s == 300.0


@pytest.mark.parametrize("value", [10.0, 3600.0])
def test_x5_gives_its_anchors_ten_seconds_to_an_hour(value: float) -> None:
    assert make_settings(x5_anchor_budget_s=value).x5_anchor_budget_s == value


def test_the_children_s_memory_is_not_bounded_by_default() -> None:
    # opt-in: the containers' limits come first, and a guess too tight fails Docling's models
    assert make_settings().child_memory_limit_mb is None


@pytest.mark.parametrize("value", [256, 262144])
def test_the_children_s_memory_is_bounded_from_256_mib_to_256_gib(value: int) -> None:
    assert make_settings(child_memory_limit_mb=value).child_memory_limit_mb == value


@pytest.mark.parametrize(
    ("variable", "value"),
    [
        ("CHILD_MEMORY_LIMIT_MB", "255"),
        ("CHILD_MEMORY_LIMIT_MB", "262145"),
        ("X5_ANCHOR_BUDGET_S", "9.9"),
        ("X5_ANCHOR_BUDGET_S", "3600.1"),
        ("MAX_JOBS_IN_FLIGHT", "0"),
        ("MAX_JOBS_IN_FLIGHT", "1001"),
        ("MODEL_STARTS_PER_MINUTE", "0"),
        ("EXTRACT_CONCURRENCY", "0"),
        ("EXTRACT_CONCURRENCY", "17"),
        ("SHACL_TIMEOUT_S", "9"),
        ("SHACL_TIMEOUT_S", "1801"),
    ],
)
def test_the_limits_of_jobs_are_bounded(monkeypatch: pytest.MonkeyPatch, variable: str, value: str) -> None:
    monkeypatch.setenv("DATABASE_URL", FAKE_URL)
    monkeypatch.setenv(variable, value)

    with pytest.raises(ValidationError, match=variable.lower()):
        Settings()


def test_the_service_converts_with_pdfplumber_alone_until_a_converter_runs() -> None:
    assert make_settings().conversion_engine_list == ("pdfplumber",)


def test_the_engines_offered_are_named_the_first_the_one_asked_of_by_default() -> None:
    assert make_settings(conversion_engines="docling,pdfplumber").conversion_engine_list == (
        "docling",
        "pdfplumber",
    )


@pytest.mark.parametrize(
    "value", ["", "tesseract", "pdfplumber,tesseract", "docling,docling", "docling, pdfplumber"]
)
def test_the_engines_offered_are_known_engines_each_named_once(value: str) -> None:
    with pytest.raises(ValidationError, match="conversion_engines"):
        make_settings(conversion_engines=value)


def test_the_sweep_keeps_jobs_a_quarter_the_audit_a_year_and_raw_answers_a_month_by_default() -> None:
    settings = make_settings()

    assert (
        settings.retention_jobs_days,
        settings.retention_audit_days,
        settings.retention_raw_answers_days,
    ) == (
        90,
        365,
        30,
    )


@pytest.mark.parametrize(
    "name", ["retention_jobs_days", "retention_audit_days", "retention_raw_answers_days"]
)
@pytest.mark.parametrize("value", [0, 3650])
def test_a_retention_is_nothing_to_ten_years(name: str, value: int) -> None:
    # 0 keeps everything
    assert getattr(make_settings(**{name: value}), name) == value


@pytest.mark.parametrize(
    "name", ["retention_jobs_days", "retention_audit_days", "retention_raw_answers_days"]
)
@pytest.mark.parametrize("value", [-1, 3651])
def test_a_retention_beyond_its_bounds_is_refused(name: str, value: int) -> None:
    with pytest.raises(ValidationError, match=name):
        make_settings(**{name: value})
