"""Реліз називає версії, з яких відповідь могла бути складена, і коштує один запит.

`corpus_release_id` читав повну проєкцію прольотів і будував модель прольоту, документа
й версії на кожен рядок. На імпортованому корпусі — 116 229 прольотів над 1616
версіями — це 232 458 конструювань Pydantic на питання: 6.9 с із 17 с відповіді, тоді
як пошук, який він штампує, має бюджет 1200 мс. У самій відповіді не було нічого
хибного; вона просто тривала настільки довго, що системою не можна було користуватись.

Далі виявилось гірше, і саме тому цей файл переписано. Дайджест брав ЧОТИРИ поля на
версію й обрізався до 16 шістнадцяткових знаків, а журнал засвідчував ту саму
відповідь ІНШОЮ тотожністю — дайджестом знімка з дев'ятнадцяти полів, повної довжини.
Два стани корпусу, що різнились лише грифом, відкликанням чи відсіками, діставали
ОДНАКОВИЙ старий ідентифікатор. Відповідь називала реліз, який уже не описував того,
що читач бачив, і жодне поле цих двох випадків не розрізняло.

Тепер тотожність одна: `CorpusReadToken.release_id`. Кожна властивість, яку боронив
старий набір, лишається виміряною тут — бо зникнення перевірки разом із кодом, який
вона перевіряла, і є тим способом, яким мовчки гине інваріант.
"""

from __future__ import annotations

from datetime import date, timedelta

from fastapi.testclient import TestClient
from korpus.application.corpus_snapshot import release_identity_digest
from korpus.domain.models import AccessTier, Identity

from apps.api.tests.helpers import approve, ingest_text

READER = Identity(
    subject="reader",
    roles=frozenset({"user"}),
    clearance=AccessTier.PUBLIC,
    corpora=frozenset({"public"}),
)


def _release(client: TestClient, as_of: date, identity: Identity = READER) -> str:
    reader = client.app.state.corpus_snapshot_reader
    corpora = identity.corpora
    token = reader.capture(identity, frozenset(corpora), as_of)
    release: str = token.release_id
    return release


def _versions_in_span_projection(client: TestClient, as_of: date) -> set[str]:
    """Правило членства, записане незалежно від того, як рахується дайджест."""
    repository = client.app.state.repository
    rows = repository.list_retrievable_spans(READER, frozenset({"public"}), as_of)
    return {str(version.id) for _, _document, version in rows}


def _versions_in_release(client: TestClient, as_of: date) -> set[str]:
    reader = client.app.state.corpus_snapshot_reader
    repository = client.app.state.repository
    from korpus.infrastructure import retrieval_queries
    from korpus.infrastructure.semantic_release import semantic_release_members

    with repository.engine.begin() as connection:
        statement = retrieval_queries.release_projection(READER, frozenset({"public"}), as_of)
        rows = list(connection.execute(statement).mappings().all())
        visible = [row for row in rows if retrieval_queries.release_row_is_current(row, as_of)]
        members = semantic_release_members(connection, visible)
    assert reader is not None
    return {member.version_id for member in members}


def test_the_release_names_exactly_the_versions_an_answer_could_cite(
    client: TestClient,
) -> None:
    """Найважливіший тест: членство релізу = членство пошукової проєкції.

    Дайджест може рахуватись як завгодно; хибним його робить не арифметика, а
    НАБІР версій. Тому набір звіряється з правилом, записаним окремо.
    """
    for index in range(3):
        result = ingest_text(
            client,
            title=f"Наказ {index}",
            text=f"Підрозділ веде журнал {index}. Кожен запис має дату та відповідальну особу.",
        )
        approve(client, result["version"]["id"])
    as_of = date.today()

    assert _versions_in_release(client, as_of) == _versions_in_span_projection(client, as_of)


def test_a_version_that_changes_changes_the_release_id(client: TestClient) -> None:
    """Негативний контроль: дайджест, який ніколи не рухається, не ідентифікує нічого."""
    as_of = date.today()
    before = _release(client, as_of)

    result = ingest_text(client, title="Новий наказ", text="Новий порядок обліку майна.")
    approve(client, result["version"]["id"])

    assert _release(client, as_of) != before


def test_a_quarantined_version_is_not_in_the_release(client: TestClient) -> None:
    """Членство — це «чи могла відповідь це процитувати», а не «чи є воно в базі»."""
    as_of = date.today()
    before = _release(client, as_of)

    ingest_text(client, title="Непереглянутий", text="Текст, який ніхто не затверджував.")

    assert _release(client, as_of) == before


def test_a_corpus_the_reader_cannot_reach_yields_the_empty_digest(
    client: TestClient,
) -> None:
    outsider = Identity(
        subject="outsider",
        roles=frozenset({"user"}),
        clearance=AccessTier.PUBLIC,
        corpora=frozenset({"other"}),
    )

    assert _release(client, date.today(), outsider) == release_identity_digest([])


def test_a_version_not_yet_in_force_is_not_in_the_release(client: TestClient) -> None:
    """Реліз називає те, що можна процитувати *на запитану дату*, а не те, що існує.

    Правило чинності раніше діставалось безкоштовно: старий шлях будував модель версії
    на кожен проліт і кликав `is_valid_on`. Рахунок дайджесту з проєкції означає, що
    те саме питання ставиться ЯВНО, а забути його — покласти завтрашній наказ у
    сьогоднішній відбиток.
    """
    as_of = date.today()
    before = _release(client, as_of)

    result = ingest_text(
        client,
        title="Наказ, що набирає сили пізніше",
        text="Порядок, який починає діяти наступного місяця.",
        publication_date=None,
        effective_from=as_of + timedelta(days=30),
    )
    approve(client, result["version"]["id"])

    assert _release(client, as_of) == before, (
        "версія, яка сьогодні нічим не керує, увійшла в сьогоднішній реліз"
    )
    assert _release(client, as_of + timedelta(days=31)) != before, (
        "і вона мусить увійти в реліз на дату, якою вона керує"
    )


def test_the_release_binds_state_the_old_four_field_digest_could_not_see(
    client: TestClient,
) -> None:
    """Причина заміни, виміряна: відкликання рухає реліз, а старі чотири поля — ні.

    Старий дайджест брав `document_id`, `version_id`, `source_hash`, `review_state`.
    Відкликання не змінює жодного з них — версія лишається затвердженою, з тим самим
    вмістом. Тобто корпус, у якому наказ уже відкликано, і корпус, у якому він чинний,
    мали ОДИН ідентифікатор релізу.
    """
    result = ingest_text(
        client,
        title="Наказ, який буде відкликано",
        text="Порядок, що діє до окремого розпорядження про його скасування.",
    )
    version_id = result["version"]["id"]
    approve(client, version_id)
    as_of = date.today()
    before = _release(client, as_of)

    response = client.post(
        f"/v1/document-versions/{version_id}/rescission",
        json={"note": "withdrawn by issuing authority to measure release sensitivity"},
    )
    assert response.status_code == 200, response.text

    assert _release(client, as_of) != before
