from scripts.openapi_contract import DEFAULT, canonical_contract


def test_openapi_contract_has_no_unreviewed_drift():
    assert DEFAULT.read_text(encoding="utf-8") == canonical_contract()
