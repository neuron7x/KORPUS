"""Звіт кредитує вісь, лише поки описує ТОЙ САМИЙ стан.

Гейт осей перевіряв ВІК звіту: старший за добу — UNMEASURED. Вік це сурогат. Він
відповідає на «коли міряли», а питання інше: «чи те, що міряли, ще те саме». Звіт віком
23 години про корпус, змінений п'ять хвилин тому, проходив; звіт віком 25 годин про
нерухомий корпус відхилявся. Обидві помилки з одного джерела.

Тут звіт носить ідентичність своїх ВХОДІВ — змісту корпусу й самого вимірювача, — і
гейт звіряє її покомпонентно, бо «звіт застарів» без причини змушує наступного вгадувати,
а зрушений корпус і зрушений вимірювач вимагають різних дій.
"""

from __future__ import annotations

import sqlite3
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / "scripts"))

from build_liveness_fixture import build  # noqa: E402
from check_answer_axes import stale_input  # noqa: E402
from corpus_identity import corpus_identity, identity_digest, report_inputs  # noqa: E402


def _fixture(tmp_path: Path) -> Path:
    target = tmp_path / "corpus"
    target.mkdir()
    (target / "sources").mkdir()
    for name in ("statute.txt", "derived.txt", "audit-events.json", "audit-key.txt"):
        source = ROOT / "evals/fixtures/liveness/sources" / name
        (target / "sources" / name).write_bytes(source.read_bytes())
    build(target)
    return target / "korpus.db"


def test_the_identity_moves_when_a_quote_changes(tmp_path: Path) -> None:
    database = _fixture(tmp_path)
    before = identity_digest(corpus_identity(database))

    connection = sqlite3.connect(str(database))
    connection.execute(
        "update evidence_spans set text_hash = 'f' * 64 "
        "where id = (select id from evidence_spans limit 1)"
    )
    connection.commit()
    connection.close()

    assert identity_digest(corpus_identity(database)) != before


def test_the_identity_moves_when_a_link_changes(tmp_path: Path) -> None:
    """Посилання не входять у хеш прольоту, а вісь простежуваності міряє саме їх."""
    database = _fixture(tmp_path)
    before = identity_digest(corpus_identity(database))

    connection = sqlite3.connect(str(database))
    connection.execute(
        "update document_versions set source_uri = 'https://змінено/' "
        "where id = (select id from document_versions limit 1)"
    )
    connection.commit()
    connection.close()

    assert identity_digest(corpus_identity(database)) != before


def test_housekeeping_does_not_move_the_identity(tmp_path: Path) -> None:
    """Негативний контроль: ідентичність, що рухається від VACUUM, псує свіжі звіти.

    Вона мусить бути похідною від ЗМІСТУ. Файл рухається від службових причин, яких
    жодна вісь не міряє, а `touch` — це зміна mtime, не корпусу.
    """
    database = _fixture(tmp_path)
    before = identity_digest(corpus_identity(database))

    connection = sqlite3.connect(str(database))
    connection.execute("vacuum")
    connection.close()
    database.touch()

    assert identity_digest(corpus_identity(database)) == before


def test_an_unchanged_report_is_not_called_stale(tmp_path: Path) -> None:
    """Сторож, який завжди каже «застарів», не розрізняє нічого."""
    database = _fixture(tmp_path)
    measurer = Path("scripts/measure_corpus_integrity.py")
    payload = {
        "database": str(database),
        "inputs": report_inputs(database, ROOT / measurer),
    }
    spec = {"measurer": str(measurer)}

    assert stale_input(spec, payload, ROOT) is None


def test_a_changed_measurer_is_named_as_the_thing_that_moved(tmp_path: Path) -> None:
    database = _fixture(tmp_path)
    measurer = Path("scripts/measure_corpus_integrity.py")
    payload = {
        "database": str(database),
        "inputs": report_inputs(database, ROOT / measurer),
    }
    payload["inputs"]["measurer"] = "0" * 64

    moved = stale_input({"measurer": str(measurer)}, payload, ROOT)

    assert moved is not None
    assert "вимірювач" in moved


def test_a_report_without_recorded_inputs_falls_through_to_age(tmp_path: Path) -> None:
    """Звіти, зроблені до цієї прив'язки, не оголошуються застарілими за замовчуванням.

    Інакше введення правила саме по собі почервонило б усе, що ним ще не позначене, —
    і це читалося б як регрес системи, а не як зміна вимірювання.
    """
    assert stale_input({"measurer": "scripts/measure_corpus_integrity.py"}, {}, ROOT) is None


def test_a_report_about_a_corpus_that_is_gone_cannot_be_judged(tmp_path: Path) -> None:
    """Відсутність бази — не «свіжо» і не «застаріло», а неможливість судити."""
    database = _fixture(tmp_path)
    measurer = Path("scripts/measure_corpus_integrity.py")
    payload = {
        "database": str(database),
        "inputs": report_inputs(database, ROOT / measurer),
    }
    database.unlink()

    moved = stale_input({"measurer": str(measurer)}, payload, ROOT)

    assert moved is not None
    assert "немає" in moved


def test_a_changed_corpus_is_named_as_the_thing_that_moved(tmp_path: Path) -> None:
    database = _fixture(tmp_path)
    measurer = Path("scripts/measure_corpus_integrity.py")
    payload = {
        "database": str(database),
        "inputs": report_inputs(database, ROOT / measurer),
    }
    connection = sqlite3.connect(str(database))
    connection.execute(
        "update document_versions set source_uri = 'https://інше/' "
        "where id = (select id from document_versions limit 1)"
    )
    connection.commit()
    connection.close()

    moved = stale_input({"measurer": str(measurer)}, payload, ROOT)

    assert moved is not None
    assert "корпус" in moved


def test_a_recorded_input_the_gate_ignores_is_worse_than_none(tmp_path: Path) -> None:
    """Голова журналу лежала у входах і не звірялась, тож звіт лишався «свіжим».

    Записаний вхід, якого ніхто не перевіряє, створює враження прив'язки там, де її
    немає, — і це гірше за відсутню, бо виглядає як зроблена робота.
    """
    database = _fixture(tmp_path)
    measurer = Path("scripts/measure_corpus_integrity.py")
    payload = {
        "database": str(database),
        "inputs": {
            **report_inputs(database, ROOT / measurer),
            "audit_head": "0" * 64,
        },
    }

    moved = stale_input({"measurer": str(measurer)}, payload, ROOT)

    assert moved is not None
    assert "журнал" in moved
