SHELL := /bin/bash
PY := apps/api/.venv/bin/python
PIP := apps/api/.venv/bin/pip

.PHONY: corpus-axes evidence-bases dormant-subsystems control-copy serving-freshness lane-report install-nightly-gates check-nightly nightly-evidence check-deployment deployment-debt deployment-debt-selftest public-env-parity public-env-parity-selftest gate-closure gate-closure-selftest public-surface public-surface-selftest subject-precision repair-span-markup fetch-stubs diagnose-retrieval span-hygiene compare-retrieval remap-reference-versions serve-semantic-local restore-document-types embedding-backfill-sqlite runtime-corpus-manifest refusal-retryability publication-mirrors agent-protocol catalog-uri-uniqueness cache-in-tree evidence-refusal gate-liveness capture-evidence capture-evidence-selftest content-signals remote-digest document-probe deterministic-replay provenance provenance-verify reference-set reference-eval embedding-candidate-screen embedding-backfill corpus-admission gold-annotation-audit runtime-corpus-audit service-objectives corpus-release corpus-release-verify security-scan reproducible-build chaos-matrix ingestion-drill load-probe backup-sqlite restore-sqlite drive-snapshot drive-public serve-public public-tunnel draft-manifest import-corpus review-token audit-export web-contract web-contract-check environment-drift environment-observe requirements-register module-budget file-modes import-cycles release-identity source-manifest-verify retention-plan postgres-suite sqlite-recovery-drill quality-gate handoff-verify handoff-verify-bound openapi audit-closure desired-state supply-chain-inventory kubernetes-validate github-actions-validate infra-validate backup-postgres restore-postgres api-install api-run api-test api-lint web-install web-run web-build bootstrap eval mutation migration-gate scale operational-gate assurance assemble-assurance snapshot audit-verify validate check release infra-secrets infra-up infra-support infra-down package clean production-engineering production-tevv production-observability production-state-contracts production-authorization production-redteam-internal production-redteam-external production-inference-security production-reliability-internal production-reliability production-postgres-security production-exact-environment production-sbom production-supply-chain production-mutation production-assurance production-assurance-verify production-release dependency-locks assurance-model-check standards-control-map slsa-provenance slsa-provenance-verify release-mutation-delta package-build-identity evidence-refresh mutation-probe mutation-report-freshness answer-quality answer-axes corpus-integrity recut-spans coverage-ratchet coverage-union determinism-gate stress-gate plasticity-gate canonical-release-cycle production-hard-predicates military-readiness military-readiness-full evidence-stores selftest-coverage installed-units-verify canonical-verify branch-integration

api-install:
	python3 -m venv apps/api/.venv
	$(PIP) install --no-deps --require-hashes --requirement apps/api/requirements.dev.lock

api-run:
	mkdir -p var/objects
	$(PY) -m uvicorn korpus.main:app --app-dir apps/api/src --host 127.0.0.1 --port 8000 --reload

# --cov-fail-under bounds one combined number. The release policy states line and
# branch minimums separately, and the only thing that read the branch one ran at the
# very end of the pipeline — so branch coverage sat below policy for as long as anyone
# had been writing tests. check_coverage_thresholds.py reads both from the policy.
api-test:
	PYTHONPATH=apps/api/src $(PY) -m pytest apps/api/tests -p no:cacheprovider --junitxml=var/pytest.xml --cov=apps/api/src/korpus --cov-branch --cov-report=term-missing --cov-report=xml:var/coverage.xml --cov-report=json:var/coverage.json --cov-fail-under=82
	PYTHONPATH=apps/api/src $(PY) scripts/check_coverage_thresholds.py

# The ratchet reads the union of both dialects, because both are what the suite runs.
# Measuring SQLite alone reports every `dialect.name == "postgresql"` arm as untaken by a
# run that cannot reach it — fourteen branches in `repository.py` alone — and the queue
# then lists work that is already done. `coverage-union` fails closed when the PostgreSQL
# report is absent rather than silently falling back to the SQLite one, so the number the
# ratchet reads always says which runs produced it.
coverage-ratchet: api-test coverage-union
	PYTHONPATH=apps/api/src:. $(PY) scripts/coverage_gap_plan.py --coverage var/coverage-union.json --out var/coverage-gap-plan.json

# The suite runs against both dialects; only one of them was ever measured. `api-test`
# measures SQLite, `postgres-suite` runs PostgreSQL with --no-cov, and eight
# `dialect.name` branches in the repository are therefore reported as untaken by a run
# that cannot reach them. This unions the two so the ratchet's own queue stops listing
# work that is already done — the ratchet itself keeps reading the SQLite report, which
# is the stricter of the two, so nothing is relaxed by producing this.
#   make coverage-union   (after api-test and a PostgreSQL run with coverage)
coverage-union:
	PYTHONPATH=apps/api/src $(PY) scripts/merge_dialect_coverage.py
	PYTHONPATH=apps/api/src:. $(PY) scripts/coverage_gap_plan.py --coverage var/coverage-union.json --out var/coverage-gap-plan-union.json

deterministic-replay:
	PYTHONPATH=apps/api/src:. $(PY) scripts/deterministic_replay_probe.py

determinism-gate:
	PYTHONPATH=apps/api/src:. $(PY) scripts/run_determinism_gate.py --out var/determinism-gate.json

stress-gate:
	PYTHONPATH=apps/api/src:. $(PY) scripts/run_stress_gate.py --out var/stress-gate.json

plasticity-gate:
	PYTHONPATH=apps/api/src:. $(PY) scripts/run_plasticity_gate.py --out var/plasticity-gate.json

# One serial fail-closed release cycle. The explicit recursive makes keep this order
# even when the parent make is invoked with -j; no later gate can hide an earlier FAIL.
# `mutation` moved ahead of `operational-gate` on 2026-08-28. The gate reads
# MUTATION_REPORT.json and refuses a report generated from another source tree, so with
# mutation last the gate always read the *previous* run's report: on any changed tree the
# cycle failed with `mutation: generated from a different source tree`, and passed only
# when it was run twice. Producers before the gate that consumes them.
canonical-release-cycle:
	$(MAKE) api-lint PY=$(PY)
	$(MAKE) coverage-ratchet PY=$(PY)
	$(MAKE) determinism-gate PY=$(PY)
	$(MAKE) stress-gate PY=$(PY)
	$(MAKE) plasticity-gate PY=$(PY)
	$(MAKE) release-mutation-delta PY=$(PY)
	$(MAKE) eval PY=$(PY)
	$(MAKE) mutation PY=$(PY)
	$(MAKE) migration-gate PY=$(PY)
	$(MAKE) scale PY=$(PY)
	$(MAKE) operational-gate PY=$(PY)
	$(MAKE) validate PY=$(PY)
	$(MAKE) web-build

# `mypy apps/api/src` from the repository root did not type-check this project.
# The [tool.mypy] section lives in apps/api/pyproject.toml, and mypy only reads a
# pyproject.toml it finds in the *current* directory — so the strict flags were never
# applied. Passing a source path also overrode packages = ["korpus"], which left mypy
# unable to resolve korpus.* at all: the run reported 136 import-not-found errors
# instead of the 42 real strict violations underneath them (probed 2026-08-03).
# Runs both tools and records the run in var/quality-report.json. The aggregate
# assurance verdict requires that recording: a declared-but-unexecuted tool used to
# sit next to "status": "PASS" (destruction stage 2026-08-03).
api-lint:
	PYTHONPATH=apps/api/src $(PY) scripts/run_quality_gate.py

web-install:
	npm --prefix apps/web ci

web-run:
	npm --prefix apps/web run dev

# `node --check <file>` exits 0 for any file containing an `import`, so the two
# --check invocations that used to stand here stopped checking anything the moment
# app.js became a module and kept printing success. The parse now happens inside
# validate.mjs, on stdin, with an explicit --input-type — and validate_gate.test.mjs
# mutates a copy of the tree to prove each control can still fail.
web-build: web-contract-check
	npm --prefix apps/web run lint
	npm --prefix apps/web run test
	npm --prefix apps/web run build
	npm --prefix apps/web run test:browser

# Generated browser contracts: operator request constraints and the consumer transport
# surface. Both derive from canonical OpenAPI/release identity; neither is hand-maintained.
web-contract:
	PYTHONPATH=apps/api/src $(PY) scripts/generate_web_contract.py
	PYTHONPATH=apps/api/src $(PY) scripts/generate_transport_contract.py

web-contract-check:
	PYTHONPATH=apps/api/src $(PY) scripts/generate_web_contract.py --check
	PYTHONPATH=apps/api/src $(PY) scripts/generate_transport_contract.py --check

# OPS-004. Two commands, because the observation has to be taken on the machine that is
# running and the comparison made against the manifest as committed. Doing both here
# would fingerprint the build host, which is the failure the check exists to catch.
environment-drift:
	$(PY) scripts/check_environment_drift.py --observation "$(OBSERVATION)"

environment-observe:
	$(PY) scripts/check_environment_drift.py --observe "$(ROOT)" --out "$(OUT)"

bootstrap:
	mkdir -p var/objects
	PYTHONPATH=apps/api/src $(PY) scripts/bootstrap_local.py

eval:
	PYTHONPATH=apps/api/src $(PY) scripts/run_evals.py

# A measurement, not a gate. The curated catalogue covers 126 modules and reports 100%
# over itself; 162 modules and 15 853 lines carry no mutant at all, so that number says
# nothing about them. This samples ordinary operator mutations there — a comparison
# flipped, a boolean swapped — and reports what the suite kills. Survivors are candidates
# for the curated catalogue, not defects on their own: an equivalent mutation is always a
# possible explanation and has to be checked one at a time.
#   make mutation-probe SAMPLE=60
mutation-probe:
	PYTHONPATH=apps/api/src $(PY) scripts/probe_uncatalogued_mutation.py \
	  $(if $(SAMPLE),--sample $(SAMPLE)) $(if $(SEED),--seed $(SEED))

mutation:
	PYTHONPATH=apps/api/src PYTHON=$(PY) KORPUS_MUTATION_SHARDS=6 scripts/run_mutation_shards.sh

# The suite against a migrated PostgreSQL database, in a throwaway container. Not part
# of `check`: it needs docker, and `check` has to run where docker does not. It is a
# required CI job instead — the closures in this tree were proved on SQLite, and the
# two dialects have separate implementations of the currency filters, the retrieval
# projection and the audit head update.
postgres-suite:
	scripts/run_postgres_suite.sh

migration-gate:
	PYTHONPATH=apps/api/src $(PY) scripts/run_migration_gate.py

