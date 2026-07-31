from pathlib import Path

import pytest

from korpus.domain.models import AccessTier, DocumentRecord, Identity
from korpus.infrastructure.extraction import extract_pages
from korpus.infrastructure.object_store import LocalObjectStore


def test_json_and_html_extraction():
    json_pages, json_method = extract_pages(b'{"alpha": "beta"}', "x.json", "application/json", False, "eng")
    html_pages, html_method = extract_pages(b'<html><script>bad()</script><p>Allowed text</p></html>', "x.html", "text/html", False, "eng")
    assert json_method == "plain_text" and '"alpha"' in json_pages[0].text
    assert html_method == "plain_text" and "Allowed text" in html_pages[0].text
    assert "bad()" not in html_pages[0].text


def test_object_store_is_content_addressed_and_blocks_escape(tmp_path: Path):
    store = LocalObjectStore(tmp_path)
    key = store.put(b"payload", "a" * 64, "../unsafe.txt")
    assert store.get(key) == b"payload"
    with pytest.raises(ValueError, match="escapes"):
        store.get("../../etc/passwd")


def test_access_tier_parse_and_document_decision(public_identity: Identity):
    assert AccessTier.parse("restricted") is AccessTier.RESTRICTED
    document = DocumentRecord(
        canonical_title="Restricted document",
        corpus_id="public",
        issuer="Issuer",
        jurisdiction="UA",
        document_type="order",
        access_tier=AccessTier.RESTRICTED,
        classification="restricted",
    )
    from korpus.application.policy import PolicyEngine
    decision = PolicyEngine().can_access_document(public_identity, document)
    assert decision.allowed is False
