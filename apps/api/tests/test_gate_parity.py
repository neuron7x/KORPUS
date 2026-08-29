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
import json
import re
import shlex
import subprocess
import sys
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
    assert "MYPYPATH" in source, (
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
        line.rstrip("/").strip().removeprefix("**/")
        for line in (ROOT / ".gitignore").read_text(encoding="utf-8").splitlines()
        if line.strip().endswith("/") and not line.strip().startswith("#")
    }
    source = (ROOT / "apps/api/src/korpus/repository_requirements.py").read_text(encoding="utf-8")
    tree = ast.parse(source)
    skip: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Assign) and any(
            isinstance(t, ast.Name) and t.id == "SKIP_PARTS" for t in node.targets
        ):
            # `frozenset({...})` is a Call whose argument holds the elements, while a
            # bare `{...}` holds them directly. Reading only the second silently
            # produced an empty set when the constant was wrapped.
            value = node.value
            if isinstance(value, ast.Call) and value.args:
                value = value.args[0]
            skip = {
                element.value
                for element in getattr(value, "elts", [])
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
        "yaml",
        reason="PyYAML is in requirements.runtime.lock; a missing parser here "
        "means the environment is wrong, not that the check is optional",
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
            block = next(b for b in re.split(r"\n(?=\S)", text) if b.startswith(f"{consumer}:"))
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


def test_every_job_that_runs_the_suite_has_git_in_its_image() -> None:
    """test_manifest_generation shells out to git; three images so far lacked it.

    `python:*-slim` and `pgvector/pgvector` both ship without git, and the failure is
    FileNotFoundError at collection time — not a skip, not a warning. .python-job
    installs it and says why in a comment, but a comment does not reach a job that
    declares its own image: api:postgres-and-restore repeated the identical failure on
    the first pipeline that reached it (2026-08-05, #38).

    Skipping the test where git is absent would be worse than the failure: it is what
    keeps build artefacts out of the release manifest, and a skip reads green.
    """
    text = CI.read_text(encoding="utf-8")
    offenders = []
    for block in re.split(r"\n(?=\S)", text):
        header = block.split("\n", 1)[0]
        if not header.endswith(":") or header.startswith(("#", " ")):
            continue
        name = header[:-1]
        if not re.search(r"pytest[^\n]*apps/api/tests", block):
            continue
        if name == ".python-job" or "extends: .python-job" in block:
            continue
        if not re.search(r"apt-get install[^\n]*\bgit\b", block):
            offenders.append(name)
    assert not offenders, (
        f"these jobs run the suite in an image with no git, so "
        f"test_manifest_generation dies at collection: {offenders}"
    )


def test_the_desired_state_manifest_matches_the_files_it_fingerprints() -> None:
    """The manifest is derived, and nothing regenerates it on the way to a commit.

    `config/operations/desired-state.json` pins the sha256 of .gitlab-ci.yml, both
    Dockerfiles, both lock files and the kubernetes tree. Editing any of them makes it
    stale, and the only thing that said so was `repository:validate` — the first job
    of a pipeline, i.e. after the push. It caught the author of this very test twice
    on 2026-08-05 (pipelines #37 and the one after #38 failed for no other reason).

    Asserting it here moves the signal into the local pytest run, which happens before
    the commit rather than after it.
    """
    result = subprocess.run(
        [sys.executable, "scripts/generate_desired_state.py", "--check"],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, (
        "the desired-state manifest no longer matches its inputs; regenerate it with "
        f"`python3 scripts/generate_desired_state.py`:\n{result.stdout}"
    )


#: Discovered, not enumerated. This tuple named its two members until 2026-08-06, and
#: a third lock — `apps/api/requirements.lock` — sat beside them carrying 56 known
#: advisories, no hashes at all, and pins eight packages behind the runtime lock,
#: including `cryptography==46.0.4` (the exact CVE set already fixed here) and
#: `pypdf==5.9.0`, the parser that reads uploaded documents. Nothing installed from it,
#: which is why it survived: every gate enumerated the files it already knew about, so
#: the one nobody knew about was outside all of them. It is the most obviously-named of
#: the three, so `pip install -r apps/api/requirements.lock` was one keystroke away.
LOCK_FILES = tuple(sorted((ROOT / "apps/api").glob("requirements*.lock")))


def test_every_pinned_dependency_carries_a_hash() -> None:
    """A version pin says which release to fetch; a hash says which bytes.

    pip-audit warned about this on every run — "users are encouraged to fully hash
    their pinned dependencies" — and the warning scrolled past in a job that was
    skipped for two days anyway. Without hashes, `pip install -r lock` reproduces the
    build only for as long as nobody replaces an artefact on the index.
    """
    unhashed: list[str] = []
    for path in LOCK_FILES:
        text = path.read_text(encoding="utf-8")
        # One requirement is a pin line plus its continuation lines; the next pin
        # starts at column zero.
        pin = r"^([\w.\-\[\]]+==[^\s\\]+)([^\n]*(?:\n[ \t].*)*)"
        for block in re.finditer(pin, text, re.M):
            if "--hash=sha256:" not in block.group(2):
                unhashed.append(f"{path.name}: {block.group(1)}")
    assert not unhashed, (
        "these pins name a version but not the bytes, so the install is reproducible "
        f"only while the index is: {sorted(set(unhashed))}"
    )


def test_every_install_of_a_lock_file_requires_those_hashes() -> None:
    """Hashes in the file do nothing unless the installer is told to enforce them.

    pip silently ignores --hash lines without --require-hashes: the lock would look
    hardened in review and install anything at runtime — the shape of defect this
    repository keeps finding, where the artefact says one thing and the execution
    says another.
    """
    offenders: list[str] = []
    for path, text in (
        ("Makefile", MAKEFILE.read_text(encoding="utf-8")),
        (".gitlab-ci.yml", CI.read_text(encoding="utf-8")),
        ("apps/api/Dockerfile", (ROOT / "apps/api/Dockerfile").read_text(encoding="utf-8")),
    ):
        for line in text.splitlines():
            # Matching "pip install" missed the Makefile entirely, which invokes
            # $(PIP): the first version of this test passed while the Makefile
            # installed unverified — a check that reads past the thing it guards.
            installs_lock = re.search(r"\binstall\b", line) and ".lock" in line
            if installs_lock and "--require-hashes" not in line:
                offenders.append(f"{path}: {line.strip()}")
    assert not offenders, (
        f"pip ignores --hash entries unless --require-hashes is passed: {offenders}"
    )


def test_every_job_running_the_suite_uses_the_production_interpreter() -> None:
    """Tests on one Python say nothing about a service shipped on another.

    api:postgres-and-restore ran on the pgvector image's own python3, which on trixie
    is 3.13, while apps/api/Dockerfile ships 3.12.13 and every other job here uses it.
    The only job that exercised PostgreSQL — the dialect-specific validity filters,
    the retrieval projection, the audit head update — was therefore testing a
    different interpreter from production, and nothing in the repository said so.

    What said so, eventually, was the hashed lock: pip refused a cp313 wheel against
    cp312 hashes. That is a check catching a defect it was not written for, which is
    luck. This asserts the property directly.
    """
    dockerfile = (ROOT / "apps/api/Dockerfile").read_text(encoding="utf-8")
    match = re.search(r"^ARG PYTHON_IMAGE=(\S+)", dockerfile, re.M)
    assert match, "apps/api/Dockerfile no longer declares PYTHON_IMAGE"
    production = match.group(1)

    text = CI.read_text(encoding="utf-8")
    offenders: list[tuple[str, str]] = []
    for block in re.split(r"\n(?=\S)", text):
        header = block.split("\n", 1)[0]
        if not header.endswith(":") or header.startswith(("#", " ")):
            continue
        name = header[:-1]
        if not re.search(r"pytest[^\n]*apps/api/tests", block):
            continue
        if "extends: .python-job" in block:
            continue
        image = re.search(r"^\s+image:\s*(\S+)\s*$", block, re.M)
        if image is None or image.group(1) != production:
            offenders.append((name, image.group(1) if image else "<none or nested>"))
    assert not offenders, (
        f"these jobs run the suite on an interpreter other than {production}: "
        f"{offenders} — a service tested on one Python and shipped on another has "
        "been tested somewhere else"
    )


def test_the_coverage_thresholds_are_checked_where_coverage_is_produced() -> None:
    """A predicate evaluated only at the end of the pipeline is evaluated only rarely.

    `coverage_branch` lives in the release aggregator, which runs in `source:package`
    from artefacts produced four stages earlier — so on 2026-08-05, the first pipeline
    that ever reached that job, branch coverage turned out to have been below policy
    for as long as anyone had been writing tests. `--cov-fail-under` had not caught it
    because it bounds one combined line-and-branch number, not the two the policy
    states separately.
    """
    for label, lines in (
        ("make api-test", _makefile_recipe("api-test")),
        ("api:test", _ci_script("api:test")),
    ):
        assert any("scripts/check_coverage_thresholds.py" in line for line in lines), (
            f"{label} no longer checks the policy coverage minimums: {lines}"
        )
        assert any("--cov-report=json" in line for line in lines), (
            f"{label} does not produce the JSON report the threshold check reads"
        )


def test_the_coverage_thresholds_are_not_a_second_copy_of_the_policy() -> None:
    """Two places holding the same number is one place holding a stale one.

    The first version of this test looked for `= 0.xx` and passed while the file said
    `"line": 0.50` — a guard reading past the thing it guards, for the second time
    today. It now resolves the `minimums` literal by ast and requires every value to
    come from the policy.
    """
    tree = ast.parse((ROOT / "scripts/check_coverage_thresholds.py").read_text(encoding="utf-8"))
    literal = next(
        (
            node.value
            for node in ast.walk(tree)
            if isinstance(node, ast.Assign)
            and any(isinstance(t, ast.Name) and t.id == "minimums" for t in node.targets)
            and isinstance(node.value, ast.Dict)
        ),
        None,
    )
    assert literal is not None, "check_coverage_thresholds.py no longer builds `minimums`"
    constants = [
        ast.unparse(value)
        for value in literal.values
        if not (
            isinstance(value, ast.Call)
            and "policy" in ast.unparse(value)
            and "minimum_" in ast.unparse(value)
        )
    ]
    assert not constants, (
        f"these thresholds do not come from the policy: {constants} — a second copy of "
        "a number is a second thing to forget, and the drift looks like a passing build"
    )


APPLICATION = ROOT / "apps/api/src/korpus/application"


def _functions_calling(source: str, attribute: str) -> list[ast.FunctionDef]:
    """Functions whose body contains a call to `<something>.<attribute>(...)`."""
    tree = ast.parse(source)
    found = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef):
            continue
        for inner in ast.walk(node):
            if (
                isinstance(inner, ast.Call)
                and isinstance(inner.func, ast.Attribute)
                and inner.func.attr == attribute
            ):
                found.append(node)
                break
    return found


def test_every_document_lookup_is_followed_by_an_access_decision() -> None:
    """`get_document` returns the row; it does not decide who may have it.

    `list_documents` filters by corpus, clearance, classification and compartment.
    `get_document` filters by nothing — on PostgreSQL row-level security refuses
    first, and on SQLite nothing does. Every caller in the application layer is
    therefore responsible for `policy.can_access_document`, and on 2026-08-05 one of
    them was not doing it: `IngestionJobService.submit_version` would queue a version
    against a document in a corpus the actor held no entitlement to. The control
    existed in one dialect and the application leaned on it without saying so.

    Asserted structurally rather than by testing each route, because the defect is a
    caller that forgets — including one written next week.
    """
    offenders: list[str] = []
    for path in sorted(APPLICATION.glob("*.py")):
        source = path.read_text(encoding="utf-8")
        for function in _functions_calling(source, "get_document"):
            body = ast.unparse(function)
            if "can_access_document" not in body:
                offenders.append(f"{path.name}::{function.name}")
    assert not offenders, (
        "these functions read a document without deciding whether the actor may have "
        f"it: {offenders} — get_document does not filter by corpus"
    )


def test_scripts_reading_installed_metadata_run_under_the_locked_interpreter() -> None:
    """`python3 script.py` asks the system environment, not the locked one.

    generate_supply_chain_inventory.py reads license expressions from installed
    distributions. Invoked with a bare interpreter it resolved five of sixty-eight and
    reported the rest as unknown — a number that described the invocation rather than
    the supply chain. Under the venv the lock builds, all sixty-eight resolve.
    """
    metadata_readers = [
        path.name
        for path in sorted((ROOT / "scripts").glob("*.py"))
        if "importlib.metadata" in path.read_text(encoding="utf-8")
    ]
    assert metadata_readers, "no script reads installed metadata; this test is out of date"

    makefile = MAKEFILE.read_text(encoding="utf-8")
    offenders = [
        f"{name}: {line.strip()}"
        for name in metadata_readers
        for line in makefile.splitlines()
        if name in line and line.lstrip().startswith("python3 ")
    ]
    assert not offenders, (
        "these recipes read installed distribution metadata with the system "
        f"interpreter, so the answer depends on the machine: {offenders}"
    )


def test_the_module_budget_is_enforced_in_both_entry_points() -> None:
    """A ceiling nothing checks is a note, not a ratchet."""
    assert "module-budget" in _makefile_prerequisites("validate"), (
        "make validate no longer enforces the module budget"
    )
    assert any("check_module_budget.py" in line for line in _ci_script("repository:validate")), (
        "repository:validate no longer enforces the module budget"
    )


def test_file_modes_are_enforced_in_both_entry_points() -> None:
    """A rule nothing runs is a comment. Ruff covers Python under four directories only."""
    assert "file-modes" in _makefile_prerequisites("validate"), (
        "make validate no longer enforces the file-mode rule"
    )
    assert any("check_file_modes.py" in line for line in _ci_script("repository:validate")), (
        "repository:validate no longer enforces the file-mode rule"
    )


def test_the_source_manifest_is_verified_in_both_entry_points() -> None:
    """SOURCE_MANIFEST.json is the anchor every release report binds itself to.

    It was verified only inside full-ssot-package, at the end of the release graph. A commit
    could leave it describing a tree that no longer exists, `make validate` stayed green,
    the pipeline stayed green, and the mismatch surfaced at packaging time — after the
    evidence claiming that manifest had already been produced.
    """
    assert "source-manifest-verify" in _makefile_prerequisites("validate"), (
        "make validate no longer verifies the source manifest"
    )
    assert any("verify_source_manifest.py" in line for line in _ci_script("repository:validate")), (
        "repository:validate no longer verifies the source manifest"
    )


def test_the_source_manifest_describes_this_tree() -> None:
    result = subprocess.run(
        [sys.executable, "scripts/verify_source_manifest.py"],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=False,
        env={"PATH": "/usr/bin:/bin", "PYTHONPATH": "scripts"},
    )
    report = json.loads(result.stdout)
    assert report["valid"], report["failures"]
    assert report["files"] > 1000, "the manifest describes almost nothing"


def test_every_tracked_file_carries_the_mode_its_shebang_implies() -> None:
    """Eight different modes were in the tree before this rule; the drift is the defect.

    The rule is ruff's own EXE001/EXE002 — shebang means executable — applied to the set
    `git ls-files` returns rather than to Python in four directories.
    """
    result = subprocess.run(
        [sys.executable, "scripts/check_file_modes.py"],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=False,
        env={"PATH": "/usr/bin:/bin"},
    )
    report = json.loads(result.stdout)
    assert report["status"] == "PASS", report["violations"]
    assert report["files_checked"] > 1000, "the gate measured almost nothing"


def test_every_module_is_in_the_budget() -> None:
    """ "Not yet budgeted" is how a file reaches two thousand lines unnoticed."""
    result = subprocess.run(
        [sys.executable, "scripts/check_module_budget.py"],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=False,
        env={"PYTHONPATH": str(ROOT / "apps/api/src"), "PATH": "/usr/bin:/bin"},
    )
    report = json.loads(result.stdout)
    assert report["unbudgeted"] == [], (
        f"these modules have no recorded ceiling: {report['unbudgeted']}"
    )
    assert report["status"] == "PASS", report["violations"]


def test_no_job_reaches_a_relaxed_runner() -> None:
    """The relaxation was removed rather than scoped, once a tool existed that needs none.

    Rootless buildkit failed twice on a plain docker executor: the seccomp profile
    blocked `fork/exec /proc/self/exe`, and then `mount src=proc` was refused. Both are
    fixable with SYS_ADMIN, which is privileged escape under a different flag name —
    it would have satisfied the letter of the ban on `privileged: true` while removing
    exactly the isolation the ban exists for.

    kaniko builds in userspace with no daemon and no capabilities beyond an ordinary
    container's, so no job needs a relaxed runner and none may quietly acquire one.
    """
    text = CI.read_text(encoding="utf-8")
    # Job names contain a colon (`container:build`), so the header is everything up to
    # the final one — splitting on the first produced "container" and made the test
    # fail against a correct pipeline.
    tagged = [
        block.split("\n", 1)[0].rstrip(":")
        for block in re.split(r"\n(?=\S)", text)
        if not block.startswith((".", "#", " ")) and "korpus-buildkit" in block
    ]
    assert tagged == [], (
        f"these jobs reach the relaxed-seccomp runner: {tagged}. Nothing needs it since "
        "the image build moved to kaniko; a job acquiring the tag is a job asking for "
        "weaker isolation without saying why"
    )
    # Non-comment lines only: the first version matched the phrase inside the comment
    # that explains why privileged mode is banned, so documenting the ban broke the
    # check on the ban. Fifth instance today of a guard reading text instead of the
    # thing it guards.
    directives = [line for line in text.splitlines() if not line.lstrip().startswith("#")]
    assert not any("privileged: true" in line for line in directives), (
        "a privileged runner would make the tag pointless and is banned outright"
    )


def test_the_requirements_register_is_current() -> None:
    """A generated document that drifts is worse than none: it reads as authoritative.

    §2.5 asks an outside assessor to judge this system, and the register is the first
    thing they read. Regenerating it in `validate` means a requirement added without
    regenerating fails the gate rather than leaving the document quietly one behind.
    """
    register = ROOT / "docs/operations/REQUIREMENTS_REGISTER.md"
    before = register.read_text(encoding="utf-8")

    result = subprocess.run(
        [sys.executable, "scripts/export_requirements.py"],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=False,
        env={"PYTHONPATH": str(ROOT / "apps/api/src"), "PATH": "/usr/bin:/bin"},
    )

    assert result.returncode == 0, result.stdout
    assert register.read_text(encoding="utf-8") == before, (
        "the requirements register is stale; run `make requirements-register`"
    )


def test_every_ci_image_pins_an_exact_tag() -> None:
    """A tag that does not exist fails at pull time, after the pipeline has queued.

    Written after `gcr.io/kaniko-project/executor:v1.25.0-debug` was pinned without
    checking that the tag existed: the job died in `prepare_executor` with "manifest
    unknown", which is a slower and more confusing way to learn a version number was
    invented than reading it here.

    Existence still cannot be asserted offline — that is what the registry answers. The
    property that can be held here is that every image names a specific version, so
    `latest` cannot drift under a pipeline whose whole claim is reproducibility.
    """
    text = CI.read_text(encoding="utf-8")
    images = [
        match.group(1).strip()
        for match in re.finditer(r"^\s*(?:image:|name:)\s*([^\s#]+)\s*$", text, re.M)
        if "/" in match.group(1) or ":" in match.group(1)
    ]
    assert images, ".gitlab-ci.yml declares no images — this test is out of date"

    unpinned = [
        image
        for image in images
        if image.endswith(":latest") or ":" not in image.rsplit("/", 1)[-1]
    ]
    assert not unpinned, (
        f"these CI images do not pin a version: {unpinned}. `latest` is whatever the "
        "registry served that morning, in a pipeline whose claim is reproducibility"
    )

    # SUP-001. A tag is a name the registry may repoint at any time; a digest is the
    # bytes. The version invented on 2026-08-05 reached a queued pipeline before
    # anything caught it, and a digest could not have been invented at all.
    without_digest = [image for image in images if "@sha256:" not in image]
    assert not without_digest, f"these CI images are pinned by tag alone: {without_digest}"


def test_a_failed_generator_does_not_leave_its_previous_report_behind() -> None:
    """Stale evidence and absent evidence must not be the same state.

    On 2026-08-05 six mutants went INVALID after their targets moved to a new module.
    The run exited non-zero and `var/mutation-report.json` stayed behind from the run
    before, so the operational gate read a report from a different tree and reported
    "generated from a different source tree" — accurate, and three steps removed from
    the cause. A missing report says "the generator did not finish"; a stale one says
    something about a tree that no longer exists.
    """
    shards = (ROOT / "scripts/run_mutation_shards.sh").read_text(encoding="utf-8")

    assert "rm -f" in shards and "mutation-report.json" in shards, (
        "the shard runner no longer removes its report when a shard fails"
    )
    failure_block = shards[shards.index('if [[ "$failed" -ne 0 ]]') :]
    assert "rm -f" in failure_block.split("exit 1")[0], (
        "the report is removed outside the failure path, so a successful run would "
        "delete the evidence it just produced"
    )


def test_the_environment_drift_check_runs_in_the_pipeline() -> None:
    """OPS-004. A comparator nobody invokes is documentation.

    The check is deliberately in two halves: the pipeline observes its own checkout,
    which proves the comparator runs and that the manifest describes this tree. It is
    not evidence about a cluster — that observation has to be taken on the host that is
    running, and taking it here would fingerprint the build host, which is the failure
    the check exists to catch, performed by the checker.
    """
    script = _ci_script("repository:validate")
    observe = [line for line in script if "check_environment_drift.py --observe" in line]
    compare = [line for line in script if "--observation" in line]
    assert observe, "repository:validate no longer takes an environment observation"
    assert compare, "repository:validate observes the environment and never compares it"
    assert script.index(observe[0]) < script.index(compare[0]), (
        "the comparison runs before the observation it reads"
    )


def test_the_browsers_copy_of_the_request_contract_cannot_go_stale() -> None:
    """WEB-001. Two copies of the domain rules, and the copy is the one that drifts.

    apps/web/public/contract.js carries the field constraints and the role table the
    operator consoles validate against. Stale means the forms refuse what the API
    accepts — a failure nobody reports, because nobody reports a form that would not
    submit something they never tried to submit.
    """
    assert any(
        "generate_web_contract.py --check" in line for line in _ci_script("repository:validate")
    ), "repository:validate no longer checks the generated web contract"
    assert "web-contract-check" in _makefile_prerequisites("web-build"), (
        "make web-build no longer checks the generated web contract"
    )


def test_the_web_gate_runs_its_own_negative_controls() -> None:
    """`node --check <file>` exits 0 for any file containing an `import`.

    Verified on node v22.23.1: a file holding both an import and `const y = ;` passes.
    Two such invocations stood in `npm run lint` until 2026-08-05, so from the moment
    app.js became a module the web syntax check was inert and kept printing success.
    The parse now happens inside validate.mjs on stdin with an explicit --input-type,
    and apps/web/tests/validate_gate.test.mjs mutates a copy of the tree to prove each
    control can still fail.
    """
    package = json.loads((ROOT / "apps/web/package.json").read_text(encoding="utf-8"))
    for name in ("lint", "typecheck"):
        assert "--check" not in package["scripts"][name], (
            f"apps/web `{name}` is back to `node --check`, which does not check modules"
        )
    assert "node --test" in package["scripts"].get("test", ""), (
        "apps/web has no test script, so the gate's negative controls never run"
    )
    assert any("run test" in line for line in _ci_script("web:test")), (
        "web:test no longer runs the negative controls for its own gate"
    )
    assert "test" in _makefile_recipe("web-build")[1], (
        "make web-build no longer runs the web test suite"
    )


def test_web_release_gates_execute_the_built_surface_in_a_real_browser() -> None:
    ci = _ci_script("web:test")
    browser_indexes = [index for index, line in enumerate(ci) if "test:browser" in line]
    build_indexes = [index for index, line in enumerate(ci) if "run build" in line]
    assert browser_indexes and build_indexes and min(browser_indexes) > max(build_indexes), (
        "web:test must execute browser E2E after the production build"
    )
    recipe = _makefile_recipe("web-build")
    browser_indexes = [index for index, line in enumerate(recipe) if "test:browser" in line]
    build_indexes = [index for index, line in enumerate(recipe) if "run build" in line]
    assert browser_indexes, "make web-build no longer exercises the browser surface"
    assert min(browser_indexes) > max(build_indexes), (
        "make web-build must build before it executes browser E2E"
    )


def test_audit_closure_csv_generator_uses_canonical_lf_lines() -> None:
    """Generated closure CSV must not reintroduce CRLF as diff-check whitespace."""
    source = (ROOT / "scripts/build_audit_closure.py").read_text(encoding="utf-8")
    assert source.count('lineterminator="\\n"') == 2, (
        "both closure CSV writers must force canonical LF line endings"
    )


def test_real_browser_e2e_runner_cannot_disappear_silently() -> None:
    """WEB-001 keeps a real-browser executable surface even when CI cannot navigate.

    The local browser report is deliberately not production OIDC evidence, but deleting
    the CDP runner or its package entrypoint must still fail repository verification.
    """
    package = json.loads((ROOT / "apps/web/package.json").read_text(encoding="utf-8"))
    command = package["scripts"].get("test:browser", "")
    runner = ROOT / "apps/web/scripts/browser_e2e.mjs"
    assert command == "node scripts/browser_e2e.mjs", "browser E2E entrypoint drifted"
    assert runner.is_file(), "real Chromium/CDP browser E2E runner is missing"
    source = runner.read_text(encoding="utf-8")
    for token in (
        "LOCAL_BROWSER_POLICY_COMPATIBLE",
        "consumer_authenticated_boot",
        "evidence_render_escapes_xss",
        "typed_429_is_not_rendered_as_outage",
        "mobile_viewport_has_no_horizontal_overflow",
        "operator_console_roles_and_preview_gate",
        "network_navigation_executed:false",
        "release_tag:release.tag",
        "git_head:gitHead",
    ):
        assert token in source, f"browser E2E contract lost {token}"


def test_every_writing_console_previews_before_it_acts() -> None:
    """WEB-001's acceptance predicate needs the workflows to be safe, not merely present.

    An approval is irreversible and lands on whatever version id the field holds. The
    submit button ships disabled, a preview enables it, and any edit disables it again
    — so nothing irreversible fires on a first click.
    """
    console = (ROOT / "apps/web/public/console.html").read_text(encoding="utf-8")
    for workflow in ("ingest", "review", "rescind"):
        assert f'id="{workflow}-preview"' in console, f"{workflow} has no preview step"
        assert re.search(rf'id="{workflow}-submit"[^>]*disabled', console), (
            f"{workflow} can be submitted before anything was previewed"
        )


def test_every_lock_file_is_audited_for_known_vulnerabilities() -> None:
    """The dev lock had never been audited by anything.

    `python:audit` read `requirements.runtime.lock` alone, so the packages CI installs
    on a runner holding a checkout of this repository were outside every security gate.
    That is a strictly larger blast radius than a runtime package inside a read-only
    container: a compromised test dependency reads the tree and holds the pipeline's
    credentials. Running pip-audit against the dev lock for the first time on
    2026-08-06 found PYSEC-2026-1845 in pytest 9.0.2.
    """
    script = _ci_script("python:audit")
    audited = {
        line.rsplit(" ", 1)[-1]
        for line in script
        if "pip-audit" in line and line.rstrip().endswith(".lock")
    }
    locks = {f"apps/api/{path.name}" for path in (ROOT / "apps/api").glob("requirements*.lock")}

    assert locks, "no lock files found — this test is out of date"
    assert locks <= audited, f"these lock files are never audited: {sorted(locks - audited)}"


def test_no_lock_file_pins_a_package_with_a_known_advisory_recorded_here() -> None:
    """A regression pin for the advisories this repository has already answered.

    pip-audit needs the network and is a CI job. This is the offline half: once a
    version has been found vulnerable and replaced, going back to it must fail in the
    test suite rather than wait for the security stage — which runs four stages later
    and, for the dev lock, did not run at all until 2026-08-06.
    """
    known_bad = {
        # (package, first version that is NOT affected, advisory)
        ("pytest", "9.0.3", "PYSEC-2026-1845"),
        ("cryptography", "50.0.0", "PYSEC-2026-3552/3553/3554"),
    }
    text = "\n".join(
        path.read_text(encoding="utf-8") for path in (ROOT / "apps/api").glob("requirements*.lock")
    )
    pinned = dict(re.findall(r"^([A-Za-z0-9_.\-]+)==([0-9][^\s\\]*)", text, re.MULTILINE))

    for package, fixed, advisory in known_bad:
        version = pinned.get(package)
        if version is None:
            continue
        assert _version_tuple(version) >= _version_tuple(fixed), (
            f"{package}=={version} is below {fixed}, which {advisory} requires"
        )


def _version_tuple(value: str) -> tuple[int, ...]:
    return tuple(int(part) for part in re.findall(r"\d+", value))


def test_the_development_proxy_mirrors_the_production_edge() -> None:
    """`make web-run` and `make api-run` could not talk to each other.

    config.js points the browser at `/api`; the static dev server had no such route, so
    every request 404'd and the two dev servers were unusable together. The obvious fix
    — pointing config.js at http://127.0.0.1:8000 — "works" only by moving the session
    cookie cross-origin, and same-origin is the security property here, not a
    convenience: `credentials: "same-origin"` and the `__Host-` cookie prefix both mean
    nothing across origins.

    So serve.mjs proxies the same prefix nginx does, and strips it the same way.
    apps/web/tests/validate_gate.test.mjs mutates each half and asserts the gate refuses.
    """
    serve = (ROOT / "apps/web/scripts/serve.mjs").read_text(encoding="utf-8")
    nginx = (ROOT / "apps/web/nginx.conf").read_text(encoding="utf-8")
    config = (ROOT / "apps/web/public/config.js").read_text(encoding="utf-8")

    assert 'apiUrl: "/api"' in config, (
        "the browser no longer talks to a same-origin path; a cross-origin apiUrl "
        "silently drops the session cookie and the CSRF double-submit with it"
    )
    assert 'const API_PREFIX = "/api/";' in serve
    assert "location /api/ {" in nginx
    assert "proxy_pass http://api:8000/;" in nginx, (
        "nginx no longer strips the prefix, so the dev proxy strips one nginx keeps"
    )
    assert "development proxy: no rate limit, no CSP, no TLS" in serve, (
        "a dev proxy that looks like the production edge is how one gets served through"
    )


def test_the_bootstrap_produces_a_corpus_that_can_actually_answer() -> None:
    """`make bootstrap` approved a version that stated neither date.

    Approval refuses that — without `effective_from` or `publication_date` the version
    would govern every past date — so the documented way to get a running local instance
    failed at its last step from the moment that rule landed. Found 2026-08-06 by
    running it.

    A fixed date rather than today's: a bootstrap that seeds a different corpus on every
    run cannot be compared against itself, and "which edition was in force on date X" is
    the question this system exists to answer.
    """
    source = (ROOT / "scripts/bootstrap_local.py").read_text(encoding="utf-8")

    assert "BOOTSTRAP_PUBLICATION_DATE = date(" in source
    assert "publication_date=BOOTSTRAP_PUBLICATION_DATE" in source
    assert "date.today()" not in source.split("def main")[1].split("VersionCreate")[1][:400]


def test_ci_secret_scan_is_bound_to_the_pipeline_revision() -> None:
    ci = CI.read_text(encoding="utf-8")

    command = (
        'gitleaks detect --source . --no-banner --redact --exit-code 1 --log-opts "$CI_COMMIT_SHA"'
    )
    assert command in ci


def test_every_script_is_reachable_from_a_runner() -> None:
    """A script nobody runs is a script nobody maintains — and one that is cited.

    `scripts/export_audit.py` was named as AUD-004's evidence in the closure register
    while no Makefile target, CI job or test invoked it: a citation that names a file
    rather than a run, which is the shape ADR-0008 exists to refuse. And
    `scripts/prepare_postgres_test_role.py` was a ten-line compatibility wrapper around
    `prepare_postgres_role.py` that nothing called — a decoy one keystroke from the live
    script, so half the edits to "the role provisioner" would have landed on the copy
    that never runs. It is deleted.
    """
    scripts = sorted(
        [
            path.name
            for path in (ROOT / "scripts").glob("*.py")
            if path.name != "__init__.py"
            and 'if __name__ == "__main__"' in path.read_text(encoding="utf-8", errors="ignore")
        ]
        + [path.name for path in (ROOT / "scripts").glob("*.sh")]
    )
    assert scripts, "no scripts found — this test is out of date"

    haystacks = {
        "Makefile": MAKEFILE.read_text(encoding="utf-8"),
        "CI": CI.read_text(encoding="utf-8")
        + "\n"
        + "\n".join(
            path.read_text(encoding="utf-8", errors="ignore")
            for path in (ROOT / ".github/workflows").glob("*.yml")
        ),
        "tests": "\n".join(
            path.read_text(encoding="utf-8") for path in (ROOT / "apps/api/tests").rglob("*.py")
        ),
        "scripts": "\n".join(
            path.read_text(encoding="utf-8", errors="ignore")
            for path in (ROOT / "scripts").rglob("*")
            if path.is_file() and "__pycache__" not in path.parts
        ),
        # A documented tool a human runs by hand is reached; a tool nothing mentions
        # at all is not.
        "docs": "\n".join(
            path.read_text(encoding="utf-8", errors="ignore")
            for path in (ROOT / "docs").rglob("*.md")
        )
        + (ROOT / "CONTRIBUTING.md").read_text(encoding="utf-8"),
    }

    unreachable = [
        script
        for script in scripts
        # A script naming only itself is not referenced: `scripts` includes the file.
        if not any(
            script in text
            for name, text in haystacks.items()
            if name != "scripts" or text.count(script) > 1
        )
    ]

    assert not unreachable, f"no runner mentions these scripts: {unreachable}"


def test_the_pipeline_graph_is_consistent() -> None:
    """Every `needs` names a real job that runs earlier, and no artefact has two producers.

    A `needs` on a job in a later stage is accepted by GitLab and never satisfied — the
    dependent job runs with the artefact absent, which is how `audit:closure` spent two
    days consuming a mutation report that had not been produced yet. Two producers for
    one path is the same defect from the other side: whichever ran last wins, and the
    evidence a later job reads is nondeterministic.
    """
    import yaml

    document = yaml.safe_load(CI.read_text(encoding="utf-8"))
    stages = document["stages"]
    jobs = {
        name: body
        for name, body in document.items()
        if isinstance(body, dict)
        and name not in {"workflow", "default", "variables"}
        and not name.startswith(".")
    }
    assert jobs, "no jobs parsed — this test is out of date"

    problems: list[str] = []
    produced: dict[str, list[str]] = {}
    for name, job in jobs.items():
        stage = job.get("stage")
        if stage not in stages:
            problems.append(f"{name}: unknown stage {stage!r}")
            continue
        for need in job.get("needs", []) or []:
            target = need["job"] if isinstance(need, dict) else need
            if target not in jobs:
                problems.append(f"{name}: needs unknown job {target!r}")
            elif stages.index(jobs[target]["stage"]) > stages.index(stage):
                problems.append(f"{name} ({stage}) needs {target} in a later stage")
        for path in (job.get("artifacts") or {}).get("paths", []) or []:
            produced.setdefault(path.rstrip("/"), []).append(name)

    duplicated = {path: who for path, who in produced.items() if len(who) > 1}
    assert not problems, problems
    assert not duplicated, f"these artefacts have more than one producer: {duplicated}"


def test_no_mutant_covers_two_call_sites_at_once() -> None:
    """Two occurrences under one mutant is not two covered call sites.

    The substitution replaces *every* occurrence of the target string, so a mutant whose
    line appears twice mutates both and is answered by whichever site its test happens to
    reach. The other is never individually falsified, and the catalogue reports a kill
    for it anyway.

    This is not hypothetical. `M05_SQL_CLEARANCE_FILTER_REMOVED` passed for months that
    way; splitting the retrieval projection out of the repository left the `list_documents`
    predicate alone and the mutant immediately survived. The sweep on 2026-08-06 found
    three more — the malware scan on both ingestion paths, the per-version cap declared
    twice, and the lease check guarding both `complete` and `fail`.
    """
    import sys

    sys.path.insert(0, str(ROOT / "scripts"))
    from run_mutation_tests import MUTANTS

    ambiguous = []
    absent = []
    for mutant in MUTANTS:
        source = ROOT / mutant.file
        if not source.is_file():
            absent.append(f"{mutant.id}: {mutant.file} does not exist")
            continue
        occurrences = source.read_text(encoding="utf-8").count(mutant.old)
        if occurrences == 0:
            absent.append(f"{mutant.id}: target not present in {mutant.file}")
        elif occurrences > 1:
            ambiguous.append(f"{mutant.id}: target appears {occurrences}× in {mutant.file}")

    assert not absent, absent
    assert not ambiguous, (
        "these mutants replace more than one occurrence, so one kill is credited to "
        f"several call sites: {ambiguous}"
    )


def test_every_mutant_cites_a_test_that_exists() -> None:
    """A mutant citing a renamed test dies on collection error rather than on the defect.

    It still reports KILLED — pytest exits non-zero either way — so the catalogue would
    read as covered while nothing was exercised.
    """
    import sys

    sys.path.insert(0, str(ROOT / "scripts"))
    import ast

    from run_mutation_tests import MUTANTS

    missing = []
    node_cache: dict[Path, set[str]] = {}
    for mutant in MUTANTS:
        for spec in mutant.tests:
            path, _, node = spec.partition("::")
            target = ROOT / path
            if not target.is_file():
                missing.append(f"{mutant.id}: {path} does not exist")
                continue
            if not node:
                continue
            if target not in node_cache:
                tree = ast.parse(target.read_text(encoding="utf-8"))
                names = {
                    item.name
                    for item in tree.body
                    if isinstance(item, (ast.FunctionDef, ast.AsyncFunctionDef))
                }
                for item in tree.body:
                    if isinstance(item, ast.ClassDef):
                        names.update(
                            f"{item.name}::{child.name}"
                            for child in item.body
                            if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef))
                        )
                node_cache[target] = names
            normalized = node.split("[")[0]
            if normalized not in node_cache[target]:
                missing.append(f"{mutant.id}: {node} not found exactly in {path}")

    assert not missing, missing


