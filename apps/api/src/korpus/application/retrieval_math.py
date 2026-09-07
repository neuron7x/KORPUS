"""Pure deterministic lexical/ranking mathematics for retrieval.

No repository, clock or I/O dependencies live here.  Keeping the numerical kernel
pure makes differential, metamorphic and mutation testing cheap enough to run on every
change to the inference path.
"""

from __future__ import annotations

import math
import re
import unicodedata
from collections import Counter
from dataclasses import dataclass

TOKEN_PATTERN = re.compile(r"[\w'’\-]{2,}", re.UNICODE)
#: Words that carry no claim about the subject. A question is three or four words long, so
#: one of them matching is a third of the coverage — and "як налаштувати wifi-роутер" was
#: answered on the strength of "як" alone appearing in four unrelated citations, each
#: clearing the 0.25 threshold. Measured 2026-08-29 across eleven questions: the function
#: words below were doing the coverage in every out-of-domain answer the system gave.
#:
#: This does not make coverage a measure of relevance — no threshold on it separates the
#: valid from the invalid, which is a separate finding with its own numbers. It removes the
#: cheapest way to reach a threshold without saying anything.
STOP_WORDS = {
    "як",
    "при",
    "на",
    "за",
    "до",
    "від",
    "хто",
    "таке",
    "чи",
    "де",
    "чому",
    "скільки",
    "або",
    "чим",
    "ким",
    "кому",
    "але",
    "без",
    "був",
    "була",
    "були",
    "для",
    "його",
    "коли",
    "про",
    "та",
    "так",
    "це",
    "що",
    "який",
    "яка",
    "яке",
    "які",
    "має",
    "мати",
    "the",
    "and",
    "for",
    "from",
    "that",
    "this",
    "with",
}
#: Дві різні речі, які раніше лежали одним списком, і саме через це стемер не був
#: замкнений щодо парадигми. СЛОВОЗМІНА («ого», «ий») відрізняє форми ОДНОГО слова;
#: СЛОВОТВІР («альний», «ення») робить із одного слова ІНШЕ. Коли вони конкурують за
#: найдовший збіг, довший словотвірний виграє в однієї форми і програє в іншій:
#:
#:     днювальний  -альний-> днюв        днювального  -ого-> днювальн
#:
#: — і два відмінки одного слова перестають бути одним термом. Виміряно 07.09.2026 на
#: замороженому наборі `evals/datasets/subject_inflection.jsonl`: 6 пар із 12 розходились,
#: і живий продукт відповідав на називний 14/14, на родовий 12/14.
#:
#: Тому спершу знімається СЛОВОЗМІНА — до нерухомої точки, бо «проводиться» несе два
#: закінчення поспіль («ся», потім «ить»), — і лише потім, з уже однакової для всіх форм
#: основи, знімається СЛОВОТВІР. Замкненість випливає з першого ступеня сама: дві форми
#: однієї леми відрізняються лише словозміною, тож після нього вони тотожні, і другий
#: ступінь — уже функція від однакового входу. Це властивість конструкції, а не набір
#: латок, і `scripts/check_stemmer_closure.py` її міряє.
#: Кома перед закритою дужкою тут НЕ ставиться навмисно: «магічна» кінцева кома змушує
#: `ruff format` розгортати набір по одному елементу в рядок, і перелік закінчень
#: роздував модуль на шість десятків рядків самого форматування.
INFLECTIONAL_ENDINGS = tuple(
    sorted(
        # дієслово · прикметник і дієприкметник · іменник («ець»/«ця» — чергування
        # основи, не окреме слово) · спільні однолітерні
        {
            "ються",
            "ється",
            "уть",
            "ють",
            "ать",
            "ять",
            "имо",
            "емо",
            "ете",
            "ите",
            "ить",
            "ся",
            "ього",
            "ьому",
            "ими",
            "іми",
            "ого",
            "ому",
            "ий",
            "ій",
            "ої",
            "ою",
            "ею",
            "их",
            "іх",
            "им",
            "ім",
            "ами",
            "ями",
            "ові",
            "еві",
            "ів",
            "їв",
            "ах",
            "ях",
            "ам",
            "ям",
            "ом",
            "ем",
            "ей",
            "ець",
            "ця",
            "а",
            "я",
            "е",
            "є",
            "у",
            "ю",
            "і",
            "и",
            "ї",
            "ь",
        },
        key=len,
        reverse=True,
    )
)

