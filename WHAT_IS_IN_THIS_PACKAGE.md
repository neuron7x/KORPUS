# KORPUS v0.9.7 — What Is In This Package

FULL SSOT engineering handoff: executable source, tests, web client, contracts, configuration, deployment/IaC, evaluation protocols, release tooling, documentation, current reports, lineage, and portable raw current evidence under `handoff/evidence/current/`.

Excluded by policy: `.git`, virtual environments, `node_modules`, developer caches, and
production secrets.

`var/` НЕ виключено цілком. `DISTRIBUTION_MANIFEST.json` містить **302 шляхи під `var/`**
— звіти шардів регресії (`final-regression-v2`, `final-regression32`, `mutation-shards`),
`var/audit-anchor.json` і зашифровані бекапи `var/backups/offsite/*.tar.enc`. Ключ
розшифрування в дереві не лежить, тож це розбіжність в ОБСЯГУ, не витік.

> **ВИПРАВЛЕНО 02.09.2026.** Тут значилось «Excluded by policy: … top-level runtime
> `var/`». Причина розходження — `scripts/manifest_paths.py:83` має коротший перелік
> винятків, без `var`. Документ описував політику, якої пакувальник не виконує, і читач
> звіряв би вміст пакета з текстом, а не з маніфестом.
