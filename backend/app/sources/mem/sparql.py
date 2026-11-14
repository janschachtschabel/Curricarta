"""The client of the MEM endpoint (plan M2, E11): SELECT queries over POST, their JSON results as plain
strings.

Only a job asks it (Gesamtplan §7.2). It reads the graphs GRAPHS names - a Land's or the standards' graph
with the three shared ones - and no other; the endpoint holds system graphs and older copies beside them.
An IRI is written into a query only through ``mem_iri``, which refuses whatever could leave its angle
brackets. An answer is read up to its limit and within its time, as a whole - httpx2's timeout bounds
each read alone -, never past a redirect or through the environment's proxy. Virtuoso's anytime mode
answers 200 with what it found in its time and says so in ``X-SQL-State`` alone; such an answer is not
taken.
Virtuoso cuts an answer at its row limit without a word, so a plan's parts are read in pages
(``select_pages``) and their number checked against a count.

MemUnavailable is for now - the endpoint out of reach, busy, failing, slow, its name not resolved now, a
transfer cut: a job asks again later.
MemRefused is for good - a query or graph refused, an endpoint that is not public or whose name does not
exist, an answer that is none, past its limit or short of its count: asking again changes nothing.
"""

import asyncio
import json
import re
from collections.abc import Callable
from dataclasses import dataclass

import httpx2

from app.sources.http_body import (
    ACCEPT_ENCODING,
    BodyTooLarge,
    BrokenCompression,
    UnsupportedEncoding,
    aread_body,
)
from app.sources.url_fetch import HostNotResolved, UrlNotAllowed, pinned_transport

USER_AGENT = "curricarta (MEM-Schule import)"
ONTOLOGY_GRAPH = "https://w3id.org/lehrplan/ontology/1.0.0rc3"
# the graphs a query reads beside a plan's: the ontology, the school types, the subjects
SHARED_GRAPHS = (ONTOLOGY_GRAPH, "https://w3id.org/schulart/1.0.0", "https://w3id.org/schulfach/1.0.0")
# a Land's or the standards' whole graph - its /data and /inferences graphs are parts of it (measured
# 2026-11-09: Berlin's /data holds 4 of 68 parts); the endpoint names Berlin's and the KMK's graph/…
KMK_GRAPH = "https://w3id.org/lehrplan/graph/bista"  # the KMK's educational standards: of no Land
GRAPHS = (
    "https://w3id.org/lehrplan/by",
    "https://w3id.org/lehrplan/rp",
    "https://w3id.org/lehrplan/sn",
    "https://w3id.org/lehrplan/graph/be",
    KMK_GRAPH,
)
PAGE = 500  # parts of a plan a page of the closure reads: the closure has rows by part and ancestor
_IRI = re.compile(r"https?://[^\s<>\"{}|\\^`\x00-\x1f\x7f]+")
MAX_IRI = 2000  # as the tables take one (migration 0030)
_ASKED_AGAIN = frozenset({429, 500, 502, 503, 504})


class MemUnavailable(Exception):
    """The endpoint is out of reach, busy or failing: ask again later."""


class MemRefused(Exception):
    """A query, a graph or an answer the client cannot take: asking again changes nothing."""


@dataclass(frozen=True)
class MemEndpoint:
    url: str
    timeout_s: float = 60.0
    max_bytes: int = 50_000_000  # a JSON answer of a plan's closure is a few MB
    # timeout_s bounds an answer as a whole: connecting, asking and reading it


def mem_iri(value: str) -> str:
    """``value`` in angle brackets, as a query writes an IRI; MemRefused for one that could break out."""
    if len(value) > MAX_IRI or _IRI.fullmatch(value) is None:
        raise MemRefused("an IRI the query cannot hold")
    return f"<{value}>"


