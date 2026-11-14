"""The SHACL check in the test's own process, for tests of what X5, the repair and the MEM export do with
its results rather than of the check: each start of the check's child and its parse of the model took
seconds per test.

``shacl_in_process`` has ``shacl_check``'s signature and result type. It runs the function the child runs
(``validate_graph``) with the same options, on the graph as the child reads it (N-Triples written and read
back), in a thread - as the product writes the child's file, so the loop keeps turning - within the same
deadline. A validation that raises comes back as the child's does, through the check's own reading of a
child's answer: ShaclCrashed, naming the error's kind. Only the reading of the model and the shapes is
kept for the session (``parsed_once``). tests/pipeline/test_shacl_in_process.py holds that both ways give
the same results; tests/pipeline/test_shacl.py tests the check and its child.

Not covered, as no switched test relies on it: past its deadline the thread is not killed as the child
is - it runs on, holding the lock and rdflib's swapped query method, until its validation ends; and the
child's logging set-up is not made - pyshacl puts a handler of its own on its logger in the test's
process, as test_shacl.py's in-process validations did before.
"""

import asyncio
import functools
import json
import shutil
import tempfile
import threading
from pathlib import Path

from rdflib import Graph

from app.core.child import ChildLog, write
from app.pipeline import shacl, shacl_child
from app.pipeline.shacl import ShaclTimeout
from app.pipeline.shacl_child import ShaclResult, ShapeSet, validate_graph

_parse = shacl_child._parsed
# one validation at a time, as each child has a process of its own: validate_graph swaps a method of
# rdflib's SPARQL processor for its run (two at once would leave one swapped), and pyshacl adds to the
# shapes graph that is kept here
_ONE_AT_A_TIME = threading.Lock()


@functools.cache
def _parsed_paths(paths: tuple[Path, ...]) -> Graph:
    return _parse(list(paths))


def parsed_once(paths: list[Path]) -> Graph:
    """``_parsed``, read once per session for each list of files (a failed read is not kept). pyshacl adds
    its system triples to the shapes graph it is given, the same ones each time; the model is copied into
    each data graph."""
    return _parsed_paths(tuple(paths))


def _validated(graph: Graph, ontology_dir: Path, shapes: ShapeSet, told: ChildLog) -> list[ShaclResult]:
    data = Graph().parse(data=graph.serialize(format="nt", encoding="utf-8"), format="nt")
    with _ONE_AT_A_TIME:
        try:
            return validate_graph(ontology_dir, data, shapes)
        except Exception as error:
            return _as_the_child_answers(error, told)


def _as_the_child_answers(error: Exception, told: ChildLog) -> list[ShaclResult]:
    """The error as the child leaves it (shacl_child.run_child), read as the check reads a child's answer."""
    out = Path(tempfile.mkdtemp(prefix="shacl-in-process-"))
    try:
        write(out / "crashed.json", json.dumps({"error": type(error).__name__}))
        return shacl._outcome(told, 1, out)
    finally:
        shutil.rmtree(out, ignore_errors=True)


async def shacl_in_process(
    graph: Graph, *, ontology_dir: Path, timeout_s: float, told: ChildLog, shapes: ShapeSet = "kern"
) -> list[ShaclResult]:
    """``shacl_check`` without its child: the same validation and results, in a thread."""
    try:
        async with asyncio.timeout(timeout_s):
            return await asyncio.to_thread(_validated, graph, ontology_dir, shapes, told)
    except TimeoutError:
        raise ShaclTimeout(f"the SHACL validation took longer than {timeout_s} s") from None
