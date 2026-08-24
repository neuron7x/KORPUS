#!/usr/bin/env python3
"""Deterministically stage, promote, verify, and (on failure) roll back the public UI."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.request
from datetime import UTC, datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
IMAGE = "nginx:1.31.3-alpine@sha256:4a73073bd557c65b759505da037898b61f1be6cbcc3c2c3aeac22d2a470c1752"
CONTAINER = "korpus-public-edge"
FORBIDDEN = {"console.html", "console.js", "console_rules.js"}
GENERATED = {"PUBLIC_MANIFEST.json"}
REQUIRED = {"index.html", "app.js", "styles.css", "tokens.css", "sw.js", "config.js"}


def canonical_bytes(value: object) -> bytes:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()


def artifact_manifest(source: Path) -> dict[str, object]:
    """Return a stable manifest and refuse unsafe or incomplete build trees."""
    records: list[dict[str, object]] = []
    names: set[str] = set()
    for path in sorted(source.rglob("*"), key=lambda item: item.relative_to(source).as_posix()):
        relative = path.relative_to(source).as_posix()
        if path.is_symlink():
            raise ValueError(f"public artifact contains symlink: {relative}")
        if not path.is_file():
            continue
        if relative in FORBIDDEN or relative in GENERATED:
            continue
        data = path.read_bytes()
        names.add(relative)
        records.append({"path": relative, "bytes": len(data), "sha256": hashlib.sha256(data).hexdigest()})
    missing = sorted(REQUIRED - names)
    if missing:
        raise ValueError(f"public artifact is incomplete: {', '.join(missing)}")
    body: dict[str, object] = {"schema": "korpus.public-web-manifest.v1", "files": records}
    body["tree_sha256"] = hashlib.sha256(canonical_bytes(body)).hexdigest()
    return body


def normalize_public_permissions(root: Path) -> None:
    root.chmod(0o755)
    for path in root.rglob("*"):
        path.chmod(0o755 if path.is_dir() else 0o644)


def stage_release(source: Path, releases: Path) -> tuple[Path, dict[str, object]]:
    manifest = artifact_manifest(source)
    digest = str(manifest["tree_sha256"])
    destination = releases / digest
    if destination.exists():
        if artifact_manifest(destination) != manifest:
            raise RuntimeError(f"content-addressed release was modified: {destination}")
        normalize_public_permissions(destination)
        return destination, manifest
    releases.mkdir(parents=True, exist_ok=True)
    temporary = Path(tempfile.mkdtemp(prefix=f".{digest}.", dir=releases))
    try:
        records = manifest["files"]
        if not isinstance(records, list):
            raise TypeError("manifest files must be a list")
        for record in records:
            if not isinstance(record, dict):
                raise TypeError("manifest record must be an object")
            relative = Path(str(record["path"]))
            target = temporary / relative
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(source / relative, target)
        (temporary / "PUBLIC_MANIFEST.json").write_bytes(canonical_bytes(manifest) + b"\n")
        normalize_public_permissions(temporary)
        os.replace(temporary, destination)
    finally:
        shutil.rmtree(temporary, ignore_errors=True)
    return destination, manifest


def run(command: list[str]) -> None:
    subprocess.run(command, cwd=ROOT, check=True)


def start_edge(release: Path, nginx_config: Path) -> None:
    subprocess.run(["docker", "rm", "-f", CONTAINER], cwd=ROOT, check=False, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    run([
        "docker", "run", "-d", "--name", CONTAINER, "--restart", "unless-stopped",
        "--network", "host", "--add-host", "api:127.0.0.1",
        "-v", f"{nginx_config.resolve()}:/etc/nginx/nginx.conf:ro",
        "-v", f"{release.resolve()}:/usr/share/nginx/html:ro",
        "--read-only", "--tmpfs", "/tmp:size=64m,mode=1777",
        "--tmpfs", "/var/cache/nginx:size=32m", "--security-opt", "no-new-privileges:true",
        "--entrypoint", "sh", IMAGE, "-c", 'mkdir -p /tmp/nginx && exec nginx -g "daemon off;"',
    ])


def probe(base_url: str, attempts: int = 15) -> None:
    checks = (("/healthz", b'"status":"ok"'), ("/", b"KORPUS"), ("/api/health", b'"status"'))
    last_error: Exception | None = None
    for _ in range(attempts):
        try:
            for suffix, marker in checks:
                with urllib.request.urlopen(base_url.rstrip("/") + suffix, timeout=5) as response:
                    if response.status != 200 or marker not in response.read():
                        raise RuntimeError(f"invalid probe response: {suffix}")
            return
        except (OSError, RuntimeError, urllib.error.URLError) as error:
            # The bounded retry is part of deployment admission; all other failures
            # (programming errors included) escape immediately and therefore fail closed.
            last_error = error
            time.sleep(1)
    raise RuntimeError(f"deployment probes failed: {last_error}")


def write_receipt(path: Path, *, status: str, manifest: dict[str, object], previous: str | None) -> None:
    body = {
        "schema": "korpus.public-web-deployment-receipt.v1",
        "status": status,
        "generated_at": datetime.now(UTC).isoformat(),
        "git_head": subprocess.run(["git", "rev-parse", "HEAD"], cwd=ROOT, check=True, capture_output=True, text=True).stdout.strip(),
        "release_sha256": manifest["tree_sha256"],
        "previous_release_sha256": previous,
        "manifest_sha256": hashlib.sha256(canonical_bytes(manifest)).hexdigest(),
    }
    body["receipt_sha256"] = hashlib.sha256(canonical_bytes(body)).hexdigest()
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(".tmp")
    temporary.write_bytes(json.dumps(body, ensure_ascii=False, indent=2, sort_keys=True).encode() + b"\n")
    os.replace(temporary, path)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--base-url", default="http://127.0.0.1:8081")
    parser.add_argument("--no-build", action="store_true")
    args = parser.parse_args()
    state = ROOT / "var/public"
    releases, current = state / "releases", state / "CURRENT"
    previous = current.read_text(encoding="utf-8").strip() if current.is_file() else None
    legacy = state / "edge/html"
    if previous is None and legacy.is_dir():
        # First adoption is reversible too: capture the deployment that is serving
        # before replacing its container mount.
        _legacy_release, legacy_manifest = stage_release(legacy, releases)
        previous = str(legacy_manifest["tree_sha256"])
    if not args.no_build:
        run(["npm", "--prefix", "apps/web", "run", "lint"])
        run(["npm", "--prefix", "apps/web", "run", "test"])
        run(["npm", "--prefix", "apps/web", "run", "build"])
    release, manifest = stage_release(ROOT / "apps/web/dist", releases)
    config = state / "edge/nginx.conf"
    if not config.is_file():
        raise RuntimeError("rendered public nginx config is missing; run scripts/serve_public.sh once")
    try:
        start_edge(release, config)
        probe(args.base_url)
    except Exception as deployment_error:
        rollback_error: Exception | None = None
        try:
            if not previous or not (releases / previous).is_dir():
                raise RuntimeError("no verified previous release is available")
            start_edge(releases / previous, config)
            probe(args.base_url)
        except (OSError, RuntimeError, subprocess.CalledProcessError, urllib.error.URLError) as error:
            rollback_error = error
        write_receipt(
            state / "DEPLOYMENT_RECEIPT.json",
            status="ROLLBACK_FAILED" if rollback_error else "ROLLED_BACK",
            manifest=manifest,
            previous=previous,
        )
        if rollback_error:
            raise RuntimeError(f"deployment failed ({deployment_error}); rollback failed ({rollback_error})") from deployment_error
        raise
    current.write_text(str(manifest["tree_sha256"]) + "\n", encoding="utf-8")
    write_receipt(state / "DEPLOYMENT_RECEIPT.json", status="PASS", manifest=manifest, previous=previous)
    print(json.dumps({"status": "PASS", "release_sha256": manifest["tree_sha256"], "release": str(release)}))
    return 0


if __name__ == "__main__":
    sys.exit(main())
