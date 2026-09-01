#!/usr/bin/env python3
"""Малий корпус, на якому гейти можна ЗМУСИТИ впасти.

`make gate-liveness` озброїв шість гейтів із сорока чотирьох, і причина не в недбалості:
проба копіює дерево й отруює копію, а гейти корпусу читають `var/runtime` — 395 МБ бази й
об'єктів, плюс ключі, яких у дереві немає й бути не може. Отруїти такий вхід ніхто не міг,
тож найважливіші перевірки — ті, що боронять саме твердження системи, — жодного разу не
показали, що здатні почервоніти.

Тут будується той самий корпус у мініатюрі: два документи, їхні об'єкти, прольоти, три
події журналу й тестовий ключ. Гейти приймають `--database` й `--object-root`, тож проба
дає їм ЦЕЙ вхід, псує його й дивиться на вирок.

**Чому генератор, а не покладений у git файл.** База — двійковий файл; рецензент не бачить
у ній нічого. Тут у git лежить і генератор, і його вихід, а `--verify` доводить, що вихід
відтворюється байт у байт із генератора. Розходження означає, що еталон правили повз опис,
і це видно.

**Прольоти будуються тим самим `cut_points`, що й бойова нарізка** — інакше еталон
доводив би гейти на входах, яких конвеєр не виробляє.

**Ключ у `audit-key.txt` не секрет.** Він підписує рівно три вигадані події цього еталона
й названий так, щоб його не сплутали з ключем розгортання. Секрет, що лежить у git,
перестає бути секретом — саме це й знайшлось 31.08.2026 у двох місцях одразу.

    build_liveness_fixture.py            # зібрати
    build_liveness_fixture.py --verify   # довести, що зібране = те, що в git
"""

from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import sqlite3
import sys
from datetime import UTC, datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
sys.path.insert(0, str(ROOT / "apps/api/src"))

from respan_from_source import cut_points  # noqa: E402

#: У git лежать ТІЛЬКИ тексти. Усе, що будується — база, об'єкти, копія ключа — живе під
#: `var/`, бо `var/` виключена з межі джерел усюди. Перша версія клала базу поруч із
#: текстами, і `verify_source_manifest` у копії без `.git` побачив її файловою системою як
#: ВКИНУТИЙ файл: `*.db` невидима для git і видима для обходу теки. Похідний артефакт у
#: джерельному дереві ламає саме ту перевірку, яка боронить межу джерел.
SOURCES_DIR = ROOT / "evals/fixtures/liveness/sources"
FIXTURE = ROOT / "var/liveness-fixture"
KEY_ID = "fixture-2026-08"
WHEN = "2026-08-31 00:00:00"
STATUTE_URI = "https://zakon.rada.gov.ua/laws/show/550-14/print"

#: Тексти лежать у дереві ОКРЕМИМИ файлами, а не константами тут, і це не оформлення.
#: Проба живучості псує ВХІД і перезбирає еталон; якби тексти жили в цьому скрипті,
#: перезбирання затирало б отруту, і кожна проба питала б чистий вхід під виглядом
#: зіпсованого — тобто доводила б рівно нічого.
DOCUMENTS = (
    ("doc-statute", "Статут гарнізонної та вартової служб Збройних Сил України", "statute.txt"),
    ("doc-derived", "Обов'язки: Вивідний (Статут, ст.243)", "derived.txt"),
)

