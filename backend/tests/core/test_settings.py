"""Settings come from the environment; secrets may come from a file named by <NAME>_FILE.

Only invented values are used here: a settings object built from the real environment
would read real keys, and pydantic would print them in a validation error. The settings of each
part are tested beside: test_settings_service.py, test_settings_work.py.
"""

from collections.abc import Iterator
from pathlib import Path
from typing import Annotated

import pytest
from pydantic import Field, SecretStr, ValidationError

from app.core.secret_files import environment_value
from app.core.settings import Settings
from tests.support import FAKE_DATABASE_URL as FAKE_URL
from tests.support import without_settings_variables


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


def test_a_file_variable_is_found_in_any_case_on_a_case_sensitive_environment() -> None:
    # Windows' environment ignores case anyway; Linux' does not
    environment = {"database_url_file": "/run/secrets/lower", "OTHER_FILE": "/x"}

    assert environment_value("DATABASE_URL_FILE", environment) == "/run/secrets/lower"
    assert environment_value("DATABASE_URL_FILE", {"DATABASE_URL_FILE": "/exact"}) == "/exact"
    assert environment_value("DATABASE_URL_FILE", {}) is None


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
