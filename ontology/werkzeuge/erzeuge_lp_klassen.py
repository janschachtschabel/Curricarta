"""Generate the FWU Lehrplan-Ontologie's class chain and its state classes' base types (plan M2, E8/E9).

Input:
- werkzeuge/quellen/lp.ttl: the FWU Lehrplan-Ontologie (MEM-Schule) as published, version 1.0.0rc3,
  CC BY-SA 4.0 (https://github.com/FWU-DE/lehrplan-ontologie);
- werkzeuge/quellen/fwu-landesklassen.csv: one row per state class, with its base type (column
  basistyp_iri), derived from its superclass chain or from its "hat Funktion" value.

Output:
- mem/lp-klassen.ttl: a faithful extract of lp.ttl - every named class with its named superclasses
  (rdfs:subClassOf) and its labels, nothing added. The MEM shapes target base classes (Bereich, Lehrplan,
  Verweis); SHACL follows rdfs:subClassOf* in the data graph, so a class lp.ttl places under a base
  class reaches its shape without a reasoner.
- mem/grundtypen.json: the base types of the table's curricular classes, by class IRI - a
  classification aid the import types by. For a class whose base type follows from its function value
  the ontology does not entail it (FWU's reasoned.ttl infers only the Verweis ones), so it is kept out of
  the chain and never written as FWU's axiom.

Usage: python -I erzeuge_lp_klassen.py <ontology-dir>
"""

from __future__ import annotations

import csv
import json
import sys
from pathlib import Path
from typing import Any

from rdflib import OWL, RDF, RDFS, Graph, Literal, URIRef

HEADER = (
    "# Generiert von werkzeuge/erzeuge_lp_klassen.py aus werkzeuge/quellen/lp.ttl - nicht von Hand ändern.\n"
    "# Lehrplan Ontology, Version 1.0.0rc3, https://w3id.org/lehrplan/ontology (FWU), CC BY-SA 4.0:\n"
    "# auf Klassen, Oberklassen und Labels gekürzt, nichts hinzugefügt (mem/LIZENZ.md).\n"
)
NOTE = (
    "Grundtypen der curricularen Landesklassen aus werkzeuge/quellen/fwu-landesklassen.csv "
    "(Spalte basistyp_iri), eine Hilfe zur Typisierung beim Import: für Klassen, deren Grundtyp aus "
    "ihrem Funktionswert folgt, folgt er nicht aus lp.ttl (reasoned.ttl folgert nur die Verweise)."
)


def build(source: Graph) -> Graph:
    """The named classes of ``source`` with their named superclasses and their labels."""
    chain = Graph()
    chain.bind("lp", "https://w3id.org/lehrplan/ontology/")
    chain.bind("obo", "http://purl.obolibrary.org/obo/")
    for klass in source.subjects(RDF.type, OWL.Class):
        if not isinstance(klass, URIRef):
            continue
        chain.add((klass, RDF.type, OWL.Class))
        for parent in source.objects(klass, RDFS.subClassOf):
            if isinstance(parent, URIRef):
                chain.add((klass, RDFS.subClassOf, parent))
        for label in source.objects(klass, RDFS.label):
            if isinstance(label, Literal):
                chain.add((klass, RDFS.label, label))
    return chain


def base_types(rows: list[dict[str, str]]) -> dict[str, Any]:
    """The table's curricular classes with their base types, two where the table names two."""
    types = {
        row["iri"]: sorted(base.strip() for base in row["basistyp_iri"].split(" + ") if base.strip())
        for row in rows
        if row["basistyp"].startswith("CE-")
    }
    return {"hinweis": NOTE, "grundtypen": dict(sorted(types.items()))}


def main() -> None:
    root = Path(sys.argv[1])
    sources = root / "werkzeuge" / "quellen"
    chain = build(Graph().parse(sources / "lp.ttl", format="turtle"))
    (root / "mem" / "lp-klassen.ttl").write_bytes((HEADER + chain.serialize(format="turtle")).encode("utf-8"))
    with (sources / "fwu-landesklassen.csv").open(encoding="utf-8", newline="") as table:
        types = base_types(list(csv.DictReader(table, delimiter=";")))
    written = json.dumps(types, ensure_ascii=False, indent=1) + "\n"
    (root / "mem" / "grundtypen.json").write_bytes(written.encode("utf-8"))
    print(f"{len(set(chain.subjects(RDF.type, OWL.Class)))} Klassen, {len(types['grundtypen'])} Grundtypen")


if __name__ == "__main__":
    main()
