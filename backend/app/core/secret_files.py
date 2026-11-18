"""A secret setting read from the file its ``<NAME>_FILE`` names (Docker and Kubernetes secrets): the source
the settings classes put before the plain variables (app/core/settings.py, app/llm/settings.py)."""

import os
from collections.abc import Mapping
from pathlib import Path
from typing import Annotated, Any, get_args, get_origin

from pydantic import SecretStr
from pydantic.fields import FieldInfo
from pydantic_settings import PydanticBaseSettingsSource


class SecretFileSource(PydanticBaseSettingsSource):
    """Reads each secret field (``SecretStr``, optional or not) from the file its ``<NAME>_FILE`` names.

    The file is UTF-8; a byte order mark and the final line end are not part of the secret.
    """

    def get_field_value(self, field: FieldInfo, field_name: str) -> tuple[Any, str, bool]:
        variable = f"{field_name.upper()}_FILE"
        path = environment_value(variable) if is_secret(field.annotation) else None
        if not path:
            return None, field_name, False
        try:
            content = Path(path).read_text(encoding="utf-8-sig")
        except OSError as error:
            raise ValueError(f"{variable} names a file that cannot be read: {error.strerror}") from None
        except UnicodeDecodeError:  # its message quotes a byte of the secret
            raise ValueError(f"{variable} names a file that is not UTF-8 text") from None
        return content.rstrip("\r\n"), field_name, False

    def __call__(self) -> dict[str, Any]:
        values: dict[str, Any] = {}
        for name, field in self.settings_cls.model_fields.items():
            value, key, _ = self.get_field_value(field, name)
            if value is not None:
                values[key] = value
        return values


def is_secret(annotation: object) -> bool:
    """``SecretStr`` itself, constrained (``Annotated``) or optional (``... | None``)."""
    if annotation is SecretStr:
        return True
    if get_origin(annotation) is Annotated:
        return is_secret(get_args(annotation)[0])
    return any(is_secret(argument) for argument in get_args(annotation))


def environment_value(name: str, environment: Mapping[str, str] = os.environ) -> str | None:
    """``name`` in the environment in any case, as pydantic matches the plain variables."""
    if name in environment:
        return environment[name]
    return next((value for key, value in environment.items() if key.upper() == name), None)
