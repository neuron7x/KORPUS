from __future__ import annotations

import os
from pathlib import Path


class LocalObjectStore:
    def __init__(self, root: Path) -> None:
        self.root = root.resolve()
        self.root.mkdir(parents=True, exist_ok=True)

    def put(self, content: bytes, source_hash: str, filename: str) -> str:
        safe_name = Path(filename).name.replace(" ", "_")
        directory = self.root / source_hash[:2] / source_hash[2:4]
        directory.mkdir(parents=True, exist_ok=True)
        path = directory / f"{source_hash}-{safe_name}"
        if not path.exists():
            temporary = path.with_suffix(path.suffix + ".tmp")
            temporary.write_bytes(content)
            os.replace(temporary, path)
        return str(path.relative_to(self.root))

    def get(self, object_key: str) -> bytes:
        path = (self.root / object_key).resolve()
        if self.root not in path.parents:
            raise ValueError("object key escapes object root")
        return path.read_bytes()
