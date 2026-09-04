"""Цикл читання MCP по stdio: дев'ять гілок без жодного прогону.

Вимір покриття гілок 04.09.2026. Це поверхня, через яку в систему заходить чужий
процес, і жодна її гілка не виконувалась: порожній рядок, зіпсований JSON,
сповіщення без відповіді, кінець потоку. Транспорт, чиї межі не перевірені, — це
місце, де падіння виглядає як мовчання.

Сервер тут не потрібен: усі перевірені шляхи закінчуються ДО звернення до нього.
Предмет виміру — сам цикл, а не інструменти під ним.
"""

from __future__ import annotations

import io
import json

from korpus.mcp.stdio import handle, serve


class _NeverCalledServer:
    """Якщо цикл сюди звернеться, тест бреше про те, що міряє."""

    def __getattr__(self, name: str) -> object:
        raise AssertionError(f"цикл не мав торкатись сервера, а звернувся до {name!r}")


def _run(lines: str, **kwargs: object) -> list[dict[str, object]]:
    sink = io.StringIO()
    serve(_NeverCalledServer(), io.StringIO(lines), sink, **kwargs)  # type: ignore[arg-type]
    return [json.loads(line) for line in sink.getvalue().splitlines() if line]


def test_an_empty_stream_produces_no_output_and_returns() -> None:
    """Кінець потоку — звичайне завершення, не помилка: клієнт від'єднався."""
    assert _run("") == []


def test_blank_lines_are_skipped_without_a_parse_error() -> None:
    """Порожній рядок не є повідомленням.

    Відповісти на нього «parse error» означало б звинуватити клієнта в тому, чого
    він не робив, і засмітити канал відповідями на ніщо.
    """
    assert _run("\n   \n\t\n") == []


def test_malformed_json_gets_a_parse_error_and_the_loop_continues() -> None:
    """Одне зіпсоване повідомлення не завершує сеанс.

    Обрив тут виглядав би для клієнта як мовчазна смерть сервера, хоча зіпсований
    був лише один рядок.
    """
    responses = _run('це не json\n{"jsonrpc":"2.0","id":7,"method":"немає"}\n')
    assert len(responses) == 2
    assert responses[0]["error"]["code"] == -32700  # type: ignore[index]
    assert responses[0]["id"] is None
    assert responses[1]["id"] == 7
    assert responses[1]["error"]["code"] == -32601  # type: ignore[index]


def test_a_notification_for_an_unknown_method_is_answered_with_silence() -> None:
    """Сповіщення не має `id`, тож відповідати НІКОМУ.

    JSON-RPC забороняє відповідь на сповіщення: відповідь без `id` клієнт не зміг
    би зіставити з запитом і мусив би її відкинути або впасти.
    """
    assert _run('{"jsonrpc":"2.0","method":"немає"}\n') == []
    assert handle(_NeverCalledServer(), {"method": "немає"}) is None  # type: ignore[arg-type]


def test_a_request_for_an_unknown_method_is_answered_with_method_not_found() -> None:
    """Негативне плече: запит із `id` мусить дістати відповідь, а не мовчання."""
    responses = _run('{"jsonrpc":"2.0","id":1,"method":"немає"}\n')
    assert responses[0]["id"] == 1
    assert responses[0]["error"]["code"] == -32601  # type: ignore[index]


def test_the_line_observer_sees_every_non_blank_line_before_it_is_parsed() -> None:
    """Спостерігач бачить рядок ДО розбору — інакше зіпсовані входи були б невидимі.

    Саме вони й потрібні в журналі: справні повідомлення видно з відповідей.
    """
    seen: list[str] = []
    _run('\n це не json \n{"jsonrpc":"2.0","method":"немає"}\n', on_line=seen.append)
    assert seen == ["це не json", '{"jsonrpc":"2.0","method":"немає"}']


def test_the_loop_runs_without_an_observer() -> None:
    """Негативне плече: спостерігач необов'язковий, і його відсутність не гілка з помилкою."""
    assert _run('{"jsonrpc":"2.0","id":2,"method":"немає"}\n')[0]["id"] == 2
