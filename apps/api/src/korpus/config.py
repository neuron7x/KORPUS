from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from urllib.parse import parse_qs, urlparse

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


def _read_optional_secret_file(path: Path | None, fallback: str | None) -> str | None:
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
    database_pool_size: int = Field(default=8, ge=1, le=128)
    database_max_overflow: int = Field(default=8, ge=0, le=256)
    database_pool_timeout_seconds: float = Field(default=10.0, gt=0, le=120)
    database_pool_recycle_seconds: int = Field(default=1800, ge=30, le=86400)
    database_connect_timeout_seconds: int = Field(default=5, ge=1, le=60)
    database_statement_timeout_ms: int = Field(default=30_000, ge=100, le=600_000)
    database_lock_timeout_ms: int = Field(default=5_000, ge=100, le=120_000)
    schema_mode: str = "auto"
    object_root: Path = Path("./var/objects")
    object_store_mode: str = "local"
    s3_bucket: str | None = None
    s3_prefix: str = "objects"
    s3_endpoint_url: str | None = None
    s3_region: str | None = None
    s3_governance_retention_days: int = Field(default=0, ge=0, le=36500)
    s3_force_path_style: bool = False
    s3_connect_timeout_seconds: float = Field(default=3.0, gt=0, le=30)
    s3_read_timeout_seconds: float = Field(default=15.0, gt=0, le=120)
    s3_max_attempts: int = Field(default=4, ge=1, le=10)
    audit_anchor_mode: str = "file"
    audit_anchor_path: Path = Path("./var/audit-anchor.json")
    audit_anchor_url: str | None = None
    audit_anchor_token: str | None = None
    audit_anchor_token_file: Path | None = None
    audit_anchor_timeout_seconds: float = Field(default=5.0, gt=0, le=30)
    audit_reconcile_interval_seconds: float = Field(default=2.0, ge=0.2, le=60)
    audit_reconcile_batch_size: int = Field(default=64, ge=1, le=10_000)
    audit_max_pending_events: int = Field(default=64, ge=0, le=1_000_000)
    audit_max_pending_age_seconds: float = Field(default=30.0, ge=0, le=86_400)
    audit_hmac_key: str = "replace-local-audit-key"
    audit_hmac_key_file: Path | None = None

    auth_mode: str = "disabled"
    bind_host: str = "127.0.0.1"
    dev_mode_acknowledgement: str | None = None
    jwt_secret: str = "replace-local-jwt-secret"
    jwt_secret_file: Path | None = None
    jwt_issuer: str = "korpus-local"
    jwt_audience: str = "korpus-api"
    jwt_max_lifetime_minutes: int = Field(default=120, ge=5, le=1440)
    oidc_jwks_url: str | None = None
    oidc_algorithms: str = "RS256,ES256"
    oidc_jwks_cache_seconds: int = Field(default=300, ge=30, le=86400)
    oidc_http_timeout_seconds: float = Field(default=5.0, gt=0, le=30)
    oidc_clock_skew_seconds: int = Field(default=30, ge=0, le=300)
    oidc_required_acr: str | None = None
    oidc_require_mfa: bool = False
    oidc_max_auth_age_seconds: int = Field(default=3600, ge=60, le=86400)
    oidc_authorization_endpoint: str | None = None
    oidc_token_endpoint: str | None = None
    oidc_end_session_endpoint: str | None = None
    oidc_client_id: str | None = None
    oidc_client_secret: str | None = None
    oidc_client_secret_file: Path | None = None
    oidc_redirect_uri: str | None = None
    oidc_scopes: str = "openid profile"
    browser_auth_enabled: bool = False
    browser_session_key: str | None = None
    browser_session_key_file: Path | None = None
    browser_session_ttl_seconds: int = Field(default=1800, ge=300, le=43200)
    browser_flow_ttl_seconds: int = Field(default=600, ge=60, le=1800)
    browser_cookie_secure: bool = True
    browser_session_cookie: str = "__Host-korpus_session"
    browser_flow_cookie: str = "__Host-korpus_flow"
    browser_csrf_cookie: str = "__Host-korpus_csrf"
    entitlement_profile_path: Path | None = None
    entitlement_profile_sha256: str | None = Field(default=None, pattern=r"^[a-f0-9]{64}$")
    source_trust_profile_path: Path | None = None
    source_trust_profile_sha256: str | None = Field(default=None, pattern=r"^[a-f0-9]{64}$")
    require_source_signatures: bool = False
    reviewer_registry_path: Path | None = None
    reviewer_registry_sha256: str | None = Field(default=None, pattern=r"^[a-f0-9]{64}$")
    corpus_governance_profile_path: Path | None = None
    corpus_governance_profile_sha256: str | None = Field(default=None, pattern=r"^[a-f0-9]{64}$")
    dev_subject: str = "local-user"
    dev_roles: str = "user"
    dev_clearance: str = "public"
    dev_corpora: str = "public"
    dev_compartments: str = ""

    answer_policy_mode: str = "development"
    calibration_profile_path: Path | None = None
    calibration_profile_sha256: str | None = Field(default=None, pattern=r"^[a-f0-9]{64}$")
    calibration_dataset_path: Path | None = None
    calibration_system_manifest_path: Path | None = None
    calibration_evaluation_protocol_path: Path | None = None
    min_retrieval_score: float = Field(0.18, ge=0, le=1)
    min_query_coverage: float = Field(0.25, ge=0, le=1)
    min_support_score: float = Field(0.18, ge=0, le=1)
    retrieval_candidate_budget: int = Field(default=256, ge=8, le=10_000)
    retrieval_timeout_ms: int = Field(default=1200, ge=10, le=60_000)
    semantic_retrieval_enabled: bool = False
    semantic_weight: float = Field(default=0.0, ge=0, le=0.30)
    embedding_endpoint: str | None = None
    embedding_model_id: str | None = None
    embedding_dimensions: int = Field(default=768, ge=8, le=4000)
    embedding_token: str | None = None
    embedding_token_file: Path | None = None
    embedding_timeout_seconds: float = Field(default=5.0, gt=0, le=30)
    embedding_max_attempts: int = Field(default=3, ge=1, le=8)
    embedding_max_response_bytes: int = Field(default=2 * 1024 * 1024, ge=1024, le=20 * 1024 * 1024)
    retrieval_cache_entries: int = Field(default=512, ge=1, le=100_000)
    retrieval_cache_ttl_seconds: float = Field(default=30.0, gt=0, le=3600)
    max_concurrent_answers: int = Field(default=16, ge=1, le=4096)
    max_concurrent_ingestions: int = Field(default=2, ge=1, le=128)
    ingestion_mode: str = "synchronous"
    ingestion_job_max_attempts: int = Field(default=3, ge=1, le=20)
    ingestion_job_lease_seconds: int = Field(default=300, ge=30, le=7200)
    quarantine_object_root: Path = Path("./var/quarantine")
    s3_quarantine_prefix: str = "quarantine"
    metrics_enabled: bool = True
    metrics_token: str | None = None
    metrics_token_file: Path | None = None
    otlp_endpoint: str | None = None
    service_name: str = "korpus-api"
    admission_wait_ms: int = Field(default=50, ge=0, le=10_000)
    ingestion_wait_ms: int = Field(default=100, ge=0, le=10_000)
    review_separation_required: bool = False

    max_upload_bytes: int = Field(default=50 * 1024 * 1024, ge=1024, le=500 * 1024 * 1024)
    malware_scan_mode: str = "disabled"
    clamd_host: str = "clamav"
    clamd_port: int = Field(default=3310, ge=1, le=65535)
    malware_scan_timeout_seconds: float = Field(default=30.0, gt=0, le=300)
    parser_sandbox_enabled: bool = False
    parser_timeout_seconds: int = Field(default=120, ge=5, le=900)
    parser_memory_limit_mb: int = Field(default=768, ge=128, le=8192)
    parser_output_limit_bytes: int = Field(default=64 * 1024 * 1024, ge=1024 * 1024, le=256 * 1024 * 1024)
    ocr_total_timeout_seconds: int = Field(default=300, ge=10, le=3600)
    max_pdf_pages: int = Field(default=500, ge=1, le=10_000)
    max_spans_per_document: int = Field(default=20_000, ge=1, le=100_000)
    max_chunk_chars: int = Field(default=1400, ge=100, le=12_000)
    chunk_overlap_chars: int = Field(default=180, ge=0, le=4000)
    ocr_enabled: bool = True
    ocr_languages: str = "ukr+eng"
    cors_origins: str = "http://127.0.0.1:3000,http://localhost:3000"
    trusted_hosts: str = "localhost,127.0.0.1,testserver"

    @field_validator("environment")
    @classmethod
    def validate_environment(cls, value: str) -> str:
        allowed = {"local", "test", "development", "production", "controlled", "isolated"}
        if value not in allowed:
            raise ValueError(f"environment must be one of {sorted(allowed)}")
        return value

    @field_validator("audit_anchor_mode")
    @classmethod
    def validate_audit_anchor_mode(cls, value: str) -> str:
        if value not in {"file", "http"}:
            raise ValueError("audit_anchor_mode must be file or http")
        return value

    @field_validator("object_store_mode")
    @classmethod
    def validate_object_store_mode(cls, value: str) -> str:
        if value not in {"local", "s3"}:
            raise ValueError("object_store_mode must be local or s3")
        return value

    @field_validator("schema_mode")
    @classmethod
    def validate_schema_mode(cls, value: str) -> str:
        if value not in {"auto", "migrations"}:
            raise ValueError("schema_mode must be auto or migrations")
        return value

    @field_validator("auth_mode")
    @classmethod
    def validate_auth_mode(cls, value: str) -> str:
        if value not in {"disabled", "dev", "jwt", "oidc"}:
            raise ValueError("auth_mode must be disabled, dev, jwt, or oidc")
        return value

    @field_validator("ingestion_mode")
    @classmethod
    def validate_ingestion_mode(cls, value: str) -> str:
        if value not in {"synchronous", "durable_async"}:
            raise ValueError("ingestion_mode must be synchronous or durable_async")
        return value

    @field_validator("malware_scan_mode")
    @classmethod
    def validate_malware_scan_mode(cls, value: str) -> str:
        if value not in {"disabled", "clamd"}:
            raise ValueError("malware_scan_mode must be disabled or clamd")
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
        if self.auth_mode == "dev":
            if self.environment not in {"local", "test", "development"}:
                raise ValueError("OIDC authentication is required in controlled environments; dev authentication is forbidden")
            if self.dev_mode_acknowledgement != "I_ACKNOWLEDGE_DEV_AUTH_IS_INSECURE":
                raise ValueError("dev authentication requires explicit acknowledgement")
            if self.bind_host not in {"127.0.0.1", "::1", "localhost", "testserver"}:
                raise ValueError("dev authentication requires loopback-only binding")
        if self.auth_mode == "disabled" and controlled:
            raise ValueError("controlled environments cannot disable authentication")
        if controlled:
            if not self.database_url.startswith("postgresql"):
                raise ValueError("controlled environments require PostgreSQL")
            database_query = parse_qs(urlparse(self.database_url.replace("postgresql+psycopg", "postgresql", 1)).query)
            if database_query.get("sslmode", [""])[0] != "verify-full":
                raise ValueError("controlled PostgreSQL connections require sslmode=verify-full")
            if self.auth_mode != "oidc":
                raise ValueError("OIDC authentication is required in controlled environments")
            if self.schema_mode != "migrations":
                raise ValueError("controlled environments require migration-managed schema")
            if not self.oidc_jwks_url:
                raise ValueError("OIDC JWKS URL is required")
            if not self.browser_auth_enabled:
                raise ValueError("controlled environments require browser OIDC/BFF authentication")
            required_browser = {
                "authorization endpoint": self.oidc_authorization_endpoint,
                "token endpoint": self.oidc_token_endpoint,
                "client id": self.oidc_client_id,
                "redirect URI": self.oidc_redirect_uri,
            }
            browser_missing = [name for name, value in required_browser.items() if not value]
            if browser_missing:
                raise ValueError(f"browser OIDC settings are missing: {', '.join(browser_missing)}")
            if not self.resolved_browser_session_key or len(self.resolved_browser_session_key) < 32:
                raise ValueError("controlled browser sessions require a strong session key")
            if not self.browser_cookie_secure:
                raise ValueError("controlled browser session cookies must be Secure")
            if not self.oidc_redirect_uri.startswith("https://"):
                raise ValueError("controlled OIDC redirect URI must use HTTPS")
            if self.entitlement_profile_path is None or not self.entitlement_profile_path.is_file():
                raise ValueError("controlled environments require a server-side entitlement profile")
            if not self.entitlement_profile_sha256:
                raise ValueError("controlled environments require an entitlement profile digest")
            if not self.require_source_signatures:
                raise ValueError("controlled environments require detached source signatures")
            if self.source_trust_profile_path is None or not self.source_trust_profile_path.is_file():
                raise ValueError("controlled environments require a source trust profile")
            if not self.source_trust_profile_sha256:
                raise ValueError("controlled environments require a source trust profile digest")
            if self.reviewer_registry_path is None or not self.reviewer_registry_path.is_file():
                raise ValueError("controlled environments require a reviewer credential registry")
            if not self.reviewer_registry_sha256:
                raise ValueError("controlled environments require a reviewer registry digest")
            if self.corpus_governance_profile_path is None or not self.corpus_governance_profile_path.is_file():
                raise ValueError("controlled environments require a corpus governance profile")
            if not self.corpus_governance_profile_sha256:
                raise ValueError("controlled environments require a corpus governance profile digest")
            if len(self.resolved_audit_hmac_key) < 32 or self.resolved_audit_hmac_key.startswith("replace-"):
                raise ValueError("production audit key is missing or weak")
            if self.answer_policy_mode != "calibrated" or self.calibration_profile_path is None:
                raise ValueError("validated calibration profile is required")
            if not self.review_separation_required:
                raise ValueError("controlled environments require reviewer separation")
            if self.audit_anchor_mode != "http" or not self.audit_anchor_url:
                raise ValueError("controlled environments require a remote HTTP audit anchor")
            if not self.resolved_audit_anchor_token:
                raise ValueError("controlled environments require audit anchor authentication")
            if not self.metrics_enabled:
                raise ValueError("controlled environments require operational metrics")
            if not self.resolved_metrics_token:
                raise ValueError("controlled environments require an authenticated metrics endpoint")
            if any(origin == "*" or not origin.startswith("https://") for origin in self.cors_origin_list):
                raise ValueError("controlled CORS origins must be explicit HTTPS origins")
            if not self.trusted_host_list or "*" in self.trusted_host_list:
                raise ValueError("controlled environments require explicit trusted hosts")
            if self.s3_endpoint_url and not self.s3_endpoint_url.startswith("https://"):
                raise ValueError("controlled S3 endpoints must use HTTPS")
            if self.s3_governance_retention_days < 1:
                raise ValueError("controlled object storage requires governance retention")
            if self.ingestion_mode != "durable_async":
                raise ValueError("controlled environments require durable asynchronous ingestion")
            if self.malware_scan_mode != "clamd":
                raise ValueError("controlled environments require fail-closed malware scanning")
            if not self.parser_sandbox_enabled:
                raise ValueError("controlled environments require parser process isolation")
            if self.otlp_endpoint and not self.otlp_endpoint.startswith("https://"):
                raise ValueError("controlled OTLP endpoints must use HTTPS")
        if self.browser_auth_enabled:
            if self.auth_mode != "oidc":
                raise ValueError("browser authentication requires OIDC mode")
            required = [self.oidc_authorization_endpoint, self.oidc_token_endpoint, self.oidc_client_id, self.oidc_redirect_uri]
            if any(not value for value in required):
                raise ValueError("browser OIDC endpoints, client id, and redirect URI are required")
            if not self.resolved_browser_session_key or len(self.resolved_browser_session_key) < 32:
                raise ValueError("browser session key must contain at least 32 characters")
            if not self.oidc_authorization_endpoint.startswith("https://") or not self.oidc_token_endpoint.startswith("https://"):
                raise ValueError("OIDC browser endpoints must use HTTPS")
            if not self.oidc_redirect_uri.startswith(("https://", "http://127.0.0.1", "http://localhost", "http://testserver")):
                raise ValueError("OIDC redirect URI must be HTTPS or an explicit loopback test URI")
        if self.semantic_retrieval_enabled:
            if not self.database_url.startswith("postgresql"):
                raise ValueError("semantic retrieval requires PostgreSQL/pgvector")
            if not self.embedding_endpoint or not self.embedding_model_id:
                raise ValueError("semantic retrieval requires embedding endpoint and model id")
            if self.semantic_weight <= 0 and self.answer_policy_mode == "development":
                raise ValueError("semantic retrieval requires a positive semantic weight")
            if controlled and not self.embedding_endpoint.startswith("https://"):
                raise ValueError("controlled embedding endpoints must use HTTPS")
            if controlled and not self.resolved_embedding_token:
                raise ValueError("controlled embedding integration requires authentication")
        elif self.semantic_weight != 0:
            raise ValueError("semantic weight must be zero when semantic retrieval is disabled")
        if self.audit_anchor_mode == "http" and not self.audit_anchor_url:
            raise ValueError("audit_anchor_url is required for HTTP audit anchoring")
        if self.object_store_mode == "s3" and not self.s3_bucket:
            raise ValueError("s3_bucket is required for S3 object storage")
        if controlled and self.object_store_mode == "local":
            raise ValueError("controlled environments require durable S3-compatible object storage")
        if self.auth_mode == "jwt" and (
            len(self.resolved_jwt_secret) < 32 or self.resolved_jwt_secret.startswith("replace-")
        ):
            raise ValueError("JWT secret is missing or weak")
        if self.chunk_overlap_chars >= self.max_chunk_chars:
            raise ValueError("chunk overlap must be smaller than chunk size")
        if self.entitlement_profile_path is not None:
            from korpus.security.entitlements import EntitlementProfile
            EntitlementProfile.load(self.entitlement_profile_path, self.entitlement_profile_sha256)
        if self.source_trust_profile_path is not None:
            from korpus.security.source_authenticity import SourceTrustProfile
            SourceTrustProfile.load(self.source_trust_profile_path, self.source_trust_profile_sha256)
        if self.require_source_signatures and self.source_trust_profile_path is None:
            raise ValueError("source signatures require a source trust profile")
        if self.reviewer_registry_path is not None:
            from korpus.security.reviewers import ReviewerRegistry
            ReviewerRegistry.load(self.reviewer_registry_path, self.reviewer_registry_sha256)
        if self.corpus_governance_profile_path is not None:
            from korpus.security.corpus_governance import CorpusGovernanceProfile
            CorpusGovernanceProfile.load(
                self.corpus_governance_profile_path, self.corpus_governance_profile_sha256
            )
        if self.answer_policy_mode == "calibrated":
            required_artifacts = {
                "profile": self.calibration_profile_path,
                "dataset": self.calibration_dataset_path,
                "system manifest": self.calibration_system_manifest_path,
                "evaluation protocol": self.calibration_evaluation_protocol_path,
            }
            missing = [name for name, path in required_artifacts.items() if path is None or not path.is_file()]
            if missing:
                raise ValueError(f"calibration artifacts are missing: {', '.join(missing)}")
            if not self.calibration_profile_sha256:
                raise ValueError("calibration profile digest is required")
            profile = CalibrationProfile.load(
                self.calibration_profile_path, expected_sha256=self.calibration_profile_sha256
            )
            profile.validate_artifact_bindings(
                dataset=self.calibration_dataset_path,
                system_manifest=self.calibration_system_manifest_path,
                evaluation_protocol=self.calibration_evaluation_protocol_path,
            )
            if not profile.deployment_valid:
                raise ValueError("calibration profile does not satisfy finite-sample risk gate")
            if profile.weight_semantic > 0 and not self.semantic_retrieval_enabled:
                raise ValueError("calibration profile requires semantic retrieval but it is disabled")
            if self.semantic_retrieval_enabled and profile.weight_semantic <= 0:
                raise ValueError("semantic retrieval is enabled but calibration assigns zero semantic weight")
        return self

    @property
    def resolved_audit_hmac_key(self) -> str:
        return _read_secret_file(self.audit_hmac_key_file, self.audit_hmac_key)

    @property
    def resolved_jwt_secret(self) -> str:
        return _read_secret_file(self.jwt_secret_file, self.jwt_secret)

    @property
    def resolved_audit_anchor_token(self) -> str | None:
        return _read_optional_secret_file(self.audit_anchor_token_file, self.audit_anchor_token)

    @property
    def resolved_metrics_token(self) -> str | None:
        return _read_optional_secret_file(self.metrics_token_file, self.metrics_token)

    @property
    def resolved_embedding_token(self) -> str | None:
        return _read_optional_secret_file(self.embedding_token_file, self.embedding_token)

    @property
    def resolved_oidc_client_secret(self) -> str | None:
        return _read_optional_secret_file(self.oidc_client_secret_file, self.oidc_client_secret)

    @property
    def resolved_browser_session_key(self) -> str | None:
        return _read_optional_secret_file(self.browser_session_key_file, self.browser_session_key)

    @property
    def oidc_scope_list(self) -> list[str]:
        scopes = [part.strip() for part in self.oidc_scopes.split() if part.strip()]
        if "openid" not in scopes:
            scopes.insert(0, "openid")
        return scopes

    @property
    def cors_origin_list(self) -> list[str]:
        return [part.strip() for part in self.cors_origins.split(",") if part.strip()]

    @property
    def oidc_algorithm_list(self) -> list[str]:
        return [part.strip() for part in self.oidc_algorithms.split(",") if part.strip()]

    @property
    def trusted_host_list(self) -> list[str]:
        return [part.strip() for part in self.trusted_hosts.split(",") if part.strip()]


@lru_cache
def get_settings() -> Settings:
    return Settings()
