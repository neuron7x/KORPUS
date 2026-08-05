"""A gate an author cannot run before pushing is a gate that fails in the pipeline.

ADR-0008 records four defects that shared one shape: a check was declared, looked
green, and had not run. Three of them would have survived any review of the check's
*output*, because the output was fine — the check simply measured something other
than what its name claimed.

These tests read the two places where KORPUS declares its checks — `Makefile` and
`.gitlab-ci.yml` — and assert that they agree, and that each declared tool is invoked
in the form that makes its configuration take effect. They are deliberately textual:
the failure mode being defended against is a command that runs successfully while
reading the wrong configuration, which no amount of running it can detect.
"""

from __future__ import annotations

import ast
import re
import shlex
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[3]
MAKEFILE = ROOT / "Makefile"
CI = ROOT / ".gitlab-ci.yml"


def _makefile_recipe(target: str) -> list[str]:
    """Return the command lines of one Makefile target, comments and blanks dropped."""
    lines = MAKEFILE.read_text(encoding="utf-8").splitlines()
    out: list[str] = []
    collecting = False
    for line in lines:
        if re.match(rf"^{re.escape(target)}\s*:", line):
            collecting = True
            continue
        if collecting:
            if line.startswith("\t"):
                stripped = line[1:].strip()
                if stripped and not stripped.startswith("#"):
                    out.append(stripped)
                continue
            if line.strip() == "":
                continue
            break
    if not out:
        pytest.fail(f"Makefile has no target {target!r} — this test is out of date")
    return out


def _makefile_prerequisites(target: str) -> list[str]:
    """Return the prerequisite list of one Makefile target, in declared order.

    Order is the payload: `check` runs its prerequisites left to right, so a gate that
    reads a file another gate writes has to appear after it.
    """
    for line in MAKEFILE.read_text(encoding="utf-8").splitlines():
        match = re.match(rf"^{re.escape(target)}\s*:([^=].*)?$", line)
        if match:
            return (match.group(1) or "").split()
    pytest.fail(f"Makefile has no target {target!r} — this test is out of date")


def _ci_script(job: str) -> list[str]:
    """Return the `script:` lines of one CI job, without parsing YAML.

    PyYAML is not in the test environment's dependency set, and adding a parser to
    read four lines would put this test behind an install step it does not need.
    """
    lines = CI.read_text(encoding="utf-8").splitlines()
    out: list[str] = []
    in_job = False
    in_script = False
    for line in lines:
        if re.match(rf"^{re.escape(job)}\s*:\s*$", line):
            in_job = True
            continue
        if in_job and re.match(r"^\S", line):
            break
        if in_job and re.match(r"^\s{2}script:\s*$", line):
            in_script = True
            continue
        if in_script:
            if re.match(r"^\s{4}- ", line):
                out.append(line.strip()[2:])
                continue
            if re.match(r"^\s{4}#", line) or line.strip() == "":
                continue
            break
    if not out:
        pytest.fail(f".gitlab-ci.yml has no script for job {job!r} — this test is out of date")
    return out


def _ruff_paths(command: str) -> list[str]:
    """Extract the path arguments of a `ruff check ...` invocation."""
    tokens = shlex.split(command)
    if "ruff" not in " ".join(tokens):
        pytest.fail(f"not a ruff invocation: {command!r}")
    start = tokens.index("check") + 1
    return [t for t in tokens[start:] if not t.startswith("-")]


QUALITY_GATE = ROOT / "scripts/run_quality_gate.py"


def _quality_gate_command(name: str) -> list[str]:
    """Read the RUFF/MYPY command literal out of scripts/run_quality_gate.py."""
    tree = ast.parse(QUALITY_GATE.read_text(encoding="utf-8"))
    for node in ast.walk(tree):
        if isinstance(node, ast.Assign) and any(
            isinstance(target, ast.Name) and target.id == name for target in node.targets
        ):
            return [
                element.value
                for element in getattr(node.value, "elts", [])
                if isinstance(element, ast.Constant) and isinstance(element.value, str)
            ]
    pytest.fail(f"{QUALITY_GATE.name} no longer defines {name} as a list literal")


