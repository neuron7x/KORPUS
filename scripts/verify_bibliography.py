#!/usr/bin/env python3
"""Validate and deterministically render the KORPUS engineering bibliography."""

from __future__ import annotations

import argparse
import copy
import json
import re
from collections import Counter
from collections.abc import Callable
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

ROOT = Path(__file__).resolve().parents[1]
REGISTRY = Path("config/assurance/ASSURANCE_SOURCE_REGISTRY_2026.json")
MARKDOWN = Path("docs/research/BIBLIOGRAPHY_2026.md")
BIBTEX = Path("docs/research/korpus-engineering-2026.bib")
SCHEMA = "korpus.assurance-source-registry.v2"
MINIMUM_SOURCES = 50
ALLOWED_TYPES = {
    "industry-methodology",
    "law",
    "official-documentation",
    "official-guidance",
    "official-policy",
    "peer-reviewed-research",
    "preprint",
    "specification",
    "standard",
}
ALLOWED_STATUSES = {
    "approved",
    "best-current-practice",
    "current",
    "final",
    "final-under-revision",
    "informational",
    "law-current",
    "living",
    "preprint",
    "recommendation",
    "research",
    "stable",
}
ID_PATTERN = re.compile(r"^[A-Z0-9][A-Z0-9._-]+$")
DOI_PATTERN = re.compile(r"^10\.\d{4,9}/\S+$", re.IGNORECASE)
JsonMap = dict[str, Any]


def _nonempty_text(value: object) -> bool:
    return isinstance(value, str) and bool(value.strip())


def _valid_https(value: object) -> bool:
    if not isinstance(value, str):
        return False
    parsed = urlparse(value)
    return parsed.scheme == "https" and bool(parsed.netloc)


def _source_scalar_failures(source: dict[str, object], prefix: str, as_of_year: int) -> list[str]:
    failures: list[str] = []
    source_id = source.get("id")
    if not isinstance(source_id, str) or not ID_PATTERN.fullmatch(source_id):
        failures.append(f"{prefix}.id")
    for field in ("authority", "title", "used_for", "boundary"):
        if not _nonempty_text(source.get(field)):
            failures.append(f"{prefix}.{field}")
    if source.get("type") not in ALLOWED_TYPES:
        failures.append(f"{prefix}.type")
    if source.get("status") not in ALLOWED_STATUSES:
        failures.append(f"{prefix}.status")
    year = source.get("year")
    if not isinstance(year, int) or isinstance(year, bool) or not 1900 <= year <= as_of_year:
        failures.append(f"{prefix}.year")
    if not _valid_https(source.get("url")):
        failures.append(f"{prefix}.url")
    doi = source.get("doi")
    if doi is not None and (not isinstance(doi, str) or not DOI_PATTERN.fullmatch(doi)):
        failures.append(f"{prefix}.doi")
    return failures


def _source_list_failures(
    source: dict[str, object], prefix: str, known_domains: set[str]
) -> list[str]:
    failures: list[str] = []
    authors = source.get("authors")
    if not isinstance(authors, list) or not authors or not all(_nonempty_text(v) for v in authors):
        failures.append(f"{prefix}.authors")
    domains = source.get("domains")
    if not isinstance(domains, list) or not domains or len(domains) != len(set(domains)):
        failures.append(f"{prefix}.domains")
    elif any(domain not in known_domains for domain in domains):
        failures.append(f"{prefix}.unknown_domain")
    return failures


def _source_failures(
    source: object, index: int, known_domains: set[str], as_of_year: int
) -> list[str]:
    prefix = f"sources[{index}]"
    if not isinstance(source, dict):
        return [f"{prefix}.shape"]
    return [
        *_source_scalar_failures(source, prefix, as_of_year),
        *_source_list_failures(source, prefix, known_domains),
    ]


def _metadata_failures(data: dict[str, object]) -> tuple[list[str], int]:
    failures: list[str] = []
    if data.get("schema") != SCHEMA:
        failures.append("schema")
    as_of = data.get("as_of")
    if not isinstance(as_of, str) or not re.fullmatch(r"\d{4}-\d{2}-\d{2}", as_of):
        failures.append("as_of")
        as_of_year = 1900
    else:
        as_of_year = int(as_of[:4])
    verification = data.get("verification")
    if not isinstance(verification, dict) or verification.get("reviewed_on") != as_of:
        failures.append("verification.reviewed_on")
    elif not all(_nonempty_text(verification.get(field)) for field in ("method", "freshness_rule")):
        failures.append("verification.method")
    exclusions = data.get("exclusions")
    if not isinstance(exclusions, dict) or not all(
        _nonempty_text(exclusions.get(field))
        for field in ("doctrine_corpus", "compliance", "secondary_sources")
    ):
        failures.append("exclusions")
    return failures, as_of_year


