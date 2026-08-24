from __future__ import annotations
from korpus.application.pec_external_assurance import validate_external_assurance

S="a"*64
def receipt(): return {"independent":True,"release":"v0.9.7","source_digest":S,"signer_fingerprint":"trusted","blocking_findings_closed":True}

def test_external_assurance_accepts_trusted_independent_receipt():
    assert validate_external_assurance(receipt(),release="v0.9.7",source_digest=S,trusted_signers={"trusted"}).admissible

def test_external_assurance_rejects_self_assessment():
    r=receipt(); r["independent"]=False
    v=validate_external_assurance(r,release="v0.9.7",source_digest=S,trusted_signers={"trusted"})
    assert not v.admissible and "independent" in v.failures

def test_external_assurance_rejects_untrusted_signer():
    v=validate_external_assurance(receipt(),release="v0.9.7",source_digest=S,trusted_signers={"other"})
    assert not v.admissible and "trusted_signer" in v.failures

def test_external_assurance_rejects_open_blocking_findings():
    r=receipt(); r["blocking_findings_closed"]=False
    v=validate_external_assurance(r,release="v0.9.7",source_digest=S,trusted_signers={"trusted"})
    assert not v.admissible and "blocking_findings_closed" in v.failures
