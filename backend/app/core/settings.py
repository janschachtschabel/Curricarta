"""Process settings, read once at start from the environment.

A secret may instead come from a file named by ``<NAME>_FILE`` (Docker and Kubernetes
secrets); the file wins over the plain variable. Errors never echo a value.

The fields stand in parts by concern (app/core/settings_service.py, settings_work.py,
settings_storage.py); what ties two parts together is checked here.
"""

from typing import Self

from pydantic import model_validator
from pydantic_settings import BaseSettings, PydanticBaseSettingsSource, SettingsConfigDict

from app.core.secret_files import SecretFileSource
from app.core.settings_service import AccessSettings, DatabaseSettings, JobSettings, ServerSettings
from app.core.settings_storage import StorageSettings
from app.core.settings_work import (
    REPOSITORY_ONTOLOGY,
    ConversionSettings,
    LimitSettings,
    OntologySettings,
    PipelineSettings,
    RetentionSettings,
    SourceSettings,
)

__all__ = ["REPOSITORY_ONTOLOGY", "Settings"]


class Settings(
    # pydantic takes the fields of the last part first: listed from the last to the first, so that they
    # keep the order of the generated table (app/core/config_doc.py)
    StorageSettings,
    OntologySettings,
    RetentionSettings,
    ConversionSettings,
    SourceSettings,
    PipelineSettings,
    LimitSettings,
    JobSettings,
    AccessSettings,
    ServerSettings,
    DatabaseSettings,
    BaseSettings,
):
    model_config = SettingsConfigDict(hide_input_in_errors=True)

    @classmethod
    def settings_customise_sources(
        cls,
        settings_cls: type[BaseSettings],
        init_settings: PydanticBaseSettingsSource,
        env_settings: PydanticBaseSettingsSource,
        dotenv_settings: PydanticBaseSettingsSource,
        file_secret_settings: PydanticBaseSettingsSource,
    ) -> tuple[PydanticBaseSettingsSource, ...]:
        return init_settings, SecretFileSource(settings_cls), env_settings

    @model_validator(mode="after")
    def _ports_differ(self) -> Self:
        if self.internal_port == self.public_port:
            raise ValueError("internal_port must differ from public_port")
        if self.db_pool_max_size < self.db_pool_min_size:
            raise ValueError("db_pool_max_size must not be smaller than db_pool_min_size")
        if self.storage_backend == "s3" and self.s3_bucket is None:
            raise ValueError("s3_bucket is needed for storage_backend=s3")
        if (self.s3_access_key is None) != (self.s3_secret_key is None):
            raise ValueError("s3_access_key and s3_secret_key come both or neither")
        return self
