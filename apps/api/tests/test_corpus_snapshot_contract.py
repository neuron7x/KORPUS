from __future__ import annotations

import ast
import hashlib
from dataclasses import replace
from datetime import date
from pathlib import Path
from types import SimpleNamespace

import pytest
from korpus.application.answer_snapshot import SnapshotAnswerRuntime, SnapshotAuditPolicy
from korpus.application.corpus_snapshot import (
    CorpusConsistencyError,
    CorpusReadToken,
    SemanticReleaseMember,
    canonical_optional,
    canonical_set,
    release_identity_digest,
    version_evidence_digest,
)
from korpus.application.ports import Repository
from korpus.domain.models import AccessTier
from korpus.infrastructure import corpus_snapshot_guards
from sqlalchemy import text


def _token(release_id: str) -> CorpusReadToken:
    return CorpusReadToken(
        state_epoch=7,
        release_id=release_id,
        as_of=date(2026, 8, 14),
        corpus_ids=frozenset({"public"}),
        authorization_scope_id="b" * 64,
    )


def _release_member(**changes: str) -> SemanticReleaseMember:
    member = SemanticReleaseMember(
        document_id="document-a",
        version_id="version-a",
        source_hash="a" * 64,
        review_state="approved",
        evidence_digest="b" * 64,
        canonical_title="Canonical title",
        corpus_id="public",
        access_tier="0",
        classification="public",
        document_compartments=canonical_set({"alpha"}),
        visibility_compartments=canonical_set({"alpha"}),
        revision="1",
        source_uri=canonical_optional("https://source.invalid/order"),
        publication_date=canonical_optional("2026-01-01"),
        effective_from=canonical_optional("2026-01-02"),
        effective_until=canonical_optional("2027-01-01"),
        rescinded_at=canonical_optional(None),
        authority="official_ua",
        supersedes_version_id=canonical_optional(None),
    )
    return replace(member, **changes)


def test_application_repository_port_cannot_recompute_answer_release() -> None:
    assert not hasattr(Repository, "corpus_release_id")


def test_no_runtime_component_calls_legacy_release_restamp() -> None:
    source_root = Path(__file__).resolve().parents[1] / "src/korpus"
    findings: list[str] = []
    for path in source_root.rglob("*.py"):
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        relative = path.relative_to(source_root)
        for node in ast.walk(tree):
            if isinstance(node, ast.Attribute) and node.attr == "corpus_release_id":
                findings.append(f"{relative}:{node.lineno}: call/reference")
            if (
                isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef)
                and node.name == "corpus_release_id"
                and relative.as_posix() != "infrastructure/repository.py"
            ):
                findings.append(f"{relative}:{node.lineno}: definition")
    assert findings == []


def test_corpus_read_token_accepts_full_sha256_release_identity() -> None:
    token = _token("a" * 64)
    assert token.release_id == "a" * 64


@pytest.mark.parametrize(
    "release_id",
    ["a" * 16, "a" * 63, "a" * 65, "A" * 64, "g" * 64],
)
def test_corpus_read_token_rejects_truncated_or_noncanonical_release_identity(
    release_id: str,
) -> None:
    with pytest.raises(ValueError, match="SHA-256"):
        _token(release_id)


@pytest.mark.parametrize(
    ("field", "replacement"),
    [
        ("document_id", "document-b"),
        ("version_id", "version-b"),
        ("source_hash", "c" * 64),
        ("review_state", "rejected"),
        ("evidence_digest", "d" * 64),
        ("canonical_title", "Changed title"),
        ("corpus_id", "training"),
        ("access_tier", "1"),
        ("classification", "internal"),
        ("document_compartments", canonical_set({"bravo"})),
        ("visibility_compartments", canonical_set({"alpha", "bravo"})),
        ("revision", "2"),
        ("source_uri", canonical_optional("https://source.invalid/changed")),
        ("publication_date", canonical_optional("2026-01-03")),
        ("effective_from", canonical_optional("2026-01-04")),
        ("effective_until", canonical_optional("2027-01-02")),
        ("rescinded_at", canonical_optional("2026-08-14T10:00:00+00:00")),
        ("authority", "official_allied"),
        ("supersedes_version_id", canonical_optional("version-old")),
    ],
)
def test_release_identity_digest_commits_every_member_field(field: str, replacement: str) -> None:
    baseline = _release_member()
    changed = replace(baseline, **{field: replacement})
    assert release_identity_digest([baseline]) != release_identity_digest([changed])


