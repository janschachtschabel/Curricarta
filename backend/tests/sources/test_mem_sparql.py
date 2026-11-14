"""The client of the MEM endpoint (app/sources/mem/sparql.py, plan M2 E11): SELECT over POST, JSON results as
plain strings, the graphs it may read named, an IRI written into a query only once checked, an answer read
up to its limit and in pages checked against their count; never a redirect, never the environment's proxy.
A mock transport stands in for the endpoint."""

import asyncio
import gzip
import json
from collections.abc import AsyncIterator
from typing import Any
from urllib.parse import parse_qs

import httpx2
import pytest

from app.sources.mem.sparql import (
    GRAPHS,
    KMK_GRAPH,
    SHARED_GRAPHS,
    MemEndpoint,
    MemRefused,
    MemSparql,
    MemUnavailable,
    mem_iri,
)
from app.sources.url_fetch import HostNotResolved, HostRefused

pytestmark = pytest.mark.anyio
URL = "https://sparql.example.invalid/sparql"
RP = "https://w3id.org/lehrplan/rp"


def answer(rows: list[dict[str, str]], status: int = 200) -> httpx2.Response:
    bindings = [{key: {"type": "literal", "value": value} for key, value in row.items()} for row in rows]
    body = json.dumps(
        {"head": {"vars": sorted({key for row in rows for key in row})}, "results": {"bindings": bindings}}
    )
    return httpx2.Response(
        status, content=body.encode(), headers={"content-type": "application/sparql-results+json"}
    )


def client(handler: Any, max_bytes: int = 1_000_000) -> MemSparql:
    return MemSparql(
        MemEndpoint(URL, timeout_s=5, max_bytes=max_bytes), transport=httpx2.MockTransport(handler)
    )


async def test_a_select_is_posted_as_a_form_and_its_rows_are_plain_strings() -> None:
    asked: list[httpx2.Request] = []

    def handler(request: httpx2.Request) -> httpx2.Response:
        asked.append(request)
        return answer([{"plan": "https://w3id.org/x", "n": "3"}])

    rows = await client(handler).select("SELECT ?plan ?n WHERE { ?plan ?p ?n }")

    assert rows == [{"plan": "https://w3id.org/x", "n": "3"}]
    assert asked[0].method == "POST"
    assert parse_qs(asked[0].content.decode())["query"] == ["SELECT ?plan ?n WHERE { ?plan ?p ?n }"]
    assert asked[0].headers["accept"] == "application/sparql-results+json"


@pytest.mark.parametrize("status", [429, 500, 502, 503, 504])
async def test_a_busy_or_failing_endpoint_is_unavailable_for_now(status: int) -> None:
    with pytest.raises(MemUnavailable):
        await client(lambda request: answer([], status)).select("SELECT * WHERE { ?s ?p ?o }")


async def test_an_endpoint_out_of_reach_is_unavailable_for_now() -> None:
    def handler(request: httpx2.Request) -> httpx2.Response:
        raise httpx2.ConnectError("refused", request=request)

    with pytest.raises(MemUnavailable):
        await client(handler).select("SELECT * WHERE { ?s ?p ?o }")


@pytest.mark.parametrize(
    "response",
    [
        httpx2.Response(400, content=b"syntax error"),
        httpx2.Response(302, headers={"location": "https://elsewhere.example.invalid/"}),
        httpx2.Response(200, content=b"<html>not json</html>"),
        httpx2.Response(200, content=b'{"results": {}}'),
    ],
    ids=["refused-query", "redirect", "not-json", "no-bindings"],
)
async def test_an_answer_the_client_cannot_take_is_refused(response: httpx2.Response) -> None:
    with pytest.raises(MemRefused):
        await client(lambda request: response).select("SELECT * WHERE { ?s ?p ?o }")


async def test_an_answer_past_the_limit_is_refused() -> None:
    rows = [{"n": "x" * 100} for _ in range(100)]

    with pytest.raises(MemRefused, match="limit"):
        await client(lambda request: answer(rows), max_bytes=1_000).select("SELECT ?n WHERE { ?n ?p ?o }")


