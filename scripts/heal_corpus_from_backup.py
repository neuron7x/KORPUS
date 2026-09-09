#!/usr/bin/env python3
"""Підняти корпус із найсвіжішого бекапа, коли зонд читаності сказав UNREADABLE.

Пʼять пошкоджень за три доби, і кожне піднімала рука: зупинити службу, знайти бекап,
розшифрувати, підмінити файл, підписати відкат журналу, підняти службу. Між пошкодженням
о 17:34 і відновленням о 19:27 служба віддавала 503 майже дві години — не тому, що щось
було складне, а тому, що людина мусила бути присутня.

ПРЕДМЕТ ЛІКУВАННЯ НЕ ОГОЛОШУЄТЬСЯ ТУТ. Цей виробник питає той самий зонд, який стереже
службу (`watch_corpus_readability`), і діє РІВНО на його вироку:

  READABLE  → відмова: лікувати нема чого, і відновлення на цілому корпусі — руйнування;
  UNKNOWN   → відмова: коли стан невідомий, підміна файла є дією без предмета;
  UNREADABLE→ дозвіл, і лише він.

ЩО ЗБЕРІГАЄТЬСЯ. Пошкоджений файл НЕ затирається ніколи: він відʼїжджає вбік під власним
іменем з часом події, разом зі своїми `-wal` і `-shm` — залишений `-wal` від старої бази
накотився б на щойно відновлену і зробив би з відновлення друге пошкодження. Попередній
підписаний запис відкату теж не затирається: він відʼїжджає поруч, бо ліки, що знищують
доказ, якого самі потребують, — це вже інша вада.

ЗАПИС ВІДКАТУ ПЕРЕВІРЯЄТЬСЯ, А НЕ ПЕРЕВИПУСКАЄТЬСЯ НАОСЛІП. Спершу нинішній `audit.restore`
звіряється з НОВОЮ базою і нинішнім якорем тією самою функцією, якою це робить сама
служба (`audit_restore.rollback_accounted`). Якщо він пояснює саме цей відкат — його
лишають. Якщо ні — `attest_restore.py` спочатку кличеться БЕЗ `--apply`, і підпис
ставиться лише за порожнього переліку відмов.

    heal_corpus_from_backup.py [--apply]
    heal_corpus_from_backup.py --selftest
"""

from __future__ import annotations

import argparse
import fcntl
import hmac
import json
import os
import shutil
import sqlite3
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.request
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, NamedTuple

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / "apps/api/src"), str(ROOT / "scripts")]

import watch_corpus_readability as watch  # noqa: E402
from backup_crypto import load_key  # noqa: E402
from backup_manifest import sign as sign_manifest  # noqa: E402
from korpus.infrastructure.audit_restore import read_record, rollback_accounted  # noqa: E402

SCHEMA = "korpus.corpus-heal.v1"
RUNTIME = ROOT / "var/runtime/corpus-v6-20260807"
DEFAULT_BACKUPS = Path.home() / "korpus-backups"
DEFAULT_KEY_ID = "korpus-local-2026-08"


class Poll(NamedTuple):
    """Бюджет очікування готовності. Затримка НАЗВАНА входом, а не константою модуля:
    без неї «сорок спроб» минають за частку секунди, тобто цикл виглядає як очікування
    і ним не є, — і саме тому бюджет мусить бути видимим і перевірюваним."""

    attempts: int
    delay: float


POLL = Poll(45, 2.0)


class Service(NamedTuple):
    """Як спинити, як підняти, де питати про 200 і скільки на це чекати."""

    stop: list[str]
    start: list[str]
    ready_url: str
    poll: Poll


class Plan(NamedTuple):
    """Усе, що потрібно одному лікуванню. Кортеж, бо стеля аргументів функції низька."""

    database: Path
    anchor: Path
    backups: Path
    backup_key_file: Path
    backup_key_id: str
    audit_key_file: Path
    apply: bool


class Refusal(RuntimeError):
    """Названа причина не лікувати. Відмова — теж твердження, і вона входить у журнал."""


# ── вибір бекапа ─────────────────────────────────────────────────────────────────────


def _manifest_of(backup: Path) -> dict[str, Any]:
    return dict(json.loads(Path(f"{backup}.json").read_text(encoding="utf-8")))


