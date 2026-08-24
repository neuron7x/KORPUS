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


def _dangerous_rule(node: ast.Call) -> str | None:
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
    return "weak_security_hash" if weak_hash and not explicit_nonsecurity else None


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
    findings: list[dict[str, object]] = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        rule = _dangerous_rule(node)
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
    checks = {
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
