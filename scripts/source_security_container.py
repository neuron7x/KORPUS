"""Bind scanner cleanup to an owned container, including client-timeout paths."""

from __future__ import annotations

import re
import stat
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from uuid import uuid4

from scripts.source_security_contract import IMAGES, require

OWNER_LABEL = "io.korpus.source-security.owner"


@dataclass(frozen=True)
class OwnedContainer:
    cli: tuple[str, ...]
    name: str
    owner: str
    cidfile: Path


def owned_command(tool: str, command: list[str]) -> tuple[list[str], OwnedContainer | None]:
    if tool not in IMAGES:
        return command, None
    require(
        command[:2] == ["/usr/bin/docker", "--config"]
        and len(command) > 4
        and command[3] == "run"
        and IMAGES[tool] in command,
        "scanner container command is not fixed",
    )
    require(
        not any(flag in command for flag in ("--name", "--label", "--cidfile")),
        "caller supplied scanner ownership",
    )
    owner = uuid4().hex
    name = "korpus-source-security-" + owner
    cidfile = Path(command[2]).parent / (name + ".cid")
    require(cidfile.is_absolute() and not cidfile.exists(), "invalid scanner cidfile")
    owned = OwnedContainer(tuple(command[:3]), name, owner, cidfile)
    flags = ["--name", name, "--label", OWNER_LABEL + "=" + owner, "--cidfile", str(cidfile)]
    return [*command[:4], *flags, *command[4:]], owned


def _invoke(
    owned: OwnedContainer, arguments: list[str], environment: dict[str, str]
) -> subprocess.CompletedProcess[bytes]:
    return subprocess.run(
        [*owned.cli, "container", *arguments],
        env=environment,
        capture_output=True,
        timeout=10,
        check=False,
    )


def _cidfile(owned: OwnedContainer) -> str | None:
    try:
        info = owned.cidfile.lstat()
    except FileNotFoundError:
        return None
    require(stat.S_ISREG(info.st_mode) and info.st_size <= 65, "unsafe scanner cidfile")
    value = owned.cidfile.read_text().strip()
    if info.st_size == 0 and not value:
        return None
    require(re.fullmatch(r"[a-f0-9]{64}", value) is not None, "invalid scanner container ID")
    return value


def _ids(owned: OwnedContainer, selector: str, environment: dict[str, str]) -> list[str]:
    result = _invoke(
        owned, ["ls", "--all", "--quiet", "--no-trunc", "--filter", selector], environment
    )
    require(result.returncode == 0, "container absence query failed")
    values = result.stdout.decode("ascii").split()
    require(
        len(values) <= 1 and all(re.fullmatch(r"[a-f0-9]{64}", value) for value in values),
        "ambiguous scanner container query",
    )
    return values


def _remove_owned(owned: OwnedContainer, cid: str, environment: dict[str, str]) -> int:
    template = '{{.Id}} {{index .Config.Labels "' + OWNER_LABEL + '"}}'
    inspected = _invoke(owned, ["inspect", "--format", template, cid], environment)
    require(
        inspected.returncode == 0 and inspected.stdout.decode().strip() == cid + " " + owned.owner,
        "scanner container ownership mismatch",
    )
    removed = _invoke(owned, ["rm", "--force", cid], environment)
    require(not _ids(owned, "id=" + cid, environment), "scanner container survived cleanup")
    return removed.returncode


def cleanup(owned: OwnedContainer, environment: dict[str, str]) -> dict[str, Any]:
    record: dict[str, Any] = {
        "name": owned.name,
        "owner": owned.owner,
        "container_id": None,
        "status": "UNPROVEN",
        "confirmed_absent": False,
        "remove_exit_code": None,
    }
    try:
        cid = _cidfile(owned)
        selector = "id=" + cid if cid else "name=^/" + owned.name + "$"
        found = _ids(owned, selector, environment)
        require(bool(cid or found), "container creation outcome is unproven")
        if found:
            require(cid is None or found == [cid], "scanner container ID mismatch")
            cid = found[0]
            record["remove_exit_code"] = _remove_owned(owned, cid, environment)
        record.update(container_id=cid, status="ABSENT", confirmed_absent=True)
    except (OSError, UnicodeError, ValueError, subprocess.SubprocessError) as error:
        record["error"] = f"{type(error).__name__}: {error}"
    return record


def cleanup_valid(execution: dict[str, Any]) -> bool:
    if execution.get("tool") not in IMAGES:
        return True
    record, command = execution.get("cleanup"), execution.get("command")
    if not isinstance(record, dict) or not isinstance(command, list):
        return False
    owner = record.get("owner")
    if not isinstance(owner, str) or re.fullmatch(r"[a-f0-9]{32}", owner) is None:
        return False
    expected = {"--name": "korpus-source-security-" + owner, "--label": OWNER_LABEL + "=" + owner}
    return (
        record.get("status") == "ABSENT"
        and record.get("confirmed_absent") is True
        and isinstance(record.get("container_id"), str)
        and re.fullmatch(r"[a-f0-9]{64}", record["container_id"]) is not None
        and record.get("name") == expected["--name"]
        and all(
            command.count(flag) == 1
            and command.index(flag) + 1 < len(command)
            and command[command.index(flag) + 1] == value
            for flag, value in expected.items()
        )
    )