def _authentic(manifest: dict[str, Any], plan: Plan) -> bool:
    """Маніфест автентичний і саме того ключа.

    Перевіряється ДО вибору, а не лише перед розшифруванням: `created_at` із чужого
    маніфеста інакше керував би тим, який бекап візьмуть, — тобто підробка впливала б на
    рішення, навіть якщо потім її ловить `restore_sqlite.sh`.
    """
    if str(manifest.get("key_id", "")) != plan.backup_key_id:
        return False
    expected = sign_manifest(manifest, load_key(plan.backup_key_file))
    return hmac.compare_digest(str(manifest.get("manifest_hmac_sha256", "")), expected)


def _candidate(backup: Path, plan: Plan) -> tuple[str, Path] | None:
    try:
        manifest = _manifest_of(backup)
    except (OSError, ValueError):
        return None
    created = str(manifest.get("created_at", ""))
    if not created or not _authentic(manifest, plan):
        return None
    return (created, backup)


def freshest_backup(plan: Plan) -> Path:
    """Найсвіжіший — за `created_at` у маніфесті, а НЕ за mtime файла.

    mtime — властивість машини: копіювання, rsync і відновлення прав переставляють його,
    не торкаючись того, з якого моменту знято корпус.
    """
    found = [
        candidate
        for backup in sorted(plan.backups.glob("*.tar.enc"))
        if (candidate := _candidate(backup, plan)) is not None
    ]
    if not found:
        raise Refusal(f"у {plan.backups} немає жодного бекапа з автентичним маніфестом")
    return max(found)[1]


# ── збереження доказу ────────────────────────────────────────────────────────────────


def stamp_now() -> str:
    return datetime.now(UTC).strftime("%Y-%m-%dT%H%M%S")


def preserved_name(database: Path, stamp: str) -> Path:
    """Імʼя, під яким доказ відʼїжджає вбік. Зайняте імʼя НЕ затирається."""
    target = database.with_name(f"{database.name}.malformed-{stamp}")
    index = 1
    while target.exists():
        target = database.with_name(f"{database.name}.malformed-{stamp}-{index}")
        index += 1
    return target


def preserve(database: Path, stamp: str) -> Path:
    """Пошкоджений файл і його супутники відʼїжджають РАЗОМ.

    Залишений поруч `-wal` від старої бази SQLite накотив би на щойно відновлену — тобто
    ліки самі зробили б друге пошкодження. Такі сироти вже лежать у цьому каталозі від
    попередніх ручних відновлень.
    """
    target = preserved_name(database, stamp)
    database.rename(target)
    for suffix in ("-wal", "-shm"):
        companion = database.with_name(database.name + suffix)
        if companion.exists():
            companion.rename(target.with_name(target.name + suffix))
    return target


# ── відновлення ──────────────────────────────────────────────────────────────────────


def restore_into(plan: Plan, backup: Path, staging: Path) -> str:
    """`restore_sqlite.sh` перевіряє маніфест, розшифровує, доводить схему до head і
    відмовляється віддавати корпус без документів, схвалених версій і прольотів."""
    environment = dict(os.environ)
    environment["KORPUS_BACKUP_ENCRYPTION_KEY_FILE"] = str(plan.backup_key_file)
    done = subprocess.run(
        [str(ROOT / "scripts/restore_sqlite.sh"), str(backup), str(staging)],
        capture_output=True,
        text=True,
        env=environment,
        check=False,
        timeout=3600,
    )
    if done.returncode != 0:
        raise Refusal(f"відновлення не вдалося: {done.stderr.strip()[-400:]}")
    return done.stdout.strip().splitlines()[-1]


def _query(database: Path, statement: str, parameters: tuple[Any, ...] = ()) -> Any:
    connection = sqlite3.connect(f"file:{database}?mode=ro", uri=True, timeout=30)
    try:
        return connection.execute(statement, parameters).fetchone()
    finally:
        connection.close()


def head_of(database: Path) -> tuple[int, str]:
    sequence, head_hash = _query(
        database, "select sequence, head_hash from audit_heads where singleton_id=1"
    )
    return int(sequence), str(head_hash)


