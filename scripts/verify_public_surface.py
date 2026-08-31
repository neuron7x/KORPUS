#!/usr/bin/env python3
"""Чи двері — ті, які ми сказали, що збудували.

Про публічне розгортання вже є два виміри, і жоден не міряє цього. `public_health_
controller` питає «чи воно живе» — і відповідає ТАК, поки edge віддає особу; корпус
міг би бути порожній. `korpus-answer-quality` питає «чи воно добре відповідає» — і
судить зміст відповіді. Між ними діра: **форма самої поверхні**. Де слухає. Що
віддає. Яку особу підставляє. Що пропускає вглиб.

Діру знайдено не читанням. `deploy/public/nginx.conf` каже про себе три речі; дві з
них виміряно хибними 31.08.2026 на живому розгортанні:

    «The operator consoles are not served»   → console.html 404, але console.js,
                                                console_rules.js, console.css — 200.
                                                Правило `location = /console.html`
                                                стереже ОДНЕ ім'я файла, а твердження
                                                говорить про ПОВЕРХНЮ. Сторінку, яку
                                                воно ховає, відвідувач складає з тих
                                                самих скриптів за хвилину.
    «nginx listens on loopback only»          → контейнер у `network_mode: host` із
                                                `listen 8081;` без адреси. Виміряно 200
                                                з 192.168.0.101, 100.75.207.68,
                                                172.17.0.1, 172.18.0.1 — тобто з LAN,
                                                з tailnet і з КОЖНОГО контейнера на
                                                docker-мостах. Тунель перестав бути
                                                єдиними дверима, і саме на цій умові
                                                стоїть увесь аргумент про real_ip.
    «The API refuses on the role»             → тримається (`user` = answer:read +
                                                document:list, ingest немає), але
                                                відмова настає ПІСЛЯ розбору тіла:
                                                POST /v1/documents/ingest віддає 422,
                                                а не 403, і вивантаження встигає
                                                лягти на диск.

Спільна форма всіх трьох: **твердження ширше за правило, яке його стереже**. Це той
самий клас, що вже коштував цьому репозиторію чотирьох знахідок, і єдиний спосіб не
платити за нього вп'яте — зробити твердження вимірюваним.

Гейт розділено навпіл навмисно. `observe()` ходить у мережу й нічого не судить;
`assess()` судить і нікуди не ходить. Тому негативні контролі справжні: суддя
годується вигаданим спостереженням і мусить почервоніти, а не «пройти, бо сервера
немає». Мережева відмова дає UNKNOWN і НЕ дає PASS.

    verify_public_surface.py --base http://127.0.0.1:8081
    verify_public_surface.py --selftest
"""

from __future__ import annotations

import argparse
import base64
import ipaddress
import json
import re
import subprocess
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent
TEMPLATE = ROOT / "deploy/public/nginx.conf"
RENDERED = ROOT / "var/public/edge/nginx.conf"
DEFAULT_OUT = ROOT / "var/public-surface.json"

SCHEMA = "korpus.public-surface.v1"

#: Уся операторська поверхня, а не її головна сторінка. Перелік узято з того, що
#: `deploy_public_web.py` копіює в edge: якщо файл потрапляє в html-теку, він або
#: навмисно публічний, або мусить бути закритий — третього стану немає.
CONSOLE_ASSETS = (
    "/console.html",
    "/console.css",
    "/console.js",
    "/console_rules.js",
    "/console_accounts.js",
    "/console_mutations.js",
    "/console_readonly.js",
)

#: Записові маршрути: читацька сторінка не кличе жодного з них, а публічна особа не
#: може мати їх ніколи. Вони мусять упиратися в МЕЖУ, бо відмова застосунку тут
#: запізнюється — FastAPI читає тіло до виконання залежностей, тож завантаження вже
#: лежить на диску, коли `policy.require` каже «ні».
EDGE_DENIED_ROUTES = (
    ("POST", "/api/v1/documents/ingest"),
    ("POST", "/api/v1/ingestion-jobs/documents"),
    ("POST", "/api/v1/documents/1/versions/ingest"),
    ("POST", "/api/v1/document-versions/1/review"),
    ("POST", "/api/v1/document-versions/1/rescission"),
    ("GET", "/api/v1/admin/accounts"),
)

