# Bounded question applicability and completeness

Issue #133 adds necessary applicability checks to the extractive answer path. The
failure reproduced by the neutral archive-card probes was an exact quote about
one archive answering a question about another, and a color-only quote answering
a request for both color and size. Both could exceed the unchanged lexical
coverage threshold. Exact bytes establish provenance; they do not establish that
the quote answers this question.

## Recognized language

`question_obligations.py` is a pure deterministic surface-language contract. It
recognizes quoted names, non-initial capitalized terms, alphanumeric identifiers,
dotted version identifiers, and numbers following explicit version/revision
markers. Identifier matching preserves the whole lexeme: `A-7` does not match
`A-70`, and `v2.1` does not match `v2.10`.

The property grammar recognizes a leading Ukrainian `який/яка/яке/які` (and listed
case forms) or English `what/which`, optional English `is/are/the`, one-word
property heads coordinated by `і/й/та/and`, and a shared noun-phrase subject.
For example, `Який колір і розмір картки архіву?` and
`What are the color and size of the archive card A-7?` carry two property
obligations. Subject terms are mandatory even in a lowercase question. Predicate
questions containing the listed clause markers retain the existing interrogative
and declared-subject path; generic questions without recognized obligations retain
the existing calibrated gates.

A single duty head recognized by the existing interrogative classifier also retains
that path in the genitive form, such as `Які обов'язки архіваріуса?`. The recognized
role remains a mandatory subject; a duty formulation is not incorrectly required
to repeat the literal noun `обов'язки`. Coordinated property heads are not exempted.

Ordinary terms use the existing canonical tokenizer/stemmer, so supported
inflections share the same decision without a place-name list. Explicit quoted
names and identifiers require literal normalized lexemes. An alias can be used
when that spelling is present in the approved quoted source. The bounded naming
construction is a quoted native name followed by a parenthetical name of one to
three capitalized words, such as `«Сокіл» (Sokil)`. This change adds no alias
registry, equivalence from free-standing co-mentions, unversioned document metadata, model-based entity
resolver, or multilingual semantic model. An absent alias is not guessed.
Only an explicit named/quoted query obligation licenses this naming construction;
a generic noun such as "archive" cannot authorize additional names in a fact head.

The grammar is intentionally bounded to 16 subject obligations and 8 property
heads. Exceeding the recognition budget refuses explicitly; it never silently
drops obligations. These rules are necessary checks, not a general semantic proof.
They do not resolve arbitrary pronouns, paraphrases, spelling variants, implicit
aliases, unrestricted relations between co-mentioned entities, or whether a
mentioned property actually supplies its value. Complex coordination and multilingual semantic
retrieval remain separately measured capability boundaries. A source that only
describes who will decide a property is not proved to supply that property's value
by this contract.

## Admission and evidence selection

Each offered sentence must satisfy every recognized subject obligation. Only the
existing declared-subject title contract may provide subject context without
repetition in the quote. No unrelated quote may borrow an entity from another
quote. Coverage, support, authorization, dates, authority, source-instruction
filtering and contradiction gates remain in force at their previous thresholds.

A recognized property needs a witness in the same fact clause as its subject.
The bounded source grammar splits punctuation/contrast clauses and takes the head
before a dash, colon, equals sign or listed copula. Its significant terms must be
drawn from the question's subject/property terms, grammatical function words and
the source's explicit naming construction. An extra unrequested entity or
qualifier in that head is not silently ignored; the construction is refused.
This intentionally conservative closed head check also works for lowercase names.
A subject mentioned only after a fact's binding marker or in a neighboring clause
cannot transfer another entity's property. A recognized correct clause can still
be quoted in full alongside an unrelated neighboring clause. Every emitted quote
must have its own applicable property witness; a correct quote cannot rescue an
extra quote whose only match is a foreign-property co-mention.

For a recognized multi-property question, candidates are grouped by exact version.
Selection prefers a version covering all recognized properties, then chooses
sentences that add uncovered properties using stable evidence and sentence keys.
Facts may reside in one span or separate spans of the same version. Incomplete
facts from unrelated versions cannot be joined into a complete witness. The
retrieval diversity cap for one version can use the recognized property count,
bounded by the existing total result limit; there is no extra retrieval call or
candidate-budget expansion. Existing global claim limits still apply. Selection
does not guarantee that every relevant source will be retrieved within those
budgets; missing witnesses continue to refuse.

Repeated exact sentences are emitted once. Several quotes from one version remain
one source and retain the existing reader-facing limitation. Every chosen sentence
retains its original span ID, quote offsets, quote hash, span hash, source hash,
document/version identity and citation adjudication. Sentences are not stitched
across span boundaries.

`answer_obligations.py` independently checks actual claim/citation pairs before an
answer can become `answered`. It verifies each recognized subject again, exact
claim/quote binding to the eligible document and version, and complete property
coverage within one version. This check does not trust candidate selection to have
been implemented correctly. Unmet obligations return existing
`insufficient_evidence` with reason `question_obligations_unmet`, no claims or
citations, and a limitation naming what is missing. There is no new partial-success
schema and no incomplete answer labeled complete.

Independent review demonstrated that one claim could borrow another quotation's
span ID. The final gate now requires equality of the literal `(claim text, span ID)`
and `(quotation text, span ID)` relations in both directions. Every declared claim
reference needs its own exact citation, and every citation needs its matching claim.
This binding check also applies when the question has no recognized language
obligations. A correct cited claim cannot conceal an extra uncited claim from the
same otherwise eligible span.

## Identity and verification

The contract is source code covered by the normal release source manifest and
package identity; it adds no answer-visible metadata or schema migration. The
development retrieval configuration changes from `development-default-ranking-v5`
to `development-default-ranking-v6` because multi-property retrieval diversity
changes. Calibrated cache configuration IDs append `:obligations-v1` to
the same single-loaded profile ID, and continue to bind corpus/release identity.
The corpus release describes corpus state; the explicit configuration suffix
also separates algorithm versions when corpus state and calibration are unchanged.
Canonical release artifacts must be regenerated through
the normal publication workflow, and existing calibration results do not establish
unmeasured linguistic accuracy for the new contract.

Focused controls live in `test_question_obligations.py` and
`test_question_obligations_api.py`. They include wrong/right/unknown subjects,
lowercase and measured inflections, literal source aliases, identifier/version
contrasts, generic positive controls, exact provenance, missing-property refusal,
same-version requirements, duplicate sentences, claim limits and candidate-order
invariance. The HTTP controls use the shipped 0.18/0.5/0.18 thresholds.

The service-level three-property matrix exhausts all eight source-availability
masks and checks original, reversed and duplicated candidate orders. Only the full
witness may answer; the comparison includes status, reasons, claims, citations and
limitations while excluding generated answer ID and timestamp. Both test files are
part of the ordinary four-seed determinism gate alongside its existing six suites.
Mutants M820–M825 respectively bypass subject obligations, accept an absent
property, re-emit duplicate sentences and bypass the independent final subject
check, let an uncited claim borrow another quote's span, or regress genitive duty
questions into literal property matching. Existing extraction/provenance mutants retain their targets, with M346
following the sentence-order helper into its new module.

These fixtures establish the named invariants on synthetic archive material. They
are neither a domain benchmark nor permission to enable a new model, relax
thresholds, claim universal answer correctness, or skip independent review and
hosted release gates.