SCHEMA = """
CREATE TABLE documents (
	id VARCHAR(36) NOT NULL, 
	canonical_title VARCHAR(500) NOT NULL, 
	corpus_id VARCHAR(64) NOT NULL, 
	issuer VARCHAR(300) NOT NULL, 
	jurisdiction VARCHAR(50) NOT NULL, 
	document_type VARCHAR(100) NOT NULL, 
	access_tier INTEGER NOT NULL, 
	classification VARCHAR(32) NOT NULL, 
	compartments_json TEXT NOT NULL, 
	created_at DATETIME NOT NULL, 
	PRIMARY KEY (id), 
	CONSTRAINT ck_document_access_tier CHECK (access_tier >= 0 AND access_tier <= 3)
);
CREATE TABLE document_versions (
	id VARCHAR(36) NOT NULL, 
	document_id VARCHAR(36) NOT NULL, 
	revision VARCHAR(120) NOT NULL, 
	publication_identifier VARCHAR(200), 
	source_uri TEXT, 
	source_hash VARCHAR(64) NOT NULL, 
	object_key TEXT NOT NULL, 
	mime_type VARCHAR(200) NOT NULL, 
	publication_date DATE, 
	effective_from DATE, 
	effective_until DATE, 
	rescinded_at DATETIME, 
	authority VARCHAR(64) NOT NULL, 
	source_key_id VARCHAR(200), 
	source_signature_b64 TEXT, 
	content_fingerprint VARCHAR(16) NOT NULL, 
	near_duplicate_of_version_id VARCHAR(36), 
	near_duplicate_similarity FLOAT, 
	near_duplicate_acknowledged_by VARCHAR(200), 
	extraction_text_chars INTEGER NOT NULL, 
	extraction_alnum_ratio FLOAT NOT NULL, 
	extraction_replacement_ratio FLOAT NOT NULL, 
	extraction_quality_flags_json TEXT NOT NULL, 
	extraction_quality_acknowledged_by VARCHAR(200), 
	review_state VARCHAR(64) NOT NULL, 
	supersedes_version_id VARCHAR(36), 
	state_version INTEGER NOT NULL, 
	metadata_reviewed_by VARCHAR(200), 
	metadata_reviewer_credential_id VARCHAR(200), 
	content_reviewed_by VARCHAR(200), 
	content_reviewer_credential_id VARCHAR(200), 
	approved_at DATETIME, 
	approved_by VARCHAR(200), 
	approver_credential_id VARCHAR(200), 
	is_current BOOLEAN NOT NULL, 
	created_at DATETIME NOT NULL, 
	PRIMARY KEY (id), 
	CONSTRAINT uq_version_document_revision UNIQUE (document_id, revision), 
	CONSTRAINT ck_version_state_version CHECK (state_version >= 0), 
	CONSTRAINT ck_version_effective_window CHECK (effective_until IS NULL OR effective_from IS NULL OR effective_until >= effective_from), 
	CONSTRAINT ck_version_current_approved CHECK (NOT is_current OR review_state = 'approved'), 
	FOREIGN KEY(document_id) REFERENCES documents (id) ON DELETE CASCADE, 
	FOREIGN KEY(near_duplicate_of_version_id) REFERENCES document_versions (id), 
	FOREIGN KEY(supersedes_version_id) REFERENCES document_versions (id)
);
CREATE UNIQUE INDEX uq_current_version_per_document ON document_versions (document_id) WHERE is_current IS 1;
CREATE TABLE evidence_spans (
	id VARCHAR(36) NOT NULL, 
	version_id VARCHAR(36) NOT NULL, 
	ordinal INTEGER NOT NULL, 
	page INTEGER, 
	section VARCHAR(500), 
	text TEXT NOT NULL, 
	text_hash VARCHAR(64) NOT NULL, 
	created_at DATETIME NOT NULL, 
	PRIMARY KEY (id), 
	CONSTRAINT uq_span_version_ordinal UNIQUE (version_id, ordinal), 
	FOREIGN KEY(version_id) REFERENCES document_versions (id) ON DELETE CASCADE
);
CREATE TABLE audit_events (
	sequence BIGINT NOT NULL, 
	event_id VARCHAR(36) NOT NULL, 
	event_schema_version INTEGER NOT NULL, 
	occurred_at DATETIME NOT NULL, 
	actor_subject VARCHAR(200) NOT NULL, 
	action VARCHAR(200) NOT NULL, 
	resource_type VARCHAR(100) NOT NULL, 
	resource_id VARCHAR(200), 
	payload_json TEXT NOT NULL, 
	previous_hash VARCHAR(64) NOT NULL, 
	event_hash VARCHAR(64) NOT NULL, 
	audit_key_id VARCHAR(64) DEFAULT 'legacy-unversioned' NOT NULL, 
	PRIMARY KEY (sequence), 
	UNIQUE (event_id)
);
CREATE TABLE audit_heads (
	singleton_id INTEGER NOT NULL, 
	sequence BIGINT NOT NULL, 
	head_hash VARCHAR(64) NOT NULL, 
	PRIMARY KEY (singleton_id), 
	CONSTRAINT ck_audit_head_singleton CHECK (singleton_id = 1)
);
"""


