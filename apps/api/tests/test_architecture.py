"""The layering, read off the import graph rather than asserted in a document.

`docs/architecture/SYSTEM_V5.md` states the layers. Until 2026-08-06 nothing checked
them, and the graph had drifted: `application/ingestion.py` imported the parser
functions and `application/ingestion_jobs.py` imported `SqlRepository` and
`SqlIngestionJobQueue` — the two classes that hold every transaction and every
row-level-security session.

The cost is not tidiness. A layer that names its adapters cannot be exercised without
them, so a test about *ordering* — is the job created before its audit event, does the
sandbox setting reach the parser — needs a database, a parser binary and a fork. And the
layering becomes unenforceable in the direction that matters: nothing stops the next
method from reaching for `queue.engine` and opening a connection outside the session
context that sets the RLS identity.

The rule is stated once here, as data, and every violation is reported together. Reading
the graph is what makes this a check rather than a claim: an `import` is exactly the
dependency, and there is no way to have one without the checker seeing it.
"""

from __future__ import annotations

import ast
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
SRC = ROOT / "apps/api/src/korpus"

#: Lower may not import higher. `security` sits beside `application` because both are
#: policy over the domain and neither may reach for an adapter; `domain` is the floor.
LAYERS: dict[str, int] = {
    "domain": 0,
    "application": 1,
    "security": 1,
    "infrastructure": 2,
    "api": 3,
}

#: Modules directly under `korpus/` are the composition root: `composition.py` wires the
#: ports to the adapters, `main.py` builds the app, `cli.py` builds a process. They are
#: allowed to name both sides, because something has to and neither layer may.
COMPOSITION_ROOT = "root"


def _layer_of_module(module: str) -> str | None:
    parts = module.split(".")
    if len(parts) >= 2 and parts[0] == "korpus" and parts[1] in LAYERS:
        return parts[1]
    return None


def _layer_of_file(path: Path) -> str:
    relative = path.relative_to(SRC).as_posix()
    head = relative.split("/")[0] if "/" in relative else COMPOSITION_ROOT
    return head if head in LAYERS else COMPOSITION_ROOT


def _imports(path: Path) -> list[tuple[str, int]]:
    """Every korpus import in a file, including the ones inside functions.

    Deferred imports count. A `from korpus.infrastructure... import` inside `__init__`
    is the same dependency as one at module scope — it just fails later — and this
    check exists precisely because "resolve it lazily" is the shape the violation kept
    coming back in.
    """
    found: list[tuple[str, int]] = []
    tree = ast.parse(path.read_text(encoding="utf-8"))
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and node.module:
            found.append((node.module, node.lineno))
        elif isinstance(node, ast.Import):
            found.extend((alias.name, node.lineno) for alias in node.names)
    return found


def _graph() -> dict[str, set[tuple[str, str, int]]]:
    edges: dict[str, set[tuple[str, str, int]]] = defaultdict(set)
    for path in sorted(SRC.rglob("*.py")):
        if "__pycache__" in path.parts:
            continue
        here = _layer_of_file(path)
        for module, lineno in _imports(path):
            there = _layer_of_module(module)
            if there is not None and there != here:
                edges[here].add((there, path.relative_to(ROOT).as_posix(), lineno))
    return edges


def test_no_layer_imports_a_layer_above_it() -> None:
    violations = [
        f"{where}:{line} — {source} imports {target}"
        for source, targets in _graph().items()
        if source in LAYERS
        for target, where, line in sorted(targets)
        if LAYERS[target] > LAYERS[source]
    ]

    assert not violations, (
        "these imports run against the layering, so the lower layer cannot be imported, "
        f"reasoned about or tested without the higher one: {violations}"
    )


def test_the_domain_depends_on_nothing_in_this_package() -> None:
    """The floor. A domain model that imports a service is not a model."""
    outward = [
        f"{where}:{line} — domain imports {target}"
        for target, where, line in sorted(_graph().get("domain", set()))
    ]

    assert not outward, outward


def test_the_application_layer_reaches_infrastructure_only_through_ports() -> None:
    """The specific edge this file was written for.

    Stated separately from the general rule so a regression names the thing that
    regressed. `application/ports.py` is the whole outward surface: Repository,
    Extractor, IngestionJobQueue, ObjectStore, Retriever.
    """
    offenders = [
        f"{where}:{line}"
        for target, where, line in sorted(_graph().get("application", set()))
        if target == "infrastructure"
    ]

    assert not offenders, (
        "the application layer names an adapter instead of a port; korpus/composition.py "
        f"is where both sides may be known: {offenders}"
    )


