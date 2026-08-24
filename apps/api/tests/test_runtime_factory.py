from pathlib import Path

from korpus.config import Settings
from korpus.infrastructure.audit_anchor import FileAuditAnchorStore
from korpus.infrastructure.object_store import LocalObjectStore
from korpus.infrastructure.runtime import create_object_store, create_repository


def test_runtime_factories_share_configuration_and_do_not_recreate_defaults(tmp_path: Path):
    settings = Settings(
        environment="test",
        database_url=f"sqlite:///{tmp_path / 'runtime.db'}",
        object_root=tmp_path / "objects",
        audit_anchor_path=tmp_path / "anchor.json",
        audit_hmac_key="runtime-audit-key",
    )
    repository = create_repository(settings)
    store = create_object_store(settings)
    assert isinstance(repository.anchor_store, FileAuditAnchorStore)
    assert repository.anchor_store.path == settings.audit_anchor_path
    assert isinstance(store, LocalObjectStore)