def insert(connection: sqlite3.Connection, table: str, values: dict[str, object]) -> None:
    """За іменами колонок, не позиційно: схема реальна й має 36 колонок у версіях."""
    columns = ", ".join(values)
    marks = ", ".join("?" for _ in values)
    connection.execute(f"insert into {table} ({columns}) values ({marks})", tuple(values.values()))


def object_path(text: str) -> tuple[str, str]:
    """Адреса за вмістом, як у бойовому сховищі: два рівні по два символи хеша."""
    digest = hashlib.sha256(text.encode("utf-8")).hexdigest()
    return f"{digest[:2]}/{digest[2:4]}/{digest}", digest


def build(target: Path) -> dict[str, str]:
    objects = target / "objects"
    for stale in sorted(objects.rglob("*"), reverse=True):
        stale.unlink() if stale.is_file() else stale.rmdir()
    database = target / "korpus.db"
    database.unlink(missing_ok=True)
    connection = sqlite3.connect(str(database))
    connection.executescript(SCHEMA)
    written: dict[str, str] = {}
    for index, (doc_id, title, source_name) in enumerate(DOCUMENTS):
        text = (SOURCES_DIR / source_name).read_text(encoding="utf-8")
        key, digest = object_path(text)
        path = objects / key
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")
        written[doc_id] = digest
        insert(
            connection,
            "documents",
            {
                "id": doc_id,
                "canonical_title": title,
                "corpus_id": "fixture",
                "issuer": "МОУ",
                "jurisdiction": "UA",
                "document_type": "statute",
                "access_tier": 0,
                "classification": "public",
                "compartments_json": "[]",
                "created_at": WHEN,
            },
        )
        insert(
            connection,
            "document_versions",
            {
                "id": f"v-{doc_id}",
                "document_id": doc_id,
                "revision": "1",
                "source_uri": STATUTE_URI,
                "source_hash": digest,
                "object_key": key,
                "mime_type": "text/plain",
                "authority": "official_ua",
                "content_fingerprint": digest[:16],
                "extraction_text_chars": len(text),
                "extraction_alnum_ratio": 0.9,
                "extraction_replacement_ratio": 0.0,
                "extraction_quality_flags_json": "[]",
                "review_state": "approved",
                "state_version": 1,
                "is_current": 1,
                "created_at": WHEN,
            },
        )
        for ordinal, (start, end) in enumerate(cut_points(text, limit=400, overlap=80)):
            piece = text[start:end]
            insert(
                connection,
                "evidence_spans",
                {
                    "id": f"s-{index}-{ordinal}",
                    "version_id": f"v-{doc_id}",
                    "ordinal": ordinal,
                    "text": piece,
                    "text_hash": hashlib.sha256(piece.encode("utf-8")).hexdigest(),
                    "created_at": WHEN,
                },
            )
    ledger = json.loads((SOURCES_DIR / "audit-events.json").read_text(encoding="utf-8"))
    for event in ledger["events"]:
        insert(connection, "audit_events", dict(event))
    insert(
        connection,
        "audit_heads",
        {"singleton_id": 1, "sequence": len(ledger["events"]), "head_hash": ledger["head_hash"]},
    )
    connection.commit()
    connection.close()
    shutil.copyfile(SOURCES_DIR / "audit-key.txt", target / "audit-key.txt")
    # Друга база й фальшивий каталог процесів — для гейта `evidence-bases`.
    #
    # Він судить РЕЄСТР, і реєстр лежить у дереві, як і належить. Але його присуд має
    # сенс лише там, де є ЩО не оголосити: без другої бази й без процесу, який її
    # обслуговує, отруту «база жива, а реєстр про неї не знає» відтворити нічим — а це
    # рівно та отрута, яку перша версія гейта пропускала з кодом 0.
    #
    # Шлях у `environ` записаний ВІДНОСНИЙ (`sqlite:///` + шлях без початкової навскісної,
    # як у SQLAlchemy) і тому однаковий у кожній збірці: `--verify` порівнює два прогони
    # побайтово, і абсолютний шлях зробив би еталон недетермінованим за побудовою.
    # Розв'язується він від робочого каталогу, а проба живучості запускає гейт із кореня
    # дерева — тобто рівно там, де ці бази й лежать.
    shutil.copyfile(database, target / "mirror.db")
    for pid, name in (("4242", "korpus.db"), ("4243", "mirror.db")):
        entry = target / "proc" / pid
        entry.mkdir(parents=True, exist_ok=True)
        (entry / "environ").write_bytes(
            f"KORPUS_DATABASE_URL=sqlite:///var/liveness-fixture/{name}".encode()
        )
    (target / "README.md").write_text(
        "# Еталон для проб живучості гейтів\n\n"
        "Зібрано `scripts/build_liveness_fixture.py`. Не правити руками: `--verify` доводить,\n"
        "що вміст відтворюється з генератора, і ручна правка стане видимою розбіжністю.\n\n"
        "`audit-key.txt` НЕ є секретом — він підписує три вигадані події цього еталона.\n\n"
        "`korpus.db` НЕ лежить у git (`.gitignore: *.db`): це похідний артефакт. Перед\n"
        "прямим запуском гейта збери його — `python scripts/build_liveness_fixture.py`.\n"
        "Проби живучості роблять це самі, тому отрута у вхідному тексті доходить до гейта.\n",
        encoding="utf-8",
    )
    return written


