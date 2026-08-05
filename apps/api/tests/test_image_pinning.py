"""A tag is a name the registry may repoint; a digest is the bytes.

SUP-001 in the frozen audit: "Container/CI images pinned tags, not immutable digests".
The concrete cost showed up on 2026-08-05, when a kaniko version that does not exist
was pinned and reached a queued pipeline before anything noticed. A digest cannot be
invented — the registry either has those bytes or it does not — and cannot be silently
repointed at different ones later, which is the failure a tag permits and nothing here
could have detected.

Both halves are tested: a digest-pinned image passes, and a tag-only image is refused.
Every service in the compose file passing today is not evidence that the check works.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from korpus.application.requirements import evaluate_requirements
from korpus.infrastructure_requirements import (
    DIGEST_PINNED,
    EXACT_TAG,
    INFRASTRUCTURE_REQUIREMENTS,
    InfrastructureContext,
)

ROOT = Path(__file__).resolve().parents[3]
DIGEST = "sha256:" + "a" * 64


def _context(image: str) -> InfrastructureContext:
    context = InfrastructureContext(root=ROOT)
    context.compose = {"services": {"api": {"image": image}}}
    return context


def _api_digest_requirement():
    return next(
        requirement
        for requirement in INFRASTRUCTURE_REQUIREMENTS
        if requirement.id == "compose.api.digest_pinned"
    )


def test_a_digest_pinned_image_is_accepted() -> None:
    """The dual: a rule that refuses everything pins nothing."""
    context = _context(f"pgvector/pgvector:0.8.5-pg17-trixie@{DIGEST}")

    assert _api_digest_requirement().evaluate(context) is True


def test_a_tag_without_a_digest_is_refused() -> None:
    """The state the whole tree was in until SUP-001 was closed."""
    context = _context("pgvector/pgvector:0.8.5-pg17-trixie")

    assert _api_digest_requirement().evaluate(context) is False


@pytest.mark.parametrize(
    "image",
    [
        "pgvector/pgvector:0.8.5@sha256:short",
        "pgvector/pgvector:0.8.5@md5:" + "a" * 32,
        "pgvector/pgvector:0.8.5@sha256:" + "A" * 64,
    ],
)
def test_a_malformed_digest_is_not_a_digest(image: str) -> None:
    """Uppercase hex, a truncated digest and a non-sha256 algorithm all read as pinned
    to a regex that only looks for the `@` — which is how a pin becomes decorative."""
    assert not DIGEST_PINNED.search(image)


def test_the_tag_survives_beside_the_digest() -> None:
    """A diff saying only that 64 hex characters changed tells a reviewer nothing.

    The tag is kept for humans and the digest is what gets pulled; the exact-tag rule
    has to accept both forms or pinning by digest would fail the older requirement.
    """
    assert EXACT_TAG.fullmatch(f"pgvector/pgvector:0.8.5-pg17-trixie@{DIGEST}")
    assert EXACT_TAG.fullmatch("pgvector/pgvector:0.8.5-pg17-trixie")
    assert not EXACT_TAG.fullmatch(f"pgvector/pgvector@{DIGEST}")


def test_every_compose_service_is_digest_pinned_today() -> None:
    """The shipped state, asserted separately from whether the rule can fail."""
    from korpus.infrastructure_requirements import load_context

    report = evaluate_requirements(
        [r for r in INFRASTRUCTURE_REQUIREMENTS if r.id.endswith(".digest_pinned")],
        load_context(ROOT),
    )

    assert report.satisfied, [failure.id for failure in report.unmet]
    assert report.total >= 9
