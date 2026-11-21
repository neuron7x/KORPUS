"""Fixed Gitleaks resource alignment, scan policy and non-authoritative CPU diagnostics."""

from __future__ import annotations


def gitleaks_environment(tool: str) -> list[str]:
    return ["--env", "GOMAXPROCS=2"] if tool == "gitleaks" else []


def gitleaks_arguments(commit: str) -> list[str]:
    return [
        "detect",
        "--source",
        "/source",
        "--no-banner",
        "--redact",
        "--exit-code",
        "1",
        "--log-opts",
        f"{commit} --full-history --diff-merges=first-parent",
        "--baseline-path",
        "/source/.gitleaks-baseline.json",
        "--report-format",
        "json",
        "--report-path",
        "/output/gitleaks.json",
        "--log-level",
        "info",
        "--timeout",
        "230",
        "--diagnostics",
        "cpu",
        "--diagnostics-dir",
        "/output/gitleaks-profile",
    ]
