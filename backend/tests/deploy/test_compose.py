"""What deploy/docker-compose.yml promises, read off the file.

The run itself (all services up, the migration exactly once, /ready 200) is the package's
check; these keep the safety properties from slipping out of the file afterwards.
"""

import ipaddress
import re
from pathlib import Path
from typing import Any

import pytest
import yaml  # type: ignore[import-untyped]

from app.core.settings import Settings
from app.jobs.worker import HAND_BACKS_WAIT_S, RELEASE_WAIT_S

ROOT = Path(__file__).resolve().parents[3]
TEXT = (ROOT / "deploy" / "docker-compose.yml").read_text(encoding="utf-8")
COMPOSE: dict[str, Any] = yaml.safe_load(TEXT)
SERVICES: dict[str, Any] = COMPOSE["services"]
# The services the converter's file lays over this one (its api adds to the base file's)
OVERLAY: dict[str, Any] = yaml.safe_load(
    (ROOT / "deploy" / "docker-compose.converter.yml").read_text(encoding="utf-8")
)["services"]
APP = ["bucket", "migrate", "vocab", "api", "worker", "retention"]
# The services that run on; the one-off steps end, and a restart would run them again
LASTING = ["postgres", "minio", "api", "worker", "web"]
# A second beside a stopping worker's own waits, for the process to end after them
SHUTDOWN_RESERVE_S = 1.0
# What a stopping worker takes beside JOB_SHUTDOWN_GRACE_S: its handler's unwinding, the reservations
# handed back, the reserve (app/jobs/worker.py)
BESIDE_THE_GRACE_S = RELEASE_WAIT_S + HAND_BACKS_WAIT_S + SHUTDOWN_RESERVE_S


def _seconds(duration: str) -> float:
    match = re.fullmatch(r"(\d+)(s|m)", duration)
    assert match, duration
    return int(match.group(1)) * (60 if match.group(2) == "m" else 1)


def test_no_variable_of_the_developers_environment_is_read() -> None:
    # an interpolated ${OPENAI_API_KEY} would hand a real key to a container, and render it
    # into `docker compose config`
    assert not re.search(r"\$\{?[A-Za-z_]", TEXT)


@pytest.mark.parametrize("name", SERVICES)
def test_no_variable_passes_through_from_the_shell_or_a_file(name: str) -> None:
    # "MISTRAL_API_KEY:" without a value takes the shell's, env_file a whole file's: neither
    # needs a $, and real keys are exported on the developers' machines
    service = SERVICES[name]

    assert "env_file" not in service
    environment = service.get("environment", {})
    assert isinstance(environment, dict), "a list may name a variable without its value"
    assert all(isinstance(value, str) and value for value in environment.values()), environment


def test_every_secret_is_a_file_of_deploy_secrets() -> None:
    # A secret may also come from the host's environment ({environment: OPENAI_API_KEY}), with
    # no $ and no env_file - and the developers' machines export real keys
    assert COMPOSE["secrets"]
    assert all(source == {"file": f"./secrets/{name}"} for name, source in COMPOSE["secrets"].items())


@pytest.mark.parametrize("name", [name for name, service in SERVICES.items() if "build" in service])
def test_a_build_takes_nothing_from_the_host(name: str) -> None:
    assert not {"args", "secrets", "ssh"} & set(SERVICES[name]["build"])


def test_only_the_web_server_is_published_and_only_on_loopback() -> None:
    published = {name: service["ports"] for name, service in SERVICES.items() if service.get("ports")}

    assert published == {"web": ["127.0.0.1:18080:8080"]}


@pytest.mark.parametrize("name", [*APP, "web"])
def test_a_service_of_ours_runs_without_privileges_on_a_read_only_root(name: str) -> None:
    service = SERVICES[name]

    assert service["read_only"] is True
    assert service["cap_drop"] == ["ALL"]
    assert "no-new-privileges:true" in service["security_opt"]


@pytest.mark.parametrize("name", APP)
def test_secrets_come_as_files_not_as_values(name: str) -> None:
    environment = SERVICES[name]["environment"]
    secret_names = {"DATABASE_URL", "API_KEY_PEPPER", "S3_ACCESS_KEY", "S3_SECRET_KEY", "OPENAI_API_KEY"}

    assert not secret_names & set(environment)
    assert environment["DATABASE_URL_FILE"].startswith("/run/secrets/")


def test_every_third_party_image_is_pinned_by_digest() -> None:
    images = [service["image"] for service in SERVICES.values() if "build" not in service]
    third_party = [image for image in images if not image.startswith("curricarta-")]

    assert third_party
    assert all(re.search(r"@sha256:[0-9a-f]{64}$", image) for image in third_party), third_party


def test_the_migration_runs_once_and_before_api_and_worker() -> None:
    for name in ("api", "worker"):
        assert SERVICES[name]["depends_on"]["migrate"] == {"condition": "service_completed_successfully"}
    assert SERVICES["migrate"]["command"] == ["python", "-m", "app.db.migrate"]
    assert "replicas" not in SERVICES["migrate"].get("deploy", {})


def test_api_and_worker_run_twice() -> None:
    assert SERVICES["api"]["deploy"]["replicas"] == 2
    assert SERVICES["worker"]["deploy"]["replicas"] == 2


