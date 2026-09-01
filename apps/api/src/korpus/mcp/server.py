"""Три інструменти, і жоден із них не виробляє факту.

Агент має LLM; факти має корпус. Межа між ними тут не в промті, а в тому, що
інструмент фізично не має чим вигадати: він повертає рівно те, що віддав API,
плюс ОДНЕ похідне число — запас над порогом, який той самий API оголосив.

Чому запас, а не вирок. Виміряно 01.09.2026 на живому розгортанні: питання «Яка
столиця Бразилії?» дістало `answered` із `query_coverage` рівно 0.5 — на самій
межі, — тоді як своє питання дало 1.0. Вісь `boundary_foreign` тримає підлогу
0.75, тобто чужі питання впускаються ЗА ПОБУДОВОЮ. Ставити тут ДРУГИЙ, суворіший
поріг означало б завести другу тотожність «своє питання» й розійтися з першою
мовчки. Тому інструмент не судить — він показує відстань до межі, і судить агент.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from korpus.mcp.transport import KorpusApi, TransportFailure


class ToolFailure(RuntimeError):
    """Інструмент не зміг відповісти. Відрізняється від «корпус не має підстав»."""


#: Скільки цитат віддавати агентові за раз. Не налаштування: більше — це вже не
#: «покажи підставу», а «віддай корпус», і агент почне переказувати замість цитувати.
MAX_CITATIONS = 8


def _margin(answer: dict[str, Any], admission: dict[str, Any]) -> dict[str, Any]:
    """Відстань до межі — єдине, що цей шар рахує сам."""
    out: dict[str, Any] = {}
    for measured, declared in (
        ("query_coverage", "min_query_coverage"),
        ("retrieval_score", "min_retrieval_score"),
    ):
        value, floor = answer.get(measured), admission.get(declared)
        if isinstance(value, int | float) and isinstance(floor, int | float):
            out[measured] = {
                "value": round(float(value), 4),
                "floor": float(floor),
                "margin": round(float(value) - float(floor), 4),
                "at_floor": abs(float(value) - float(floor)) < 1e-9,
            }
    return out


def _citation(record: dict[str, Any]) -> dict[str, Any]:
    """Цитата віддається З ХЕШАМИ: без них агент не має чим її перевірити."""
    return {
        "quote": record.get("quote"),
        "title": record.get("title"),
        "source_uri": record.get("source_uri"),
        "page": record.get("page"),
        "section": record.get("section"),
        "span_id": record.get("span_id"),
        "quote_hash": record.get("quote_hash"),
        "span_hash": record.get("span_hash"),
        "source_hash": record.get("source_hash"),
        "starts_mid_sentence": record.get("quote_starts_mid_sentence"),
        "adjudication_reason": record.get("adjudication_reason"),
    }


@dataclass
class KorpusMcpServer:
    api: KorpusApi

    def _admission(self) -> dict[str, Any]:
        bootstrap = self.api.bootstrap()
        admission = bootstrap.get("admission")
        if not isinstance(admission, dict):
            # Порогів немає ⇒ запас не рахується. Порахувати його з власної
            # константи означало б завести друге оголошення межі.
            raise ToolFailure("korpus api does not publish its admission thresholds")
        return admission

    def ask(self, question: str, as_of: str | None = None) -> dict[str, Any]:
        if not isinstance(question, str) or not question.strip():
            raise ToolFailure("question must be a non-empty string")
        admission = self._admission()
        answer = self.api.ask(question.strip(), as_of)
        citations = answer.get("citations") or []
        return {
            "status": answer.get("status"),
            "decision_reason": answer.get("decision_reason"),
            "text": answer.get("text"),
            "citations": [_citation(item) for item in citations[:MAX_CITATIONS]],
            "citation_count": len(citations),
            "corpus_release": answer.get("corpus_release"),
            "admission": _margin(answer, admission),
            "limitations": answer.get("limitations"),
            "calibration_id": answer.get("calibration_id"),
            # Названо явно, бо це головне, чого агент не сміє забути.
            "contract": (
                "Кожне речення в `text` — дослівна цитата з корпусу. Інструмент не "
                "додає фактів. `admission.*.at_floor` істинне означає, що відповідь "
                "пройшла РІВНО по межі: на чужих питаннях це типовий стан."
            ),
        }

    def quote(self, span_id: str) -> dict[str, Any]:
        if not isinstance(span_id, str) or not span_id.strip():
            raise ToolFailure("span_id must be a non-empty string")
        span = self.api.span(span_id.strip())
        return {
            "span_id": span.get("id"),
            "text": span.get("text"),
            "text_hash": span.get("text_hash"),
            "source_hash": span.get("source_hash"),
            "source_uri": span.get("source_uri"),
            "document_title": span.get("document_title"),
            "page": span.get("page"),
            "section": span.get("section"),
            "revision": span.get("revision"),
            "publication_date": span.get("publication_date"),
            "effective_from": span.get("effective_from"),
            "effective_until": span.get("effective_until"),
            "rescinded_at": span.get("rescinded_at"),
            "authority": span.get("authority"),
        }

    def grounds(self, question: str, as_of: str | None = None) -> dict[str, Any]:
        """Чи МАЄ корпус підставу — без тексту відповіді.

        Окремий інструмент, а не прапорець: агент, який спершу питає підставу,
        не платить за складання відповіді там, де її не буде, і не спокушається
        переказати текст, який дістав «просто подивитись».
        """
        answer = self.ask(question, as_of)
        return {
            "has_grounds": answer["status"] == "answered",
            "status": answer["status"],
            "decision_reason": answer["decision_reason"],
            "citation_count": answer["citation_count"],
            "sources": sorted({item["title"] for item in answer["citations"] if item.get("title")}),
            "admission": answer["admission"],
            "corpus_release": answer["corpus_release"],
        }


def build_tools(server: KorpusMcpServer) -> list[dict[str, Any]]:
    """Оголошення інструментів для `tools/list`."""
    return [
        {
            "name": "korpus_ask",
            "description": (
                "Спитати КОРПУС. Повертає дослівні цитати з хешами, ідентифікатор "
                "релізу корпусу й ЗАПАС над порогом допуску. Жодного слова понад "
                "цитоване не додається."
            ),
            "inputSchema": {
                "type": "object",
                "properties": {
                    "question": {"type": "string", "description": "Питання українською."},
                    "as_of": {
                        "type": "string",
                        "description": "Дата ISO: стан корпусу на цю дату.",
                    },
                },
                "required": ["question"],
            },
        },
        {
            "name": "korpus_grounds",
            "description": (
                "Чи має корпус підставу на це питання — без тексту відповіді. "
                "Дешевша перевірка перед тим, як витрачати відповідь."
            ),
            "inputSchema": {
                "type": "object",
                "properties": {
                    "question": {"type": "string"},
                    "as_of": {"type": "string"},
                },
                "required": ["question"],
            },
        },
        {
            "name": "korpus_quote",
            "description": (
                "Перевірити конкретну цитату: віддає проліт із хешем тексту, хешем "
                "джерела, чинністю й відкликанням. Тим самим агент може довести, що "
                "цитата не вигадана."
            ),
            "inputSchema": {
                "type": "object",
                "properties": {"span_id": {"type": "string"}},
                "required": ["span_id"],
            },
        },
    ]


def call_tool(server: KorpusMcpServer, name: str, arguments: dict[str, Any]) -> dict[str, Any]:
    if name == "korpus_ask":
        return server.ask(arguments.get("question", ""), arguments.get("as_of"))
    if name == "korpus_grounds":
        return server.grounds(arguments.get("question", ""), arguments.get("as_of"))
    if name == "korpus_quote":
        return server.quote(arguments.get("span_id", ""))
    raise ToolFailure(f"unknown tool: {name}")


__all__ = [
    "MAX_CITATIONS",
    "KorpusMcpServer",
    "ToolFailure",
    "TransportFailure",
    "build_tools",
    "call_tool",
]