def test_release_identity_digest_is_order_and_join_multiplicity_stable() -> None:
    first = _release_member()
    second = _release_member(
        document_id="document-b",
        version_id="version-b",
        source_hash="c" * 64,
        evidence_digest="d" * 64,
    )
    assert release_identity_digest([first, second]) == release_identity_digest(
        [second, first, first]
    )


def test_semantic_canonicalization_distinguishes_absence_and_is_set_order_stable() -> None:
    assert canonical_optional(None) != canonical_optional("")
    assert canonical_set(["alpha", "bravo"]) == canonical_set(["bravo", "alpha", "alpha"])


def test_version_evidence_digest_distinguishes_missing_from_empty_section() -> None:
    content = "same evidence bytes"
    text_hash = hashlib.sha256(content.encode("utf-8")).hexdigest()
    missing = version_evidence_digest([("span-1", 0, None, None, content, text_hash)])
    empty = version_evidence_digest([("span-1", 0, None, "", content, text_hash)])
    assert missing != empty


def test_snapshot_capture_rejects_state_change_during_release_projection(
    client, admin_identity, monkeypatch
) -> None:
    reader = client.app.state.corpus_snapshot_reader
    epochs = iter((41, 42))
    monkeypatch.setattr(reader, "_epoch", lambda _connection: next(epochs))

    with pytest.raises(CorpusConsistencyError, match="while release identity was captured"):
        reader.capture(admin_identity, frozenset(), date(2026, 8, 14))


def test_snapshot_token_cannot_be_reused_for_another_historical_date(
    client, admin_identity
) -> None:
    reader = client.app.state.corpus_snapshot_reader
    corpora = frozenset({"public"})
    captured_at = date(2026, 8, 14)
    token = reader.capture(admin_identity, corpora, captured_at)

    with pytest.raises(CorpusConsistencyError, match="historical date"):
        reader.validate(admin_identity, corpora, date(2026, 8, 13), token)


@pytest.mark.parametrize("field", ["subject", "clearance", "roles", "corpora", "compartments"])
def test_snapshot_token_cannot_be_reused_under_another_authorization_identity(
    client, admin_identity, field: str
) -> None:
    reader = client.app.state.corpus_snapshot_reader
    corpora = frozenset({"public"})
    as_of = date(2026, 8, 14)
    token = reader.capture(admin_identity, corpora, as_of)
    changes: dict[str, object] = {
        "subject": f"{admin_identity.subject}-other",
        "clearance": AccessTier.AUTHENTICATED,
        "roles": admin_identity.roles | {"snapshot_scope_probe"},
        "corpora": admin_identity.corpora | {"snapshot-scope-probe"},
        "compartments": admin_identity.compartments | {"snapshot-scope-probe"},
    }
    changed_identity = admin_identity.model_copy(update={field: changes[field]})

    with pytest.raises(CorpusConsistencyError, match="authorization identity"):
        reader.validate(changed_identity, corpora, as_of, token)


def test_answer_runtime_rejects_split_snapshot_authorities() -> None:
    repository_reader = object()
    retriever_reader = object()
    repository = SimpleNamespace(corpus_snapshot_reader=repository_reader)
    retriever = SimpleNamespace(snapshot_reader=retriever_reader)
    policy = SnapshotAuditPolicy(0.1, 0.1, 0.1, "contract-test")

    with pytest.raises(ValueError, match="share one corpus snapshot reader"):
        SnapshotAnswerRuntime(repository, retriever, policy)  # type: ignore[arg-type]


def test_guard_verification_binds_trigger_name_to_target_relation(client) -> None:
    """A correctly named trigger on the wrong table is not a temporal guard."""
    reader = client.app.state.corpus_snapshot_reader
    repository = client.app.state.repository
    with repository.engine.connect() as connection:
        transaction = connection.begin()
        try:
            connection.execute(text("DROP TRIGGER trg_documents_epoch_insert"))
            connection.execute(
                text(
                    "CREATE TRIGGER trg_documents_epoch_insert "
                    "AFTER INSERT ON document_versions BEGIN "
                    "UPDATE corpus_state_epoch SET epoch = epoch + 1 WHERE singleton_id = 1; END"
                )
            )
            with pytest.raises(RuntimeError, match="corpus snapshot guards are missing"):
                reader._require_guards(connection)
        finally:
            transaction.rollback()