def hash_at(database: Path, sequence: int) -> str | None:
    row = _query(database, "select event_hash from audit_events where sequence=?", (sequence,))
    return None if row is None else str(row[0])


# ── запис відкату ────────────────────────────────────────────────────────────────────


def record_is_accounted(plan: Plan) -> bool:
    """Чи пояснює НИНІШНІЙ запис саме цей відкат — тією самою функцією, що й служба."""
    audit_key = plan.audit_key_file.read_bytes().strip()
    record = read_record(plan.anchor.with_suffix(".restore"), audit_key)
    if record is None:
        return False
    anchor = json.loads(plan.anchor.read_text(encoding="utf-8"))
    head_sequence, _ = head_of(plan.database)
    return rollback_accounted(
        record,
        anchor_sequence=int(anchor["sequence"]),
        anchor_hash=str(anchor["head_hash"]),
        head_sequence=head_sequence,
        hash_at_restore_point=hash_at(plan.database, record.restored_head_sequence),
    )


def _attest(plan: Plan, backup: Path) -> dict[str, Any]:
    command = [
        str(ROOT / "apps/api/.venv/bin/python"),
        str(ROOT / "scripts/attest_restore.py"),
        "--database",
        str(plan.database),
        "--anchor",
        str(plan.anchor),
        "--backup",
        str(backup),
        "--backup-key-file",
        str(plan.backup_key_file),
        "--audit-key-file",
        str(plan.audit_key_file),
    ]
    planned = subprocess.run(command, capture_output=True, text=True, check=False, timeout=600)
    verdict = json.loads(planned.stdout or "{}")
    if verdict.get("refusals"):
        return {"decision": "REFUSED", "refusals": verdict["refusals"]}
    # Попередній запис відʼїжджає вбік, а не гине: він пояснював попередній відкат, і
    # порада, що затирає доказ, якого сама потребує, вже коштувала одного розслідування.
    superseded = plan.anchor.with_suffix(".restore")
    if superseded.exists():
        shutil.copy2(
            superseded, superseded.with_name(f"{superseded.name}.superseded-{stamp_now()}")
        )
    applied = subprocess.run(
        [*command, "--apply"], capture_output=True, text=True, check=False, timeout=600
    )
    return {"decision": "REISSUED", "status": json.loads(applied.stdout or "{}").get("status")}


def attest_rollback(plan: Plan, backup: Path) -> dict[str, Any]:
    """Перевірити; підписувати лише те, що перевірку не пройшло, і лише через `attest_restore`."""
    anchor = json.loads(plan.anchor.read_text(encoding="utf-8"))
    head_sequence, _ = head_of(plan.database)
    if int(anchor["sequence"]) <= head_sequence:
        return {"decision": "NOT_NEEDED", "anchor": int(anchor["sequence"]), "head": head_sequence}
    if record_is_accounted(plan):
        return {"decision": "KEPT", "anchor": int(anchor["sequence"]), "head": head_sequence}
    return {**_attest(plan, backup), "anchor": int(anchor["sequence"]), "head": head_sequence}


# ── служба ───────────────────────────────────────────────────────────────────────────


def run_command(command: list[str]) -> dict[str, Any]:
    if not command:
        return {"command": [], "skipped": True}
    done = subprocess.run(command, capture_output=True, text=True, check=False, timeout=300)
    return {"command": command, "returncode": done.returncode, "stderr": done.stderr[-300:]}


def ready_code(url: str) -> int:
    try:
        with urllib.request.urlopen(url, timeout=10) as response:
            return int(response.status)
    except urllib.error.HTTPError as error:
        return int(error.code)
    except (urllib.error.URLError, OSError, ValueError):
        return 0


def await_ready(url: str, budget: Poll = POLL) -> dict[str, Any]:
    """Опитування із СПРАВЖНЬОЮ затримкою: без неї сорок спроб минають за мить."""
    if not url:
        return {"url": "", "skipped": True}
    for attempt in range(1, budget.attempts + 1):
        code = ready_code(url)
        if code == 200:
            return {"url": url, "code": 200, "attempts": attempt}
        time.sleep(budget.delay)
    return {"url": url, "code": ready_code(url), "attempts": budget.attempts}