def test_the_api_trusts_the_web_server_alone_to_name_the_client() -> None:
    # The network holds the gateway too: every connection to the published port comes from it,
    # and a host process could reach the API from there with an X-Forwarded-For of its choosing
    web = SERVICES["web"]["networks"]["default"]["ipv4_address"]
    network = COMPOSE["networks"]["default"]["ipam"]["config"][0]

    assert SERVICES["api"]["environment"]["FORWARDED_ALLOW_IPS"] == web
    # outside the range Docker hands out: no container started first can hold it
    assert ipaddress.ip_address(web) in ipaddress.ip_network(network["subnet"])
    assert ipaddress.ip_address(web) not in ipaddress.ip_network(network["ip_range"])


def test_the_api_alone_cancels_a_statement_past_a_minute() -> None:
    # a request's statement; a worker's step - the converter's too - may wait for a lock longer (no timeout)
    others = [*(SERVICES[name] for name in SERVICES if name != "api"), *OVERLAY.values()]

    assert SERVICES["api"]["environment"]["DB_STATEMENT_TIMEOUT_S"] == "60"
    assert all("DB_STATEMENT_TIMEOUT_S" not in service.get("environment", {}) for service in others)


@pytest.mark.parametrize("name", ["api", "worker"])
def test_the_answer_limit_is_set_for_api_and_worker_alike(name: str) -> None:
    # the API offers a repair only where the workers would ask under the same limit: a value for one
    # of them alone leaves the page offering none, or one that asks nothing
    shared = COMPOSE["x-app"]["environment"]

    assert SERVICES[name]["environment"].get("LLM_MAX_OUTPUT_TOKENS") == shared.get("LLM_MAX_OUTPUT_TOKENS")


def test_the_database_counts_as_healthy_once_it_listens_on_tcp() -> None:
    # On the first start the entrypoint runs a server on its socket only, to make the database:
    # pg_isready over the socket says healthy then, and the migration finds port 5432 closed
    assert "-h 127.0.0.1" in " ".join(SERVICES["postgres"]["healthcheck"]["test"])


@pytest.mark.parametrize("name", LASTING)
def test_a_service_that_ends_with_an_error_is_started_again(name: str) -> None:
    # the worker ends with an error when its sweeper breaks, trusting a supervisor to restart it
    assert SERVICES[name]["restart"] == "unless-stopped"


def test_a_stopping_worker_may_finish_its_job_before_docker_kills_it() -> None:
    worker = SERVICES["worker"]
    default = Settings.model_fields["job_shutdown_grace_s"].default
    grace = float(worker["environment"].get("JOB_SHUTDOWN_GRACE_S", default))

    # Docker's default of 10 s would kill a busy worker; its job would wait for the lease to end
    assert _seconds(worker["stop_grace_period"]) >= grace + BESIDE_THE_GRACE_S


def test_the_worker_is_checked_by_the_image_s_health_check() -> None:
    # it answers /health on its internal port: switched off, a stuck worker would look healthy
    assert SERVICES["worker"].get("healthcheck", {}).get("disable") is not True


def test_the_api_is_found_healthy_within_seconds_of_its_start() -> None:
    # the image checks every 30 s, and the web server waits for the first healthy check;
    # Compose keeps the image's test and only asks more often
    check = SERVICES["api"]["healthcheck"]

    assert "test" not in check
    assert _seconds(check["interval"]) <= 5


def test_the_secret_files_are_kept_out_of_git() -> None:
    ignored = (ROOT / ".gitignore").read_text(encoding="utf-8").splitlines()

    assert "/deploy/secrets/" in ignored


def test_compose_starts_the_sweep_only_when_asked() -> None:
    # `docker compose --profile retention run --rm -T retention`, from the operator's timer: never with up
    sweep = SERVICES["retention"]

    assert sweep["profiles"] == ["retention"]
    assert sweep["command"] == ["python", "-m", "app.retention"]
    assert "restart" not in sweep and "replicas" not in sweep.get("deploy", {})
    # beside the running service: never the migration or the bucket's step again
    assert set(sweep["depends_on"]) == {"postgres", "minio"}


def test_the_sweep_holds_neither_the_pepper_nor_the_model_s_key() -> None:
    # the anchor's list would hand it the pepper: its own, the database and the store alone
    sweep = SERVICES["retention"]

    assert sweep["secrets"] == ["database_url", "s3_access_key", "s3_secret_key"]
    assert not {"API_KEY_PEPPER_FILE", "OPENAI_API_KEY_FILE"} & set(sweep["environment"])


def test_the_sweep_reaches_the_store_as_the_worker_does() -> None:
    # without the store it lists nothing there: it would forget every note and leave the objects for good
    sweep, worker = SERVICES["retention"], SERVICES["worker"]
    store = {
        name: value
        for name, value in COMPOSE["x-app"]["environment"].items()
        if name.startswith(("S3_", "STORAGE_"))
    }

    assert store and {name: sweep["environment"].get(name) for name in store} == store
    assert sweep.get("volumes") == worker.get("volumes")


def test_the_times_of_the_retention_reach_the_sweep() -> None:
    # set under another service alone, a time - a 0 to keep everything - would not reach the sweep
    sweep = SERVICES["retention"]["environment"]
    elsewhere = {
        name: value
        for service in (
            COMPOSE["x-app"],
            *(SERVICES[name] for name in SERVICES if name != "retention"),
            *OVERLAY.values(),
        )
        for name, value in service.get("environment", {}).items()
        if name.startswith("RETENTION_")
    }

    assert {name: sweep.get(name) for name in elsewhere} == elsewhere
