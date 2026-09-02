#!/usr/bin/env python3
"""Offline fail-closed static checks for high-confidence dangerous primitives.

This gate supplements, but never substitutes for, external secret/dependency/image
scanners. It exists so the repository retains a zero-install security floor when
networked tooling is unavailable.
"""

from __future__ import annotations

import argparse
import ast
import json
import re
from pathlib import Path

from korpus.application.provenance import compute_source_digest

release_tag = __import__(
    "scripts.release_identity" if __package__ else "release_identity", fromlist=["release_tag"]
).release_tag

ROOT = Path(__file__).resolve().parents[1]
PYTHON_ROOTS = ("apps/api/src/korpus", "scripts")
SECRET_ROOTS = ("apps/api/src/korpus", "scripts", "config", "infra", "deploy")
EXCLUDED_PARTS = {
    "tests",
    "test",
    "docs",
    "evals",
    "reports",
    "var",
    "node_modules",
    ".venv",
    ".git",
}
SECRET_PATTERNS = {
    "private_key": re.compile(r"-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----"),
    "aws_access_key": re.compile(r"\bAKIA[0-9A-Z]{16}\b"),
    "github_pat": re.compile(r"\bgithub_pat_[A-Za-z0-9_]{20,}\b|\bgh[pousr]_[A-Za-z0-9]{30,}\b"),
    "openai_key": re.compile(r"\bsk-(?:proj-)?[A-Za-z0-9_-]{20,}\b"),
}


def _call_name(node: ast.Call) -> str:
    value = node.func
    parts: list[str] = []
    while isinstance(value, ast.Attribute):
        parts.append(value.attr)
        value = value.value
    if isinstance(value, ast.Name):
        parts.append(value.id)
    return ".".join(reversed(parts))


def _kw_bool(node: ast.Call, name: str) -> bool:
    for keyword in node.keywords:
        if keyword.arg == name and isinstance(keyword.value, ast.Constant):
            return keyword.value.value is True
    return False


#: Імена функцій, у яких слабкий геш не може бути «не для безпеки» за побудовою.
_SIGNING_CONTEXT = re.compile(r"sign|signature|mac\b|hmac|auth|verify|digest|token", re.I)


def _dangerous_rule(node: ast.Call, enclosing: str | None = None) -> str | None:
    name = _call_name(node)
    if name in {"eval", "exec", "builtins.eval", "builtins.exec"}:
        return "dynamic_code_execution"
    if name in {"os.system", "os.popen"}:
        return "shell_execution"
    subprocess_calls = {
        "subprocess.run",
        "subprocess.Popen",
        "subprocess.call",
        "subprocess.check_call",
        "subprocess.check_output",
    }
    if name in subprocess_calls and _kw_bool(node, "shell"):
        return "subprocess_shell_true"
    if name in {"pickle.load", "pickle.loads", "dill.load", "dill.loads"}:
        return "unsafe_deserialization"
    if name == "tempfile.mktemp":
        return "insecure_temporary_path"
    if name in {"yaml.load", "yaml.unsafe_load"}:
        return "unsafe_yaml_load"
    weak_hash = name in {"hashlib.md5", "hashlib.sha1"}
    explicit_nonsecurity = any(
        kw.arg == "usedforsecurity"
        and isinstance(kw.value, ast.Constant)
        and kw.value.value is False
        for kw in node.keywords
    )
    # `usedforsecurity=False` — це ТВЕРДЖЕННЯ КОДУ ПРО СЕБЕ, і гейт, який приймає
    # неперевірене твердження від власного суб'єкта, гейтом не є. Виміряно 02.09.2026:
    # єдиний ужиток цього прапорця в дереві стояв у `liqpay._digest`, який кличе
    # `sign_data`, тобто рахує ПІДПИС платіжного колбека. Прапорець казав «не для
    # безпеки» про підпис, і детектор через це мовчав саме там, де мав спрацювати.
    if weak_hash and explicit_nonsecurity and _SIGNING_CONTEXT.search(enclosing or ""):
        return "weak_security_hash_claimed_nonsecurity"
    return "weak_security_hash" if weak_hash and not explicit_nonsecurity else None


#: Прийняті знахідки. Прийняття — РІШЕННЯ з причиною і датою, а не прапорець у коді.
ACCEPTANCES = Path("config/operations/security-acceptances.json")


