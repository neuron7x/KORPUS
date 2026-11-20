"""Canonical derivation and real local persistence; Docker/PG qualification runs in CI."""

from __future__ import annotations

import copy
import hashlib
import os
import subprocess
import sys
from pathlib import Path

import pytest
import yaml
from korpus.config import Settings
from korpus.infrastructure.object_store import LocalObjectStore
from korpus.runtime_config_policy import validate_storage_integrations

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / "scripts"))

import generate_pilot_compose as generator  # noqa: E402
from compose_pilot_environment import SERVICES, SmokeFailure, Workspace  # noqa: E402
from pilot_acceptance_contract import Fixture  # noqa: E402


def test_derivation_changes_storage_and_project_without_relaxing_the_runtime() -> None:
    base = yaml.safe_load((ROOT / "docker-compose.yml").read_text())
    original = copy.deepcopy(base)
    profile = generator.derive(base)
    assert base == original
    assert base["name"] == "korpus" and profile["name"] == "korpus-pilot"
    assert set(profile["services"]) == SERVICES
    assert profile["networks"] == base["networks"]
    assert set(profile["volumes"]) == (set(base["volumes"]) - {"minio-data"}) | {"pilot-objects"}
    assert not any(name.startswith("minio_") for name in profile["secrets"])
    for name, service in profile["services"].items():
        if name not in {"api", "worker"}:
            assert service == base["services"][name]
            continue
        before = base["services"][name]
        allowed = {"environment", "secrets", "depends_on", "volumes"}
        assert {key: value for key, value in service.items() if key not in allowed} == {
            key: value for key, value in before.items() if key not in allowed
        }
        for key, value in before["environment"].items():
            if key != "KORPUS_OBJECT_STORE_MODE" and not key.startswith(("AWS_", "KORPUS_S3_")):
                assert service["environment"][key] == value
        assert not any(key.startswith(("AWS_", "KORPUS_S3_")) for key in service["environment"])
        assert service["environment"]["KORPUS_OBJECT_STORE_MODE"] == "local"
        assert service["environment"]["KORPUS_OBJECT_ROOT"] == "/data/objects"
        assert service["environment"]["KORPUS_QUARANTINE_OBJECT_ROOT"] == "/data/quarantine"
        assert service["volumes"][:-1] == before["volumes"]
        assert service["volumes"][-1] == {
            "type": "volume",
            "source": "pilot-objects",
            "target": "/data",
        }
        assert service["depends_on"] == {
            key: value for key, value in before["depends_on"].items() if key != "minio-init"
        }


def test_canonical_guard_change_is_inherited_and_requires_regeneration(tmp_path: Path) -> None:
    base_text = (ROOT / "docker-compose.yml").read_text()
    (tmp_path / "docker-compose.yml").write_text(base_text)
    target = tmp_path / generator.PROFILE_RELATIVE
    target.parent.mkdir(parents=True)
    target.write_text(generator.render(base_text))
    assert generator.current(tmp_path)
    base = yaml.safe_load(base_text)
    base["services"]["api"]["pids_limit"] = 128
    changed = yaml.safe_dump(base)
    (tmp_path / "docker-compose.yml").write_text(changed)
    assert not generator.current(tmp_path)
    with pytest.raises(SmokeFailure, match="profile is stale"):
        Workspace.create(tmp_path)
    target.write_text(generator.render(changed))
    assert generator.current(tmp_path)
    assert yaml.safe_load(target.read_text())["services"]["api"]["pids_limit"] == 128


def test_checked_in_profile_is_the_exact_deterministic_derivation() -> None:
    assert generator.current(ROOT)
    profile = yaml.safe_load((ROOT / generator.PROFILE_RELATIVE).read_text())
    assert profile["services"]["web"]["ports"] == ["127.0.0.1:3000:8080"]
    assert profile["volumes"]["pilot-objects"] is None


def test_existing_canonical_data_mount_requires_explicit_derivation_review() -> None:
    base = yaml.safe_load((ROOT / "docker-compose.yml").read_text())
    base["services"]["worker"]["volumes"].append("existing-data:/data")
    with pytest.raises(ValueError, match="canonical /data mount changed"):
        generator.derive(base)


