#!/usr/bin/env python3
"""Одне місце, де вимірювач кладе собі контекст RLS — через БРОКЕРА, як рантайм.

Схема 0020 забрала у застосункового логіна право писати claim'и: політики читають
довірену таблицю `korpus_rls_context`, а не `current_setting`, і покласти туди рядок
може лише `korpus_bind_rls_context` під роллю `korpus_authz`. Інструменти, що лишились
на `set_config('korpus.*')`, з того дня бачать НУЛЬ рядків — і кажуть це не як «я не
маю допуску», а як твердження про предмет:

    verify_postgres_restore.py  звинувачував БЕКАП у порожньому корпусі (виправлено
                                04.09.2026, доведено запуском на відновленій базі);
    measure_recovery.py         рахував `document_rows: 0` і `writes_after_backup: 0`,
                                отже `lost_documents: 0` — число, яке не могло вийти
                                іншим, тобто не вимір. Так само мовчки в CI.

Дві копії однієї прив'язки розійшлися б так само мовчки, як розійшлися ці дві з
протоколом. Тому вона тут одна.

    rls_context.py --selftest
"""

from __future__ import annotations

import argparse
import json
from typing import Any

from sqlalchemy import create_engine, text

#: Допуск ВИМІРЮВАЧА, не застосунку: він рахує рядки, які має рахувати, і не пише.
MEASUREMENT_CLAIMS: dict[str, Any] = {
    "clearance": 3,
    "corpora": ["public", "restricted-demo"],
    "classifications": ["internal", "public", "restricted"],
    "compartments": [],
    "roles": ["admin", "user"],
}

BIND = (
    "SELECT public.korpus_bind_rls_context("
    ":backend_pid, :transaction_id, CAST(:session_login AS name), "
    "CAST(:subject AS text), :clearance, "
    "CAST(:corpora AS jsonb), CAST(:classifications AS jsonb), "
    "CAST(:compartments AS jsonb), CAST(:roles AS jsonb))"
)

TARGET = (
    "SELECT pg_catalog.pg_backend_pid() AS backend_pid, "
    "pg_catalog.txid_current() AS transaction_id, session_user::text AS session_login"
)


def broker_parameters(target: Any, subject: str) -> dict[str, Any]:
    """Параметри виклику брокера. Ключ — (backend_pid, txid, session_user) З'ЄДНАННЯ."""
    packed = {
        name: json.dumps(value, separators=(",", ":"))
        for name, value in MEASUREMENT_CLAIMS.items()
        if isinstance(value, list)
    }
    return {
        "backend_pid": int(target.backend_pid),
        "transaction_id": int(target.transaction_id),
        "session_login": str(target.session_login),
        "subject": subject,
        "clearance": int(MEASUREMENT_CLAIMS["clearance"]),
        **packed,
    }


def bind(connection: Any, authz_url: str, subject: str) -> None:
    """Покласти контекст для ЦІЄЇ транзакції. Порожній `authz_url` — відмова, не пропуск."""
    if not authz_url:
        raise SystemExit(
            "URL брокера (роль korpus_authz) обов'язковий: без нього вимірювач не має "
            "claim'ів, бачить нуль рядків і каже це як факт про предмет"
        )
    target = connection.execute(text(TARGET)).one()
    broker_engine = create_engine(authz_url, pool_pre_ping=True)
    try:
        with broker_engine.begin() as broker:
            broker.execute(text(BIND), broker_parameters(target, subject))
    finally:
        broker_engine.dispose()


class _Target:
    backend_pid = 42
    transaction_id = 7
    session_login = "korpus_app"


def selftest() -> int:
    parameters = broker_parameters(_Target(), "recovery-drill")
    cases = [
        (
            "списки їдуть як JSON, не як рядок з комами",
            parameters["corpora"],
            '["public","restricted-demo"]',
        ),
        ("порожній перелік відсіків лишається порожнім JSON", parameters["compartments"], "[]"),
        ("допуск — число, не текст", parameters["clearance"], 3),
        ("предмет виміру названо", parameters["subject"], "recovery-drill"),
        ("ключ прив'язки — з'єднання, не роль", parameters["backend_pid"], 42),
        ("протокол `set_config` більше не згадується", "set_config" in BIND, False),
    ]
    bad = 0
    for name, actual, expected in cases:
        ok = actual == expected
        bad += not ok
        print(f"  {'ok' if ok else 'FAIL'} {name}: {actual!r}")
    try:
        bind(None, "", "x")
    except SystemExit:
        print("  ok порожній брокер — ВІДМОВА, не тихий пропуск")
    else:  # pragma: no cover - доводиться відмовою вище
        bad += 1
        print("  FAIL порожній брокер не відмовив")
    total = len(cases) + 1
    print(f"негативний контроль: {total - bad}/{total}")
    return 1 if bad else 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--selftest", action="store_true")
    if not parser.parse_args().selftest:
        parser.print_usage()
        return 2
    return selftest()


if __name__ == "__main__":
    raise SystemExit(main())