#: Межа мусить сказати «нема», не «не можна»: 404 не підтверджує існування маршруту.
REFUSED_AT_EDGE = frozenset({404})

#: Маршрути, які читач ЛЕГІТИМНО кличе (панель трасування) і які мусить відхилити
#: РОЛЬ, а не межа. Запити навмисно коректні: 422 від невдало складеної проби сказав
#: би про пробу, а не про систему — на цьому вимір уже раз збився.
ROLE_REFUSED_ROUTES = (
    "/v1/audit/events?trace_id=00000000-0000-0000-0000-000000000000&limit=10",
    "/v1/audit/verify",
    "/v1/admin/accounts",
)

#: Стеля життя підставленої особи. Політика API — 1440 хв; токен, випущений надовше,
#: означав би, що перевипуск зламано, а не що він щедрий.
MAX_IDENTITY_LIFETIME_SECONDS = 1440 * 60

#: Пости, з яких мусить бути ГЛУХО. Пусто — бо жодна локальна адреса, крім петлі,
#: не є дверима: тунель приходить на 127.0.0.1.
LOOPBACK = frozenset({"127.0.0.1", "::1"})


# ---------------------------------------------------------------- судження (без I/O)


def _finding(check: str, verdict: str, detail: str) -> dict[str, str]:
    return {"check": check, "verdict": verdict, "detail": detail}


