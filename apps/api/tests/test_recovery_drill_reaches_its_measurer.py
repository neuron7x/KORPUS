"""Прогін і його вимірювач розійшлися мовчки, і маршрут був мертвий два дні.

`measure_recovery.py` став вимагати URL ролі БРОКЕРА 04.09.2026 —
`scripts/run_recovery_drill.sh` востаннє чіпали 12.08. Прогін доходив до вимірювача,
той відмовляв, і предикат `trusted_recovery_attestation` не мав ЖОДНОЇ дороги до
закриття. Вічне PENDING читалося як очікування на людину, а було НЕДОСЯЖНІСТЮ.

Тест питає не «чи прогін працює» — це коштувало б контейнера. Він питає, чи прогін
ПЕРЕДАЄ кожну змінну, без якої його вимірювачі відмовляють. Розходження двох файлів
ловиться читанням обох, а не пам'яттю того, хто правив один.
"""

from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
DRILL = ROOT / "scripts/run_recovery_drill.sh"
MEASURERS = (
    ROOT / "scripts/measure_recovery.py",
    ROOT / "scripts/verify_postgres_restore.py",
)
#: Змінна, яку вимірювач читає ЯК ОБОВ'ЯЗКОВУ: `os.environ["X"]` кидає без неї.
REQUIRED = re.compile(r'os\.environ\[\s*"([A-Z_]+)"\s*\]')
#: І та, без якої він відмовляє явним повідомленням, читаючи через `.get`.
REFUSED_WITHOUT = ("KORPUS_AUTHZ_DATABASE_URL", "KORPUS_RECOVERY_SOURCE_AUTHZ_URL")


def _required_names() -> set[str]:
    names: set[str] = set()
    for path in MEASURERS:
        names |= set(REQUIRED.findall(path.read_text(encoding="utf-8")))
    return names | set(REFUSED_WITHOUT)


def test_the_drill_passes_every_variable_its_measurers_demand() -> None:
    script = DRILL.read_text(encoding="utf-8")
    missing = sorted(name for name in _required_names() if name not in script)
    assert not missing, (
        f"прогін не передає {missing}: вимірювач відмовить, і предикат лишиться "
        "PENDING без жодної дороги до закриття"
    )


def test_the_reader_of_required_names_actually_finds_them() -> None:
    """Негативний контроль на сам тест: порожня множина зробила б його тавтологією."""
    names = _required_names()
    assert "KORPUS_RECOVERY_SOURCE_URL" in names
    assert "KORPUS_POSTGRES_TEST_URL" in names
    assert len(names) >= 6, f"читач знайшов лише {len(names)} імен — розбір зламався"


def test_the_restored_copy_gets_its_own_broker_url() -> None:
    """Одна URL брокера на обидві бази міряла б відновлену копію проти самої себе."""
    script = DRILL.read_text(encoding="utf-8")
    assert "KORPUS_RECOVERY_RESTORED_AUTHZ_URL" in script
    assert "restored_authz_url" in script
