# Evaluation evidence admission — issue #131

The reference evaluator now admits the actual question set and verifies cited source
bytes before counting an answer as supported. These are data and evidence admission
controls. They do not establish complete zero trust architecture, device posture, or
qualification of an owner's machine, external HTTPS endpoint, or restore procedure.

## Input identity and execution

`run_reference_eval.py` checks nonempty JSONL, unique case identifiers, the actual
case/expectation schema, expected version UUIDs, metadata counts, and the complete
SHA-256 before creating the HTTP client. It preserves the canonical serialization
used by the existing builder: sorted JSON keys, UTF-8, and one newline per case.
Duplicate JSON keys and nonfinite JSON constants are rejected. The report records
the computed digest and the run's fixed UTC default date; an explicit case date
overrides that default for both its answer and its source disclosure.

`run_boundary_eval.py` reads and validates its complete question/metadata snapshot
before HTTP. It reports the hash of those exact bytes, even if a file changes during
execution. The public producer accepts a dataset path instead of arbitrary rows
whose answers could previously be paired with the unrelated default file's digest.
Its original raw-byte SHA-256 convention is retained. Both strata must be nonempty.

## Citation evidence and transport

The reference judge fetches only `GET /v1/spans/{canonical-UUID}?as_of={date}` through
the same configured API base and bearer used for the answer. It never fetches a
citation's `source_uri`. Redirect following and environment proxy discovery are
disabled; nonlocal HTTP is rejected. Requests have a finite deadline and responses
are bounded to 1 MiB. These constraints also apply to answer requests.

Every citation must match the authorized disclosure's document/version/span identity,
source hash, displayed source metadata, UTF-8 span hash, quote hash, and exact
character-offset substring. Matching an expected version identifier or a quote's
own hash alone is insufficient. The judge does not trust claimed verification flags.
Missing, forbidden, redirected, fabricated, or malformed evidence is a failure.
Dependency failures (HTTP 429/5xx) and transport failures are unavailable measurements.
A known failure outranks unavailable evidence; unavailable evidence never increases
supported answers or produces a passing run. Locally detectable malformed citations
are rejected before attempting source retrieval.

The source disclosure endpoint remains the authorization boundary. The evaluator
does not independently authenticate original file ownership or prove semantic
entailment, source truth, current corpus completeness, or a live deployment's quality.
Boundary answer rates continue to measure whether an answer was issued, not whether
that answer was correct. A reference safety pass can still contain abstentions;
the separate retrieval-effectiveness metrics expose that distinction.

## Numeric ratchet and historical evidence

Rates, recorded baseline rates, floors and ceilings must be finite numeric values in
`[0,1]`; booleans are rejected. A measured stratum must contain integer counts with
`0 <= answered <= judged`, a positive denominator, and a rate exactly equal to
`answered / judged`. Incomplete or invalid measurements cannot be represented as
`MEASURED`. Policy and report schemas, threshold axes, relaxation records, and full
64-character dataset identities are checked before threshold comparisons.

The historical dataset's existing full digest is
`12cef2e250cba405626017a186b69817f152490f1ccfc73f56a4f38ce614b5ea`.
The ratchet previously stored only its first 16 characters. Expanding that identity
uses the already recorded metadata and matching dataset bytes; it creates no new
measurement. Recorded rates **0.95 / 0.20** and thresholds **0.90 / 0.25** are unchanged.

## Repeatable controls and module bounds

The ordinary pytest suite and determinism gate include valid synthetic archive cases
and adversarial dataset, source, transport, and numeric controls. The mutation catalog
adds M800–M805 for a skipped dataset digest, a skipped source-substring check, a skipped
numeric domain check, redirect following, malformed metadata, and incomplete sample
cardinality. Existing M355 still tests a coherent
foreign-question rate above the ceiling; its fixture now carries matching counts.
The fixtures contain no real corpus or credentials.

New helpers remain below the unchanged module defaults. The reference runner is
reduced from a recorded 260-line / complexity-26 ceiling to a measured 94 lines /
complexity 6. The boundary runner remains within its existing 116-line / complexity-6
ceiling. Two narrow data/proof budget changes are recorded: the unchanged eight
ratchet selftest cases need **48 → 66 proof lines** for their now-valid schemas,
complete identities and integer counts; four added determinism test entries need
**57 → 61 module lines**, without changing executable complexity. Neither change
raises a global default or exempts executable logic.

Local focused tests are implementation checks, not independent review or a canonical
hosted mutation result. Git/process ownership refusals remain failures and are not
suppressed. Release authority still requires the existing independent review and
hosted gates on the published candidate.

## Independent review corrections

Source and citation metadata are validated independently before equality comparison.
Required title/revision values cannot disappear through matching missing keys or
null values. Page numbers require strict positive integers, so a JSON boolean cannot
impersonate page 1. Nullable page/section/source URI values remain valid when explicitly
present. Citation shape is checked before source transport, so a known malformed
citation remains FAIL even if the source would be unavailable.

The ratchet policy also pins 20 cases per stratum from the existing frozen metadata.
Each measured denominator must equal that cardinality. A two-case sample cannot claim
the full 40-case identity merely by reporting internally consistent rates. These
cardinalities describe the frozen inputs; no historical rates were remeasured.

Measured local module-ceiling changes for the new metadata/cardinality guards are
recorded individually in the budget ledger, without changing global defaults.
