"""Every door to an answer goes through the bound. Read from the code, not remembered.

A re-audit found the concurrency bound on one of the two answer routes. `POST /v1/answers`
acquired the admission controller — a global limit, and inside it a per-subject share so no
single reader can take the whole service. `POST /v1/conversations/{id}/ask`, added by
ACT-001, called `ExtractiveAnswerService.execute` directly.

Nothing failed. The suite was green, the metric kept reporting, and the control was simply
not on the path the browser had started using — the conversation route became the default
the moment the interface had a conversation panel. That is the shape this project keeps
finding: a gate that reads green because it is on the other door.

So the check is structural. It parses the API modules, finds every function that reaches
the answer service, and asserts each one goes through `korpus.api.answering`. A third route
added next year fails here rather than in production.
"""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

API = Path(__file__).resolve().parents[1] / "src/korpus/api"

#: The call that costs: retrieval over the whole corpus, a possible model round trip, and
#: an audit append. Anything reaching it is an answer path whatever the URL says.
ANSWER_CALL = "execute"

#: The one place the bound lives.
BOUNDED = "bounded_answer"


def _functions_calling(name: str) -> dict[str, str]:
    """`{qualified function: module}` for every function that calls `name` on anything."""
    found: dict[str, str] = {}
    for path in sorted(API.glob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if not isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef):
                continue
            for inner in ast.walk(node):
                call = getattr(inner, "func", None)
                attribute = isinstance(call, ast.Attribute) and call.attr == name
                bare = isinstance(call, ast.Name) and call.id == name
                # `run_in_threadpool(service.execute, ...)` passes the callable rather
                # than calling it, so the reference is looked for too — otherwise the
                # exact form the unbounded route used would slip past this check.
                reference = isinstance(inner, ast.Attribute) and inner.attr == name
                if attribute or bare or reference:
                    found[f"{path.name}::{node.name}"] = path.name
                    break
    return found


def test_every_answer_path_goes_through_the_shared_bound() -> None:
    callers = _functions_calling(ANSWER_CALL)
    assert callers, "no function reaches the answer service — this test is stale"

    unbounded = []
    for qualified, module in sorted(callers.items()):
        if module == "answering.py":
            continue
        source = (API / module).read_text(encoding="utf-8")
        function = qualified.split("::", 1)[1]
        body = _function_source(source, function)
        if BOUNDED not in body:
            unbounded.append(qualified)

    assert not unbounded, (
        "these answer paths reach retrieval without the concurrency bound, so one "
        f"account can saturate the service through them: {unbounded}"
    )


def _function_source(source: str, name: str) -> str:
    tree = ast.parse(source)
    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef) and node.name == name:
            return ast.get_source_segment(source, node) or ""
    return ""


def test_the_bound_lives_in_exactly_one_module() -> None:
    """Two copies drifted once. Three would drift again."""
    acquiring = [
        path.name
        for path in sorted(API.glob("*.py"))
        if "admission.acquire" in path.read_text(encoding="utf-8")
    ]
    # routes.py keeps its own for ingestion, which is a different controller with a
    # different capacity; the answer bound is answering.py's alone.
    assert "answering.py" in acquiring
    assert "routes_tenancy.py" not in acquiring, (
        "the conversation route acquires the bound itself instead of sharing it"
    )


def test_this_check_can_fail() -> None:
    """The negative control. A checker that cannot fail has never checked anything."""
    source = "async def ask(service):\n    return await service.execute(identity, query)\n"
    assert BOUNDED not in _function_source(source, "ask")
    assert "execute" in _function_source(source, "ask")


@pytest.mark.parametrize("route", ["create_answer", "ask_within_conversation"])
def test_both_named_routes_are_present_and_bounded(route: str) -> None:
    """Named explicitly as well as discovered.

    The discovery above would pass trivially if both routes were renamed or deleted, which
    is precisely the edit that removes an answer path without anyone noticing it was one.
    """
    sources = "\n".join(path.read_text(encoding="utf-8") for path in API.glob("*.py"))
    assert f"def {route}(" in sources, f"{route} no longer exists"
    for path in sorted(API.glob("*.py")):
        body = _function_source(path.read_text(encoding="utf-8"), route)
        if body:
            assert BOUNDED in body, f"{route} answers without the bound"
            return
    pytest.fail(f"{route} was not found in any API module")
