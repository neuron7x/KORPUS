"""Чверть питання — це одне слово з чотирьох, і цього достатньо для зеленого вироку.

Виміряно 31.08.2026 на 40 питаннях через живий публічний edge: 20 із корпусу і 20
свідомо поза ним (гаманець Ethereum, віза до Кореї, рецепт борщу, Kubernetes ingress).
При типовому порозі 0.25 система відповідала на **17 із 20 чужих** під вироком
«ПІДСТАВА Є» і `evidence_coverage 1.0`. «Як налаштувати гаманець Ethereum для донатів»
отримувало обов'язки техніка БпАК — дослівно правдиву цитату, покладену під питання,
на яке вона не відповідає.

Розподіли максимального покриття claim'а розділяються:

    у корпусі     0.25 0.5 0.5 0.5 0.67 0.67 0.67 0.75 0.75 1.0 ×10
    поза корпусом 0.25 ×8  0.33 ×4  0.4  0.5 ×3  0.75

Поріг 0.5 лишає 18 із 20 своїх і прибирає 13 із 17 чужих. На замороженому еталоні
дерева він же дає 93/95 проти 89/95 і supported_answer_rate 0.886 проти 0.861 —
покращення зібране з відмов, не з правильних відповідей. Ціна названа: answer_yield
0.937 → 0.911, тобто один із двадцяти своїх втрачений.
"""

from __future__ import annotations

from datetime import date

from fastapi.testclient import TestClient
from korpus.application.answer_query import AnswerPolicy, ExtractiveAnswerService
from korpus.config import Settings
from korpus.domain.models import Identity, QueryRequest, RetrievedEvidence

from apps.api.tests.helpers import approve, ingest_text

QUESTION = "як накласти турнікет пораненому"
WEAK = "Турнікет зберігається у складі медичного майна підрозділу."
STRONG = "Турнікет накласти пораненому вище рани."


def test_the_shipped_threshold_is_half_the_question() -> None:
    """Число живе в одному місці, і воно тут назване, щоб зміна була видимою."""
    assert Settings(environment="local").min_query_coverage == 0.5


def _answer(client: TestClient, identity: Identity, text: str, coverage: float) -> object:
    result = ingest_text(client, text=text)
    approve(client, result["version"]["id"])
    rows = client.app.state.repository.list_retrievable_spans(
        client.identity_provider.current, frozenset({"public"}), date.today()
    )
    span, document, version = rows[0]
    evidence = RetrievedEvidence(
        span=span, document=document, version=version, score=0.95, query_coverage=1.0
    )

    class _Retriever:
        def search(
            self,
            _identity: Identity,
            _text: str,
            _corpus_ids: frozenset[str],
            _as_of: date,
            limit: int = 8,
        ) -> list[RetrievedEvidence]:
            return [evidence]

    service = ExtractiveAnswerService(
        client.app.state.repository,
        _Retriever(),
        client.app.state.policy,
        AnswerPolicy(
            minimum_score=0.05,
            minimum_query_coverage=coverage,
            minimum_support_score=0.05,
            calibration_id="coverage-threshold-test",
        ),
    )
    return service.execute(identity, QueryRequest(text=QUESTION))


def test_a_sentence_that_shares_one_word_with_the_question_is_not_an_answer(
    client: TestClient, admin_identity: Identity
) -> None:
    """«Турнікет зберігається у складі майна» правдиве і не відповідає на «як накласти»."""
    answer = _answer(client, admin_identity, WEAK, coverage=0.5)

    assert answer.status.value != "answered", (
        "речення, що збігається з питанням одним словом, показано як підставу"
    )
    assert not answer.citations


def test_the_same_sentence_did_pass_at_the_old_threshold(
    client: TestClient, admin_identity: Identity
) -> None:
    """Негативний контроль: доводить, що поріг — причина, а не збіг.

    Без нього тест вище був би зеленим і від зовсім іншої відмови — наприклад від
    порогу підтримки чи від того, що речення взагалі не дійшло.
    """
    answer = _answer(client, admin_identity, WEAK, coverage=0.25)

    assert answer.status.value == "answered"
    assert answer.citations


def test_a_sentence_that_answers_the_question_still_passes(
    client: TestClient, admin_identity: Identity
) -> None:
    """Поріг, що не пропускає нічого, — це не суворість, а поломка."""
    answer = _answer(client, admin_identity, STRONG, coverage=0.5)

    assert answer.status.value == "answered"
    assert answer.citations[0].quote == STRONG
