from __future__ import annotations

import hashlib
import json

from korpus.application.capability_gateway.errors import CapabilityContractError
from korpus.application.capability_gateway.types import CapabilitySpec, IntegrationRequest


def canonical_json_bytes(value: object) -> bytes:
    try:
        text = json.dumps(
            value,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
            allow_nan=False,
        )
    except (TypeError, ValueError) as exc:
        raise CapabilityContractError("payload is not canonical JSON") from exc
    return text.encode("utf-8")


def payload_digest(value: object) -> str:
    return "sha256:" + hashlib.sha256(canonical_json_bytes(value)).hexdigest()


def validate_request_binding(request: IntegrationRequest, spec: CapabilitySpec) -> None:
    if request.capability_id != spec.capability_id or request.capability_version != spec.version:
        raise CapabilityContractError("request capability id/version does not match resolved spec")

    request_size = len(canonical_json_bytes(request.input))
    if request_size > spec.data_policy.max_request_bytes:
        raise CapabilityContractError(
            f"request payload exceeds capability maximum: {request_size} > "
            f"{spec.data_policy.max_request_bytes}"
        )

    if spec.idempotency.required and request.idempotency_key is None:
        raise CapabilityContractError("idempotency key is required by capability contract")