def digest_tree(target: Path) -> str:
    """Тільки те, що лежить у git.

    `*.db` виключена `.gitignore`, тож на свіжому клоні її просто немає. Якби вона
    входила в дайджест, `--verify` порівнював би зібране з незібраним і відмовляв там, де
    все правильно — а відмова, яка приходить як факт, коштувала цьому дереву вже двох
    хибних висновків за добу.
    """
    parts = []
    for path in sorted(target.rglob("*")):
        if path.is_file() and path.suffix != ".db":
            parts.append(path.relative_to(target).as_posix())
            parts.append(hashlib.sha256(path.read_bytes()).hexdigest())
    return hashlib.sha256("\n".join(parts).encode("utf-8")).hexdigest()


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--verify", action="store_true")
    args = parser.parse_args()
    if args.verify:
        import tempfile

        with tempfile.TemporaryDirectory() as tmp:
            first, second = Path(tmp) / "a", Path(tmp) / "b"
            first.mkdir()
            second.mkdir()
            build(first)
            build(second)
            # Обидва дайджести знімаються ТУТ, усередині блоку. Друкований раніше
            # рахувався після виходу з нього — каталогу вже не було, `rglob` не знаходив
            # нічого, і у звіт лягав sha256 порожнього рядка
            # (e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855) для
            # будь-якого еталона. Порівняння було справжнім, надрукований доказ — ні.
            digest = digest_tree(first)
            same = digest == digest_tree(second)
        print(
            json.dumps(
                {
                    "status": "PASS" if same else "FAIL",
                    "deterministic": same,
                    "digest": digest if same else None,
                    "why": (
                        "два прогони з тих самих текстів мусять дати той самий еталон; "
                        "інакше проба живучості порівнює гейт із рухомою ціллю"
                    ),
                },
                ensure_ascii=False,
                indent=2,
            )
        )
        return 0 if same else 1
    FIXTURE.mkdir(parents=True, exist_ok=True)
    build(FIXTURE)
    print(
        json.dumps(
            {
                "status": "PASS",
                "built": str(FIXTURE),
                "digest": digest_tree(FIXTURE),
                "built_at": datetime.now(UTC).isoformat(),
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
