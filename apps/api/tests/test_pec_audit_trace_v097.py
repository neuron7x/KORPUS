from __future__ import annotations
import pytest
from korpus.application.pec_revision_binding import RevisionBinding
from korpus.application.pec_audit_trace import extract_audit_trace

B=RevisionBinding("v0.9.7","rev-7","prod-v1","CANARY","PRODUCTION","a"*64)

def rows(): return [{"sequence":2,"event_id":"e2","action":"judge","revision":"rev-7","profile":"prod-v1","phase":"CANARY","environment_class":"PRODUCTION"},{"sequence":1,"event_id":"e1","action":"retrieve","revision":"rev-7","profile":"prod-v1","phase":"CANARY","environment_class":"PRODUCTION"}]

def test_audit_trace_is_deterministic_under_input_order():
    a=extract_audit_trace(rows(),B); b=extract_audit_trace(list(reversed(rows())),B)
    assert a==b and a.event_ids==("e1","e2")

def test_audit_trace_rejects_revision_drift():
    data=rows(); data[0]["revision"]="other"
    with pytest.raises(ValueError, match="revision binding mismatch"): extract_audit_trace(data,B)

def test_audit_trace_rejects_profile_phase_drift():
    data=rows(); data[0]["phase"]="SHADOW"
    with pytest.raises(ValueError, match="profile/phase"): extract_audit_trace(data,B)

def test_audit_trace_rejects_duplicate_event_ids():
    data=rows(); data[0]["event_id"]="e1"
    with pytest.raises(ValueError, match="unique"): extract_audit_trace(data,B)
