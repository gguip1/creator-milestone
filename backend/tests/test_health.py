from fastapi.testclient import TestClient

from app.main import app


def test_health_reports_no_secrets():
    response = TestClient(app).get("/api/health")
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "ok"
    assert body["paypal"]["environment"] == "SANDBOX"
    assert "secret" not in response.text.lower()