def test_source_inspection_mutants_use_a_full_repository_copy() -> None:
    """A test that reads source beside itself must see the mutated bytes, not the SSOT tree.

    M148 survived when application mutations used only a PYTHONPATH overlay: the structural
    answer-path test resolves ``src/korpus/api`` from its own file location, so it inspected
    the unmutated repository.  This flag is load-bearing mutation-harness semantics.
    """
    import sys

    sys.path.insert(0, str(ROOT / "scripts"))
    from run_mutation_tests import MUTANTS

    mutant = next(
        item for item in MUTANTS if item.id == "M148_CONVERSATION_ROUTE_BYPASSES_THE_BOUND"
    )
    assert mutant.full_copy is True


def test_mutant_ids_are_unique() -> None:
    """An id is how a mutant is cited in the closure register and matched to a finding."""
    import sys
    from collections import Counter

    sys.path.insert(0, str(ROOT / "scripts"))
    from run_mutation_tests import MUTANTS

    counts = Counter(mutant.id for mutant in MUTANTS)

    assert [identifier for identifier, count in counts.items() if count > 1] == []


def test_the_import_pipeline_refuses_a_draft_manifest() -> None:
    """`build_import_manifest.py` marks what it could not read; the importer must refuse it.

    The draft exists so a curator edits one file instead of typing four hundred entries.
    It works only if the sentinel is load-bearing: a manifest that still says
    REVIEW_REQUIRED must fail loudly, or the convenience becomes a way to enter the
    corpus described by a guess — an issuer nobody stated, a revision parsed out of
    "v2_final_FINAL", a date that decides when a document took force.
    """
    builder = (ROOT / "scripts/build_import_manifest.py").read_text(encoding="utf-8")
    importer = (ROOT / "scripts/import_corpus.py").read_text(encoding="utf-8")

    assert 'REVIEW_REQUIRED = "REVIEW_REQUIRED"' in builder
    assert '"review_sentinel": REVIEW_REQUIRED' in builder
    assert 'manifest.get("review_sentinel"' in importer
    assert "awaiting review" in importer
    # Never derived, because a filename does not say them. `issuer` may be supplied for
    # a whole batch; the other two cannot be, and must always start as the sentinel.
    assert '"issuer": arguments.issuer or REVIEW_REQUIRED' in builder
    for field in ("revision", "publication_date"):
        assert f'"{field}": REVIEW_REQUIRED' in builder, field


