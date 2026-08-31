"""Цитата, у якої відрізали початок речення, читається як інша норма.

Спан — це шматок джерела фіксованого розміру, не речення. На корпусі, який
обслуговується, 32 820 із 38 863 спанів (84,5 %) починаються посеред речення
(виміряно 31.08.2026). Найдорожчий випадок із тих, що відтворені: межа спана
розрізала слово «За|лишається», і речення

    «Воєнний об'єкт залишається таким навіть у тому випадку, якщо на ньому
     знаходяться цивільні особи»

показувалось читачеві як

    «лишається таким навіть у тому випадку, якщо на ньому знаходяться цивільні особи»

— без підмета, під зеленим вироком, у відповідь на «коли дозволяється відкривати
вогонь по цивільній особі». Речення обмежує; уривок читається як дозвіл.

Тому два правила, і обидва тут атаковані:
  * повне речення виграє в уривка серед тих, що вже пройшли поріг покриття;
  * якщо показати можна лише уривок, читач про це дізнається з відповіді.
"""

from __future__ import annotations

from korpus.application.evidence import segment_sentences, starts_mid_sentence


def test_a_passage_that_begins_after_a_sentence_started_is_named_as_such() -> None:
    assert starts_mid_sentence("лишається таким навіть у тому випадку")
    assert starts_mid_sentence("ня рани\nЗупинка вузлової кровотечі")


def test_a_whole_sentence_is_not_called_a_fragment() -> None:
    assert not starts_mid_sentence("Воєнні об'єкти вважаються законними цілями для нападу.")
    assert not starts_mid_sentence("До основних обмежувальних правил відноситься:")


def test_a_clause_that_opens_with_a_number_is_not_guessed_at() -> None:
    """«16.» не каже, де почалося речення. Позначити його уривком означало б
    позначити половину нумерованого статуту, і мітка перестала б щось значити."""
    assert not starts_mid_sentence("16.")
    assert not starts_mid_sentence("2) забезпечення особового складу")


def test_an_empty_passage_is_treated_as_a_fragment() -> None:
    """Порожнє не є цілим. UNKNOWN не є PASS."""
    assert starts_mid_sentence("")
    assert starts_mid_sentence("   \n ")


def test_the_rule_reads_the_first_letter_that_carries_case() -> None:
    """Провідні лапки й дужки не є початком речення і не є його відсутністю."""
    assert not starts_mid_sentence('"Буг" по цілі А78')
    assert starts_mid_sentence("(лишається таким)")


def test_segmentation_of_a_headless_span_yields_a_headless_first_sentence() -> None:
    """Негативний контроль на саму сегментацію: вона НЕ лікує обрізок, лише ділить.

    Якби вона його лікувала, правило вище було б зайвим — і цей тест почервонів би,
    попередивши, що охорона більше не охороняє того, заради чого написана.
    """
    text = "лишається таким навіть у тому випадку. Наступне речення ціле."
    sentences = segment_sentences(text)

    assert len(sentences) == 2
    assert starts_mid_sentence(sentences[0][0])
    assert not starts_mid_sentence(sentences[1][0])


# ── Поведінка, а не лише детектор: що саме показують читачеві.

from datetime import date  # noqa: E402

from fastapi.testclient import TestClient  # noqa: E402
from korpus.application.answer_query import AnswerPolicy, ExtractiveAnswerService  # noqa: E402
from korpus.domain.models import Identity, QueryRequest, RetrievedEvidence  # noqa: E402

from apps.api.tests.helpers import approve, ingest_text  # noqa: E402

QUESTION = "коли дозволяється відкривати вогонь по цивільній особі"
HEADLESS = "лишається таким навіть коли дозволяється відкривати вогонь по цивільній особі."
WHOLE = "Заборонено відкривати вогонь по цивільній особі."


def _answer(client: TestClient, identity: Identity, text: str) -> object:
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
            minimum_query_coverage=0.1,
            minimum_support_score=0.05,
            calibration_id="citation-fragment-test",
        ),
    )
    return service.execute(identity, QueryRequest(text=QUESTION))


def test_a_whole_sentence_outranks_a_fragment_that_matches_more_of_the_question(
    client: TestClient, admin_identity: Identity
) -> None:
    """Покриття питання каже, скільки слів збіглося. Воно не каже, чи вціліла думка.

    Уривок тут збігається з питанням СЛОВО В СЛОВО, а ціле речення — частково, і
    все одно виграє: читач має бачити норму, а не її хвіст.
    """
    answer = _answer(client, admin_identity, f"{HEADLESS} {WHOLE}")

    assert answer.citations, "нічого не показано"
    assert answer.citations[0].quote == WHOLE
    assert answer.citations[0].quote_starts_mid_sentence is False


def test_when_only_a_fragment_can_be_shown_the_reader_is_told(
    client: TestClient, admin_identity: Identity
) -> None:
    """Негативний контроль до попереднього: правило не мовчить і не викидає доказ.

    Якби воно просто відкидало уривки, система втратила б відповідь там, де інших
    речень у спані немає — а це 84,5 % спанів корпусу.
    """
    answer = _answer(client, admin_identity, HEADLESS)

    assert answer.citations, "уривок відкинуто замість позначити — відповідь зникла"
    assert answer.citations[0].quote == HEADLESS
    assert answer.citations[0].quote_starts_mid_sentence is True
