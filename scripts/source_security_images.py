"""Provision pinned images separately from the bounded offline scanner commands."""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
from typing import Any

from scripts.source_security_contract import IMAGES, require


def provision_images(
    temporary: Path,
    output: Path,
    source: Path,
    receipt: dict[str, Any],
    execute: Callable[[str, list[str], Path, Path], dict[str, Any]],
) -> None:
    """Retain every pull's own outcome before allowing native scanner execution."""
    config = temporary / "docker-config"
    config.mkdir()
    receipt["provisioning"] = [
        execute(
            f"image:{tool}",
            [
                "/usr/bin/docker",
                "--config",
                str(config),
                "pull",
                "--platform",
                "linux/amd64",
                image,
            ],
            output,
            source,
        )
        for tool, image in IMAGES.items()
    ]
    require(
        all(
            type(item["exit_code"]) is int and item["exit_code"] == 0
            for item in receipt["provisioning"]
        ),
        "image provisioning did not succeed",
    )
