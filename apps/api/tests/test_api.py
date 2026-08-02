from fastapi.testclient import TestClient

from korpus.main import app

client = TestClient(app)


def test_health() -> None:
    assert client.get("/health").json() == {"status": "ok"}


def test_answer_contract_abstains_by_default() -> None:
    response = client.post("/v1/answers", json={"text": "Що каже перевірена база?"})
    assert response.status_code == 200
    assert response.json()["status"] == "insufficient_evidence"

