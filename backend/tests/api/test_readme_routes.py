"""The README names every operation of the API: each method and path of the OpenAPI schema stands there - the
path in full or as its tail after ``/api/v1``, written as a code span, after the prefix or after a method, its
parameters in braces whatever their names, and its method within the few words before it
(``PATCH /api/v1/nodes/{id}`` and ``/statements/{id}`` names both). A new route the README does not name, or
a new method on a path it names for another, turns this red, so it is written where the editors and the
operators read the routes. An operation the README names otherwise would stand in ``OTHERWISE``, with where
it does; none does now."""

import re
from pathlib import Path

from app.api.app import create_app
from tests.support import make_settings

README = Path(__file__).resolve().parents[3] / "README.md"
BEFORE = 40  # characters before the path the method stands within
# (method, path): where the README names the operation without its method and path
OTHERWISE: set[tuple[str, str]] = set()


def _braced(text: str) -> str:
    return re.sub(r"\{[^}]*\}", "{}", text)


def unnamed(readme: str, paths: dict[str, dict[str, object]]) -> set[tuple[str, str]]:
    """The operations the README does not name by their method and path."""
    text = _braced(re.sub(r"\s+", " ", readme))
    missing = set()
    for path, operations in paths.items():
        tail = _braced(path).removeprefix("/api/v1")
        at_path = r"(?:/api/v1|`|\b(?:GET|POST|PUT|PATCH|DELETE) )" + re.escape(tail) + r"(?=[`?\s,)])"
        named = [found.end() - len(tail) for found in re.finditer(at_path, text)]  # where the tail starts
        for method in (each.upper() for each in operations):
            if not any(re.search(rf"\b{method}\b", text[max(0, at - BEFORE) : at]) for at in named):
                missing.add((method, path))
    return missing


def test_the_readme_names_every_operation_of_the_api() -> None:
    paths = create_app(make_settings()).openapi()["paths"]

    assert unnamed(README.read_text(encoding="utf-8"), paths) == OTHERWISE


def test_an_operation_named_neither_by_its_path_nor_by_its_method_is_found() -> None:
    paths: dict[str, dict[str, object]] = {
        "/api/v1/a/{a_id}/b": {"get": {}, "put": {}},
        "/api/v1/c/{c_id}": {"post": {}},
        "/api/v1/d": {"get": {}},
    }
    readme = "`GET /api/v1/a/{id}/b` and, wrapped, `POST\n  /c/{id}` (a word); /api/v1/dd is another"

    assert unnamed(readme, paths) == {("PUT", "/api/v1/a/{a_id}/b"), ("GET", "/api/v1/d")}
