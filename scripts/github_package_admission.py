"""Bind the fixed package artifact census to immutable captured release identity bytes."""

from __future__ import annotations

import re
from dataclasses import replace

from github_evidence_run import PACKAGE, Producer
from github_evidence_source import Checkout
from github_evidence_transport import insist, strict_object
from package_identity_contract import valid_release_identity


def package_producer(checkout: Checkout) -> Producer:
    records = [
        content
        for path, _mode, content in checkout.files
        if path.as_posix() == "apps/api/src/korpus/release.json"
    ]
    insist(len(records) == 1, "captured source lacks one canonical release identity")
    release = strict_object(records[0], "captured release identity")
    insist(valid_release_identity(release), "captured release identity is inconsistent")
    name = release["distribution_artifact"]
    insist(
        re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]*\.zip", name) is not None,
        "release distribution name is not a single safe ZIP filename",
    )
    members = ("dist/" + name, "dist/" + name + ".sha256", *PACKAGE.required_members)
    return replace(PACKAGE, required_members=members)