@pytest.mark.parametrize("source", ["services: [unclosed", "[]", "services: {}"])
def test_malformed_source_fails_before_creating_a_workspace(tmp_path: Path, source: str) -> None:
    (tmp_path / "docker-compose.yml").write_text(source)
    target = tmp_path / generator.PROFILE_RELATIVE
    target.parent.mkdir(parents=True)
    target.write_text("name: unrelated")
    assert not generator.current(tmp_path)
    with pytest.raises(SmokeFailure, match="profile is stale"):
        Workspace.create(tmp_path)


def test_generator_check_refuses_missing_or_hand_edited_output(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    (tmp_path / "docker-compose.yml").write_bytes((ROOT / "docker-compose.yml").read_bytes())
    monkeypatch.setattr(generator, "ROOT", tmp_path)
    monkeypatch.setattr(sys, "argv", ["generate_pilot_compose.py", "--check"])
    assert generator.main() == 1
    monkeypatch.setattr(sys, "argv", ["generate_pilot_compose.py"])
    assert generator.main() == 0
    target = tmp_path / generator.PROFILE_RELATIVE
    target.write_text(target.read_text().replace("KORPUS_AUTH_MODE: jwt", "KORPUS_AUTH_MODE: dev"))
    monkeypatch.setattr(sys, "argv", ["generate_pilot_compose.py", "--check"])
    assert generator.main() == 1
    assert '"valid": false' in capsys.readouterr().out


def test_separate_processes_share_persistent_paths_and_reject_changed_bytes(tmp_path: Path) -> None:
    profile = yaml.safe_load((ROOT / generator.PROFILE_RELATIVE).read_text())
    api_environment = profile["services"]["api"]["environment"]
    worker_environment = profile["services"]["worker"]["environment"]
    volume = tmp_path / "fresh-named-volume-view"
    object_root = volume / Path(api_environment["KORPUS_OBJECT_ROOT"]).relative_to("/data")
    quarantine_root = volume / Path(api_environment["KORPUS_QUARANTINE_OBJECT_ROOT"]).relative_to(
        "/data"
    )
    fixture = Fixture("pilot-smoke-persistent-paths")
    content = fixture.content
    digest = hashlib.sha256(content).hexdigest()
    quarantine = LocalObjectStore(quarantine_root)
    key = quarantine.put(content, digest, "acceptance.txt")
    quarantine.close()
    worker_script = """
import sys
from pathlib import Path
from korpus.infrastructure.object_store import LocalObjectStore
root, object_path, quarantine_path, key, digest = sys.argv[1:]
root = Path(root)
source = LocalObjectStore(root / Path(quarantine_path).relative_to('/data'))
target = LocalObjectStore(root / Path(object_path).relative_to('/data'))
job = root / 'temporary-job' / 'source.txt'
source.get_to_path(key, job)
assert target.put_path(job, digest, 'acceptance.txt') == key
source.close()
target.close()
"""
    result = subprocess.run(
        [
            sys.executable,
            "-c",
            worker_script,
            str(volume),
            worker_environment["KORPUS_OBJECT_ROOT"],
            worker_environment["KORPUS_QUARANTINE_OBJECT_ROOT"],
            key,
            digest,
        ],
        env={
            "PATH": os.environ.get("PATH", "/usr/bin:/bin"),
            "PYTHONPATH": str(ROOT / "apps/api/src"),
        },
        capture_output=True,
        text=True,
        timeout=15,
        check=False,
    )
    assert result.returncode == 0, result.stderr
    fresh_api = LocalObjectStore(object_root)
    assert fresh_api.get(key) == content
    assert (quarantine_root / key).read_bytes() == content
    (object_root / key).write_bytes(b"changed archive color")
    with pytest.raises(RuntimeError, match="integrity verification failed"):
        fresh_api.get(key)
    assert not list(volume.rglob(".object-*"))
    assert not list(volume.rglob(".download-*"))


def test_local_pilot_does_not_authorize_local_storage_in_controlled_environments(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    for key in list(os.environ):
        if key.startswith("KORPUS_"):
            monkeypatch.delenv(key)
    settings = Settings(
        _env_file=None,
        environment="local",
        object_store_mode="local",
        schema_mode="migrations",
        database_url="postgresql+psycopg://fixture:fixture@localhost/unused",
        object_root=tmp_path / "objects",
        quarantine_object_root=tmp_path / "quarantine",
        audit_anchor_path=tmp_path / "audit.json",
    )
    validate_storage_integrations(settings, controlled=False)
    with pytest.raises(ValueError, match="require durable remote object storage"):
        validate_storage_integrations(settings, controlled=True)