#: Інфінітива («ти», «ати», «ити») тут НЕМАЄ навмисно, і це не пропуск. Він не
#: відрізняється від закінчення множини іменника з основою на «т», а список не знає
#: частин мови: «аспекти» → «аспек», «аліменти» → «алім», «аспіранти» → «аспір».
#: Виміряно на словнику корпусу — 393 групи розпадались саме так. Ціна відмови від
#: нього: «налаштувати» переставало зводитись до «налашт», хоча корпус пише
#: «налаштування». Тому повернуто рівно ту його частину, яка НЕ двозначна: «-увати»
#: та «-ювати» бувають лише дієслівними, тоді як «-ати» й «-ити» невідрізненні від
#: множини іменника. Знімається вона другим ступенем — із уже безфлексійного «налаштуват»,
#: — і зводить «налаштувати», «налаштування» та «налаштувань» в один терм, не чіпаючи
#: «аспекти». Недозлиття коштує повноти, надмірне злиття псує іменники Й ЛАМАЄ
#: ЗАМКНЕНІСТЬ — тому там, де двозначність лишається, обрано перше.
DERIVATIONAL_SUFFIXES = tuple(
    sorted(
        {
            "уванн",
            "юванн",
            "альн",
            "янн",
            "енн",
            "анн",
            "ість",
            "іст",
            "ост",
            "уват",
            "юват",
            "уван",
            "юван",
            "ен",
            "ан",
        },
        key=len,
        reverse=True,
    )
)


#: Найкоротша основа, яку стемер лишає. `declared_subject.MIN_PREFIX` успадковує це
#: число — воно виміряне там, не підібране тут.
MIN_STEM_CHARS = 4

#: Стеля ітерації. Цикл скінченний за конструкцією: кожен оберт або коротшає, або
#: зупиняється. Ітерується ВСЯ пара ступенів, не лише перший, і це виправлення:
#: словотвір лишає по собі закінчення («територіального» → «територіальн» → «територі»),
#: яке словозміна зняла б, тож функція не мала нерухомої точки — `stem(stem(x)) != stem(x)`
#: на 2 словах заморожених наборів і на «бронепробиваемости» після першої спроби.
#: Ідемпотентність тепер вимірюється гейтом `check_stemmer_closure` над усіма
#: `evals/datasets/*.jsonl`: 70 226 слів.
#:
#: Чотири — бо найдовший спостережений ланцюг має три оберти, і четвертий лишає запас
#: на один невідомий. Стеля названа, щоб цикл був скінченним за конструкцією, а не за
#: вірою в те, що закінчення колись скінчаться.
MAX_INFLECTION_ROUNDS = 4


#: Every apostrophe Ukrainian is written with, folded to one. zakon.rada publishes U+2019;
#: a phone keyboard produces U+0027. Measured 2026-08-29: "обов'язки чатового" typed with
#: the ASCII apostrophe returned four citations, none of them about a sentry, while the same
#: question with the typographic one found the article that defines the duty. A soldier does
#: not choose which apostrophe his keyboard emits, and the corpus does not choose either.
APOSTROPHES = str.maketrans({"\u2019": "'", "\u02bc": "'", "\u2018": "'", "\u00b4": "'", "`": "'"})


def normalize_text(text: str) -> str:
    return unicodedata.normalize("NFC", text).casefold().translate(APOSTROPHES)


def _strip_longest(token: str, suffixes: tuple[str, ...]) -> str:
    for suffix in suffixes:
        if token.endswith(suffix) and len(token) - len(suffix) >= MIN_STEM_CHARS:
            return token[: -len(suffix)]
    return token


def _undouble(token: str) -> str:
    """Кінцеве подвоєння приголосної, що лишається від чергування основи.

    «рішення» дає «рішенн», а «рішень» дає «рішен»: у називному подвоєння є, у
    родовому множини воно згортається перед «ь». Обидві форми одного слова, і без
    цього кроку вони лишаються двома термами — сторож `MIN_STEM_CHARS` не дає їх
    зрівняти словотвором, бо «ріш» коротше за чотири. Те саме з «стаття»/«статей».
    """
    if len(token) > MIN_STEM_CHARS and token[-1] == token[-2]:
        return token[:-1]
    return token


