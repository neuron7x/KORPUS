# Bounded ZIP Snapshot Admission — Issue #22

## Exact invariant

`verified_bytes == hashed_bytes` in every canonical ZIP verdict: semantic checks and SHA-256 consume the same private seekable snapshot, never a second pathname lookup. Content equality is **not cryptographic authenticity**.

## Resource and mutation policy

The descriptor must be a regular file. `fstat` is taken before copying and admission refuses inputs above **512 MiB compressed**. The copier reads exactly the initial admitted byte count in at most **1 MiB chunks**, hashing the same bytes written to the private temporary file. Premature EOF, short writes, changed size, changed mtime/ctime and extra bytes at the opened descriptor all refuse verification. The snapshot is rewound for existing ZIP path/inventory/uncompressed-ratio, size and entry-count checks; none are removed.

## Deterministic negative campaign

`apps/api/tests/test_package_archive_snapshot.py` tests path A/B substitution in both directions. `apps/api/tests/test_snapshot_admission.py` tests regular files, huge sparse inputs, pipes, append/truncate during copy, forced premature EOF, and fixed-seed cross-chunk boundaries (0, 1, 4096, 1 MiB ± 1, 2 MiB + 31). No sleeps, no production keys or deploys.

Validate with `PYTHONPATH=apps/api/src:. python -m pytest apps/api/tests/test_package_archive_snapshot.py apps/api/tests/test_snapshot_admission.py -q`, `make api-lint`, `python scripts/check_module_budget.py`, and complete hosted CI/PostgreSQL/research assurance. Record the exact source/merge SHA and every gate verdict; never infer a PASS from absent checks.

## Residuals outside this patch

#20: packaged runtime evidence authenticity and consumer obligations. #8: production signed-manifest byte identity. #72: effective GitHub main protection and negative bypass tests. `production_authorized=false`. Green tests do not close these dependencies.
