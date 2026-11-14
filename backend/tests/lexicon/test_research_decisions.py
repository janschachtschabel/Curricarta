"""The editors' decisions in the research's files (ontology/werkzeuge/recherche_entscheidungen.py, the
importer; plan M1 10.3, 10c C9): recherche-ergebnisse/entscheidungen.json, as python -m
app.lexicon.export_reviews writes it, checked whole before anything is written; a confirmed cue verified at
the editors' strength with where they found it, a rejected one gone, a decision whose cue the research no
longer gives counted - and every other cue as it was."""

import json
from collections import Counter
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path
from typing import Any

import pytest
import rdflib
from importiere_recherche import import_reports
from rdflib import Literal, URIRef
from rdflib.namespace import SKOS
from recherche_entscheidungen import Decision, decisions_of

from app.db.cue_review import Decision as Made
from app.db.term_review import TermReview
from app.lexicon.export_reviews import document
from tests.lexicon.reports import ontology, row

CUR = rdflib.Namespace("https://w3id.org/wlo/curriculum/core#")
NW = "profile/laender/schule-DE-NW.ttl"
HE = "profile/laender/schule-DE-HE.ttl"
FILE = "entscheidungen.json"
NOW = datetime(2026, 10, 31, 12, tzinfo=UTC)


def graph(content: bytes) -> rdflib.Graph:
    return rdflib.Graph().parse(data=content.decode("utf-8"), format="turtle")


def cue_of(content: bytes, word: str) -> URIRef:
    found = graph(content).value(predicate=CUR.surfaceForm, object=Literal(word))
    assert isinstance(found, URIRef), word
    return found


def decided(root: Path, *entries: Any, form: Any = 2, terms: tuple[Any, ...] = ()) -> None:
    held = {"format": form, "decisions": list(entries), "new_terms": list(terms)}
    (root / "recherche-ergebnisse" / FILE).write_text(json.dumps(held, ensure_ascii=False), encoding="utf-8")


def confirmed(cue: URIRef, **changes: Any) -> dict[str, Any]:
    entry = {
        "cue": str(cue),
        "decision": "confirmed",
        "strength": "0.90",
        "evidence": "KLP S. 14",
        "note": None,
    }
    return entry | {"content": {"surface_form": "Inhaltsfeld"}} | changes


def rejected(cue: URIRef | str) -> dict[str, Any]:
    return {
        "cue": str(cue),
        "decision": "rejected",
        "strength": None,
        "evidence": None,
        "note": None,
        "content": {},
    }


def triples(content: bytes, but: URIRef) -> set[Any]:
    return {triple for triple in graph(content) if but not in triple}


def test_a_confirmed_cue_is_verified_at_its_strength_with_where_the_editors_found_it(tmp_path: Path) -> None:
    root = ontology(tmp_path, {"01-schule-DE-NW.md": [row(), row("Lernbereich")]})
    before, _ = import_reports(root)
    cue = cue_of(before[NW], "Inhaltsfeld")
    decided(root, confirmed(cue, note="passt so"))

    after, reported = import_reports(root)

    g = graph(after[NW])
    assert g.value(cue, CUR.verified) == Literal(True)
    strength = g.value(cue, CUR.strength)
    assert isinstance(strength, Literal) and strength.toPython() == Decimal("0.9")
    assert set(g.objects(cue, SKOS.editorialNote)) == set(
        graph(before[NW]).objects(cue, SKOS.editorialNote)
    ) | {
        Literal("Von der Redaktion geprüft: KLP S. 14", lang="de"),
        Literal("Anmerkung der Redaktion: passt so", lang="de"),
    }
    assert Literal("Länderrecherche, Beleg E: KLP S. 14", lang="de") in set(
        g.objects(cue, SKOS.editorialNote)
    )
    assert triples(after[NW], cue) == triples(before[NW], cue)  # only the decided cue changes
    assert reported[FILE] == Counter({"bestätigt": 1})


