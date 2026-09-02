"""КОРПУС як інструмент агента: LLM міркує, факт бере лише звідси.

Межа тут не в промті. Промт — це прохання, а інструмент, який фізично не має чим
вигадати, — це відповідь. Тому головні перевірки нижче негативні: інструмент не
породжує тексту, якого не було у відповіді API, і не перетворює транспортну
відмову на «корпус не має підстав».

Друге, чого не було б без виміру. 01.09.2026 на живому розгортанні питання «Яка
столиця Бразилії?» дістало `answered` із `query_coverage` РІВНО 0.5 — на самій
межі допуску, — тоді як своє питання дало 1.0. Вісь `boundary_foreign` тримає
підлогу 0.75, тобто чужі питання впускаються за побудовою. Агент, який читає лише
`status`, цього не побачить; тому інструмент віддає ЗАПАС над порогом, і `at_floor`
на такій відповіді істинне.
"""

from __future__ import annotations

import json
from typing import Any

import pytest
from korpus.mcp.server import KorpusMcpServer, ToolFailure, build_tools, call_tool
from korpus.mcp.stdio import PROTOCOL_VERSION, handle
from korpus.mcp.transport import TransportFailure

ADMISSION = {
    "min_retrieval_score": 0.18,
    "min_query_coverage": 0.5,
    "min_support_score": 0.18,
}
ON_DOMAIN = {
    "status": "answered",
    "decision_reason": "extractive_claims_passed_calibrated_gates",
    "text": "знати завдання варти",
    "query_coverage": 1.0,
    "retrieval_score": 0.6463,
    "corpus_release": "a" * 64,
    "calibration_id": "development-unvalidated",
    "limitations": ["Відповідь екстрактивна."],
    "citations": [
        {
            "quote": "знати завдання варти",
            "title": "Обов'язки: Начальник варти",
            "span_id": "span-1",
            "quote_hash": "b" * 64,
            "span_hash": "c" * 64,
            "source_hash": "d" * 64,
            "source_uri": "https://zakon.rada.gov.ua/laws/show/550-14/print",
            "quote_starts_mid_sentence": True,
            "adjudication_reason": "уривок починається не з початку речення",
        }
    ],
}
OFF_DOMAIN = {
    **ON_DOMAIN,
    "text": "их об'єднань громадян",
    "query_coverage": 0.5,
    "retrieval_score": 0.3202,
    "citations": [{**ON_DOMAIN["citations"][0], "title": "Конституція України, ст.2"}],
}


class _Api:
    """Подвійник API. Він і є межею: інструмент бачить рівно те, що тут написано."""

    def __init__(self, answer: dict[str, Any] | None = None, **overrides: Any) -> None:
        self.answer = answer if answer is not None else ON_DOMAIN
        self.admission: Any = overrides.get("admission", ADMISSION)
        self.raises = overrides.get("raises")
        self.span_record = overrides.get("span", {"id": "span-1", "text": "джерело"})
        self.asked: list[str] = []

    def bootstrap(self) -> dict[str, Any]:
        return {"admission": self.admission} if self.admission is not None else {}

    def ask(self, question: str, as_of: str | None = None) -> dict[str, Any]:
        if self.raises is not None:
            raise self.raises
        self.asked.append(question)
        return self.answer

    def span(self, span_id: str) -> dict[str, Any]:
        if self.raises is not None:
            raise self.raises
        return self.span_record


def _server(**kwargs: Any) -> KorpusMcpServer:
    return KorpusMcpServer(api=_Api(**kwargs))


def test_the_tool_returns_no_sentence_the_api_did_not_return() -> None:
    """Головне. Усе, що агент прочитає як факт, мусить бути в відповіді API."""
    result = _server().ask("Які обов'язки начальника варти?")

    assert result["text"] == ON_DOMAIN["text"]
    for citation in result["citations"]:
        assert citation["quote"] in {item["quote"] for item in ON_DOMAIN["citations"]}
    rendered = json.dumps(result, ensure_ascii=False)
    assert "знати завдання варти" in rendered
    # Нічого, чого не було у відповіді: перелік ключів фіксований, і новий ключ
    # тут — це нове твердження, яке хтось мусить обґрунтувати.
    assert set(result) == {
        "status",
        "decision_reason",
        "text",
        "citations",
        "citation_count",
        "corpus_release",
        "admission",
        "limitations",
        "calibration_id",
        "contract",
    }