# ── саме лікування ───────────────────────────────────────────────────────────────────


def refusal_for(seen: dict[str, Any]) -> str:
    """Чистий предикат над ВИРОКОМ зонда. Окремо від зчитування, щоб отруту можна було
    внести в дані вироку, а не підмінювати сам зонд заради випадку."""
    if seen["status"] == "READABLE":
        return "корпус читається: лікувати нема чого, а підміна цілого — руйнування"
    if seen["status"] != "UNREADABLE":
        return f"стан {seen['status']}: відновлення без предмета — не лікування"
    return ""


def admit(plan: Plan) -> dict[str, Any]:
    """Єдиний дозвіл — вирок зонда, який стереже службу. Нічого іншого тут не питають."""
    seen = watch.observe(plan.database)
    refusal = refusal_for(seen)
    if refusal:
        raise Refusal(refusal)
    return seen


def swap(plan: Plan, restored: Path) -> dict[str, Any]:
    stamp = stamp_now()
    preserved = preserve(plan.database, stamp)
    shutil.move(str(restored), str(plan.database))
    plan.database.chmod(0o640)
    return {"preserved": str(preserved), "installed": str(plan.database), "stamp": stamp}


def heal(plan: Plan, service: Service) -> dict[str, Any]:
    """Кроки в порядку, у якому вони не можуть зашкодити один одному."""
    report: dict[str, Any] = {"before": admit(plan)}
    backup = freshest_backup(plan)
    report["backup"] = backup.name
    if not plan.apply:
        return {**report, "status": "PLANNED"}
    with tempfile.TemporaryDirectory(dir=str(plan.database.parent)) as staging:
        restored = Path(restore_into(plan, backup, Path(staging)))
        report["restored_probe"] = watch.observe(restored)["status"]
        if report["restored_probe"] != "READABLE":
            raise Refusal("відновлена копія не читається тим самим зондом — підміна не робиться")
        report["stop"] = run_command(service.stop)
        report["swap"] = swap(plan, restored)
    report["rollback_record"] = attest_rollback(plan, backup)
    report["start"] = run_command(service.start)
    report["ready"] = await_ready(service.ready_url, service.poll)
    report["status"] = "HEALED" if report["ready"].get("code", 200) == 200 else "INCOMPLETE"
    return report


def journal(path: Path, report: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(report, ensure_ascii=False) + "\n")


def guarded(plan: Plan, service: Service) -> dict[str, Any]:
    """Два прогони не сміють лікувати одну базу одночасно: вони знесли б роботу один
    одному, і слід від цього вже бачили — хибний FAIL плюс тридцять пʼять помилок."""
    lock = plan.database.with_name(plan.database.name + ".heal.lock")
    lock.touch(exist_ok=True)
    with lock.open("a") as handle:
        try:
            fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError:
            return {"status": "REFUSED", "refusal": "лікування вже триває в іншому прогоні"}
        try:
            return heal(plan, service)
        except Refusal as refusal:
            return {"status": "REFUSED", "refusal": str(refusal)}
        except Exception as error:  # noqa: BLE001 — обрив лікування теж мусить лягти в журнал
            return {"status": "FAILED", "error": f"{type(error).__name__}: {error}"}


# ── самоперевірка ────────────────────────────────────────────────────────────────────


def _fake_backups(work: Path, key: bytes) -> Path:
    """Дві копії, у яких СВІЖІША за маніфестом — СТАРІША за mtime. Так вибір, зроблений
    за часом файла, дає інший результат, ніж вибір за часом зняття."""
    directory = work / "backups"
    directory.mkdir()
    for name, created in (("old", "20260901T000000.000000Z"), ("new", "20260909T000000.000000Z")):
        archive = directory / f"korpus-{name}.tar.enc"
        archive.write_bytes("не архів".encode())
        manifest = {
            "schema": "korpus-postgres-backup-v4",
            "created_at": created,
            "file": archive.name,
            "key_id": DEFAULT_KEY_ID,
        }
        manifest["manifest_hmac_sha256"] = sign_manifest(manifest, key)
        Path(f"{archive}.json").write_text(json.dumps(manifest), encoding="utf-8")
    os.utime(directory / "korpus-new.tar.enc.json", (0, 0))
    os.utime(directory / "korpus-new.tar.enc", (0, 0))
    return directory