scale:
	PYTHONPATH=apps/api/src $(PY) scripts/run_scale_probe.py

operational-gate:
	PYTHONPATH=apps/api/src $(PY) scripts/run_operational_gate.py

military-readiness:
	PYTHONPATH=apps/api/src:. $(PY) scripts/run_military_readiness_campaign.py

military-readiness-full:
	PYTHONPATH=apps/api/src:. $(PY) scripts/run_military_readiness_campaign.py --full --full-timeout 180 --regression-batch-size 8 --regression-workers 2

assemble-assurance:
	PYTHONPATH=apps/api/src $(PY) scripts/assemble_assurance.py

assurance:
	PYTHONPATH=apps/api/src $(PY) scripts/run_research_assurance.py

snapshot:
	PYTHONPATH=apps/api/src $(PY) scripts/snapshot_assurance.py

# A plan, not a scheduler: it computes dispositions and deletes nothing. Exit 2 means
# material is past its retention period with no deletion permission, or sits in a
# corpus with no governance policy — decisions nobody has made, not code faults.
# A ratchet, not a target: modules may shrink freely, growth fails. "Not yet in the
# budget" is how a file gets to two thousand lines without anyone noticing.
# The register as a document: §2.5 asks an outside party to judge this system, and the
# first thing they need is the list of properties it claims about itself.
requirements-register:
	PYTHONPATH=apps/api/src $(PY) scripts/export_requirements.py

import-cycles:
	PYTHONPATH=apps/api/src $(PY) scripts/check_import_cycles.py

release-identity:
	PYTHONPATH=apps/api/src $(PY) scripts/check_release_identity.py

source-manifest-verify:
	PYTHONPATH=scripts python3 scripts/verify_source_manifest.py


package-build-identity:
	PYTHONPATH=apps/api/src:scripts $(PY) scripts/verify_package_build_identity.py

release-mutation-delta:
	PYTHONPATH=apps/api/src:. $(PY) scripts/run_release_mutation_microcampaign.py

# The report is written twice on purpose. `var/` is the run artefact; the copy under
# `reports/` is what `current-truth-verify` reads to prove the evidence is bound to the
# tree that produced it. Copying it here rather than by hand is why the two stopped
# disagreeing: the checked-in copy had been four source digests behind for weeks, and
# nothing in the pipeline updated it.
dependency-locks:
	mkdir -p var
	PYTHONPATH=apps/api/src:. $(PY) scripts/verify_dependency_locks.py --out var/dependency-lock-report.json --osv-out var/osv-query-batch.json
	install -m 0644 var/dependency-lock-report.json reports/DEPENDENCY_LOCK_VERIFICATION_CURRENT.json

assurance-model-check:
	mkdir -p var
	PYTHONPATH=apps/api/src:. $(PY) scripts/model_check_assurance.py > var/assurance-model-check.json

standards-control-map:
	mkdir -p var
	PYTHONPATH=apps/api/src:. $(PY) scripts/verify_standards_control_map.py --out var/standards-control-map-verification.json
	install -m 0644 var/standards-control-map-verification.json reports/STANDARDS_CONTROL_MAP_VERIFICATION.json

# Artifact provenance is intentionally emitted beside the ZIP rather than embedded in it:
# the statement binds the completed artifact digest, and embedding it would create a
# circular digest. Local provenance is structurally verifiable but does not self-assert
# a SLSA level or trusted builder identity.
slsa-provenance:
	test -n "$(ARTIFACT)"
	test -n "$(OUT)"
	PYTHONPATH=apps/api/src:scripts $(PY) scripts/slsa_provenance.py generate --artifact "$(ARTIFACT)" --out "$(OUT)" $(if $(BUILDER_ID),--builder-id "$(BUILDER_ID)") $(if $(INVOCATION_ID),--invocation-id "$(INVOCATION_ID)")

slsa-provenance-verify:
	test -n "$(ARTIFACT)"
	test -n "$(STATEMENT)"
	PYTHONPATH=apps/api/src:scripts $(PY) scripts/slsa_provenance.py verify --artifact "$(ARTIFACT)" --statement "$(STATEMENT)" --trusted-builders config/assurance/trusted-builders.v1.json $(if $(REQUIRE_TRUSTED_BUILDER),--require-trusted-builder)

module-budget:
	PYTHONPATH=apps/api/src $(PY) scripts/check_module_budget.py
	PYTHONPATH=apps/api/src:scripts $(PY) scripts/check_budget_raises_are_named.py

# Ruff states the same rule as EXE001/EXE002, but it reads only Python under four
# directories: the shell scripts, Dockerfiles, Terraform and manifests had no mode check
# at all. This reads `git ls-files`, which is the set the source manifest hashes.
file-modes:
	$(PY) scripts/check_file_modes.py

# The doctrine catalog's provenance rules, executable: RESTRICTED never ingestible,
# rights clearance stays a human decision, secondary analysis is never given a governing
# authority, an unverified mirror enters quarantine. A curated bibliography, not corpus
# bytes — gated so a hand-edit that would let a restricted or commercial source in fails.
doctrine-catalog:
	PYTHONPATH=apps/api/src $(PY) scripts/validate_doctrine_catalog.py

# Чи кожен гейт узагалі здатен почервоніти. Не в `validate`: кожна проба копіює дерево
# і проганяє гейт заново, тож це хвилини, а не секунди. Запускати перед merge.
# Еталон, на якому гейти корпусу можна ЗМУСИТИ впасти. Не гейт: він БУДУЄ вхід для проб.
# Тексти лежать у git, усе побудоване — під `var/`, бо похідний артефакт у джерельному
# дереві ламає саме ту перевірку, що боронить межу джерел.
liveness-fixture:
	$(PY) scripts/build_liveness_fixture.py $(if $(VERIFY),--verify)

# Похідні статті успадковують посилання батьківського статуту. Батько визначається
# ДОСЛІВНИМ входженням у оригінал з object-store, не назвою: у назві сказано лише
# «Статут», а їх чотири.
relink-derived:
	@test -n "$(DATABASE)" || { echo "вжиток: make relink-derived DATABASE=/шлях/до/korpus.db [APPLY=1]" >&2; exit 64; }
	$(PY) scripts/relink_derived_articles.py --selftest
	$(PY) scripts/relink_derived_articles.py --database "$(DATABASE)" $(if $(OBJECT_ROOT),--object-root "$(OBJECT_ROOT)") $(if $(APPLY),--apply)
	$(PY) scripts/validate_derived_source_links.py --database "$(DATABASE)" $(if $(OBJECT_ROOT),--object-root "$(OBJECT_ROOT)")

gate-liveness:
	PYTHONPATH=$(HOME)/neuron7x-verdict/src $(PY) -m neuron7x_verdict.cli gates \
		--config config/operations/gate-liveness.yaml --root . \
		$(if $(ONLY),--only "$(ONLY)") $(if $(OUT),--json "$(OUT)")

# Прочитати кожне джерело каталогу один раз і записати, що саме прочитано. Потребує
# мережі, тому не гейт. Ратчет усередині: прогін, який не опустив стелю, себе не пише.
capture-evidence:
	PYTHONPATH=apps/api/src $(PY) scripts/capture_source_evidence.py --write $(ARGS)

# Чи вісь значення розділяє те, чого вісь слова не розділяла. Потребує локального
# embedding-сервера, тому не гейт. Нічого не вмикає — див. promotion_authorized у звіті.
semantic-separation:
	PYTHONPATH=apps/api/src $(PY) scripts/measure_semantic_separation.py $(ARGS)

# Де стоїть поріг відносно даних, які він мав би ділити. Відповідає на «чи він узагалі
# перевірений», НЕ на «чи він перевірений правильно»: `separates` означає лише, що межа
# проходить крізь дані, і запрошує подивитися, ЩО опинилось по різні боки.
threshold-distance:
	PYTHONPATH=apps/api/src $(PY) scripts/threshold_distance.py $(ARGS)

threshold-distance-selftest:
	PYTHONPATH=apps/api/src $(PY) scripts/threshold_distance.py --selftest

# Переміряти відмови: причина без дати ніколи не пропонує себе перечитати.
recheck-blocked:
	PYTHONPATH=apps/api/src $(PY) scripts/recheck_blocked_sources.py $(ARGS)

recheck-blocked-selftest:
	PYTHONPATH=apps/api/src $(PY) scripts/recheck_blocked_sources.py --selftest

capture-evidence-selftest:
	PYTHONPATH=apps/api/src $(PY) scripts/capture_source_evidence.py --selftest

# Claims about this system's own gates, and who signed them. A verdict from the actor who
# made the claim is refused: producer and acceptor being the same is the defect a full day
# of cross-session work was spent finding, and it is the one that repeats.
verdict-ledger:
	$(PY) scripts/verify_verdict_ledger.py --selftest
	$(PY) scripts/verify_verdict_ledger.py

# Does the commit stand on its own? Four defects this session passed in the working tree and
# failed in a clone of HEAD: a digest over untracked files, a catalog citing captures the
# commit did not carry, a manifest describing a file since rewritten, a budget already red.
# Not in `validate` — it clones the repository, which a gate inside the repository must not.
verify-clean-clone:
	bash scripts/verify_clean_clone.sh

# HTTP 200 on a public domain is not permission. robots.txt carries two express
# reservations the catalog never read: `Content-Signal: ai-train=no / ai-input=no /
# use=reference`, which binds everyone, and `User-agent: ClaudeBot ... Disallow: /`,
# which names us. A `Disallow: /` for Bytespider names someone else and must not block
# a source here — the gate keeps those two apart, and --selftest proves it can go red.
content-signals:
	$(PY) scripts/validate_content_signals.py
	$(PY) scripts/validate_content_signals.py --selftest

# Evidence for an artifact too large for the tree: sha256 of the first and last 64 KB plus
# Content-Length. Rechecking costs 128 KB, so a third party can actually contradict it —
# which an integrity_anchor with no file never could. Kept as its OWN axis: it proves the
# artifact existed and was this one, and says nothing about its content, so it must never
# be folded into content_probe or attachments_captured.
remote-digest:
	$(PY) scripts/validate_remote_digest.py
	$(PY) scripts/validate_remote_digest.py --selftest

# What a document FILE contains: pages, words, structure, and an index of the named
# systems it mentions. content_probe demands card/print variants because it was built for
# rada pages; inventing those for a PDF would satisfy the shape without measuring anything.
# The rule that earns this gate its place: pages>0 with words≈0 is a scan, and a catalogue
# that records only the page count says "we have it" about a file nothing can read.
document-probe:
	$(PY) scripts/validate_document_probe.py
	$(PY) scripts/validate_document_probe.py --selftest

