"""A fixture that asks for preloaded_vocabulary gets a database holding the ontology's vocabulary
already: its own load must be its first write, of that vocabulary, with the result unused."""

import ast
from pathlib import Path

TESTS = Path(__file__).resolve().parent
MARKER = "preloaded_vocabulary"


def _is_fixture(function: ast.FunctionDef | ast.AsyncFunctionDef) -> bool:
    return any("fixture" in ast.unparse(decorator) for decorator in function.decorator_list)


def _bare_call(statement: ast.stmt, name: str) -> ast.Call | None:
    if (
        isinstance(statement, ast.Expr)
        and isinstance(statement.value, ast.Call)
        and isinstance(statement.value.func, ast.Name)
        and statement.value.func.id == name
    ):
        return statement.value
    return None


def _loads_the_ontology_first(function: ast.FunctionDef | ast.AsyncFunctionDef) -> bool:
    body = function.body
    if body and isinstance(body[0], ast.Expr) and isinstance(body[0].value, ast.Constant):
        body = body[1:]  # the docstring
    for statement in body:
        if _bare_call(statement, "migrate") is not None:
            continue
        load = _bare_call(statement, "load_vocabulary")
        if load is None or len(load.args) != 2 or load.keywords:
            return False
        vocabulary = load.args[1]
        return (
            isinstance(vocabulary, ast.Call)
            and isinstance(vocabulary.func, ast.Name)
            and vocabulary.func.id == "ontology_vocabulary"
            and not vocabulary.args
            and not vocabulary.keywords
        )
    return False


def _marker_fixtures() -> list[tuple[Path, ast.FunctionDef | ast.AsyncFunctionDef]]:
    found = []
    for path in sorted(TESTS.rglob("*.py")):
        for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"), filename=str(path))):
            if (
                isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
                and _is_fixture(node)
                and any(argument.arg == MARKER for argument in node.args.args + node.args.kwonlyargs)
            ):
                found.append((path, node))
    return found


def test_the_marker_fixtures_load_the_ontology_before_anything_else() -> None:
    fixtures = _marker_fixtures()
    assert fixtures, f"no fixture asks for {MARKER}: the guard would check nothing"
    broken = [
        f"{path.relative_to(TESTS).as_posix()}::{function.name}"
        for path, function in fixtures
        if not _loads_the_ontology_first(function)
    ]
    assert not broken, (
        f"these fixtures ask for {MARKER} but do not start with nothing but migrate(...) calls and then "
        f"a bare load_vocabulary(<url>, ontology_vocabulary()): {broken}"
    )