class MemSparql:
    """The endpoint, asked one query at a time."""

    def __init__(self, endpoint: MemEndpoint, transport: httpx2.AsyncBaseTransport | None = None) -> None:
        self._endpoint = endpoint
        self._transport = transport

    def from_clauses(self, graph: str) -> str:
        """``FROM <…>`` for the shared graphs and ``graph``, one of GRAPHS; MemRefused for any other."""
        if graph not in GRAPHS:
            raise MemRefused("a graph the client does not read")
        return "\n".join(f"FROM {mem_iri(name)}" for name in (*SHARED_GRAPHS, graph))

    async def select(self, query: str) -> list[dict[str, str]]:
        """The rows of a SELECT, each binding's value as its string."""
        try:
            async with (
                asyncio.timeout(self._endpoint.timeout_s),
                httpx2.AsyncClient(
                    transport=self._transport or pinned_transport(),
                    follow_redirects=False,
                    timeout=self._endpoint.timeout_s,
                    trust_env=False,
                ) as client,
            ):
                request = client.build_request(
                    "POST",
                    self._endpoint.url,
                    data={"query": query},
                    headers={
                        "Accept": "application/sparql-results+json",
                        "Accept-Encoding": ACCEPT_ENCODING,
                        "User-Agent": USER_AGENT,
                    },
                )
                response = await client.send(request, stream=True)
                try:
                    body = await self._body(response)
                finally:
                    await response.aclose()
        except TimeoutError:
            raise MemUnavailable(
                f"the answer took longer than its time ({self._endpoint.timeout_s:.0f} s)"
            ) from None
        except HostNotResolved as error:
            # the pinned transport's own errors, which httpx2 passes on as they are
            if error.transient:
                raise MemUnavailable("the endpoint's name did not resolve") from None
            raise MemRefused("the endpoint's name does not exist") from None
        except UrlNotAllowed:
            raise MemRefused("the endpoint is not public") from None
        except (httpx2.TransportError, httpx2.DecodingError) as error:
            raise MemUnavailable(f"the endpoint is out of reach ({type(error).__name__})") from None
        return _rows(body)

    async def select_pages(
        self, query_for: Callable[[int, int], str], count_query: str, page: int = PAGE
    ) -> list[dict[str, str]]:
        """The rows of ``query_for(limit, offset)`` page by page, until COUNT of ``count_query`` (one row,
        ``?count``) is reached; MemRefused where the pages fall short of or past it."""
        if page < 1:
            raise ValueError("a page holds a row at least")
        counted = await self.select(count_query)
        try:
            total = int(counted[0]["count"])
        except (IndexError, KeyError, ValueError):
            raise MemRefused("a count the endpoint did not give") from None
        rows: list[dict[str, str]] = []
        while len(rows) < total:
            found = await self.select(query_for(page, len(rows)))
            rows.extend(found)
            if len(found) < page:
                break
        if len(rows) != total:
            raise MemRefused(f"{len(rows)} rows read of a count of {total}")
        return rows

    async def _body(self, response: httpx2.Response) -> bytes:
        if response.status_code in _ASKED_AGAIN:
            raise MemUnavailable(f"the endpoint answered {response.status_code}")
        if response.status_code != 200:
            raise MemRefused(f"the endpoint answered {response.status_code}")
        if "X-SQL-State" in response.headers:
            raise MemUnavailable("a partial answer: the endpoint ran out of its time")
        try:
            return await aread_body(response, self._endpoint.max_bytes)
        except BodyTooLarge:
            raise MemRefused("the answer exceeds its limit") from None
        except (UnsupportedEncoding, BrokenCompression):
            raise MemRefused("an answer that cannot be unpacked") from None


def _rows(body: bytes) -> list[dict[str, str]]:
    try:
        bindings = json.loads(body)["results"]["bindings"]
        return [{name: str(value["value"]) for name, value in row.items()} for row in bindings]
    except (ValueError, KeyError, TypeError, AttributeError):
        raise MemRefused("an answer that is no SPARQL result") from None
