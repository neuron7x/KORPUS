"""Репродукція з чистої кімнати: вісім перевірок, які не читав жоден тест.

`clean_room_checks` додано 06.09.2026 як відповідь на VD-6 («доказ без споживача»).
Мутаційний прогін показав, що інвертувати можна `status_pass`, `class_is_remote` і
`source_bound`, а повна батарея лишається зеленою. Потім чотири перевірки слідів
самого прогону додались — і теж без жодного тесту. Тут кожне плече своє: спочатку
позитивне (артефакт, що ПРОХОДИТЬ), потім по одному спростуванню на перевірку.
"""

from __future__ import annotations

import hashlib
import json
import subprocess
from pathlib import Path

from scripts.clean_room_contract import _candidate_on_live_remote
from scripts.current_truth_admission import CLEAN_ROOM, clean_room_checks
from scripts.evidence_source_binding import committed_evidence_source_digest

ALL = (
    "present",
    "schema_exact",
    "status_pass",
    "status_coherent",
    "class_is_remote",
    "producer_exact",
    "remote_is_trunk",
    "candidate_on_live_trunk",
    "release_bound",
    "source_bound",
    "scope_exact",
    "candidate_source_bound",
    "dependency_lock_bound",
    "junit_present",
    "junit_hash_bound",
    "junit_counts_match",
    "trust_root_candidate_bound",
    "owner_attestation_verified",
    "run_counted",
    "run_clean",
)


def _artefact(root: Path, **overrides: object) -> Path:
    remote = root.parent / f"{root.name}-remote.git"
    signing_key = root.parent / f"{root.name}-signing"
    subprocess.run(["git", "init", "--bare", "-q", str(remote)], check=True)
    subprocess.run(
        ["ssh-keygen", "-q", "-t", "ed25519", "-N", "", "-f", str(signing_key)], check=True
    )
    release = {
        "schema": "korpus.release-identity.v1",
        "product": "KORPUS",
        "version": "9",
        "tag": "v9",
        "artifact_stem": "KORPUS_v9",
        "distribution_artifact": "KORPUS_v9.zip",
    }
    for relative, value in {
        "apps/api/src/korpus/release.json": json.dumps(release),
        "apps/api/requirements.dev.lock": "pytest==1 --hash=sha256:" + "a" * 64,
        "config/operations/forges.json": json.dumps(
            {"forges": {"trunk": {"url": str(remote), "ssh": str(remote)}}}
        ),
        "config/operations/canonical-state.json": json.dumps({"canonical_branch": "main"}),
        "config/operations/trusted-git-signers": (
            "test@example.invalid " + signing_key.with_suffix(".pub").read_text().strip()
        ),
    }.items():
        path = root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(value + "\n", encoding="utf-8")
    subprocess.run(["git", "init", "-q"], cwd=root, check=True)
    subprocess.run(["git", "config", "user.email", "test@example.invalid"], cwd=root, check=True)
    subprocess.run(["git", "config", "user.name", "test"], cwd=root, check=True)
    subprocess.run(["git", "add", "."], cwd=root, check=True)
    subprocess.run(["git", "commit", "-qm", "fixture"], cwd=root, check=True)
    subprocess.run(["git", "remote", "add", "origin", str(remote)], cwd=root, check=True)
    subprocess.run(["git", "push", "-q", "origin", "HEAD:refs/heads/main"], cwd=root, check=True)
    candidate = subprocess.run(
        ["git", "rev-parse", "HEAD"], cwd=root, check=True, capture_output=True, text=True
    ).stdout.strip()
    digest = committed_evidence_source_digest(candidate, root)
    junit = root / "reports/closure/CLEAN_ROOM_REPRODUCTION.junit.xml"
    junit.parent.mkdir(parents=True, exist_ok=True)
    junit.write_text(
        '<testsuite tests="3892" failures="0" errors="0" skipped="0"/>\n', encoding="utf-8"
    )
    payload: dict[str, object] = {
        "schema": "korpus.clean-room-remote.v1",
        "status": "PASS",
        "class": "REMOTE_SOURCE_FRESH_DEPENDENCIES",
        "produced_by": "scripts/reproduce_clean_room.py",
        "remote": str(remote),
        "remote_class": "TRUNK",
        "release": "v9",
        "source_tree_sha256": digest,
        "digest_scope": "evidence_paths",
        "pytest_exit_code": 0,
        "pytest": {"tests": 3892, "failures": 0, "errors": 0, "skipped": 0},
        "candidate_sha": candidate,
        "dependency_freeze_sha256": hashlib.sha256(
            (root / "apps/api/requirements.dev.lock").read_bytes()
        ).hexdigest(),
        "junit_path": "reports/closure/CLEAN_ROOM_REPRODUCTION.junit.xml",
        "junit_sha256": hashlib.sha256(junit.read_bytes()).hexdigest(),
        "attested_by": "test@example.invalid",
        "attestation_class": "OWNER_ATTESTED",
    }
    payload.update(overrides)
    path = root / CLEAN_ROOM
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload) + "\n", encoding="utf-8")
    subprocess.run(
        [
            "ssh-keygen",
            "-q",
            "-Y",
            "sign",
            "-f",
            str(signing_key),
            "-n",
            "korpus-clean-room",
            str(path),
        ],
        check=True,
    )
    return root