# A source our own extractor refuses is not "available", and the three reasons need
# three verdicts. `extractor_refused` is a limit of ours and contradicts ingestible.
# `extractor_misclassified` means we misread content that is fine — blocking the source
# for our own bug is the very thing this gate exists to prevent, so it does NOT go red;
# it ages out instead, because a known bug nobody acts on is a debt recorded as a fact.
# A retryable network failure from today is a stale reading, not a verdict: writing
# `ingestible: false` from it is how four public Distribution A documents were lost.
evidence-refusal:
	$(PY) scripts/validate_evidence_refusal.py
	$(PY) scripts/validate_evidence_refusal.py --selftest

# Ніщо не пише кеш, похідні дані чи тимчасове ВСЕРЕДИНІ дерева. Перевіряється СТАН
# дерева, а не текст коду: правило, що шукає відомий рядок, знає лише ту помилку, яку
# вже зробили. Два випадки за добу: `scripts/.mypy_cache` (24 МБ) робив гейт досяжності
# зеленим назавжди, а кеш витягнутого тексту в `var/evidence-capture/derived` зник разом
# із 580 МБ від одного `make clean`. Спільне: вимір мусить жити там, де його не дістане
# ані редагування, ані прибирання, ані відкіт.
cache-in-tree:
	$(PY) scripts/validate_no_cache_in_tree.py
	$(PY) scripts/validate_no_cache_in_tree.py --selftest

# Звіт мутацій, що описує ІНШИЙ каталог, виглядає точно як свіжий: двічі за 31.08.2026
# він розійшовся з кодом (379 проти 385, потім 385 проти 390) і обидва рази пережив
# зелений `make validate`. Порівнюється МНОЖИНА ідентифікаторів, а не кількість — обмін
# «один прибрано, інший додано» лічильник не помічає.
# Чи вміє система відрізнити своє питання від чужого — і чи не розучилась. Не в
# `validate`: потрібен ЖИВИЙ сервіс, а `validate` мусить проходити там, де сервісу немає.
# Ганяється нічним таймером korpus-answer-quality.timer.
#   make answer-quality BASE=https://korpus-1.taile5d24a.ts.net/api
# Один вирок над усіма осями відповіді, і він дорівнює НАЙСЛАБШІЙ. Профіль без
# композиції — це дашборд: показує і нічого не забороняє. Не в `validate`: осі
# міряються проти живого сервісу, а `validate` мусить проходити там, де сервісу немає.
# Дві властивості САМОГО корпусу, від яких залежить «показати, ДЕ САМЕ це написано».
# Жоден прогін питань їх не бачить: вимір робиться прямо по базі, що обслуговується.
# Перенести провідний уламок речення до попереднього прольоту, не втративши жодного
# символу й не вивівши проліт за стелю 1400, у якій корпус зібрано. Не в `validate`:
# міняє дані, а не перевіряє їх.
#   make recut-spans DATABASE=... APPLY=1
recut-spans:
	$(PY) scripts/recut_span_boundaries.py --selftest
	$(PY) scripts/recut_span_boundaries.py --database "$(or $(DATABASE),$(SERVED_CORPUS))" $(if $(APPLY),--apply)

corpus-integrity:
	$(PY) scripts/measure_corpus_integrity.py --selftest
	$(PY) scripts/measure_corpus_integrity.py --database "$(or $(DATABASE),$(SERVED_CORPUS))"

answer-axes:
	$(PY) scripts/check_answer_axes.py --selftest
	$(PY) scripts/check_answer_axes.py

# Вимірювачі корпусу, журналу й баз — і лише потім вирок.
#
# Досі їх не кликав НІХТО: п'ять осей профілю мали вимірювача, і жоден лан його не
# запускав, тож звіти вироблялись рукою. Мовчазним це не було — ідентичність входів
# робить вісь UNMEASURED, щойно звіт перестає описувати той самий стан, — але
# «не бреше» і «виконується» це різні твердження, і виконувалось лише перше.
#
# ПОРЯДОК НЕ ДЕКОРАТИВНИЙ. `measure_audit_integrity` іде БЕЗПОСЕРЕДНЬО перед
# `check_answer_axes`: його вхід — голова журналу, а живий сервер рухає її на кожній
# відповіді, тож будь-що між ними робить свіжий звіт несвіжим. `measure_evidence_bases`
# стоїть перед ним, бо він не читає журналу.
corpus-axes:
	$(PY) scripts/measure_corpus_integrity.py --selftest
	$(PY) scripts/measure_corpus_integrity.py --database "$(or $(DATABASE),$(SERVED_CORPUS))"
	$(PY) scripts/validate_derived_source_links.py --selftest
	$(PY) scripts/validate_derived_source_links.py --database "$(or $(DATABASE),$(SERVED_CORPUS))"
	$(PY) scripts/measure_declared_coverage.py --selftest
	$(PY) scripts/measure_declared_coverage.py --database "$(or $(DATABASE),$(SERVED_CORPUS))"
	$(PY) scripts/measure_evidence_bases.py --selftest
	$(PY) scripts/measure_evidence_bases.py
	$(PY) scripts/check_dormant_subsystems.py --selftest
	$(PY) scripts/check_dormant_subsystems.py --database "$(or $(DATABASE),$(SERVED_CORPUS))"
	$(PY) scripts/measure_audit_integrity.py --selftest
	$(PY) scripts/measure_audit_integrity.py --database "$(or $(DATABASE),$(SERVED_CORPUS))" \
	  --key "korpus-public-2026-08-31=$(SECRET_DIR)/audit-key.txt" \
	  --key "legacy-unversioned=$(SECRET_DIR)/audit-key-legacy-unversioned.txt" \
	  --key "serve-public-inline-2026-08=$(SECRET_DIR)/audit-key-serve-public-inline.txt" \
	  --min-attribution 1.0 --max-placeholder-signed 4061
	$(MAKE) answer-axes PY=$(PY)

evidence-bases:
	$(PY) scripts/measure_evidence_bases.py --selftest
	$(PY) scripts/measure_evidence_bases.py

# Підсистеми, які СПЛЯТЬ — оголошено, а не залишено без нагляду. 27 із 35 таблиць бази
# порожні; найбільша група не імпортується жодним маршрутом API. Стан, якого ніхто не
# обирав, виглядає однаково і як задум, і як недогляд.
dormant-subsystems:
	$(PY) scripts/check_dormant_subsystems.py --selftest
	$(PY) scripts/check_dormant_subsystems.py --database "$(or $(DATABASE),$(SERVED_CORPUS))"

# Контрольний сервер на КОПІЇ обслуговуваної бази: наслідок зміни в коді відповіді
# міряється, не чіпаючи те, що обслуговує читача. Порівняння робиться ДВОМА копіями на
# двох портах — перший процес піднімається до правки, другий після, — бо два стани
# одного дерева інакше ніколи не існують одночасно.
#
#   make control-copy PORT=8021 DB=/tmp/ab/A.db TAG=A
control-copy:
	sqlite3 "file:$(SERVED_CORPUS)?mode=ro" "VACUUM INTO '$(DB)'"
	scripts/serve_control_copy.sh "$(or $(PORT),8021)" "$(DB)" "$(or $(TAG),control)"

# Свіжість ПРОЦЕСА, а не звіту. Перше — бо все нижче питає живий сервер, і звіт,
# отриманий від процесу, старшого за код, описує не це дерево. Корпус при цьому той
# самий, вимірювач той самий, вік звіту малий — тобто жодне інше поле цього не ловить.
#
# Виміряно 01.09.2026: усі п'ять обслуговуючих процесів були старші за найновіший файл
# коду, включно з тим, що обслуговує читача. Один із них до того ж віддавав HTTP 500 на
# кожне питання, бо ліниво імпортований модуль підтягнувся вже після правки сигнатури.
serving-freshness:
	$(PY) scripts/check_serving_freshness.py --selftest
	$(PY) scripts/check_serving_freshness.py

answer-quality: serving-freshness
	PYTHONPATH=apps/api/src $(PY) scripts/run_boundary_eval.py $(if $(BASE),--base "$(BASE)")
	$(PY) scripts/check_answer_quality_ratchet.py
	$(PY) scripts/check_answer_quality_ratchet.py --selftest
	$(PY) scripts/run_paraphrase_eval.py --selftest
	PYTHONPATH=apps/api/src $(PY) scripts/run_paraphrase_eval.py $(if $(BASE),--base "$(BASE)")

mutation-report-freshness:
	PYTHONPATH=apps/api/src $(PY) scripts/check_mutation_report_freshness.py
	PYTHONPATH=apps/api/src $(PY) scripts/check_mutation_report_freshness.py --selftest

catalog-uri-uniqueness:
	$(PY) scripts/validate_catalog_uri_uniqueness.py
	$(PY) scripts/validate_catalog_uri_uniqueness.py --selftest

## НЕ входить у `validate` навмисно: гейт червоний на реальному стані журналу (44
## твердження без вироку при бюджеті 12), і це його робота — називати борг, а не
## бути зеленим. Вмикати у validate можна лише коли борг закрито, інакше правило
## почнуть послаблювати, щоб конвеєр був зелений.
agent-protocol:
	$(PY) scripts/agent_protocol.py --selftest
	$(PY) scripts/agent_protocol.py --registry
	-$(PY) scripts/agent_protocol.py --ledger
	#: Перелік незакритих тверджень — вхід приймальника, і саме тому він мусить
	#: запускатися звідси, а не лежати поруч. Тест досяжності скриптів упіймав
	#: його як недосяжний: скрипт, якого ніхто не запускає, не є частиною гейта.
	-$(PY) scripts/open_claims.py --limit 5

## Теж поза `validate`: гейт червоний на двох парах дзеркал, і виправлення — це
## рішення про каталог, а не про код. Зелений він стане тоді, коли пари оголошено.
publication-mirrors:
	$(PY) scripts/validate_publication_mirrors.py --selftest
	$(PY) scripts/validate_publication_mirrors.py

refusal-retryability:
	$(PY) scripts/validate_refusal_retryability.py --selftest
	$(PY) scripts/validate_refusal_retryability.py

# Not a gate: it needs the network, so it can never run in CI. It measures what each
# zakon.rada URL actually returns — the card variant carries the act's title and none of
# its text — and records the measurement as content_probe. doctrine-catalog then holds
# offline that source_uri is the variant the measurement found richest. Re-run when a
# source is added or an act is amended; the recorded probe date says when it last ran.
source-probe:
	PYTHONPATH=apps/api/src $(PY) scripts/probe_source_content.py

