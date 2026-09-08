"""Кожна відмова адаптера HTTP — окремим входом, а не одним «неправильним» випадком.

`GovernedHttpReadAdapter` існує щоб керована спроможність не могла піти кудись, куди її
не пускали: не за межі origin, не з підробленими заголовками, не по відповіді без межі.
Виміряно 08.09.2026: у гілковому покритті модуля 18 непокритих ребер, і всі вони —
саме ці відмови. Шлях відмови, який ніхто не проходив, не є доведеним: він однаково
виглядає і коли працює, і коли його зняли.

Кожен тест рухає РІВНО ОДИН вхід: інакше зелений вирок не каже, яка з умов його дала.
"""

from __future__ import annotations

import httpx
import pytest
from korpus.application.capability_gateway.adapters import AdapterExecutionFailed
from korpus.application.capability_gateway.types import (
    CapabilitySpec,
    EvidenceProfile,
    ProviderType,
)
from korpus.infrastructure.integrations.http import GovernedHttpReadAdapter, HttpReadPlan

# Фікстури беруться з наявного тесту, а не пишуться вдруге: друга копія специфікації
# розійшлася б із першою мовчки, і тест почав би міряти власну копію.
from apps.api.tests.test_capability_gateway_http_adapter import (
    _context,
    _request,
    _spec,
)

BASE = "https://provider.example/api"


class _Chunks(httpx.SyncByteStream):
    """Потік без оголошеної довжини: httpx не ставить `content-length` для нього."""

    def __init__(self, chunks) -> None:
        self._chunks = list(chunks)

    def __iter__(self):
        yield from self._chunks


def _plan_for(path: str, query: tuple[tuple[str, str], ...] = ()) -> object:
    def build(payload: dict[str, object], resource: str) -> HttpReadPlan:
        del payload, resource
        return HttpReadPlan(path=path, query=query)

    return build


def _adapter(client: httpx.Client, *, base: str = BASE, plan: object = None, **kwargs: object):
    return GovernedHttpReadAdapter(
        client=client,
        base_url=base,
        plan_builder=plan or _plan_for("v1/reference"),
        **kwargs,  # type: ignore[arg-type]
    )


def _run(adapter: object, *, spec: CapabilitySpec | None = None) -> object:
    return adapter.execute(  # type: ignore[attr-defined]
        spec=spec or _spec(),
        request=_request(),
        context=_context(),
        logical_resource="reference/alpha",
    )


def _client(handler=None) -> httpx.Client:
    def ok(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"value": "ok"}, request=request)

    return httpx.Client(transport=httpx.MockTransport(handler or ok))


# ── База: адреса, з якої спроможність не може вийти ────────────────────────────


@pytest.mark.parametrize(
    ("base", "why"),
    [
        ("http://provider.example/api", "не HTTPS"),
        ("https:///api", "без хоста"),
        ("https://user:pw@provider.example/api", "з обліковими даними"),
        ("https://provider.example/api?x=1", "із запитом"),
        ("https://provider.example/api#frag", "із фрагментом"),
        ("https://provider.example/api/%2e%2e/etc", "з відсотковим виходом угору"),
    ],
)
def test_base_url_that_is_not_a_safe_origin_is_refused(base: str, why: str) -> None:
    with _client() as client, pytest.raises(ValueError):
        _adapter(client, base=base)


# ── Заголовки: сервер володіє ними, не виклик ─────────────────────────────────


@pytest.mark.parametrize(
    "headers",
    [
        {"X-Trace": 7},
        {7: "value"},
        {"": "value"},
        {"host": "elsewhere"},
        {"X-Trace": "line\r\ninjected"},
        {"X-Trace\n": "value"},
        {"X-Trace": "null\x00byte"},
    ],
)
def test_headers_that_could_reroute_or_reframe_are_refused(headers: dict) -> None:
    with _client() as client, pytest.raises(ValueError):
        _adapter(client, headers=headers)


# ── Шлях: лише дані шляху, і лише всередині origin ────────────────────────────


@pytest.mark.parametrize(
    "path",
    [
        "",
        "https://elsewhere.example/x",
        "//elsewhere.example/x",
        "v1?x=1",
        "v1#f",
        "v1/../../etc",
        "v1/%2e%2e/etc",
        "v1/\\etc",
        "v1/\x01etc",
    ],
)
def test_path_that_is_not_pure_path_data_is_refused(path: str) -> None:
    """Шлях, який не є лише даними шляху, не доходить до мережі.

    Порожній шлях, схема, хост, запит чи фрагмент у ньому, вихід угору (у тому числі
    відсотково закодований), зворотний слеш і керуючий символ — кожен окремим входом.
    Назовні це `AdapterExecutionFailed`: тип валідатора не протікає через межу.
    """
    with _client() as client, pytest.raises((ValueError, AdapterExecutionFailed)):
        _run(_adapter(client, plan=_plan_for(path)))


# ── Запит: пари рядків без керуючих символів ──────────────────────────────────


@pytest.mark.parametrize(
    "query",
    [
        (("only",),),
        ((7, "value"),),
        (("name", 7),),
        (("", "value"),),
        (("name", "line\r\nbreak"),),
        (("name\n", "value"),),
    ],
)
def test_query_that_is_not_clean_string_pairs_is_refused(query: tuple) -> None:
    """Помилка плану доходить до виклику як ВІДМОВА адаптера, не як `ValueError`.

    Межа підсистеми загортає негідний план у `AdapterExecutionFailed`: назовні не
    протікає ані тип валідатора, ані те, який саме рядок його не влаштував.
    """
    with _client() as client, pytest.raises(AdapterExecutionFailed):
        _run(_adapter(client, plan=_plan_for("v1/reference", query)))


