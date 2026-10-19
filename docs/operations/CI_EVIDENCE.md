# CI evidence production and recovery

The CI workflow calls the repository's reusable assurance workflow at the same
commit. The assurance jobs produce PostgreSQL coverage and the evaluation,
mutation, migration, scale, and operational reports. The repository and API jobs
depend on that call and download their required artifacts into `var/` before
running their consumers. Scheduled and manual assurance runs remain available.

## Coverage admission

Each dialect produces three required files: native coverage data, a JSON report,
and an execution receipt. The receipt binds a successful command to the source
bytes before and after execution, the locked coverage.py version, the coverage
configuration, and the hashes of the data and report. GitHub receipts also bind
the repository, tested SHA, workflow run, and attempt; GitLab receipts bind the
project, tested SHA, and pipeline.

The union requires both dialects and checks their executable lines and branch
arcs. It regenerates reports from the admitted native data and uses coverage.py's
native combination and reporting. Missing, corrupt, stale, altered, or
incompatible inputs fail the gate. No JSON-only or single-dialect fallback is
available. Coverage minimums and the missing-branch ratchet remain unchanged.

For local verification, install the locked development environment, then run:

```sh
PYTHON=apps/api/.venv/bin/python make postgres-coverage
make coverage-ratchet
```

The second command runs the SQLite producer, waits for it to succeed, and then
combines both dialects. This order also holds under parallel Make. A failed
producer cannot leave an admissible receipt for an earlier execution.

## Current source evidence and release evidence

The CI repository check explicitly selects `SOURCE_CHECKOUT`. It verifies fresh
reports from the current code, including mutation catalogue identity, producer
outcomes, input hashes, and recomputed operational predicates. Static repository
contracts continue to run. CI keeps these measurements under `var/`; it does
not overwrite frozen release reports to make their recorded source hashes match.

Default `make validate` and default full current-truth verification retain their
full distribution and production evidence requirements. Source checks do not
authorize a production release. Selecting a source context over a production
evidence surface is refused. Validation is ordered so source checks execute
before jobs create internal production gate reports.

## Reruns and diagnosis

Use **Re-run all jobs** after a transient failure in this evidence graph. Artifact
names include `github.run_attempt`, and coverage receipts require matching
attempts. Rerunning only a consumer cannot substitute an artifact from an older
attempt. A source change requires a new workflow run with both producers.

Required uploads fail when inputs are missing. Diagnostic uploads execute after
success or failure and have a fourteen-day retention period. They include API
JUnit and coverage evidence, separate consumer logs, PostgreSQL security results,
and mutation shard logs and JSON outcomes. Inspect the first failed step and its
diagnostic artifact; skipped dependent jobs have not passed their gates.

The PostgreSQL coverage producer runs the full API suite. The additional security
gate selects its nine declared adversarial test files explicitly. Both runners
wait for stable TCP readiness, excluding the image's temporary initialization
server. A security subprocess timeout records failure with exit code 124 and
preserves both complete output streams under `var/postgres-security/` so the gate
can still publish its failure report.

## Terraform verification before merge

The GCP workflow also runs on pull requests. Its verification job uses the pinned,
signature-verified Terraform 1.15.8 to check formatting, initialize the bootstrap,
foundation, and runtime stacks with `-backend=false -lockfile=readonly`, and
validate their provider schemas against the checked-in dependency locks. Each PR
has its own concurrency group; main retains serialized runs.
Deployment still requires the main ref, explicit production enablement, and the
production environment. A successful source verification is not deployment.

When the formatting gate lists files, run the pinned `terraform fmt -recursive
infra/gcp` locally, then repeat the check and schema validations. The formatter's
failure stops the step before schema validation, so formatting success alone does
not establish that the configurations satisfy their provider schemas.

The formatting repair from issue #58 was imported from an isolated worktree:
seven Terraform files received only native formatter whitespace changes.
Five production and SLO predicate literals and the existing worker negative
control were aligned with that canonical output. The network and SLO mutation
controls still reject broken state binding, policy bounds, and deletion protection.

The underlying contracts are documented by [GitHub's reusable workflow guide](https://docs.github.com/en/actions/how-tos/reuse-automations/reuse-workflows),
[workflow artifacts](https://docs.github.com/en/actions/how-tos/writing-workflows/choosing-what-your-workflow-does/storing-and-sharing-data-from-a-workflow),
and [coverage.py's native combination](https://coverage.readthedocs.io/en/7.13.3/commands/cmd_combine.html).
Terraform documents [canonical formatting](https://developer.hashicorp.com/terraform/cli/commands/fmt),
[configuration validation](https://developer.hashicorp.com/terraform/cli/commands/validate),
and [read-only dependency locks](https://developer.hashicorp.com/terraform/cli/commands/init#plugin-installation).
