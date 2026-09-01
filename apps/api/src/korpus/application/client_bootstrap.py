"""Server-authoritative projection consumed by browser clients.

The browser may render authorization and runtime capability decisions; it must not
reconstruct them from roles, local configuration, or DOM state. This projection keeps
identity, effective permissions, release identity and deploy-time capabilities in one
response so every UI surface observes the same server decision.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict

from korpus.application.policy import KNOWN_PERMISSIONS, PolicyEngine
from korpus.config import Settings
from korpus.domain.models import Identity
from korpus.release import RELEASE_TAG


class ClientCapabilities(BaseModel):
    model_config = ConfigDict(frozen=True)

    browser_auth_enabled: bool
    subscription_required: bool
    offline_pack_enabled: bool
    ingestion_mode: Literal["synchronous", "durable_async"]


class AdmissionThresholds(BaseModel):
    """Правило, за яким сервер вирішив, а не лише його вирок.

    Клієнт діставав `status: answered` і числа `query_coverage`,
    `retrieval_score` — але не МЕЖУ, з якою сервер їх порівнював. Без неї
    «0.5» нечитабельне: агент не може відрізнити відповідь, що пройшла рівно по
    межі, від тієї, що має запас удвічі.

    Це не декоративно. Виміряно 01.09.2026 на живому розгортанні: питання «Яка
    столиця Бразилії?» дістало `answered` із `query_coverage` рівно 0.5 — тобто
    на самій межі, — тоді як своє питання дало 1.0. Вісь `boundary_foreign`
    тримає підлогу 0.75, тобто чужі питання впускаються за побудовою, і
    відрізнити їх може лише той, хто бачить ЗАПАС.

    Пороги віддаються з тих самих полів налаштувань, які застосовує шлях
    відповіді. Друге їх оголошення в клієнті розійшлося б мовчки.
    """

    model_config = ConfigDict(frozen=True)

    min_retrieval_score: float
    min_query_coverage: float
    min_support_score: float


class ClientBootstrap(BaseModel):
    model_config = ConfigDict(frozen=True)

    release: str
    api_version: str
    identity: Identity
    effective_permissions: tuple[str, ...]
    capabilities: ClientCapabilities
    admission: AdmissionThresholds


def effective_permissions(identity: Identity, policy: PolicyEngine) -> tuple[str, ...]:
    granted = policy.permissions(identity)
    allowed = KNOWN_PERMISSIONS if "*" in granted else granted.intersection(KNOWN_PERMISSIONS)
    return tuple(sorted(allowed))


def build_client_bootstrap(
    identity: Identity, settings: Settings, policy: PolicyEngine
) -> ClientBootstrap:
    return ClientBootstrap(
        release=RELEASE_TAG,
        api_version="v1",
        identity=identity,
        effective_permissions=effective_permissions(identity, policy),
        capabilities=ClientCapabilities(
            browser_auth_enabled=settings.browser_auth_enabled,
            subscription_required=settings.subscription_required,
            offline_pack_enabled=settings.offline_pack_enabled,
            ingestion_mode=settings.ingestion_mode,
        ),
        admission=AdmissionThresholds(
            min_retrieval_score=settings.min_retrieval_score,
            min_query_coverage=settings.min_query_coverage,
            min_support_score=settings.min_support_score,
        ),
    )