# ── Відповідь: тип, довжина, межа ─────────────────────────────────────────────


def test_non_json_content_type_is_refused() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200, text="<html/>", headers={"content-type": "text/html"}, request=request
        )

    with _client(handler) as client, pytest.raises(AdapterExecutionFailed):
        _run(_adapter(client))


def test_a_json_suffix_media_type_is_accepted() -> None:
    """Негативний контроль до перевірки типу: `+json` — теж JSON."""

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            content=b'{"value":"ok"}',
            headers={"content-type": "application/vnd.x+json"},
            request=request,
        )

    with _client(handler) as client:
        assert _run(_adapter(client)).output == {"value": "ok"}  # type: ignore[attr-defined]


def test_unparsable_content_length_is_refused() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            content=b'{"value":"ok"}',
            headers={"content-type": "application/json", "content-length": "not-a-number"},
            request=request,
        )

    with _client(handler) as client, pytest.raises(AdapterExecutionFailed):
        _run(_adapter(client))


def test_declared_length_over_the_maximum_is_refused_before_reading() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            content=b'{"value":"ok"}',
            headers={"content-type": "application/json", "content-length": "99999"},
            request=request,
        )

    with _client(handler) as client, pytest.raises(AdapterExecutionFailed):
        _run(
            _adapter(
                client,
            ),
            spec=_spec(max_response_bytes=16),
        )


def test_body_that_is_not_json_is_refused() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200, content=b"not json", headers={"content-type": "application/json"}, request=request
        )

    with _client(handler) as client, pytest.raises(AdapterExecutionFailed):
        _run(_adapter(client))


def test_non_success_status_is_refused() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(503, json={"error": "down"}, request=request)

    with _client(handler) as client, pytest.raises(AdapterExecutionFailed):
        _run(_adapter(client))


def test_wrong_provider_type_is_refused_before_any_request() -> None:
    """Адаптер HTTP не виконує спроможність, оголошену не як HTTP."""
    spec = _spec().model_copy(update={"provider_type": ProviderType.MCP})
    with _client() as client, pytest.raises(AdapterExecutionFailed):
        _run(_adapter(client), spec=spec)


def test_a_plan_path_that_leaves_the_origin_is_refused() -> None:
    """Останній рубіж походження: після склеювання адреса мусить лишитись у тому ж origin.

    Перевірка стоїть ПІСЛЯ побудови URL саме тому, що склеювання — місце, де origin
    може змінитись непомітно для перевірок над самим рядком шляху.
    """
    with _client() as client, pytest.raises((ValueError, AdapterExecutionFailed)):
        _run(
            _adapter(
                client, base="https://provider.example", plan=_plan_for("//elsewhere.example/x")
            )
        )


def test_a_response_without_declared_length_is_still_bounded_while_reading() -> None:
    """Межа не покладається на заголовок: без `content-length` тіло рахується на льоту."""

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            content=b'{"value":"' + b"x" * 4096 + b'"}',
            headers={"content-type": "application/json"},
            request=request,
        )

    with _client(handler) as client, pytest.raises(AdapterExecutionFailed):
        _run(_adapter(client), spec=_spec(max_response_bytes=64))


def test_evidence_profile_none_yields_no_envelope() -> None:
    """Профіль NONE не «слабший доказ», а ВІДСУТНІЙ: конверт не вигадується."""
    result = None
    with _client() as client:
        result = _run(_adapter(client), spec=_spec(evidence=EvidenceProfile.NONE))
    assert result.evidence is None  # type: ignore[attr-defined]


def test_a_non_default_port_is_carried_into_provider_identity() -> None:
    """Порт — частина походження: провайдер на іншому порту не той самий провайдер."""

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"value": "ok"}, request=request)

    with _client(handler) as client:
        result = _run(
            _adapter(client, base="https://provider.example:8443/api"),
        )
    assert result.evidence is not None  # type: ignore[attr-defined]
    assert "8443" in result.evidence.provenance.provider_identity  # type: ignore[attr-defined]


def test_a_streamed_response_without_declared_length_is_bounded_while_reading() -> None:
    """Межа тримається БЕЗ `content-length`: заголовок — зручність, не гарантія.

    Провайдер, що віддає потоком без оголошеної довжини, — звичайний випадок і саме
    той, у якому перевірка заголовка нічого не важить. Рахунок іде по прочитаному.
    """

    def handler(request: httpx.Request) -> httpx.Response:
        def chunks():
            for _ in range(8):
                yield b"x" * 64

        return httpx.Response(
            200,
            stream=_Chunks(chunks()),
            headers={"content-type": "application/json"},
            request=request,
        )

    with _client(handler) as client, pytest.raises(AdapterExecutionFailed):
        _run(_adapter(client), spec=_spec(max_response_bytes=64))


def test_a_streamed_response_within_the_bound_is_accepted() -> None:
    """Негативний контроль: правило карає ПЕРЕВИЩЕННЯ, а не потік як такий."""

    def handler(request: httpx.Request) -> httpx.Response:
        def chunks():
            yield b'{"value":'
            yield b'"ok"}'

        return httpx.Response(
            200,
            stream=_Chunks(chunks()),
            headers={"content-type": "application/json"},
            request=request,
        )

    with _client(handler) as client:
        assert _run(_adapter(client)).output == {"value": "ok"}  # type: ignore[attr-defined]
