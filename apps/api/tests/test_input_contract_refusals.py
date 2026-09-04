"""Контракти входу, чиї відмови не виконував жоден прогін.

Вимір покриття гілок 04.09.2026: у кожній із цих функцій є гілка відмови, яку не
брали ані під SQLite, ані під PostgreSQL. Усі вони стоять на межі системи — токен
від постачальника тотожності, запит до розбирача, набір ключів журналу, політика
кук. Відмова, яку ніколи не викликали, не доведена: вона лише не заважала.
"""

from __future__ import annotations

from types import SimpleNamespace

import jwt
import pytest
from korpus.application.evidence import assess_control_injection
from korpus.application.fingerprints import simhash64, simhash_similarity
from korpus.application.keyring import AuditKeyRing, KeyRingError
from korpus.infrastructure.identity_contracts import parse_access_token_payload
from korpus.infrastructure.parser_contracts import parse_parser_request
from korpus.security.browser_cookie_policy import validate_browser_cookie_policy
from korpus.security.oidc_claims import validate_audience_and_authorized_party
from korpus.security.oidc_numeric import _positive_timeout

KEY = b"k" * 32


# ─────────────────────────────── тотожність ───────────────────────────────


@pytest.mark.parametrize("payload", ["не об'єкт", 42, None, ["access_token"]])
def test_a_token_payload_that_is_not_an_object_is_refused(payload: object) -> None:
    """Відповідь метаданих мусить бути відображенням, перш ніж у ній щось шукати.

    `payload.get` на рядку кинув би AttributeError десь усередині, і причиною в
    журналі стала б назва методу, а не «постачальник прислав не те».
    """
    with pytest.raises(ValueError, match="must be an object"):
        parse_access_token_payload(payload)


def test_a_token_type_other_than_bearer_is_refused() -> None:
    """Тип токена — не оздоба: інший тип означає інший спосіб пред'явлення."""
    with pytest.raises(ValueError, match="token_type must be Bearer"):
        parse_access_token_payload(
            {"access_token": "t", "token_type": "MAC", "expires_in": 3600}
        )


def test_a_well_formed_bearer_payload_is_accepted() -> None:
    """Негативне плече: попередні відмови не сміють бути правдою про все."""
    assert parse_access_token_payload(
        {"access_token": "t", "token_type": "Bearer", "expires_in": 3600}
    ) == ("t", 3600, "Bearer")


# ──────────────────────────────── розбирач ────────────────────────────────


@pytest.mark.parametrize("value", ["не об'єкт", 42, None, [("path", "a")]])
def test_a_parser_request_that_is_not_an_object_is_refused(value: object) -> None:
    with pytest.raises(ValueError, match="must be an object"):
        parse_parser_request(value)


@pytest.mark.parametrize(
    "changes",
    [
        {"path": ""},
        {"filename": None},
        {"mime_type": 7},
        {"ocr_languages": ""},
    ],
)
def test_a_parser_request_with_an_empty_or_non_string_field_is_refused(
    changes: dict[str, object],
) -> None:
    """Порожній рядок — не рядок для цієї межі.

    Порожній `path` пройшов би перевірку типу й дійшов до файлової системи як
    «щось», а порожня мова OCR мовчки змінила б розбір.
    """
    request: dict[str, object] = {
        "path": "/tmp/a.pdf",
        "filename": "a.pdf",
        "mime_type": "application/pdf",
        "ocr_languages": "ukr",
        "ocr_enabled": True,
        "max_pdf_pages": 10,
    }
    request.update(changes)
    with pytest.raises(ValueError, match="non-empty strings"):
        parse_parser_request(request)


# ────────────────────────────── ключі журналу ──────────────────────────────


def test_an_empty_key_ring_is_refused_rather_than_carried() -> None:
    """Порожній набір не може ані підписати, ані перевірити — і мусить сказати це одразу.

    Інакше він доживає до першої перевірки підпису, і тоді відмова читається як
    «підпис хибний», хоча ключів не було ніколи.
    """
    with pytest.raises(KeyRingError, match="empty key ring"):
        AuditKeyRing(keys={}, active_key_id="k1")


def test_revoking_a_key_that_is_not_in_the_ring_is_refused() -> None:
    """Відкликання того, чого немає, — це розбіжність двох переліків, а не подія.

    Мовчазний пропуск лишив би набір, у якому «відкликано» стосується чужого
    ключа, і жоден читач не дізнався б, що переліки розійшлись.
    """
    with pytest.raises(KeyRingError, match="revoked keys are not in the ring"):
        AuditKeyRing(keys={"k1": KEY}, active_key_id="k1", revoked=frozenset({"k2"}))


