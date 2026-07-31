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