def test_both_entry_points_run_the_same_quality_gate() -> None:
    """Parity by construction: one script, invoked from both places.

    Textual comparison of two independent command lines could only ever detect the
    drift after it was written down twice. Since 2026-08-04 the tools are invoked in
    exactly one place — and that place records the run, which is what the assurance
    aggregator requires as evidence.
    """
    local = _makefile_recipe("api-lint")
    remote = _ci_script("api:quality")
    assert any("scripts/run_quality_gate.py" in line for line in local), (
        f"make api-lint no longer runs the quality gate script: {local}"
    )
    assert any("scripts/run_quality_gate.py" in line for line in remote), (
        f"api:quality no longer runs the quality gate script: {remote}"
    )
    assert not any("ruff" in line or "mypy" in line for line in local + remote), (
        "ruff/mypy are invoked directly again; a second invocation site can drift "
        "from the recorded one and leave the aggregate verdict describing a run "
        "that did not happen"
    )


def test_the_quality_gate_lints_every_directory_that_holds_korpus_code() -> None:
    """A directory nobody lints is a directory where the rules do not exist."""
    linted = set(_ruff_paths(" ".join(_quality_gate_command("RUFF"))))
    required = {"apps/api/src", "apps/api/tests", "apps/api/migrations", "scripts"}
    assert required <= linted, f"unlinted source directories: {sorted(required - linted)}"


def test_ruff_configuration_is_resolved_from_the_repository_root() -> None:
    """Without a root config ruff walks *above* the checkout to find one (ADR-0008)."""
    assert (ROOT / "ruff.toml").is_file(), (
        "ruff.toml is missing from the repository root: ruff would resolve its "
        "configuration by walking up the filesystem, so lint results would depend "
        "on where the repository was cloned"
    )


def test_mypy_is_invoked_so_that_its_configuration_applies() -> None:
    """`mypy apps/api/src` reads neither the strict flags nor packages = ["korpus"]."""
    tokens = _quality_gate_command("MYPY")
    assert "--config-file" in tokens, (
        "mypy is called without --config-file, so [tool.mypy] in "
        "apps/api/pyproject.toml does not apply and strict mode is silently off"
    )
    tail = tokens[tokens.index("--config-file") + 2 :]
    positional = [token for token in tail if not token.startswith("-")]
    assert not positional, (
        f"passing {positional} overrides packages = ['korpus'] from the config file, "
        "which leaves mypy unable to resolve the project's own imports"
    )
    source = QUALITY_GATE.read_text(encoding="utf-8")
    assert 'MYPYPATH' in source, (
        "the quality gate no longer sets MYPYPATH, so mypy cannot resolve korpus.*"
    )


def test_ci_does_not_retry_failing_jobs() -> None:
    """OPS-002: a retried job turns a reproducible failure into an intermittent one.

    Automatic retry is indistinguishable from a fix in the pipeline UI, and the
    flakiness it hides is exactly the signal the destruction stage relies on — one
    test that failed once in five runs turned out to be a real base64 defect.
    """
    document = pytest.importorskip("yaml").safe_load(CI.read_text(encoding="utf-8"))
    assert document.get("default", {}).get("retry") == 0, (
        "default.retry is not 0: failing jobs would be re-run, and an intermittent "
        "green would close a defect that is still there"
    )
    retried = [
        job
        for job, body in document.items()
        if isinstance(body, dict) and body.get("retry") not in (None, 0)
    ]
    assert not retried, f"these jobs override retry: {retried}"


