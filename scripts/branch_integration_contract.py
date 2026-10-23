"""Pure schema and decision contract for branch integration."""

from __future__ import annotations

import re
from typing import Any

from branch_integration_declaration import convergence_candidate

REGISTRY_SCHEMA = "korpus.branch-integration-registry.v1"
CANONICAL_DECLARATION = "config/operations/canonical-state.json"
HEAD_SHA = re.compile(r"[0-9a-f]{40}")
ISO_DATE = re.compile(r"\d{4}-\d{2}-\d{2}")
BASE_FIELDS = {
    "schema",
    "canonical_branch_declared_in",
    "integrated",
    "measured_at",
    "note",
    "stranded",
}
TRANSITION_FIELDS = {"blocker", "convergence_candidate_ref", "integration_order"}
BLOCKER_FIELDS = {"kind", "detail", "closes_when"}
INTEGRATED_FIELDS = {"branch", "head", "disposition", "into", "note", "on"}
ARCHIVE_FIELDS = {"archive_tag", "archive_signer", "archive_signer_fingerprint"}
STRANDED_FIELDS = {"branch", "head", "unique", "clean", "carries", "closes_when"}


def _finding(check: str, verdict: str, detail: str) -> dict[str, str]:
    return {"check": check, "verdict": verdict, "detail": detail}


def _nonempty(value: object, minimum: int = 1) -> bool:
    return isinstance(value, str) and len(value.strip()) >= minimum


def _exact_fields(
    entry: dict[str, Any], expected: set[str], prefix: str, errors: list[str]
) -> None:
    missing = sorted(expected - set(entry))
    extra = sorted(set(entry) - expected)
    if missing:
        errors.append(f"{prefix} missing fields: {', '.join(missing)}")
    if extra:
        errors.append(f"{prefix} unknown fields: {', '.join(extra)}")


def _common_integrated_errors(entry: dict[str, Any], prefix: str) -> list[str]:
    errors: list[str] = []
    if not _nonempty(entry.get("branch")):
        errors.append(f"{prefix}.branch is invalid")
    if not isinstance(entry.get("head"), str) or HEAD_SHA.fullmatch(entry["head"]) is None:
        errors.append(f"{prefix}.head is not a full commit SHA")
    if entry.get("disposition") not in {"ancestor", "superseded_archive"}:
        errors.append(f"{prefix}.disposition is invalid")
    for field in ("into", "note"):
        if not _nonempty(entry.get(field)):
            errors.append(f"{prefix}.{field} is invalid")
    if not isinstance(entry.get("on"), str) or ISO_DATE.fullmatch(entry["on"]) is None:
        errors.append(f"{prefix}.on is invalid")
    return errors


def _integrated_entry_errors(entry: object, index: int) -> list[str]:
    prefix = f"integrated[{index}]"
    if not isinstance(entry, dict):
        return [f"{prefix} is not an object"]
    disposition = entry.get("disposition")
    expected = INTEGRATED_FIELDS | (
        ARCHIVE_FIELDS if disposition == "superseded_archive" else set()
    )
    errors = _common_integrated_errors(entry, prefix)
    _exact_fields(entry, expected, prefix, errors)
    if disposition == "superseded_archive":
        if not _nonempty(entry.get("archive_tag")):
            errors.append(f"{prefix}.archive_tag is required")
        if not _nonempty(entry.get("archive_signer")):
            errors.append(f"{prefix}.archive_signer is required")
        fingerprint = entry.get("archive_signer_fingerprint")
        if not isinstance(fingerprint, str) or not fingerprint.startswith("SHA256:"):
            errors.append(f"{prefix}.archive_signer_fingerprint is required")
    return errors


def _stranded_entry_errors(entry: object, index: int) -> list[str]:
    prefix = f"stranded[{index}]"
    if not isinstance(entry, dict):
        return [f"{prefix} is not an object"]
    expected = STRANDED_FIELDS | ({"clean_but_held"} if entry.get("clean") is True else set())
    errors: list[str] = []
    _exact_fields(entry, expected, prefix, errors)
    if not _nonempty(entry.get("branch")):
        errors.append(f"{prefix}.branch is invalid")
    if not isinstance(entry.get("head"), str) or HEAD_SHA.fullmatch(entry["head"]) is None:
        errors.append(f"{prefix}.head is not a full commit SHA")
    unique = entry.get("unique")
    if isinstance(unique, bool) or not isinstance(unique, int) or unique <= 0:
        errors.append(f"{prefix}.unique is invalid")
    if not isinstance(entry.get("clean"), bool):
        errors.append(f"{prefix}.clean is invalid")
    for field in ("carries", "closes_when"):
        if not _nonempty(entry.get(field), 20):
            errors.append(f"{prefix}.{field} is invalid")
    if entry.get("clean") is True and not _nonempty(entry.get("clean_but_held"), 20):
        errors.append(f"{prefix}.clean_but_held is required")
    return errors


