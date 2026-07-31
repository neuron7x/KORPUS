from functools import lru_cache
from pathlib import Path

from pydantic import Field, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


def _read_secret_file(path: Path | None, fallback: str) -> str:
    if path is None:
        return fallback
    value = path.read_text(encoding="utf-8").strip()
    if not value:
        raise ValueError(f"empty secret file: {path}")
    return value


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="KORPUS_", env_file=".env", extra="ignore")

    environment: str = "local"
    database_url: str = "sqlite:///./var/korpus.db"
    object_root: Path = Path("./var/objects")
    audit_hmac_key: str = "replace-local-audit-key"
    audit_hmac_key_file: Path | None = None

    auth_mode: str = "dev"
    jwt_secret: str = "replace-local-jwt-secret"
    jwt_secret_file: Path | None = None
    jwt_issuer: str = "korpus-local"
    jwt_audience: str = "korpus-api"
    dev_subject: str = "local-admin"
    dev_roles: str = "admin,curator,reviewer,instructor,user,auditor"
    dev_clearance: str = "restricted"
    dev_corpora: str = "public,training,administrative,restricted-demo"

    min_retrieval_score: float = Field(0.18, ge=0, le=1)
    min_query_coverage: float = Field(0.25, ge=0, le=1)
    ocr_enabled: bool = True
    ocr_languages: str = "ukr+eng"
    cors_origins: str = "http://127.0.0.1:3000,http://localhost:3000"

    @field_validator("auth_mode")
    @classmethod
    def validate_auth_mode(cls, value: str) -> str:
        if value not in {"dev", "jwt"}:
            raise ValueError("auth_mode must be dev or jwt")
        return value

    @model_validator(mode="after")
    def validate_production_security(self) -> "Settings":
        if self.environment in {"production", "controlled", "isolated"}:
            if self.auth_mode == "dev":
                raise ValueError("dev authentication is forbidden outside local/test environments")
            if len(self.resolved_jwt_secret) < 32 or self.resolved_jwt_secret.startswith("replace-"):
                raise ValueError("production JWT secret is missing or weak")
            if len(self.resolved_audit_hmac_key) < 32 or self.resolved_audit_hmac_key.startswith("replace-"):
                raise ValueError("production audit key is missing or weak")
        return self

    @property
    def resolved_audit_hmac_key(self) -> str:
        return _read_secret_file(self.audit_hmac_key_file, self.audit_hmac_key)

    @property
    def resolved_jwt_secret(self) -> str:
        return _read_secret_file(self.jwt_secret_file, self.jwt_secret)

    @property
    def cors_origin_list(self) -> list[str]:
        return [part.strip() for part in self.cors_origins.split(",") if part.strip()]


@lru_cache
def get_settings() -> Settings:
    return Settings()
