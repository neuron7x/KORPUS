# Review, change, and release protocol

## Change classes

- C0: documentation only;
- C1: UI or non-semantic implementation;
- C2: retrieval, chunking, ranking, prompt, model, or answer-policy change;
- C3: access, high-risk corpus, identity, encryption, or data-flow change.

C2 requires frozen eval comparison and reviewer sign-off. C3 additionally requires a
threat-model update, security reviewer, rollback drill, and staged release.

## Release evidence

Every release produces:

- immutable commit and image digest;
- SBOM and dependency/security reports;
- test and eval result bundle;
- schema migration plan and rollback;
- data/corpus version manifest;
- model/prompt/policy versions;
- operator checklist and acceptance act.

## Iteration method

Use dual-track discovery/delivery and small vertical slices. Each iteration has a
hypothesis, user outcome, measurable guardrail, implementation, eval, rollout, and
decision to keep/change/revert. Story points and model demos are not evidence of value.

