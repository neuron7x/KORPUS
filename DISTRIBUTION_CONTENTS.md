# KORPUS v6.7.1 distribution contract

The distribution is generated from one tagged canonical Git tree. Hardened source wins every path
collision; historical Git objects travel as a bundle, not as a second nested repository. Generated
assurance evidence is copied explicitly and the final ZIP receives a deterministic distribution
manifest. `scripts/package_production_release.sh` adds a detached Ed25519 release attestation only
after production assurance is PASS.
