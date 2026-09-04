from __future__ import annotations

import json
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from urllib.parse import unquote, urlsplit

import httpx

from korpus.application.capability_gateway.adapters import (
    AdapterExecutionFailed,
    AdapterExecutionResult,
)
from korpus.application.capability_gateway.contracts import payload_digest
from korpus.application.capability_gateway.evidence import (
    EvidenceBinding,
    EvidenceEnvelope,
    EvidenceProvenance,
    EvidenceStatus,
    ProvenanceKind,
)
from korpus.application.capability_gateway.types import (
    CapabilitySpec,
    EffectClass,
    EvidenceProfile,
    IntegrationRequest,
    InvocationContext,
    ProviderType,
)

_FORBIDDEN_HEADERS = frozenset(
    {
        "connection",
        "content-length",
        "host",
        "proxy-authenticate",
        "proxy-authorization",
        "transfer-encoding",
        "upgrade",
    }
)


@dataclass(frozen=True, slots=True)
class HttpReadPlan:
    """Server-derived HTTP request shape; callers never supply a URL or method."""

    path: str
    query: tuple[tuple[str, str], ...] = ()


HttpReadPlanBuilder = Callable[[Mapping[str, object], str], HttpReadPlan]


class GovernedHttpReadAdapter:
    """Bounded same-origin HTTPS GET adapter for READ_REMOTE capabilities.

    The adapter deliberately does not implement writes. Generic HTTP cannot infer whether
    a timeout or arbitrary 4xx/5xx response proves that a provider-side effect did not
    commit; effectful providers require a provider-specific adapter with explicit commit
    and reconciliation semantics.
    """

    def __init__(
        self,
        *,
        client: httpx.Client,
        base_url: str,
        plan_builder: HttpReadPlanBuilder,
        headers: Mapping[str, str] | None = None,
    ) -> None:
        self._client = client
        self._base = self._validate_base_url(base_url)
        self._plan_builder = plan_builder
        self._headers = self._validate_headers(headers or {})

    def execute(
        self,
        *,
        spec: CapabilitySpec,
        request: IntegrationRequest,
        context: InvocationContext,
        logical_resource: str,
    ) -> AdapterExecutionResult:
        self._validate_spec(spec)
        try:
            plan = self._plan_builder(request.input, logical_resource)
            url = self._resolve_url(plan.path)
            query = self._validate_query(plan.query)
        except (TypeError, ValueError, RuntimeError) as exc:
            raise AdapterExecutionFailed("HTTP request plan rejected") from exc

        timeout = spec.timeouts.total_ms / 1000.0
        try:
            with self._client.stream(
                "GET",
                url,
                params=query,
                headers=self._headers,
                timeout=timeout,
                follow_redirects=False,
            ) as response:
                if 300 <= response.status_code < 400:
                    raise AdapterExecutionFailed("HTTP redirect refused")
                if not 200 <= response.status_code < 300:
                    raise AdapterExecutionFailed("HTTP provider returned non-success status")
                self._validate_content_type(response)
                body = self._read_bounded(response, spec.data_policy.max_response_bytes)
        except AdapterExecutionFailed:
            raise
        except httpx.TransportError as exc:
            raise AdapterExecutionFailed("HTTP provider unavailable") from exc

        try:
            output = json.loads(body)
            output_digest = payload_digest(output)
        except (TypeError, ValueError, RuntimeError) as exc:
            raise AdapterExecutionFailed("HTTP provider returned invalid JSON") from exc

        evidence = self._evidence(spec, context, output_digest, url)
        return AdapterExecutionResult(output=output, evidence=evidence)

    @staticmethod
    def _validate_base_url(base_url: str) -> httpx.URL:
        candidate = httpx.URL(base_url)
        if candidate.scheme != "https" or not candidate.host:
            raise ValueError("HTTP capability base URL must be absolute HTTPS")
        if candidate.userinfo or candidate.query or candidate.fragment:
            raise ValueError("HTTP capability base URL cannot contain credentials, query, or fragment")
        decoded = unquote(candidate.path)
        if "\\" in decoded or any(segment in {".", ".."} for segment in decoded.split("/")):
            raise ValueError("HTTP capability base URL contains unsafe path segments")
        return candidate

    @staticmethod
    def _validate_headers(headers: Mapping[str, str]) -> dict[str, str]:
        result: dict[str, str] = {}
        for name, value in headers.items():
            if not isinstance(name, str) or not isinstance(value, str):
                raise ValueError("HTTP capability headers must be strings")
            normalized = name.strip().lower()
            if not normalized or normalized in _FORBIDDEN_HEADERS:
                raise ValueError(f"HTTP capability header is forbidden: {name}")
            if any(char in name or char in value for char in ("\r", "\n", "\x00")):
                raise ValueError("HTTP capability headers contain control characters")
            result[name] = value
        return result

    @staticmethod
    def _validate_spec(spec: CapabilitySpec) -> None:
        if spec.provider_type is not ProviderType.HTTP:
            raise AdapterExecutionFailed("HTTP adapter requires provider_type=http")
        if spec.effect_class is not EffectClass.READ_REMOTE:
            raise AdapterExecutionFailed("generic HTTP adapter is read-only")
        if spec.evidence.profile not in {
            EvidenceProfile.NONE,
            EvidenceProfile.EXECUTION_ONLY,
            EvidenceProfile.PROVIDER_PROVENANCE,
        }:
            raise AdapterExecutionFailed(
                "generic HTTP adapter cannot manufacture factual or signed evidence"
            )

    def _resolve_url(self, path: str) -> httpx.URL:
        if not path:
            raise ValueError("HTTP capability path is empty")
        parsed = urlsplit(path)
        if parsed.scheme or parsed.netloc or parsed.query or parsed.fragment:
            raise ValueError("HTTP capability path must contain path data only")
        decoded = unquote(parsed.path)
        if (
            "\\" in decoded
            or any(ord(char) < 32 for char in decoded)
            or any(segment in {".", ".."} for segment in decoded.split("/"))
        ):
            raise ValueError("HTTP capability path is invalid")

        base_path = self._base.path.rstrip("/")
        relative_path = parsed.path.lstrip("/")
        joined_path = f"{base_path}/{relative_path}" if relative_path else base_path or "/"
        candidate = self._base.copy_with(path=joined_path, query=None, fragment=None)
        if (
            candidate.scheme != self._base.scheme
            or candidate.host != self._base.host
            or candidate.port != self._base.port
        ):
            raise ValueError("HTTP capability target escaped configured origin")
        return candidate

    @staticmethod
    def _validate_query(query: tuple[tuple[str, str], ...]) -> list[tuple[str, str]]:
        result: list[tuple[str, str]] = []
        for pair in query:
            if len(pair) != 2:
                raise ValueError("HTTP capability query pair is invalid")
            name, value = pair
            if not isinstance(name, str) or not isinstance(value, str) or not name:
                raise ValueError("HTTP capability query must contain string pairs")
            if any(char in name or char in value for char in ("\r", "\n", "\x00")):
                raise ValueError("HTTP capability query contains control characters")
            result.append((name, value))
        return result

    @staticmethod
    def _validate_content_type(response: httpx.Response) -> None:
        media_type = response.headers.get("content-type", "").split(";", 1)[0].strip().lower()
        if media_type != "application/json" and not media_type.endswith("+json"):
            raise AdapterExecutionFailed("HTTP provider response is not JSON")

    @staticmethod
    def _read_bounded(response: httpx.Response, maximum: int) -> bytes:
        declared = response.headers.get("content-length")
        if declared is not None:
            try:
                if int(declared) > maximum:
                    raise AdapterExecutionFailed("HTTP provider response exceeds configured maximum")
            except ValueError as exc:
                raise AdapterExecutionFailed("HTTP provider content-length is invalid") from exc

        body = bytearray()
        for chunk in response.iter_bytes():
            body.extend(chunk)
            if len(body) > maximum:
                raise AdapterExecutionFailed("HTTP provider response exceeds configured maximum")
        return bytes(body)

    def _evidence(
        self,
        spec: CapabilitySpec,
        context: InvocationContext,
        output_digest: str,
        url: httpx.URL,
    ) -> EvidenceEnvelope | None:
        if spec.evidence.profile is EvidenceProfile.NONE:
            return None
        observed_at = datetime.now(UTC)
        expires_at = (
            observed_at + timedelta(seconds=spec.evidence.freshness_seconds)
            if spec.evidence.freshness_seconds is not None
            else None
        )
        safe_source = str(url.copy_with(query=None, fragment=None))
        origin = f"{url.scheme}://{url.host}"
        if url.port is not None:
            origin += f":{url.port}"
        return EvidenceEnvelope(
            schema_version="korpus.evidence-envelope.v1",
            status=EvidenceStatus.VALID,
            binding=EvidenceBinding(
                invocation_id=context.invocation_id,
                capability_id=spec.capability_id,
                capability_version=spec.version,
                adapter_id=spec.adapter.adapter_id,
                adapter_version=spec.adapter.adapter_version,
                output_digest=output_digest,
            ),
            provenance=EvidenceProvenance(
                kind=ProvenanceKind.REMOTE_RESPONSE,
                source_refs=[safe_source],
                provider_identity=origin,
            ),
            observed_at=observed_at,
            expires_at=expires_at,
            reproducible=False,
        )
