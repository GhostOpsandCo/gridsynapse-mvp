from __future__ import annotations

import app.main as main_module
import pytest
from app.main import app
from app.repository import InMemoryOptimizationRepository
from fastapi.testclient import TestClient

client = TestClient(app)


@pytest.fixture(autouse=True)
def isolated_repository(monkeypatch):
    monkeypatch.setattr(main_module, "repository", InMemoryOptimizationRepository())
    monkeypatch.setattr(main_module, "WRITE_AUTH_REQUIRED", False)
    main_module._write_request_times.clear()


def _scenario():
    response = client.get("/api/v2/scenarios/reference-cost-carbon-tradeoff-v1")
    assert response.status_code == 200
    return response.json()


def _optimization():
    response = client.post("/api/v2/optimizations", json=_scenario())
    assert response.status_code == 200
    return response.json()


def test_health_and_scenario_listing():
    health = client.get("/health").json()
    assert health["status"] == "healthy"
    assert health["persistence"]["backend"] == "memory"
    assert health["persistence"]["durable"] is False
    scenarios = client.get("/api/v2/scenarios").json()
    assert scenarios[0]["scenarioId"] == "reference-cost-carbon-tradeoff-v1"
    assert scenarios[0]["workloadCount"] == 3


def test_scenario_validation_and_data_health():
    scenario = _scenario()
    validation = client.post("/api/v2/scenarios/validate", json=scenario)
    assert validation.status_code == 200
    assert validation.json()["valid"] is True
    health = client.get("/api/v2/scenarios/reference-cost-carbon-tradeoff-v1/data-health").json()
    assert health["sourceCount"] == 3
    assert all(source["sourceType"] == "synthetic" for source in health["sources"])


def test_optimize_explain_approve_and_export():
    result = _optimization()
    assert result["status"] == "feasible"
    assert result["validation"]["valid"] is True
    recommendation_id = result["recommendationId"]

    explanation = client.get(f"/api/v2/optimizations/{recommendation_id}/explanation")
    assert explanation.status_code == 200
    assert explanation.json()["generatedBy"] == "deterministic-template"
    assert "constraint" in explanation.json()["summary"]

    approval = client.post(
        f"/api/v2/optimizations/{recommendation_id}/approval",
        json={"status": "approved", "actor": "portfolio-reviewer"},
    )
    assert approval.status_code == 200
    assert approval.json()["approval"]["status"] == "approved"
    assert approval.json()["approval"]["approvedBy"] == "portfolio-reviewer"

    csv_export = client.get(f"/api/v2/optimizations/{recommendation_id}/export?format=csv")
    assert csv_export.status_code == 200
    assert csv_export.headers["content-type"].startswith("text/csv")
    assert "baseline" in csv_export.text and "optimized" in csv_export.text


def test_approval_survives_repeated_optimization_and_history_is_recorded():
    scenario = _scenario()
    first = client.post("/api/v2/optimizations", json=scenario).json()
    recommendation_id = first["recommendationId"]

    approved = client.post(
        f"/api/v2/optimizations/{recommendation_id}/approval",
        json={"status": "approved", "actor": "portfolio-reviewer"},
    )
    assert approved.status_code == 200

    repeated = client.post("/api/v2/optimizations", json=scenario)
    assert repeated.status_code == 200
    assert repeated.json()["approval"]["status"] == "approved"
    assert repeated.json()["approval"]["approvedBy"] == "portfolio-reviewer"

    history = client.get("/api/v2/decision-history?limit=5")
    assert history.status_code == 200
    assert history.json()[0]["recommendationId"] == recommendation_id
    assert history.json()[0]["approvalStatus"] == "approved"


def test_missing_recommendation_returns_404():
    assert client.get("/api/v2/optimizations/not-found").status_code == 404


def test_invalid_payload_returns_actionable_422():
    response = client.post("/api/v2/optimizations", json={"schemaVersion": "wrong"})
    assert response.status_code == 422
    assert response.json()["detail"]


def test_live_market_endpoint_uses_adapter_snapshot(monkeypatch):
    expected = {
        "scenario": {"scenarioId": "live-test"},
        "health": {"status": "healthy"},
        "generatedAt": "2026-07-18T04:00:00Z",
        "marketMode": "hybrid-live",
        "warnings": [],
        "sources": {},
    }
    monkeypatch.setattr(main_module.live_market_service, "snapshot", lambda force=False: expected)

    response = client.get("/api/v2/live-market/scenario?refresh=true")

    assert response.status_code == 200
    assert response.json() == expected


def test_production_write_routes_require_server_key(monkeypatch):
    monkeypatch.setattr(main_module, "WRITE_AUTH_REQUIRED", True)
    monkeypatch.setattr(main_module, "API_WRITE_KEY", "server-only-key")

    unauthorized = client.post("/api/v2/scenarios/validate", json=_scenario())
    authorized = client.post(
        "/api/v2/scenarios/validate",
        json=_scenario(),
        headers={"x-gridsynapse-api-key": "server-only-key"},
    )

    assert unauthorized.status_code == 401
    assert authorized.status_code == 200


def test_write_rate_limit_returns_429(monkeypatch):
    monkeypatch.setattr(main_module, "WRITE_RATE_LIMIT_PER_MINUTE", 1)
    scenario = _scenario()
    first = client.post("/api/v2/scenarios/validate", json=scenario)
    second = client.post("/api/v2/scenarios/validate", json=scenario)

    assert first.status_code == 200
    assert second.status_code == 429
    assert second.headers["retry-after"] == "60"