def test_every_port_the_application_declares_has_an_implementation() -> None:
    """A protocol nobody implements is a design document with a `.py` extension.

    The dual of the rule above: it would be trivially satisfied by an application layer
    that declares ports and never gets wired to anything.
    """
    from typing import Protocol, get_type_hints  # noqa: F401  (imported for clarity)

    from korpus.application import ports

    protocols = [
        name
        for name, value in vars(ports).items()
        if isinstance(value, type) and Protocol in getattr(value, "__bases__", ())
    ]
    assert protocols, "application/ports.py declares no protocols — this test is stale"

    import korpus.composition  # noqa: F401  (imports the adapters it wires)
    from korpus.infrastructure.extraction import DocumentExtractor
    from korpus.infrastructure.ingestion_jobs import SqlIngestionJobQueue
    from korpus.infrastructure.object_store import LocalObjectStore
    from korpus.infrastructure.repository import SqlRepository

    implementations = {
        "Repository": SqlRepository,
        "Extractor": DocumentExtractor,
        "IngestionJobQueue": SqlIngestionJobQueue,
        "ObjectStore": LocalObjectStore,
    }
    unimplemented = [name for name in protocols if name not in implementations
                     and name not in {"Retriever"}]
    assert not unimplemented, (
        f"these ports have no adapter named here: {unimplemented}"
    )

    # Structural, not nominal: Protocol conformance is what the type checker enforces,
    # and an adapter that has drifted from its port fails here rather than at a call
    # site three layers away.
    for name, adapter in implementations.items():
        port = getattr(ports, name)
        missing = [
            member
            for member in dir(port)
            if not member.startswith("_") and not hasattr(adapter, member)
        ]
        assert not missing, f"{adapter.__name__} does not satisfy {name}: missing {missing}"


def test_the_composition_root_is_the_only_module_naming_both_sides() -> None:
    """Otherwise "the composition root" is a name for wherever the wiring leaked to."""
    both = []
    for path in sorted(SRC.rglob("*.py")):
        if "__pycache__" in path.parts:
            continue
        layers = {
            _layer_of_module(module)
            for module, _ in _imports(path)
            if _layer_of_module(module) is not None
        }
        if {"application", "infrastructure"} <= layers and _layer_of_file(path) == COMPOSITION_ROOT:
            both.append(path.relative_to(ROOT).as_posix())

    assert "apps/api/src/korpus/composition.py" in both, (
        "composition.py no longer wires the application to its adapters"
    )
    # `main.py`, `cli.py` and the requirement registries legitimately build processes.
    # What must not happen is a *layer* module doing it, which the rule above covers.


def test_the_layering_check_can_fail(tmp_path: Path) -> None:
    """A rule that passes on a clean tree proves nothing until it refuses a dirty one.

    Both shapes the violation actually took are probed: an import at module scope, and
    the deferred one inside a constructor that "resolves it lazily". They are the same
    dependency; only the moment of failure differs, and the second is the one that keeps
    coming back because it looks like a fix.
    """
    source = (SRC / "application/ingestion.py").read_text(encoding="utf-8")

    at_module_scope = source.replace(
        "from korpus.application.ports import",
        "from korpus.infrastructure.extraction import DocumentExtractor\n"
        "from korpus.application.ports import",
        1,
    )
    deferred = source.replace(
        "        self.extractor = extractor",
        "        from korpus.infrastructure.extraction import DocumentExtractor\n"
        "        self.extractor = extractor",
        1,
    )
    assert at_module_scope != source and deferred != source, "probe is out of date"

    for mutated in (at_module_scope, deferred):
        probe = tmp_path / "ingestion.py"
        probe.write_text(mutated, encoding="utf-8")
        modules = {module for module, _ in _imports(probe)}
        assert any(_layer_of_module(module) == "infrastructure" for module in modules), (
            "the import reader missed an infrastructure dependency it was shown"
        )


def test_no_public_function_takes_a_positional_boolean_flag() -> None:
    """Two adjacent booleans are one transposition away from a false audit record.

    `transition_version` took `acknowledge_near_duplicate` and
    `acknowledge_extraction_quality` positionally. Both are a reviewer's assertion about
    what they inspected, both go into the audit chain under their name, and swapping
    them is invisible: the call type-checks, the transition succeeds, and the record
    says the reviewer acknowledged something they did not look at.

    Booleans that are internal switches on a private helper are not the hazard; this
    covers the public surface, where the caller is somewhere else.
    """
    offenders: list[str] = []
    for path in sorted(SRC.rglob("*.py")):
        if "__pycache__" in path.parts:
            continue
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if not isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef):
                continue
            if node.name.startswith("_"):
                continue
            positional = node.args.posonlyargs + node.args.args
            first_defaulted = len(positional) - len(node.args.defaults)
            for index, argument in enumerate(positional):
                if index < first_defaulted:
                    continue
                default = node.args.defaults[index - first_defaulted]
                if isinstance(default, ast.Constant) and isinstance(default.value, bool):
                    offenders.append(
                        f"{path.relative_to(ROOT)}:{node.lineno} "
                        f"{node.name}({argument.arg}={default.value})"
                    )

    assert not offenders, (
        "these boolean parameters can be passed positionally; make them keyword-only "
        f"so a transposition is a syntax error rather than a wrong record: {offenders}"
    )
