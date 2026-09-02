# KORPUS v0.9.7 distribution contract

The source boundary is byte-inventoried by `SOURCE_MANIFEST.json`. The final recovery envelope
contains the clean source tree plus the **17-file baseline delta** under
`LINEAGE/v0.9.7-original-uploaded/modified-baseline/`, so provenance recovery does not require
contaminating the source tree with a nested archive.

> **ВИПРАВЛЕНО 02.09.2026.** Два твердження були хибні.
>
> «Gitless canonical source snapshot … no Git commit is invented»: репозиторій існує, гілка
> `main`, коміти реальні. Формулювання описувало стан, який минув.
>
> «Byte-preserved uploaded predecessor under `LINEAGE/`»: там не побайтовий попередник, а
> ДЕЛЬТА. `LINEAGE/README.md` — і він точний — каже: з 2151 файла оригіналу 2134 побайтово
> тотожні живому дереву, **17 мають пізніші версії**, і збережено саме ті 17. Два документи
> кореня суперечили один одному; хибний той, кого ніхто не перераховує.

Generated local assurance evidence is explicitly identified as local and cannot satisfy predicates
that require independent assessment, production-like PostgreSQL, a trusted hosted builder or exact
deployment attestation. `reports/PRODUCTION_ASSURANCE_REPORT.json` remains the production authority.
