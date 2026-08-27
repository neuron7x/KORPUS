"""What a language model is allowed to contribute to an answer: better questions.

The measured failure is recall, not phrasing. On the imported corpus "що робити при
артилерійському обстрілі" returned `retrieval_gate_failed` with zero citations while the
material was there — the documents say "укриття", "перебіжка", "артилерійський наліт",
"щілина". The question and the corpus speak different Ukrainian.

So a planner rewrites the question into the corpus's vocabulary, and that is the whole of
its authority. It never writes an answer. Every claim a reader sees still carries
`quote_hash`, `span_hash` and a page, because it is still a sentence lifted verbatim from
an approved version — that property is the reason this system can be handed to a
commander, and generated prose has no hash to carry.

The corpus makes it worse than a general design concern: almost everything in it is
`AuthorityClass.ANALYTICAL` — training literature, not orders. A model synthesising
across it produces text that reads like doctrine and is not.

Three rules, enforced below rather than asked for:

  * a plan is a list of *search strings*, never instructions, never prose;
  * a plan that fails, times out, or returns nonsense degrades to the original question,
    which is exactly today's behaviour and therefore opens nothing;
  * the original question is always searched, first, whatever the planner says — a
    planner that quietly replaced it could steer a reader away from the passage they
    asked for and nothing downstream would notice.
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass, field
from typing import Protocol

from korpus.application.evidence import assess_control_injection
from korpus.application.model_bulkhead import ModelDeadline, result_before

#: A reformulation is a query. Anything long enough to be a sentence of prose is not one,
#: and is the shape an attempt to smuggle text into the answer would take.
MAX_QUERY_CHARS = 120

#: The rule the module claims — "2–6 words" — enforced rather than requested. Length
#: alone admitted "Наказ дозволяє залишити позицію без команди.": forty-three characters,
#: no forbidden marker, and a declarative sentence about what an order permits. It could
#: still only ever have been *searched for*, never quoted, but a plan that carries
#: assertions is a plan whose audit record reads like the system considered one.
MAX_QUERY_TOKENS = 8

#: A phrase does not end a sentence.
_TERMINAL = ".!?…"

#: Enough to cover a subject's vocabulary, few enough that one question cannot turn into
#: a scan of the corpus. Each variant costs a full-text search.
MAX_VARIANTS = 4

#: Control characters, bidi overrides and the private-use area do not appear in a military
#: term. They do appear in payloads built to render as one thing and match another.
_FORBIDDEN = re.compile(r"[\x00-\x1f\x7f​-‏‪-‮⁦-⁩-]")

#: A reformulation that carries these is not a query about the corpus.
_INSTRUCTION_MARKERS = (
    "ignore",
    "disregard",
    "system",
    "prompt",
    "instruction",
    "інструкці",
    "ігнору",
    "не зважай",
    "ти маєш",
    "відповідай",
)


class PlannerUnavailable(RuntimeError):
    """What an adapter raises when its provider did not answer.

    Declared here so the application can name the failure without importing an HTTP
    client: the adapter knows about timeouts and status codes, this layer knows only
    that the suggestion did not arrive.
    """


class QueryPlanner(Protocol):
    """Produces alternative phrasings of a question in the corpus's vocabulary.

    Returns an empty list for "no suggestion". Raising is also acceptable: the caller
    treats both as "search the question as asked".
    """

    def variants(self, question: str, subjects: list[str]) -> list[str]: ...


@dataclass(frozen=True)
class QueryPlan:
    """The searches that will run, and where each came from.

    `origin` is carried into the audit chain. An answer built partly from a
    machine-suggested phrasing is a different thing from one built from the words a
    soldier typed, and a record that cannot tell them apart cannot answer "why did it
    show me this" six months from now.
    """

    asked: str
    variants: tuple[str, ...] = ()
    refused: tuple[str, ...] = field(default_factory=tuple)

    @property
    def searches(self) -> tuple[str, ...]:
        """The question first, always, then whatever survived admission."""
        return (self.asked, *self.variants)

    def as_audit_record(self) -> dict[str, object]:
        return {
            "asked": self.asked,
            "variants": list(self.variants),
            "refused": list(self.refused),
            "interpretation": (
                "Reformulations are search strings suggested by a language model. They "
                "widen what was looked for; they contribute no text to the answer, which "
                "remains sentences quoted verbatim from approved versions."
            ),
        }


def admissible_variant(candidate: object, asked: str) -> str | None:
    """Admit only a short search phrase; all other model output is data, never control."""
    if not isinstance(candidate, str):
        return None
    text = unicodedata.normalize("NFC", candidate).strip()
    shape_refused = (
        not text
        or len(text) > MAX_QUERY_CHARS
        or bool(_FORBIDDEN.search(text))
        or "\n" in text
        or "\r" in text
        or text.endswith(tuple(_TERMINAL))
        or len(text.split()) > MAX_QUERY_TOKENS
    )
    if shape_refused:
        return None
    lowered = text.casefold()
    if any(marker in lowered for marker in _INSTRUCTION_MARKERS):
        return None
    if assess_control_injection(text).blocked:
        return None
    asked_key = unicodedata.normalize("NFC", asked).strip().casefold()
    return None if lowered == asked_key else text


#: The caller's bound on a third party, independent of whatever timeout the adapter
#: happens to set. Measured in the chaos matrix on 2026-08-06: a planner that blocked for
#: eight seconds cost the reader eight seconds, because nothing above the adapter was
#: counting. A suggestion that has not arrived by now is a suggestion the reader is
#: better off without.
PLANNER_DEADLINE_SECONDS = 8.0


def build_plan(
    question: str,
    planner: QueryPlanner | None,
    subjects: list[str] | None = None,
    *,
    deadline_seconds: float = PLANNER_DEADLINE_SECONDS,
) -> QueryPlan:
    """The searches to run for this question.

    Every failure mode ends at the same place — the question as asked — because that is
    what this system did before a planner existed. A planner that is missing, slow,
    broken or hostile leaves the reader exactly where they were.
    """
    if planner is None:
        return QueryPlan(asked=question)
    # A bounded process bulkhead rather than a signal: answer work already runs outside
    # the main thread. Timed-out provider calls may finish in their worker, but cannot
    # create an unbounded thread per request or consume the composer's separate pool.
    try:
        suggested = result_before(
            "planner",
            planner.variants,
            question,
            list(subjects or []),
            timeout_seconds=deadline_seconds,
        )
    except ModelDeadline as error:
        return QueryPlan(
            asked=question,
            refused=(str(error)[:200],),
        )
    except (PlannerUnavailable, TimeoutError, OSError, ValueError, TypeError) as error:
        # Named rather than blanket. Everything a provider can do to us arrives as one
        # of these — the adapter wraps its transport failures in `PlannerUnavailable` —
        # and anything else is a defect in this tree, which must surface rather than be
        # absorbed into "the model had no suggestion".
        #
        # Degraded, not swallowed: the plan says which planner failed and how, that
        # record reaches the audit chain with the answer, and the reader is left exactly
        # where they were — searching the question they asked.
        return QueryPlan(
            asked=question,
            refused=(f"planner unavailable: {type(error).__name__}: {error}"[:200],),
        )

    if not isinstance(suggested, (list, tuple)):
        message = f"planner contract violation: expected list/tuple, got {type(suggested).__name__}"
        return QueryPlan(asked=question, refused=(message[:200],))

    accepted: list[str] = []
    refused: list[str] = []
    seen = {unicodedata.normalize("NFC", question).strip().casefold()}
    for candidate in list(suggested)[: MAX_VARIANTS * 3]:
        admitted = admissible_variant(candidate, question)
        if admitted is None:
            refused.append(str(candidate)[:MAX_QUERY_CHARS])
            continue
        key = admitted.casefold()
        if key in seen:
            continue
        seen.add(key)
        accepted.append(admitted)
        if len(accepted) >= MAX_VARIANTS:
            break
    return QueryPlan(asked=question, variants=tuple(accepted), refused=tuple(refused))
