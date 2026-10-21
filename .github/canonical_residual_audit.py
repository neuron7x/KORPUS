"""Read-only, pinned Git-history comparison; never execute legacy source."""
import ast
import hashlib
import json
import os
import subprocess
from pathlib import Path, PurePosixPath

CANDIDATE = "c2abdb69edd273c53e3a7bb2344f1ffb3be2a158"
MAIN = "345c0f7daf1da2152d0e554cc8733381ca5a1e9e"
PINS = {
    "agent/ci-local-ref-isolation-20261018": "df008029c6d630bdbe825cacd214715a95337772",
    "codex/issue-46-architecture": "4cfd7a26945617fbe2c14fcadcf335e3d6def48e",
    "codex/issue-6-release-evidence": "7469e4a080e4a4b0a98825d91c3d695594317e16",
    "proposal/korpus-capability-gateway-v1-20260904": "f90a409bb8e2ab13aa90a15ed979885e2f43b413",
    "work/issue-54-hosted-bootstrap": "aa8fb96463f967ad7e7e4b0a83633f283c9511b1",
}
ENV = {k: v for k, v in os.environ.items() if not k.startswith("GIT_") and k not in {"GH_TOKEN", "GITHUB_TOKEN"}}
ENV.update(GIT_NO_REPLACE_OBJECTS="1", GIT_CONFIG_NOSYSTEM="1", GIT_CONFIG_GLOBAL="/dev/null", GIT_TERMINAL_PROMPT="0")
OUT = Path(os.environ["RUNNER_TEMP"]) / "residual-audit"
OUT.mkdir(exist_ok=False)

def git(*args):
    result = subprocess.run(["/usr/bin/git", "--no-replace-objects", *args], env=ENV, capture_output=True, check=True, timeout=90)
    return result.stdout

def tree(ref):
    result = {}
    for row in git("ls-tree", "-r", "-z", ref).split(b"\0"):
        if row:
            metadata, path = row.split(b"\t", 1)
            mode, kind, sha = metadata.decode("ascii").split()
            result[path.decode("utf-8")] = {"mode": mode, "type": kind, "sha": sha}
    return result

def definitions(data, path):
    if not path.endswith(".py") or not data:
        return {}
    try:
        module = ast.parse(data)
    except (SyntaxError, ValueError, UnicodeError):
        return {"__parse_failed__": None}
    result = {}
    def visit(nodes, prefix=""):
        for node in nodes:
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                name = prefix + node.name
                result[name] = hashlib.sha256(ast.dump(node, include_attributes=False).encode()).hexdigest()
                if isinstance(node, ast.ClassDef):
                    visit(node.body, name + ".")
    visit(module.body)
    return result

def is_generated(path):
    return path.startswith(("reports/", "candidate_evidence/", "LINEAGE/", "handoff/")) or path in {
        "SOURCE_MANIFEST.json", "DISTRIBUTION_MANIFEST.json", "PACKAGE_BUILD.json", "RELEASE_ENVELOPE.json"
    }

def read(entry):
    if entry is None or entry["type"] != "blob" or entry["mode"] not in {"100644", "100755"}:
        return b""
    size = int(git("cat-file", "-s", entry["sha"]))
    if size > 2_000_000:
        raise RuntimeError("Unexpected oversized source blob")
    return git("cat-file", "blob", entry["sha"])

assert git("rev-parse", "HEAD").decode().strip() == os.environ["GITHUB_SHA"]
assert git("rev-parse", "HEAD^").decode().strip() == CANDIDATE
assert git("rev-parse", "refs/remotes/origin/main").decode().strip() == MAIN
for branch, sha in PINS.items():
    assert git("rev-parse", "refs/remotes/origin/" + branch).decode().strip() == sha, "Source branch drift"
current = tree(CANDIDATE)
summary = {"schema": "korpus.residual-static-audit.v1", "candidate": CANDIDATE, "main": MAIN,
           "request_head": os.environ["GITHUB_SHA"], "run_id": os.environ["GITHUB_RUN_ID"],
           "limits": "Blob/AST equality is evidence, not automatic semantic approval. No legacy code executed.",
           "branches": [], "merge_authorized": False, "production_authorized": False}
for index, (branch, sha) in enumerate(PINS.items()):
    common = git("merge-base", CANDIDATE, sha).decode().strip()
    original, legacy = tree(common), tree(sha)
    changed = sorted(path for path in original.keys() | legacy.keys() if original.get(path) != legacy.get(path))
    record = {"branch": branch, "head": sha, "merge_base": common, "changes": []}
    prefix = OUT / f"branch-{index}"
    for path in changed:
        relative = PurePosixPath(path)
        assert not relative.is_absolute() and ".." not in relative.parts
        b, l, c = original.get(path), legacy.get(path), current.get(path)
        row = {"path": path, "base": b, "legacy": l, "candidate": c,
               "same_blob_and_mode": l == c, "generated": is_generated(path)}
        if not row["generated"]:
            data = {"base": read(b), "legacy": read(l), "candidate": read(c)}
            defs = {role: definitions(value, path) for role, value in data.items()}
            added_changed = {k: v for k, v in defs["legacy"].items() if defs["base"].get(k) != v}
            row["legacy_changed_definitions"] = sorted(added_changed)
            row["identical_definitions"] = sorted(k for k, v in added_changed.items() if defs["candidate"].get(k) == v)
            row["different_definitions"] = sorted(k for k in added_changed if k in defs["candidate"] and defs["candidate"][k] != added_changed[k])
            row["missing_definitions"] = sorted(k for k in added_changed if k not in defs["candidate"])
            for role, value in data.items():
                if value:
                    target = prefix / role / relative
                    target.parent.mkdir(parents=True, exist_ok=True)
                    target.write_bytes(value)
            for role, a, z in [("introduced", common, sha), ("candidate_delta", sha, CANDIDATE)]:
                value = git("diff", "--no-ext-diff", "--no-textconv", a, z, "--", path)
                target = prefix / (role + ".diff")
                with target.open("ab") as handle:
                    handle.write(value)
        record["changes"].append(row)
    summary["branches"].append(record)
    print(branch, "changed", len(changed), "exact", sum(r["same_blob_and_mode"] for r in record["changes"]), flush=True)
(OUT / "summary.json").write_text(json.dumps(summary, indent=2, sort_keys=True) + "\n")
files = sorted(p for p in OUT.rglob("*") if p.is_file())
assert sum(p.stat().st_size for p in files) <= 50_000_000
checksums = {str(p.relative_to(OUT)): hashlib.sha256(p.read_bytes()).hexdigest() for p in files}
(OUT / "SHA256.json").write_text(json.dumps(checksums, indent=2, sort_keys=True) + "\n")
print("Evidence files:", len(files), "bytes:", sum(p.stat().st_size for p in files))
