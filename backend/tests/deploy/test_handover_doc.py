"""docs/uebergabe/anforderungen.md, the answers for the operators' IT team, held to what the service is:
the metrics it exports and the alerts on them, what its image carries, the volumes it mounts, and the
state the configuration document speaks of."""

import re
from pathlib import Path
from typing import Any

import yaml  # type: ignore[import-untyped]
from prometheus_client import REGISTRY

from app.core import metrics  # noqa: F401 - registers the service's metrics
from tests.deploy.test_alert_rules import RULES

ROOT = Path(__file__).resolve().parents[3]
HANDOVER = ROOT / "docs" / "uebergabe"
DOCUMENT = (HANDOVER / "anforderungen.md").read_text(encoding="utf-8")
CONFIGURATION = (HANDOVER / "konfiguration.md").read_text(encoding="utf-8")
DOCKERFILE = (ROOT / "deploy" / "api.Dockerfile").read_text(encoding="utf-8")
COMPOSE_FILES = ("docker-compose.yml", "docker-compose.converter.yml")
HELM: dict[str, Any] = yaml.safe_load(
    (ROOT / "deploy" / "helm-values.example.yaml").read_text(encoding="utf-8")
)
STAND = re.compile(r"\bStand ([A-Z][^,\n]*, \d{1,2}\.\d{1,2}\.\d{4})")


def exported_metrics() -> set[str]:
    """Each metric of the service by the name a query and the document give it: a counter with _total."""
    return {
        family.name + ("_total" if family.type == "counter" else "")
        for family in REGISTRY.collect()
        if family.name.startswith("curricarta_")
    }


def row(question: str) -> str:
    [line] = [line for line in DOCUMENT.splitlines() if line.startswith(f"| {question} |")]
    return line


def test_every_metric_the_document_names_is_one_the_service_exports() -> None:
    named = set(re.findall(r"\bcurricarta_[a-z0-9_]*[a-z0-9]\b", DOCUMENT))

    assert named == exported_metrics()


def test_every_alert_the_document_names_is_a_rule_of_the_rule_file() -> None:
    assert set(re.findall(r"\bCurricarta[A-Z][A-Za-z]+\b", DOCUMENT)) == {rule["alert"] for rule in RULES}


def final_stage_copies(dockerfile: str) -> list[str]:
    """The sources the last stage copies from the build context (not from another stage)."""
    final = re.split(r"(?m)^FROM ", dockerfile)[-1]
    return [match.group(1) for match in re.finditer(r"(?m)^COPY (?!--from)(\S+) ", final)]


def test_the_document_says_what_the_image_carries() -> None:
    sources = final_stage_copies(DOCKERFILE)

    assert "data/seed" in sources and "backend/app" in sources
    assert not [source for source in sources if f"`{source}`" not in row("Images?")]


def mounted_volumes() -> dict[str, str]:
    """Each named volume or claim a service of the deployment mounts, with its path."""
    mounts = {}
    for name in COMPOSE_FILES:
        compose = yaml.safe_load((ROOT / "deploy" / name).read_text(encoding="utf-8"))
        for service in compose["services"].values():
            for volume in service.get("volumes", []):
                source, path = volume.split(":")[:2]
                if not source.startswith((".", "/")):  # a named volume, not a file of the host
                    mounts[source] = path
    for part in HELM.values():
        if isinstance(part, dict):
            for volume in part.get("volumes", {}).values():
                mounts[volume["existingClaim"]] = volume["mountPath"]
    return mounts


def test_the_volumes_the_document_names_are_those_the_deployment_mounts() -> None:
    # the retention's sweep among the services: it mounts none
    volumes = row("Volumes?")
    mounts = mounted_volumes()
    known = {*mounts, *(name for file in COMPOSE_FILES for name in _top_level_volumes(file))}

    assert mounts
    assert {name for name in re.findall(r"`([^`]+)`", volumes) if name in known} == set(mounts)
    assert not [path for path in mounts.values() if f"`{path}`" not in volumes]


def _top_level_volumes(name: str) -> list[str]:
    return list(yaml.safe_load((ROOT / "deploy" / name).read_text(encoding="utf-8")).get("volumes") or [])


def test_both_documents_carry_the_same_stand() -> None:
    stands = [STAND.findall(text)[:1] for text in (DOCUMENT, CONFIGURATION)]

    assert stands[0] and stands[0] == stands[1]
