"""Обстановка сторінки не є текстом документа.

Вимір 2026-08-30 на 163 захоплених текстах: питання «Яка ставка податку на
прибуток підприємств у 2019 році?» — свідомо поза доменом — мало покриття 0.500
при порозі відмови 0.25 і не відхилялось. Найкращим реченням корпусу для нього
був `<title>` сторінки zakon.rada.gov.ua, зчеплений із написами на кнопках
панелі. Прибирання обстановки опустило стелю поза доменом 0.500 → 0.250, не
змінивши ЖОДНОГО з семи питань у домені.

Кожне позитивне твердження тут має негативний контроль: перевірка, яка викидає
все, виглядала б найсуворішою, тому нижче доведено і те, що зміст залишається.
"""

from __future__ import annotations

from korpus.infrastructure.extraction import NON_DOCUMENT_ELEMENTS, _strip_html

_PAGE = """<!DOCTYPE html>
<html lang="uk">
<head><title>Про грошове забезпечення | від 30.08.2017 № 704 (Текст для друку)</title></head>
<body>
  <nav>Картка Файли Історія Зв'язки Публікації</nav>
  <span>Шрифт:
    <button id="increase">+<span>збільшити</span></button>
    <button id="decrease">−<span>зменшити</span></button>
  </span>
  <select name="lang"><option>Укр</option><option>Eng</option></select>
  <aside>Альтернативний контекстний пошук</aside>
  <p>Установити з 1 січня 2018 року розміри посадових окладів військовослужбовців.</p>
</body></html>"""


def test_page_furniture_is_not_document_text():
    text = _strip_html(_PAGE)
    for furniture in (
        "Текст для друку",
        "збільшити",
        "зменшити",
        "Картка Файли",
        "Альтернативний контекстний пошук",
        "Укр",
        "Eng",
    ):
        assert furniture not in text, furniture


def test_the_document_itself_survives_the_same_pass():
    text = _strip_html(_PAGE)
    assert "розміри посадових окладів військовослужбовців" in text
    assert "1 січня 2018 року" in text


def test_the_rule_is_structural_and_not_a_word_list():
    """Ті самі слова у ТІЛІ документа лишаються: правило про елемент, не про текст."""
    body = "<html><body><p>Копію рішення надіслати для друку та оприлюднення.</p></body></html>"
    assert "для друку" in _strip_html(body)
    quoted = "<html><body><p>Кнопку «збільшити» розміщено праворуч.</p></body></html>"
    assert "збільшити" in _strip_html(quoted)


def test_unclosed_option_cannot_swallow_the_document():
    """`option` навмисно поза набором: його часто не закривають.

    Якби він рахувався глибиною, перший же незакритий `<option>` зробив би
    порожнім увесь подальший документ, і це не відрізнялось би від сторінки без
    тексту.
    """
    assert "option" not in NON_DOCUMENT_ELEMENTS
    markup = "<html><body><option>Укр<option>Eng<p>Стаття 1. Загальні положення.</p></body></html>"
    assert "Стаття 1. Загальні положення." in _strip_html(markup)


def test_unclosed_title_keeps_the_document_and_pays_with_noise():
    """Незакритий `<title>` НЕ сміє зробити сторінку порожньою.

    `HTMLParser` віддає все після нього одним шматком даних заголовка, тож
    ігнорування коштувало б усього документа. Обмін названий вголос: шум
    залишається, документ залишається теж.
    """
    markup = "<html><head><title>Заголовок<body><p>Стаття 2. Сфера дії.</p></body></html>"
    assert "Стаття 2. Сфера дії." in _strip_html(markup)


def test_a_closed_title_is_still_dropped():
    """Негативний контроль до попереднього: поступка діє лише на зламаній розмітці."""
    markup = "<html><head><title>Заголовок</title></head><body><p>Стаття 2.</p></body></html>"
    text = _strip_html(markup)
    assert "Заголовок" not in text
    assert "Стаття 2." in text


def test_scripts_and_styles_are_still_dropped():
    """Старе покриття не зникло разом із розширенням набору."""
    markup = (
        "<html><body><script>var contlen = 400;</script>"
        "<style>.btn{color:red}</style><p>Стаття 3. Терміни.</p></body></html>"
    )
    text = _strip_html(markup)
    assert "contlen" not in text
    assert "color:red" not in text
    assert "Стаття 3. Терміни." in text


def test_double_encoded_markup_does_not_survive_as_document_text() -> None:
    """Джерело віддає розмітку, вже екрановану один раз, і один `unescape` її лишає.

    Виміряно 31.08.2026 на рантайм-корпусі: 55 із 38 863 ЦИТОВНИХ прольотів несли
    залишок `&lt;p>` або `&#34;`, і один із них — у Стройовому статуті ЗСУ. Тобто на
    питання солдата система могла віддати уламок розмітки як доказ, із тим самим
    хешем і тим самим виглядом достовірності, що й стаття статуту.

    Розкодувати «до стабільності» не можна: після другого `unescape` в тексті
    опиняються справжні теги. Тому другий шар ПЕРЕПАРСЮЄТЬСЯ — і `NON_DOCUMENT_ELEMENTS`
    діє на нього так само, як на перший.
    """
    doubly_encoded = (
        "<p>&amp;lt;a href=&amp;#34;#&amp;#34;&amp;gt;Reset password&amp;lt;/a&amp;gt;"
        " Наказ набирає чинності з дня опублікування.</p>"
    )
    text = _strip_html(doubly_encoded)
    assert "&lt;" not in text
    assert "&#34;" not in text
    assert "href=" not in text
    assert "Наказ набирає чинності з дня опублікування." in text


def test_single_encoded_entity_in_real_sentence_is_decoded_not_dropped() -> None:
    """Негативний контроль: сутність у справжньому реченні — не сміття, а символ.

    Правило, що прибирає розмітку, не сміє прибирати текст. `&#8230;` у звіті Центру
    протидії дезінформації — це три крапки, і речення мусить лишитись цілим.
    """
    text = _strip_html("<p>Звіти Центру протидії дезінформації&amp;#8230; за 2026 рік.</p>")
    assert "Звіти Центру протидії дезінформації" in text
    assert "за 2026 рік." in text
    assert "&#" not in text


def test_ordinary_page_is_not_reparsed_into_nothing() -> None:
    """Сторінка без подвійного кодування проходить рівно один розбір і не змінюється."""
    text = _strip_html("<p>Командир бригади відповідає за бойову готовність.</p>")
    assert "Командир бригади відповідає за бойову готовність." in text
