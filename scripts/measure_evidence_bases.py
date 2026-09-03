#!/usr/bin/env python3
"""Скільки баз доказів існує, і чи те, чим вони різняться, хтось оголосив.

Корпус був відремонтований 31.08.2026 — нарізка перебудована з оригіналів, дослівність
0.3904 → 1.0, прольотів 38 863 → 31 464. Ремонт застосували до бази, яка обслуговує
читача. Через добу вимір показав, що бази ДВІ: поруч живе PostgreSQL-копія з
увімкненою семантикою, і в ній лишились ті самі 38 863 прольоти з-перед ремонту.
Жодна вісь цього не бачила, бо кожна читає ОДНУ базу — ту, яку їй назвали. Вимір, який
питає «чи цей корпус цілий», не може відповісти на «а чи він один».
## Що саме зламано, коли баз дві
Виміряно 01.09.2026: обидві бази тримають ТІ САМІ 256 джерел — множини `source_hash`
збігаються цілком. І жодного спільного ідентифікатора: 0 із 256 `document_id`, 0 із 256
`version_id`. Тобто цитата, видана однією базою, називає версію, якої в другій НЕМАЄ,
і перевірити її там неможливо — при тому, що це буквально той самий документ.

Заморожений еталон пошуку пінить ідентифікатори версій. Він дійсний рівно для однієї
бази, і ніде не записано, для якої.
## Чому гейт саме такої форми
Різниця між базами не є вадою сама по собі: контрольна база на те й контрольна, щоб
відрізнятись конфігурацією. Вадою є РІЗНИЦЯ, ЯКОЇ НІХТО НЕ ОГОЛОСИВ — бо саме вона
робить порівняння недійсним мовчки: прогін 30.08.2026 порівнював лексику з гібридом на
базі, яка з того часу перестала бути тим самим корпусом, і висновок «гібрид гірший»
лишився записаний як число про сьогодні.

Тому тут ратчет на ЗНАННЯ, не на число. Реєстр оголошує кожну базу і кожне
співвідношення з базою обліку (`sources`, `spans`, `version_ids` — `same` чи
`different`). Гейт міряє й порівнює з оголошеним:
  · база, якої в реєстрі немає         → REJECT (те, що сталося насправді);
  · оголошено `same`, виміряно різне   → REJECT (розійшлись);
  · оголошено `different`, виміряно те саме → REJECT (оголошення застаріло).
Кількості рухаються вільно: вони ростуть від інжесту й ратчет на них був би податком на
роботу. Рухається СПІВВІДНОШЕННЯ — і його треба переоголосити рукою.
База, до якої не достукались, дає UNKNOWN (код 2), не PASS: відсутність виміру не є
вимірюванням згоди.

## Вада, яку знайшла отрута на ЦЕЙ гейт, і чому вона тут головна

Перша версія читала лише реєстр. Отрута «прибрати базу з реєстру» — рівно те, що сталося
насправді, — дала код 0: нема кого міряти, тож усе гаразд. Гейт проти незадекларованих
баз, який САМ спирається на декларацію, зелений саме в тому стані, заради якого існує.

Тому бази ВИЯВЛЯЮТЬСЯ незалежно від реєстру: з оточення живих процесів
(`/proc/<pid>/environ`, змінна `KORPUS_DATABASE_URL`). База має значення тоді, коли її
щось обслуговує, і саме так другу базу знайшли вперше. Виявлена й неназвана база — це
REJECT, а не рядок у примітках.

    measure_evidence_bases.py --out var/evidence-bases.json
    measure_evidence_bases.py --selftest
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import sqlite3
import subprocess
import sys
from datetime import UTC, datetime
from fnmatch import fnmatch
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from corpus_identity import report_inputs  # noqa: E402

REGISTRY = ROOT / "config/operations/evidence-bases.json"
DATA_ROOT = Path(os.environ.get("KORPUS_DATA_ROOT") or ROOT).resolve()

#: Співвідношення, які реєстр мусить оголосити для КОЖНОЇ бази, що не є базою обліку.
#: Список закритий навмисно: поле, дописане в реєстр, але не назване тут, не гейтується,
#: і оголошення виглядало б повнішим, ніж перевірка.
RELATIONS = ("sources", "spans", "version_ids")

#: Таблиці, чия відсутність не є відмовою виміру: мініатюра еталона живучості несе
#: меншу схему. Відсутність НАЗИВАЄТЬСЯ у звіті — підставити нуль означало б зробити
#: «вбудовувань немає» і «таблиці вбудовувань немає» одним числом.
OPTIONAL_TABLES = frozenset({"span_embeddings"})


def _sqlite_path(url: str) -> Path | None:
    """Три навскісні — шлях відносний, чотири — абсолютний; так це в SQLAlchemy.

    Розрізнення не косметичне: `sqlite:///var/x.db` і `sqlite:////var/x.db` вказують на
    різні файли, і зведення обох до абсолютного зробило б відносну форму невидимою для
    порівняння з реєстром — тобто база, оголошена й жива, виглядала б неоголошеною.
    """
    prefix = "sqlite:///"
    if not url.startswith(prefix):
        return None
    rest = url[len(prefix) :]
    return Path(rest).resolve() if rest else None


def fingerprint(url: str) -> str:
    """Ім'я бази без секрета: пароль у відбитку зробив би звіт місцем витоку."""
    path = _sqlite_path(url)
    if path is not None:
        return f"sqlite:{path}"
    if url.startswith("postgres"):
        tail = url.split("://", 1)[1] if "://" in url else url
        credentials, _, location = tail.rpartition("@")
        user = credentials.split(":", 1)[0] if credentials else ""
        return f"postgres:{user}@{location}"
    return url


