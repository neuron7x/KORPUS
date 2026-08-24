"""Query risk as a register of rules with examples, and an unknown class that fails closed.

RAG-009: "Risk classifier є regex heuristic … Перефразування обходить stricter
thresholds". Two defects sat behind that sentence, and only one of them is about
regular expressions.

The first is coverage. "Чи можу я виїхати без наказу?" contains none of `наказ|
процедур|обовязков`, so it classified as STANDARD and was answered under the loosest
evidence thresholds this system has — for a question about whether the reader is
permitted to act. Rephrasing did not defeat a classifier; the classifier was never
looking at the thing that makes a question operational.

The second is the direction of failure. An unrecognised query fell to STANDARD, the
weakest setting. That is fail-open in the one place the whole design is fail-closed:
the cost of treating an operational question as ordinary is an answer that met lower
standards of proof than the question deserved, and the reader cannot see which
standard was applied.

So: rules carry ids and examples, an unmatched query is UNCLASSIFIED rather than
STANDARD, and UNCLASSIFIED is scored at the stricter setting rather than the looser
one. The examples are the test corpus — a rule whose example it does not match, or
whose counterexample it does match, fails the build.

What this is not: a trained classifier evaluated on a blind set with per-class
precision and recall and worst-group metrics. That is the acceptance predicate the
audit states, it needs annotated queries nobody here has, and it stays open. What is
closed is the fail-open direction and the invisibility of the rules.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from enum import StrEnum


class QueryRisk(StrEnum):
    STANDARD = "standard"
    TEMPORAL = "temporal"
    OPERATIONAL = "operational"
    #: No rule matched. Scored at the stricter setting, and named in the answer so a
    #: reader can tell "we judged this ordinary" from "we could not judge it".
    UNCLASSIFIED = "unclassified"


@dataclass(frozen=True)
class RiskRule:
    id: str
    risk: QueryRisk
    pattern: re.Pattern[str]
    rationale: str
    examples: tuple[str, ...]
    counterexamples: tuple[str, ...] = ()


#: Order matters: the first matching rule wins, and operational outranks temporal
#: because a question that is both ("який наказ чинний і що я маю робити") is
#: operational — the reader is about to act on the answer.
RISK_RULES: tuple[RiskRule, ...] = (
    RiskRule(
        id="operational.obligation",
        risk=QueryRisk.OPERATIONAL,
        pattern=re.compile(
            r"\b(наказ|процедур|порядок дій|зобовязан|обовязков|дозволен|заборонен"
            r"|order|procedure|must|shall|required|prohibited|authorized)"
        ),
        rationale="the query names an obligation, a permission or the order carrying it",
        examples=(
            "Який наказ регулює допуск?",
            "Чи дозволено виносити документи?",
            "What procedure applies to handover?",
            # Names an order and asks about its force. The overlap with
            # temporal.validity is resolved toward operational deliberately: the
            # stricter thresholds are the safe side of an ambiguous question.
            "Is this order still effective?",
        ),
        counterexamples=("Скільки підрозділів у складі?",),
    ),
    RiskRule(
        id="operational.permission_question",
        risk=QueryRisk.OPERATIONAL,
        # "чи можна знайти цей документ" is a question about the corpus, not about
        # permission to act, and firing on it would put the strictest thresholds on
        # ordinary lookups until operators stopped reading the class. The excluded
        # verbs are the retrieval ones; everything else after "чи можна" is an action.
        pattern=re.compile(
            # The pronoun sits between the words: "що я маю робити" is the ordinary
            # phrasing and "що робити" the terse one. A literal pair missed the first,
            # which is the same coverage failure RAG-009 was raised about, one level in.
            # `чи мож` as a prefix would swallow `чи можна`, whose retrieval exception
            # lives below — shortening the alternative to save four characters undid the
            # exception written three lines away.
            r"\b(чи можу|чи може|чи маю|чи повинен|чи потрібно|як діяти"
            r"|що.{0,12}?робити|ма[юєш].{0,4}робити"
            r"|may i|can i|should i|am i allowed|what do i do)"
            r"|\bчи можна(?!\s+(?:знайти|подивитися|переглянути|отримати доступ|прочитати))"
        ),
        rationale=(
            "the reader is asking whether they may act, which is an operational "
            "question however it is phrased. Rephrasing past the vocabulary rule is "
            "exactly what RAG-009 recorded"
        ),
        examples=(
            "Чи можу я виїхати без письмового підтвердження?",
            "Що робити, якщо командир відсутній?",
            "Am I allowed to release this to a partner unit?",
        ),
        counterexamples=("Чи можна знайти цей документ у корпусі?",),
    ),
    RiskRule(
        id="operational.consequence",
        risk=QueryRisk.OPERATIONAL,
        pattern=re.compile(
            r"\b(відповідальн|стягнен|покаран|наслідк|порушенн"
            r"|liable|penalty|sanction|consequence|violation)"
        ),
        rationale="a question about consequences is a question about what is required",
        examples=(
            "Яка відповідальність за порушення строку?",
            "What penalty applies to a late report?",
        ),
    ),
    RiskRule(
        id="temporal.validity",
        risk=QueryRisk.TEMPORAL,
        pattern=re.compile(
            r"\b(чинн|діє|строк|дата|редакц|скасован|на сьогодні|станом на"
            r"|valid|effective|current|as of|deadline|revision)"
        ),
        rationale="the answer depends on which edition was in force, and when",
        examples=(
            "Яка редакція чинна станом на травень?",
            "Is this revision still effective?",
            "Чи скасовано цей документ?",
        ),
        counterexamples=("Хто підписав документ?",),
    ),
    RiskRule(
        id="temporal.comparison",
        risk=QueryRisk.TEMPORAL,
        pattern=re.compile(
            r"\b(до \d{4}|після \d{4}|раніше|попередн|змінилося|before \d{4}|after \d{4}"
            r"|previously|changed)"
        ),
        rationale="comparing states across time requires knowing which state applied when",
        examples=("Що змінилося після 2024 року?", "What changed previously?"),
    ),
)


def classify(text: str, *, normalize: bool = True) -> tuple[QueryRisk, str | None]:
    """Return the risk class and the id of the rule that decided it.

    The rule id travels with the class so an answer can say *why* it was held to a
    given standard. A class without its reason is a number the reader must trust.
    """
    from korpus.application.retrieval import normalize_text

    candidate = normalize_text(text).replace("’", "'") if normalize else text
    for rule in RISK_RULES:
        if rule.pattern.search(candidate):
            return rule.risk, rule.id
    return QueryRisk.UNCLASSIFIED, None
