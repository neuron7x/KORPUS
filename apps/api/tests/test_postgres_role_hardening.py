from __future__ import annotations

from scripts.postgres_role_hardening import ensure_group, ensure_login, revoke_all_memberships


class _ScalarRows:
    def __init__(self, values: list[str]) -> None:
        self.values = values

    def all(self) -> list[str]:
        return self.values


class _Result:
    def __init__(self, *, exists: bool = False, memberships: list[str] | None = None) -> None:
        self.exists = exists
        self.memberships = memberships or []

    def scalar_one_or_none(self) -> int | None:
        return 1 if self.exists else None

    def scalars(self) -> _ScalarRows:
        return _ScalarRows(self.memberships)


class _Connection:
    def __init__(self, *, exists: bool = True, memberships: list[str] | None = None) -> None:
        self.exists = exists
        self.memberships = memberships or []
        self.statements: list[str] = []

    def execute(self, statement, parameters=None):
        rendered = str(statement)
        self.statements.append(rendered)
        if "SELECT 1 FROM pg_roles" in rendered:
            return _Result(exists=self.exists)
        if "FROM pg_catalog.pg_auth_members" in rendered:
            return _Result(memberships=self.memberships)
        return _Result()


def test_existing_runtime_group_is_rehardened_not_trusted() -> None:
    connection = _Connection(exists=True)
    ensure_group(connection, "korpus_app_runtime")
    ddl = "\n".join(connection.statements)
    assert "ALTER ROLE \"korpus_app_runtime\"" in ddl
    for fragment in (
        "NOLOGIN", "NOSUPERUSER", "NOCREATEDB", "NOCREATEROLE", "NOINHERIT", "NOBYPASSRLS"
    ):
        assert fragment in ddl


def test_existing_login_is_rehardened_even_when_precreated() -> None:
    connection = _Connection(exists=True)
    ensure_login(connection, "korpus_app", "secret")
    ddl = "\n".join(connection.statements)
    assert "ALTER ROLE \"korpus_app\"" in ddl
    assert "NOSUPERUSER" in ddl
    assert "NOINHERIT" in ddl
    assert "NOBYPASSRLS" in ddl


def test_all_stale_memberships_are_revoked_before_exact_runtime_grant() -> None:
    connection = _Connection(
        memberships=["legacy_bypass", "legacy_owner", "korpus_review_runtime"]
    )
    revoke_all_memberships(connection, "korpus_app")
    ddl = "\n".join(connection.statements)
    assert 'REVOKE "legacy_bypass" FROM "korpus_app"' in ddl
    assert 'REVOKE "legacy_owner" FROM "korpus_app"' in ddl
    assert 'REVOKE "korpus_review_runtime" FROM "korpus_app"' in ddl
