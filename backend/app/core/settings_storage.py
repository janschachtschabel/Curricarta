"""The settings of the object store, a part of Settings (app/core/settings.py), and the check of an address
the process calls (the object store here, the language model in app/llm/settings.py)."""

import ipaddress
import re
from pathlib import Path
from typing import Annotated, Literal
from urllib.parse import urlsplit

from pydantic import BaseModel, Field, SecretStr, field_validator

# A DNS label as botocore takes it: letters, digits and "-", not at either end
_HOST_LABEL = re.compile(r"(?!-)[A-Za-z0-9-]{1,63}(?<!-)")
# The address of a service the process calls: the language model, the object store
EndpointUrl = Annotated[str, Field(pattern=r"^https?://[^\s/]+(/\S*)?$")]


def plain_endpoint(value: str) -> str:
    """``value`` if it is http(s)://host[:port][/path]; http for a service inside the cluster.

    A user, a query or a fragment would ride along on every request and into logs.
    """
    parts = urlsplit(value)
    try:
        port_valid = parts.port is None or parts.port > 0
    except ValueError:  # out of range
        port_valid = False
    if not parts.hostname or "@" in parts.netloc or "?" in value or "#" in value or not port_valid:
        raise ValueError("must be http(s)://host[:port][/path], without user, query or fragment")
    return value


def _s3_host(hostname: str) -> bool:
    try:
        ipaddress.ip_address(hostname)
    except ValueError:
        labels = hostname.rstrip(".").split(".")
        return len(hostname) <= 255 and all(_HOST_LABEL.fullmatch(label) for label in labels)
    return True


class StorageSettings(BaseModel):
    # Where objects go: a folder (development, one node) or an S3-compatible service (a cluster)
    storage_backend: Literal["fs", "s3"] = "fs"
    # The folder for the file system store; the store does not open without it
    storage_dir: Path | None = None
    # The S3 service: its address (empty for AWS itself), bucket and region; the keys come both or
    # neither - without them boto3 takes the credentials of the pod or machine
    s3_endpoint_url: EndpointUrl | None = None
    s3_bucket: Annotated[str, Field(pattern=r"^[a-z0-9][a-z0-9.-]{1,61}[a-z0-9]$")] | None = None
    s3_region: Annotated[str, Field(pattern=r"^[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?$")] = "us-east-1"
    s3_access_key: Annotated[SecretStr, Field(min_length=1)] | None = None
    s3_secret_key: Annotated[SecretStr, Field(min_length=1)] | None = None

    @field_validator("s3_endpoint_url", mode="before")
    @classmethod
    def _empty_endpoint_is_aws(cls, value: object) -> object:
        # The Helm values write S3_ENDPOINT_URL: "" for AWS itself; boto3 refuses "" as an address
        return None if value == "" else value

    @field_validator("s3_endpoint_url")
    @classmethod
    def _plain_s3_endpoint(cls, value: str | None) -> str | None:
        if value is None:
            return None
        # boto3 refuses a host name with "_" (a Compose service name may have one) only as it
        # builds the client, quoting the address; here the start stops, naming the setting
        if not _s3_host(urlsplit(plain_endpoint(value)).hostname or ""):
            raise ValueError("must name a host of letters, digits, dots and hyphens, or an IP address")
        return value
