"""The versions of what the Kern builders write (plan M3a, audit 2026-11-14 follow-up): KERN_GRAPH_VERSION,
which X5 records with each check (app/db/runs.py), and KERN_EXPORT, which names the kept exports
(app/exports/kern_export.py). Each is pinned to a digest of the source that decides what it versions - its
syntax tree, without docstrings, comments and the version's own line -, so a change of what is written
without a new version turns a test here red.

A red test here: bump the version beside the builder, then pin the new digest under the new version.
Never pin a version again: its checks (X5) and its kept files stand for the old source. The syntax tree is
Python's own, so a new minor version of Python may change every digest at once without a change of the
source: then pin the digests anew under the versions they stand for.
"""

import ast
import hashlib
import inspect
from types import ModuleType

from app.exports import kern_child, kern_naming, kern_rdf, kern_rows
from app.exports.kern_child import KERN_EXPORT
from app.exports.kern_rdf import KERN_GRAPH_VERSION

# what the graph X5 checks is made of: the rows read, and the triples written of them
# (the rows read for the file's head count too: a column read for it alone is a new version as well)
GRAPH_DIGESTS = {1: "c7e87a404943270f9d32ad0fb8788b4132fe809bed8833d9a2cbc5b94163f515"}
# what the kept file is made of beside the graph: its head, its blank nodes' labels, the frozen naming
EXPORT_DIGESTS = {
    "kern-ttl/1": "27e298e01744e2298e4e59681718e411f5f7991335462d7042896437966ae011",
    "kern-ttl/2": "d2653ec27b33ba77eb8c4315c016d581d03aee1b2d367b96206cf60640703840",  # the graph's version
}
_VERSIONS = frozenset({"KERN_GRAPH_VERSION", "KERN_EXPORT"})


def source_digest(*modules: ModuleType) -> str:
    """The digest of the modules' syntax trees, without docstrings and without the versions' lines."""
    return tree_digest(*map(inspect.getsource, modules))


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


def test_the_graph_s_version_names_the_builder_x5_checks_with() -> None:
    assert max(GRAPH_DIGESTS) == KERN_GRAPH_VERSION
    assert source_digest(kern_rows, kern_rdf) == GRAPH_DIGESTS[KERN_GRAPH_VERSION]


def test_the_export_s_version_names_what_the_kept_file_adds_to_the_graph() -> None:
    assert list(EXPORT_DIGESTS)[-1] == KERN_EXPORT
    assert source_digest(kern_child, kern_naming) == EXPORT_DIGESTS[KERN_EXPORT]


def test_a_docstring_or_a_comment_is_no_change_of_what_is_written() -> None:
    plain = "X = 1\n\n\ndef made():\n    return X\n"
    told = '"""A module."""\n\nX = 1  # one\n\n\ndef made():\n    """One."""\n    return X\n'
    other = "X = 2\n\n\ndef made():\n    return X\n"

    assert tree_digest(plain) == tree_digest(told) != tree_digest(other)