# The bridge from bibliography to corpus: fetch every ingestible source at the URI the
# content probe measured as richest, run each download through this system's own extractor,
# and emit the import manifest. Nothing is approved — every version lands in quarantine,
# because approval is a person taking responsibility in the audit chain. Network-bound, so
# never a gate; `make import-corpus MANIFEST=var/doctrine-staging/manifest.json` is next.
doctrine-staging:
	PYTHONPATH=apps/api/src $(PY) scripts/stage_doctrine_corpus.py --out var/doctrine-staging

source-probe-write:
	PYTHONPATH=apps/api/src $(PY) scripts/probe_source_content.py --write

retention-plan:
	PYTHONPATH=apps/api/src $(PY) scripts/plan_retention.py

# AUD-004's executable half. The closure register cited this script as evidence and
# nothing ran it — a citation that names a file rather than a run, which is the shape
# ADR-0008 exists to refuse. `--limit 0` makes it a smoke run against whatever chain is
# present: the batch is empty, and an empty batch is the ordinary case, not a failure.
# A review session over a LAN: the real nginx edge, the API in jwt mode, a short-lived
# token. `auth_mode=dev` trusts whoever connects and is refused on any non-loopback bind
# for exactly that reason, so showing this to people who are not at this keyboard needs
# a signed token rather than a wider bind.
#
# In jwt mode the token *carries* the entitlements — the server-side profile projects
# identity only under oidc, which controlled environments require. Whoever holds the
# token holds what is written in it, which is why it is short-lived and why the secret
# is mode 600.
# Bring a directory of documents into the corpus. Every version lands in quarantine:
# approval is a person taking responsibility in the audit chain under their own name,
# and a bulk importer that granted it would forge that signature at scale.
#   make import-corpus MANIFEST=path/to/manifest.json
# Pull a Drive folder into a local snapshot with provenance. One-time setup on the
# operator's own hands: `rclone config` -> new remote named `drive`, type `drive`,
# scope 2 (read-only). Fetching is not ingestion: a live dependency would let a document
# change after it was reviewed.
#   make drive-snapshot FOLDER_ID=... INTO=var/corpus/ml
drive-snapshot:
	$(PY) scripts/fetch_drive_snapshot.py --remote $(or $(REMOTE),drive:) \
	  --folder-id "$(FOLDER_ID)" --into "$(or $(INTO),var/corpus)"

# The same snapshot, for a folder shared with "anyone with the link". No OAuth, no
# account, no rclone: Drive's own web viewer reads such a folder through a browser key
# the folder page carries, and this asks the same question the same way. A folder that
# is not public simply does not answer.
#   make drive-public FOLDER_ID=... INTO=var/corpus/ml MAX_FILE_BYTES=2000000
drive-public:
	$(PY) scripts/fetch_drive_public.py --folder-id "$(FOLDER_ID)" \
	  --into "$(or $(INTO),var/corpus)" \
	  $(if $(MAX_FILE_BYTES),--max-file-bytes $(MAX_FILE_BYTES)) $(if $(LIMIT),--limit $(LIMIT))

# Publish the read-only reader on a public edge that authenticates on the visitor's
# behalf. Everything reachable through it is public by decision, not by default.
#   make serve-public
serve-public:
	bash scripts/serve_public.sh

# Форма публічної поверхні, а не її життя і не якість її відповідей.
# `public_health_controller` питає «чи воно живе», `answer-quality` — «чи добре
# відповідає»; між ними лишалася діра: де слухає, що віддає, яку особу підставляє,
# що пропускає вглиб. НЕ в `validate`: вимір проти живого сервісу не належить гейту,
# який мусить проходити там, де сервісу немає. `--direct-token` обов'язковий, інакше
# 401 дасть UNKNOWN — невпізнаний відвідувач нічого не доводить про роль.
# Що саме означає «дерево зелене». Виміряно 31.08.2026: 193 цілі, 44 перевірочних,
# 27 не виконуються під `check`. Гейт не закриває ті 27 — він робить кожну з них
# РІШЕННЯМ із причиною і датою замість тиші, і не пускає двадцять восьму.
#
# Стоїть у `validate` навмисно: гейт про покриття гейтами, який сам не під гейтом,
# був би першим спростуванням власного твердження.
# Два оголошення оточення публічного API — скрипт і юніт systemd — не сміють
# розійтися. Копії дві навмисно (юніт мусить бути самооголошеним), тож замість
# єдиного джерела тут гейт: кожна різниця мусить бути названою.
public-env-parity:
	$(PY) scripts/check_public_env_parity.py

public-env-parity-selftest:
	$(PY) scripts/check_public_env_parity.py --selftest

gate-closure:
	$(PY) scripts/verify_gate_closure.py

gate-closure-selftest:
	$(PY) scripts/verify_gate_closure.py --selftest

public-surface:
	$(PY) scripts/verify_public_surface.py \
	  $(if $(BASE),--base "$(BASE)") $(if $(DIRECT),--direct-base "$(DIRECT)") \
	  $(if $(TOKEN),--direct-token "$(TOKEN)") $(if $(RENDERED),--rendered "$(RENDERED)")

public-surface-selftest:
	$(PY) scripts/verify_public_surface.py --selftest

# Keep a public HTTPS address pointed at the edge, and write the current one to
# var/public/URL. The provider assigns the hostname per session and rotates it on every
# reconnect, so the file is the address of record and an empty file means there is none.
#   make public-tunnel
public-tunnel:
	bash scripts/public_tunnel.sh

# Draft a manifest from a fetched directory. Everything it cannot read from a filename —
# issuer, revision, publication date — is marked REVIEW_REQUIRED, and import-corpus
# refuses those entries.
#   make draft-manifest ROOT=var/corpus/ml OUT=var/corpus/ml/manifest.json
draft-manifest:
	$(PY) scripts/build_import_manifest.py --root "$(ROOT)" --out "$(OUT)" \
	  $(if $(ISSUER),--issuer "$(ISSUER)") $(if $(AUTHORITY),--authority "$(AUTHORITY)") \
	  $(if $(FROM_SNAPSHOT),--from-snapshot)

import-corpus:
	PYTHONPATH=apps/api/src $(PY) scripts/import_corpus.py --manifest "$(MANIFEST)" $(IMPORT_FLAGS)

corpus-admission:
	test -n "$(MANIFEST)"
	test -n "$(ROOT)"
	PYTHONPATH=apps/api/src $(PY) scripts/audit_corpus_admission.py --manifest "$(MANIFEST)" --root "$(ROOT)" $(if $(OUT),--out "$(OUT)")

gold-annotation-audit:
	test -n "$(LEDGER)"
	PYTHONPATH=apps/api/src $(PY) scripts/audit_gold_annotations.py --ledger "$(LEDGER)" $(if $(OUT),--out "$(OUT)")

review-token:
	PYTHONPATH=apps/api/src $(PY) scripts/mint_review_token.py \
	  --subject $(or $(SUBJECT),reviewer) \
	  --minutes $(or $(MINUTES),120) \
	  --roles $(or $(ROLES),user) \
	  --clearance $(or $(CLEARANCE),public) \
	  --corpora $(or $(CORPORA),public)

audit-export:
	PYTHONPATH=apps/api/src $(PY) scripts/export_audit.py --limit $(or $(LIMIT),1000)

# Під ТИМ САМИМ оточенням, що й сервіс. Без цього гейт брав типові значення
# `Settings` і читав базу РОЗРОБНИКА, а вирок «external audit anchor is ahead of the
# database head» описував не журнал, а дві різні бази під одним якорем.
audit-verify:
	$(PY) scripts/check_public_env_parity.py --exec $(PY) scripts/verify_audit.py

handoff-verify:
	PYTHONPATH=apps/api/src $(PY) scripts/verify_handoff_contract.py

# The release-shaped form: refuses release evidence that describes another tree, or none at
# all. Separate from handoff-verify because BOUND needs the full evidence cycle — the
# PostgreSQL recovery drill included — and `make validate` has to stay passable on a
# machine without a database. A gate nobody can pass gets deleted, not satisfied.
handoff-verify-bound:
	PYTHONPATH=apps/api/src $(PY) scripts/verify_handoff_contract.py --require-bound


openapi:
	PYTHONPATH=apps/api/src $(PY) scripts/openapi_contract.py

audit-closure:
	PYTHONPATH=apps/api/src:scripts $(PY) scripts/build_audit_closure.py

desired-state:
	python3 scripts/generate_desired_state.py --check

# $(PY), not python3: this reads license metadata from the installed distributions, so
# a bare interpreter resolves whichever packages happen to be on the system — five of
# sixty-eight, when this was written. The lock is the environment it must be asked in.
supply-chain-inventory:
	PYTHONPATH=apps/api/src $(PY) scripts/generate_supply_chain_inventory.py

kubernetes-validate:
	python3 scripts/validate_kubernetes.py

github-actions-validate:
	PYTHONPATH=apps/api/src $(PY) scripts/validate_github_actions.py

.PHONY: public-web-deploy
public-web-deploy:
	$(PY) scripts/deploy_public_web.py

.PHONY: agent-runtime-install public-runtime-install public-watchdog-install public-health
agent-runtime-install:
	python3 scripts/install_agent_runtime.py

public-runtime-install:
	python3 scripts/install_public_runtime.py

public-watchdog-install:
	python3 scripts/install_public_watchdog.py

public-health:
	python3 scripts/public_health_controller.py --observe-only

# audit-closure is deliberately NOT here: it resolves citations that include
# var/mutation-report.json, which `mutation` produces. As a prerequisite of `validate`
# it ran first and passed only on a tree where an earlier run had left the file behind.
validate: public-env-parity gate-closure selftest-coverage mutation-report-freshness handoff-verify openapi desired-state supply-chain-inventory dependency-locks assurance-model-check standards-control-map import-cycles release-identity module-budget file-modes source-manifest-verify current-truth-verify verdict-ledger requirements-register doctrine-catalog content-signals remote-digest document-probe evidence-refusal cache-in-tree catalog-uri-uniqueness publication-mirrors refusal-retryability github-actions-validate production-hard-predicates
	python3 scripts/validate_repository.py --context FULL_SSOT_DISTRIBUTION
	python3 scripts/validate_infrastructure.py
	python3 scripts/validate_kubernetes.py

infra-validate:
	python3 scripts/validate_infrastructure.py

backup-postgres:
	scripts/backup_postgres.sh

restore-postgres:
	scripts/restore_postgres.sh "$(BACKUP)"