def _signed(directory: Path, name: str, fields: dict[str, Any]) -> None:
    archive = directory / name
    archive.write_bytes("не архів".encode())
    manifest = {"created_at": "20261231T000000.000000Z", "file": name, **fields}
    Path(f"{archive}.json").write_text(json.dumps(manifest), encoding="utf-8")


def _plan_for(work: Path, database: Path) -> Plan:
    work.mkdir(parents=True, exist_ok=True)
    key_file = work / "backup.key"
    key_file.write_text("ab" * 32 + "\n", encoding="ascii")
    audit_key = work / "audit.key"
    audit_key.write_text("probe-audit-key", encoding="utf-8")
    backups = _fake_backups(work, load_key(key_file))
    return Plan(database, work / "audit.anchor", backups, key_file, DEFAULT_KEY_ID, audit_key, True)


def _selection_problems(work: Path) -> list[str]:
    """Вибір бекапа — теж вимір, і його можна отруїти трьома різними способами."""
    plan = _plan_for(work, work / "korpus.db")
    problems: list[str] = []
    if freshest_backup(plan).name != "korpus-new.tar.enc":
        problems.append("вибрано не найсвіжіший за маніфестом — обрано за часом файла")
    key = load_key(plan.backup_key_file)
    _signed(
        plan.backups,
        "korpus-forged.tar.enc",
        {"key_id": DEFAULT_KEY_ID, "manifest_hmac_sha256": "0" * 64},
    )
    if freshest_backup(plan).name == "korpus-forged.tar.enc":
        problems.append("маніфест із чужим підписом керував вибором бекапа")
    stranger = {"key_id": "stranger-key-2026"}
    stranger["manifest_hmac_sha256"] = sign_manifest(
        {"created_at": "20261231T000000.000000Z", "file": "korpus-stranger.tar.enc", **stranger},
        key,
    )
    _signed(plan.backups, "korpus-stranger.tar.enc", stranger)
    if freshest_backup(plan).name == "korpus-stranger.tar.enc":
        problems.append("бекап чужого ключа прийнято")
    return problems


REPORTS = (
    ("READABLE", "цілий корпус не відмовлено — ліки руйнівніші за хворобу"),
    ("UNKNOWN", "невідомий стан прийнято за дозвіл лікувати"),
    ("UNREADABLE", ""),
)


def _admission_problems(work: Path) -> list[str]:
    """Дозвіл дає РІВНО UNREADABLE. Отрута вноситься у вирок, а не в сам зонд."""
    problems = [
        complaint
        for status, complaint in REPORTS
        if bool(refusal_for({"status": status})) != bool(complaint)
    ]
    healthy = watch.fixture(work / "healthy.db")
    try:
        admit(_plan_for(work / "whole", healthy))
    except Refusal:
        return problems
    return [*problems, "цілий корпус пройшов через `admit` до підміни файла"]


def _preservation_problems(work: Path) -> list[str]:
    problems: list[str] = []
    room = work / "keep"
    room.mkdir()
    database = watch.fixture(room / "korpus.db")
    for suffix in ("-wal", "-shm"):
        database.with_name(database.name + suffix).write_bytes("старий супутник".encode())
    first = preserve(database, "2026-09-09T170000")
    if not first.is_file() or database.exists():
        problems.append("доказ не відʼїхав убік або база лишилась на місці")
    for suffix in ("-wal", "-shm"):
        if database.with_name(database.name + suffix).exists():
            problems.append(f"{suffix} лишився поруч і накотиться на відновлену базу")
    watch.fixture(room / "korpus.db")
    second = preserve(database, "2026-09-09T170000")
    if second == first:
        problems.append("друге лікування затерло доказ першого")
    if not first.is_file():
        problems.append("перший доказ зник під час другого лікування")
    return problems