def assess(observation: dict[str, Any]) -> list[dict[str, str]]:
    """Вирок над спостереженням. Жодного мережевого виклику — тому й перевірюваний.

    UNKNOWN — окремий вирок, і він НЕ PASS: спостереження, якого не сталося, не
    доводить нічого, а зарахований у зелене мовчазно стирає саму перевірку.
    """
    findings: list[dict[str, str]] = []

    # 1. Операторська поверхня. Твердження шаблону — про консолі, тож і правило має
    #    бути про консолі. Один 404 на index не закриває сім файлів.
    assets = observation.get("console_assets")
    if not isinstance(assets, dict) or not assets:
        findings.append(_finding("console_surface", "UNKNOWN", "консолі не спостережено"))
    else:
        leaked: list[str] = []
        masquerade: list[str] = []
        for path, seen in sorted(assets.items()):
            record = seen if isinstance(seen, dict) else {"status": seen, "content_type": ""}
            if int(record.get("status", 0)) != 200:
                continue
            # HTML на шляху скрипта — це фолбек, а не файл консолі: витоку немає,
            # але код 200 бреше про існування, і саме він ховав витік поруч.
            (masquerade if "text/html" in record.get("content_type", "") else leaked).append(path)
        if leaked or masquerade:
            parts = []
            if leaked:
                parts.append("віддано вміст консолі: " + ", ".join(leaked))
            if masquerade:
                parts.append("200 з index.html під іменем скрипта: " + ", ".join(masquerade))
            findings.append(
                _finding(
                    "console_surface",
                    "FAIL",
                    "шаблон каже «operator consoles are not served»; " + "; ".join(parts),
                )
            )
        else:
            findings.append(
                _finding("console_surface", "PASS", f"закрито {len(assets)} шляхів консолі")
            )

    # 2. Де слухає. Аргумент шаблону про real_ip спирається на «loopback only»; поки
    #    це не так, аргумент недійсний незалежно від того, чи хтось цим скористався.
    listen = observation.get("listen")
    if not isinstance(listen, dict) or not listen.get("addresses"):
        findings.append(
            _finding("edge_binding", "UNKNOWN", "адрес прослуховування не спостережено")
        )
    else:
        reachable = sorted(
            entry["address"]
            for entry in listen["addresses"]
            if entry.get("status") == 200 and entry.get("address") not in LOOPBACK
        )
        if reachable:
            findings.append(
                _finding(
                    "edge_binding",
                    "FAIL",
                    "шаблон каже «nginx listens on loopback only», а відповідає з: "
                    + ", ".join(reachable),
                )
            )
        else:
            findings.append(
                _finding("edge_binding", "PASS", "поза петлею не відповідає жодна адреса")
            )

    # 3. Посада єгресу. Сьогодні інертна, бо композитор вимкнений, — і саме тому її
    #    ніхто не бачить. Вмикання композитора не повинно ВІДКРИВАТИ вихід назовні:
    #    хто вмикає інференс, той не думає в ту мить про права на матеріал.
    status = observation.get("inference_status")
    if not isinstance(status, dict) or "egress_posture" not in status:
        findings.append(_finding("egress_posture", "UNKNOWN", "стан інференсу не спостережено"))
    elif status["egress_posture"] == "external_allowed":
        findings.append(
            _finding(
                "egress_posture",
                "FAIL",
                "публічна поверхня оголошує egress_posture=external_allowed; "
                f"інертно лише поки enabled={status.get('enabled')!r}",
            )
        )
    else:
        findings.append(
            _finding("egress_posture", "PASS", f"egress_posture={status['egress_posture']}")
        )

    # 4. Підставлена особа. Її ніхто не бачить у браузері, тому єдине місце, де її
    #    надмірність могла б проявитись, — цей вимір.
    identity = observation.get("identity")
    if not isinstance(identity, dict) or "roles" not in identity:
        findings.append(_finding("injected_identity", "UNKNOWN", "особу не спостережено"))
    else:
        excess = sorted(set(identity.get("roles") or []) - {"user"})
        lifetime = int(identity.get("lifetime_seconds") or 0)
        problems = []
        if identity.get("subject") != "public":
            problems.append(f"subject={identity.get('subject')!r}")
        if excess:
            problems.append("зайві ролі: " + ", ".join(excess))
        if identity.get("clearance") != "public":
            problems.append(f"clearance={identity.get('clearance')!r}")
        if lifetime > MAX_IDENTITY_LIFETIME_SECONDS:
            problems.append(f"життя {lifetime} с понад стелю {MAX_IDENTITY_LIFETIME_SECONDS}")
        if problems:
            findings.append(_finding("injected_identity", "FAIL", "; ".join(problems)))
        else:
            findings.append(
                _finding("injected_identity", "PASS", f"public/user/public, життя {lifetime} с")
            )

    # 5. Записові маршрути. Застосунок відмовляє на ролі — це другий рубіж і він
    #    живий. Але для завантаження він запізнюється: FastAPI читає тіло ДО
    #    виконання залежностей, тож 31.08.2026 коректний анонімний multipart на
    #    `/v1/documents/ingest` діставав 422 від валідації `DocumentCreate` — файл
    #    уже був прочитаний. Спинити це можна лише на межі.
    routes = observation.get("edge_denied_routes")
    if not isinstance(routes, dict) or not routes:
        findings.append(_finding("edge_denied_routes", "UNKNOWN", "маршрутів не спостережено"))
    else:
        passed = sorted(
            f"{route}={code}" for route, code in routes.items() if code not in REFUSED_AT_EDGE
        )
        if passed:
            findings.append(
                _finding(
                    "edge_denied_routes",
                    "FAIL",
                    "межа пропускає записовий маршрут углиб: " + ", ".join(passed),
                )
            )
        else:
            findings.append(
                _finding(
                    "edge_denied_routes", "PASS", f"{len(routes)} записових маршрутів спинено межею"
                )
            )

    # 6. Другий рубіж мусить лишитись живим. Якщо межа закрила все, а застосунок
    #    перестав відмовляти на ролі, гейт вище позеленів би на порожньому місці —
    #    тому роль перевіряється ОКРЕМО, повз межу, прямо на застосунку.
    #    401 сюди НЕ рахується: невпізнаний відвідувач нічого не доводить про роль,
    #    а зарахований як відмова він тихо стер би саму перевірку — треба ПРЕД'ЯВИТИ
    #    публічну особу й дістати 403 від неї.
    direct = observation.get("role_refusal_direct")
    if not isinstance(direct, dict) or not direct:
        findings.append(_finding("role_refusal", "UNKNOWN", "прямої перевірки ролі не було"))
    else:
        allowed = sorted(
            f"{route}={code}" for route, code in direct.items() if code not in (401, 403)
        )
        unproven = sorted(route for route, code in direct.items() if code == 401)
        if allowed:
            findings.append(
                _finding(
                    "role_refusal", "FAIL", "застосунок не відмовив на ролі: " + ", ".join(allowed)
                )
            )
        elif unproven:
            findings.append(
                _finding(
                    "role_refusal",
                    "UNKNOWN",
                    "401 без пред'явленої особи не доводить відмову на ролі: "
                    + ", ".join(unproven),
                )
            )
        else:
            findings.append(
                _finding("role_refusal", "PASS", f"{len(direct)} маршрутів відмовлено на ролі")
            )

    return findings


