# Current verification entry point

Current machine-verifiable release evidence lives under `reports/` and is valid only for
the source digest named by `reports/RESEARCH_ASSURANCE_REPORT.json`.

Authoritative verification sequence:

```bash
python3 scripts/verify_source_manifest.py
PYTHONPATH=apps/api/src:scripts python3 scripts/verify_release_evidence.py
PYTHONPATH=apps/api/src python3 scripts/check_import_cycles.py
make validate
make web-build
```

After packaging, verify the final distribution separately:

```bash
python3 scripts/verify_package.py dist/KORPUS_SYSTEM_v6.3.0.zip
```

`VERIFICATION_REPORT_V5.md` is retained as a historical v5 snapshot. Its counts are not
current-release claims.