def _lock_problems(work: Path) -> list[str]:
    room = work / "lock"
    room.mkdir()
    plan = _plan_for(room, watch.fixture(room / "korpus.db"))
    lock = plan.database.with_name(plan.database.name + ".heal.lock")
    lock.touch()
    with lock.open("a") as held:
        fcntl.flock(held, fcntl.LOCK_EX | fcntl.LOCK_NB)
        verdict = guarded(plan, Service([], [], "", POLL))
    if verdict.get("refusal") != "лікування вже триває в іншому прогоні":
        return [f"другий прогін не спинився на замку: {verdict}"]
    return []


def _wait_problems(work: Path) -> list[str]:
    del work
    budget = Poll(3, 0.2)
    started = time.monotonic()
    verdict = await_ready("http://127.0.0.1:1/ready", budget)
    elapsed = time.monotonic() - started
    if verdict["code"] == 200:
        return ["мертвий порт визнано готовим"]
    if elapsed < budget.attempts * budget.delay:
        return [f"очікування зайняло {elapsed:.3f} с — це цикл, а не очікування"]
    if POLL.delay <= 0 or POLL.attempts < 2:
        return [f"бойовий бюджет {POLL} не є очікуванням"]
    return []


def selftest() -> int:
    problems: list[str] = []
    blocks = (
        _selection_problems,
        _admission_problems,
        _preservation_problems,
        _lock_problems,
        _wait_problems,
    )
    with tempfile.TemporaryDirectory() as directory:
        for block in blocks:
            problems += _survived(block, Path(directory) / block.__name__)
    print(
        json.dumps(
            {
                "selftest": "korpus.corpus-heal",
                "cases": 12,
                "blocks": len(blocks),
                "failures": problems,
            },
            ensure_ascii=False,
        )
    )
    return 1 if problems else 0


def _survived(block: Any, work: Path) -> list[str]:
    work.mkdir(parents=True, exist_ok=True)
    try:
        return list(block(work))
    except Exception as error:  # noqa: BLE001 — обрив блоку не сміє знімати решту з прогону
        return [f"{block.__name__} обірвався: {type(error).__name__}: {error}"]


# ── запуск ───────────────────────────────────────────────────────────────────────────


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--database", type=Path, default=RUNTIME / "korpus.db")
    parser.add_argument("--anchor", type=Path, default=RUNTIME / "audit.anchor")
    parser.add_argument("--backups", type=Path, default=DEFAULT_BACKUPS)
    parser.add_argument(
        "--backup-key-file",
        type=Path,
        default=Path(os.environ.get("KORPUS_BACKUP_ENCRYPTION_KEY_FILE", "")),
    )
    parser.add_argument(
        "--backup-key-id", default=os.environ.get("KORPUS_BACKUP_KEY_ID", DEFAULT_KEY_ID)
    )
    parser.add_argument(
        "--audit-key-file",
        type=Path,
        default=Path(os.environ.get("KORPUS_AUDIT_HMAC_KEY_FILE", "")),
    )
    parser.add_argument("--stop-command", default="systemctl --user stop korpus-public-api.service")
    parser.add_argument(
        "--start-command", default="systemctl --user start korpus-public-api.service"
    )
    parser.add_argument("--ready-url", default="http://127.0.0.1:8000/ready")
    parser.add_argument("--poll-attempts", type=int, default=POLL.attempts)
    parser.add_argument("--poll-seconds", type=float, default=POLL.delay)
    parser.add_argument("--journal", type=Path, default=ROOT / "var/corpus-heal.jsonl")
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--selftest", action="store_true")
    return parser


def main() -> int:
    arguments = build_parser().parse_args()
    if arguments.selftest:
        return selftest()
    plan = Plan(
        arguments.database,
        arguments.anchor,
        arguments.backups,
        arguments.backup_key_file,
        arguments.backup_key_id,
        arguments.audit_key_file,
        arguments.apply,
    )
    service = Service(
        arguments.stop_command.split(),
        arguments.start_command.split(),
        arguments.ready_url,
        Poll(arguments.poll_attempts, arguments.poll_seconds),
    )
    report = {
        "schema": SCHEMA,
        "healed_at": datetime.now(UTC).isoformat(),
        "database": str(plan.database),
        **guarded(plan, service),
    }
    journal(arguments.journal, report)
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0 if report["status"] in {"HEALED", "REFUSED", "PLANNED"} else 1


if __name__ == "__main__":
    sys.exit(main())