def test_every_citation_carries_what_makes_it_checkable() -> None:
    citation = _server().ask("питання")["citations"][0]

    for field in ("quote_hash", "span_hash", "source_hash", "span_id", "source_uri"):
        assert citation[field], field


def test_an_answer_at_the_threshold_is_marked_as_such() -> None:
    """Чуже питання проходить РІВНО по межі — і агент мусить це бачити."""
    off = _server(answer=OFF_DOMAIN).ask("Яка столиця Бразилії?")
    on = _server(answer=ON_DOMAIN).ask("Які обов'язки начальника варти?")

    assert off["status"] == on["status"] == "answered", "status їх не розрізняє"
    assert off["admission"]["query_coverage"]["at_floor"] is True
    assert off["admission"]["query_coverage"]["margin"] == 0.0
    assert on["admission"]["query_coverage"]["at_floor"] is False
    assert on["admission"]["query_coverage"]["margin"] == 0.5


def test_the_margin_is_computed_from_the_servers_own_thresholds() -> None:
    """Друга константа тут завела б другу тотожність «своє питання»."""
    strict = _server(answer=OFF_DOMAIN, admission={**ADMISSION, "min_query_coverage": 0.4})

    assert strict.ask("питання")["admission"]["query_coverage"]["margin"] == 0.1


def test_without_published_thresholds_the_tool_refuses_instead_of_guessing() -> None:
    with pytest.raises(ToolFailure, match="admission thresholds"):
        _server(admission=None).ask("питання")


def test_a_transport_failure_is_not_reported_as_absent_grounds() -> None:
    """Найтихіша підміна: агент запише у висновок відсутність, якої не міряли."""
    server = _server(raises=TransportFailure("korpus api unreachable", retryable=True))
    response = handle(
        server,
        {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "tools/call",
            "params": {"name": "korpus_ask", "arguments": {"question": "питання"}},
        },
    )

    assert response is not None
    assert response["result"]["isError"] is True
    body = json.loads(response["result"]["content"][0]["text"])
    assert body["retryable"] is True
    assert "unreachable" in body["error"]


def test_grounds_answers_the_cheap_question_without_the_text() -> None:
    grounds = _server().grounds("Які обов'язки начальника варти?")

    assert grounds["has_grounds"] is True
    assert "text" not in grounds
    assert grounds["sources"] == ["Обов'язки: Начальник варти"]


def test_an_empty_question_is_refused_before_it_reaches_the_corpus() -> None:
    api = _Api()
    server = KorpusMcpServer(api=api)

    for empty in ("", "   ", None):
        with pytest.raises(ToolFailure):
            server.ask(empty)  # type: ignore[arg-type]
    assert api.asked == []


def test_the_handshake_names_the_protocol_and_every_tool() -> None:
    server = _server()
    initialize = handle(server, {"jsonrpc": "2.0", "id": 1, "method": "initialize"})
    listed = handle(server, {"jsonrpc": "2.0", "id": 2, "method": "tools/list"})

    assert initialize is not None and listed is not None
    assert initialize["result"]["protocolVersion"] == PROTOCOL_VERSION
    assert {tool["name"] for tool in listed["result"]["tools"]} == {
        "korpus_ask",
        "korpus_grounds",
        "korpus_verify",
        "korpus_quote",
    }


def test_a_notification_gets_no_answer_and_an_unknown_method_gets_an_error() -> None:
    server = _server()

    assert handle(server, {"jsonrpc": "2.0", "method": "notifications/initialized"}) is None
    unknown = handle(server, {"jsonrpc": "2.0", "id": 9, "method": "нема/такого"})
    assert unknown is not None and unknown["error"]["code"] == -32601