def verdict(findings: list[dict[str, str]]) -> str:
    """FAIL перебиває UNKNOWN, UNKNOWN перебиває PASS. Порожній перелік — не PASS."""
    if not findings:
        return "UNKNOWN"
    verdicts = {f["verdict"] for f in findings}
    if "FAIL" in verdicts:
        return "FAIL"
    if "UNKNOWN" in verdicts:
        return "UNKNOWN"
    return "PASS"


# ------------------------------------------------------------------ спостереження (I/O)


def _probe(url: str, method: str = "GET", token: str = "", timeout: float = 8.0) -> int:
    headers = {"Authorization": f"Bearer {token}"} if token else {}
    request = urllib.request.Request(url, method=method, headers=headers)
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            return int(response.status)
    except urllib.error.HTTPError as error:
        return int(error.code)
    except (OSError, urllib.error.URLError):
        return 0


def _probe_detail(url: str, timeout: float = 8.0) -> dict[str, Any]:
    """Код МАЛО. `try_files` віддає index.html із кодом 200 на будь-яке ім'я, тож
    перевірка, що дивиться лише на код, не відрізняє віддану консоль від сторінки
    під її іменем — а це дві різні поломки з двома різними лікуваннями."""
    request = urllib.request.Request(url)
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            body = response.read(4096)
            return {
                "status": int(response.status),
                "content_type": response.headers.get("Content-Type", ""),
                "bytes": len(body),
            }
    except urllib.error.HTTPError as error:
        return {"status": int(error.code), "content_type": "", "bytes": 0}
    except (OSError, urllib.error.URLError):
        return {"status": 0, "content_type": "", "bytes": 0}


def _fetch_json(url: str, timeout: float = 8.0) -> dict[str, Any] | None:
    try:
        with urllib.request.urlopen(url, timeout=timeout) as response:
            payload = json.loads(response.read())
    except (OSError, urllib.error.URLError, json.JSONDecodeError):
        return None
    return payload if isinstance(payload, dict) else None


def local_addresses() -> list[str]:
    """Кожна адреса цієї машини, а не та, яку ми сподіваємось побачити.

    Перелік беремо в системи: список, вписаний у гейт, застаріє мовчки — рівно тоді,
    коли з'явиться новий інтерфейс, тобто рівно тоді, коли перевірка потрібна.
    """
    try:
        output = subprocess.run(
            ["hostname", "-I"], check=False, capture_output=True, text=True, timeout=5
        ).stdout
    except (OSError, subprocess.SubprocessError):
        output = ""
    addresses = ["127.0.0.1"]
    for token in output.split():
        try:
            parsed = ipaddress.ip_address(token)
        except ValueError:
            continue
        if parsed.version == 4:
            addresses.append(token)
    return addresses