def test_the_repository_walk_skips_everything_gitignore_excludes() -> None:
    """`validate_repository` walks the filesystem but claims to describe the repository.

    Anything a tool drops inside the checkout therefore counts as repository content.
    The first pipeline in which that job ran with a locked environment failed on five
    pip wheels under `.cache/pip`, which CI puts there by setting PIP_CACHE_DIR to
    `$CI_PROJECT_DIR/.cache/pip`. Keeping the two lists in step is what stops the next
    ignored directory from turning into a red gate about nothing.
    """
    ignored_dirs = {
        line.rstrip("/").strip()
        for line in (ROOT / ".gitignore").read_text(encoding="utf-8").splitlines()
        if line.strip().endswith("/") and not line.strip().startswith("#")
    }
    source = (ROOT / "scripts/validate_repository.py").read_text(encoding="utf-8")
    tree = ast.parse(source)
    skip: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Assign) and any(
            isinstance(t, ast.Name) and t.id == "SKIP_PARTS" for t in node.targets
        ):
            skip = {
                element.value
                for element in getattr(node.value, "elts", [])
                if isinstance(element, ast.Constant) and isinstance(element.value, str)
            }
    assert skip, "SKIP_PARTS is no longer a literal set — this test cannot read it"
    missing = sorted(ignored_dirs - skip)
    assert not missing, (
        "these directories are gitignored but still walked by validate_repository, so "
        f"whatever a tool writes there becomes a repository-validation failure: {missing}"
    )


def _imports_korpus(script: Path, seen: frozenset[Path] = frozenset()) -> bool:
    """True if `script` imports korpus.* directly or through another repo script.

    Resolved statically with ast, not by importing: the point is to answer the
    question CI answers at runtime — will this file need pydantic? — without needing
    the very environment whose absence is the defect.
    """
    if script in seen or not script.is_file():
        return False
    try:
        tree = ast.parse(script.read_text(encoding="utf-8"))
    except SyntaxError:  # pragma: no cover - a syntax error is compileall's job
        return False
    local: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom):
            module = node.module or ""
            if module == "korpus" or module.startswith("korpus."):
                return True
            local.append(module.split(".")[0])
        elif isinstance(node, ast.Import):
            for alias in node.names:
                if alias.name == "korpus" or alias.name.startswith("korpus."):
                    return True
                local.append(alias.name.split(".")[0])
    # scripts/ is on PYTHONPATH in several jobs, so a sibling script is a real edge.
    return any(
        _imports_korpus(script.parent / f"{name}.py", seen | {script})
        for name in local
        if (script.parent / f"{name}.py").is_file()
    )


def test_every_ci_job_that_runs_korpus_code_installs_the_locked_environment() -> None:
    """ADR-0008 defect (0): a job installed PyYAML alone and imported pydantic.

    That job was `repository:validate`; because nothing downstream declared `needs`,
    its failure skipped the other thirteen jobs and the pipeline finished red without
    running one test. The check is not "did someone mention scripts/" — it resolves
    which scripts actually reach korpus.* and demands a locked environment only there.
    """
    text = CI.read_text(encoding="utf-8")
    offenders: list[tuple[str, str]] = []
    for block in re.split(r"\n(?=\S)", text):
        header = block.split("\n", 1)[0]
        if not header.endswith(":") or header.startswith((".", "#", " ")):
            continue
        name = header[:-1]
        provisioned = "extends: .python-job" in block or "requirements.dev.lock" in block
        if provisioned:
            continue
        for called in re.findall(r"python3?\s+(?:-m\s+\S+\s+)?(scripts/[\w./-]+\.py)", block):
            if _imports_korpus(ROOT / called):
                offenders.append((name, called))
        if re.search(r"(?:^|\s)pytest\s", block):
            offenders.append((name, "pytest"))
    assert not offenders, (
        "these CI jobs run code that imports korpus.* without installing the locked "
        f"environment, so they die on the first import: {offenders}"
    )


def test_no_migration_revision_exceeds_the_alembic_version_column() -> None:
    """Alembic stores the current revision in version_num VARCHAR(32), fixed width.

    SQLite ignores declared VARCHAR lengths, so a 33-character revision id runs fine
    locally and forever; PostgreSQL raises StringDataRightTruncation. The first
    pipeline that reached a real database died on
    `UPDATE alembic_version SET version_num='0002_database_defense_and_vectors'`,
    which means no migration past 0001 had ever been applied to PostgreSQL — and the
    RLS, pgvector, backup and restore work sitting behind those migrations had never
    executed anywhere.
    """
    limit = 32
    offenders: list[tuple[str, int]] = []
    for path in sorted((ROOT / "apps/api/migrations/versions").glob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            target = None
            if isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name):
                target = node.target.id
            elif isinstance(node, ast.Assign) and len(node.targets) == 1:
                first = node.targets[0]
                target = first.id if isinstance(first, ast.Name) else None
            if target not in {"revision", "down_revision"}:
                continue
            value = node.value
            if (
                isinstance(value, ast.Constant)
                and isinstance(value.value, str)
                and len(value.value) > limit
            ):
                offenders.append((value.value, len(value.value)))
    assert not offenders, (
        f"these revision identifiers exceed alembic's version_num VARCHAR({limit}), so "
        f"the migration applying them fails on PostgreSQL while passing on SQLite: "
        f"{offenders}"
    )


