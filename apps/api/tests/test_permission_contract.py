"""Every permission the API requires exists in the table the browser reads. Both ways.

`account:manage` was required by a route and named in no role. `admin` holds the wildcard,
so the API allowed it and every test passed — while the console decides which tab to show
from `ROLE_PERMISSIONS`, where the string did not appear. A deployment that later granted
`account:manage` to a `security-officer` without the wildcard would have had the API say
yes and the interface show nothing, and the person holding that role would have reported it
as "the console is broken".

The class is drift between two representations of one decision. So this compares them by
reading both, in both directions:

  required ⊆ known    a route may not check a permission the system does not name.
  known ⊇ granted     a role may not be granted a permission the system does not name.
  known = exported    the browser's copy is the same set, not a subset that happens to
                      cover today's roles.
"""

from __future__ import annotations

import ast
import json
import re
from pathlib import Path

from korpus.application.policy import KNOWN_PERMISSIONS, ROLE_PERMISSIONS

ROOT = Path(__file__).resolve().parents[3]
SRC = ROOT / "apps/api/src/korpus"
CONTRACT = ROOT / "apps/web/public/contract.js"


def _required_permissions() -> set[str]:
    """Every literal handed to `PolicyEngine.require`, read from the source.

    From the AST rather than by grep so a permission passed as a module constant —
    `require(identity, ACCOUNT_MANAGE)` — is resolved rather than missed. That form is the
    one the admin routes use, and a checker that only saw string literals would have
    reported the very gap it exists to catch as absent.
    """
    found: set[str] = set()
    for path in sorted(SRC.rglob("*.py")):
        source = path.read_text(encoding="utf-8")
        tree = ast.parse(source)
        constants = {
            target.id: node.value.value
            for node in ast.walk(tree)
            if isinstance(node, ast.Assign) and isinstance(node.value, ast.Constant)
            for target in node.targets
            if isinstance(target, ast.Name) and isinstance(node.value.value, str)
        }
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            function = node.func
            name = function.attr if isinstance(function, ast.Attribute) else None
            if name != "require" or len(node.args) < 2:
                continue
            argument = node.args[1]
            if isinstance(argument, ast.Constant) and isinstance(argument.value, str):
                found.add(argument.value)
            elif isinstance(argument, ast.Name) and argument.id in constants:
                found.add(constants[argument.id])
    return found


def _exported_permissions() -> set[str]:
    body = CONTRACT.read_text(encoding="utf-8")
    match = re.search(r"export const CONTRACT = (\{.*\});?\s*$", body, re.DOTALL)
    assert match, "contract.js is no longer a single exported object"
    return set(json.loads(match.group(1))["permissions"])


def test_every_permission_a_route_requires_is_a_permission_the_system_names() -> None:
    required = _required_permissions()
    assert required, "no permission checks were found — this test is stale"
    unknown = sorted(required - KNOWN_PERMISSIONS)
    assert not unknown, (
        "these permissions are checked by the API and named nowhere, so nothing that "
        f"reads the permission table can know they exist: {unknown}"
    )


def test_every_granted_permission_is_a_permission_the_system_names() -> None:
    granted = {
        permission
        for permissions in ROLE_PERMISSIONS.values()
        for permission in permissions
        if permission != "*"
    }
    unknown = sorted(granted - KNOWN_PERMISSIONS)
    assert not unknown, f"these permissions are granted to a role and named nowhere: {unknown}"


def test_the_browser_reads_the_same_set_the_server_holds() -> None:
    exported = _exported_permissions()
    assert exported == set(KNOWN_PERMISSIONS), {
        "only in the browser": sorted(exported - KNOWN_PERMISSIONS),
        "only in the server": sorted(KNOWN_PERMISSIONS - exported),
    }


def test_nothing_named_is_unreachable() -> None:
    """The dual. A permission nobody checks and nobody grants is a string in a set.

    Not a failure — `training:manage` is granted to `instructor` and checked nowhere yet —
    so this reports rather than refuses. What it stops is the set becoming a graveyard
    that the two checks above then pass against trivially.
    """
    required = _required_permissions()
    granted = {
        permission
        for permissions in ROLE_PERMISSIONS.values()
        for permission in permissions
        if permission != "*"
    }
    orphaned = sorted(KNOWN_PERMISSIONS - required - granted)
    assert not orphaned, (
        "these permissions are named, checked by no route and granted to no role; either "
        f"they are dead or something was renamed around them: {orphaned}"
    )


def test_account_management_is_held_by_no_ordinary_role() -> None:
    """The specific rule the general check exists to keep: only the wildcard reaches it."""
    for role, permissions in ROLE_PERMISSIONS.items():
        if role == "admin":
            assert "*" in permissions
            continue
        assert "account:manage" not in permissions, f"{role} may switch a person off"


def test_admin_wildcard_does_not_authorize_an_unknown_permission() -> None:
    from korpus.application.policy import AuthorizationError, PolicyEngine
    from korpus.domain.models import Identity
    import pytest

    admin = Identity(subject="admin", roles=frozenset({"admin"}), corpora=frozenset({"public"}))
    with pytest.raises(AuthorizationError, match="unknown permission"):
        PolicyEngine().require(admin, "document:aprove")
