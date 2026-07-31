# Operations

## Daily

- verify readiness and corpus release identifier;
- verify audit chain and anchor the terminal hash externally;
- inspect failed ingestion, review backlog and authorization denials;
- verify backups by restore sampling, not job completion alone.

## Release

- promote immutable image digest;
- record database migration identifier and corpus release;
- run frozen eval and restricted-marker probe;
- retain previous image and migration rollback procedure;
- stop rollout on evidence, authorization, audit or readiness regression.

## Backup invariant

A backup is valid only after an automated restore produces the same corpus release identifier and a valid audit chain. Storage-provider success status alone is insufficient.