def _only(root: Path, digest: str | None = None) -> dict[str, bool]:
    if digest is None:
        digest = committed_evidence_source_digest("HEAD", root)
    return {key.rsplit(".", 1)[1]: value for key, value in clean_room_checks(root, digest).items()}


def test_a_passing_remote_reproduction_of_this_tree_is_admitted(tmp_path: Path) -> None:
    """Позитивне плече. Без нього кожне спростування нижче проходило б і на
    перевірці, що завжди повертає False."""
    checks = _only(_artefact(tmp_path))
    assert set(checks) == set(ALL), "перевірку додано або прибрано без тесту на неї"
    assert all(checks.values())


def test_a_reproduction_that_did_not_pass_is_not_admitted(tmp_path: Path) -> None:
    checks = _only(_artefact(tmp_path, status="FAIL"))
    assert checks["status_pass"] is False
    assert checks["class_is_remote"] is True


def test_a_local_clone_is_not_a_remote_reproduction(tmp_path: Path) -> None:
    """`verify-clean-clone` пише СЛАБШИЙ клас; зарахувати його означало б назвати
    клон із локального дерева репродукцією з віддаленого джерела."""
    checks = _only(_artefact(tmp_path, **{"class": "LOCAL_CLONE"}))
    assert checks["class_is_remote"] is False
    assert checks["status_pass"] is True


def test_a_reproduction_of_another_tree_is_not_source_bound(tmp_path: Path) -> None:
    checks = _only(_artefact(tmp_path, source_tree_sha256="b" * 64))
    assert checks["source_bound"] is False


def test_an_empty_digest_cannot_bind_a_reproduction(tmp_path: Path) -> None:
    """Порожній дайджест дорівнював би сам собі: прив'язка задовольнялась би тим,
    що дайджест не обчислили."""
    checks = _only(_artefact(tmp_path, source_tree_sha256=""), digest="")
    assert checks["source_bound"] is False


def test_a_reproduction_that_ran_nothing_is_not_a_reproduction(tmp_path: Path) -> None:
    """Нуль виконаних тестів і чиста батарея нерозрізненні за `failures == 0`."""
    checks = _only(_artefact(tmp_path, pytest={"tests": 0, "failures": 0, "errors": 0}))
    assert checks["junit_counts_match"] is False
    assert checks["run_counted"] is True


def test_a_reproduction_with_failures_is_not_clean(tmp_path: Path) -> None:
    checks = _only(_artefact(tmp_path, pytest={"tests": 12, "failures": 1, "errors": 0}))
    assert checks["junit_counts_match"] is False
    assert checks["run_counted"] is True


def test_a_reproduction_with_collection_errors_is_not_clean(tmp_path: Path) -> None:
    """Помилка збору дає нуль падінь: батарея не впала, вона не почалась."""
    checks = _only(_artefact(tmp_path, pytest={"tests": 12, "failures": 0, "errors": 2}))
    assert checks["junit_counts_match"] is False