def test_the_drive_snapshot_is_a_snapshot_and_not_a_sync() -> None:
    """A live dependency on a consumer cloud would let a document change after review.

    The version the system cites would no longer be the version somebody approved, and
    nothing in the answer would say so. So the fetch records provenance and reports a
    changed file rather than acting on it: promoting a change to a new corpus version,
    with a revision and a supersession edge, is a curator's decision.
    """
    fetch = (ROOT / "scripts/fetch_drive_snapshot.py").read_text(encoding="utf-8")

    assert '"drive_id"' in fetch and '"drive_md5"' in fetch and '"sha256"' in fetch
    assert '"CHANGED"' in fetch
    # The transport stays outside the trust boundary: no OAuth client, no network call
    # anywhere the parser can reach.
    assert "rclone" in fetch
    assert "googleapiclient" not in fetch and "google.oauth2" not in fetch


def test_runtime_lock_satisfies_every_declared_runtime_dependency() -> None:
    """The install contract and the hash-pinned artifact must describe the same graph root.

    A lock can be internally exact and still be impossible to install from the project's
    own metadata. That happened when pyproject required pypdf<6 while the release lock
    pinned pypdf==6.14.2. CI normally installs the lock directly, so the contradiction
    survived unless somebody attempted an editable/wheel install.
    """
    import tomllib

    from packaging.requirements import Requirement
    from packaging.utils import canonicalize_name
    from packaging.version import Version

    pyproject = tomllib.loads((ROOT / "apps/api/pyproject.toml").read_text(encoding="utf-8"))
    declared = [Requirement(item) for item in pyproject["project"]["dependencies"]]
    lock_text = (ROOT / "apps/api/requirements.runtime.lock").read_text(encoding="utf-8")
    locked = {
        canonicalize_name(name): Version(version)
        for name, version in re.findall(r"(?m)^([A-Za-z0-9_.-]+)==([^\s\\]+)", lock_text)
    }

    missing: list[str] = []
    incompatible: list[str] = []
    for requirement in declared:
        name = canonicalize_name(requirement.name)
        version = locked.get(name)
        if version is None:
            missing.append(requirement.name)
        elif version not in requirement.specifier:
            incompatible.append(f"{requirement} vs locked {version}")

    assert not missing, f"runtime direct dependencies missing from lock: {missing}"
    assert not incompatible, f"pyproject/lock version contract drift: {incompatible}"


