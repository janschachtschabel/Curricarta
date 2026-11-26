"""The versions of the Kern builders and of X5's check (plan M3a): KERN_GRAPH_VERSION, which X5 records
with each check (app/db/runs.py) - the graph the builder writes and how X5 validates it -, and KERN_EXPORT,
which names the kept exports (app/exports/kern_export.py). Each is pinned to a digest of what decides what
it versions - the modules' syntax trees, without docstrings, comments and the version's own line; for the
graph's version also the shape files and model files X5 validates by and the pinned pyshacl's version -,
so a change of what is written or checked without a new version turns a test here red.

A red test here: bump the version beside the builder, then pin the new digest under the new version.
Never pin a version again: its checks (X5) and its kept files stand for the old source. A change of the
check alone - a shape, a vocabulary, pyshacl, any line of shacl_child.py, its logging too - is a new graph
version as well: every draft is owed a check anew, and the kept exports' fingerprint (kern_export.py)
moves, so a frozen file is built anew and says it was checked under the old version, built with the new,
though its graph is the same. The syntax tree is Python's own, so a new minor version of Python may change
every digest at once without a change of the source: then pin the digests anew under the versions they
stand for.
"""

import ast
import hashlib
import inspect
import shutil
import sys
from importlib.metadata import version
from pathlib import Path
from types import ModuleType

import pytest

from app.db import assessment_rows, rule_rows, value_rows
from app.exports import (
    kern_assessments,
    kern_child,
    kern_naming,
    kern_rdf,
    kern_rows,
    kern_rules,
    kern_scope,
    kern_values,
)
from app.exports.kern_child import KERN_EXPORT
from app.exports.kern_rdf import KERN_GRAPH_VERSION
from app.pipeline import shacl_child
from app.pipeline.shacl_child import SHAPE_FILES, model_paths
from app.vocab.loader import MODEL_DIRS

# what the graph X5 checks is made of: the rows read, and the triples written of them - of the values too
# (the rows read for the file's head count too: a column read for it alone is a new version as well)
# value_rows: how the values are read; kern_scope: a specification's applicability (plan M3a H1); rule_rows,
# kern_rules: how the rules are read and written (plan M3a I)
# shacl_child: how X5 validates the graph - the version X5 records says what was checked, and a check by
# another validator is another check (a draft checked while every value's vocabulary went unchecked, audit
# 2026-11-14, is owed one); beside it the files and the checker it validates by (check_digest). Not held:
# rdflib and owlrl, on which pyshacl runs (the kept exports' fingerprint holds rdflib's version)
# rule_rows, kern_rules: the rules read and stated (plan M3a I); assessment_rows, kern_assessments: the
# assessments read and stated (plan M3a J)
GRAPH_MODULES = (
    kern_rows, value_rows, kern_rdf, kern_values, kern_scope, shacl_child, rule_rows, kern_rules,
    assessment_rows, kern_assessments,
)  # fmt: skip
ONTOLOGY = Path(__file__).resolve().parents[3] / "ontology"
GRAPH_DIGESTS = {
    1: "c7e87a404943270f9d32ad0fb8788b4132fe809bed8833d9a2cbc5b94163f515",
    2: "8f9b27919fa004d4e2fc31c6796476430409a883523bead68d836dbd9f0850ad",  # the values (plan M3a F1)
    3: "a6d616c76fe83efc1b11e899dff686ef4f3f85dec580ff830e010e538941945e",  # applicability (plan M3a H1)
    # the check beside the graph: the validator, its shape and model files, pyshacl (check_digest); it
    # checks a value's vocabulary and the blank nodes (audit 2026-11-14)
    4: "6dbfbedd032e339397787aef67489b09861a13d59efa4f2fbfca48326e4348ac",
    5: "da1497e0c0852006704316af78a65a1c146cf11500ac10907b00bf4245b0ad36",  # rules (plan M3a I)
    6: "508974a782d6bcff5feef944081de0d8a31ebf135326fc4345982561831bd041",  # assessments (plan M3a J)
}
# what the kept file is made of beside the graph: its head, its blank nodes' labels, the frozen naming
EXPORT_DIGESTS = {
    "kern-ttl/1": "27e298e01744e2298e4e59681718e411f5f7991335462d7042896437966ae011",
    "kern-ttl/2": "d2653ec27b33ba77eb8c4315c016d581d03aee1b2d367b96206cf60640703840",  # the graph's version
    "kern-ttl/3": "7b86aae1ff4c6ada4205560198ce783cb6d53302e7a4c70ce939927584ae423e",  # value kinds
    "kern-ttl/4": "89c8fb757df5f3c45dcd26bc6e095ba51904fe10152a00ec26e9c7e1a94332d1",  # contexts
    "kern-ttl/5": "6e4da7a2e72c3b406d16824ededcdf2079d9ab7c954a2558b35b17d419efee04",  # rules named by IRI
    "kern-ttl/6": "b4f86ca5b266acd78b682f4ff63ff58cd5a34c90d6b72695878a6f38c6b7ab18",  # assessments by IRI
}
_VERSIONS = frozenset({"KERN_GRAPH_VERSION", "KERN_EXPORT"})


