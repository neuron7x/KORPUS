"""Оголошений юніт, що несе свіжий код і відмовляє кожному, — це відмова, не свіжість.

Виміряно 06.09.2026: публічний сервіс ніс поточну ревізію і три доби віддавав `503`
КОЖНОМУ запиту, бо якір аудиту пам'ятає 81 подію, яких відновлена після пошкодження
база не має. Конвеєр 18/18, `make validate` rc=0, лан розгортання зелений — і система,
до якої прийшла б запрошена людина, не відповіла жодного разу.

Причина була структурна, а не недогляд: конверт релізу оголошував ЛИШЕ пілот, тож
гейт свіжості чесно міряв процес, який не несе корпус. Питання «чи відповідає» не
ставив ніхто.
"""

from __future__ import annotations

import importlib.util
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
SPEC = importlib.util.spec_from_file_location(
    "check_serving_readiness", ROOT / "scripts/check_serving_readiness.py"
)
assert SPEC and SPEC.loader
GATE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(GATE)

OK = {"port": 8030, "status": 200, "body": '{"status":"ready"}'}
REFUSING = {"port": 8000, "status": 503, "body": '{"detail":{"database":true,"ready":false}}'}


def test_a_service_that_answers_is_serving() -> None:
    """Позитивне плече. Без нього кожне спростування нижче проходило б і на гейті,
    який завжди каже FAIL."""
    assert GATE.verdict(["u"], [8030], [OK])["status"] == "PASS"


def test_one_declared_port_refusing_fails_the_whole_verdict() -> None:
    """Найслабша ланка, не середнє: сервіс, що відмовляє, не компенсується сусідом."""
    result = GATE.verdict(["u"], [8030, 8000], [OK, REFUSING])
    assert result["status"] == "FAIL"
    assert result["serving"] == [8030]
    assert result["refusing"][0]["port"] == 8000


def test_an_empty_probe_set_is_not_agreement() -> None:
    """`all([])` істинне: порожній перелік проб зробив би гейт зеленим у стані,
    заради якого він існує."""
    assert GATE.verdict(["u"], [], [])["status"] == "FAIL"


def test_a_topology_that_declares_nothing_is_not_a_subject() -> None:
    """Нуль оголошених юнітів і один випадковий процес читались би однаково."""
    assert GATE.verdict([], [8030], [OK])["status"] == "FAIL"


def test_an_unreachable_port_is_a_state_not_a_missing_measurement() -> None:
    unreachable = {"port": 1, "status": None, "body": "ConnectionRefusedError"}
    assert GATE.verdict(["u"], [1], [unreachable])["status"] == "FAIL"


def test_the_refusal_names_which_checks_are_false() -> None:
    """«503» саме по собі каже «щось не так». Гейт мусить назвати ЩО."""
    body = '{"detail":{"database":true,"anchor_not_ahead":false,"ready":false}}'
    assert GATE.refusing_detail(body) == ["anchor_not_ahead", "ready"]


def test_a_body_that_is_not_json_does_not_break_the_verdict() -> None:
    assert GATE.refusing_detail("<html>502 Bad Gateway</html>") == []


def test_a_flat_payload_without_detail_is_still_read() -> None:
    """Не кожна відмова обгорнута в `detail`; читач мусить впоратись з обома формами."""
    assert GATE.refusing_detail('{"ready": false, "database": true}') == ["ready"]


def test_liveness_saying_ok_while_readiness_refuses_is_named() -> None:
    """Саме ця пара тримала простій невидимим три доби.

    `/health` віддає 200 доти, доки процес живий; `/ready` відмовляв кожному запиту з
    03.09.2026. Усе, що дивилось на сервіс, дивилось на живучість — і бачило «ок».
    «Здоровий» і «здатний відповісти» — різні твердження.
    """
    live_ok = {"port": 8000, "status": 200, "body": '{"status":"ok"}'}
    result = GATE.verdict(["u"], [8000], [REFUSING], [live_ok])
    assert result["liveness_masking_readiness"] == [8000]
    assert result["status"] == "FAIL"


def test_a_port_that_is_dead_on_both_paths_is_not_masked() -> None:
    """Дуал: зупинений сервіс видно і без цього поля. Маскування — це саме СУПЕРЕЧНІСТЬ
    між двома пробами, а не будь-яка відмова."""
    dead = {"port": 8000, "status": None, "body": ""}
    assert GATE.verdict(["u"], [8000], [REFUSING], [dead])["liveness_masking_readiness"] == []


def test_a_healthy_and_ready_port_is_not_masked() -> None:
    live_ok = {"port": 8030, "status": 200, "body": '{"status":"ok"}'}
    assert GATE.verdict(["u"], [8030], [OK], [live_ok])["liveness_masking_readiness"] == []


def test_without_a_liveness_probe_the_field_claims_nothing() -> None:
    """Відсутність другої проби не сміє читатись як «маскування немає»: це різні стани,
    і поле мовчить лише тому, що його нічим наповнити."""
    assert GATE.verdict(["u"], [8000], [REFUSING])["liveness_masking_readiness"] == []
    assert GATE.verdict(["u"], [8000], [REFUSING])["status"] == "FAIL"