def test_the_ci_configuration_is_parseable_yaml() -> None:
    """A .gitlab-ci.yml that does not parse produces a pipeline with zero jobs.

    On 2026-08-03 an edit left `- "$SYFT" dir:. -o ...` in a script block. YAML reads
    that as a double-quoted scalar followed by stray text and rejects the document.
    GitLab accepted the push, created a pipeline, and marked it failed with no jobs,
    no yaml_errors field and nothing in the UI to read — indistinguishable from a
    runner or quota problem. The cause only surfaced by POSTing to the pipeline API,
    which returns the parser message.

    The other gate-parity tests read this file with regexes and would happily keep
    passing on a broken document, so the parse itself has to be asserted.
    """
    yaml = pytest.importorskip(
        "yaml", reason="PyYAML is in requirements.runtime.lock; a missing parser here "
        "means the environment is wrong, not that the check is optional"
    )
    document = yaml.safe_load(CI.read_text(encoding="utf-8"))
    assert isinstance(document, dict), ".gitlab-ci.yml did not parse into a mapping"
    reserved = {"workflow", "default", "stages", "variables", "include"}
    jobs = [k for k in document if not k.startswith(".") and k not in reserved]
    assert len(jobs) >= 10, (
        f"only {len(jobs)} jobs parsed out of .gitlab-ci.yml — a truncated or "
        f"mis-nested document would look exactly like this: {jobs}"
    )
    for job in jobs:
        body = document[job]
        assert isinstance(body, dict), f"job {job!r} did not parse into a mapping"
        for key in ("script", "before_script", "after_script"):
            if key in body:
                assert isinstance(body[key], list), (
                    f"{job}.{key} parsed as {type(body[key]).__name__}, not a list of "
                    "commands — the usual cause is an unquoted line starting with a "
                    "quote or brace"
                )


CLOSURE_BUILDER = ROOT / "scripts/build_audit_closure.py"


def _cited_runtime_artefacts() -> set[str]:
    """Paths under var/ that the closure registry cites as evidence.

    Read from the EVIDENCE literal by ast, not from a duplicate list here: a copy
    would keep asserting about citations that had already moved.
    """
    tree = ast.parse(CLOSURE_BUILDER.read_text(encoding="utf-8"))
    cited: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Assign):
            targets = node.targets
        elif isinstance(node, ast.AnnAssign):
            targets = [node.target]
        else:
            continue
        if not any(isinstance(t, ast.Name) and t.id == "EVIDENCE" for t in targets):
            continue
        if node.value is None:
            continue
        for value in ast.walk(node.value):
            if (
                isinstance(value, ast.Constant)
                and isinstance(value.value, str)
                and value.value.startswith("var/")
            ):
                cited.add(value.value)
    if not cited:
        pytest.fail(
            f"{CLOSURE_BUILDER.name} no longer cites any produced artefact; if that is "
            "deliberate, delete these tests rather than leaving them vacuously green"
        )
    return cited


def _ci_producers(artefact: str) -> set[str]:
    """CI jobs whose `artifacts:` publish the given path."""
    text = CI.read_text(encoding="utf-8")
    producers: set[str] = set()
    for block in re.split(r"\n(?=\S)", text):
        header = block.split("\n", 1)[0]
        if not header.endswith(":") or header.startswith((".", "#", " ")):
            continue
        if re.search(rf"^\s+- {re.escape(artefact)}\s*$", block, re.MULTILINE):
            producers.add(header[:-1])
    return producers


