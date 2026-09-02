"""Прапорець у коді не є прийняттям. Прийняття — рішення з причиною і датою.

ВИМІРЯНО 02.09.2026. Єдиний у дереві `usedforsecurity=False` стояв у
`liqpay._digest`, який кличе `sign_data`: прапорець казав «не для безпеки» про геш, що
рахує ПІДПИС платіжного колбека. Вбудований безпековий детектор через це мовчав саме
там, де мав спрацювати — бо приймав твердження від власного суб'єкта.

Це той самий клас, що «гейт, який читає власне оголошення»: суб'єкт перевірки заявляє
про себе те, чого перевірка не міряє, і перевірка вірить. Ліки — не заборона ужитку
(SHA-1 вимагає ЧУЖИЙ протокол LiqPay, і дефолт у коді `sha3_256`), а перенесення
рішення туди, де в нього є автор, причина й дата.

Реєстр озброєний трьома способами збрехати, і кожен доведено запуском:
  * знахідка без запису            -> FAIL
  * запис без причини або дати     -> FAIL (не є названим)
  * запис, що не збігається ні з чим -> FAIL як МЕРТВИЙ

Третій контроль спрацював на мені того ж дня: я змінив код, клас знахідки змінився з
`weak_security_hash_claimed_nonsecurity` на `weak_security_hash`, і гейт негайно
оголосив запис мертвим. Реєстр не сміє переживати причину, заради якої існує.
"""

from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
REGISTRY = ROOT / "config/operations/security-acceptances.json"
# Гейт живе в `scripts/` і імпортує сусідів звідти ж; без цього рядка збірка тесту
# падає на `release_identity`, а не на предметі перевірки.
if str(ROOT / "scripts") not in sys.path:
    sys.path.insert(0, str(ROOT / "scripts"))
_SPEC = importlib.util.spec_from_file_location(
    "builtin_security", ROOT / "scripts/run_builtin_security_gate.py"
)
assert _SPEC and _SPEC.loader
gate = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(gate)

_FINDING = {"rule": "weak_security_hash", "path": "a/b.py", "line": 1, "detail": "hashlib.sha1"}


def _registry(tmp: Path, entries: list[dict]) -> Path:
    (tmp / "config/operations").mkdir(parents=True, exist_ok=True)
    (tmp / "config/operations/security-acceptances.json").write_text(
        json.dumps({"schema": "korpus.security-acceptances.v1", "accepted": entries}),
        encoding="utf-8",
    )
    return tmp


def test_a_named_acceptance_removes_the_finding(tmp_path: Path):
    root = _registry(
        tmp_path,
        [
            {
                "rule": "weak_security_hash",
                "path": "a/b.py",
                "reason": "чужий протокол",
                "on": "2026-09-02",
            }
        ],
    )
    remaining, dead = gate._apply_acceptances(root, [dict(_FINDING)])
    assert remaining == [] and dead == []


def test_an_acceptance_without_a_reason_is_not_an_acceptance(tmp_path: Path):
    root = _registry(
        tmp_path, [{"rule": "weak_security_hash", "path": "a/b.py", "on": "2026-09-02"}]
    )
    remaining, _ = gate._apply_acceptances(root, [dict(_FINDING)])
    assert remaining, "запис без причини зняв знахідку — прийняття стало прапорцем"


def test_an_acceptance_without_a_date_is_not_an_acceptance(tmp_path: Path):
    root = _registry(tmp_path, [{"rule": "weak_security_hash", "path": "a/b.py", "reason": "бо"}])
    remaining, _ = gate._apply_acceptances(root, [dict(_FINDING)])
    assert remaining, "запис без дати зняв знахідку"


def test_an_acceptance_that_matches_nothing_is_reported_dead(tmp_path: Path):
    root = _registry(
        tmp_path,
        [
            {
                "rule": "weak_security_hash",
                "path": "gone/away.py",
                "reason": "стара",
                "on": "2026-01-01",
            }
        ],
    )
    _, dead = gate._apply_acceptances(root, [])
    assert dead, "мертвий запис не помічено — реєстр переживе причину, заради якої існує"


def test_the_escape_hatch_does_not_excuse_a_signature():
    """Негативний контроль на саме правило, а не на реєстр."""
    import ast

    call = ast.parse("hashlib.sha1(v, usedforsecurity=False)").body[0].value
    assert gate._dangerous_rule(call, "sign_data") == "weak_security_hash_claimed_nonsecurity"
    assert gate._dangerous_rule(call, "cache_key_for_filename") is None


def test_the_tree_registry_is_well_formed_and_alive():
    payload = json.loads(REGISTRY.read_text(encoding="utf-8"))
    for entry in payload["accepted"]:
        assert entry.get("reason") and entry.get("on") and entry.get("rule") and entry.get("path")
        assert len(entry["reason"]) >= 40, "причина коротша за речення не є причиною"
    _, dead = gate._apply_acceptances(ROOT, gate._ast_findings(ROOT) + gate._secret_findings(ROOT))
    assert not dead, f"у дереві є мертві прийняття: {dead}"