def _top_level_errors(registry: dict[str, Any]) -> list[str]:
    errors: list[str] = []
    stranded = registry.get("stranded")
    expected = BASE_FIELDS | (
        TRANSITION_FIELDS if isinstance(stranded, list) and stranded else set()
    )
    _exact_fields(registry, expected, "root", errors)
    if registry.get("schema") != REGISTRY_SCHEMA:
        errors.append("schema mismatch")
    if registry.get("canonical_branch_declared_in") != CANONICAL_DECLARATION:
        errors.append("canonical declaration path mismatch")
    if (
        not isinstance(registry.get("measured_at"), str)
        or ISO_DATE.fullmatch(registry["measured_at"]) is None
    ):
        errors.append("measured_at is invalid")
    if not _nonempty(registry.get("note"), 20):
        errors.append("note is invalid")
    if expected >= TRANSITION_FIELDS:
        errors.extend(_transition_errors(registry))
    return errors


def _transition_errors(registry: dict[str, Any]) -> list[str]:
    errors: list[str] = []
    blocker = registry.get("blocker")
    if not isinstance(blocker, dict):
        errors.append("blocker is not an object")
    else:
        _exact_fields(blocker, BLOCKER_FIELDS, "blocker", errors)
        for field in BLOCKER_FIELDS:
            if not _nonempty(blocker.get(field), 20 if field != "kind" else 1):
                errors.append(f"blocker.{field} is invalid")
    order = registry.get("integration_order")
    if not isinstance(order, list) or not order or not all(_nonempty(item, 20) for item in order):
        errors.append("integration_order is invalid")
    candidate = convergence_candidate(registry)
    if candidate is None:
        errors.append("convergence_candidate_ref is invalid")
    integrated = registry.get("integrated")
    if candidate is not None and isinstance(integrated, list):
        wrong_targets = sorted(
            entry.get("branch", f"integrated[{index}]")
            for index, entry in enumerate(integrated)
            if isinstance(entry, dict) and entry.get("into") != candidate
        )
        if wrong_targets:
            errors.append(
                "integrated records target a different convergence candidate: "
                + ", ".join(wrong_targets)
            )
    return errors


def registry_errors(registry: dict[str, Any]) -> list[str]:
    if not isinstance(registry, dict):
        return ["root is not an object"]
    errors = _top_level_errors(registry)
    integrated = registry.get("integrated")
    stranded = registry.get("stranded")
    if not isinstance(integrated, list):
        errors.append("integrated is not a list")
        integrated = []
    if not isinstance(stranded, list):
        errors.append("stranded is not a list")
        stranded = []
    for index, entry in enumerate(integrated):
        errors.extend(_integrated_entry_errors(entry, index))
    for index, entry in enumerate(stranded):
        errors.extend(_stranded_entry_errors(entry, index))
    errors.extend(_cross_record_errors(integrated, stranded))
    return errors


def _indexed(entries: list[object]) -> tuple[dict[str, dict[str, Any]], list[str]]:
    indexed: dict[str, dict[str, Any]] = {}
    duplicates: list[str] = []
    for entry in entries:
        if not isinstance(entry, dict) or not isinstance(entry.get("branch"), str):
            continue
        branch = entry["branch"]
        if branch in indexed:
            duplicates.append(branch)
        indexed[branch] = entry
    return indexed, duplicates


def _cross_record_errors(integrated: list[object], stranded: list[object]) -> list[str]:
    integrated_by_branch, integrated_duplicates = _indexed(integrated)
    stranded_by_branch, stranded_duplicates = _indexed(stranded)
    errors = [f"duplicate integrated branch: {name}" for name in integrated_duplicates]
    errors.extend(f"duplicate stranded branch: {name}" for name in stranded_duplicates)
    for branch, entry in stranded_by_branch.items():
        integrated_entry = integrated_by_branch.get(branch)
        if integrated_entry is None:
            errors.append(f"stranded branch has no integrated record: {branch}")
        elif integrated_entry.get("head") != entry.get("head"):
            errors.append(f"stranded head differs from integrated record: {branch}")
    return errors


def _named(registry: dict[str, Any]) -> dict[str, dict[str, Any]]:
    entries = registry.get("stranded") if isinstance(registry, dict) else None
    indexed, _duplicates = _indexed(entries if isinstance(entries, list) else [])
    return indexed


def _exact_state_finding(
    diverged: dict[str, Any], named: dict[str, dict[str, Any]]
) -> dict[str, str]:
    drifted = sorted(
        branch
        for branch in set(named) & set(diverged)
        if any(
            named[branch].get(field) != diverged[branch].get(field)
            for field in ("head", "unique", "clean")
        )
    )
    if drifted:
        return _finding(
            "recorded_branch_state_exact",
            "FAIL",
            "head/unique/clean не збігаються зі спостереженням: " + ", ".join(drifted),
        )
    return _finding(
        "recorded_branch_state_exact", "PASS", "кожен head, count і merge-verdict збігається"
    )


