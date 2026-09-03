"""Гейт проти неоголошених баз не сміє сам спиратися на оголошення.

31.08.2026 корпус відремонтували: нарізку перебудували з оригіналів, прольотів стало
31 464 замість 38 863. Через добу вимір показав, що баз ДВІ — поруч живе PostgreSQL з
увімкненою семантикою, і в ній лишились ті самі 38 863 з-перед ремонту. Жодна вісь
цього не бачила, бо кожна читає ОДНУ базу, ту, яку їй назвали.

Перша версія цього виміру читала лише реєстр. Отрута «прибрати базу з реєстру» — рівно
те, що сталося насправді — давала код 0: нема кого міряти, отже все гаразд. Тому тут два
класи тестів, і другий важливіший за перший:

  · присуд — оголошене проти виміряного;
  · ВИЯВЛЕННЯ — те, що робить присуд можливим, коли реєстр мовчить.
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / "scripts"))

import measure_evidence_bases as evidence_bases  # noqa: E402
from measure_evidence_bases import (  # noqa: E402
    _fixture,
    adjudicate,
    compare,
    discover_serving_bases,
    fingerprint,
)

RECORD = _fixture(["s1", "s2", "s3"], ["v1", "v2"])
RECUT = _fixture(["s1", "s2"], ["v1", "v2"])
REIMPORTED = _fixture(["s1", "s2", "s3"], ["w1", "w2"])


def _verdict(declared: dict[str, str], other: dict[str, object], **extra: object) -> dict:
    registry = {
        "of_record": "record",
        "bases": {"record": {}, "control": {"relation_to_record": declared}},
    }
    return adjudicate(registry, {"record": RECORD, "control": other}, **extra)


def test_the_same_sources_cut_differently_are_not_the_same_base() -> None:
    """Те, що сталося насправді: ті самі джерела, інша нарізка."""
    assert compare(RECORD, RECUT) == {
        "sources": "same",
        "spans": "different",
        "version_ids": "same",
    }


def test_the_same_document_under_a_new_identifier_is_visible_as_different() -> None:
    """Цитата з такої бази називає версію, якої в базі обліку немає."""
    assert compare(RECORD, REIMPORTED)["version_ids"] == "different"
    assert compare(RECORD, REIMPORTED)["sources"] == "same"


def test_a_true_declaration_passes() -> None:
    honest = {"sources": "same", "spans": "different", "version_ids": "same"}

    assert _verdict(honest, RECUT)["rate"] == 1.0


def test_a_declaration_that_says_the_same_about_a_base_that_differs_fails() -> None:
    lying = {"sources": "same", "spans": "same", "version_ids": "same"}

    assert _verdict(lying, RECUT)["rate"] == 0.5


def test_a_declaration_of_difference_that_stopped_being_true_fails() -> None:
    """Застаріла правда не є правдою: після повторного імпорту оголошення теж бреше."""
    stale = {"sources": "same", "spans": "different", "version_ids": "same"}
    aligned = _fixture(["s3", "s1", "s2"], ["v2", "v1"])

    assert _verdict(stale, aligned)["rate"] == 0.5


def test_a_relation_nobody_declared_is_not_silently_accepted() -> None:
    assert _verdict({"sources": "same", "spans": "different"}, RECUT)["rate"] == 0.5


def test_an_unreachable_base_is_unknown_rather_than_agreement() -> None:
    unknown = adjudicate(
        {"of_record": "record", "bases": {"record": {}, "control": {}}}, {"record": RECORD}
    )

    assert unknown["status"] == "UNKNOWN"
    assert "control" in [
        item["base"] for item in unknown["bases"] if item["state"] == "UNREACHABLE"
    ]


# ── Виявлення. Без нього все вище зелене саме тоді, коли базу приховали.


def test_a_base_nobody_declared_but_something_serves_is_a_rejection() -> None:
    """Отрута, що проходила: реєстр мовчить, база жива."""
    honest = {"sources": "same", "spans": "different", "version_ids": "same"}

    report = _verdict(honest, RECUT, undeclared={"postgres:korpus@host:5432/korpus": "4242"})

    assert report["rate"] < 1.0
    assert report["undeclared_surfaces"] == ["postgres:korpus@host:5432/korpus"]


def test_discovery_reads_the_environment_of_live_processes(tmp_path: Path) -> None:
    """Відбиток береться з того, ЩО процес відкрив, а не з того, що про нього записали."""
    process = tmp_path / "4242"
    process.mkdir()
    (process / "environ").write_bytes(
        b"PATH=/usr/bin\x00KORPUS_DATABASE_URL=sqlite:////srv/korpus.db\x00HOME=/root\x00"
    )

    assert discover_serving_bases(tmp_path) == {"sqlite:/srv/korpus.db": "4242"}


def test_a_process_without_a_corpus_is_not_a_base(tmp_path: Path) -> None:
    """Негативний контроль: виявлення, у яке потрапляє все, нічого не виявляє."""
    process = tmp_path / "77"
    process.mkdir()
    (process / "environ").write_bytes(b"PATH=/usr/bin\x00LANG=uk_UA.UTF-8\x00")

    assert discover_serving_bases(tmp_path) == {}


def test_the_fingerprint_does_not_carry_the_password() -> None:
    """Звіт публікується; відбиток із паролем зробив би вимір місцем витоку."""
    printed = fingerprint("postgresql+psycopg://postgres:s3cr3t@172.18.0.2:5432/korpus")

    assert "s3cr3t" not in printed
    assert printed == "postgres:postgres@172.18.0.2:5432/korpus"


def test_relative_evidence_base_paths_bind_to_the_runtime_root(
    tmp_path: Path,
    monkeypatch,
) -> None:
    monkeypatch.setattr(evidence_bases, "DATA_ROOT", tmp_path)

    assert evidence_bases._data_path("var/runtime/korpus.db") == (
        tmp_path / "var/runtime/korpus.db"
    )
    assert evidence_bases._data_path(tmp_path / "absolute.db") == tmp_path / "absolute.db"
