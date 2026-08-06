"""The parser sandbox runs in the document's directory, so its path must not be relative.

Found by running a bulk import for real. `extract_pages_sandboxed` sets
`cwd=path.parent` — the untrusted file's own directory — and passed `PYTHONPATH` through
verbatim. Every natural way to invoke this tree carries a *relative* one: the Makefile
target is `PYTHONPATH=apps/api/src`, and so is every shell line in the documentation.
Resolved against the document's directory that names nothing, and the worker died with
"Error while finding module" on every file in the batch.

What made it expensive rather than annoying: the failure surfaces as a per-document
`ValueError`, and `import_corpus.py` records those as refusals and keeps going. So a
whole corpus reported itself as "refused: parser error" — which reads as four hundred
malformed documents, not as one wrong environment variable. Nothing in the message named
the cwd.

The negative control matters here: assert that a relative entry is *not* passed through,
not merely that an absolute one survives. Passing the value through unchanged already
satisfies the second.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any

import pytest

from korpus.infrastructure import extraction


@pytest.fixture
def captured(monkeypatch: pytest.MonkeyPatch) -> dict[str, Any]:
    """Run the launcher far enough to see the environment, then stop it."""
    seen: dict[str, Any] = {}

    def fake_run(*arguments: Any, **keywords: Any) -> Any:
        seen["env"] = keywords["env"]
        seen["cwd"] = keywords["cwd"]
        raise OSError("stopped before the worker starts")

    monkeypatch.setattr(extraction.subprocess, "run", fake_run)
    return seen


def _launch(document: Path) -> None:
    with pytest.raises(ValueError, match="parser sandbox unavailable"):
        extraction.extract_pages_sandboxed(
            document,
            document.name,
            "application/pdf",
            False,
            "ukr",
            max_pdf_pages=10,
            ocr_total_timeout_seconds=10,
            timeout_seconds=10,
            memory_limit_mb=256,
            output_limit_bytes=1024,
        )


def test_a_relative_pythonpath_is_resolved_before_the_worker_sees_it(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, captured: dict[str, Any]
) -> None:
    package = tmp_path / "src"
    package.mkdir()
    document = tmp_path / "documents" / "order.pdf"
    document.parent.mkdir()
    document.write_bytes(b"%PDF-1.4\n")

    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("PYTHONPATH", "src")
    _launch(document)

    passed = captured["env"]["PYTHONPATH"]
    assert passed != "src", "a relative entry reached a worker whose cwd is the document's"
    assert Path(passed).is_absolute(), passed
    assert Path(passed).resolve() == package.resolve(), passed
    assert Path(captured["cwd"]).resolve() == document.parent.resolve()


def test_every_entry_is_resolved_not_just_the_first(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, captured: dict[str, Any]
) -> None:
    document = tmp_path / "order.pdf"
    document.write_bytes(b"%PDF-1.4\n")

    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("PYTHONPATH", os.pathsep.join(["one", "/already/absolute", "two"]))
    _launch(document)

    entries = captured["env"]["PYTHONPATH"].split(os.pathsep)
    assert all(Path(entry).is_absolute() for entry in entries), entries
    assert "/already/absolute" in entries, entries


def test_an_empty_pythonpath_stays_empty(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, captured: dict[str, Any]
) -> None:
    """An empty entry on `sys.path` is the current directory — here, the document's."""
    document = tmp_path / "order.pdf"
    document.write_bytes(b"%PDF-1.4\n")

    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv("PYTHONPATH", raising=False)
    _launch(document)

    assert captured["env"]["PYTHONPATH"] == ""
