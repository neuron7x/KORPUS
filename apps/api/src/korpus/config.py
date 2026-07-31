from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from pydantic import Field, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

from korpus.application.calibration import CalibrationProfile


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
    schema_mode: str = "auto"
    object_root: Path = Path("./var/objects")
    audit_anchor_path: Path = Path("./var/audit-anchor.json")
    audit_hmac_key: str = "replace-local-audit-key"
    audit_hmac_key_file: Path | None = None

    auth_mode: str = "dev"
    jwt_secret: str = "replace-local-jwt-secret"
    jwt_secret_file: Path | None = None
    jwt_issuer: str = "korpus-local"
    jwt_audience: str = "korpus-api"
    jwt_max_lifetime_minutes: int = Field(default=120, ge=5, le=1440)
    oidc_jwks_url: str | None = None
    oidc_algorithms: str = "RS256,ES256"
    dev_subject: str = "local-admin"
    dev_roles: str = "admin,curator,reviewer,instructor,user,auditor"
    dev_clearance: str = "restricted"
    dev_corpora: str = "public,training,administrative,restricted-demo"

    answer_policy_mode: str = "development"
    calibration_profile_path: Path | None = None
    min_retrieval_score: float = Field(0.18, ge=0, le=1)
    min_query_coverage: float = Field(0.25, ge=0, le=1)
    min_support_score: float = Field(0.18, ge=0, le=1)
    retrieval_candidate_budget: int = Field(default=256, ge=8, le=10_000)
    retrieval_timeout_ms: int = Field(default=1200, ge=10, le=60_000)
    retrieval_cache_entries: int = Field(default=512, ge=1, le=100_000)
    retrieval_cache_ttl_seconds: float = Field(default=30.0, gt=0, le=3600)
    review_separation_required: bool = False

    max_upload_bytes: int = Field(default=50 * 1024 * 1024, ge=1024, le=500 * 1024 * 1024)
    max_pdf_pages: int = Field(default=500, ge=1, le=10_000)
    max_spans_per_document: int = Field(default=20_000, ge=1, le=100_000)
    max_chunk_chars: int = Field(default=1400, ge=100, le=12_000)
    chunk_overlap_chars: int = Field(default=180, ge=0, le=4000)
    ocr_enabled: bool = True
    ocr_languages: str = "ukr+eng"
    cors_origins: str = "http://127.0.0.1:3000,http://localhost:3000"

    @field_validator("schema_mode")
    @classmethod
    def validate_schema_mode(cls, value: str) -> str:
        if value not in {"auto", "migrations"}:
            raise ValueError("schema_mode must be auto or migrations")
        return value

    @field_validator("auth_mode")
    @classmethod
    def validate_auth_mode(cls, value: str) -> str:
        if value not in {"dev", "jwt", "oidc"}:
            raise ValueError("auth_mode must be dev, jwt, or oidc")
        return value

    @field_validator("answer_policy_mode")
    @classmethod
    def validate_policy_mode(cls, value: str) -> str:
        if value not in {"development", "calibrated"}:
            raise ValueError("answer_policy_mode must be development or calibrated")
        return value

    @model_validator(mode="after")
    def validate_security_and_calibration(self) -> "Settings":
        controlled = self.environment in {"production", "controlled", "isolated"}
        if controlled:
            if self.auth_mode != "oidc":
                raise ValueError("OIDC authentication is required in controlled environments")
            if self.schema_mode != "migrations":
                raise ValueError("controlled environments require migration-managed schema")
            if not self.oidc_jwks_url:
                raise ValueError("OIDC JWKS URL is required")
            if len(self.resolved_audit_hmac_key) < 32 or self.resolved_audit_hmac_key.startswith("replace-"):
                raise ValueError("production audit key is missing or weak")
            if self.answer_policy_mode != "calibrated" or self.calibration_profile_path is None:
                raise ValueError("validated calibration profile is required")
            if not self.review_separation_required:
                raise ValueError("controlled environments require reviewer separation")
        if self.auth_mode == "jwt" and (
            len(self.resolved_jwt_secret) < 32 or self.resolved_jwt_secret.startswith("replace-")
        ):
            raise ValueError("JWT secret is missing or weak")
        if self.chunk_overlap_chars >= self.max_chunk_chars:
            raise ValueError("chunk overlap must be smaller than chunk size")
        if self.answer_policy_mode == "calibrated":
            if self.calibration_profile_path is None or not self.calibration_profile_path.is_file():
                raise ValueError("calibration profile file is missing")
            profile = CalibrationProfile.load(self.calibration_profile_path)
            if not profile.deployment_valid:
                raise ValueError("calibration profile does not satisfy finite-sample risk gate")
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

    @property
    def oidc_algorithm_list(self) -> list[str]:
        return [part.strip() for part in self.oidc_algorithms.split(",") if part.strip()]


@lru_cache
def get_settings() -> Settings:
    return Settings()
