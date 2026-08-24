## Change contract

- Problem / falsifiable claim:
- Smallest change that can test it:
- Trust boundary touched:
- Rollback path:

## Evidence

- [ ] New/changed invariant has a negative control that can fail.
- [ ] Relevant unit/integration/adversarial tests executed.
- [ ] `make validate` executed.
- [ ] Dependency or image changes remain version- and digest-bound.
- [ ] No production authorization is inferred from local/CI evidence.

## Destruction pass

State the strongest counterexample attempted and what would still invalidate this change.

## Complexity delta

State what code/config was added, removed, or made simpler. Complexity without measured benefit is a regression.