def test_a_reproduction_without_a_pytest_block_counts_nothing(tmp_path: Path) -> None:
    checks = _only(_artefact(tmp_path, pytest="3892 passed"))
    assert checks["junit_counts_match"] is False


def test_a_tampered_junit_is_not_bound_to_the_reproduction(tmp_path: Path) -> None:
    root = _artefact(tmp_path)
    (root / "reports/closure/CLEAN_ROOM_REPRODUCTION.junit.xml").write_text(
        '<testsuite tests="1" failures="0" errors="0" skipped="0"/>\n', encoding="utf-8"
    )
    checks = _only(root)
    assert checks["junit_hash_bound"] is False
    assert checks["junit_counts_match"] is False


def test_a_report_changed_after_attestation_is_refused(tmp_path: Path) -> None:
    root = _artefact(tmp_path)
    path = root / CLEAN_ROOM
    payload = json.loads(path.read_text(encoding="utf-8"))
    payload["status"] = "FAIL"
    path.write_text(json.dumps(payload) + "\n", encoding="utf-8")
    assert _only(root)["owner_attestation_verified"] is False


def test_an_untracked_replacement_trust_root_cannot_authorize_a_report(tmp_path: Path) -> None:
    root = _artefact(tmp_path)
    allowed = root / "config/operations/trusted-git-signers"
    allowed.write_text(allowed.read_text().replace("test@example.invalid", "other@example.invalid"))
    checks = _only(root)
    assert checks["trust_root_candidate_bound"] is False
    assert checks["owner_attestation_verified"] is False


def test_a_well_formed_but_invented_candidate_is_not_source_bound(tmp_path: Path) -> None:
    checks = _only(_artefact(tmp_path, candidate_sha="f" * 40))
    assert checks["candidate_source_bound"] is False
    assert checks["candidate_on_live_trunk"] is False


def test_a_feature_only_remote_candidate_is_not_the_canonical_trunk(tmp_path: Path) -> None:
    root = _artefact(tmp_path)
    (root / "feature.txt").write_text("feature\n", encoding="utf-8")
    subprocess.run(["git", "add", "feature.txt"], cwd=root, check=True)
    subprocess.run(["git", "commit", "-qm", "feature"], cwd=root, check=True)
    feature = subprocess.run(
        ["git", "rev-parse", "HEAD"], cwd=root, check=True, capture_output=True, text=True
    ).stdout.strip()
    remote = subprocess.run(
        ["git", "remote", "get-url", "origin"],
        cwd=root,
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()
    subprocess.run(["git", "push", "-q", "origin", "HEAD:refs/heads/feature"], cwd=root, check=True)
    assert _candidate_on_live_remote(root, feature, remote) is False


def test_a_reproduction_that_names_no_candidate_is_about_no_commit(tmp_path: Path) -> None:
    checks = _only(_artefact(tmp_path, candidate_sha=""))
    assert checks["candidate_source_bound"] is False


def test_a_reproduction_that_names_no_dependency_origin_is_not_reproducible(
    tmp_path: Path,
) -> None:
    """Свіжі залежності без названого походження — прогін, який ніхто не повторить."""
    checks = _only(_artefact(tmp_path, dependency_freeze_sha256=""))
    assert checks["dependency_lock_bound"] is False


def test_an_absent_reproduction_is_absent_not_silently_fine(tmp_path: Path) -> None:
    assert clean_room_checks(tmp_path, "a" * 64) == {f"{CLEAN_ROOM}.present": False}


def test_the_reproduction_names_the_trunk_not_the_archive() -> None:
    """Дефолт чистої кімнати завжди йде з оголошеного канонічного форжа."""
    import importlib.util

    root = Path(__file__).resolve().parents[3]
    spec = importlib.util.spec_from_file_location(
        "reproduce_clean_room", root / "scripts/reproduce_clean_room.py"
    )
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)

    assert "github.com" in module.TRUNK
    assert "gitlab.com" in module.ARCHIVE
    assert module.TRUNK != module.ARCHIVE