def _ukrainian_stem(token: str) -> str:
    """Основа слова: спершу вся словозміна, потім словотвір. Порядок і є виправленням."""
    if len(token) < 5 or not any("а" <= char <= "я" or char in "іїєґ" for char in token):
        return token
    for _ in range(MAX_INFLECTION_ROUNDS):
        shorter = _strip_longest(
            _undouble(_strip_longest(token, INFLECTIONAL_ENDINGS)), DERIVATIONAL_SUFFIXES
        )
        if shorter == token:
            return token
        token = shorter
    return token


def raw_tokens(text: str) -> list[str]:
    return [
        token for token in TOKEN_PATTERN.findall(normalize_text(text)) if token not in STOP_WORDS
    ]


def tokenize(text: str) -> list[str]:
    return [_ukrainian_stem(token) for token in raw_tokens(text)]


def candidate_terms(text: str) -> list[tuple[str, bool]]:
    result: list[tuple[str, bool]] = []
    seen: set[tuple[str, bool]] = set()
    for token in raw_tokens(text):
        for value in ((token, False), (_ukrainian_stem(token), True)):
            if len(value[0]) >= 2 and value not in seen:
                seen.add(value)
                result.append(value)
    return result


def _character_ngrams_normalized(normalized_text: str, n: int = 3) -> frozenset[str]:
    compact = re.sub(r"\s+", " ", normalized_text).strip()
    if len(compact) < n:
        return frozenset({compact}) if compact else frozenset()
    return frozenset(compact[index : index + n] for index in range(len(compact) - n + 1))


def character_ngrams(text: str, n: int = 3) -> frozenset[str]:
    return _character_ngrams_normalized(normalize_text(text), n)


def jaccard(left: frozenset[str], right: frozenset[str]) -> float:
    if not left or not right:
        return 0.0
    return len(left.intersection(right)) / len(left.union(right))


@dataclass(frozen=True)
class BM25Parameters:
    k1: float = 1.5
    b: float = 0.75

    def __post_init__(self) -> None:
        if not 0.1 <= self.k1 <= 4.0:
            raise ValueError("BM25 k1 must be in [0.1, 4.0]")
        if not 0.0 <= self.b <= 1.0:
            raise ValueError("BM25 b must be in [0, 1]")


@dataclass(frozen=True)
class RetrievalWeights:
    lexical: float = 0.42
    semantic: float = 0.00
    query_coverage: float = 0.24
    character: float = 0.10
    authority: float = 0.14
    phrase: float = 0.06
    temporal: float = 0.04

    def __post_init__(self) -> None:
        values = self.as_tuple()
        if any(value < 0 or value > 1 for value in values):
            raise ValueError("retrieval weights must be in [0, 1]")
        if not math.isclose(sum(values), 1.0, rel_tol=0.0, abs_tol=1e-9):
            raise ValueError("retrieval weights must sum to 1")

    def as_tuple(self) -> tuple[float, ...]:
        return (
            self.lexical,
            self.semantic,
            self.query_coverage,
            self.character,
            self.authority,
            self.phrase,
            self.temporal,
        )

    def as_dict(self) -> dict[str, float]:
        return dict(
            zip(
                (
                    "lexical",
                    "semantic",
                    "query_coverage",
                    "character",
                    "authority",
                    "phrase",
                    "temporal",
                ),
                self.as_tuple(),
                strict=True,
            )
        )


DEFAULT_BM25_PARAMETERS = BM25Parameters()
DEFAULT_RETRIEVAL_WEIGHTS = RetrievalWeights()