def test_guard_verification_rejects_correctly_named_noop_trigger(client) -> None:
    """A correctly named trigger with inert SQL must fail startup verification."""
    reader = client.app.state.corpus_snapshot_reader
    repository = client.app.state.repository
    with repository.engine.connect() as connection:
        transaction = connection.begin()
        try:
            connection.execute(text("DROP TRIGGER trg_documents_epoch_insert"))
            connection.execute(
                text(
                    "CREATE TRIGGER trg_documents_epoch_insert "
                    "AFTER INSERT ON documents BEGIN SELECT 1; END"
                )
            )
            with pytest.raises(RuntimeError, match="invalid definition"):
                reader._require_guards(connection)
        finally:
            transaction.rollback()


class _Rows:
    def __init__(self, rows: list[tuple[object, ...]]) -> None:
        self.rows = rows

    def all(self) -> list[tuple[object, ...]]:
        return self.rows


class _PostgresGuardCatalogueConnection:
    """Return catalog-shaped rows without requiring a PostgreSQL service."""

    def __init__(self) -> None:
        self.calls = 0

    def execute(self, _statement) -> _Rows:
        self.calls += 1
        if self.calls == 1:
            triggers = [
                (
                    table,
                    f"trg_{table}_epoch",
                    f"CREATE TRIGGER trg_{table}_epoch AFTER INSERT OR DELETE OR UPDATE "
                    f"ON public.{table} FOR EACH STATEMENT EXECUTE FUNCTION "
                    "korpus_bump_corpus_state_epoch()",
                )
                for table in corpus_snapshot_guards.EPOCH_TABLES
            ]
            triggers.extend(
                [
                    (
                        "evidence_spans",
                        "trg_evidence_spans_immutable",
                        "CREATE TRIGGER trg_evidence_spans_immutable BEFORE INSERT OR DELETE OR "
                        "UPDATE ON public.evidence_spans FOR EACH ROW EXECUTE FUNCTION "
                        "korpus_refuse_approved_evidence_mutation()",
                    ),
                    (
                        "document_versions",
                        "trg_approved_version_digest_immutable",
                        "CREATE TRIGGER trg_approved_version_digest_immutable BEFORE UPDATE OF "
                        "evidence_digest ON public.document_versions FOR EACH ROW EXECUTE FUNCTION "
                        "korpus_refuse_approved_digest_mutation()",
                    ),
                ]
            )
            return _Rows(triggers)
        if self.calls == 2:
            return _Rows(
                [
                    (
                        "korpus_bump_corpus_state_epoch",
                        True,
                        ["search_path=pg_catalog"],
                        """
                        BEGIN
                          IF FALSE THEN
                            UPDATE public.corpus_state_epoch
                            SET epoch = epoch + 1 WHERE singleton_id = 1;
                          END IF;
                          RETURN NULL;
                        END;
                        """,
                    ),
                    (
                        "korpus_refuse_approved_evidence_mutation",
                        True,
                        ["search_path=pg_catalog"],
                        corpus_snapshot_guards._POSTGRES_FUNCTION_BODIES[
                            "korpus_refuse_approved_evidence_mutation"
                        ],
                    ),
                    (
                        "korpus_refuse_approved_digest_mutation",
                        False,
                        None,
                        corpus_snapshot_guards._POSTGRES_FUNCTION_BODIES[
                            "korpus_refuse_approved_digest_mutation"
                        ],
                    ),
                ]
            )
        raise AssertionError("unexpected guard catalogue query")


def test_postgres_guard_verifier_rejects_dead_code_decoy_body_without_database() -> None:
    connection = _PostgresGuardCatalogueConnection()
    with pytest.raises(
        RuntimeError, match=r"korpus_bump_corpus_state_epoch.*invalid function body"
    ):
        corpus_snapshot_guards._postgres_guards(connection)  # type: ignore[arg-type]