def test_mutation_harness_does_not_credit_bootstrap_errors_as_kills(monkeypatch) -> None:
    import sys
    from pathlib import Path

    sys.path.insert(0, str(ROOT / "scripts"))
    import run_mutation_tests as runner

    environment = runner.mutation_test_environment(pythonpath=ROOT / "apps/api/src")
    assert "KORPUS_MUTATION_JOBS" not in environment
    assert "KORPUS_MUTATION_SHARDS" not in environment

    assert runner._mutation_status_from_pytest_exit(0) == "SURVIVED"
    assert runner._mutation_status_from_pytest_exit(1) == "KILLED"
    for bootstrap_or_collection_error in (2, 3, 4, 5):
        assert runner._mutation_status_from_pytest_exit(bootstrap_or_collection_error) == "ERROR"

    source = Path(runner.run_mutant.__code__.co_filename).read_text(encoding="utf-8")
    assert "verify_mutation_baseline(mutants)" in source


def test_production_gate_generators_are_wired_to_the_ci_evidence_locations() -> None:
    """A gate script not executed where its substrate exists is documentation, not a gate."""
    postgres = "\n".join(_ci_script("api:postgres-and-restore"))
    package = "\n".join(_ci_script("source:package"))
    assert "run_postgres_security_gate.py" in postgres
    assert (
        "run_engineering_production_gate.py --report var/research-assurance-report.json" in package
    )
    assert "run_exact_environment_gate.py" in package
    assert "run_inference_security_gate.py" in package
    assert "run_mutation_production_gate.py" in package
    assert "snapshot_production_assurance.py" in package