def test_the_closure_check_runs_after_whatever_produces_the_evidence_it_resolves() -> None:
    """The registry cites var/mutation-report.json; api:assurance produces it.

    `build_audit_closure.py` used to run in `repository:validate`, the first stage —
    before any producer existed. Every pipeline from d894a89 to 2458942 died there
    with "cited evidence does not exist", which skipped the other thirteen jobs, so
    twelve commits of PostgreSQL, gate and admission work were never once exercised
    by CI. Locally the same command passed, because a report from an earlier run was
    still sitting in var/: `make clean && make audit-closure` reproduces the failure.

    Ordering is the invariant, and `needs: artifacts: true` is what carries the file.
    """
    text = CI.read_text(encoding="utf-8")
    consumers = [
        block.split(":", 1)[0]
        for block in re.split(r"\n(?=\S)", text)
        if not block.startswith((".", "#", " "))
        and re.search(r"^\s+- .*build_audit_closure\.py", block, re.MULTILINE)
    ]
    assert consumers, ".gitlab-ci.yml no longer runs build_audit_closure.py anywhere"
    for artefact in _cited_runtime_artefacts():
        producers = _ci_producers(artefact)
        assert producers, (
            f"the closure registry cites {artefact}, and no CI job publishes it as an "
            "artefact — the check can only pass on a runner that happens to have it"
        )
        for consumer in consumers:
            block = next(
                b for b in re.split(r"\n(?=\S)", text) if b.startswith(f"{consumer}:")
            )
            needed = set(re.findall(r"-\s+job:\s*(\S+)", block))
            assert needed & producers, (
                f"{consumer} resolves {artefact} but declares no needs on any of its "
                f"producers {sorted(producers)}; stage order alone does not download "
                "the artefact"
            )
            assert "artifacts: true" in block, (
                f"{consumer} needs a producer of {artefact} without artifacts: true, "
                "so the file is absent at runtime"
            )


def test_local_check_resolves_closure_evidence_only_after_producing_it() -> None:
    """`make check` on a clean tree must not depend on leftovers in var/.

    The Makefile had `audit-closure` as a prerequisite of `validate`, which is the
    first item of `check` — so the citation was resolved before `mutation` had run.
    The order held only because var/ survived between runs, which is exactly the
    state a fresh clone or a CI runner does not have.
    """
    order = _makefile_prerequisites("check")
    assert "audit-closure" in order, "make check no longer resolves the closure registry"
    assert "mutation" in order, "make check no longer runs the mutation gate"
    assert order.index("mutation") < order.index("audit-closure"), (
        f"make check resolves the closure registry before producing its evidence: {order}"
    )
    assert "audit-closure" not in _makefile_prerequisites("validate"), (
        "audit-closure is a prerequisite of validate again; validate runs first in "
        "check, so the citation would be resolved before the report exists"
    )


def test_the_assurance_runner_resolves_closure_evidence_only_after_producing_it() -> None:
    """Third executor of the same registry, same ordering requirement.

    `scripts/run_research_assurance.py` ran audit-closure as its second step and the
    mutation shards last. On a clean tree that run reported FAIL for a reason that had
    nothing to do with the code under test; on a dirty tree it reported PASS against a
    report produced by an earlier commit.
    """
    text = (ROOT / "scripts/run_research_assurance.py").read_text(encoding="utf-8")
    closure = text.index("build_audit_closure.py")
    mutation = text.index("run_mutation_shards.sh")
    assert mutation < closure, (
        "run_research_assurance.py resolves the closure registry before running the "
        "mutation shards that produce the report it cites"
    )


def test_the_closure_builder_still_resolves_produced_artefacts() -> None:
    """The relaxation belongs to the early callers, not to the one that runs last.

    `verify_closure_registry(..., include_produced=False)` exists so `api:test` can
    check the registry before anything has produced var/. If `build_audit_closure.py`
    ever passed the same flag, no executor would resolve COD-005's mutation report at
    all and the registry would read closed against a file nobody writes.
    """
    text = (ROOT / "scripts/build_audit_closure.py").read_text(encoding="utf-8")
    assert "include_produced=False" not in text, (
        "build_audit_closure.py runs after api:assurance; skipping produced artefacts "
        "there leaves every var/ citation unresolved by anyone"
    )