def _domain_config(data: dict[str, object]) -> tuple[list[str], int, list[str]]:
    failures: list[str] = []
    domains = data.get("required_domains")
    if (
        not isinstance(domains, list)
        or not domains
        or len(domains) != len(set(domains))
        or not all(_nonempty_text(domain) for domain in domains)
    ):
        return [], 2, ["required_domains"]
    floor = data.get("minimum_sources_per_domain")
    if not isinstance(floor, int) or isinstance(floor, bool) or floor < 2:
        failures.append("minimum_sources_per_domain")
        floor = 2
    return domains, floor, failures


def _duplicate_failures(sources: list[object]) -> list[str]:
    failures: list[str] = []
    mappings = {
        "id": [
            value
            for source in sources
            if isinstance(source, dict) and isinstance((value := source.get("id")), str)
        ],
        "url": [
            value
            for source in sources
            if isinstance(source, dict) and isinstance((value := source.get("url")), str)
        ],
        "doi": [
            value
            for source in sources
            if isinstance(source, dict) and isinstance((value := source.get("doi")), str)
        ],
    }
    for label, values in mappings.items():
        duplicates = sorted(value for value, count in Counter(values).items() if count > 1)
        failures.extend(f"duplicate.{label}:{value}" for value in duplicates)
    return failures


def _coverage_failures(sources: list[object], domains: list[str], floor: int) -> list[str]:
    coverage = Counter(
        domain
        for source in sources
        if isinstance(source, dict) and isinstance(source.get("domains"), list)
        for domain in source["domains"]
    )
    return [
        f"domain.floor:{domain}:{coverage[domain]}<{floor}"
        for domain in sorted(domains)
        if coverage[domain] < floor
    ]


def verify_registry(data: object) -> list[str]:
    if not isinstance(data, dict):
        return ["registry.shape"]
    failures, as_of_year = _metadata_failures(data)
    domains, floor, domain_failures = _domain_config(data)
    failures.extend(domain_failures)
    if not domains:
        return failures
    sources = data.get("sources")
    if not isinstance(sources, list):
        return [*failures, "sources.shape"]
    if len(sources) < MINIMUM_SOURCES:
        failures.append(f"sources.floor:{len(sources)}<{MINIMUM_SOURCES}")
    for index, source in enumerate(sources):
        failures.extend(_source_failures(source, index, set(domains), as_of_year))
    failures.extend(_duplicate_failures(sources))
    failures.extend(_coverage_failures(sources, domains, floor))
    return failures


def _authors(source: JsonMap) -> str:
    return "; ".join(str(author) for author in source["authors"])


def render_markdown(data: JsonMap) -> str:
    sources = sorted(data["sources"], key=lambda value: value["id"])
    coverage = Counter(domain for source in sources for domain in source["domains"])
    lines = [
        "# KORPUS technical and research bibliography — 2026",
        "",
        f"Reviewed: `{data['as_of']}`. Canonical data: `config/assurance/ASSURANCE_SOURCE_REGISTRY_2026.json`.",
        "",
        str(data["scope"]),
        "",
        "## Epistemic boundary",
        "",
        f"- {data['exclusions']['compliance']}",
        f"- {data['exclusions']['doctrine_corpus']}",
        f"- {data['exclusions']['secondary_sources']}",
        f"- {data['verification']['freshness_rule']}",
        "",
        "## Coverage",
        "",
    ]
    lines.extend(
        f"- `{domain}` — {coverage[domain]} sources" for domain in data["required_domains"]
    )
    lines.extend(["", "## Bibliography", ""])
    for source in sources:
        doi = f" DOI: `{source['doi']}`." if source.get("doi") else ""
        lines.extend(
            [
                f"### {source['id']}",
                "",
                f"{_authors(source)} ({source['year']}). *{source['title']}*. "
                f"{source['authority']}. [{source['url']}]({source['url']}).{doi}",
                "",
                f"Status: `{source['status']}`; type: `{source['type']}`; "
                f"domains: {', '.join(f'`{domain}`' for domain in source['domains'])}.",
                "",
                f"Use: {source['used_for']}",
                "",
                f"Boundary: {source['boundary']}",
                "",
            ]
        )
    return "\n".join(lines).rstrip() + "\n"


def _bibtex_escape(value: object) -> str:
    return str(value).replace("\\", "\\textbackslash{}").replace("{", "\\{").replace("}", "\\}")


