"""A small ontology with research reports, as the lexicon tools' tests build it (plan M1 10a, 10b)."""

from pathlib import Path

FENCE = "`" * 3
T3 = (
    "land;begriff_woertlich;fundort;funktion;ziel_id;rolle;erkennungsmerkmal;beispiel_woertlich;fundstelle;"
    "gilt_fuer;plangeneration_oder_gueltig_ab;abgrenzung_verwechslung;abgleich_vorliste;hinweis_id;beleg"
)
T4 = "land;rahmen_titel;kuerzel_oder_symbol;bedeutung_woertlich;markierung_wo;entspricht;fundstelle;beleg"
MODEL = """@prefix schul: <https://w3id.org/wlo/curriculum/profile/school#> .
@prefix cur: <https://w3id.org/wlo/curriculum/core#> .
@prefix qz: <https://w3id.org/wlo/curriculum/crosscutting/> .
@prefix skos: <http://www.w3.org/2004/02/skos/core#> .
schul:Terminology a cur:TerminologyProfile .
schul:Inhaltsbereich a cur:NodeType .
schul:Kompetenzbereich a cur:NodeType .
qz:BNE a cur:CrossCuttingObjective .
schul:Faecher a skos:ConceptScheme .
"""


LANDS = "@prefix land: <https://w3id.org/wlo/curriculum/region/> .\n" + "".join(
    f"land:{code} a <http://www.w3.org/2004/02/skos/core#Concept> .\n"
    for code in ("DE", "DE-BY", "DE-HE", "DE-NW", "DE-SN")
)


def row(
    begriff: str = "Inhaltsfeld",
    land: str = "DE-NW",
    fundstelle: str = "KLP S. 14",
    beleg: str = "E",
    *,
    ziel: str = "schul:Inhaltsbereich",
    rolle: str = "cue",
    fundort: str = "ueberschrift",
    abgleich: str = "neu",
    hinweis: str = "",
    funktion: str = "gliederung:area",
) -> str:
    """A T3 row: a term with its target, where and how sure the research found it."""
    return (
        f"{land};{begriff};{fundort};{funktion};{ziel};{rolle};Nummer;„{begriff} 1“;"
        f"{fundstelle};Physik;2019;;{abgleich};{hinweis};{beleg}"
    )


def block(header: str, *rows: str) -> str:
    return "\n".join([f"{FENCE}csv", header, *rows, FENCE, ""])


def ontology(root: Path, reports: dict[str, list[str] | str]) -> Path:
    """`root` as an ontology: the school profile of MODEL, the lands of LANDS and the reports, as T3 rows or a
    whole text."""
    (root / "profile").mkdir(parents=True)
    (root / "profile" / "schule.ttl").write_text(MODEL, encoding="utf-8")
    (root / "vokabulare").mkdir()
    (root / "vokabulare" / "laender.ttl").write_text(LANDS, encoding="utf-8")
    (root / "recherche-ergebnisse").mkdir()
    (root / "recherche-ergebnisse" / "README.md").write_text("# keine Tabellen\n", encoding="utf-8")
    for name, rows in reports.items():
        text = rows if isinstance(rows, str) else "<!-- Recherche -->\n" + block(T3, *rows)
        (root / "recherche-ergebnisse" / name).write_text(text, encoding="utf-8")
    return root
