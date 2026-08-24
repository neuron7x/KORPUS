from __future__ import annotations
from korpus.application.pec_revision_binding import RevisionBinding
from korpus.application.pec_canary_admission import evaluate_canary

B=RevisionBinding("v0.9.7","rev-7","prod-v1","CANARY","PRODUCTION","a"*64)
def receipt(): return {"release":"v0.9.7","cloud_run_revision":"api-00042-x","environment_class":"PRODUCTION","samples":200,"server_error_rate":0.0,"human_judgment_admissible":True}

def test_canary_accepts_exact_revision_and_policy():
    assert evaluate_canary(receipt(),binding=B,cloud_run_revision="api-00042-x",minimum_samples=100,maximum_server_error_rate=0.01).admitted

def test_canary_rejects_revision_mismatch():
    r=receipt(); r["cloud_run_revision"]="api-old"
    v=evaluate_canary(r,binding=B,cloud_run_revision="api-00042-x",minimum_samples=100,maximum_server_error_rate=0.01)
    assert not v.admitted and "cloud_run_revision_mismatch" in v.failures

def test_canary_rejects_underpowered_sample():
    r=receipt(); r["samples"]=99
    v=evaluate_canary(r,binding=B,cloud_run_revision="api-00042-x",minimum_samples=100,maximum_server_error_rate=0.01)
    assert not v.admitted and "insufficient_samples" in v.failures

def test_canary_requires_admissible_human_judgment():
    r=receipt(); r["human_judgment_admissible"]=False
    v=evaluate_canary(r,binding=B,cloud_run_revision="api-00042-x",minimum_samples=100,maximum_server_error_rate=0.01)
    assert not v.admitted and "human_judgment_not_admissible" in v.failures
