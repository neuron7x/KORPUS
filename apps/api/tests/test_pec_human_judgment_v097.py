from __future__ import annotations
from korpus.application.pec_revision_binding import RevisionBinding
from korpus.application.pec_human_judgment import evaluate_human_judgments

B=RevisionBinding("v0.9.7","rev-7","prod-v1","CANARY","PRODUCTION","a"*64)
def row(case="a"): return {"case_id":case,"actor_type":"HUMAN","model_self_judgment":False,"revision":"rev-7","profile":"prod-v1","phase":"CANARY","judgment_provenance_sha256":"b"*64}

def test_human_judgment_accepts_exact_complete_cohort():
    v=evaluate_human_judgments([row("a"),row("b")], expected_case_ids=["a","b"], binding=B)
    assert v.admissible and v.judgments==2

def test_model_self_judgment_is_never_authoritative():
    r=row(); r["model_self_judgment"]=True
    v=evaluate_human_judgments([r], expected_case_ids=["a"], binding=B)
    assert not v.admissible and "model_self_judgment:a" in v.failures

def test_nonhuman_actor_is_rejected_even_if_model_flag_is_false():
    r=row(); r["actor_type"]="MODEL"
    v=evaluate_human_judgments([r], expected_case_ids=["a"], binding=B)
    assert not v.admissible and "non_human_judgment:a" in v.failures

def test_human_judgment_rejects_revision_drift():
    r=row(); r["revision"]="old"
    v=evaluate_human_judgments([r], expected_case_ids=["a"], binding=B)
    assert not v.admissible and "revision_mismatch:a" in v.failures