# The deployment that is actually serving holds its corpus in SQLite: 1616 documents and
# 116 229 spans that took five hours to build, on one disk with no replica. `VACUUM INTO`
# takes a consistent snapshot while the reader is served; the object store travels with
# it, because a corpus database without the objects it names restores to a system that
# cites passages nobody can open.
#   KORPUS_BACKUP_ENCRYPTION_KEY_FILE=... KORPUS_BACKUP_KEY_ID=... make backup-sqlite
sqlite-recovery-drill:
	PYTHONPATH=apps/api/src:scripts PYTHON=$(PY) scripts/run_sqlite_recovery_drill.sh

backup-sqlite:
	scripts/backup_sqlite.sh

# Load, spike and soak against a running deployment, with the conditions recorded beside
# the numbers. SRE-005 and RAG-014 both say the same thing: scale evidence produced
# against a fixture is evidence about the fixture.
#   make load-probe BASE=http://127.0.0.1:8000 TOKEN=...
# Break each dependency in turn and record what the system says. A fail-closed claim is a
# claim about behaviour under failure, and this tree had tested every dependency present
# and none absent.
# Every scanner the pipeline declares, run here, with the reports archived beside their
# exit codes. A declared scanner is a plan; an archived report is evidence.
# Freeze what the corpus contains and sign it, so a citation can be traced to the release
# it came from without the running system. Verifying against a restored backup is how a
# rollback is proved to have landed.
#   make corpus-release OUT=var/releases/$(shell date +%F).json SIGNER="..."
corpus-release:
	$(PY) scripts/corpus_release.py freeze --out "$(OUT)" \
	  $(if $(DATABASE),--database "$(DATABASE)") $(if $(SIGNER),--signer "$(SIGNER)") \
	  $(if $(KEY_FILE),--key-file "$(KEY_FILE)")

corpus-release-verify:
	$(PY) scripts/corpus_release.py verify --manifest "$(MANIFEST)" \
	  $(if $(DATABASE),--database "$(DATABASE)") $(if $(KEY_FILE),--key-file "$(KEY_FILE)")

# What this deployment promises, checked against what it was measured doing. An objective
# nobody checks is a paragraph.
# Freeze a reference set from the deployed corpus, stratified and digest-sealed, and run
# it. Objective on retrieval, citation integrity and refusal; silent on whether an answer
# is good, which needs annotators (RAG-003).
#   make reference-set && make reference-eval TOKEN=...
# Say what an image was built from, sign it, and refuse to deploy what does not verify.
# An SBOM travelling beside an image answers "what is in some image".
#   make provenance IMAGE=korpus-api:local OUT=var/provenance/api.json
provenance:
	$(PY) scripts/build_provenance.py attest --image "$(IMAGE)" --out "$(OUT)" \
	  $(if $(SBOM),--sbom "$(SBOM)") $(if $(KEY_FILE),--key-file "$(KEY_FILE)")

provenance-verify:
	$(PY) scripts/build_provenance.py verify --statement "$(STATEMENT)" \
	  $(if $(IMAGE),--image "$(IMAGE)") $(if $(SBOM),--sbom "$(SBOM)") \
	  $(if $(KEY_FILE),--key-file "$(KEY_FILE)")

## Тип документа — вхід стратифікації набору оцінювання. Імпорт його губить, тож
## перед перезбиранням набору тип повертається з каталогу. Без --apply лише показує.
## Порівняння конфігурацій пошуку й перепривʼязка версій набору — інструменти виміру,
## не гейти. Цілі потрібні, бо скрипт без раннера тест досяжності не вважає частиною
## системи, і має рацію: його ніхто не запустить і ніхто не помітить, що він зламався.
compare-retrieval:
	@test -n "$(BASE)" || { echo "вжиток: make compare-retrieval BASE=http://127.0.0.1:8000 TOKEN=..." >&2; exit 64; }
	$(PY) scripts/compare_retrieval_configs.py --base "$(BASE)" $(if $(TOKEN),--token "$(TOKEN)")

remap-reference-versions:
	@test -n "$(DATABASE)" || { echo "вжиток: make remap-reference-versions DATABASE=..." >&2; exit 64; }
	$(PY) scripts/remap_reference_versions.py --database "$(DATABASE)"

## Локальний семантичний рушій для перевірки гібридного пошуку.
serve-semantic-local:
	bash scripts/serve_semantic_local.sh

## Гігієна прольотів. Не в `validate`: потребує бази. Але червоний він по ділу —
## екранована розмітка в ЦИТОВНОМУ прольоті означає, що солдату можуть віддати
## `&lt;p>` як доказ, із хешем і посиланням.
## Дві діагностики гіпотез про пошук: чи запит розводиться зайвими словами і чи
## є розмірний зсув. Не гейти — інструменти виміру, але раннер потрібен, бо
## скрипт без нього ніхто не запустить і ніхто не помітить, що він зламався.
## Корпус, який публічний сайт РЕАЛЬНО подає. Типове значення, а не обовʼязковий
## аргумент: перевірка, яку не запустили, і перевірка, якої немає, з відстані
## однакові.
SERVED_CORPUS ?= var/runtime/corpus-v6-20260807/korpus.db
# Ключі журналу живуть ПОЗА деревом: `zip -r korpus .` не сміє винести підпис доказу.
SECRET_DIR ?= $(if $(XDG_STATE_HOME),$(XDG_STATE_HOME),$(HOME)/.local/state)/korpus-public
SERVED_OBJECTS ?= var/runtime/corpus-v6-20260807/objects

## Обидві діагностики питають ЖИВИЙ API, а не базу: вони міряють, що система
## відповідає, а не що в ній лежить. Раннер передавав їм `--database`, якого жодна з
## них не приймає, тож `make diagnose-retrieval` падав на першому рядку — раннер,
## написаний щоб помітити зламаний скрипт, був зламаний сам.
diagnose-retrieval:
	@test -n "$(BASE)" || { echo "вжиток: make diagnose-retrieval BASE=http://127.0.0.1:8000 TOKEN=<jwt> [DATABASE=$(SERVED_CORPUS)]" >&2; exit 64; }
	$(PY) scripts/diagnose_query_dilution.py --base "$(BASE)" --token "$(TOKEN)"
	$(PY) scripts/diagnose_size_bias.py --base "$(BASE)" --token "$(TOKEN)" --database "$(or $(DATABASE),$(SERVED_CORPUS))"

## Ремонт уже збережених прольотів. Не гейт: він ПИШЕ. Без APPLY=1 лише показує,
## і відмовляється чіпати проліт, у якому ремонт зʼїв би саме речення.
repair-span-markup:
	$(PY) scripts/repair_span_markup.py --selftest
	$(PY) scripts/repair_span_markup.py --database "$(or $(DATABASE),$(SERVED_CORPUS))" $(if $(APPLY),--apply)

## Бенчмарк предметної точності. Не гейт: потребує піднятого API. Але число з нього
## — головне, що ця система має показувати замість обіцянок: чи відповідь про того,
## кого спитали. Базова лінія 31.08.2026: top1 = 0.000 на 92 оголошених предметах,
## і впевненість ПЕРЕВЕРНУТА — на хибних відповідях покриття вище, ніж на правильних.
subject-precision:
	$(PY) scripts/benchmark_subject_precision.py --selftest
	@test -n "$(BASE)" || { echo "вжиток: make subject-precision BASE=http://127.0.0.1:8000 [DATABASE=...]" >&2; exit 64; }
	$(PY) scripts/benchmark_subject_precision.py --base "$(BASE)" --database "$(or $(DATABASE),$(SERVED_CORPUS))"
# Друга форма питання. Еталон питає НАЗИВНИМ, бо роль береться із заголовка як є;
# людина питає РОДОВИМ. Виміряно 01.09.2026: називний 14/14, родовий 1/14 — тобто
# перше число правдиве про свій розподіл входу й мовчить про той, який справді буде.
	$(PY) scripts/benchmark_subject_precision.py --base "$(BASE)" --inflected \
	  --out var/subject-inflection.json

## Скільки баз доказів існує — і чи та, яку подають, є тією, яку назвали. Виміряно
## 01.09.2026: шість сховищ форми «докази», з них порожнє на типовому шляху
## налаштувань і постгрес із тими самими 256 документами, але іншою нарізкою.
## Негативний контроль, який не бігає, негативним контролем не є. Виміряно 01.09.2026:
## 31 скрипт оголошує `--selftest`, і 22 не виконувались ЖОДНОЮ дорогою — серед них
## саме ті, що доводять здатність гейтів червоніти. Разом 1,8 с. Переліку тут немає
## навмисно: гейт САМ знаходить кожен такий скрипт і САМ його запускає, тож стан
## «самоперевірку забули підключити» перестає існувати, а не стає піднаглядним.
selftest-coverage:
	$(PY) scripts/verify_selftest_coverage.py --selftest
	$(PY) scripts/verify_selftest_coverage.py

## Чи те, що ВСТАНОВЛЕНО на машині, є тим, що описує дерево. Виміряно 01.09.2026:
## встановлений `korpus-public-api.service` має `EnvironmentFile=`, а шаблон у дереві
## самооголошений — тобто гейт паритету звіряв дві копії, жодна з яких не виконується.
## Стоїть ОСТАННІМ у нічному лані свідомо: відмова тут правдива, але вона не сміє
## засліпити все, що вимірюється до неї.
installed-units-verify:
	$(PY) scripts/verify_installed_units.py --selftest
	$(PY) scripts/verify_installed_units.py

## Що саме означає «канонічне». Виміряно 01.09.2026: кандидатів ТРИ — локальна гілка,
## `main` і опубліковане на GitLab — і вони розходились на 105–125 комітів, а жодна
## перевірка цього не бачила. `--fetch` навмисно: порівнювати з невідомо коли
## оновленими посиланнями означало б міряти власну пам'ять, а не стан світу.
## Одна канонічна гілка — або НАЗВАНИЙ перелік того, що поза нею. Виміряно 01.09.2026:
## локальні гілки всі мають нуль унікальних комітів, а на origin лежать 21 гілка з
## 18–355 власними комітами і п'ятьма спроможностями, яких у каноні немає ЖОДНОЮ
## згадкою. Автоматично зливається рівно одна: решту тримає зіткнення номерів міграцій,
## якого git не бачить, бо файли різні.
branch-integration:
	$(PY) scripts/verify_branch_integration.py --selftest
	$(PY) scripts/verify_branch_integration.py

canonical-verify:
	$(PY) scripts/verify_canonical_state.py --selftest
	$(PY) scripts/verify_canonical_state.py --fetch

evidence-stores:
	$(PY) scripts/verify_evidence_stores.py --selftest
	$(PY) scripts/verify_evidence_stores.py