@dataclass(frozen=True)
class ScoredCandidate:
    index: int
    lexical_score: float
    semantic_score: float
    query_coverage: float
    character_score: float
    authority_score: float
    phrase_score: float
    temporal_score: float
    weights: RetrievalWeights

    @property
    def lexical_normalized(self) -> float:
        return 1 - math.exp(-self.lexical_score / 3)

    @property
    def normalized_score(self) -> float:
        components = (
            self.lexical_normalized,
            self.semantic_score,
            self.query_coverage,
            self.character_score,
            self.authority_score,
            self.phrase_score,
            self.temporal_score,
        )
        combined = sum(
            weight * value
            for weight, value in zip(self.weights.as_tuple(), components, strict=True)
        )
        return min(1.0, max(0.0, combined))


def _component_vectors(
    texts: list[str],
    official: list[bool] | None,
    authority_scores: list[float] | None,
    semantic_scores: list[float] | None,
    temporal_scores: list[float] | None,
) -> tuple[list[float], list[float], list[float]]:
    flags = [False] * len(texts) if official is None else official
    if len(flags) != len(texts):
        raise ValueError("texts and authority flags must have equal length")
    authority = (
        [1.0 if value else 0.0 for value in flags] if authority_scores is None else authority_scores
    )
    semantic = [0.0] * len(texts) if semantic_scores is None else semantic_scores
    temporal = [0.0] * len(texts) if temporal_scores is None else temporal_scores
    if any(len(values) != len(texts) for values in (authority, semantic, temporal)):
        raise ValueError("component arrays must have equal length")
    if any(not 0 <= value <= 1 for values in (authority, semantic, temporal) for value in values):
        raise ValueError("normalized component scores must be in [0, 1]")
    return authority, semantic, temporal


def _bm25(
    query_set: set[str],
    tokens: list[str],
    document_frequency: Counter[str],
    document_count: int,
    average_length: float,
    parameters: BM25Parameters,
) -> float:
    frequencies = Counter(tokens)
    score = 0.0
    for term in query_set:
        frequency = frequencies.get(term, 0)
        if not frequency:
            continue
        df = document_frequency[term]
        inverse_document_frequency = math.log(1 + (document_count - df + 0.5) / (df + 0.5))
        denominator = frequency + parameters.k1 * (
            1 - parameters.b + parameters.b * len(tokens) / max(average_length, 1)
        )
        score += inverse_document_frequency * (frequency * (parameters.k1 + 1)) / denominator
    return score


def score_candidates(
    query: str,
    texts: list[str],
    official: list[bool] | None = None,
    parameters: BM25Parameters = DEFAULT_BM25_PARAMETERS,
    *,
    authority_scores: list[float] | None = None,
    semantic_scores: list[float] | None = None,
    temporal_scores: list[float] | None = None,
    weights: RetrievalWeights = DEFAULT_RETRIEVAL_WEIGHTS,
) -> list[ScoredCandidate]:
    authority, semantic, temporal = _component_vectors(
        texts, official, authority_scores, semantic_scores, temporal_scores
    )
    query_tokens = tokenize(query)
    if not query_tokens or not texts:
        return []
    normalized_texts = [normalize_text(text) for text in texts]
    tokenized = [
        [
            _ukrainian_stem(token)
            for token in TOKEN_PATTERN.findall(normalized)
            if token not in STOP_WORDS
        ]
        for normalized in normalized_texts
    ]
    document_frequency: Counter[str] = Counter()
    for tokens in tokenized:
        document_frequency.update(set(tokens))
    average_length = sum(map(len, tokenized)) / len(tokenized)
    query_set, normalized_query = set(query_tokens), normalize_text(query)
    query_grams = _character_ngrams_normalized(normalized_query)
    scored: list[ScoredCandidate] = []
    for index, tokens in enumerate(tokenized):
        if not tokens:
            continue
        token_set = set(tokens)
        scored.append(
            ScoredCandidate(
                index=index,
                lexical_score=_bm25(
                    query_set,
                    tokens,
                    document_frequency,
                    len(tokenized),
                    average_length,
                    parameters,
                ),
                semantic_score=semantic[index],
                query_coverage=len(query_set.intersection(token_set)) / len(query_set),
                character_score=jaccard(
                    query_grams, _character_ngrams_normalized(normalized_texts[index])
                ),
                authority_score=authority[index],
                phrase_score=1.0 if normalized_query in normalized_texts[index] else 0.0,
                temporal_score=temporal[index],
                weights=weights,
            )
        )
    return scored