def token_claims(config_text: str) -> dict[str, Any] | None:
    """Розбір підставленої особи з рендереного конфігу. Токен НЕ повертається."""
    matched = re.search(r'Authorization\s+"Bearer\s+([A-Za-z0-9._\-]+)"', config_text)
    if matched is None:
        return None
    segments = matched.group(1).split(".")
    if len(segments) != 3:
        return None
    payload = segments[1] + "=" * (-len(segments[1]) % 4)
    try:
        claims = json.loads(base64.urlsafe_b64decode(payload))
    except (ValueError, json.JSONDecodeError):
        return None
    if not isinstance(claims, dict):
        return None
    issued, expires = int(claims.get("iat", 0)), int(claims.get("exp", 0))
    return {
        "subject": claims.get("sub"),
        "roles": claims.get("roles"),
        "clearance": claims.get("clearance"),
        "lifetime_seconds": max(expires - issued, 0),
        "remaining_seconds": max(expires - int(time.time()), 0),
    }


def observe(
    base: str,
    port: int,
    direct_base: str,
    direct_token: str,
    timeout: float,
    rendered: Path = RENDERED,
) -> dict[str, Any]:
    base = base.rstrip("/")
    observation: dict[str, Any] = {"schema": SCHEMA, "base": base}

    observation["console_assets"] = {
        path: _probe_detail(base + path, timeout=timeout) for path in CONSOLE_ASSETS
    }

    addresses = []
    for address in local_addresses():
        addresses.append(
            {"address": address, "status": _probe(f"http://{address}:{port}/", timeout=timeout)}
        )
    observation["listen"] = {"port": port, "addresses": addresses}

    observation["inference_status"] = _fetch_json(
        f"{base}/api/v1/inference/status", timeout=timeout
    )

    config_text = ""
    try:
        config_text = rendered.read_text(encoding="utf-8")
    except OSError:
        config_text = ""
    observation["identity"] = token_claims(config_text)

    observation["edge_denied_routes"] = {
        route: _probe(base + route, method=method, timeout=timeout)
        for method, route in EDGE_DENIED_ROUTES
    }

    # Другий рубіж міряється повз межу — інакше зелена межа ховала б мертву роль.
    direct = direct_base.rstrip("/")
    observation["role_refusal_direct"] = (
        {
            route: _probe(f"{direct}{route}", token=direct_token, timeout=timeout)
            for route in ROLE_REFUSED_ROUTES
        }
        if direct
        else {}
    )
    return observation


# ------------------------------------------------------------------- негативні контролі