span-hygiene:
	$(PY) scripts/validate_span_hygiene.py --selftest
	$(PY) scripts/validate_span_hygiene.py --database "$(or $(DATABASE),$(SERVED_CORPUS))"

## Сторінка, яку видавець САМ оголосив невідображеною, не є документом. Пʼять
## документів корпусу мають авторитетну назву й жодного рядка нормативного тексту,
## серед них Стройовий статут ЗСУ і накази з переліками ВОС.
fetch-stubs:
	$(PY) scripts/validate_fetch_stubs.py --selftest
	$(PY) scripts/validate_fetch_stubs.py --database "$(or $(DATABASE),$(SERVED_CORPUS))" --objects "$(or $(OBJECTS),$(dir $(SERVED_CORPUS))objects)"

restore-document-types:
	$(PY) scripts/restore_document_types.py --selftest
	@test -n "$(DATABASE)" || { echo "вжиток: make restore-document-types DATABASE=... [APPLY=1]" >&2; exit 64; }
	$(PY) scripts/restore_document_types.py --database "$(DATABASE)" $(if $(APPLY),--apply)

reference-set:
	$(PY) scripts/build_reference_set.py $(if $(DATABASE),--database "$(DATABASE)")

reference-eval:
	$(PY) scripts/run_reference_eval.py $(if $(BASE),--base "$(BASE)") $(if $(TOKEN),--token "$(TOKEN)")

embedding-candidate-screen:
	$(PY) scripts/run_embedding_candidate_screen.py

embedding-backfill:
	PYTHONPATH=apps/api/src $(PY) scripts/run_embedding_backfill.py

## Той самий крок, але для SQLite-рантайму: `run_embedding_backfill.py` іде в
## PostgreSQL і на рантайм-корпусі незастосовний. Ціль потрібна ще й тому, що
## скрипт без раннера тест досяжності вважає не частиною системи — і має рацію.
embedding-backfill-sqlite:
	@test -n "$(DATABASE)" || { echo "вжиток: make embedding-backfill-sqlite DATABASE=/шлях/до/korpus.db" >&2; exit 64; }
	PYTHONPATH=apps/api/src $(PY) scripts/backfill_span_embeddings_sqlite.py --database "$(DATABASE)"

## Складач маніфесту рантайм-корпусу. Не гейт і не в `validate`: він БУДУЄ дані,
## а не судить їх, і потребує шляху до перевіреного корпусу. Але ціль тут мусить
## бути: скрипт, якого не запускає жоден раннер, не є частиною системи — це
## документація у вигляді коду, і тест досяжності ловить саме це.
runtime-corpus-manifest:
	@test -n "$(SOURCE)" || { echo "вжиток: make runtime-corpus-manifest SOURCE=/шлях/до/corpus.sqlite" >&2; exit 64; }
	$(PY) scripts/build_runtime_manifest.py --source "$(SOURCE)" $(if $(OUT),--out "$(OUT)")

# Типове — ОБСЛУГОВУВАНИЙ корпус, як уже зроблено в `corpus-integrity`. Ціль, що
# вимагає аргументу, не може бути частиною беззастережного прогону, і саме тому вона
# роками не бігла: не через дефект, а через те, що її ніхто не міг запустити без
# додаткового знання.
runtime-corpus-audit:
	$(PY) scripts/audit_runtime_corpus.py --database "$(or $(DATABASE),$(SERVED_CORPUS))" \
	  --object-root "$(or $(OBJECT_ROOT),$(SERVED_OBJECTS))" $(if $(OUT),--out "$(OUT)")

service-objectives:
	$(PY) scripts/service_objectives.py $(if $(MEASUREMENTS),--measurements "$(MEASUREMENTS)")

# Backup copies, evidence retention and quotas, checked against the disk. A policy in a
# document is a sentence.
retention-policy:
	$(PY) scripts/retention_policy.py

# Gate reports kept under their digest for the system's life, not the pipeline's.
evidence-registry:
	$(PY) scripts/evidence_registry.py

# How long a known vulnerability may stay here, and whether the scan that would find it
# actually ran. A scanner that exited 127 is neither clean nor a finding.
patch-policy:
	$(PY) scripts/patch_policy.py

security-scan:
	scripts/security_scan.sh

# Build twice from one tree and say which layers disagree. The recorded nondeterminism is
# the part usually skipped, and skipping it is how "reproducible" becomes a word.
reproducible-build:
	scripts/reproducible_build_probe.sh

chaos-matrix:
	PYTHONPATH=.:apps/api/src $(PY) scripts/chaos_matrix.py

# Kill a corpus import partway and prove the resumed run reconciles by content with an
# uninterrupted one. "Resumable" was a property of the design until this executed it.
#   make ingestion-drill MANIFEST=var/corpus/ml-manifest.json ROOT=var/corpus/ml
ingestion-drill:
	$(PY) scripts/ingestion_recovery_drill.py --manifest "$(MANIFEST)" --root "$(ROOT)" \
	  --workdir "$(or $(WORKDIR),var/drill)" $(if $(DOCUMENTS),--documents $(DOCUMENTS))

load-probe:
	$(PY) scripts/load_probe.py $(if $(BASE),--base "$(BASE)") $(if $(TOKEN),--token "$(TOKEN)") \
	  $(if $(CONCURRENCY),--concurrency $(CONCURRENCY)) $(if $(SPIKE),--spike $(SPIKE)) \
	  $(if $(SECONDS),--seconds $(SECONDS)) $(if $(SOAK_SECONDS),--soak-seconds $(SOAK_SECONDS))

# Restores somewhere else on purpose: a drill that overwrites the live corpus is a drill
# nobody runs, and one that never runs is not known to work.
#   make restore-sqlite BACKUP=var/backups/sqlite/korpus-<stamp>.tar.enc INTO=var/restored
restore-sqlite:
	scripts/restore_sqlite.sh "$(BACKUP)" "$(or $(INTO),var/restored)"

# Другий вхід, і саме його бракувало. `check` доводить властивості ДЕРЕВА і мусить
# проходити там, де ні корпусу, ні сервісу немає. Гейти, що міряють РОЗГОРТАННЯ —
# обслуговуваний корпус, його журнал, його прольоти — не могли стояти в ньому, і тому
# не стояли ніде: `span-hygiene` був червоний ще до 31.08.2026 і не червонив нічого.
#
# Ці два входи НЕ взаємозамінні: зелений `check` нічого не каже про розгортання, а
# зелений `check-deployment` — про дерево. Плутати їх означає повернутись до «зелено»
# без означення.
# Третій вхід: те, що дороге ЗА ПОБУДОВОЮ і тому не належить у прогін перед злиттям.
# Кожна з цих цілей копіює дерево або переганяє повний набір: `gate-liveness` мутує
# самі гейти в копіях, `verify-clean-clone` збирає репозиторій з нуля, `mutation-probe`
# шукає мутації ПОЗА каталогом випадковою вибіркою (виміряно: понад 420 с без стелі),
# `coverage-ratchet` повторно тягне api-test (235 с).
#
# Це не «менш важливе». Це інший БЮДЖЕТ ЧАСУ, і без власного лану воно не бігло ніколи.
install-nightly-gates:
	$(PY) scripts/install_nightly_gates.py

# ПОРЯДОК тут не косметика. `handoff-verify` — єдиний із дев'яти гейтів живучості,
# чий «чистий стан» не є властивістю ДЕРЕВА: він властивість ПАРИ (дерево, докази).
# Решта вісім міряють вміст і самодостатні. Запускати `gate-liveness` у довільний
# момент означає ловити його червоним щоразу, коли хтось закомітив після останнього
# прогону ланцюга — і читати правдиву доповідь проби як ваду харнесу. Саме так я
# 31.08 прочитав ARMED 8/9 і мало не поліз копіювати `.git`; переліки файлів із git і
# з обходу теки виявились тотожними (1677 = 1677), тобто гіпотеза була хибна, а проба
# казала рівно те, що написано.
#
# Тому лан спершу ОНОВЛЮЄ докази, а потім міряє живучість. 9/9 стає досяжним станом,
# а не стелею, і докази заразом свіжішають щоночі.
# Що лан ВИМІРЯВ, а що просто не встиг. `make` спиняється на першій відмові, тож ціль,
# поставлена після червоної, не боронить нічого й виглядає так само, як зелена.
# Виміряно 01.09.2026: `validate` падав на ТРЕТІЙ цілі з 30 і називав одну проблему;
# бігун показав ТРИ — `current-truth-verify` і `cache-in-tree` не бачив ніхто.
lane-report:
	$(PY) scripts/run_lane.py --selftest
	$(PY) scripts/run_lane.py --lane "$(or $(LANE),validate)"

check-nightly:
# ПЕРШИМ, і це не порядок за смаком: гейт про недосяжність сам мусить бути досяжним.
# Поставлений після чогось червоного, він розділив би долю тих 26, про які й розповідає.
	$(MAKE) lane-report PY=$(PY)
	$(MAKE) nightly-evidence PY=$(PY)
	$(MAKE) check-deployment PY=$(PY)
	$(MAKE) load-probe PY=$(PY) SECONDS=8 SOAK_SECONDS=8 CONCURRENCY=3 SPIKE=8
	$(MAKE) corpus-axes PY=$(PY)
	$(MAKE) gate-liveness PY=$(PY)
	$(MAKE) mutation-probe PY=$(PY)
	$(MAKE) verify-clean-clone PY=$(PY)
	$(MAKE) coverage-ratchet PY=$(PY)
	$(MAKE) package PY=$(PY)
	$(MAKE) installed-units-verify PY=$(PY)
	$(MAKE) canonical-verify PY=$(PY)
	$(MAKE) branch-integration PY=$(PY)

# Мутація — ОСТАННІЙ продюсер: її звіт єдиний в'яжеться до дайджесту джерела, тож
# будь-що після неї робить його звітом про інше дерево.
nightly-evidence:
	$(MAKE) api-test PY=$(PY)
	$(MAKE) eval PY=$(PY)
	$(MAKE) migration-gate PY=$(PY)
	$(MAKE) scale PY=$(PY)
	PYTHONPATH=apps/api/src PYTHON=$(PY) KORPUS_MUTATION_SHARDS=6 scripts/run_mutation_shards.sh
	$(MAKE) operational-gate PY=$(PY)
	$(MAKE) assemble-assurance PY=$(PY)
	$(MAKE) snapshot PY=$(PY)
	$(MAKE) evidence-refresh PY=$(PY)

check-deployment: runtime-corpus-audit corpus-integrity audit-verify deployment-debt evidence-stores

deployment-debt:
	$(PY) scripts/check_deployment_debt.py

