"""Два оголошення оточення публічного API під гейтом.

Копії дві навмисно: юніт systemd мусить бути самооголошеним, бо його властивості
безпеки читаються в репозиторії. Ціна цього рішення — розходження, і воно сталося.
Виміряно 31.08.2026: сторож відновлює API через `systemctl --user restart`, тобто
НЕНАГЛЯДОВИЙ шлях іде юнітом, і після відновлення о 21:34 у живому процесі не було ні
`KORPUS_MODEL_EGRESS_POSTURE`, ні ключа аудиту. Виправлення, зроблене у скрипті, туди
не доходило: посада лишалась `external_allowed`, журнал підписувався плейсхолдером.

Тести тримають не список змінних (він росте), а правило: кожна різниця мусить бути
названою, а безпекові значення — збігатися дослівно.
"""

from __future__ import annotations

import importlib.util
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
SCRIPT = ROOT / "scripts/check_public_env_parity.py"
SPEC = importlib.util.spec_from_file_location("check_public_env_parity", SCRIPT)
assert SPEC and SPEC.loader
GATE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(GATE)


def _real() -> tuple[dict[str, str], dict[str, str]]:
    unit = GATE.unit_environment(
        (ROOT / "deploy/public/korpus-public-api.service").read_text("utf-8")
    )
    shell = GATE.shell_environment((ROOT / "scripts/serve_public.sh").read_text("utf-8"))
    return unit, shell


def test_the_two_declarations_agree_on_the_real_files() -> None:
    unit, shell = _real()
    findings = GATE.assess(unit, shell)
    assert GATE.verdict(findings) == "PASS", findings


def test_the_unattended_path_carries_the_egress_posture() -> None:
    """Саме її бракувало юніту, і саме юнітом піднімає сторож."""
    unit, _shell = _real()
    assert unit.get("KORPUS_MODEL_EGRESS_POSTURE") == "local_only"


def test_the_unattended_path_carries_the_key_that_signs_the_evidence() -> None:
    unit, _shell = _real()
    assert unit.get("KORPUS_AUDIT_HMAC_KEY_FILE", "").endswith("audit-key.txt")
    assert unit.get("KORPUS_AUDIT_KEY_ID") == "korpus-public-2026-08-31"


def _finding(findings: list[dict[str, str]], check: str) -> dict[str, str]:
    """Конкретна перевірка, а не сукупний вирок.

    Тест, що дивиться лише на вирок, не вбиває мутанта: зняття однієї перевірки
    ховається за іншою, яка червоніє з тієї ж причини. Виміряно — троє мутантів
    вижили саме так.
    """
    return next(item for item in findings if item["check"] == check)


def test_a_variable_the_script_declares_and_the_unit_lacks_is_refused() -> None:
    unit, shell = _real()
    stripped = {k: v for k, v in unit.items() if k != "KORPUS_MODEL_EGRESS_POSTURE"}
    finding = _finding(GATE.assess(stripped, shell), "unit_missing")
    assert finding["verdict"] == "FAIL" and "KORPUS_MODEL_EGRESS_POSTURE" in finding["detail"]


def test_a_safety_value_that_drifts_is_refused() -> None:
    unit, shell = _real()
    assert (
        GATE.verdict(
            GATE.assess({**unit, "KORPUS_MODEL_EGRESS_POSTURE": "external_allowed"}, shell)
        )
        == "FAIL"
    )


def test_a_secret_by_value_in_the_unit_is_refused() -> None:
    """Юніт читається в репозиторії; секрет значенням там був би секретом у git."""
    unit, shell = _real()
    finding = _finding(
        GATE.assess({**unit, "KORPUS_JWT_SECRET": "s3cret"}, shell), "no_secret_by_value"
    )
    assert finding["verdict"] == "FAIL" and "KORPUS_JWT_SECRET" in finding["detail"]


def test_an_indented_export_is_seen() -> None:
    """`export` усередині блоку — звичайний shell; парсер, прибитий до початку рядка,
    мовчки не побачив би такої змінної, і гейт звітував би про паритет, якого немає."""
    parsed = GATE.shell_environment('if true; then\n  export KORPUS_X="1"\nfi\n')
    assert parsed == {"KORPUS_X": "1"}


def test_a_default_in_a_parameter_expansion_is_the_effective_value() -> None:
    """`${VAR:-x}` без оточення дає x — саме воно чинне на ненаглядовому шляху."""
    parsed = GATE.shell_environment('export KORPUS_X="${KORPUS_X:-local_only}"\n')
    assert parsed == {"KORPUS_X": "local_only"}


def test_unknown_is_never_a_pass() -> None:
    assert GATE.verdict(GATE.assess({}, {"KORPUS_X": "1"})) == "UNKNOWN"
    assert GATE.verdict(GATE.assess({"KORPUS_X": "1"}, {})) == "UNKNOWN"


def test_gate_reddens_on_every_defect_separately() -> None:
    completed = subprocess.run(
        [sys.executable, str(SCRIPT), "--selftest"], capture_output=True, text=True, check=False
    )
    assert completed.returncode == 0, completed.stdout + completed.stderr