def test_a_rejected_cue_leaves_the_files_and_a_file_left_without_cues_goes(tmp_path: Path) -> None:
    root = ontology(tmp_path, {"01-schule-DE-NW.md": [row()], "01-schule-DE-HE.md": [row(land="DE-HE")]})
    before, _ = import_reports(root)
    decided(root, rejected(cue_of(before[NW], "Inhaltsfeld")))

    after, reported = import_reports(root)

    assert sorted(after) == [HE]
    assert after[HE] == before[HE]
    assert reported[FILE] == Counter({"verworfen": 1})
    assert reported["01-schule-DE-NW.md"]["Cues"] == 1  # what the report gives, before the editors


def test_a_decision_on_a_cue_the_research_no_longer_gives_is_counted_and_changes_nothing(
    tmp_path: Path,
) -> None:
    root = ontology(tmp_path, {"01-schule-DE-NW.md": [row()]})
    before, _ = import_reports(root)
    decided(root, rejected("https://w3id.org/wlo/curriculum/profile/school#re-DE-NW-000000000000"))

    unmatched = ["from an earlier run"]  # the caller's list: added to, never counted
    after, reported = import_reports(root, unmatched)

    assert after == before
    assert reported[FILE] == Counter({"Entscheidung ohne Cue": 1})
    assert unmatched == [
        "from an earlier run",
        "https://w3id.org/wlo/curriculum/profile/school#re-DE-NW-000000000000",
    ]


def test_a_confirmation_without_a_note_adds_where_it_was_found_alone(tmp_path: Path) -> None:
    root = ontology(tmp_path, {"01-schule-DE-NW.md": [row()]})
    before, _ = import_reports(root)
    cue = cue_of(before[NW], "Inhaltsfeld")
    decided(root, confirmed(cue, evidence="  KLP S. 3 "))

    after, _ = import_reports(root)

    notes = set(graph(after[NW]).objects(cue, SKOS.editorialNote))
    assert notes == set(graph(before[NW]).objects(cue, SKOS.editorialNote)) | {
        Literal("Von der Redaktion geprüft: KLP S. 3", lang="de")
    }


def test_the_export_s_file_is_what_the_importer_reads(tmp_path: Path) -> None:
    made = [
        Made(
            CUE,
            "confirmed",
            Decimal("0.90"),
            "KLP S. 14",
            None,
            {"surface_form": "Fächer"},
            "R",
            NOW,
            False,
            False,
        ),
        Made(CUE[:-1] + "f", "rejected", None, None, "falsch", {}, "R", NOW, True, True),
    ]
    (tmp_path / "recherche-ergebnisse").mkdir()
    (tmp_path / "recherche-ergebnisse" / FILE).write_bytes(document(made, []).encode("utf-8"))

    assert decisions_of(tmp_path) == {
        CUE: Decision("confirmed", "0.90", "KLP S. 14", None),
        CUE[:-1] + "f": Decision("rejected", None, None, "falsch"),
    }


def test_the_export_s_new_cues_are_what_the_importer_takes(tmp_path: Path) -> None:
    root = ontology(tmp_path, {"01-schule-DE-NW.md": [row()]})
    before, _ = import_reports(root)
    school = "https://w3id.org/wlo/curriculum/profile/school#"
    vocab = "https://w3id.org/wlo/curriculum/vocab#"

    def review(key: str, decision: Any, **cue: Any) -> TermReview:
        values = {"profile": school + "Terminology", "maps_to": None, "role": None, "note": None} | cue
        return TermReview(
            "school",
            vocab + "sec_school",
            ("DE-NW",),
            key,
            key.capitalize(),
            decision,
            content={},
            decided_by="R",
            decided_at=NOW,
            applied=None,
            **values,
        )

    taken = [
        review("lernbereich", "cue", maps_to=school + "Kompetenzbereich", role=vocab + "role_alt", note="NW"),
        review("leitidee", "document"),
    ]
    (root / "recherche-ergebnisse" / FILE).write_bytes(document([], taken).encode("utf-8"))

    after, reported = import_reports(root)

    assert sorted(after) == [NW]
    g = graph(after[NW])
    cue = cue_of(after[NW], "Lernbereich")
    assert (g.value(cue, CUR.cueRole), g.value(cue, CUR.mapsTo)) == (
        URIRef(vocab + "role_alt"),
        URIRef(school + "Kompetenzbereich"),
    )
    assert triples(after[NW], cue) == triples(before[NW], cue)  # the research's cue as it was
    assert reported[FILE] == Counter({"neuer Hinweis": 1})


