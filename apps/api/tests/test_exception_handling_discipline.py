"""A broad `except` may fail closed or record; it may not return success.

`TECHNICAL_DEBT_V5.md` carries "removal or narrowing of broad exception handlers in
critical paths" as open engineering debt. Reading all fourteen of them showed something
different from what the entry implies: every one already re-raises, degrades to a
conservative value, or records the failure. The debt is not the handlers — it is that
nothing holds them to it, so the next one written can swallow silently and no test,
gate or review artefact will say a word.

The property is therefore stated over the tree rather than over today's fourteen
sites. A handler for `Exception`, `BaseException` or a bare `except` must do at least
one of:

  * re-raise — the failure keeps travelling;
  * return a value that cannot be mistaken for success (False, None, a non-zero exit
    code) — the caller sees degradation;
  * record the failure through a logger, metric or stderr write — somebody can find
    out that it happened.

`pass`, or returning a success value, is the one shape that is refused: it converts a
fault into evidence of health, which is the failure mode this repository has found in
its gates, its reports and its aggregator, and would find in its runtime next.
"""

from __future__ import annotations

import ast
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
SOURCES = (ROOT / "apps/api/src/korpus", ROOT / "scripts")
BROAD = {"Exception", "BaseException"}

#: names that mean "the failure was written down somewhere a human can reach"
RECORDING = ("log", "warn", "error", "exception", "observe", "record", "write", "print", "emit")


def _is_broad(handler: ast.ExceptHandler) -> bool:
    if handler.type is None:
        return True
    names = {
        node.id
        for node in ast.walk(handler.type)
        if isinstance(node, ast.Name)
    }
    return bool(names & BROAD)


def _reraises(handler: ast.ExceptHandler) -> bool:
    return any(isinstance(node, ast.Raise) for node in ast.walk(handler))


def _records(handler: ast.ExceptHandler) -> bool:
    for node in ast.walk(handler):
        if isinstance(node, ast.Call):
            rendered = ast.unparse(node.func).lower()
            if any(marker in rendered for marker in RECORDING):
                return True
    return False


def _returns_only_non_success(handler: ast.ExceptHandler) -> bool:
    """True when every `return` in the handler yields a value meaning "not ok"."""
    returns = [node for node in ast.walk(handler) if isinstance(node, ast.Return)]
    if not returns:
        return False
    for node in returns:
        value = node.value
        if value is None:
            continue  # bare `return` — the caller gets None
        if isinstance(value, ast.Constant):
            constant = value.value
            # `True` is an int in Python, so an `isinstance(..., int)` test admits it —
            # which is how the first version of this rule passed while a handler
            # returned True. Ordered so bool is decided before int.
            if constant is True:
                return False
            if constant is False or constant is None:
                continue
            if isinstance(constant, int) and constant != 0:
                continue  # a non-zero exit code is a failure the caller can see
        return False
    return True


def _handlers() -> list[tuple[str, int, ast.ExceptHandler]]:
    found: list[tuple[str, int, ast.ExceptHandler]] = []
    for root in SOURCES:
        for path in sorted(root.rglob("*.py")):
            if "__pycache__" in path.parts:
                continue
            tree = ast.parse(path.read_text(encoding="utf-8"))
            for node in ast.walk(tree):
                if isinstance(node, ast.ExceptHandler) and _is_broad(node):
                    found.append((str(path.relative_to(ROOT)), node.lineno, node))
    return found


def test_there_are_broad_handlers_to_judge() -> None:
    """The dual. A rule over an empty set is a rule that has never been applied."""
    assert len(_handlers()) >= 10, (
        "no broad exception handlers found — either the tree changed shape or this "
        "test is looking in the wrong place, and either way it is asserting nothing"
    )


def test_no_broad_handler_turns_a_fault_into_evidence_of_health() -> None:
    offenders = [
        f"{path}:{line}"
        for path, line, handler in _handlers()
        if not (_reraises(handler) or _records(handler) or _returns_only_non_success(handler))
    ]
    assert not offenders, (
        "these handlers catch everything and neither re-raise, degrade, nor record — "
        f"the caller cannot tell a fault from a success: {offenders}"
    )


def test_no_bare_except_hides_which_failure_occurred() -> None:
    """`except:` also catches KeyboardInterrupt and SystemExit."""
    bare = [
        f"{path}:{line}"
        for path, line, handler in _handlers()
        if handler.type is None
    ]
    assert not bare, (
        f"bare `except:` swallows KeyboardInterrupt and SystemExit as well: {bare}"
    )


def test_no_broad_handler_is_an_empty_body() -> None:
    """`except Exception: pass` is the shape the whole rule exists to refuse."""
    silent = [
        f"{path}:{line}"
        for path, line, handler in _handlers()
        if all(isinstance(statement, ast.Pass) for statement in handler.body)
    ]
    assert not silent, f"these handlers discard the failure entirely: {silent}"