def _apply_acceptances(
    root: Path, findings: list[dict[str, object]]
) -> tuple[list[dict[str, object]], list[str]]:
    """Знімає названі знахідки й повертає МЕРТВІ записи окремо.

    Запис, що не збігається з жодною знахідкою, — теж дефект: реєстр не сміє переживати
    причину, заради якої існує. Це той самий негативний контроль, що `dead_exemption` у
    гейті замикання, і без нього реєстр повільно перетворюється на список побажань.

    Усі чотири поля обов'язкові. Запис без причини й дати не є названим.
    """
    path = root / ACCEPTANCES
    if not path.is_file():
        return findings, []
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return findings, ["реєстр прийняттів не читається"]
    entries = [
        item
        for item in payload.get("accepted", [])
        if isinstance(item, dict)
        and item.get("rule")
        and item.get("path")
        and item.get("reason")
        and item.get("on")
    ]
    keys = {(str(i["rule"]), str(i["path"])) for i in entries}
    seen = {(str(f["rule"]), str(f["path"])) for f in findings}
    remaining = [f for f in findings if (str(f["rule"]), str(f["path"])) not in keys]
    dead = sorted(f"{rule} @ {where}" for rule, where in keys - seen)
    return remaining, dead


def _scan_python_file(root: Path, path: Path) -> list[dict[str, object]]:
    relative = path.relative_to(root)
    try:
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(relative))
    except (OSError, UnicodeError, SyntaxError) as exc:
        return [
            {
                "rule": "python_parse_failure",
                "path": relative.as_posix(),
                "line": 0,
                "detail": str(exc),
            }
        ]
    # Ім'я охопної функції для КОЖНОГО виклику: правило слабкого гешу мусить знати, чи
    # він рахує підпис. Без цього прапорець `usedforsecurity=False` виправдовує будь-що.
    enclosing: dict[int, str] = {}
    for holder in ast.walk(tree):
        if isinstance(holder, (ast.FunctionDef, ast.AsyncFunctionDef)):
            for inner in ast.walk(holder):
                if isinstance(inner, ast.Call):
                    enclosing.setdefault(id(inner), holder.name)
    findings: list[dict[str, object]] = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        rule = _dangerous_rule(node, enclosing.get(id(node)))
        if rule:
            findings.append(
                {
                    "rule": rule,
                    "path": relative.as_posix(),
                    "line": getattr(node, "lineno", 0),
                    "detail": _call_name(node),
                }
            )
    return findings


def _ast_findings(root: Path) -> list[dict[str, object]]:
    findings: list[dict[str, object]] = []
    for base in PYTHON_ROOTS:
        for path in sorted((root / base).rglob("*.py")):
            relative = path.relative_to(root)
            if not any(part in EXCLUDED_PARTS for part in relative.parts):
                findings.extend(_scan_python_file(root, path))
    return findings


def _secret_findings(root: Path) -> list[dict[str, object]]:
    findings: list[dict[str, object]] = []
    for base in SECRET_ROOTS:
        target = root / base
        if not target.exists():
            continue
        for path in sorted(target.rglob("*")):
            if not path.is_file() or path.stat().st_size > 2_000_000:
                continue
            relative = path.relative_to(root)
            if any(part in EXCLUDED_PARTS for part in relative.parts):
                continue
            try:
                text = path.read_text(encoding="utf-8")
            except (OSError, UnicodeError):
                continue
            for rule, pattern in SECRET_PATTERNS.items():
                match = pattern.search(text)
                if match:
                    findings.append(
                        {
                            "rule": f"hardcoded_{rule}",
                            "path": relative.as_posix(),
                            "line": text[: match.start()].count("\n") + 1,
                        }
                    )
    return findings


def evaluate(root: Path) -> dict[str, object]:
    findings = [*_ast_findings(root), *_secret_findings(root)]
    findings, dead = _apply_acceptances(root, findings)
    checks = {
        "no_dead_acceptance": not dead,
        "python_sources_parse": not any(
            item["rule"] == "python_parse_failure" for item in findings
        ),
        "no_high_confidence_dangerous_primitives": not any(
            not str(item["rule"]).startswith("hardcoded_")
            and item["rule"] != "python_parse_failure"
            for item in findings
        ),
        "no_high_confidence_hardcoded_secrets": not any(
            str(item["rule"]).startswith("hardcoded_") for item in findings
        ),
    }
    return {
        "schema": "korpus.builtin-security-gate.v1",
        "status": "PASS" if all(checks.values()) else "FAIL",
        "release": release_tag(),
        "source_tree_sha256": compute_source_digest(root),
        "scope": {"python_roots": list(PYTHON_ROOTS), "secret_roots": list(SECRET_ROOTS)},
        "checks": checks,
        "findings": findings,
        "dead_acceptances": dead,
        "limitations": [
            "not_a_dependency_vulnerability_scan",
            "not_a_container_or_os_vulnerability_scan",
            "not_equivalent_to_gitleaks_trivy_pip_audit_or_osv_scanner",
        ],
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, default=ROOT)
    parser.add_argument("--out", type=Path)
    args = parser.parse_args()
    root = args.root.resolve()
    report = evaluate(root)
    rendered = json.dumps(report, ensure_ascii=False, indent=2) + "\n"
    if args.out:
        out = args.out if args.out.is_absolute() else root / args.out
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(rendered, encoding="utf-8")
    print(rendered, end="")
    return 0 if report["status"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
