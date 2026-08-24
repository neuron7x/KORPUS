from __future__ import annotations
import pytest
from korpus.application.pec_evidence_receipt import canonical_receipt

S="a"*64; C="b"*64

def payload(): return {"release":"v0.9.7","source_digest":S,"collection_digest":C,"artifacts":{"z":"d"*64,"a":"c"*64}}

def test_evidence_receipt_is_deterministic_and_sorted():
    a=canonical_receipt(payload(),release="v0.9.7",source_digest=S,collection_digest=C)
    b=canonical_receipt(payload(),release="v0.9.7",source_digest=S,collection_digest=C)
    assert a==b and list(a["artifacts"])==["a","z"]

def test_evidence_receipt_rejects_release_drift():
    r=payload(); r["release"]="v0.9.6"
    with pytest.raises(ValueError, match="release mismatch"): canonical_receipt(r,release="v0.9.7",source_digest=S,collection_digest=C)

def test_evidence_receipt_rejects_source_drift():
    r=payload(); r["source_digest"]="e"*64
    with pytest.raises(ValueError, match="source digest mismatch"): canonical_receipt(r,release="v0.9.7",source_digest=S,collection_digest=C)

def test_evidence_receipt_rejects_malformed_artifact_digest():
    r=payload(); r["artifacts"]={"x":"bad"}
    with pytest.raises(ValueError, match="artifact digests"): canonical_receipt(r,release="v0.9.7",source_digest=S,collection_digest=C)