def source_digest(*modules: ModuleType) -> str:
    """The digest of the modules' syntax trees, without docstrings and without the versions' lines."""
    return tree_digest(*map(inspect.getsource, modules))


def check_digest() -> str:
    """The digest of the graph's modules, the files X5 validates by - the shape files and the model files it
    loads, line ends as git keeps them - and the pinned pyshacl's version, as the MEM gate's fingerprint
    holds its own (app/exports/mem_export.py)."""
    digest = hashlib.sha256(source_digest(*GRAPH_MODULES).encode())
    digest.update(b"\x00" + version("pyshacl").encode())
    names = {path.relative_to(ONTOLOGY).as_posix() for path in model_paths(ONTOLOGY)} | set(SHAPE_FILES)
    for name in sorted(names):  # by name, as on every system (a Windows path sorts without case)
        digest.update(b"\x00" + name.encode() + b"\x00")
        digest.update((ONTOLOGY / name).read_bytes().replace(b"\r\n", b"\n"))
    return digest.hexdigest()


def tree_digest(*sources: str) -> str:
    """The digest of the sources' syntax trees, as ``source_digest`` says."""
    digest = hashlib.sha256()
    for source in sources:
        tree = ast.parse(source)
        for node in ast.walk(tree):
            if isinstance(node, ast.Module | ast.ClassDef | ast.FunctionDef | ast.AsyncFunctionDef):
                first = node.body[0] if node.body else None
                if isinstance(first, ast.Expr) and isinstance(first.value, ast.Constant):
                    node.body = node.body[1:] or [ast.Pass()]
        tree.body = [statement for statement in tree.body if not _versions(statement)]
        digest.update(ast.dump(tree).encode())
    return digest.hexdigest()


def _versions(statement: ast.stmt) -> bool:
    targets = statement.targets if isinstance(statement, ast.Assign) else []
    return any(isinstance(target, ast.Name) and target.id in _VERSIONS for target in targets)


def test_the_graph_s_version_names_the_builder_and_the_check_x5_records() -> None:
    assert max(GRAPH_DIGESTS) == KERN_GRAPH_VERSION
    assert check_digest() == GRAPH_DIGESTS[KERN_GRAPH_VERSION]


def test_another_pyshacl_or_another_shape_file_is_another_check(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    here = sys.modules[__name__]
    pinned = check_digest()
    with monkeypatch.context() as patched:
        patched.setattr(here, "version", lambda _: "0.0.0")
        other_checker = check_digest()
    for folder in MODEL_DIRS:
        shutil.copytree(ONTOLOGY / folder, tmp_path / folder)
    monkeypatch.setattr(here, "ONTOLOGY", tmp_path)
    assert check_digest() == pinned  # the copy is no change
    shapes = tmp_path / SHAPE_FILES[0]
    shapes.write_bytes(shapes.read_bytes() + b"\n# changed\n")

    assert pinned not in {other_checker, check_digest()}


def test_the_export_s_version_names_what_the_kept_file_adds_to_the_graph() -> None:
    assert list(EXPORT_DIGESTS)[-1] == KERN_EXPORT
    assert source_digest(kern_child, kern_naming) == EXPORT_DIGESTS[KERN_EXPORT]


def test_a_docstring_or_a_comment_is_no_change_of_what_is_written() -> None:
    plain = "X = 1\n\n\ndef made():\n    return X\n"
    told = '"""A module."""\n\nX = 1  # one\n\n\ndef made():\n    """One."""\n    return X\n'
    other = "X = 2\n\n\ndef made():\n    return X\n"

    assert tree_digest(plain) == tree_digest(told) != tree_digest(other)