def test_a_file_a_windows_shell_began_with_a_byte_order_mark_is_read(tmp_path: Path) -> None:
    (tmp_path / "recherche-ergebnisse").mkdir()
    text = chr(0xFEFF) + json.dumps({"format": 2, "decisions": [rejected(CUE)], "new_terms": []})
    (tmp_path / "recherche-ergebnisse" / FILE).write_text(text, encoding="utf-8")

    assert decisions_of(tmp_path) == {CUE: Decision("rejected", None, None, None)}


def test_without_decisions_none_are_reported(tmp_path: Path) -> None:
    _, reported = import_reports(ontology(tmp_path, {"01-schule-DE-NW.md": [row()]}))

    assert FILE not in reported


CUE = "https://w3id.org/wlo/curriculum/profile/school#re-DE-NW-0e2794728e9d"


@pytest.mark.parametrize(
    ("held", "form"),
    [
        ([confirmed(URIRef(CUE))], 1),  # 10c's, before the new terms
        ([confirmed(URIRef(CUE), strength="0.95")], 2),
        ([confirmed(URIRef(CUE), strength="0.45")], 2),
        ([confirmed(URIRef(CUE), strength="neun")], 2),
        ([confirmed(URIRef(CUE), strength=0.9)], 2),
        ([confirmed(URIRef(CUE), evidence="")], 2),
        ([confirmed(URIRef(CUE), evidence="   ")], 2),
        ([confirmed(URIRef(CUE), evidence=None)], 2),
        ([rejected(CUE) | {"strength": "0.9"}], 2),
        ([confirmed(URIRef(CUE), decision="deferred")], 2),  # all else as a confirmation
        ([rejected(CUE) | {"cue": ""}], 2),
        ([rejected(CUE) | {"note": 7}], 2),
        ([rejected(CUE), rejected(CUE)], 2),
        (["rejected"], 2),
    ],
    ids=[
        "other-format",
        "above-0.9",
        "below-0.5",
        "no-number",
        "number-not-text",
        "empty-evidence",
        "blank-evidence",
        "no-evidence",
        "rejected-with-strength",
        "unknown-decision",
        "no-cue",
        "note-no-text",
        "twice",
        "no-object",
    ],
)
def test_a_file_outside_the_form_is_refused_before_anything_is_written(
    tmp_path: Path, held: list[Any], form: int
) -> None:
    root = ontology(tmp_path, {"01-schule-DE-NW.md": [row()]})
    decided(root, *held, form=form)

    with pytest.raises(ValueError, match=FILE):
        import_reports(root)


@pytest.mark.parametrize(
    "text",
    [
        "{",
        "[]",
        '{"format": 2}',
        '{"format": 2, "decisions": {}, "new_terms": []}',
        '{"format": 2, "decisions": []}',
        '{"format": 2, "decisions": [], "new_terms": {}}',
    ],
)
def test_a_file_that_is_no_list_of_decisions_is_refused(tmp_path: Path, text: str) -> None:
    root = ontology(tmp_path, {"01-schule-DE-NW.md": [row()]})
    (root / "recherche-ergebnisse" / FILE).write_text(text, encoding="utf-8")

    with pytest.raises(ValueError, match=FILE):
        import_reports(root)
