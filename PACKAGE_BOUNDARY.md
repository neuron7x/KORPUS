# KORPUS v0.9.7 FULL SSOT package boundary

This archive is the canonical engineering-closure/staging handoff for the current KORPUS project state. It contains application source, API, web client, tests, migrations, contracts, infrastructure-as-code, CI/CD workflows, verification tooling, current reports, architecture/operations documentation, lineage, and portable current raw evidence under `handoff/evidence/current/`.

Intentionally excluded: `.git`, credentials, production secrets, private production corpus payloads, virtual environments, `node_modules`, developer caches, and unattained external attestations. Their absence is never represented as PASS.

`SOURCE_MANIFEST.json` binds the canonical repository/documentation source boundary. Package outputs are never stored at the source root: the packager creates `DISTRIBUTION_MANIFEST.json` and `FULL_SSOT_PACKAGE_RECEIPT.json` only in the staged distribution. The original v0.9.7 uploaded pair is preserved byte-for-byte under `LINEAGE/v0.9.7-original-uploaded/`. Behavioral evidence remains bound separately to the source digest that
`compute_source_digest` produces over `EVIDENCE_SOURCE_PATHS` (scope `evidence_paths`).

> **ВИПРАВЛЕНО 02.09.2026.** Тут було вкарбовано значення
> `15f1630f4327babeba…78aa`, заморожене 23.08.2026 і подане в теперішньому часі. Воно
> вже не те: дайджест рухається з кожною зміною джерела — 02.09 його зміряли тричі за
> годину й дістали три різні значення. Вкарбоване число тут не додає доказовості, а
> віднімає: читач звіряє звіт із текстом і бачить `unbound` там, де все гаразд.
> Той самий заморожений рядок ще у восьми документах (`handoff/`, `reports/`).
