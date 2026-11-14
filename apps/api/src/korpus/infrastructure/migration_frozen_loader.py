"""Construct Alembic revision scripts from provenance-checked source bytes."""

from __future__ import annotations

import importlib.machinery
import importlib.util
from collections.abc import Buffer, Iterator
from pathlib import Path
from types import CodeType
from typing import TYPE_CHECKING

from alembic.script.base import Script

if TYPE_CHECKING:
    from korpus.infrastructure.migration_baseline_proof import RevisionSource


class _FrozenRevisionLoader(importlib.machinery.SourceFileLoader):
    """Compile only proven bytes; deny fallback disk and bytecode reads/writes."""

    def __init__(self, name: str, path: str, source: bytes, error_type: type[RuntimeError]) -> None:
        super().__init__(name, path)
        self._captured_source = source
        self._error_type = error_type

    def get_code(self, fullname: str) -> CodeType:
        return self.source_to_code(self._captured_source, self.path)

    def get_data(self, path: str) -> bytes:
        raise self._error_type("DENIED_BASELINE_SOURCE_REREAD")

    def set_data(self, path: str, data: Buffer, **kwargs: object) -> None:
        raise self._error_type("DENIED_BASELINE_BYTECODE_WRITE")


def frozen_revision_scripts(
    root: Path, sources: tuple[RevisionSource, ...], *, error_type: type[RuntimeError]
) -> Iterator[Script]:
    """Yield Script wrappers after executing only the already-verified captured source."""
    for item in sources:
        path = str(root / item.path)
        loader = _FrozenRevisionLoader(Path(item.path).stem, path, item.source, error_type)
        spec = importlib.util.spec_from_loader(loader.name, loader, origin=path)
        if spec is None:
            raise error_type("DENIED_BASELINE_LOADER_UNAVAILABLE")
        module = importlib.util.module_from_spec(spec)
        loader.exec_module(module)
        yield Script(module, item.revision, path)