def test_production_snapshot_wrapper_is_never_used_by_the_promotion_target() -> None:
    """A diagnostic snapshot path must not leak into production authorization."""
    recipe = "\n".join(_makefile_recipe("production-assurance"))
    release_recipe = "\n".join(_makefile_recipe("production-release"))
    assert "snapshot_production_assurance.py" not in recipe
    assert "snapshot_production_assurance.py" not in release_recipe


def test_ci_pythonpath_contains_repository_root_for_scripts_package_imports() -> None:
    """Repository validators import scripts.* and must work on a clean runner."""
    import yaml

    document = yaml.safe_load(CI.read_text(encoding="utf-8"))
    pythonpath = str(document.get("variables", {}).get("PYTHONPATH", ""))
    assert "$CI_PROJECT_DIR" in pythonpath.split(":"), pythonpath
    assert "$CI_PROJECT_DIR/apps/api/src" in pythonpath.split(":"), pythonpath


def test_the_file_mode_gate_refuses_a_tree_it_cannot_read_instead_of_crashing(
    tmp_path: Path,
) -> None:
    """An unpacked release archive has no .git, and `git ls-files` exits 128 there.

    The gate used to raise CalledProcessError: a traceback on stderr, no JSON on stdout. A
    gate that cannot say what it found looks the same as one that crashed for an unrelated
    reason — and the archive is exactly where an auditor would run it.
    """
    staged = tmp_path / "scripts"
    staged.mkdir()
    (staged / "check_file_modes.py").write_bytes(
        (ROOT / "scripts/check_file_modes.py").read_bytes()
    )

    result = subprocess.run(
        [sys.executable, "scripts/check_file_modes.py"],
        cwd=tmp_path,
        capture_output=True,
        text=True,
        check=False,
        env={"PATH": "/usr/bin:/bin", "HOME": str(tmp_path)},
    )
    assert result.returncode != 0, "a tree it cannot read must not pass"
    report = json.loads(result.stdout)
    assert report["status"] == "UNAVAILABLE"
    assert report["files_checked"] == 0
