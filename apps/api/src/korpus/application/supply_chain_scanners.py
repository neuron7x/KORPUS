from __future__ import annotations

from collections.abc import Collection, Mapping
from typing import Any

EXPECTED_SECURITY_SCANNERS = frozenset({"gitleaks", "pip-audit:runtime", "pip-audit:dev", "trivy"})
EXPECTED_CONTAINER_SCANNERS = frozenset({"trivy:api-image", "trivy:web-image"})


def _scanner_marker_clean(scan: Mapping[str, Any], expected: frozenset[str]) -> bool:
    records = scan.get("scanners", ())
    if not isinstance(records, list):
        return False
    parsed = {
        str(item.get("scanner")): item.get("exit_code")
        for item in records
        if isinstance(item, Mapping)
    }
    return (
        scan.get("status") == "PASS"
        and scan.get("worst_exit_code") == 0
        and set(parsed) == expected
        and len(records) == len(expected)
        and all(parsed[name] == 0 for name in expected)
    )


def scanner_summary_clean(scan: Mapping[str, Any]) -> bool:
    return _scanner_marker_clean(scan, EXPECTED_SECURITY_SCANNERS)


def container_scan_marker_clean(scan: Mapping[str, Any]) -> bool:
    return _scanner_marker_clean(scan, EXPECTED_CONTAINER_SCANNERS)


def scanner_marker_current(scan: Mapping[str, Any], accepted_commits: Collection[str]) -> bool:
    """Чи сканер біг на джерелі, тотожному цьому.

    Приймався ОДИН коміт, і брався він із `os.getenv("CI_COMMIT_SHA")`. У раннері це
    вимір — змінну ставить сам конвеєр; у локальній оболонці це ручна декларація, і
    саме нею 06.09.2026 був закритий сьомий твердий предикат. Тепер сюди подають
    множину, ВИМІРЯНУ по репозиторію: коміти, чиє джерело не відрізняється від
    поточного. Коміт, що змінив лише звіти, лишається прийнятним; порожня множина не
    приймає нічого.
    """
    return bool(accepted_commits) and scan.get("commit_sha") in set(accepted_commits)


#: Схему 2 пише ЛИШЕ `aggregate_ci_security_summary.py` — зі скрізних маркерів джобів,
#: що бігли в закріплених образах конвеєра. Схема 1 — локальний `security_scan.sh`.
CI_AGGREGATE_SCHEMA = 2


def scanner_summary_is_ci_aggregate(scan: Mapping[str, Any]) -> bool:
    """Чи цей підсумок узагалі того класу, якого вимагає предикат.

    Два виробники писали один файл у РІЗНИХ схемах, і слабший тихо ставав на місце
    сильнішого: назва лишалась та сама, клас доказу падав, а гейт бачив лише те, що
    коміт «не той». Скарга на свіжість там, де предмет — походження, читається як
    «перезніми», і перезняття робить гірше. Клас називається окремо.
    """
    return scan.get("schema_version") == CI_AGGREGATE_SCHEMA
