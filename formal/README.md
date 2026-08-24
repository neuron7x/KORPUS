# Formal models

These TLA+ modules are specification artifacts, not claimed TLC model-check evidence in
this package. The packaging runtime does not include TLC. Every safety property used for
the current release is therefore mirrored by an executable Python reference model and
pytest negative/destruction controls.

- `ReleasePromotion.tla` specifies monotone release promotion and fail-closed withdrawal.
- `EvidenceLattice.tla` specifies assurance evidence ordering/join laws.
- `BoundedPlasticity.tla` specifies bounded runtime knobs and monotone safety during
  adaptation. Its executable counterpart is `scripts/run_plasticity_gate.py`, which
  exhaustively enumerates the finite policy/state grid used by the release gate.

TLA+ exists here to make state variables, transition relations and invariants reviewable
independently of implementation syntax; executable Python gates carry the package-local
verification claim.

## v0.6 bounded-plasticity correspondence

`BoundedPlasticity.tla` is intentionally a review model, not release evidence: this
package does not contain TLC and therefore makes no TLC-executed claim. Its constants
and state invariants correspond to `config/operations/plasticity-policy.json`; the
release-enforced finite-state proof is `scripts/run_plasticity_gate.py`, which loads that
exact JSON, records its SHA-256, enumerates the finite observation grid, validates every
proposal, and fails closed on a policy/schema mismatch. This separation prevents a
formal-looking file that was never executed from being counted as a green gate.
