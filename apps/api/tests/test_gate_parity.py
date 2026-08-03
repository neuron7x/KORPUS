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


def test_ruff_covers_the_same_paths_locally_and_in_ci() -> None:
    """A path linted only in CI is a rule the author cannot satisfy before pushing."""
    local = next(c for c in _makefile_recipe("api-lint") if "ruff" in c)
    remote = next(c for c in _ci_script("api:quality") if "ruff" in c)
    assert _ruff_paths(local) == _ruff_paths(remote), (
        "make api-lint and api:quality lint different paths; "
        f"local={_ruff_paths(local)} ci={_ruff_paths(remote)}"
    )


def test_ruff_configuration_is_resolved_from_the_repository_root() -> None:
    """Without a root config ruff walks *above* the checkout to find one (ADR-0008)."""
    assert (ROOT / "ruff.toml").is_file(), (
        "ruff.toml is missing from the repository root: ruff would resolve its "
        "configuration by walking up the filesystem, so lint results would depend "
        "on where the repository was cloned"
    )


@pytest.mark.parametrize(
    ("where", "command"),
    [
        ("Makefile:api-lint", lambda: next(c for c in _makefile_recipe("api-lint") if "mypy" in c)),
        ("ci:api:quality", lambda: next(c for c in _ci_script("api:quality") if "mypy" in c)),
    ],
)
def test_mypy_is_invoked_so_that_its_configuration_applies(where: str, command) -> None:
    """`mypy apps/api/src` reads neither the strict flags nor packages = ["korpus"]."""
    invocation = command()
    assert "--config-file" in invocation, (
        f"{where}: mypy is called without --config-file, so [tool.mypy] in "
        "apps/api/pyproject.toml does not apply and strict mode is silently off"
    )
    assert "MYPYPATH=" in invocation, (
        f"{where}: mypy is called without MYPYPATH, so it cannot resolve korpus.*"
    )
    tokens = shlex.split(invocation)
    tail = tokens[tokens.index("--config-file") + 2 :]
    positional = [t for t in tail if not t.startswith("-")]
    assert not positional, (
        f"{where}: passing {positional} overrides packages = ['korpus'] from the "
        "config file, which leaves mypy unable to resolve the project's own imports"
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
