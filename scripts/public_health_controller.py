#!/usr/bin/env python3
"""Bounded, stateful self-healing for the public KORPUS deployment."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import subprocess
import time
import urllib.error
import urllib.request
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, cast

ROOT = Path(__file__).resolve().parents[1]
STATE_PATH = ROOT / "var/public/health-state.json"
RECEIPT_PATH = ROOT / "var/public/HEALTH_RECEIPT.json"
COMPONENTS = ("api", "edge", "public")
#: Кожна дія — ПОСЛІДОВНІСТЬ команд, бо не всяке відновлення вміщається в одну.
ACTION_COMMANDS: dict[str, tuple[list[str], ...]] = {
    "restart_api": (["systemctl", "--user", "restart", "korpus-public-api.service"],),
    "refresh_edge": (["env", "KORPUS_PUBLIC_EDGE_ONLY=true", "bash", "scripts/serve_public.sh"],),
    "restore_funnel": (["tailscale", "funnel", "--bg", "8081"],),
    "recycle_funnel": (
        ["tailscale", "funnel", "--bg", "off"],
        ["tailscale", "funnel", "--bg", "8081"],
    ),
}

#: Сходинки відновлення на компонент, у порядку зростання втручання.
#:
#: Причина існування: 31.08.2026 публічний URL упав, сторож двічі виконав
#: `restore_funnel`, обидва рази отримав `action_outcomes: {restore_funnel: true}` — і
#: URL лишався мертвим. Команда ідемпотентна: вона вмикає те, що ВЖЕ ввімкнене, тож
#: успішно не робить нічого. Повторення тієї самої дії — не ескалація, і сторож, який
#: уміє лише повторювати, звітує про відновлення, якого не сталося. Тунель піднявся
#: від `off` → `on`; звідси друга сходинка.
#:
#: `api` і `edge` мають по одній сходинці навмисно: вигадана ескалація гірша за її
#: відсутність — вона зробить щось руйнівніше, не знаючи, чи перше взагалі мало ефект.
ACTION_LADDERS: dict[str, tuple[str, ...]] = {
    "api": ("restart_api",),
    "edge": ("refresh_edge",),
    "public": ("restore_funnel", "recycle_funnel"),
}


def canonical_bytes(value: object) -> bytes:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()


def initial_state() -> dict[str, Any]:
    return {
        "schema": "korpus.public-health-state.v1",
        "failures": {name: 0 for name in COMPONENTS},
        "last_recovery": {},
        # Скільки відновлень уже витрачено на ПОТОЧНИЙ збій. Схема лишається v1
        # навмисно: поле додається, нічого не змінюючи, а бампінг версії викинув би
        # живий файл разом із витримками — тобто дозволив би зайве втручання одразу
        # після оновлення.
        "attempts": {name: 0 for name in COMPONENTS},
    }


def load_state(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError, OSError):
        return initial_state()
    if value.get("schema") != "korpus.public-health-state.v1":
        return initial_state()
    return cast(dict[str, Any], value)


def transition(
    state: dict[str, Any],
    health: dict[str, bool],
    now: int,
    *,
    threshold: int = 2,
    cooldown: int = 300,
) -> tuple[dict[str, Any], list[str]]:
    """Advance counters and select only recoveries justified by current dependencies.

    Крім залежностей і витримки тепер обирається ще й СХОДИНКА: скільки відновлень уже
    зроблено, відколи компонент востаннє був здоровий. Друга спроба того самого збою —
    інша дія, бо перша вже довела, що її замало.
    """
    updated = json.loads(json.dumps(state))
    failures = updated.setdefault("failures", {})
    recovered = updated.setdefault("last_recovery", {})
    attempts = updated.setdefault("attempts", {})
    actions: list[str] = []
    for component in COMPONENTS:
        failures[component] = 0 if health[component] else int(failures.get(component, 0)) + 1
        # Здоров'я скидає не лише лічильник відмов, а й сходинку: наступний збій — новий
        # збій, і починати його з найбільшого втручання не було б підставою.
        if health[component]:
            attempts[component] = 0
    # Dependency order prevents restarting API merely because its edge is unavailable.
    candidates = []
    if not health["api"]:
        candidates.append("api")
    if health["api"] and not health["edge"]:
        candidates.append("edge")
    if health["api"] and health["edge"] and not health["public"]:
        candidates.append("public")
    for component in candidates:
        last = int(recovered.get(component, 0))
        if failures[component] >= threshold and now - last >= cooldown:
            ladder = ACTION_LADDERS[component]
            rung = min(int(attempts.get(component, 0)), len(ladder) - 1)
            actions.append(ladder[rung])
            attempts[component] = rung + 1
            recovered[component] = now
    return updated, actions


def probe(url: str, marker: bytes) -> bool:
    try:
        with urllib.request.urlopen(url, timeout=5) as response:
            return response.status == 200 and marker in response.read(4096)
    except (OSError, urllib.error.URLError):
        return False


def execute(action: str) -> bool:
    """Виконати послідовність і судити за ОСТАННЬОЮ командою.

    Підготовчий крок має право не вдатися: `funnel off` на вимкненому тунелі нічого не
    ламає, і зарахувати через нього провал усього відновлення означало б звітувати про
    невдачу там, де вона сталася. Зворотна помилка — рахувати успіхом сам факт запуску —
    і є те, через що 31.08 сторож двічі відрапортував `restore_funnel: true` над мертвим
    URL. Тому тут судиться остання команда, а справжній вирок все одно виносить
    НАСТУПНА проба здоров'я, не цей рядок.
    """
    outcome = False
    for command in ACTION_COMMANDS[action]:
        outcome = (
            subprocess.run(
                command,
                cwd=ROOT,
                check=False,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            ).returncode
            == 0
        )
    return outcome


def atomic_json(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(".tmp")
    temporary.write_bytes(
        json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True).encode() + b"\n"
    )
    os.replace(temporary, path)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--public-url", default="https://korpus-1.taile5d24a.ts.net")
    parser.add_argument("--observe-only", action="store_true")
    args = parser.parse_args()
    now = int(time.time())
    health = {
        "api": probe("http://127.0.0.1:8000/health", b'"status":"ok"'),
        "edge": probe("http://127.0.0.1:8081/api/v1/client/bootstrap", b'"subject":"public"'),
        "public": probe(args.public_url.rstrip("/") + "/healthz", b'"status":"ok"'),
    }
    state, requested = transition(load_state(STATE_PATH), health, now)
    outcomes = {action: execute(action) for action in requested} if not args.observe_only else {}
    atomic_json(STATE_PATH, state)
    body: dict[str, Any] = {
        "schema": "korpus.public-health-receipt.v1",
        "generated_at": datetime.now(UTC).isoformat(),
        "health": health,
        "requested_actions": requested,
        "action_outcomes": outcomes,
        "observe_only": args.observe_only,
        "status": "PASS"
        if all(health.values())
        else ("RECOVERY_REQUESTED" if requested else "DEGRADED"),
    }
    body["receipt_sha256"] = hashlib.sha256(canonical_bytes(body)).hexdigest()
    atomic_json(RECEIPT_PATH, body)
    print(json.dumps(body, ensure_ascii=False, sort_keys=True))
    return 0 if all(health.values()) or requested else 1


if __name__ == "__main__":
    raise SystemExit(main())
