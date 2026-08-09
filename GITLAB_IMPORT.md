# Git import — KORPUS v6.3.0

The distribution package includes `KORPUS_SYSTEM_v6.3.0.bundle`, a Git bundle created
from the exact repository HEAD used for the source archive.

```bash
git clone KORPUS_SYSTEM_v6.3.0.bundle korpus
cd korpus
git checkout v6.3.0
git log -1 --oneline
python3 scripts/verify_source_manifest.py
```

The release tag `v6.3.0` is created only after all mandatory ACT-002 gates pass. The ZIP
and `.sha256` are distribution artefacts; `DISTRIBUTION_MANIFEST.json` verifies their
internal file set after extraction.
