"""CycloneDX completeness and GitHub CI subject-chain validation."""

from __future__ import annotations

from collections.abc import Collection, Mapping
from dataclasses import dataclass
from typing import Any

from korpus.application.github_assurance_receipts import (
    admitted_file,
    canonical_identity,
    receipt_bound,
    same_identity,
    sha256_bytes,
)

SUPPORTED_CYCLONEDX = frozenset({"1.5", "1.6"})
COMPONENT_TYPES = frozenset(
    {
        "application",
        "container",
        "cryptographic-asset",
        "data",
        "device",
        "device-driver",
        "file",
        "firmware",
        "framework",
        "library",
        "machine-learning-model",
        "operating-system",
        "platform",
    }
)


@dataclass(frozen=True)
class SbomCiEvidence:
    source_sbom: Mapping[str, Any]
    api_sbom: Mapping[str, Any]
    web_sbom: Mapping[str, Any]
    api_locked: Mapping[str, str]
    source_receipt: Mapping[str, Any]
    source_receipt_bytes: bytes
    container_receipt: Mapping[str, Any]
    container_receipt_bytes: bytes
    admission: Mapping[str, Any]
    source_tree_sha256: str


def sbom_bundle_bound(bundle: SbomCiEvidence, artifacts: Mapping[str, bytes]) -> bool:
    return sbom_ci_receipts_bound(
        bundle,
        source_sbom=artifacts.get("var/ci-evidence/source-sbom.cdx.json", b""),
        api_sbom=artifacts.get("var/ci-evidence/api-sbom.cdx.json", b""),
        web_sbom=artifacts.get("var/ci-evidence/web-sbom.cdx.json", b""),
    )


def valid_cyclonedx(data: Mapping[str, Any]) -> bool:
    components = data.get("components")
    return (
        data.get("bomFormat") == "CycloneDX"
        and data.get("specVersion") in SUPPORTED_CYCLONEDX
        and isinstance(data.get("version"), int)
        and not isinstance(data.get("version"), bool)
        and data["version"] > 0
        and isinstance(components, list)
        and bool(components)
        and all(_valid_component(item) for item in components)
    )


def _valid_component(item: Any) -> bool:
    return (
        isinstance(item, Mapping)
        and item.get("type") in COMPONENT_TYPES
        and isinstance(item.get("name"), str)
        and bool(item["name"].strip())
        and isinstance(item.get("version"), str)
        and bool(item["version"].strip())
    )


def sbom_has_components(data: Mapping[str, Any], expected: Collection[str]) -> bool:
    if not valid_cyclonedx(data) or not expected:
        return False
    names = {
        str(item["name"]).lower().replace("_", "-")
        for item in data["components"]
        if isinstance(item, Mapping)
    }
    return all(name.lower().replace("_", "-") in names for name in expected)


def source_sbom_covers_lock(data: Mapping[str, Any], locked: Mapping[str, str]) -> bool:
    if not valid_cyclonedx(data) or not locked:
        return False
    components = {
        (str(item.get("name", "")).lower().replace("_", "-"), str(item.get("version", "")))
        for item in data.get("components", ())
        if isinstance(item, Mapping)
    }
    return all((name, version) in components for name, version in locked.items())


def sbom_ci_receipts_bound(
    bundle: SbomCiEvidence,
    *,
    source_sbom: bytes,
    api_sbom: bytes,
    web_sbom: bytes,
) -> bool:
    identity = bundle.admission
    sboms = {
        "source-sbom.cdx.json": source_sbom,
        "api-sbom.cdx.json": api_sbom,
        "web-sbom.cdx.json": web_sbom,
    }
    source_subjects = bundle.source_receipt.get("subjects")
    source_subject = (
        source_subjects.get("source-tree") if isinstance(source_subjects, Mapping) else None
    )
    return (
        canonical_identity(identity)
        and same_identity(bundle.source_receipt, identity)
        and same_identity(bundle.container_receipt, identity)
        and receipt_bound(
            bundle.source_receipt,
            identity=identity,
            kind="source-sbom",
            job="source-sbom",
            source_tree_sha256=bundle.source_tree_sha256,
            artifacts={"source-sbom.cdx.json": source_sbom},
        )
        and receipt_bound(
            bundle.container_receipt,
            identity=identity,
            kind="container-sboms",
            job="container-sbom",
            source_tree_sha256=bundle.source_tree_sha256,
            artifacts={
                "api-sbom.cdx.json": api_sbom,
                "web-sbom.cdx.json": web_sbom,
            },
        )
        and isinstance(source_subject, Mapping)
        and source_subject.get("digest_scope") == "tracked_tree"
        and source_subject.get("sha256") == bundle.source_tree_sha256
        and source_subject.get("sbom") == "source-sbom.cdx.json"
        and source_subject.get("sbom_sha256") == sha256_bytes(source_sbom)
        and _container_subjects_bound(bundle.container_receipt.get("subjects"), sboms)
        and _receipts_admitted(bundle, sboms)
    )


def _receipts_admitted(bundle: SbomCiEvidence, sboms: Mapping[str, bytes]) -> bool:
    payloads = (
        ("source-sbom", "source-sbom.cdx.json", sboms["source-sbom.cdx.json"]),
        ("source-sbom", "source-sbom-receipt.json", bundle.source_receipt_bytes),
        ("container-sboms", "api-sbom.cdx.json", sboms["api-sbom.cdx.json"]),
        ("container-sboms", "web-sbom.cdx.json", sboms["web-sbom.cdx.json"]),
        ("container-sboms", "container-sbom-receipt.json", bundle.container_receipt_bytes),
    )
    return all(
        admitted_file(
            bundle.admission,
            identity=bundle.admission,
            artifact=artifact,
            name=name,
            payload=payload,
        )
        for artifact, name, payload in payloads
    )


def _container_subjects_bound(subjects: Any, sboms: Mapping[str, bytes]) -> bool:
    if not isinstance(subjects, Mapping) or set(subjects) != {"api-image.tar", "web-image.tar"}:
        return False
    pairs = (("api-image.tar", "api-sbom.cdx.json"), ("web-image.tar", "web-sbom.cdx.json"))
    for image, sbom in pairs:
        subject = subjects.get(image)
        if (
            not isinstance(subject, Mapping)
            or not _sha256(subject.get("sha256"))
            or subject.get("sbom") != sbom
            or subject.get("sbom_sha256") != sha256_bytes(sboms[sbom])
        ):
            return False
    return True


def _sha256(value: Any) -> bool:
    return (
        isinstance(value, str)
        and len(value) == 64
        and all(character in "0123456789abcdef" for character in value)
    )