@pytest.mark.parametrize(
    "iri",
    ["https://w3id.org/a b", "https://w3id.org/a>b", 'https://w3id.org/a"b', "https://w3id.org/a\x01b",
     "ftp://w3id.org/a", "w3id.org/a", "https://w3id.org/a{b}", "https://w3id.org/a\\b", "https://w3id.org/a|b",
     "https://w3id.org/a^b", "https://w3id.org/a`b", "https://w3id.org/a\x7fb", "https://w3id.org/a\nb",
     "https://w3id.org/" + "a" * 1984],
    ids=lambda iri: repr(iri[:24]) if len(iri) < 100 else "too-long",
)  # fmt: skip
def test_an_iri_that_could_break_out_of_its_brackets_is_refused(iri: str) -> None:
    with pytest.raises(MemRefused):
        mem_iri(iri)


def test_an_iri_of_two_thousand_signs_is_the_longest_taken() -> None:
    longest = "https://w3id.org/" + "a" * 1983

    assert len(longest) == 2000
    assert mem_iri(longest) == f"<{longest}>"


def test_an_iri_of_mem_is_written_in_its_brackets() -> None:
    assert mem_iri("https://w3id.org/lehrplan/instances/rp/resource/lehrplan-134-1") == (
        "<https://w3id.org/lehrplan/instances/rp/resource/lehrplan-134-1>"
    )


def test_a_query_reads_a_land_s_graph_and_the_shared_ones_alone() -> None:
    sparql = client(lambda request: answer([]))

    clauses = sparql.from_clauses(RP)

    assert clauses.splitlines() == [f"FROM <{graph}>" for graph in (*SHARED_GRAPHS, RP)]
    assert RP in GRAPHS
    with pytest.raises(MemRefused, match="graph"):
        sparql.from_clauses("https://w3id.org/lehrplan/rp/data")  # a part of the graph, not the graph


async def test_pages_are_read_until_their_count_is_reached() -> None:
    def handler(request: httpx2.Request) -> httpx2.Response:
        query = parse_qs(request.content.decode())["query"][0]
        if "COUNT" in query:
            return answer([{"count": "5"}])
        offset = int(query.rsplit("OFFSET ", 1)[1].split()[0])
        return answer([{"n": str(at)} for at in range(offset, min(offset + 2, 5))])

    rows = await client(handler).select_pages(
        lambda limit, offset: f"SELECT ?n WHERE {{ ?n ?p ?o }} LIMIT {limit} OFFSET {offset}",
        "SELECT (COUNT(*) AS ?count) WHERE { ?n ?p ?o }",
        page=2,
    )

    assert [row["n"] for row in rows] == ["0", "1", "2", "3", "4"]


async def test_pages_that_fall_short_of_their_count_are_refused() -> None:
    # Virtuoso cuts an answer at its row limit without a word: a page missing rows is no tree
    def handler(request: httpx2.Request) -> httpx2.Response:
        query = parse_qs(request.content.decode())["query"][0]
        if "COUNT" in query:
            return answer([{"count": "5"}])
        return answer([{"n": "0"}])  # always one row, a page of two asked

    with pytest.raises(MemRefused, match="count"):
        await client(handler).select_pages(
            lambda limit, offset: f"SELECT ?n WHERE {{ ?n ?p ?o }} LIMIT {limit} OFFSET {offset}",
            "SELECT (COUNT(*) AS ?count) WHERE { ?n ?p ?o }",
            page=2,
        )


async def test_an_answer_that_trickles_past_its_time_is_unavailable_for_now() -> None:
    # httpx2's timeout bounds each read alone: a chunk now and then would hold the job for ever
    async def trickle() -> AsyncIterator[bytes]:
        yield b'{"results": '
        await asyncio.sleep(5)
        yield b'{"bindings": []}}'

    sparql = MemSparql(
        MemEndpoint(URL, timeout_s=0.2),
        transport=httpx2.MockTransport(lambda request: httpx2.Response(200, content=trickle())),
    )

    with pytest.raises(MemUnavailable, match="time"):
        await asyncio.wait_for(sparql.select("SELECT * WHERE { ?s ?p ?o }"), 3)


@pytest.mark.parametrize(
    ("error", "expected"),
    [
        (HostNotResolved("sparql.example.invalid", transient=True), MemUnavailable),
        (HostNotResolved("sparql.example.invalid", transient=False), MemRefused),
        (HostRefused("sparql.example.invalid"), MemRefused),
    ],
    ids=["name-not-resolved-now", "name-unknown", "host-not-public"],
)
async def test_a_host_the_pinned_transport_cannot_reach_is_told_apart(
    error: Exception, expected: type[Exception]
) -> None:
    # the pinned transport raises these where it connects; httpx2 passes them on as they are
    def handler(request: httpx2.Request) -> httpx2.Response:
        raise error

    with pytest.raises(expected):
        await client(handler).select("SELECT * WHERE { ?s ?p ?o }")


