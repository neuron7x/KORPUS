# KORPUS lineage policy

The live repository root is the only canonical source tree. Historical full
source snapshots are not retained as recursive ZIP files or duplicate trees.

Provenance is retained through manifests, checksums, release records and the
minimal v0.9.7 baseline delta. The original uploaded v0.9.7 had 2,151 files:
2,134 are byte-identical to paths in the live tree, 17 have later versions in
the live tree, and none are missing. Therefore the original state can be
reconstructed from the live tree plus:

- `v0.9.7-original-uploaded/modified-baseline/` (the 17 original bytes);
- `../reports/recovery/KORPUS_v0.9.7_RECOVERY_MANIFEST_2026-08-24.json`;
- the recorded original archive SHA-256
  `3538c4559206e35f76d90b70ff1d109ddbb70f5e454a5315b64a012649bb1ac0`.

Historical v0.8.1 and v0.6.1 full snapshot ZIPs were integrity-tested before
removal. Their checksum and lineage metadata remain here; their duplicated
source trees are not part of the canonical project.