def discover_serving_bases(proc: Path = Path("/proc")) -> dict[str, str]:
    """Бази, які обслуговує ЖИВИЙ процес, — знайдені без участі реєстру.

    Читається лише те, що дозволено власним користувачем; чужий процес просто не
    відкриється, і це не помилка виміру, а межа його зору — названа тут, а не схована.
    """
    found: dict[str, str] = {}
    for entry in sorted(proc.glob("[0-9]*")):
        try:
            raw = (entry / "environ").read_bytes()
        except OSError:
            continue
        for item in raw.split(b"\0"):
            name, _, value = item.decode("utf-8", "replace").partition("=")
            if name == "KORPUS_DATABASE_URL" and value:
                found.setdefault(fingerprint(value), entry.name)
    return found


class Unreachable(Exception):
    """База оголошена й недосяжна. Це UNKNOWN, а не незгода."""


def _data_path(value: object) -> Path:
    return DATA_ROOT / str(value)


def _digest(values: list[str]) -> str:
    """Комутативний за побудовою: сортування знімає порядок рядків із результату."""
    accumulator = hashlib.sha256()
    for value in sorted(values):
        accumulator.update(value.encode("utf-8"))
        accumulator.update(b"\x1f")
    return accumulator.hexdigest()


def _postgres_dsn(spec: dict[str, Any]) -> str:
    container = str(spec["container"])
    secret = _data_path(spec["password_file"])
    if not secret.is_file():
        raise Unreachable(f"немає файла пароля: {secret}")
    probe = subprocess.run(
        [
            "docker",
            "inspect",
            container,
            "--format",
            "{{range .NetworkSettings.Networks}}{{.IPAddress}}{{end}}",
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    address = probe.stdout.strip()
    if probe.returncode != 0 or not address:
        raise Unreachable(f"контейнер {container} не відповідає")
    password = secret.read_text(encoding="utf-8").strip()
    return f"host={address} port={spec.get('port', 5432)} dbname={spec['database']} user={spec['user']} password={password}"


def _shape(
    counts: dict[str, int | None],
    source_hashes: list[str],
    version_ids: list[str],
    span_hashes: list[str],
    audit_key_ids: dict[str, int],
    missing_tables: tuple[str, ...] = (),
) -> dict[str, Any]:
    """Форма бази — те, що можна порівняти, не читаючи рядків.

    Лічильники приходять відображенням, а не десятьма позиційними аргументами: два
    сусідні `int` на одному місці переставити мовчки легше, ніж помітити, і різниця
    вилізла б числом у звіті, а не помилкою.
    """
    return {
        **counts,
        "audit_key_ids": audit_key_ids,
        # Названо, а не підставлено нулем. Відсутня таблиця в мініатюрі — це менша
        # схема; відсутня в бойовій базі — вада, і нуль зробив би їх нерозрізненними.
        "missing_tables": list(missing_tables),
        "sources": _digest(source_hashes),
        "version_ids": _digest(version_ids),
        "spans_digest": _digest(span_hashes),
    }


def _measure_sqlite(spec: dict[str, Any]) -> dict[str, Any]:
    database = _data_path(spec["path"])
    if not database.is_file():
        raise Unreachable(f"немає файла бази: {database}")
    connection = sqlite3.connect(f"file:{database}?mode=ro", uri=True)
    try:
        scalar = lambda sql: connection.execute(sql).fetchone()[0]  # noqa: E731
        column = lambda sql: [str(row[0]) for row in connection.execute(sql)]  # noqa: E731
        present = {
            str(row[0])
            for row in connection.execute("select name from sqlite_master where type = 'table'")
        }
        keys: dict[str, int] = {}
        for key_id, count in connection.execute(
            "select coalesce(audit_key_id, '<null>'), count(*) from audit_events group by 1"
        ):
            keys[str(key_id)] = int(count)
        return _shape(
            {
                "documents": int(scalar("select count(*) from documents")),
                "versions": int(scalar("select count(*) from document_versions")),
                "spans": int(scalar("select count(*) from evidence_spans")),
                "embeddings": int(scalar("select count(*) from span_embeddings"))
                if "span_embeddings" in present
                else None,
                "audit_events": int(scalar("select count(*) from audit_events")),
            },
            column("select source_hash from document_versions where is_current = 1"),
            column("select id from document_versions where is_current = 1"),
            column("select text_hash from evidence_spans"),
            keys,
            tuple(sorted(OPTIONAL_TABLES - present)),
        )
    finally:
        connection.close()


def _measure_postgres(spec: dict[str, Any]) -> dict[str, Any]:
    try:
        import psycopg
    except ImportError as error:  # pragma: no cover - залежність є в оточенні API
        raise Unreachable(f"psycopg недоступний: {error}") from error
    dsn = _postgres_dsn(spec)
    try:
        connection = psycopg.connect(dsn, connect_timeout=int(spec.get("timeout_seconds", 10)))
    except Exception as error:  # будь-яка відмова з'єднання є UNKNOWN, не незгода
        raise Unreachable(f"не під'єднались: {type(error).__name__}") from error
    try:
        cursor = connection.cursor()

        def scalar(sql: str) -> int:
            cursor.execute(sql)
            row = cursor.fetchone()
            return int(row[0]) if row else 0

        def column(sql: str) -> list[str]:
            cursor.execute(sql)
            return [str(row[0]) for row in cursor.fetchall()]

        cursor.execute(
            "select coalesce(audit_key_id, '<null>'), count(*) from audit_events group by 1"
        )
        keys = {str(row[0]): int(row[1]) for row in cursor.fetchall()}
        return _shape(
            {
                "documents": scalar("select count(*) from documents"),
                "versions": scalar("select count(*) from document_versions"),
                "spans": scalar("select count(*) from evidence_spans"),
                "embeddings": scalar("select count(*) from span_embeddings"),
                "audit_events": scalar("select count(*) from audit_events"),
            },
            column("select source_hash from document_versions where is_current"),
            column("select id::text from document_versions where is_current"),
            column("select text_hash from evidence_spans"),
            keys,
        )
    finally:
        connection.close()


def declared_fingerprint(spec: dict[str, Any]) -> str:
    """Відбиток оголошеної бази в тому ж просторі, що й відбиток живого процесу."""
    kind = str(spec.get("kind", ""))
    if kind == "sqlite":
        return f"sqlite:{_data_path(spec['path']).resolve()}"
    if kind == "postgres":
        dsn = _postgres_dsn(spec)
        parts = dict(item.split("=", 1) for item in dsn.split(" ") if "=" in item)
        return f"postgres:{parts['user']}@{parts['host']}:{parts['port']}/{parts['dbname']}"
    raise Unreachable(f"невідомий вид бази: {kind!r}")


def measure_base(spec: dict[str, Any]) -> dict[str, Any]:
    kind = str(spec.get("kind", ""))
    if kind == "sqlite":
        return _measure_sqlite(spec)
    if kind == "postgres":
        return _measure_postgres(spec)
    raise Unreachable(f"невідомий вид бази: {kind!r}")


def compare(of_record: dict[str, Any], other: dict[str, Any]) -> dict[str, str]:
    """Співвідношення, а не різниця: `same`/`different` по кожній осі порівняння."""
    return {
        "sources": "same" if of_record["sources"] == other["sources"] else "different",
        "spans": "same" if of_record["spans_digest"] == other["spans_digest"] else "different",
        "version_ids": (
            "same" if of_record["version_ids"] == other["version_ids"] else "different"
        ),
    }


def _judge(
    name: str, spec: dict[str, Any], record: dict[str, Any], shape: dict[str, Any]
) -> dict[str, Any]:
    """Одна база проти оголошення: неназване співвідношення й розійдене — однакова вада."""
    declared = dict(spec.get("relation_to_record", {}))
    actual = compare(record, shape)
    missing = [key for key in RELATIONS if key not in declared]
    drifted = {
        key: {"declared": declared[key], "measured": actual[key]}
        for key in RELATIONS
        if key in declared and declared[key] != actual[key]
    }
    return {
        "base": name,
        "state": "AGREES_WITH_DECLARATION" if not missing and not drifted else "UNDECLARED",
        "relation": actual,
        "undeclared_relations": missing,
        "drifted_relations": drifted,
        "shape": shape,
    }


def adjudicate(
    registry: dict[str, Any],
    shapes: dict[str, dict[str, Any]],
    undeclared: dict[str, str] | None = None,
) -> dict[str, Any]:
    """Вирок: оголошене проти виміряного, по кожній базі, плюс виявлене без оголошення."""
    record_name = str(registry["of_record"])
    bases: dict[str, Any] = dict(registry["bases"])
    findings: list[dict[str, Any]] = []
    agreeing = 0
    measured = 0

    for name, spec in sorted(bases.items()):
        shape = shapes.get(name)
        if shape is None:
            findings.append({"base": name, "state": "UNREACHABLE"})
            continue
        measured += 1
        if name == record_name:
            agreeing += 1
            findings.append({"base": name, "state": "OF_RECORD", "shape": shape})
            continue
        finding = _judge(name, spec, shapes[record_name], shape)
        agreeing += finding["state"] == "AGREES_WITH_DECLARATION"
        findings.append(finding)

    for surface, pid in sorted((undeclared or {}).items()):
        measured += 1
        findings.append({"base": surface, "state": "UNDECLARED_SURFACE", "served_by_pid": pid})

    unreachable = [item["base"] for item in findings if item["state"] == "UNREACHABLE"]
    rate = agreeing / measured if measured else 0.0
    return {
        "schema": "korpus.evidence-bases.v1",
        "of_record": record_name,
        "declared_bases": len(bases),
        "measured_bases": measured,
        "unreachable": unreachable,
        "undeclared_surfaces": sorted((undeclared or {}).keys()),
        "agreeing": agreeing,
        "rate": round(rate, 4),
        "status": "UNKNOWN" if unreachable else "MEASURED",
        "bases": findings,
    }


def _fixture(spans: list[str], version_ids: list[str]) -> dict[str, object]:
    """Форма для тестів: рухається рівно те, що перевіряється, решта — стала."""
    return _shape(
        {"documents": 2, "versions": 2, "spans": len(spans), "embeddings": 0, "audit_events": 5},
        ["a", "b"],
        version_ids,
        spans,
        {"k": 5},
    )


def selftest() -> int:
    """Негативні контролі: гейт, який не вміє відхилити, не є гейтом."""
    record = _fixture(["s1", "s2", "s3"], ["v1", "v2"])
    same = _fixture(["s3", "s1", "s2"], ["v2", "v1"])
    other_spans = _fixture(["s1", "s2"], ["v1", "v2"])

    checks: list[tuple[str, Any, Any]] = [
        ("порядок рядків не змінює дайджеста", compare(record, same)["sources"], "same"),
        ("інша нарізка видно як different", compare(record, other_spans)["spans"], "different"),
        ("однакові ід версій — same", compare(record, other_spans)["version_ids"], "same"),
    ]

    def verdict(declared: dict[str, str], other: dict[str, Any]) -> dict[str, Any]:
        registry = {
            "of_record": "record",
            "bases": {"record": {}, "control": {"relation_to_record": declared}},
        }
        return adjudicate(registry, {"record": record, "control": other})

    honest = {"sources": "same", "spans": "different", "version_ids": "same"}
    checks.append(("правдиве оголошення проходить", verdict(honest, other_spans)["rate"], 1.0))
    lying = {"sources": "same", "spans": "same", "version_ids": "same"}
    checks.append(
        ("оголошення «те саме» на різному падає", verdict(lying, other_spans)["rate"], 0.5)
    )
    stale = {"sources": "same", "spans": "different", "version_ids": "same"}
    checks.append(("застаріле «різне» на однаковому падає", verdict(stale, same)["rate"], 0.5))
    partial = {"sources": "same", "spans": "different"}
    checks.append(("неоголошене співвідношення падає", verdict(partial, other_spans)["rate"], 0.5))
    unknown = adjudicate(
        {"of_record": "record", "bases": {"record": {}, "control": {}}}, {"record": record}
    )
    checks.append(("недосяжна база дає UNKNOWN", unknown["status"], "UNKNOWN"))
    checks.append(("недосяжна база не рахується згодою", unknown["rate"], 1.0))

    passed = 0
    for name, got, want in checks:
        ok = got == want
        passed += ok
        print(f"  {'ok' if ok else 'ПРОВАЛ'} {name}: {got!r}")
    print(f"негативний контроль: {passed}/{len(checks)}")
    return 0 if passed == len(checks) else 1


def _discovered(arguments: argparse.Namespace) -> list[tuple[str, str]]:
    """Виявлення відокремлене від головної, щоб `--no-discovery` було ОДНИМ місцем."""
    if arguments.no_discovery:
        return []
    return sorted(discover_serving_bases(arguments.proc_root).items())


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--registry", type=Path, default=REGISTRY)
    parser.add_argument("--out", type=Path, default=ROOT / "var/evidence-bases.json")
    parser.add_argument(
        "--proc-root",
        type=Path,
        default=Path("/proc"),
        help="де шукати живі процеси; еталон живучості підставляє свій каталог",
    )
    parser.add_argument(
        "--no-discovery",
        action="store_true",
        help="лише реєстр; для середовищ без /proc. Це ЗВУЖУЄ гейт до того стану, у якому "
        "він зелений на неоголошеній базі — вмикати свідомо, не за замовчуванням.",
    )
    parser.add_argument("--selftest", action="store_true")
    return parser.parse_args()


def collect(
    registry: dict[str, Any], arguments: argparse.Namespace
) -> tuple[dict[str, dict[str, Any]], dict[str, str], dict[str, str]]:
    """Форми оголошених баз, причини недосяжності й ВИЯВЛЕНІ бази, яких реєстр не називає."""
    shapes: dict[str, dict[str, Any]] = {}
    reasons: dict[str, str] = {}
    claimed: dict[str, str] = {}
    for name, spec in registry["bases"].items():
        try:
            shapes[name] = measure_base(spec)
        except Unreachable as error:
            reasons[name] = str(error)
        try:
            claimed[declared_fingerprint(spec)] = name
        except Unreachable as error:
            reasons.setdefault(name, str(error))

    ephemeral = dict(registry.get("ephemeral_copies", {}))
    globs = [str(item) for item in ephemeral.get("path_globs", ())]
    undeclared: dict[str, str] = {}
    for surface, pid in _discovered(arguments):
        if surface in claimed:
            continue
        path = surface[len("sqlite:") :] if surface.startswith("sqlite:") else ""
        if not (path and any(fnmatch(path, pattern) for pattern in globs)):
            undeclared[surface] = pid
            continue
        name = f"ephemeral:{Path(path).name}"
        registry["bases"][name] = {
            "kind": "sqlite",
            "path": path,
            "relation_to_record": ephemeral.get("relation_to_record", {}),
        }
        try:
            shapes[name] = _measure_sqlite({"path": path})
        except Unreachable as error:
            reasons[name] = str(error)
    return shapes, reasons, undeclared


def _write(path: Path, report: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    rendered = json.dumps(report, ensure_ascii=False, indent=2)
    path.write_text(rendered, encoding="utf-8")
    print(rendered)


def main() -> int:
    arguments = parse_args()
    if arguments.selftest:
        return selftest()

    registry = json.loads(arguments.registry.read_text(encoding="utf-8"))
    # Виявлення йде ПОВЗ реєстр — інакше гейт проти неоголошених баз спирався б на
    # оголошення й був би зелений рівно в тому стані, заради якого існує.
    shapes, reasons, undeclared = collect(registry, arguments)

    record_name = str(registry["of_record"])
    if record_name not in shapes:
        _write(
            arguments.out,
            {
                "schema": "korpus.evidence-bases.v1",
                "status": "UNKNOWN",
                "reason": f"база обліку недосяжна: {reasons.get(record_name, 'невідомо')}",
            },
        )
        return 2

    report = adjudicate(registry, shapes, undeclared)
    report["unreachable_reasons"] = reasons
    report["ran_at"] = datetime.now(UTC).isoformat()
    # Звіт називає базу обліку, і гейт звіряє ЇЇ ідентичність: інакше «дві бази згодні»
    # лишалось би в силі після зміни тієї, з якою міряли згоду.
    record_spec = registry["bases"][record_name]
    if str(record_spec.get("kind")) == "sqlite":
        database = _data_path(record_spec["path"])
        report["database"] = str(database)
        report["inputs"] = report_inputs(database, Path(__file__).resolve())
    _write(arguments.out, report)
    if report["unreachable"]:
        return 2
    return 0 if report["rate"] == 1.0 else 1


if __name__ == "__main__":
    sys.exit(main())
