"""``python -m app.sources.mem.amend_licence IRI`` (plan M2-6, E14): the arguments are checked before
anything is read - an https IRI, one alone; the amendment itself is app/db/mem_plans.amend_licence's."""

import psycopg
import pytest
from pydantic import ValidationError

from app.sources.mem import amend_licence
from app.sources.mem.amend_licence import main
from tests.support import make_settings

# main configures the process's logging, also the filters of pytest's handlers, which outlive the test
pytestmark = pytest.mark.usefixtures("restore_logging")


@pytest.mark.parametrize(
    "arguments",
    [[], ["https://a.example/1", "https://a.example/2"], ["CC BY-SA 4.0"], ["http://a.example/1"],
     ["https://a.example/a b"]],
    ids=["none", "two", "no-iri", "no-https", "unstorable"],
)  # fmt: skip
def test_a_licence_that_is_no_https_iri_is_refused_before_anything_is_read(arguments: list[str]) -> None:
    assert main(arguments) == 1


def test_the_setting_takes_an_https_iri_or_nothing() -> None:
    licence = "https://creativecommons.org/licenses/by-sa/4.0/"

    assert make_settings(mem_data_licence=licence).mem_data_licence == licence
    assert make_settings().mem_data_licence == ""
    for refused in ("CC BY-SA 4.0", "https://a.example/\x01", "https://a.example/\x60"):
        with pytest.raises(ValidationError):
            make_settings(mem_data_licence=refused)


LICENCE = "https://creativecommons.org/licenses/by-sa/4.0/"


def test_the_licence_goes_into_imports_and_catalogue_and_says_how_many(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    taken: list[str] = []

    async def amended(_: object, licence: str) -> tuple[int, int]:
        taken.append(licence)
        return 2, 5

    monkeypatch.setattr(
        amend_licence, "Settings", lambda: make_settings(mem_data_licence=LICENCE)
    )  # never the env's
    monkeypatch.setattr(amend_licence, "amend", amended)

    assert main([LICENCE]) == 0
    assert taken == [LICENCE] and capsys.readouterr().out.split() == ["2", "5"]


def test_a_database_away_amends_nothing_and_says_so(monkeypatch: pytest.MonkeyPatch) -> None:
    async def away(*_: object) -> tuple[int, int]:
        raise psycopg.OperationalError("no connection")

    monkeypatch.setattr(amend_licence, "Settings", lambda: make_settings(mem_data_licence=LICENCE))
    monkeypatch.setattr(amend_licence, "amend", away)

    assert main([LICENCE]) == 1


def test_a_licence_the_setting_does_not_name_is_refused(monkeypatch: pytest.MonkeyPatch) -> None:
    # set MEM_DATA_LICENCE first: else the catalogue and earlier imports would name two licences
    asked: list[str] = []

    async def amended(_: object, licence: str) -> tuple[int, int]:
        asked.append(licence)
        return 0, 0

    monkeypatch.setattr(amend_licence, "Settings", make_settings)
    monkeypatch.setattr(amend_licence, "amend", amended)

    assert main([LICENCE]) == 1 and asked == []