def _entry_proof_failures(entry: dict[str, Any], state: object) -> list[str]:
    branch = entry["branch"]
    if not isinstance(state, dict) or not state.get("commit_exists"):
        return [f"{branch}: commit missing"]
    failures: list[str] = []
    if state.get("head") != entry.get("head"):
        failures.append(f"{branch}: observed wrong head")
    ancestor = state.get("ancestor_of_checkout") is True
    if entry.get("disposition") == "ancestor" and not ancestor:
        failures.append(f"{branch}: head is not an ancestor of checkout")
    if entry.get("disposition") == "superseded_archive" and ancestor:
        failures.append(f"{branch}: archived head is already an ancestor of checkout")
    if entry.get("disposition") == "superseded_archive":
        if state.get("archive_tag_target") != entry.get("head"):
            failures.append(f"{branch}: archive tag does not resolve to head")
        if state.get("archive_remote_tag_target") != entry.get("head"):
            failures.append(f"{branch}: remote archive tag does not peel to head")
        local_object = state.get("archive_tag_object")
        if not isinstance(local_object, str) or HEAD_SHA.fullmatch(local_object) is None:
            failures.append(f"{branch}: local archive tag is not annotated")
        if state.get("archive_remote_tag_object") != local_object:
            failures.append(f"{branch}: signed archive tag object is not published")
        if not state.get("archive_tag_verified"):
            failures.append(f"{branch}: archive tag signature is not trusted")
    return failures


def _provenance_finding(observation: dict[str, Any], registry: dict[str, Any]) -> dict[str, str]:
    observed = observation.get("integrated")
    entries = registry.get("integrated")
    if not isinstance(observed, dict) or not isinstance(entries, list):
        return _finding("integrated_head_provenance", "UNKNOWN", "інтегровані head не прочитано")
    valid_entries = [
        entry
        for entry in entries
        if isinstance(entry, dict) and isinstance(entry.get("branch"), str)
    ]
    expected = {entry["branch"] for entry in valid_entries}
    failures = [f"unexpected observed head: {name}" for name in sorted(set(observed) - expected)]
    for entry in valid_entries:
        failures.extend(_entry_proof_failures(entry, observed.get(entry["branch"])))
    if failures:
        return _finding("integrated_head_provenance", "FAIL", "; ".join(sorted(failures)))
    return _finding(
        "integrated_head_provenance",
        "PASS",
        "ancestor/archive disposition кожного head підтверджено",
    )


def assess(observation: dict[str, Any], registry: dict[str, Any]) -> list[dict[str, str]]:
    errors = registry_errors(registry)
    findings = [
        _finding(
            "registry_schema",
            "FAIL" if errors else "PASS",
            "; ".join(errors) if errors else "реєстр структурно повний",
        )
    ]
    diverged = observation.get("diverged")
    if not isinstance(diverged, dict):
        findings.append(_finding("branch_integration", "UNKNOWN", "гілки не прочитано"))
        return findings
    named = _named(registry)
    unnamed = sorted(set(diverged) - set(named))
    findings.append(
        _finding(
            "every_branch_named",
            "FAIL" if unnamed else "PASS",
            (
                "гілка з власними комітами, якої ніхто не назвав: " + ", ".join(unnamed)
                if unnamed
                else f"{len(diverged)} гілок поза каноном, усі названі"
            ),
        )
    )
    findings.append(_exact_state_finding(diverged, named))
    findings.append(_provenance_finding(observation, registry))
    dead = sorted(set(named) - set(diverged))
    findings.append(
        _finding(
            "no_dead_entry",
            "FAIL" if dead else "PASS",
            (
                "запис про гілку, яка вже влита або зникла: " + ", ".join(dead)
                if dead
                else f"{len(named)} записів усі ще потрібні"
            ),
        )
    )
    findings.extend(_narrative_findings(diverged, named))
    return findings


def _narrative_findings(
    diverged: dict[str, Any], named: dict[str, dict[str, Any]]
) -> list[dict[str, str]]:
    silent = sorted(
        branch
        for branch, entry in named.items()
        if branch in diverged and not _nonempty(entry.get("carries"), 20)
    )
    lingering = sorted(
        branch
        for branch, state in diverged.items()
        if state.get("clean") and not _nonempty(named.get(branch, {}).get("clean_but_held"), 20)
    )
    return [
        _finding(
            "carries_is_named",
            "FAIL" if silent else "PASS",
            (
                "запис не каже, що саме гілка везе: " + ", ".join(silent)
                if silent
                else "кожен запис називає свій вантаж"
            ),
        ),
        _finding(
            "clean_branch_not_left_hanging",
            "FAIL" if lingering else "PASS",
            (
                "зливається ЧИСТО і досі не влита, причини не названо: " + ", ".join(lingering)
                if lingering
                else "жодної чистої гілки без причини не влито"
            ),
        ),
    ]


def verdict(findings: list[dict[str, str]]) -> str:
    if not findings:
        return "UNKNOWN"
    verdicts = {item["verdict"] for item in findings}
    if "FAIL" in verdicts:
        return "FAIL"
    return "UNKNOWN" if "UNKNOWN" in verdicts else "PASS"