deployment-debt-selftest:
	$(PY) scripts/check_deployment_debt.py --selftest

# Три цілі, які я сам записав у реєстр як «довгі експерименти», не вимірявши їх.
# Вимір: determinism 6 с, stress 13 с, plasticity 1 с — двадцять секунд разом, і всі
# рівня ДЕРЕВА (проходять у чистому worktree без runtime-корпусу). Класифікація за
# рецептом замість заміру дала три хибні записи; реєстр 25 → 22.
check: validate api-test api-lint eval mutation audit-closure migration-gate scale operational-gate determinism-gate stress-gate plasticity-gate web-build

release: assurance snapshot validate handoff-verify-bound package

infra-secrets:
	bash scripts/init_local_secrets.sh

infra-up: infra-secrets
	docker compose up -d --wait web worker

infra-support: infra-secrets
	docker compose up -d --wait postgres minio otel-collector migrate minio-init

infra-down:
	docker compose down

## Пакування і БЕЗПЕКА пакета — одне діло. `zip_safety.py` існував із тестами й ніколи
## не дивився на зіп, який ми самі роздаємо: ціль `zip-safety-verify` вимагала ARCHIVE,
## а шлях архіву не був відомий жодному лану. Тепер ім'я приходить із `dist/LATEST`,
## яке пише сам пакувальник — одне джерело імені, не друга копія правила.
package:
	bash scripts/package_repository.sh
	PYTHONPATH=apps/api/src:. $(PY) scripts/zip_safety.py "$$(cat dist/LATEST)"

# `clean` прибирає ЛИШЕ те, що відтворюється безкоштовно: кеші й артефакти збірки.
# Раніше цей самий рядок ніс `var`, і одного запуску як НЕГАТИВНОГО КОНТРОЛЮ до правки
# самої цілі вистачило, щоб знести 50 МБ бази доктрини (7608 спанів) і 530 МБ захоплених
# байтів чужої сесії. Та дія була перевірена на тому, що вона МАЛА зробити, і не
# перевірена на тому, що вона робить ЩЕ.
#
# Тому знищення СТАНУ винесене в окрему ціль із підтвердженням. Це не обережність —
# обережність не працює о сьомій ранку. Це конструкція: щоб знести стан, треба назвати
# інше слово й підтвердити, а `clean` цього більше не вміє за жодних обставин.
clean:
	rm -rf htmlcov coverage.xml dist apps/web/dist apps/web/.next
	find . -type d \( -name .pytest_cache -o -name .mypy_cache -o -name .ruff_cache \
	  -o -name __pycache__ \) -not -path './.git/*' -prune -exec rm -rf {} +
	@echo "clean: кеші й артефакти збірки прибрано; var/ НЕ чіпався (див. clean-state)"

# Знищує СТАН: бази, захоплені байти, проміжні прогони. Це те, що коштує годин, а не
# секунд, і чого немає в git. Вимагає CONFIRM=DESTROY-STATE у командному рядку — не
# тому, що хтось неуважний, а тому, що ціна помилки тут вимірюється в мегабайтах
# чужої роботи, і жодне попередження в тексті цього не спинить.
clean-state:
	@test "$(CONFIRM)" = "DESTROY-STATE" || (echo >&2 \
	  "ВІДМОВЛЕНО: clean-state знищує var/ — бази, захоплені байти, прогони."; \
	  echo >&2 "Нічого з цього немає в git. Запусти: make clean-state CONFIRM=DESTROY-STATE"; \
	  exit 2)
	@du -sh var 2>/dev/null || true
	rm -rf var
	@echo "clean-state: var/ знищено"

# Production assurance is deliberately separate from local research assurance.
# These targets generate evidence; the final assembler still fails unless every
# required gate is current, release-bound and of the required evidence class.
production-engineering:
	PYTHONPATH=apps/api/src:scripts $(PY) scripts/run_engineering_production_gate.py

production-tevv:
	PYTHONPATH=apps/api/src:scripts $(PY) scripts/run_tevv_production_gate.py

production-observability:
	PYTHONPATH=apps/api/src:scripts $(PY) scripts/verify_observability_contract.py

production-state-contracts:
	PYTHONPATH=apps/api/src:scripts $(PY) scripts/export_state_contracts.py

production-authorization:
	PYTHONPATH=apps/api/src:scripts $(PY) scripts/export_authorization_matrix.py

production-redteam-internal:
	PYTHONPATH=apps/api/src:scripts $(PY) scripts/run_pytest_campaign.py config/assurance/redteam-internal-v1.json

production-redteam-external:
	PYTHONPATH=apps/api/src:scripts $(PY) scripts/validate_external_redteam_evidence.py

production-inference-security:
	PYTHONPATH=apps/api/src:scripts $(PY) scripts/run_inference_security_gate.py

production-reliability-internal:
	PYTHONPATH=apps/api/src:scripts $(PY) scripts/run_pytest_campaign.py config/assurance/reliability-internal-v1.json

production-reliability:
	PYTHONPATH=apps/api/src:scripts $(PY) scripts/run_reliability_gate.py

production-postgres-security:
	PYTHONPATH=apps/api/src:scripts $(PY) scripts/run_postgres_security_gate.py

production-exact-environment:
	PYTHONPATH=apps/api/src:scripts $(PY) scripts/run_exact_environment_gate.py

production-hard-predicates:
	PYTHONPATH=apps/api/src:scripts $(PY) scripts/verify_production_hard_predicates.py

production-sbom:
	PYTHONPATH=apps/api/src:scripts $(PY) scripts/generate_lock_sbom.py

production-supply-chain: dependency-locks
	PYTHONPATH=apps/api/src:scripts $(PY) scripts/build_supply_chain_evidence_manifest.py
	PYTHONPATH=apps/api/src:scripts $(PY) scripts/run_supply_chain_gate.py

production-mutation:
	PYTHONPATH=apps/api/src:scripts $(PY) scripts/run_mutation_production_gate.py

production-assurance:
	PYTHONPATH=apps/api/src:scripts $(PY) scripts/assemble_production_assurance.py

production-assurance-verify:
	PYTHONPATH=apps/api/src:scripts $(PY) scripts/verify_production_assurance.py

production-release: production-assurance
	test -n "$(KORPUS_PRODUCTION_ASSURANCE_SIGNING_KEY)"
	test -n "$$KORPUS_TRUSTED_PRODUCTION_ASSURANCE_SIGNER_SHA256"
	test -n "$$KORPUS_TRUSTED_RELEASE_SIGNER_SHA256"
	test "$$KORPUS_TRUSTED_PRODUCTION_ASSURANCE_SIGNER_SHA256" != "$$KORPUS_TRUSTED_RELEASE_SIGNER_SHA256"
	PYTHONPATH=apps/api/src:scripts $(PY) scripts/release_attestation.py sign --manifest reports/PRODUCTION_ASSURANCE_REPORT.json --key "$(KORPUS_PRODUCTION_ASSURANCE_SIGNING_KEY)" --out reports/PRODUCTION_ASSURANCE_REPORT.attestation.json
	PYTHONPATH=apps/api/src:scripts $(PY) scripts/verify_production_assurance.py
	KORPUS_RELEASE_SIGNING_KEY="$(KORPUS_RELEASE_SIGNING_KEY)" scripts/package_production_release.sh

# Zero-install security floor. This deliberately supplements rather than replaces
# networked secret/dependency/container scanners.
builtin-security:
	mkdir -p var
	PYTHONPATH=apps/api/src:. $(PY) scripts/run_builtin_security_gate.py --out var/builtin-security-gate.json

# Aggregate what this checkout can prove while preserving external production blockers.
local-production-preflight:
	mkdir -p var
	PYTHONPATH=apps/api/src:. $(PY) scripts/run_local_production_preflight.py --out var/local-production-preflight.json

# Canonical v0.8 assurance/release tooling entry points.
readiness-evaluate:
	PYTHONPATH=apps/api/src:. $(PY) scripts/evaluate_engineering_readiness.py --evidence "$(EVIDENCE)" $(if $(OUT),--out "$(OUT)")

release-truth: production-hard-predicates
	PYTHONPATH=apps/api/src:. $(PY) scripts/generate_release_truth.py

# Order matters and used to be tribal knowledge. Every target that writes into `reports/`
# changes the source digest, which invalidates the bindings written before it, so running
# `release-truth` first and `dependency-locks` second leaves current-truth failing on two
# reports that were correct when they were produced. This is the order that terminates:
# the inputs first, the bindings over them last.
evidence-refresh:
	$(MAKE) dependency-locks PY=$(PY)
	$(MAKE) standards-control-map PY=$(PY)
	$(MAKE) release-truth PY=$(PY)
	PYTHONPATH=scripts $(PY) scripts/generate_manifest.py --kind source
	PYTHONPATH=apps/api/src:scripts $(PY) scripts/sync_package_build_identity.py
	$(MAKE) current-truth-verify PY=$(PY)

current-truth-verify:
	PYTHONPATH=apps/api/src:. $(PY) scripts/verify_current_truth.py $(if $(OUT),--out "$(OUT)")

regression-carry-forward-verify:
	PYTHONPATH=apps/api/src:. $(PY) scripts/verify_regression_carry_forward.py $(if $(POLICY),--policy "$(POLICY)") $(if $(OUT),--out "$(OUT)")

zip-safety-verify:
	@test -n "$(ARCHIVE)" || (echo "ARCHIVE is required" >&2; exit 2)
	PYTHONPATH=apps/api/src:. $(PY) scripts/zip_safety.py "$(ARCHIVE)"

# Release graph entrypoints: support modules are imported by these executable runners.
full-ssot-package:
	PYTHONPATH=apps/api/src:scripts:. $(PY) scripts/package_full_ssot.py $(if $(OUT),--out "$(OUT)")

external-gate-campaign:
	PYTHONPATH=apps/api/src:scripts:. $(PY) scripts/run_external_gate_campaign.py

gcp-production-contract:
	PYTHONPATH=apps/api/src:scripts:. $(PY) scripts/verify_gcp_production.py --output reports/GCP_PRODUCTION_CONTRACT.json

gcp-slo-contract:
	PYTHONPATH=apps/api/src:scripts:. $(PY) scripts/verify_gcp_slo.py --output reports/GCP_SLO_CONTRACT.json

# Predictive Evidence Control (PEC / DGC-v2).
# These targets intentionally do not supply production thresholds, corpus identities,
# or evaluator decisions. Missing evidence is a failed/unknown admission, not a default.
.PHONY: pec-dataset-build pec-dataset-audit pec-replay pec-oracle pec-decision-sensitivity pec-train pec-export pec-verify pec-ablation pec-metamorphic pec-research pec-promote pec-protocol-check

