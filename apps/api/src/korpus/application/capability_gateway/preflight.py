from __future__ import annotations

from collections.abc import Mapping

from korpus.application.capability_gateway.adapters import AdapterRegistry
from korpus.application.capability_gateway.errors import (
    CapabilityGatewayError,
    CapabilityRegistrationError,
)
from korpus.application.capability_gateway.registry import CapabilityRegistry
from korpus.application.capability_gateway.types import (
    CapabilityLifecycle,
    DataEgressClass,
    EffectClass,
    ProviderType,
)
from korpus.application.capability_gateway.validation import ExactSchemaRegistry


class CapabilityDeploymentPreflight:
    """Finite startup validation for every executable capability declaration."""

    def __init__(
        self,
        *,
        registry: CapabilityRegistry,
        adapters: AdapterRegistry,
        schemas: ExactSchemaRegistry,
        resource_mappers: Mapping[str, object],
        action_permissions: Mapping[str, str],
    ) -> None:
        self._registry = registry
        self._adapters = adapters
        self._schemas = schemas
        self._resource_mappers = frozenset(resource_mappers)
        self._action_permissions = dict(action_permissions)

    def errors(self) -> tuple[str, ...]:
        known_schemas = frozenset(self._schemas.schema_ids())
        errors: list[str] = []
        for spec in self._registry.all_specs():
            if spec.lifecycle is not CapabilityLifecycle.ENABLED:
                continue
            key = f"{spec.capability_id}@{spec.version}"
            if spec.input_schema_id not in known_schemas:
                errors.append(f"{key}: input schema is not registered: {spec.input_schema_id}")
            if spec.output_schema_id not in known_schemas:
                errors.append(f"{key}: output schema is not registered: {spec.output_schema_id}")
            if spec.authorization.resource_mapper not in self._resource_mappers:
                errors.append(
                    f"{key}: resource mapper is not registered: "
                    f"{spec.authorization.resource_mapper}"
                )
            if spec.authorization.action not in self._action_permissions:
                errors.append(
                    f"{key}: capability action has no canonical permission mapping: "
                    f"{spec.authorization.action}"
                )
            try:
                self._adapters.resolve(spec)
            except CapabilityGatewayError as exc:
                errors.append(f"{key}: {exc}")

            if spec.provider_type is ProviderType.INTERNAL and spec.data_policy.egress_class is not DataEgressClass.NONE:
                errors.append(f"{key}: internal provider must declare data egress NONE")
            if spec.provider_type is ProviderType.INTERNAL and spec.effect_class in {
                EffectClass.READ_REMOTE,
                EffectClass.WRITE_REMOTE,
            }:
                errors.append(f"{key}: internal provider cannot declare a remote effect class")
            if spec.provider_type is not ProviderType.INTERNAL and spec.data_policy.egress_class in {
                DataEgressClass.NONE,
                DataEgressClass.RESTRICTED_NO_EGRESS,
            }:
                errors.append(
                    f"{key}: enabled remote capability has a data policy that forbids all egress"
                )
        return tuple(sorted(errors))

    def require_valid(self) -> None:
        errors = self.errors()
        if errors:
            detail = "\n".join(f"- {error}" for error in errors)
            raise CapabilityRegistrationError(f"capability deployment preflight failed:\n{detail}")
