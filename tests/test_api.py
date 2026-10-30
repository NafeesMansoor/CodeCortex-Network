from fastapi.testclient import TestClient

from ccn.main import app, state


def test_health_and_initial_status() -> None:
    state["last_run"] = None
    with TestClient(app) as client:
        assert client.get("/health").json() == {"status": "ok"}
        status = client.get("/status").json()
        assert status["status"] == "ok"
        assert status["repositories"] == 0


def test_latest_run_not_found_before_scout() -> None:
    state["last_run"] = None
    with TestClient(app) as client:
        assert client.get("/scout/latest").status_code == 404

