from __future__ import annotations

from collections.abc import Mapping
from functools import lru_cache
from pathlib import Path

from pydantic import Field, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

from korpus.config_policy import validate_runtime_settings


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


from korpus.config_namespace import OPERATIONAL_VARIABLES


def unknown_settings_variables(environ: Mapping[str, str]) -> list[str]:
    """`KORPUS_*` names this system does not recognise.

    `SettingsConfigDict(extra="ignore")` drops an unrecognised variable in silence, so
    `KORPUS_REQUIRE_SOURCE_SIGNATURE=true` — singular, and the field is
    `require_source_signatures` — leaves the control off with nothing reported anywhere.
    The deployment reads correct, the review passes, and the signature requirement is
    not in force. Measured 2026-08-06: the typo above constructs cleanly and yields
    `require_source_signatures = False`.

    `extra="forbid"` cannot be the fix, because the operational scripts share the
    namespace and the process environment. So the namespace is checked against the union
    of the fields and the declared operational names, and anything else is named.
    """
    known = {f"KORPUS_{name.upper()}" for name in Settings.model_fields}
    return sorted(
        name
        for name in environ
        if name.startswith("KORPUS_") and name not in known and name not in OPERATIONAL_VARIABLES
    )


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="KORPUS_", env_file=".env", extra="ignore")

    environment: str = "local"
    runtime_role: str = "api"
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
    database_transport: str = "direct_tls"
    gcs_bucket: str | None = None
    gcs_prefix: str = "objects"
    gcs_quarantine_bucket: str | None = None
    gcs_quarantine_prefix: str = "quarantine"
    gcs_retention_seconds: int = Field(default=0, ge=0, le=100 * 365 * 24 * 3600)
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
    gcs_audit_bucket: str | None = None
    gcs_audit_prefix: str = "audit/anchors"
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
    browser_flow_cookie: str = "__Secure-korpus_flow"
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
    #: Predictive Evidence Control (PEC) is profile-governed and defaults to shadow/off.
    pec_enabled: bool = False
    pec_shadow_mode: bool = True
    pec_profile_path: Path | None = None
    pec_profile_sha256: str | None = Field(default=None, pattern=r"^[a-f0-9]{64}$")
    pec_dataset_path: Path | None = None
    pec_system_manifest_path: Path | None = None
    pec_evaluation_protocol_path: Path | None = None
    pec_replay_receipt_path: Path | None = None
    contextual_retrieval_enabled: bool = False
    min_retrieval_score: float = Field(0.18, ge=0, le=1)
    #: Скільки змістовних слів питання мусить нести речення, щоб його показали як
    #: відповідь. Було 0.25 — чверть питання, тобто одне слово з чотирьох. Виміряно
    #: 31.08.2026 на 40 питаннях через живий edge (20 у корпусі, 20 свідомо поза ним):
    #: при 0.25 система відповідала на 17 із 20 чужих питань під зеленим вироком —
    #: «як налаштувати гаманець Ethereum» отримувало обов'язки техніка БпАК. Розподіли
    #: РОЗДІЛЯЮТЬСЯ: у корпусі максимальне покриття claim'а ≥ 0.5 у 18 із 20, поза
    #: корпусом ≤ 0.5 у 16 із 20. Поріг 0.5 лишає 18 із 20 своїх і прибирає 13 із 17
    #: чужих. На замороженому еталоні дерева той самий поріг дає 93/95 проти 89/95 і
    #: supported_answer_rate 0.886 проти 0.861 — тобто платня зібрана з відмов, а не з
    #: правильних відповідей. Ціна названа: answer_yield 0.937 → 0.911.
    min_query_coverage: float = Field(0.5, ge=0, le=1)
    min_support_score: float = Field(0.18, ge=0, le=1)
    #: Optional model assistance; evidence admission remains deterministic.
    answer_composer_enabled: bool = False
    query_planner_enabled: bool = False
    query_planner_provider: str = "openai"
    query_planner_api_key: str = ""
    query_planner_api_key_file: Path | None = None
    query_planner_model: str = "gpt-5.6-sol"
    query_planner_base_url: str = ""
    query_planner_timeout_seconds: float = Field(default=6.0, gt=0, le=30)
    model_egress_posture: str = "external_allowed"
    #: GOV-006: highest corpus tier permitted to leave the deployment.
    model_egress_max_tier: str = "public"
    #: Paid access only narrows policy-authorized corpora.
    subscription_required: bool = False
    free_corpora: str = ""
    #: Signed, policy-fresh evidence snapshot for disconnected operation.
    offline_pack_enabled: bool = False
    offline_pack_signing_key_file: Path | None = None
    offline_pack_key_id: str = Field(default="offline-pack-v1", min_length=3, max_length=120)
    offline_pack_ttl_seconds: int = Field(default=24 * 3600, ge=60, le=7 * 24 * 3600)
    offline_pack_max_spans: int = Field(default=5000, ge=1, le=100_000)
    #: Deterministic test-provider secret; empty disables that provider.
    billing_webhook_secret: str = ""
    billing_webhook_secret_file: Path | None = None
    #: Production LiqPay adapter; both keys are required together.
    liqpay_public_key: str = ""
    liqpay_private_key: str = ""
    liqpay_private_key_file: Path | None = None
    liqpay_signature_algorithm: str = "sha3_256"
    billing_public_base_url: str = ""
    #: Optional server-owned sellable plan materialized at startup.
    billing_plan_code: str = ""
    billing_plan_name: str = "KORPUS"
    billing_plan_price_minor: int | None = Field(default=None, ge=1, le=100_000_000)
    billing_plan_currency: str = "UAH"
    billing_plan_interval: str = "monthly"
    billing_plan_corpora: str = ""
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
    parser_output_limit_bytes: int = Field(
        default=64 * 1024 * 1024, ge=1024 * 1024, le=256 * 1024 * 1024
    )
    ocr_total_timeout_seconds: int = Field(default=300, ge=10, le=3600)
    # 500 сиділа ВСЕРЕДИНІ реального розподілу, а не над ним. Виміряно 2026-08-29 на 57
    # захоплених PDF каталогу: 504 · 492 · 480 · 460 · 432 — чотири документи в межах 8%
    # від стелі, і один за нею. За нею опинився Статут внутрішньої служби ЗСУ: 504
    # сторінки, тобто основний документ, за яким військовослужбовець питає про свої права,
    # не входив у корпус через чотири сторінки. Стеля, що стоїть усередині робочого
    # діапазону, — не запобіжник, а підкидання монети: наступна редакція будь-якого з
    # чотирьох перетне її. 1000 — удвічі вище виміряного максимуму й удесятеро нижче
    # верхньої межі схеми, тож запобіжник від вичерпання пам'яті лишається запобіжником.
    max_pdf_pages: int = Field(default=1000, ge=1, le=10_000)
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

    @field_validator("runtime_role")
    @classmethod
    def validate_runtime_role(cls, value: str) -> str:
        allowed = {"api", "worker", "tool"}
        if value not in allowed:
            raise ValueError(f"runtime_role must be one of {sorted(allowed)}")
        return value

    @field_validator("audit_anchor_mode")
    @classmethod
    def validate_audit_anchor_mode(cls, value: str) -> str:
        if value not in {"file", "http", "gcs"}:
            raise ValueError("audit_anchor_mode must be file, http, or gcs")
        return value

    @field_validator("object_store_mode")
    @classmethod
    def validate_object_store_mode(cls, value: str) -> str:
        if value not in {"local", "s3", "gcs"}:
            raise ValueError("object_store_mode must be local, s3, or gcs")
        return value

    @field_validator("database_transport")
    @classmethod
    def validate_database_transport(cls, value: str) -> str:
        if value not in {"direct_tls", "cloud_sql_socket"}:
            raise ValueError("database_transport must be direct_tls or cloud_sql_socket")
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

    @field_validator("model_egress_posture")
    @classmethod
    def validate_model_egress_posture(cls, value: str) -> str:
        permitted = {"external_allowed", "local_only", "model_disabled"}
        if value not in permitted:
            raise ValueError(f"model_egress_posture must be one of {sorted(permitted)}")
        return value

    @field_validator("model_egress_max_tier")
    @classmethod
    def validate_model_egress_max_tier(cls, value: str) -> str:
        from korpus.domain.models import AccessTier

        try:
            AccessTier.parse(value)
        except (KeyError, ValueError) as error:
            permitted = ", ".join(tier.label() for tier in AccessTier)
            raise ValueError(f"model_egress_max_tier must be one of {permitted}") from error
        return value

    @model_validator(mode="after")
    def validate_security_and_calibration(self) -> Settings:
        validate_runtime_settings(self)
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
    def resolved_billing_webhook_secret(self) -> str | None:
        return _read_optional_secret_file(
            self.billing_webhook_secret_file, self.billing_webhook_secret or None
        )

    @property
    def resolved_liqpay_private_key(self) -> str | None:
        return _read_optional_secret_file(
            self.liqpay_private_key_file, self.liqpay_private_key or None
        )

    @property
    def billing_plan_corpus_set(self) -> frozenset[str]:
        return frozenset(
            part.strip() for part in self.billing_plan_corpora.split(",") if part.strip()
        )

    @property
    def free_corpus_set(self) -> frozenset[str]:
        return frozenset(part.strip() for part in self.free_corpora.split(",") if part.strip())

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