def render_bibtex(data: JsonMap) -> str:
    chunks = [
        "% Generated from config/assurance/ASSURANCE_SOURCE_REGISTRY_2026.json.",
        "% Run: python3 scripts/verify_bibliography.py --write",
        "",
    ]
    for source in sorted(data["sources"], key=lambda value: value["id"]):
        fields = [
            ("author", " and ".join(str(author) for author in source["authors"])),
            ("title", source["title"]),
            ("year", source["year"]),
            ("publisher", source["authority"]),
            ("url", source["url"]),
        ]
        if source.get("doi"):
            fields.append(("doi", source["doi"]))
        fields.extend(
            [
                ("note", f"KORPUS status: {source['status']}; type: {source['type']}"),
                ("keywords", ", ".join(source["domains"])),
            ]
        )
        chunks.append(f"@misc{{{source['id']},")
        for key, value in fields:
            chunks.append(f"  {key} = {{{_bibtex_escape(value)}}},")
        chunks.extend(["}", ""])
    return "\n".join(chunks).rstrip() + "\n"


def verify_rendered(root: Path, data: JsonMap) -> list[str]:
    failures: list[str] = []
    expected = ((MARKDOWN, render_markdown(data)), (BIBTEX, render_bibtex(data)))
    for relative, rendered in expected:
        path = root / relative
        if not path.is_file():
            failures.append(f"missing_render:{relative}")
        elif path.read_text(encoding="utf-8") != rendered:
            failures.append(f"stale_render:{relative}")
    return failures


def selftest(data: JsonMap, root: Path) -> tuple[list[str], int]:
    """Повертає вижилі проби І ЇХНЮ КІЛЬКІСТЬ.

    ВИМІРЯНО 02.09.2026: звіт ніс поле `negative_controls: 8 if args.selftest else 0` —
    константу в одязі виміру. Число було правильним у момент написання й саме тому
    небезпечним: додай дев'яту мутацію, і поле збреше МОВЧКИ, бо воно є ДРУГИМ
    оголошенням того, що код і так рахує. Сигнал, який ніколи не бував іншим, не є
    виміром.
    """
    probes: list[tuple[str, JsonMap]] = []
    mutations: dict[str, Callable[[JsonMap], object]] = {
        "duplicate_id": lambda value: value["sources"].append(copy.deepcopy(value["sources"][0])),
        "missing_boundary": lambda value: value["sources"][0].__setitem__("boundary", ""),
        "bad_url": lambda value: value["sources"][0].__setitem__("url", "http://example.invalid"),
        "unknown_domain": lambda value: value["sources"][0]["domains"].append("unknown"),
        "future_year": lambda value: value["sources"][0].__setitem__("year", 9999),
        "coverage_hole": lambda value: [
            source["domains"].remove("neuroscience_basis")
            for source in value["sources"]
            if "neuroscience_basis" in source["domains"]
        ],
        "unreviewed": lambda value: value["verification"].__setitem__("reviewed_on", "2026-09-01"),
    }
    for name, mutate in mutations.items():
        candidate = copy.deepcopy(data)
        mutate(candidate)
        probes.append((name, candidate))
    survivors = [name for name, candidate in probes if not verify_registry(candidate)]
    stale = copy.deepcopy(data)
    stale["sources"][0]["title"] += " mutated"
    if not verify_rendered(root, stale):
        survivors.append("stale_render")
    return survivors, len(probes) + 1


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, default=ROOT)
    parser.add_argument("--write", action="store_true")
    parser.add_argument("--selftest", action="store_true")
    args = parser.parse_args()
    root = args.root.resolve()
    registry = root / REGISTRY
    data = json.loads(registry.read_text(encoding="utf-8"))
    failures = verify_registry(data)
    if not failures and args.write:
        (root / MARKDOWN).write_text(render_markdown(data), encoding="utf-8")
        (root / BIBTEX).write_text(render_bibtex(data), encoding="utf-8")
    if not failures:
        failures.extend(verify_rendered(root, data))
    controls = 0
    if args.selftest and not failures:
        killed, controls = selftest(data, root)
        if killed:
            failures.extend(f"selftest_survivor:{name}" for name in killed)
    result = {
        "schema": "korpus.bibliography-verification.v1",
        "status": "PASS" if not failures else "FAIL",
        "sources": len(data.get("sources", [])),
        "domains": len(data.get("required_domains", [])),
        "negative_controls": controls,
        "failures": failures,
    }
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if not failures else 1


if __name__ == "__main__":
    raise SystemExit(main())
