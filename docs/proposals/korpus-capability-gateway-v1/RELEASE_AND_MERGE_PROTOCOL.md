# Release and Merge Protocol

Implementation discovery is open during build. At gateway release-candidate freeze, the
enabled profile and its acceptance denominator become fixed.

After freeze, a new finding blocks the current candidate only if it violates a frozen critical
invariant or proves a mandatory verifier can false-PASS one. Other findings go to N+1.

Final evidence binds exact commit, current source/release identity, capability contract
digests, dependency lock, migrations if any, enabled capability manifests, exact test lane,
CI and clean-room result.

## Stop rule

When the frozen set passes, P0=0, critical verifier false-PASS defects=0, CI passes and
clean-room reproduction passes, the coding/assurance cycle stops for this feature.

Final agent state: `READY_FOR_OWNER_APPROVAL`.
The agent never grants final production authority.
