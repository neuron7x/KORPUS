"""An additive reviewer exception cannot become an arbitrary SQL/policy allowance."""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

from scripts.gcp.validate_migration_compatibility import _execute_is_expanding, evaluate

ROOT = Path(__file__).resolve().parents[3]
MIGRATION = ROOT / "apps/api/migrations/versions/0028_reviewer_update_scope.py"


def _statements() -> list[str]:
    tree = ast.parse(MIGRATION.read_text())
    upgrade = next(
        node for node in tree.body if isinstance(node, ast.FunctionDef) and node.name == "upgrade"
    )
    return [
        node.args[0].value
        for node in ast.walk(upgrade)
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Attribute)
        and node.func.attr == "execute"
    ]


def _problem(sql: str) -> str | None:
    call = ast.parse(f"op.execute({sql!r})").body[0].value
    return _execute_is_expanding(call)


def test_only_the_two_complete_additive_policies_are_proven() -> None:
    statements = _statements()
    assert len(statements) == 2
    for statement in statements:
        assert _problem(statement) is None
        assert _problem(statement.replace(" AND ", "\nAND\n")) is None


@pytest.mark.parametrize("space", [" ", "\t", "\n", "\r", "\f", "\v"])
def test_only_postgresql_ascii_whitespace_separates_tokens(space: str) -> None:
    for statement in _statements():
        assert (
            _problem(
                space + statement.replace("SELECT 1 FROM", f"SELECT{space}1{space}FROM") + space
            )
            is None
        )


@pytest.mark.parametrize("space", ["\u00a0", "\x1c"])
@pytest.mark.parametrize("position", ["leading", "trailing", "keyword", "identifier", "function"])
def test_python_only_whitespace_is_not_discarded(space: str, position: str) -> None:
    for statement in _statements():
        poisoned = {
            "leading": space + statement,
            "trailing": statement + space,
            "keyword": statement.replace("CREATE POLICY", f"CREATE{space}POLICY"),
            "identifier": statement.replace("ON public.", f"ON public.{space}"),
            "function": statement.replace(
                "public.korpus_rls_roles", f"public.{space}korpus_rls_roles"
            ),
        }[position]
        assert _problem(poisoned) is not None


def test_unicode_relation_and_qualifier_do_not_match_the_reviewed_relation() -> None:
    statement = _statements()[0]
    poisoned = statement.replace(
        "ON public.document_versions", "ON public.\u00a0document_versions"
    ).replace("= document_versions.document_id", "= \u00a0document_versions.document_id")
    assert "'public.document_versions'" in poisoned
    assert _problem(poisoned) is not None


@pytest.mark.parametrize("integer", ["1FROM", "1_FROM", "11FROM", "1$FROM"])
def test_number_and_identifier_junk_cannot_be_split_into_proven_tokens(integer: str) -> None:
    for statement in _statements():
        assert _problem(statement.replace("1 FROM", integer)) is not None


@pytest.mark.parametrize(
    ("old", "new"),
    [
        ("AS PERMISSIVE", "AS RESTRICTIVE"),
        ("FOR UPDATE", "FOR ALL"),
        ("FOR UPDATE", "FOR SELECT"),
        ("FOR UPDATE", "FOR INSERT"),
        ("FOR UPDATE", "FOR DELETE"),
        ("TO PUBLIC", "TO korpus_review"),
        ("CURRENT_USER", "SESSION_USER"),
        ("pg_catalog.has_column_privilege", "public.fake_capability"),
        ("'reviewer'", "'admin'"),
        ("'reviewer'", "' reviewer '"),
        ("'UPDATE'", "'SELECT'"),
        ("public.korpus_rls_roles()", "string_to_array(current_setting('korpus.roles'), ',')"),
        ("AND 'reviewer'", "OR 'reviewer'"),
    ],
)
def test_policy_role_capability_and_command_poisons_are_refused(old: str, new: str) -> None:
    for statement in _statements():
        assert old in statement
        assert _problem(statement.replace(old, new)) is not None


@pytest.mark.parametrize(
    ("index", "old", "new"),
    [
        (0, "'review_state'", "'revision'"),
        (0, "'review_state'", "'REVIEW_STATE'"),
        (0, "document_versions.document_id", "d.id"),
        (0, "reviewer_version_update", "version_update"),
        (1, "'access_tier'", "'canonical_title'"),
        (1, "documents.access_tier <=", "0 <="),
        (1, "documents.corpus_id", "'public'"),
        (1, "documents.classification", "'public'"),
        (1, "compartment.value", "'known'"),
        (1, "NOT EXISTS", "EXISTS"),
        (1, "'public.documents'", "' public.documents'"),
    ],
)
def test_each_original_scope_axis_and_literal_is_required(index, old, new) -> None:
    statement = _statements()[index]
    assert _problem(statement.replace(old, new, 1)) is not None


@pytest.mark.parametrize(
    "suffix", ["; SELECT 1", " -- hidden", " /* hidden */", "\x00", " OR TRUE"]
)
def test_policy_has_no_trailing_or_stacked_statement(suffix: str) -> None:
    for statement in _statements():
        assert _problem(statement + suffix) is not None


def test_new_row_check_cannot_be_missing_or_weaker() -> None:
    for statement in _statements():
        using = statement.split("WITH CHECK", 1)[0]
        assert _problem(using) is not None
        assert _problem(using + "WITH CHECK (TRUE)") is not None


def test_new_policy_adds_no_findings_to_the_existing_restrictive_history() -> None:
    report = evaluate(ROOT)
    assert report["status"] == "FAIL"
    assert report["future_migrations"] == 4
    assert not any("0028_reviewer_update_scope" in finding for finding in report["findings"])
    expected = {
        "0025_sealed_provenance_integrity": 14,
        "0026_learning_history_integrity": 11,
        "0027_learning_competency_integrity": 7,
    }
    assert len(report["findings"]) == sum(expected.values())
    for revision, count in expected.items():
        assert sum(revision in finding for finding in report["findings"]) == count