PEC_DATASET ?= evals/datasets/pec/pec_eval.jsonl
PEC_REPLAY ?= reports/PEC_COUNTERFACTUAL_REPLAY_CURRENT.json
PEC_ORACLE ?= reports/PEC_ORACLE_CURRENT.json
PEC_PROFILE ?= config/pec/controller-candidate.json

pec-dataset-build:
	PYTHONPATH=apps/api/src:scripts $(PY) scripts/build_pec_eval_dataset.py --source evals/datasets/reference.jsonl --out $(PEC_DATASET) --receipt reports/PEC_DATASET_BUILD_CURRENT.json

pec-dataset-audit:
	test -n "$(VERSION_INVENTORY)"
	PYTHONPATH=apps/api/src:scripts $(PY) scripts/audit_pec_eval_dataset.py --dataset $(PEC_DATASET) --version-inventory "$(VERSION_INVENTORY)" $(if $(PRODUCTION_JUDGED),--production-judged) --release-gate --out reports/PEC_DATASET_AUDIT_CURRENT.json

pec-replay:
	test -n "$(PEC_RUNNER)$(PEC_OBSERVATIONS)"
	test -n "$(CORPUS_RELEASE_ID)"
	test -n "$(ANSWER_CALIBRATION_ID)"
	PYTHONPATH=apps/api/src:scripts $(PY) scripts/run_counterfactual_replay.py --dataset $(PEC_DATASET) $(if $(PEC_RUNNER),--runner "$(PEC_RUNNER)",--observations "$(PEC_OBSERVATIONS)") --corpus-release-id "$(CORPUS_RELEASE_ID)" --answer-calibration-id "$(ANSWER_CALIBRATION_ID)" --evaluation-protocol evals/EVALUATION_PROTOCOL.md --release-gate --out $(PEC_REPLAY)

pec-oracle:
	PYTHONPATH=apps/api/src:scripts $(PY) scripts/solve_pec_oracle.py --replay $(PEC_REPLAY) --release-gate --out $(PEC_ORACLE)

pec-decision-sensitivity:
	PYTHONPATH=apps/api/src:scripts $(PY) scripts/run_pec_decision_sensitivity_campaign.py --oracle $(PEC_ORACLE) --release-gate --out reports/PEC_DECISION_SENSITIVITY_CURRENT.json

pec-train:
	test -n "$(PEC_RISK_LIMIT)"
	test -n "$(PEC_MIN_LEAF_SAMPLES)"
	PYTHONPATH=apps/api/src:scripts $(PY) scripts/train_pec_controller.py --dataset $(PEC_DATASET) --oracle $(PEC_ORACLE) --risk-limit "$(PEC_RISK_LIMIT)" --minimum-leaf-samples "$(PEC_MIN_LEAF_SAMPLES)" --release-gate --out reports/PEC_TRAINING_CURRENT.json

pec-export:
	test -n "$(CORPUS_RELEASE_ID)"
	test -n "$(ANSWER_CALIBRATION_ID)"
	test -n "$(PEC_PROFILE_ID)"
	PYTHONPATH=apps/api/src:scripts $(PY) scripts/export_pec_controller.py --training reports/PEC_TRAINING_CURRENT.json --oracle $(PEC_ORACLE) --dataset $(PEC_DATASET) --system-manifest SOURCE_MANIFEST.json --evaluation-protocol evals/EVALUATION_PROTOCOL.md --replay-receipt $(PEC_REPLAY) --corpus-release-id "$(CORPUS_RELEASE_ID)" --answer-calibration-id "$(ANSWER_CALIBRATION_ID)" --profile-id "$(PEC_PROFILE_ID)" --out $(PEC_PROFILE) --receipt reports/PEC_EXPORT_CURRENT.json --release-gate

pec-verify:
	PYTHONPATH=apps/api/src:scripts $(PY) scripts/verify_pec_controller.py --profile $(PEC_PROFILE) --dataset $(PEC_DATASET) --system-manifest SOURCE_MANIFEST.json --evaluation-protocol evals/EVALUATION_PROTOCOL.md --replay-receipt $(PEC_REPLAY) --training-receipt reports/PEC_TRAINING_CURRENT.json --oracle $(PEC_ORACLE) --release-gate --out reports/PEC_CONTROLLER_VERIFY_CURRENT.json

pec-ablation:
	test -n "$(PEC_BASELINE_OBSERVATIONS)"
	test -n "$(PEC_CANDIDATE_OBSERVATIONS)"
	test -n "$(PEC_MIN_INFORMATIVE_PAIRS)"
	PYTHONPATH=apps/api/src:scripts $(PY) scripts/run_pec_ablation_campaign.py --baseline baseline="$(PEC_BASELINE_OBSERVATIONS)" --candidate pec="$(PEC_CANDIDATE_OBSERVATIONS)" --required-candidate pec --minimum-informative-pairs "$(PEC_MIN_INFORMATIVE_PAIRS)" --release-gate --out reports/PEC_ABLATION_CURRENT.json

pec-metamorphic:
	test -n "$(PEC_METAMORPHIC_OBSERVATIONS)"
	test -n "$(PEC_MIN_METAMORPHIC_PAIRS)"
	PYTHONPATH=apps/api/src:scripts $(PY) scripts/run_pec_metamorphic_campaign.py --observations "$(PEC_METAMORPHIC_OBSERVATIONS)" --minimum-pairs "$(PEC_MIN_METAMORPHIC_PAIRS)" --release-gate --out reports/PEC_METAMORPHIC_CURRENT.json

pec-research:
	PYTHONPATH=apps/api/src:scripts $(PY) scripts/run_pec_research_program.py --dataset $(PEC_DATASET) $(if $(wildcard $(PEC_REPLAY)),--replay $(PEC_REPLAY)) $(if $(wildcard $(PEC_ORACLE)),--oracle $(PEC_ORACLE)) --out reports/PEC_RESEARCH_PROGRAM_CURRENT.json

pec-promote:
	test -n "$(PEC_APPROVED_BY)"
	test -n "$(PEC_CHANGE_ID)"
	test -n "$(PEC_EVIDENCE_ARGS)"
	PYTHONPATH=apps/api/src:scripts $(PY) scripts/promote_pec_profile.py --profile $(PEC_PROFILE) $(PEC_EVIDENCE_ARGS) --approved-by "$(PEC_APPROVED_BY)" --change-id "$(PEC_CHANGE_ID)" --out config/pec/promoted-controller.json --receipt reports/PEC_PROMOTION_CURRENT.json

pec-protocol-check:
	PYTHONPATH=apps/api/src:scripts $(PY) -m pytest -q apps/api/tests/test_decision_sensitivity.py apps/api/tests/test_pec_protocol_gates.py apps/api/tests/test_pec_replay.py apps/api/tests/test_pec_training.py apps/api/tests/test_pec_integration.py apps/api/tests/test_pec_observability.py
	PYTHONPATH=apps/api/src:scripts $(PY) scripts/check_module_budget.py

.PHONY: pec-contextual-benchmark
pec-contextual-benchmark:
	test -n "$(PEC_CONTEXTUAL_OBSERVATIONS)"
	test -n "$(PEC_MIN_CONTEXTUAL_PAIRS)"
	PYTHONPATH=apps/api/src:scripts $(PY) scripts/run_pec_contextual_benchmark.py --observations "$(PEC_CONTEXTUAL_OBSERVATIONS)" --minimum-informative-pairs "$(PEC_MIN_CONTEXTUAL_PAIRS)" --release-gate --out reports/PEC_CONTEXTUAL_BENCHMARK_CURRENT.json

.PHONY: regression-shard regression-shard-merge backend-report release-evidence
REGRESSION_SHARDS ?= 24
REGRESSION_TIMEOUT ?= 240
regression-shard:
	test -n "$(SHARD_INDEX)"
	mkdir -p reports/regression/shards
	PYTHONPATH=apps/api/src:scripts:. $(PY) scripts/run_regression_shards.py run --shard-index "$(SHARD_INDEX)" --shard-count "$(REGRESSION_SHARDS)" --timeout-seconds "$(REGRESSION_TIMEOUT)" --out "reports/regression/shards/shard-$(SHARD_INDEX).json"

regression-shard-merge:
	PYTHONPATH=apps/api/src:scripts:. $(PY) scripts/run_regression_shards.py merge --out reports/regression/FULL_REGRESSION_CURRENT.json reports/regression/shards/shard-*.json

# The whole sharded regression, merged, and projected into the report the preflight reads.
# `FULL_BACKEND_REPORT.json` had no producer: the copy in the tree cites a path from an
# ad-hoc run, so the preflight has been reading a stale artefact and failing all eleven of
# its local checks on binding rather than on substance.
# Every report the preflight reads, produced against this tree and then published.
# `run_local_production_preflight.py` requires eleven reports under `reports/release/<tag>/`
# and each of them is produced by a target here — but nothing carried them across, so the
# copies in that directory were placed by hand and predated the tree they described. The
# preflight's eleven local failures were entirely about staleness.
#
# Order is the whole content of this target: producers first, coverage before its gap
# plan, and the publication last, after the digest has stopped moving. An artefact bound
# to another tree is refused by the publisher rather than copied.
release-evidence:
	$(MAKE) api-test PY=$(PY)
	$(MAKE) coverage-union PY=$(PY)
	$(MAKE) coverage-ratchet PY=$(PY)
	$(MAKE) determinism-gate PY=$(PY)
	$(MAKE) stress-gate PY=$(PY)
	$(MAKE) plasticity-gate PY=$(PY)
	$(MAKE) dependency-locks PY=$(PY)
	$(MAKE) standards-control-map PY=$(PY)
	$(MAKE) builtin-security PY=$(PY)
	$(MAKE) production-inference-security PY=$(PY)
	$(MAKE) release-mutation-delta PY=$(PY)
	$(MAKE) backend-report PY=$(PY)
	PYTHONPATH=apps/api/src:scripts $(PY) scripts/publish_release_evidence.py
	$(MAKE) local-production-preflight PY=$(PY)

backend-report:
	rm -rf reports/regression/shards
	mkdir -p reports/regression/shards
	for index in $$(seq 0 $$(( $(REGRESSION_SHARDS) - 1 ))); do \
	  $(MAKE) regression-shard SHARD_INDEX=$$index PY=$(PY) || exit 1; \
	done
	$(MAKE) regression-shard-merge PY=$(PY)
	PYTHONPATH=apps/api/src:scripts $(PY) scripts/publish_backend_report.py
