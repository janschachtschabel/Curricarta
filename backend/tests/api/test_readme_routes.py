"""The README names every route of the API: each operation of the OpenAPI schema stands there by its path - in
full or as its tail after ``/api/v1``, written as a code span or after the prefix -, its parameters in
braces whatever their names. A new route the README does not name turns this red, so it is written where
the editors and the operators read the routes. The few the README names otherwise stand in ``OTHERWISE``,
each with where it does."""

import re
from pathlib import Path

from app.api.app import create_app
from tests.support import make_settings

README = Path(__file__).resolve().parents[3] / "README.md"
# (method, path): where the README names the operation without its path
OTHERWISE = {
    # read after the conversion's start, as `GET …/conversion` and `GET …/conversion/blocks`
    ("GET", "/api/v1/sources/{source_id}/conversion"),
    ("GET", "/api/v1/sources/{source_id}/conversion/blocks"),
}


def _braced(text: str) -> str:
    return re.sub(r"\{[^}]*\}", "{}", text)


def unnamed(readme: str, paths: dict[str, dict[str, object]]) -> set[tuple[str, str]]:
    """The operations whose path the README does not name."""
    text = _braced(re.sub(r"\s+", " ", readme))
    missing = set()
    for path, operations in paths.items():
        tail = _braced(path).removeprefix("/api/v1")
        if not re.search(r"(?:/api/v1|`)" + re.escape(tail) + r"(?=[`?\s,)])", text):
            missing |= {(method.upper(), path) for method in operations}
    return missing


def test_the_readme_names_every_route_of_the_api() -> None:
    paths = create_app(make_settings()).openapi()["paths"]

    assert unnamed(README.read_text(encoding="utf-8"), paths) == OTHERWISE


def test_a_route_named_neither_in_full_nor_by_its_tail_is_found() -> None:
    paths: dict[str, dict[str, object]] = {
        "/api/v1/a/{a_id}/b": {"get": {}, "put": {}},
        "/api/v1/c/{c_id}": {"post": {}},
        "/api/v1/d": {"get": {}},
    }
    readme = "`GET /api/v1/a/{id}/b` and, wrapped,\n  `/c/{id}` (a word); /api/v1/dd is another"

    assert unnamed(readme, paths) == {("GET", "/api/v1/d")}
