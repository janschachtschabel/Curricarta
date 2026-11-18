"""The settings of the service's frame (app/core/settings_service.py): the database, the server, who may
come in, the worker's times. Invented values only, as in test_settings.py."""

import pytest
from pydantic import ValidationError

from app.core.settings import Settings
from tests.core.test_settings import no_settings_variables
from tests.support import FAKE_DATABASE_URL as FAKE_URL
from tests.support import make_settings

__all__ = ["no_settings_variables"]  # the fixture, shared with test_settings


@pytest.mark.parametrize("level", ["LOUD", "", "info "])
def test_an_unknown_log_level_is_refused(monkeypatch: pytest.MonkeyPatch, level: str) -> None:
    monkeypatch.setenv("DATABASE_URL", FAKE_URL)
    monkeypatch.setenv("LOG_LEVEL", level)

    with pytest.raises(ValidationError, match="log_level"):
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
