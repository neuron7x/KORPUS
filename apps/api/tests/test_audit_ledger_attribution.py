"""Журнал доказів був цілим і незасвідченим одночасно, і ніщо не кричало.

Виміряно 31.08.2026 на базі, яку обслуговують: 7223 події, нуль розривів зчеплення, голова
збігається з останньою подією — і при цьому **жодна подія не засвідчена**. Усі підписані
одним із двох рядків, що лежать у цьому ж репозиторії: `replace-local-audit-key`
(`config.py`) і `local-audit-key` (`serve_public.sh`). Обидва сегменти записані як
`legacy-unversioned`, тож жодна каблучка не перевіряла журнал далі 1025-ї події.

`make audit-verify` існував із самого початку, був червоний, до `validate` не підключений і
читав `./var/korpus.db` — порожню базу розробника з нуля подій.

Тому тут перевіряється саме те, що зливалось в одне «audit hash mismatch»: подія, підписана
НЕ тим ключем, який називає, — це інша річ, ніж подія, чий вміст не збігається з підписом, і
ще інша — ніж подія, для якої ключа просто не дали.
"""

from __future__ import annotations

import hashlib
import hmac
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / "scripts"))

from attribute_audit_keys import attribute  # noqa: E402
from measure_audit_integrity import assess, canonical_of  # noqa: E402
from reissue_audit_anchor import preflight  # noqa: E402

RIGHT = b"k" * 40
WRONG = b"j" * 40
ZERO = "0" * 64


def _event(sequence: int, key: bytes, names: str, *, previous: str = ZERO) -> dict[str, Any]:
    row: dict[str, Any] = {
        "sequence": sequence,
        "event_id": f"e{sequence}",
        "occurred_at": "2026-08-31T00:00:00+00:00",
        "actor_subject": "a",
        "action": "x",
        "resource_type": "r",
        "resource_id": None,
        "payload_json": "{}",
        "previous_hash": previous,
        "audit_key_id": names,
    }
    row["event_hash"] = hmac.new(key, canonical_of(row), hashlib.sha256).hexdigest()
    return row


def test_an_event_signed_by_the_key_it_names_is_the_only_thing_credited() -> None:
    report = assess([_event(1, RIGHT, "a")], {"a": RIGHT})

    assert report["attributed"] == 1
    assert report["rate"] == 1.0


def test_an_event_signed_by_another_held_key_is_misattributed_not_broken() -> None:
    """Саме цей клас робив журнал неперевірюваним, і саме він лікується ярликом."""
    report = assess([_event(1, WRONG, "a")], {"a": RIGHT, "b": WRONG})

    assert report["misattributed"] == 1
    assert report["unverifiable"] == 0
    assert report["rate"] == 0.0


def test_an_event_no_offered_key_verifies_is_unverifiable_not_forgery() -> None:
    """Вимір не сміє називати підробкою те, що може бути просто ненаданим ключем."""
    report = assess([_event(1, WRONG, "a")], {"a": RIGHT})

    assert report["unverifiable"] == 1
    assert report["misattributed"] == 0


def test_changing_the_payload_breaks_the_signature() -> None:
    """Негативний контроль на сам підпис: якби він не залежав від вмісту, все марно."""
    tampered = _event(1, RIGHT, "a")
    tampered["payload_json"] = '{"changed": 1}'

    assert assess([tampered], {"a": RIGHT})["unverifiable"] == 1


def test_a_break_in_the_forward_chain_is_reported() -> None:
    first = _event(1, RIGHT, "a")
    detached = _event(2, RIGHT, "a", previous="f" * 64)

    assert assess([first, detached], {"a": RIGHT})["linkage_breaks"] == [2]


def test_the_label_is_not_part_of_what_is_signed() -> None:
    """Твердження, на якому тримається вся атрибуція: ярлик не рухає хешів.

    Якби `audit_key_id` входив у канонічну форму, виправлення ярлика переписало б журнал —
    і це вже не було б виправленням.
    """
    row = _event(1, RIGHT, "a")
    before = canonical_of(row)
    row["audit_key_id"] = "інший-ід"

    assert canonical_of(row) == before


def test_a_wrong_label_is_corrected_and_a_right_one_is_left_alone() -> None:
    plan, refusals = attribute(
        [_event(1, WRONG, "legacy-unversioned")], {"legacy-unversioned": RIGHT, "b": WRONG}
    )

    assert plan == [("b", 1)]
    assert refusals == []
    assert attribute([_event(1, RIGHT, "a")], {"a": RIGHT}) == ([], [])


def test_an_unverifiable_event_stops_the_whole_relabelling() -> None:
    """Fail-closed: позначити ключем журнал, який не перевірився цілим, — це видати
    «ключа не дали» за «все гаразд»."""
    plan, refusals = attribute([_event(1, WRONG, "a")], {"a": RIGHT})

    assert plan == []
    assert len(refusals) == 1


def test_two_keys_verifying_one_event_is_a_refusal_not_a_choice() -> None:
    plan, refusals = attribute([_event(1, RIGHT, "a")], {"a": RIGHT, "copy": RIGHT})

    assert plan == []
    assert refusals


def test_the_anchor_is_only_reissued_over_a_ledger_that_verifies_whole() -> None:
    whole = {
        "unverifiable": 0,
        "misattributed": 0,
        "linkage_breaks": [],
        "sequence_gaps": [],
        "head_matches_last_event": True,
    }

    assert preflight(whole, 1024, 7223) == []
    assert preflight({**whole, "unverifiable": 1}, 1024, 7223)
    assert preflight({**whole, "head_matches_last_event": False}, 1024, 7223)
    # Якір рухається лише вперед: інакше перевипуск став би способом відкотити доказ.
    assert preflight(whole, 8000, 7223)
