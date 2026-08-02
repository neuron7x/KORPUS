# Incident response runbook

## Severity examples

- SEV-1: restricted-source disclosure, credential compromise, systemic dangerous
  answer, destructive integrity loss;
- SEV-2: repeated unsupported answers, corpus poisoning, major outage;
- SEV-3: isolated incorrect citation, degraded latency, failed background job.

## First response

1. Declare incident and incident commander.
2. Preserve audit evidence and timestamps; do not copy sensitive text into chat.
3. Contain: disable corpus/model/route, revoke sessions or credentials, block index.
4. Assess users, sources and answers affected.
5. Communicate through the approved channel.
6. Recover from verified state; run targeted regression and access tests.
7. Close only with root cause, corrective actions, owners and due dates.

For a bad source, revocation must remove it from serving immediately and enumerate
answers whose evidence sets referenced its version.

