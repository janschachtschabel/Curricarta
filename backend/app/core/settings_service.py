"""The settings of the service's frame, by concern - the database, the server, who may come in, the
worker's times -, each a part of Settings (app/core/settings.py)."""

import ipaddress
import re
from typing import Annotated, Any, Literal

import psycopg
from psycopg.conninfo import conninfo_to_dict
from pydantic import BaseModel, Field, SecretStr, field_validator

LogLevel = Literal["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"]
Port = Annotated[int, Field(ge=1, le=65535)]


class DatabaseSettings(BaseModel):
    database_url: Annotated[SecretStr, Field(min_length=1)]
    # Connections per process: the API holds a few; the cluster's total is replicas times max
    db_pool_min_size: Annotated[int, Field(ge=0)] = 1
    db_pool_max_size: Annotated[int, Field(ge=1)] = 10
    # How long a request waits for a pool connection before it answers 503
    db_pool_timeout_s: Annotated[float, Field(gt=0, le=60)] = 5.0
    # How long a session of the pool may sit in a transaction doing nothing before the server ends it and
    # its locks go - a process stuck in one holds no row past it; 0 for none. 0 also drops the server's
    # keepalives where no other timeout is on - in the worker always (it never takes the statement timeout),
    # and with them the ~60 s in which the server frees a dead worker's job row: set them on the role then
    # (docs/uebergabe/konfiguration.md). The longest pause measured on the test suite's synthetic data was 2 s
    # (tools/measure_sessions.py)
    db_idle_in_transaction_timeout_s: Annotated[int, Field(ge=0, le=3600)] = 300
    # How long one statement of the pool's sessions may run, waiting for a lock included, before the server
    # cancels it (an error 500 in the API); 0 for none. The deployment sets 60 for the API; the worker's pool
    # never takes it (app/db/pool.py, worker_pool)
    db_statement_timeout_s: Annotated[int, Field(ge=0, le=3600)] = 0

    @field_validator("database_url")
    @classmethod
    def _usable_connection_string(cls, value: SecretStr) -> SecretStr:
        """Parsed here, so a malformed one stops the start: libpq's own parse error quotes the
        string, password included, and the pool would log it at every attempt."""
        text = value.get_secret_value()
        if not text.strip():
            raise ValueError("must not be blank")
        try:
            parts = conninfo_to_dict(text)
        except (psycopg.ProgrammingError, ValueError):  # ValueError: a byte the system could not decode
            raise ValueError("is not a valid PostgreSQL connection string") from None
        # An unencoded @, / or : in the password splits the URL anew without an error: its rest
        # would be taken for the host, the port or the database name
        if _split_by_the_password(parts):
            raise ValueError("does not parse as meant; write @, / and : in the password as %40, %2F and %3A")
        return value


def _split_by_the_password(parts: dict[str, Any]) -> bool:
    """Whether an unencoded @, / or : in the password split the URL into wrong parts.

    The signs: an @ inside the host (a leading one names an abstract socket); an @ in the
    database name of a URL that kept no user or password (one with them is a name libpq read
    as written); a port that is no number (padding is fine, libpq strips it).
    """
    host = str(parts.get("host", ""))
    database = str(parts.get("dbname", ""))
    ports = str(parts.get("port", "")).split(",")
    return (
        "@" in host[1:]
        or ("@" in database and not (parts.get("user") or parts.get("password")))
        or not all(re.fullmatch(r"[0-9]*", port.strip()) for port in ports)
    )


class ServerSettings(BaseModel):
    # Loopback unless set: the image sets 0.0.0.0, a developer's start stays off the network
    host: str = "127.0.0.1"
    public_port: Port = 8000
    internal_port: Port = 9000
    # The prefix an ingress serves the API under and strips before it forwards (uvicorn's root
    # path): plain segments without a trailing slash; empty for none
    root_path: Annotated[str, Field(pattern=r"^(/[A-Za-z0-9._~-]+)*$")] = ""
    log_level: LogLevel = "INFO"

    @field_validator("log_level", mode="before")
    @classmethod
    def _upper_case_level(cls, value: object) -> object:
        return value.upper() if isinstance(value, str) else value


class AccessSettings(BaseModel):
    # The server's secret for API key hashes (HMAC); the API does not start without it
    api_key_pepper: Annotated[SecretStr, Field(min_length=32)] | None = None
    # What visitors without a token may do: nothing, look up published curricula, or also search
    public_access: Literal["off", "lookup", "search"] = "off"
    # The proxies (ingress, web server) whose X-Forwarded-For names the client: addresses or
    # networks, never "*" - with it every client could name its own address and dodge the limit
    forwarded_allow_ips: str = "127.0.0.1,::1"
    # Failed sign-ins per source (address, IPv6 /64) before its further failures get 429 for
    # the window; only a header in a token's form counts, any other gets 401, uncounted; a valid
    # token always passes
    auth_failure_limit: Annotated[int, Field(ge=1)] = 10
    auth_failure_window_s: Annotated[float, Field(gt=0)] = 900.0

    @field_validator("forwarded_allow_ips")
    @classmethod
    def _proxy_networks(cls, value: str) -> str:
        entries = [entry.strip() for entry in value.split(",")]
        try:
            # strict: 10.42.1.5/16 is no network, and taking it as 10.42.0.0/16 would trust more
            networks = [ipaddress.ip_network(entry, strict=True) for entry in entries]
        except ValueError:
            raise ValueError("must list proxy addresses or networks, comma-separated, never *") from None
        if any(net.prefixlen == 0 for net in networks):
            raise ValueError("must not trust every address (/0): every client could name its own")
        # a single address without its /32 or /128, a network with its prefix
        return ",".join(str(net.network_address) if net.num_addresses == 1 else str(net) for net in networks)


class JobSettings(BaseModel):
    # A job's lease; the worker renews it at a third. A worker gone silent loses its job after this
    job_lease_s: Annotated[float, Field(ge=3, le=3600)] = 60.0
    # How often an idle worker looks for work
    job_poll_s: Annotated[float, Field(gt=0, le=60)] = 1.0
    # How long a stopping worker lets its job run before it hands it back unspent; keep it below
    # the deployment's termination grace period (Kubernetes: 30 s), or the job waits for its lease
    job_shutdown_grace_s: Annotated[float, Field(ge=0, le=3600)] = 20.0
