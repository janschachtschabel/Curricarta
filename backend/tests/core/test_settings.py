"""Settings come from the environment; secrets may come from a file named by <NAME>_FILE.

Only invented values are used here: a settings object built from the real environment
would read real keys, and pydantic would print them in a validation error.
"""

from collections.abc import Iterator
from pathlib import Path
from typing import Annotated

import pytest
from pydantic import Field, SecretStr, ValidationError

from app.core.settings import Settings, _environment_value
from tests.support import FAKE_DATABASE_URL as FAKE_URL
from tests.support import make_settings, without_settings_variables


@pytest.fixture(autouse=True)
def no_settings_variables() -> Iterator[None]:
    with without_settings_variables():
        yield


def test_defaults_apply_when_only_the_required_value_is_set(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("DATABASE_URL", FAKE_URL)

    settings = Settings()

    assert settings.public_port == 8000
    assert settings.internal_port == 9000
    assert settings.log_level == "INFO"
    assert settings.log_format == "text"
    assert settings.database_url.get_secret_value() == FAKE_URL


def test_a_secret_file_wins_over_the_plain_variable(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    secret = tmp_path / "database_url"
    secret.write_text("postgresql://curricarta:from-file@db:5432/curricarta\n", encoding="utf-8")
    monkeypatch.setenv("DATABASE_URL", FAKE_URL)
    monkeypatch.setenv("DATABASE_URL_FILE", str(secret))

    settings = Settings()

    assert settings.database_url.get_secret_value() == "postgresql://curricarta:from-file@db:5432/curricarta"


def test_a_missing_secret_file_names_the_variable(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setenv("DATABASE_URL_FILE", str(tmp_path / "absent"))

    with pytest.raises(ValueError, match="DATABASE_URL_FILE"):
        Settings()


def test_a_secret_file_named_in_lower_case_is_read(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    # the plain variables match in any case, so their files must too
    secret = tmp_path / "database_url"
    secret.write_text("postgresql://curricarta:from-file@db/curricarta", encoding="utf-8")
    monkeypatch.setenv("database_url", FAKE_URL)
    monkeypatch.setenv("database_url_file", str(secret))

    assert Settings().database_url.get_secret_value() == "postgresql://curricarta:from-file@db/curricarta"


def test_a_byte_order_mark_is_not_part_of_the_secret(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    secret = tmp_path / "database_url"
    byte_order_mark = chr(0xFEFF)  # what PowerShell 5.1 puts in front of a UTF-8 file
    secret.write_text(f"{byte_order_mark}postgresql://curricarta:bom@db/curricarta\r\n", encoding="utf-8")
    monkeypatch.setenv("DATABASE_URL_FILE", str(secret))

    assert Settings().database_url.get_secret_value() == "postgresql://curricarta:bom@db/curricarta"


def test_a_secret_file_that_is_not_utf8_is_refused_without_its_bytes(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    secret = tmp_path / "database_url"
    secret.write_bytes(b"postgresql://curricarta:" + bytes([0xFF, 0xFE]) + b"@db/curricarta")
    monkeypatch.setenv("DATABASE_URL_FILE", str(secret))

    with pytest.raises(ValueError, match="DATABASE_URL_FILE") as caught:
        Settings()

    assert "0xff" not in str(caught.value)
    assert "position" not in str(caught.value)


@pytest.mark.parametrize("content", ["", "\n", "\r\n"], ids=["empty", "newline", "crlf"])
def test_an_empty_secret_file_counts_as_missing(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, content: str
) -> None:
    secret = tmp_path / "database_url"
    secret.write_text(content, encoding="utf-8")
    monkeypatch.setenv("DATABASE_URL", FAKE_URL)
    monkeypatch.setenv("DATABASE_URL_FILE", str(secret))

    with pytest.raises(ValidationError, match="database_url"):
        Settings()


def test_an_empty_required_variable_counts_as_missing(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("DATABASE_URL", "")

    with pytest.raises(ValidationError, match="database_url"):
        Settings()


def test_an_optional_secret_is_read_from_its_file(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    class WithOptionalSecret(Settings):
        invented_key: SecretStr | None = None

    secret = tmp_path / "invented_key"
    secret.write_text("invented-value", encoding="utf-8")
    monkeypatch.setenv("DATABASE_URL", FAKE_URL)
    monkeypatch.setenv("INVENTED_KEY_FILE", str(secret))

    key = WithOptionalSecret().invented_key

    assert key is not None
    assert key.get_secret_value() == "invented-value"


def test_a_missing_required_value_names_the_field_and_no_value(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("INTERNAL_PORT", "9123")

    with pytest.raises(ValidationError) as caught:
        Settings()

    assert "database_url" in str(caught.value)
    assert "9123" not in str(caught.value)


def test_an_invalid_value_is_reported_without_echoing_it(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("DATABASE_URL", FAKE_URL)
    monkeypatch.setenv("PUBLIC_PORT", "not-a-port-SECRET123")

    with pytest.raises(ValidationError) as caught:
        Settings()

    assert "public_port" in str(caught.value)
    assert "SECRET123" not in str(caught.value)


@pytest.mark.parametrize("level", ["LOUD", "", "info "])
def test_an_unknown_log_level_is_refused(monkeypatch: pytest.MonkeyPatch, level: str) -> None:
    monkeypatch.setenv("DATABASE_URL", FAKE_URL)
    monkeypatch.setenv("LOG_LEVEL", level)

    with pytest.raises(ValidationError, match="log_level"):
        Settings()


def test_the_iri_base_is_none_or_an_http_iri_ending_in_a_slash(monkeypatch: pytest.MonkeyPatch) -> None:
    # none until the namespace is registered (ontology/konzept.md): freezing asks for one
    monkeypatch.setenv("DATABASE_URL", FAKE_URL)
    assert Settings().iri_base is None

    monkeypatch.setenv("IRI_BASE", "https://example.org/kk/")
    assert Settings().iri_base == "https://example.org/kk/"

    monkeypatch.setenv("IRI_BASE", "https://example.org/kk")
    with pytest.raises(ValidationError, match="iri_base"):
        Settings()


def test_the_log_level_is_case_insensitive(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("DATABASE_URL", FAKE_URL)
    monkeypatch.setenv("LOG_LEVEL", "debug")

    assert Settings().log_level == "DEBUG"


def test_the_server_stays_on_loopback_without_a_root_path(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("DATABASE_URL", FAKE_URL)

    settings = Settings()

    assert settings.host == "127.0.0.1"
    assert settings.root_path == ""


def test_a_root_path_is_taken(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("DATABASE_URL", FAKE_URL)
    monkeypatch.setenv("ROOT_PATH", "/curricarta")

    assert Settings().root_path == "/curricarta"


@pytest.mark.parametrize("root", ["/curricarta/v1", "/k-a_b.c~"])
def test_a_root_path_of_plain_segments_is_taken(monkeypatch: pytest.MonkeyPatch, root: str) -> None:
    monkeypatch.setenv("DATABASE_URL", FAKE_URL)
    monkeypatch.setenv("ROOT_PATH", root)

    assert Settings().root_path == root


@pytest.mark.parametrize(
    "root",
    [
        "curricarta",
        "/curricarta/",
        "/",
        "/curricarta ",
        "/k k",
        "/curricarta?x=1",
        "/curricarta#f",
        "/curricarta\n",
        "/k'a",
        "//curricarta",
    ],
)
def test_a_root_path_other_than_plain_segments_is_refused(monkeypatch: pytest.MonkeyPatch, root: str) -> None:
    monkeypatch.setenv("DATABASE_URL", FAKE_URL)
    monkeypatch.setenv("ROOT_PATH", root)

    with pytest.raises(ValidationError, match="root_path"):
        Settings()


def test_the_two_ports_must_differ(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("DATABASE_URL", FAKE_URL)
    monkeypatch.setenv("INTERNAL_PORT", "8000")

    with pytest.raises(ValidationError, match="internal_port"):
        Settings()


def test_a_file_variable_is_found_in_any_case_on_a_case_sensitive_environment() -> None:
    # Windows' environment ignores case anyway; Linux' does not
    environment = {"database_url_file": "/run/secrets/lower", "OTHER_FILE": "/x"}

    assert _environment_value("DATABASE_URL_FILE", environment) == "/run/secrets/lower"
    assert _environment_value("DATABASE_URL_FILE", {"DATABASE_URL_FILE": "/exact"}) == "/exact"
    assert _environment_value("DATABASE_URL_FILE", {}) is None


def test_a_constrained_optional_secret_is_read_from_its_file(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    class WithConstrainedSecret(Settings):
        invented_key: Annotated[SecretStr, Field(min_length=1)] | None = None

    secret = tmp_path / "invented_key"
    secret.write_text("invented-value", encoding="utf-8")
    monkeypatch.setenv("DATABASE_URL", FAKE_URL)
    monkeypatch.setenv("INVENTED_KEY_FILE", str(secret))

    key = WithConstrainedSecret().invented_key

    assert key is not None
    assert key.get_secret_value() == "invented-value"


def test_a_blank_required_secret_counts_as_missing(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("DATABASE_URL", "   ")

    with pytest.raises(ValidationError, match="database_url"):
        Settings()


def test_the_database_pool_has_bounded_defaults(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("DATABASE_URL", FAKE_URL)

    settings = Settings()

    assert (settings.db_pool_min_size, settings.db_pool_max_size) == (1, 10)
    assert settings.db_pool_timeout_s == 5.0


@pytest.mark.parametrize("seconds", ["0", "61"])
def test_a_request_waits_for_a_connection_a_bounded_time(
    monkeypatch: pytest.MonkeyPatch, seconds: str
) -> None:
    monkeypatch.setenv("DATABASE_URL", FAKE_URL)
    monkeypatch.setenv("DB_POOL_TIMEOUT_S", seconds)

    with pytest.raises(ValidationError, match="db_pool_timeout_s"):
        Settings()


def test_the_database_sessions_end_an_idle_transaction_and_let_statements_run(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("DATABASE_URL", FAKE_URL)

    settings = Settings()

    assert (settings.db_idle_in_transaction_timeout_s, settings.db_statement_timeout_s) == (300, 0)


@pytest.mark.parametrize(
    ("variable", "value"),
    [
        ("DB_IDLE_IN_TRANSACTION_TIMEOUT_S", "-1"),
        ("DB_IDLE_IN_TRANSACTION_TIMEOUT_S", "3601"),
        ("DB_STATEMENT_TIMEOUT_S", "-1"),
        ("DB_STATEMENT_TIMEOUT_S", "3601"),
    ],
)
def test_the_database_sessions_timeouts_are_bounded(
    monkeypatch: pytest.MonkeyPatch, variable: str, value: str
) -> None:
    monkeypatch.setenv("DATABASE_URL", FAKE_URL)
    monkeypatch.setenv(variable, value)

    with pytest.raises(ValidationError, match=variable.lower()):
        Settings()


def test_the_worker_s_times_have_defaults(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("DATABASE_URL", FAKE_URL)

    settings = Settings()

    assert (settings.job_lease_s, settings.job_poll_s, settings.job_shutdown_grace_s) == (60.0, 1.0, 20.0)


@pytest.mark.parametrize(
    ("variable", "value"),
    [
        ("JOB_LEASE_S", "2"),
        ("JOB_LEASE_S", "3601"),
        ("JOB_POLL_S", "0"),
        ("JOB_POLL_S", "61"),
        ("JOB_SHUTDOWN_GRACE_S", "-1"),
        ("JOB_SHUTDOWN_GRACE_S", "3601"),
    ],
)
def test_the_worker_s_times_are_bounded(monkeypatch: pytest.MonkeyPatch, variable: str, value: str) -> None:
    monkeypatch.setenv("DATABASE_URL", FAKE_URL)
    monkeypatch.setenv(variable, value)

    with pytest.raises(ValidationError, match=variable.lower()):
        Settings()


def test_the_pool_cannot_be_smaller_than_its_minimum(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("DATABASE_URL", FAKE_URL)
    monkeypatch.setenv("DB_POOL_MIN_SIZE", "5")
    monkeypatch.setenv("DB_POOL_MAX_SIZE", "4")

    with pytest.raises(ValidationError, match="db_pool_max_size"):
        Settings()


def test_the_ontology_folder_defaults_to_the_repository_copy(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("DATABASE_URL", FAKE_URL)

    assert (Settings().ontology_dir / "ontologie" / "cur-kern.ttl").is_file()


@pytest.mark.parametrize(
    ("url", "secret"),
    [
        ("postgresql://curricarta:Fake%zzPass@127.0.0.1:1/curricarta", "Fake"),
        ("postgresql://curricarta:Pw123invented@[::1/curricarta", "Pw123invented"),
        ("postgresql://curricarta:ab@cdinvented@127.0.0.1:1/curricarta", "cdinvented"),
        ("host=127.0.0.1 password='unclosed-invented", "unclosed-invented"),
    ],
    ids=["bad-percent", "bad-bracket", "unencoded-at", "unclosed-quote"],
)
def test_a_malformed_database_url_is_refused_without_quoting_it(
    monkeypatch: pytest.MonkeyPatch, url: str, secret: str
) -> None:
    # libpq's own parse errors quote the string, password included
    monkeypatch.setenv("DATABASE_URL", url)

    with pytest.raises(ValidationError, match="database_url") as caught:
        Settings()

    assert secret not in str(caught.value)


@pytest.mark.parametrize(
    "url",
    [
        "postgresql://curricarta:se/cretinvented@127.0.0.1:1/curricarta",
        "postgresql://curricarta:a:b/cinvented@127.0.0.1:1/curricarta",
    ],
    ids=["slash", "colon-and-slash"],
)
def test_an_unencoded_slash_in_the_password_is_refused(monkeypatch: pytest.MonkeyPatch, url: str) -> None:
    # it splits the URL anew without an error: the rest of the password became the database name
    monkeypatch.setenv("DATABASE_URL", url)

    with pytest.raises(ValidationError, match="database_url") as caught:
        Settings()

    assert "invented" not in str(caught.value)


def test_a_connection_string_with_an_undecodable_byte_is_refused_without_it() -> None:
    # an environment byte Linux cannot decode arrives as a lone surrogate
    with pytest.raises(ValidationError, match="database_url") as caught:
        make_settings(database_url="postgresql://curricarta:pw" + chr(0xDCFF) + "@127.0.0.1:1/curricarta")

    assert "position" not in str(caught.value)
    assert "dcff" not in str(caught.value).lower()


@pytest.mark.parametrize(
    "url",
    [
        "postgresql://curricarta:12/cinvented@db/curricarta",
        "postgresql://curricarta:x/?sslmode=invented@db/curricarta",
    ],
    ids=["database-name-check", "port-check"],
)
def test_each_split_url_check_holds_alone(monkeypatch: pytest.MonkeyPatch, url: str) -> None:
    monkeypatch.setenv("DATABASE_URL", url)

    with pytest.raises(ValidationError, match="database_url"):
        Settings()


@pytest.mark.parametrize(
    "url",
    [
        "postgresql://curricarta:pw@db/my%40db",
        "host=db port=' 5432' dbname=curricarta",
        "postgresql:///curricarta?host=@abstract-socket",
        "postgresql://curricarta:pw@host1:5432,host2:5433/curricarta",
        "postgresql://curricarta:pw@[::1]:5432/curricarta",
    ],
    ids=["at-in-database-name", "padded-port", "abstract-socket", "two-hosts", "ipv6"],
)
def test_urls_libpq_reads_as_meant_are_taken(monkeypatch: pytest.MonkeyPatch, url: str) -> None:
    monkeypatch.setenv("DATABASE_URL", url)

    assert Settings().database_url.get_secret_value() == url


def test_visitors_get_nothing_and_sign_ins_are_limited_by_default(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("DATABASE_URL", FAKE_URL)

    settings = Settings()

    assert (settings.public_access, settings.auth_failure_limit, settings.api_key_pepper) == ("off", 10, None)


def test_a_short_pepper_is_refused_without_quoting_it(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("DATABASE_URL", FAKE_URL)
    monkeypatch.setenv("API_KEY_PEPPER", "short-invented")

    with pytest.raises(ValidationError, match="api_key_pepper") as caught:
        Settings()

    assert "short-invented" not in str(caught.value)


def test_only_the_local_proxy_is_trusted_by_default(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("DATABASE_URL", FAKE_URL)

    assert Settings().forwarded_allow_ips == "127.0.0.1,::1"


@pytest.mark.parametrize(
    "value", ["*", "10.0.0.0/8,*", "not-an-address", "", "0.0.0.0/0", "::/0", "10.42.1.5/16"]
)
def test_trusting_every_proxy_or_a_wrong_address_is_refused(
    monkeypatch: pytest.MonkeyPatch, value: str
) -> None:
    # with * every client could name its own address in X-Forwarded-For and dodge the limit
    monkeypatch.setenv("DATABASE_URL", FAKE_URL)
    monkeypatch.setenv("FORWARDED_ALLOW_IPS", value)

    with pytest.raises(ValidationError, match="forwarded_allow_ips"):
        Settings()


def test_proxy_networks_are_taken(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("DATABASE_URL", FAKE_URL)
    monkeypatch.setenv("FORWARDED_ALLOW_IPS", "10.42.0.0/16, fd00::/8")

    assert Settings().forwarded_allow_ips == "10.42.0.0/16,fd00::/8"


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


def test_x4_asks_four_units_at_once_by_default() -> None:
    assert make_settings().extract_concurrency == 4


@pytest.mark.parametrize("value", [1, 16])
def test_x4_asks_one_to_sixteen_units_at_once(value: int) -> None:
    assert make_settings(extract_concurrency=value).extract_concurrency == value


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
