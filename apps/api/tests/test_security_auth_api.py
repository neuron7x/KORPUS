from pathlib import Path

from fastapi.routing import APIRoute
from fastapi.testclient import TestClient
from korpus.config import Settings
from korpus.domain.models import AccessTier, Identity
from korpus.main import create_app
from korpus.security.auth import get_identity, issue_token


def test_jwt_auth_accepts_valid_token_and_rejects_invalid(tmp_path: Path):
    settings = Settings(
        environment="test",
        database_url=f"sqlite:///{tmp_path / 'jwt.db'}",
        object_root=tmp_path / "objects",
        audit_anchor_path=tmp_path / "anchor.json",
        auth_mode="jwt",
        jwt_secret="s" * 32,
        audit_hmac_key="audit-test",
    )
    app = create_app(settings)
    identity = Identity(
        subject="jwt-user",
        roles=frozenset({"user"}),
        clearance=AccessTier.PUBLIC,
        corpora=frozenset({"public"}),
    )
    with TestClient(app) as client:
        assert client.get("/v1/auth/me").status_code == 401
        rejected = client.get("/v1/auth/me", headers={"Authorization": "Bearer invalid"})
        assert rejected.status_code == 401
        token = issue_token(identity, settings)
        response = client.get("/v1/auth/me", headers={"Authorization": f"Bearer {token}"})
        assert response.status_code == 200
        assert response.json()["subject"] == "jwt-user"


def test_every_nonpublic_v1_route_depends_on_identity(tmp_path: Path) -> None:
    """A newly added API route is private unless its public nature is named here.

    This is an attack-surface gate, not a spot check: FastAPI's resolved dependency graph
    is inspected so aliases and nested dependencies still count. Signed provider callbacks
    are the only unauthenticated state-changing exception and have dedicated signature tests.
    """
    settings = Settings(
        environment="test",
        database_url=f"sqlite:///{tmp_path / 'surface.db'}",
        object_root=tmp_path / "objects-surface",
        audit_anchor_path=tmp_path / "anchor-surface.json",
        auth_mode="jwt",
        jwt_secret="s" * 32,
        audit_hmac_key="audit-test",
    )
    app = create_app(settings)
    public = {
        "/v1/auth/login",
        "/v1/auth/callback",
        "/v1/auth/logout",
        "/v1/billing/liqpay/callback",
        "/v1/billing/webhook",
    }

    def dependency_calls(route) -> set[object]:
        found: set[object] = set()
        pending = list(route.dependant.dependencies)
        while pending:
            dependency = pending.pop()
            found.add(dependency.call)
            pending.extend(dependency.dependencies)
        return found

    exposed: list[str] = []
    for route in app.routes:
        if not isinstance(route, APIRoute) or not route.path.startswith("/v1/"):
            continue
        if route.path in public:
            continue
        if get_identity not in dependency_calls(route):
            exposed.append(f"{','.join(sorted(route.methods))} {route.path}")

    assert not exposed, f"new unauthenticated API surface: {exposed}"