def test_an_unknown_tool_is_named_not_silently_empty() -> None:
    with pytest.raises(ToolFailure, match="unknown tool"):
        call_tool(_server(), "korpus_вигадка", {})


def test_every_declared_tool_is_callable() -> None:
    """Дуал до попереднього: оголошення без реалізації — теж тиха відсутність."""
    server = _server(span={"id": "span-1", "text": "джерело", "text_hash": "e" * 64})
    for tool in build_tools(server):
        arguments: dict[str, Any] = {"question": "питання"}
        if tool["name"] == "korpus_quote":
            arguments = {"span_id": "span-1"}
        elif tool["name"] == "korpus_verify":
            arguments = {"draft": "знати завдання варти.", "quotes": ["знати завдання варти"]}
        assert call_tool(server, tool["name"], arguments)


def test_a_token_that_cannot_be_a_jwt_is_refused_before_any_call() -> None:
    """Виміряно на власній помилці: не-ASCII токен клав ВЕСЬ сервер.

    `UnicodeEncodeError` виникав при складанні заголовка — поза всіма гілками
    обробки транспорту, — тож агент не діставав відмови, він втрачав з'єднання.
    Перевірка тут, а не при першому виклику: інакше кожен інструмент падав би
    окремо, а причина «заголовок не кодується latin-1» не назвала б, що сталось.
    """
    from korpus.mcp.transport import KorpusApi

    with pytest.raises(ValueError, match="must be ASCII"):
        KorpusApi(base_url="http://127.0.0.1:8000", token="битий.токен.тут")
    with pytest.raises(ValueError, match="empty"):
        KorpusApi(base_url="http://127.0.0.1:8000", token="   ")
    # Дуал: звичайний токен мусить прийматись, інакше перевірка боронить від усього.
    assert KorpusApi(base_url="http://127.0.0.1:8000", token="aaa.bbb.ccc").token


def test_no_http_layer_exception_can_kill_the_serving_loop() -> None:
    """Перелік винятків HTTP-шару не вичерпний, і саме на цьому сервер і помер.

    Названа відмова гірша за влучний перелік винятків рівно нічим; неназвана
    смерть — гірша за все, бо агент лишається без причини й без з'єднання.
    """
    from korpus.mcp.transport import KorpusApi, TransportFailure

    api = KorpusApi(base_url="http://127.0.0.1:9", token="aaa.bbb.ccc")

    class _Exploding(dict):
        def __getitem__(self, key: object) -> object:
            raise RuntimeError("щось геть несподіване")

    with pytest.raises(TransportFailure) as raised:
        api._request("POST", "/v1/answers", _Exploding())
    assert raised.value.retryable in {True, False}


def test_verification_needs_no_database_no_audit_and_no_identity() -> None:
    """Чиста функція над текстом: агент передає СВОЮ чернетку й ті цитати, що вже має.

    Тому подвійник API тут — той, що на будь-який виклик кидає: якщо перевірка
    його торкнеться, тест почервоніє. Читати корпус тут нема чого, і саме це
    робить інструмент безпечним для довільно частого виклику.
    """
    server = _server(raises=TransportFailure("не сміє торкатись", retryable=True))

    result = server.verify(
        "Дистанція між машинами менше 30 метрів.",
        ["Дистанція між машинами не менше 30 метрів."],
    )

    assert result["supported"] is False
    assert result["unsupported_count"] == 1
    assert "знято заперечення" in result["sentences"][0]["reason"]


def test_verification_refuses_a_joined_string_instead_of_a_list_of_quotes() -> None:
    """Склеєний рядок — та сама спільна калюжа слів під іншим ім'ям."""
    with pytest.raises(ToolFailure, match="quotes"):
        _server().verify("чернетка", "одна склеєна цитата")  # type: ignore[arg-type]
    with pytest.raises(ToolFailure, match="quotes"):
        _server().verify("чернетка", [])
    with pytest.raises(ToolFailure, match="draft"):
        _server().verify("   ", ["цитата"])
