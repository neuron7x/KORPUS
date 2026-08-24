# Incident response

## Severity 0

Restricted data exposure, authorization bypass, corrupted audit chain, signing-key compromise, or incorrect operational answer with material consequence.

Actions:

1. disable answer endpoint or affected corpus;
2. preserve logs, image digests, database snapshot and audit terminal hash;
3. revoke identity/provider credentials;
4. determine first affected corpus release and software commit;
5. notify accountable security and domain owners;
6. repair in a separate branch with a reproducing test;
7. re-run frozen and incident-specific evaluations;
8. restore only through an explicit authorization decision.

## First five minutes, as commands

| symptom | command | then |
|---|---|---|
| Readers get 503 | `curl -s localhost:8000/ready -H "Authorization: Bearer $METRICS_TOKEN"` | read the reason: `database` / `object_store` / `audit_backlog` |
| A compromised login | open the Accounts console → find by subject → disable, with a reason | the reason enters the audit chain; the account is refused everywhere next request |
| Ingestion stuck | `make audit-verify` then check for `ingestion.job_reaped` events | a crashed worker's jobs are reaped to dead_letter with a record |
| Suspected tampering | `make audit-verify` | `valid: false` names the first invalid sequence; do not restart, capture the anchor |

Disabling an account and reaping a stuck job both leave an audit event. If an action left
none, it did not happen — look again before assuming it did.
