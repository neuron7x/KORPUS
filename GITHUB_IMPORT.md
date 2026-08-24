# GitHub import — KORPUS v0.9.7

Authoritative release identity: `v0.9.7`.
Canonical distribution artifact: `KORPUS_v0.9.7_PRODUCTION_ASSURANCE_HARDENED_FULL_SSOT_CANONICAL_2026-08-23.zip`.

The distribution is a gitless recovery envelope. Its single versioned root contains the clean source
tree and release evidence; `LINEAGE/`, if present, is provenance-only. `.git`, credentials, private
production secret values and unavailable external attestations are not fabricated.

Before import, verify the outer SHA-256, `DISTRIBUTION_MANIFEST.json`, `SOURCE_MANIFEST.json` and
`PACKAGE_BUILD.json`. Importing verified source bytes creates a new Git commit identity; it does not
claim to preserve unavailable historical refs. Repository branch protection, environments, WIF and
hosted CI state remain live external predicates until configured and executed.
