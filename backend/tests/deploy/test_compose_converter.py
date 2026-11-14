"""What deploy/docker-compose.converter.yml promises, read off the file (plan M1 3b): laid over the
service's Compose file, it adds Docling's conversions - the converter, a worker of the converter's image
taking them alone, its models from a volume, read-only, fetched once by a service run by hand - and has
the API offer Docling first. Without it the API offers pdfplumber alone, and no Docling job waits for a
worker that is not there."""

import re
from pathlib import Path
from typing import Any

import pytest
import yaml  # type: ignore[import-untyped]

from app.conversion.job import DOCLING_KIND
from app.conversion.models import MODELS_DIR
from app.core.settings import Settings

ROOT = Path(__file__).resolve().parents[3]
TEXT = (ROOT / "deploy" / "docker-compose.converter.yml").read_text(encoding="utf-8")
CONVERTER: dict[str, Any] = yaml.safe_load(TEXT)
SERVICES: dict[str, Any] = CONVERTER["services"]
BASE: dict[str, Any] = yaml.safe_load((ROOT / "deploy" / "docker-compose.yml").read_text(encoding="utf-8"))
OURS = ["converter", "models"]
TMPFS = "/tmp"  # noqa: S108 - a path in the container, read off the file: no temporary file is made


def test_no_variable_of_the_developers_environment_is_read() -> None:
    assert not re.search(r"\$\{?[A-Za-z_]", TEXT)


@pytest.mark.parametrize("name", SERVICES)
def test_no_variable_passes_through_from_the_shell_or_a_file(name: str) -> None:
    service = SERVICES[name]

    assert "env_file" not in service
    environment = service.get("environment", {})
    assert isinstance(environment, dict), "a list may name a variable without its value"
    assert all(isinstance(value, str) and value for value in environment.values()), environment


def test_it_brings_no_secret_or_port_of_its_own() -> None:
    # the converter reads the service's secrets, as files, by their names in the base file
    assert "secrets" not in CONVERTER
    assert not any(service.get("ports") for service in SERVICES.values())
    assert SERVICES["converter"]["environment"]["DATABASE_URL_FILE"].startswith("/run/secrets/")


def test_the_converter_is_set_up_as_the_service_s_other_workers_are() -> None:
    # anchors do not cross files: what the base file gives its services, the converter repeats - a setting
    # added there and not here would leave the converter without it
    app = BASE["x-app"]

    assert set(SERVICES["converter"]["secrets"]) == set(app["secrets"])
    assert app["environment"].items() <= SERVICES["converter"]["environment"].items()


def test_the_fetch_of_the_models_holds_no_secret() -> None:
    # the one service that asks Hugging Face and GitHub: the database's address and the store's keys stay away
    assert "secrets" not in SERVICES["models"]
    assert not [name for name in SERVICES["models"].get("environment", {}) if name.endswith("_FILE")]


@pytest.mark.parametrize("name", OURS)
def test_its_services_run_without_privileges_on_a_read_only_root(name: str) -> None:
    service = SERVICES[name]

    assert service["read_only"] is True
    assert service["cap_drop"] == ["ALL"]
    assert "no-new-privileges:true" in service["security_opt"]
    assert service["image"] == "curricarta-convert:local"


def test_the_converter_s_image_is_built_with_docling_and_nothing_from_the_host() -> None:
    build = SERVICES["converter"]["build"]

    assert not {"secrets", "ssh"} & set(build)
    # a mapping of literal values: a list ("- VENV") would take the shell's VENV
    assert build["args"] == {"VENV": "convert"}
    assert build["dockerfile"] == "deploy/api.Dockerfile"


def test_the_converter_takes_docling_s_conversions_alone_with_the_time_they_take() -> None:
    converter = SERVICES["converter"]

    assert converter["command"] == ["python", "-m", "app.jobs.worker"]
    assert converter["environment"]["WORKER_KINDS"] == DOCLING_KIND
    # some 4 s a page on four cores: 800 pages (MAX_PDF_PAGES) take near an hour
    timeout = float(converter["environment"]["CONVERT_TIMEOUT_S"])
    limit = Settings.model_fields["convert_timeout_s"].metadata
    assert timeout >= 800 * 4 and all(getattr(bound, "le", timeout) >= timeout for bound in limit)
    assert converter["restart"] == "unless-stopped"
    # the API waits for its first healthy check: the image's every 30 s would hold up a start
    assert "test" not in converter["healthcheck"] and converter["healthcheck"]["interval"] == "5s"
    assert converter["depends_on"]["migrate"] == {"condition": "service_completed_successfully"}


def test_the_converter_reads_the_models_and_the_fetch_alone_writes_them() -> None:
    folder = MODELS_DIR.as_posix()

    assert SERVICES["converter"]["volumes"] == [f"models:{folder}:ro"]
    assert SERVICES["models"]["volumes"] == [f"models:{folder}"]
    assert "models" in CONVERTER["volumes"]


def test_the_models_are_fetched_once_by_hand_never_on_a_start() -> None:
    models = SERVICES["models"]

    assert models["profiles"] == ["models"]  # `up` leaves it; `run --rm models` runs it
    assert models["command"] == ["python", "-m", "app.conversion.fetch_models", MODELS_DIR.as_posix()]
    # the image keeps Hugging Face offline: the fetch alone may ask it
    assert models["environment"]["HF_HUB_OFFLINE"] == "0"
    # its root is read-only and the service's user has no home: Hugging Face's library keeps its refs, and
    # hf-xet its logs and chunks, under HF_HOME, which the tmpfs holds; plain downloads keep no chunks there
    assert models["environment"]["HF_HOME"].startswith(f"{TMPFS}/") and TMPFS in models["tmpfs"]
    assert models["environment"]["HF_HUB_DISABLE_XET"] == "1"
    assert "HF_HUB_OFFLINE" not in SERVICES["converter"]["environment"]
    assert models.get("restart", "no") == "no"


def test_the_api_offers_docling_first_once_the_converter_runs() -> None:
    # started before the converter is healthy - its models missing, it ends at its start -, the API would
    # take Docling's conversions that no worker takes: `up` fails instead
    assert SERVICES["api"] == {
        "environment": {"CONVERSION_ENGINES": "docling,pdfplumber"},
        "depends_on": {"converter": {"condition": "service_healthy"}},
    }
    assert "CONVERSION_ENGINES" not in BASE["services"]["api"]["environment"]
