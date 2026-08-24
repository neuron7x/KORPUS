from __future__ import annotations
import pytest
from korpus.application.pec_revision_binding import RevisionBinding

D="a"*64

def payload(): return {"release":"v0.9.7","revision":"api-00042-x","profile":"prod-v1","phase":"CANARY","environment_class":"PRODUCTION","training_receipt_sha256":D}

def test_revision_binding_accepts_exact_production_identity():
    binding=RevisionBinding.from_mapping(payload(), expected_release="v0.9.7")
    assert binding.revision=="api-00042-x" and binding.environment_class=="PRODUCTION"

def test_revision_binding_rejects_release_drift():
    row=payload(); row["release"]="v0.9.6"
    with pytest.raises(ValueError, match="release binding mismatch"): RevisionBinding.from_mapping(row, expected_release="v0.9.7")

def test_revision_binding_rejects_nonproduction_environment():
    row=payload(); row["environment_class"]="PRODUCTION_LIKE"
    with pytest.raises(ValueError, match="environment_class=PRODUCTION"): RevisionBinding.from_mapping(row, expected_release="v0.9.7")

def test_revision_binding_rejects_unbound_training_receipt():
    row=payload(); row["training_receipt_sha256"]="bad"
    with pytest.raises(ValueError, match="lowercase sha256"): RevisionBinding.from_mapping(row, expected_release="v0.9.7")
