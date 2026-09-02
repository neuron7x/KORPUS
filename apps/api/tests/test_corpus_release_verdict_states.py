"""Цілий підпис доводить, що опис не підроблено, і НІЧОГО — про те, чи він описує корпус.

ВИМІРЯНО 02.09.2026 ЗАПУСКОМ. `corpus_release.py verify` без `--database` віддавав
`status: PASS` і `rc=0` на маніфесті з фальшивим `content_digest` і ПОРОЖНІМ переліком —
бо вирок читав `result.get("matches_database", True)`, а ключа при пропущеній звірці в
словнику не було взагалі. У звіті поля теж не було, тож читач не відрізняв «звірено й
збіглося» від «не звіряли».

Це дослівно вада 31.08: бекап цілий, розшифровується і містить ІНШИЙ корпус. Той самий
механізм у другому інструменті, і це остання ланка ланцюга «цитата → випуск».

ПОРЯДОК СТАНІВ ТЕЖ Є ЧАСТИНОЮ ВИРОКУ. Перша редакція виправлення ставила UNKNOWN першим
і затуляла ним зламаний підпис — доведено власним прогоном, де `signature_intact: false`
віддавало UNKNOWN замість FAIL. FAIL мусить перебивати UNKNOWN, і це треба було
перевірити, а не припустити.
"""

from __future__ import annotations

import importlib.util
import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
SCRIPT = ROOT / "scripts/corpus_release.py"
if str(ROOT / "scripts") not in sys.path:
    sys.path.insert(0, str(ROOT / "scripts"))
_SPEC = importlib.util.spec_from_file_location("corpus_release", SCRIPT)
assert _SPEC and _SPEC.loader
release = importlib.util.module_from_spec(_SPEC)
sys.modules[_SPEC.name] = release
_SPEC.loader.exec_module(release)

_BODY = {
    "content_digest": "deadbeef" * 8,
    "entries": [],
    "versions": 0,
    "corpus_release": "проба",
}


def _fixture(tmp_path: Path, *, intact: bool) -> tuple[Path, Path]:
    key_file = tmp_path / "release.key"
    key_file.write_bytes(b"0" * 64)
    key = key_file.read_bytes().strip()
    signature = release._sign(_BODY, key) if intact else "0" * 64
    manifest = tmp_path / "manifest.json"
    manifest.write_text(
        json.dumps({**_BODY, "hmac_sha256": signature}, ensure_ascii=False), encoding="utf-8"
    )
    return manifest, key_file


def _run(manifest: Path, key_file: Path) -> tuple[int, dict]:
    completed = subprocess.run(
        [
            sys.executable,
            str(SCRIPT),
            "verify",
            "--manifest",
            str(manifest),
            "--key-file",
            str(key_file),
        ],
        capture_output=True,
        text=True,
        check=False,
        cwd=ROOT,
        env={"PYTHONPATH": f"{ROOT / 'apps/api/src'}:{ROOT}", "PATH": "/usr/bin:/bin"},
    )
    return completed.returncode, json.loads(completed.stdout)


def test_an_unchecked_corpus_is_unknown_not_pass(tmp_path: Path):
    """Головне твердження: без бази вирок не може бути PASS."""
    code, report = _run(*_fixture(tmp_path, intact=True))
    assert report["signature_intact"] is True
    assert report["status"] == "UNKNOWN", "цілий підпис віддали за перевірений корпус"
    assert report["matches_database"] is None, "поле мусить БУТИ і казати «не звіряли»"
    assert code == 2, "UNKNOWN мусить мати власний код виходу, інакше агрегатор чує PASS або FAIL"


def test_a_broken_signature_outranks_unknown(tmp_path: Path):
    """FAIL перебиває UNKNOWN: інакше зламаний підпис ховається за «не звіряли»."""
    code, report = _run(*_fixture(tmp_path, intact=False))
    assert report["signature_intact"] is False
    assert report["status"] == "FAIL"
    assert code == 1


def test_the_report_always_names_whether_the_corpus_was_compared(tmp_path: Path):
    """Негативний контроль на ФОРМУ звіту, а не лише на вирок.

    Саме ВІДСУТНІСТЬ поля робила стару ваду непомітною: читач бачив PASS і не мав як
    дізнатися, що звірки не було.

    Перша редакція цього тесту шукала в тексті скрипта рядок
    `result.get("matches_database", True)` — і впала, бо я поклав той самий вираз у
    пояснювальний коментар про те, що його прибрано. Текст не є поведінкою, і тест на
    написання ламається від правки, яка нічого не змінює, або мовчить про зміну, яка
    змінює все. Дві проби вище судять ВИРОК; ця судить, що поле ПРИСУТНЄ і несе стан.
    """
    _, report = _run(*_fixture(tmp_path, intact=True))
    assert "matches_database" in report, "звіт мовчить про те, чи звіряли корпус"
    assert report["matches_database"] is None
    assert "interpretation" in report, "стан UNKNOWN мусить пояснювати, чого бракує"
