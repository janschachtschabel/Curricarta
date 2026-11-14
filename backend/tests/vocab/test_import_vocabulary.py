"""What an import of a dataset (plan M2, MEM-Schule) needs of the core's vocabulary: the origin of rows
taken over from it, and the run that stands for X1 to X4 (cur-vokabular.ttl)."""

from typing import get_args
from uuid import uuid4

from app.db.runs import RunStart, Stage
from tests.support import ontology_vocabulary

CV = "https://w3id.org/wlo/curriculum/vocab#"


def notations(scheme: str) -> set[str]:
    concepts = ontology_vocabulary().concepts.values()
    return {concept.notation for concept in concepts if concept.scheme == CV + scheme and concept.notation}


def test_a_row_taken_over_from_a_dataset_has_an_origin_of_its_own() -> None:
    assert "import" in notations("Origins")


def test_the_stages_the_runs_take_are_the_core_s() -> None:
    # the run of an import (IM) stands in place of X1 to X4
    assert set(get_args(Stage)) == notations("Stages")
    assert "IM" in notations("Stages")


def test_a_run_of_an_import_is_a_run_of_a_stage() -> None:
    run = RunStart(uuid4(), None, None, "IM", None, None, None, None)

    assert run.stage == "IM"