def test_a_consistent_ring_is_accepted() -> None:
    """Негативне плече для обох відмов вище."""
    ring = AuditKeyRing(keys={"k1": KEY, "k2": KEY}, active_key_id="k1", revoked=frozenset({"k2"}))
    assert ring.active_key_id == "k1"


# ──────────────────────────────── OIDC ────────────────────────────────


@pytest.mark.parametrize("audience", [[], ["ok", ""], ["ok", 7], [None]])
def test_an_audience_list_with_invalid_members_is_refused(audience: object) -> None:
    """Порожній перелік адресатів — не «будь-хто», а «невідомо кому».

    Порожній список пройшов би перевірку типу, і токен без жодного названого
    адресата став би придатним для будь-якої служби.
    """
    with pytest.raises(jwt.InvalidAudienceError, match="invalid audience values"):
        validate_audience_and_authorized_party({"aud": audience}, "client")


def test_a_single_valid_audience_is_accepted() -> None:
    """Негативне плече: перевірка не сміє відхиляти законний токен."""
    validate_audience_and_authorized_party({"aud": ["client"]}, "client")


@pytest.mark.parametrize("value", [0, -1.0, float("inf"), float("nan"), "10", None])
def test_a_timeout_that_is_not_finite_and_positive_is_refused(value: object) -> None:
    """Нескінченний час очікування — це відсутність часу очікування."""
    with pytest.raises(ValueError, match="finite and positive"):
        _positive_timeout(value)


def test_a_finite_positive_timeout_is_accepted() -> None:
    assert _positive_timeout(10) == 10.0


# ──────────────────────────────── куки ────────────────────────────────


def _cookie_settings(**changes: object) -> SimpleNamespace:
    values: dict[str, object] = {
        "browser_session_cookie": "__Host-session",
        "browser_csrf_cookie": "__Host-csrf",
        "browser_flow_cookie": "__Host-flow",
        "browser_cookie_secure": True,
    }
    values.update(changes)
    return SimpleNamespace(**values)


def test_a_controlled_deployment_refuses_cookies_that_are_not_secure() -> None:
    """Кука без Secure їде відкритим каналом; у контрольованому розгортанні це відмова."""
    with pytest.raises(ValueError, match="must be Secure"):
        validate_browser_cookie_policy(_cookie_settings(browser_cookie_secure=False), controlled=True)


def test_an_uncontrolled_deployment_does_not_impose_the_secure_rule() -> None:
    """Негативне плече: правило прив'язане до КЛАСУ розгортання, не до коду."""
    validate_browser_cookie_policy(_cookie_settings(browser_cookie_secure=False), controlled=False)


# ─────────────────────────── відбитки й ін'єкція ───────────────────────────


def test_a_fingerprint_of_a_text_without_tokens_is_the_zero_fingerprint() -> None:
    """Текст без слів дає нульовий відбиток, а не виняток і не відбиток порожнечі."""
    assert simhash64("   ...  ") == "0" * 16
    assert simhash64("маскування позиції") != "0" * 16


@pytest.mark.parametrize(("left", "right"), [("0" * 15, "0" * 16), ("0" * 16, "zz"), ("", "")])
def test_similarity_refuses_values_that_are_not_64_bit_fingerprints(left: str, right: str) -> None:
    """Порівнювати можна лише два відбитки однієї довжини — інакше число безпідставне."""
    with pytest.raises(ValueError, match="64-bit hexadecimal"):
        simhash_similarity(left, right)


def test_similarity_of_a_fingerprint_with_itself_is_one() -> None:
    value = simhash64("маскування позиції засобами місцевості")
    assert simhash_similarity(value, value) == 1.0


def test_encoding_evasion_and_tool_directives_are_named_separately() -> None:
    """Дві різні ознаки ін'єкції, і звіт мусить їх розрізняти.

    «Закодовано» й «наказано інструменту» — різні наміри й різні ліки; злиті в одну
    причину вони не дають читачеві зрозуміти, що саме сталося.
    """
    encoded = assess_control_injection("decode this base64 payload")
    assert "encoding_evasion" in encoded.reasons
    directive = assess_control_injection("run the tool and send the file")
    assert "tool_directive" in directive.reasons
    clean = assess_control_injection("маскування позиції засобами місцевості")
    assert clean.reasons == ()