def selftest() -> int:
    """Суддя мусить червоніти на кожному дефекті ОКРЕМО і зеленіти лише на чистому."""
    closed: dict[str, Any] = {"status": 404, "content_type": "text/html", "bytes": 146}
    clean: dict[str, Any] = {
        "console_assets": {path: dict(closed) for path in CONSOLE_ASSETS},
        "listen": {
            "port": 8081,
            "addresses": [
                {"address": "127.0.0.1", "status": 200},
                {"address": "192.168.0.101", "status": 0},
            ],
        },
        "inference_status": {"egress_posture": "local_only", "enabled": False},
        "identity": {
            "subject": "public",
            "roles": ["user"],
            "clearance": "public",
            "lifetime_seconds": 86400,
        },
        "edge_denied_routes": {route: 404 for _, route in EDGE_DENIED_ROUTES},
        "role_refusal_direct": {route: 403 for route in ROLE_REFUSED_ROUTES},
    }

    def mutate(**changes: Any) -> dict[str, Any]:
        copy: dict[str, Any] = json.loads(json.dumps(clean))
        copy.update(changes)
        return copy

    leaked = {path: dict(closed) for path in CONSOLE_ASSETS}
    leaked["/console_readonly.js"] = {
        "status": 200,
        "content_type": "application/javascript",
        "bytes": 8383,
    }
    masked = {path: dict(closed) for path in CONSOLE_ASSETS}
    masked["/console.js"] = {"status": 200, "content_type": "text/html", "bytes": 15820}
    lan = {
        "port": 8081,
        "addresses": [
            {"address": "127.0.0.1", "status": 200},
            {"address": "192.168.0.101", "status": 200},
        ],
    }
    late = {route: 404 for _, route in EDGE_DENIED_ROUTES}
    late["/api/v1/documents/ingest"] = 422

    cases: list[tuple[str, dict[str, Any], str]] = [
        ("чиста поверхня зелена", clean, "PASS"),
        ("відданий файл консолі валить", mutate(console_assets=leaked), "FAIL"),
        ("index.html під іменем скрипта валить", mutate(console_assets=masked), "FAIL"),
        ("відповідь із LAN валить", mutate(listen=lan), "FAIL"),
        (
            "external_allowed валить",
            mutate(inference_status={"egress_posture": "external_allowed", "enabled": False}),
            "FAIL",
        ),
        (
            "зайва роль валить",
            mutate(
                identity={
                    "subject": "public",
                    "roles": ["user", "curator"],
                    "clearance": "public",
                    "lifetime_seconds": 86400,
                }
            ),
            "FAIL",
        ),
        (
            "життя понад стелю валить",
            mutate(
                identity={
                    "subject": "public",
                    "roles": ["user"],
                    "clearance": "public",
                    "lifetime_seconds": 86400 * 30,
                }
            ),
            "FAIL",
        ),
        ("422 замість відмови на межі валить", mutate(edge_denied_routes=late), "FAIL"),
        (
            "403, відданий межею замість ролі, теж валить",
            mutate(edge_denied_routes={route: 403 for _, route in EDGE_DENIED_ROUTES}),
            "FAIL",
        ),
        (
            "мертва роль на застосунку валить",
            mutate(role_refusal_direct={route: 200 for route in ROLE_REFUSED_ROUTES}),
            "FAIL",
        ),
        (
            "401 без пред'явленої особи — UNKNOWN, не PASS",
            mutate(role_refusal_direct={route: 401 for route in ROLE_REFUSED_ROUTES}),
            "UNKNOWN",
        ),
        ("відсутнє спостереження — UNKNOWN, не PASS", {}, "UNKNOWN"),
        ("порожні консолі — UNKNOWN, не PASS", mutate(console_assets={}), "UNKNOWN"),
    ]

    bad = 0
    for name, observation, expected in cases:
        got = verdict(assess(observation))
        ok = got == expected
        bad += not ok
        print(f"  [{'ok' if ok else 'ЗБІЙ'}] {name}: {got}")
    print(f"\nнегативний контроль: {len(cases) - bad}/{len(cases)}")
    return 1 if bad else 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base", default="http://127.0.0.1:8081")
    parser.add_argument("--port", type=int, default=8081)
    parser.add_argument(
        "--direct-base",
        default="",
        help="застосунок повз межу, щоб довести, що роль ще відмовляє (порожньо = не міряти)",
    )
    parser.add_argument(
        "--direct-token",
        default="",
        help="публічна особа для прямої проби; без неї 401 дасть UNKNOWN, а не PASS",
    )
    parser.add_argument(
        "--rendered",
        type=Path,
        default=RENDERED,
        help="рендерений nginx.conf ЖИВОГО розгортання, звідки читається підставлена особа",
    )
    parser.add_argument("--timeout", type=float, default=8.0)
    parser.add_argument("--out", type=Path, default=DEFAULT_OUT)
    parser.add_argument("--selftest", action="store_true")
    arguments = parser.parse_args()

    if arguments.selftest:
        return selftest()

    observation = observe(
        arguments.base,
        arguments.port,
        arguments.direct_base,
        arguments.direct_token,
        arguments.timeout,
        arguments.rendered,
    )
    findings = assess(observation)
    overall = verdict(findings)
    report = {
        "schema": SCHEMA,
        "generated_at": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
        "base": arguments.base,
        "verdict": overall,
        "findings": findings,
        "observation": observation,
    }
    arguments.out.parent.mkdir(parents=True, exist_ok=True)
    arguments.out.write_text(
        json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    for finding in findings:
        print(f"  [{finding['verdict']}] {finding['check']}: {finding['detail']}")
    print(f"\npublic-surface: {overall}  → {arguments.out}")
    return 0 if overall == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
