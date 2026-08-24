from __future__ import annotations

from scripts.gcp.production_contract_canary import evaluate as canary
from scripts.gcp.production_contract_capacity import evaluate as capacity
from scripts.gcp.production_contract_database import evaluate as database
from scripts.gcp.production_contract_delivery import evaluate as delivery
from scripts.gcp.production_contract_edge import evaluate as edge
from scripts.gcp.production_contract_migration import evaluate as migration
from scripts.gcp.production_contract_network import evaluate as network
from scripts.gcp.production_contract_observability import evaluate as observability
from scripts.gcp.production_contract_supply import evaluate as supply
from scripts.gcp.production_contract_terraform import evaluate as terraform
from scripts.gcp.production_contract_tls import evaluate as tls


def evaluate(s: object) -> list[tuple[str, bool, str]]:
    predicates: list[tuple[str, bool, str]] = []
    for evaluator in (
        canary,
        capacity,
        database,
        delivery,
        edge,
        migration,
        network,
        observability,
        supply,
        terraform,
        tls,
    ):
        predicates.extend(evaluator(s))
    return predicates