async def test_a_transfer_cut_inside_its_compression_is_unavailable_for_now() -> None:
    whole = gzip.compress(answer([{"n": "x" * 2000}]).content)

    async def cut() -> AsyncIterator[bytes]:  # streamed, so that the client unpacks it, as off the wire
        yield whole[: len(whole) // 2]

    def handler(request: httpx2.Request) -> httpx2.Response:
        return httpx2.Response(200, headers={"Content-Encoding": "gzip"}, content=cut())

    with pytest.raises(MemUnavailable):
        await client(handler).select("SELECT * WHERE { ?s ?p ?o }")


@pytest.mark.parametrize(
    "body",
    [b'{"results": {"bindings": [["n"]]}}', b'{"results": {"bindings": {"n": {"value": "x"}}}}',
     b'{"results": {"bindings": [{"n": "x"}]}}', b"[]"],
    ids=["row-a-list", "bindings-a-dict", "value-no-dict", "no-object"],
)  # fmt: skip
async def test_bindings_of_another_shape_are_refused(body: bytes) -> None:
    with pytest.raises(MemRefused, match="SPARQL"):
        await client(lambda request: httpx2.Response(200, content=body)).select("SELECT * WHERE { ?s ?p ?o }")


async def test_an_answer_virtuoso_cut_at_its_time_is_unavailable_for_now() -> None:
    # Virtuoso's anytime mode answers 200 with what it found so far, and says so in a header alone
    def handler(request: httpx2.Request) -> httpx2.Response:
        cut = answer([{"count": "500"}])
        cut.headers["X-SQL-State"] = "S1TAT"
        return cut

    with pytest.raises(MemUnavailable, match="partial"):
        await client(handler).select("SELECT (COUNT(*) AS ?count) WHERE { ?s ?p ?o }")


async def test_the_client_asks_for_the_encodings_it_can_unpack_alone() -> None:
    asked: list[httpx2.Request] = []

    def handler(request: httpx2.Request) -> httpx2.Response:
        asked.append(request)
        return answer([])

    await client(handler).select("SELECT * WHERE { ?s ?p ?o }")

    assert asked[0].headers["accept-encoding"] == "gzip, deflate"


async def test_pages_past_their_count_are_refused() -> None:
    def handler(request: httpx2.Request) -> httpx2.Response:
        query = parse_qs(request.content.decode())["query"][0]
        if "COUNT" in query:
            return answer([{"count": "3"}])
        return answer([{"n": "0"}, {"n": "1"}, {"n": "2"}, {"n": "3"}])  # four rows on a page of four

    with pytest.raises(MemRefused, match="count"):
        await client(handler).select_pages(
            lambda limit, offset: f"SELECT ?n WHERE {{ ?n ?p ?o }} LIMIT {limit} OFFSET {offset}",
            "SELECT (COUNT(*) AS ?count) WHERE { ?n ?p ?o }",
            page=4,
        )


@pytest.mark.parametrize(
    "count", [[], [{"n": "3"}], [{"count": "three"}]], ids=["no-row", "no-count", "no-number"]
)
async def test_a_count_the_endpoint_did_not_give_is_refused(count: list[dict[str, str]]) -> None:
    with pytest.raises(MemRefused, match="count"):
        await client(lambda request: answer(count)).select_pages(
            lambda limit, offset: "SELECT ?n WHERE { ?n ?p ?o }",
            "SELECT (COUNT(*) AS ?count) WHERE { ?n ?p ?o }",
        )


@pytest.mark.parametrize("page", [0, -1])
async def test_a_page_of_no_rows_is_no_page(page: int) -> None:
    with pytest.raises(ValueError, match="page"):
        await client(lambda request: answer([{"count": "3"}])).select_pages(
            lambda limit, offset: "SELECT ?n WHERE { ?n ?p ?o }",
            "SELECT (COUNT(*) AS ?count) WHERE { ?n ?p ?o }",
            page=page,
        )


def test_the_standards_graph_is_one_the_client_reads() -> None:
    assert KMK_GRAPH == "https://w3id.org/lehrplan/graph/bista" and KMK_GRAPH in GRAPHS
