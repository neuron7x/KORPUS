#!/usr/bin/env python3
"""Оголошений юніт, що несе свіжий код і ВІДМОВЛЯЄ кожному, — це відмова, не свіжість.

Виміряно 06.09.2026. `check_serving_freshness` питає, чи процеси оголошених юнітів
несуть поточну ревізію, і відповідає «8 процесів несуть код 5c643d0b». Публічний
сервіс справді ніс її — і три доби віддавав `503` КОЖНОМУ запиту, бо його якір аудиту
пам'ятає 81 подію, яких відновлена база не має. Конвеєр був 18/18, `make validate`
rc=0, лан розгортання зелений, а система, до якої прийшла б запрошена людина, не
відповідала жодного разу.

Свіжість коду і здатність обслуговувати — РІЗНІ властивості. Перша вимірювалась, друга
не вимірювалась ніде, і саме тому мовчала.

    check_serving_readiness.py [--out ФАЙЛ]
    check_serving_readiness.py --selftest
"""

from __future__ import annotations

import argparse
import json
import sys
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
from check_serving_freshness import required_units, serving_processes, unit_states  # noqa: E402
from serving_readiness_contract import owned_ports, readiness_checks, ready_response  # noqa: E402

TIMEOUT = 10.0


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *_args: object, **_kwargs: object) -> None:
        return None


def probe(port: int, path: str = "/ready", timeout: float = TIMEOUT) -> dict[str, Any]:
    """Стан одного шляху на одному порту. Недосяжність — теж стан, не брак виміру."""
    url = f"http://127.0.0.1:{port}{path}"
    try:
        with urllib.request.build_opener(_NoRedirect).open(url, timeout=timeout) as response:
            return {
                "port": port,
                "path": path,
                "status": response.status,
                "body": response.read(4096).decode(),
            }
    except urllib.error.HTTPError as e:
        status = None if 300 <= e.code < 400 else e.code
        return dict(port=port, path=path, status=status, body=e.read(4096).decode(errors="replace"))
    except (UnicodeDecodeError, OSError) as error:
        return {
            "port": port,
            "path": path,
            "status": None,
            "body": f"{type(error).__name__}: {error}",
        }


def refusing_detail(body: str) -> list[str]:
    """Які саме перевірки готовності хибні. Без цього «503» — це «щось не так»."""
    try:
        payload = json.loads(body)
    except json.JSONDecodeError:
        return []
    detail = payload.get("detail") if isinstance(payload, dict) else {}
    detail = detail if isinstance(detail, dict) else payload
    return sorted(key for key, value in detail.items() if value is False)


def liveness_masking(ready: list[dict[str, Any]], live: list[dict[str, Any]]) -> list[int]:
    """Порти, де живучість каже «ок», а готовність відмовляє.

    Саме ця пара тримала простій невидимим три доби: усе, що дивилось на сервіс,
    дивилось на `/health`, а він віддає 200 доти, доки процес живий. «Здоровий» і
    «здатний відповісти» — різні твердження, і перше не є свідченням про друге.
    """
    healthy = {item["port"] for item in live if item["status"] == 200}
    return sorted({item["port"] for item in ready if not ready_response(item)} & healthy)


def verdict(
    units: list[str],
    ports: list[int],
    probes: list[dict[str, Any]],
    liveness: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Оголошено — значить мусить відповідати. Порожній перелік не є згодою."""
    checks = readiness_checks(units, ports, probes)
    admitted = probes if checks["probe_set_complete"] else []
    serving = [item for item in admitted if ready_response(item)]
    refusing = [item for item in admitted if not ready_response(item)]
    masked = liveness_masking(admitted, liveness or [])
    failures = [name for name, ok in checks.items() if not ok]
    return {
        "schema": "korpus.serving-readiness.v1",
        "status": "PASS" if not failures else "FAIL",
        "declared_units": units,
        "probed_ports": ports,
        "serving": [item["port"] for item in serving],
        "refusing": [
            {
                "port": item["port"],
                "status": item["status"],
                "false_checks": refusing_detail(str(item["body"])),
            }
            for item in refusing
        ],
        "liveness_masking_readiness": masked,
        "checks": checks,
        "failures": failures,
        "interpretation": (
            "Свіжість коду не є здатністю обслуговувати. Процес, що несе поточну ревізію і "
            "відмовляє кожному запиту, для користувача не відрізняється від зупиненого. "
            "`liveness_masking_readiness` називає порти, де /health каже 200, а /ready "
            "відмовляє: саме ця пара робить простій невидимим для будь-якого спостерігача, "
            "що питає лише про живучість."
        ),
    }


def declared_ports() -> list[int]:
    """Порти процесів, що належать ОГОЛОШЕНИМ юнітам."""
    units = required_units()
    return owned_ports(units, unit_states(units), serving_processes())


def selftest() -> int:
    """Отрути по ДАНИХ: вирок мусить залежати від відповідей, не від наявності переліку."""
    ok = {"port": 8030, "status": 200, "body": '{"status":"ready"}'}
    bad = {"port": 8000, "status": 503, "body": '{"detail":{"database":true,"ready":false}}'}
    cases = [
        ("усі відповідають — PASS", verdict(["u"], [8030], [ok])["status"], "PASS"),
        ("один відмовляє — FAIL", verdict(["u"], [8030, 8000], [ok, bad])["status"], "FAIL"),
        ("порожній перелік проб не є згодою", verdict(["u"], [], [])["status"], "FAIL"),
        ("юнітів не оголошено — FAIL", verdict([], [8030], [ok])["status"], "FAIL"),
        ("хибні перевірки названі", refusing_detail(str(bad["body"])), ["ready"]),
        (
            "недосяжність — не 200",
            verdict(["u"], [1], [{"port": 1, "status": None, "body": ""}])["status"],
            "FAIL",
        ),
        ("неJSON-тіло не валить розбір", refusing_detail("не json"), []),
        (
            "живучість, що маскує готовність, названа",
            verdict(["u"], [8000], [bad], [{"port": 8000, "status": 200, "body": "{}"}])[
                "liveness_masking_readiness"
            ],
            [8000],
        ),
        (
            "мертвий порт не є замаскованим",
            verdict(["u"], [8000], [bad], [{"port": 8000, "status": None, "body": ""}])[
                "liveness_masking_readiness"
            ],
            [],
        ),
    ]
    bad_cases = [name for name, got, want in cases if got != want]
    for name in bad_cases:
        print(f"  x {name}", file=sys.stderr)
    print(json.dumps({"selftest": len(cases), "failed": bad_cases}, ensure_ascii=False))
    return 1 if bad_cases else 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", type=Path, default=ROOT / "var/serving-readiness.json")
    parser.add_argument("--selftest", action="store_true")
    args = parser.parse_args()
    if args.selftest:
        return selftest()
    units, ports = required_units(), declared_ports()
    payload = verdict(
        units,
        ports,
        [probe(port) for port in ports],
        [probe(port, "/health") for port in ports],
    )
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    return 0 if payload["status"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
