#!/usr/bin/env python3
"""Qualify the local-storage laptop Compose profile with a real authenticated HTTP journey."""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import re
import shutil
import signal
import subprocess
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from urllib.parse import quote

from compose_pilot_environment import (
    RUNTIME_INSPECTION,
    SERVICES,
    SmokeFailure,
    Workspace,
    check_edge,
    check_port,
    isolated_environment,
    parse_services,
    require,
    sanitize,
)
from pilot_acceptance_contract import Credentials
from run_pilot_acceptance import Options, PilotAcceptance

ROOT = Path(__file__).resolve().parents[1]
CORPUS = "pilot-smoke-compose"


class PacedAcceptance(PilotAcceptance):
    """Space completed probe stages without changing the Nginx limiter or retrying writes."""

    def passed(self) -> None:
        super().passed()
        time.sleep(0.25)


class ComposeSmoke:
    def __init__(self, source: Path, startup_timeout: int, readers: int) -> None:
        self.source = source
        self.startup_timeout = startup_timeout
        self.readers = readers
        self.environment = isolated_environment(dict(os.environ))
        self.docker: list[str] = []
        self.workspace: Workspace | None = None
        self.started = False
        self.secrets: list[str] = []
        self.phase = "preflight"
        self.report: dict[str, Any] = {
            "schema": "korpus.compose-pilot-smoke.v1",
            "status": "FAIL",
            "measured_at": datetime.now(UTC).isoformat(),
            "transport": "real_compose_http",
            "profile": "local_laptop",
            "s3_verified": False,
            "worm_verified": False,
            "owner_host_verified": False,
            "external_https_verified": False,
            "browser_ui_verified": False,
            "load_verified": False,
            "recovery_verified": False,
            "production_authorized": False,
            "cleanup": "not_required",
        }

    def execute(self, arguments: list[str], timeout: int = 30) -> str:
        try:
            result = subprocess.run(
                arguments,
                cwd=self.source,
                env=self.environment,
                text=True,
                capture_output=True,
                timeout=timeout,
                check=False,
            )
        except subprocess.TimeoutExpired as exc:
            raise SmokeFailure("command exceeded its bounded deadline") from exc
        if result.returncode:
            self.report.setdefault("command_exit_code", result.returncode)
            self.report.setdefault("diagnostic", sanitize(result.stderr, self.secrets)[-6000:])
            raise SmokeFailure("command failed; see sanitized diagnostic and failed phase")
        return result.stdout

    def compose(self, arguments: list[str], timeout: int = 30) -> str:
        require(self.workspace is not None, "private workspace is unavailable")
        assert self.workspace is not None
        return self.execute(self.docker + self.workspace.arguments() + arguments, timeout)

    def preflight(self) -> None:
        require(
            30 <= self.startup_timeout <= 900, "startup timeout must be between 30 and 900 seconds"
        )
        require(3 <= self.readers <= 5, "reader count must be between three and five")
        overrides = ("DOCKER_HOST", "DOCKER_CONTEXT", "DOCKER_TLS_VERIFY", "DOCKER_CERT_PATH")
        require(
            not any(os.environ.get(key) for key in overrides),
            "Docker endpoint environment overrides are not accepted",
        )
        check_port()
        docker = shutil.which("docker", path=self.environment["PATH"])
        require(docker, "Docker CLI is unavailable; no Compose qualification was performed")
        assert docker is not None
        endpoint = self.execute(
            [docker, "context", "inspect", "--format", "{{.Endpoints.docker.Host}}"], 15
        ).strip()
        require(
            endpoint.startswith("unix:///") and "\n" not in endpoint,
            "smoke requires a local Unix Docker endpoint",
        )
        self.docker = [docker, "--host", endpoint]
        self.report["docker_server_version"] = self.execute(
            [*self.docker, "version", "--format", "{{.Server.Version}}"], 15
        ).strip()
        self.report["compose_version"] = self.execute(
            [*self.docker, "compose", "version", "--short"], 15
        ).strip()
        self.report["source_commit"] = self.execute(["git", "rev-parse", "HEAD"]).strip()
        self.report["tracked_source_dirty"] = bool(
            self.execute(["git", "status", "--porcelain", "--untracked-files=no"]).strip()
        )

    def prepare(self) -> None:
        self.phase = "private_inputs"
        self.workspace = Workspace.create(self.source)
        self.report["project"] = self.workspace.project
        self.execute(["bash", str(self.workspace.state / "scripts/init_local_secrets.sh")])
        self.workspace.prepare_override()
        for path in self.workspace.secret_files.values():
            value = path.read_text(encoding="utf-8").strip()
            self.secrets.extend((value, quote(value, safe="")))
        self.phase = "configuration_isolation"
        rendered = self.execute(
            self.docker + self.workspace.arguments(frozen=False) + ["config", "--format", "json"]
        )
        self.workspace.freeze(json.loads(rendered))
        self.report["compose_input_sha256"] = self.workspace.frozen_digest
        require(
            not any(self.resources().values()),
            "random project already has resources; refusing to adopt it",
        )

    def resources(self) -> dict[str, list[str]]:
        require(self.workspace is not None, "private workspace is unavailable")
        assert self.workspace is not None
        self.workspace.assert_owned()
        label = "label=com.docker.compose.project=" + self.workspace.project
        commands = {
            "containers": ["ps", "--all", "--quiet"],
            "volumes": ["volume", "ls", "--quiet"],
            "networks": ["network", "ls", "--quiet"],
        }
        return {
            name: self.execute(self.docker + command + ["--filter", label]).split()
            for name, command in commands.items()
        }

    def start(self) -> None:
        self.phase = "compose_build_and_readiness"
        check_port()
        self.started = True
        self.compose(
            [
                "up",
                "-d",
                "--build",
                "--wait",
                "--wait-timeout",
                str(self.startup_timeout),
                "web",
                "worker",
            ],
            self.startup_timeout + 1200,
        )
        self.phase = "service_state"
        output = self.compose(["ps", "--all", "--format", "json"])
        services = parse_services(output)
        require(set(services) == SERVICES, "Compose did not create every expected service")
        for name, state in services.items():
            if name == "migrate":
                require(
                    state["state"] == "exited" and state["exit_code"] == 0,
                    "initialization service did not succeed",
                )
            else:
                require(state["state"] == "running", "runtime service is not running")
                if name != "worker":
                    require(state["health"] == "healthy", "runtime service is not healthy")
        self.report["services"] = services

    def inspect_runtime(self) -> None:
        self.phase = "runtime_configuration"
        result = self.compose(
            [
                "exec",
                "-T",
                "api",
                "/usr/local/bin/korpus-entrypoint",
                "python",
                "-c",
                RUNTIME_INSPECTION,
            ]
        )
        facts = json.loads(result)
        require(
            facts
            == {
                "database": "postgresql",
                "object_store": "local",
                "object_root": "/data/objects",
                "quarantine_root": "/data/quarantine",
                "process_uid": 10001,
                "object_owner_uid": 10001,
                "quarantine_owner_uid": 10001,
                "malware_scan": "clamd",
                "ingestion": "durable_async",
                "auth": "jwt",
                "review_separation": True,
                "schema": "migrations",
            },
            "container runtime does not match the required stack",
        )
        self.report["runtime"] = facts
        self.phase = "nginx_readiness_and_host_boundary"
        asyncio.run(check_edge())
        self.report["exact_hostname_boundary_verified"] = True

    def mint(self, subject: str, roles: str, corpus: str = CORPUS) -> str:
        token = self.compose(
            [
                "exec",
                "-T",
                "api",
                "/usr/local/bin/korpus-entrypoint",
                "python",
                "/app/scripts/mint_review_token.py",
                "--subject",
                subject,
                "--roles",
                roles,
                "--corpora",
                corpus,
                "--minutes",
                "10",
            ]
        ).strip()
        require(
            bool(re.fullmatch(r"[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+", token)),
            "token minting returned an invalid envelope",
        )
        self.secrets.append(token)
        return token

    def acceptance(self) -> None:
        self.phase = "synthetic_credentials"
        credentials = Credentials(
            self.mint("smoke-owner", "curator"),
            tuple(
                self.mint(f"smoke-reader-{index}", "user") for index in range(1, self.readers + 1)
            ),
            (
                self.mint("smoke-metadata", "curator"),
                self.mint("smoke-content", "reviewer"),
                self.mint("smoke-approver", "reviewer"),
            ),
            self.mint("smoke-outsider", "user", "pilot-smoke-outsider"),
        )
        self.phase = "authenticated_durable_journey"
        options = Options(
            "http://127.0.0.1:3000/api", CORPUS, exercise_fixture=True, job_timeout=120
        )
        self.report["probe_stage_pause_seconds"] = 0.25
        result = PacedAcceptance(options, credentials).run()
        self.report["acceptance"] = result
        require(result.get("status") == "PASS", "authenticated pilot acceptance failed")
        require(
            result.get("ingestion_mode") == "durable_async",
            "acceptance did not use the real worker",
        )
        self.report["status"] = "PASS"

    def cleanup(self) -> None:
        if self.workspace is None:
            return
        self.workspace.assert_owned()
        if self.started:
            self.compose(["down", "--volumes", "--timeout", "30"], 120)
            require(
                not any(self.resources().values()), "owned project resources remain after cleanup"
            )
            self.report["cleanup"] = "owned_project_removed"
            acceptance = self.report.get("acceptance", {})
            if "fixture" in acceptance:
                acceptance["fixture"].update(cleanup="owned_project_removed", retained=False)
        shutil.rmtree(self.workspace.state)

    def run(self) -> dict[str, Any]:
        try:
            self.preflight()
            self.prepare()
            self.start()
            self.inspect_runtime()
            self.acceptance()
        except (SmokeFailure, OSError, ValueError, KeyError, TypeError) as exc:
            self.report.update(status="FAIL", failed_phase=self.phase, failure=safe_failure(exc))
            self.failure_logs()
        except KeyboardInterrupt:
            self.report.update(
                status="FAIL", failed_phase=self.phase, failure="qualification interrupted"
            )
        finally:
            try:
                self.cleanup()
            except (SmokeFailure, OSError) as exc:
                self.report.update(
                    status="FAIL", cleanup="incomplete", cleanup_failure=safe_failure(exc)
                )
                if self.workspace is not None:
                    self.report["private_state_retained"] = str(self.workspace.state)
        return self.report

    def failure_logs(self) -> None:
        if not self.started:
            return
        for name, arguments in (
            ("service_states_at_failure", ["ps", "--all", "--format", "json"]),
            ("sanitized_service_diagnostics", ["logs", "--no-color", "--tail", "25"]),
        ):
            try:
                output = self.compose(arguments, 20)
                self.report[name] = (
                    parse_services(output)
                    if arguments[0] == "ps"
                    else sanitize(output, self.secrets)[-6000:]
                )
            except (SmokeFailure, OSError, ValueError, KeyError, TypeError):
                self.report[name] = "unavailable"


def safe_failure(error: Exception) -> str:
    return str(error) if isinstance(error, SmokeFailure) else type(error).__name__


def interrupted(_signal: int, _frame: object) -> None:
    raise KeyboardInterrupt


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--startup-timeout", type=int, default=600)
    parser.add_argument("--readers", type=int, choices=(3, 4, 5), default=5)
    parser.add_argument("--out", type=Path, default=Path("var/compose-pilot-smoke.json"))
    args = parser.parse_args(argv)
    signal.signal(signal.SIGTERM, interrupted)
    smoke = ComposeSmoke(ROOT, args.startup_timeout, args.readers)
    report = smoke.run()
    rendered = sanitize(json.dumps(report, ensure_ascii=False, indent=2), smoke.secrets) + "\n"
    try:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(rendered, encoding="utf-8")
    except OSError:
        print('{"status":"FAIL","failure":"sanitized report could not be saved"}')
        return 1
    print(rendered, end="")
    return 0 if report["status"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
