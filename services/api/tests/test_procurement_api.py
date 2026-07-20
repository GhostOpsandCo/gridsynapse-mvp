from __future__ import annotations

import app.main as main_module
import pytest
from app.main import app
from app.repository import InMemoryOptimizationRepository
from fastapi.testclient import TestClient
from gridsynapse_procurement import ProcurementService

client = TestClient(app)


@pytest.fixture(autouse=True)
def isolated_services(monkeypatch):
    monkeypatch.setattr(main_module, "repository", InMemoryOptimizationRepository())
    monkeypatch.setattr(
        main_module,
        "procurement_service",
        ProcurementService(procurement_enabled=True, execution_enabled=False),
    )


def _scenario():
    response = client.get("/api/v2/scenarios/reference-cost-carbon-tradeoff-v1")
    assert response.status_code == 200
    return response.json()


def _approved_optimization():
    result = client.post("/api/v2/optimizations", json=_scenario()).json()
    recommendation_id = result["recommendationId"]
    approved = client.post(
        f"/api/v2/optimizations/{recommendation_id}/approval",
        json={"status": "approved", "actor": "portfolio-reviewer"},
    )
    assert approved.status_code == 200
    return approved.json()


def _create_payload(result):
    scenario = _scenario()
    return {
        "recommendationId": result["recommendationId"],
        "expectedInputHash": result["inputHash"],
        "requestedBy": "portfolio-operator",
        "maxSpendUsd": 1000,
        "workloadSpecs": [
            {
                "workloadId": workload["id"],
                "containerImage": f"ghcr.io/gridsynapse/{workload['id']}:portfolio",
                "command": ["python", "run.py", "--workload", workload["id"]],
                "secretRefs": ["portfolio/provider-token"],
            }
            for workload in scenario["workloads"]
        ],
    }


def test_procurement_api_create_get_verify_and_simulate_lifecycle():
    result = _approved_optimization()
    created = client.post("/api/v2/procurement/plans", json=_create_payload(result))
    assert created.status_code == 200
    plan = created.json()
    plan_id = plan["procurementPlanId"]
    assert plan["status"] == "created"
    assert plan["simulationOnly"] is True
    assert plan["liveExecutionPermitted"] is False
    assert "portfolio dry-run manifest" in plan["skypilotManifestYaml"]

    fetched = client.get(f"/api/v2/procurement/plans/{plan_id}")
    assert fetched.status_code == 200
    assert fetched.json()["idempotencyKey"] == plan["idempotencyKey"]

    verified = client.post(f"/api/v2/procurement/plans/{plan_id}/verify")
    assert verified.status_code == 200
    assert verified.json()["status"] == "dry_run_ready"
    assert verified.json()["verification"]["liveLaunchAllowed"] is False

    rejected_live = client.post(
        f"/api/v2/procurement/plans/{plan_id}/transitions",
        json={
            "action": "approve_for_launch",
            "actor": "portfolio-reviewer",
            "simulation": False,
        },
    )
    assert rejected_live.status_code == 409
    assert "simulated transitions only" in rejected_live.json()["detail"]

    actions = [
        "approve_for_launch",
        "start_provisioning",
        "mark_running",
        "mark_completed",
        "reconcile",
    ]
    for action in actions:
        response = client.post(
            f"/api/v2/procurement/plans/{plan_id}/transitions",
            json={
                "action": action,
                "actor": "portfolio-reviewer",
                "simulation": True,
                "simulatedActualCostUsd": 120 if action == "reconcile" else None,
            },
        )
        assert response.status_code == 200
    reconciled = response.json()
    assert reconciled["status"] == "reconciled"
    assert reconciled["reconciliation"]["provenance"] == ("deterministic_portfolio_simulation")


def test_procurement_api_blocks_unapproved_recommendation():
    result = client.post("/api/v2/optimizations", json=_scenario()).json()

    response = client.post("/api/v2/procurement/plans", json=_create_payload(result))

    assert response.status_code == 409
    assert "must be approved" in response.json()["detail"]


def test_procurement_api_returns_404_and_disabled_state(monkeypatch):
    assert client.get("/api/v2/procurement/plans/not-found").status_code == 404
    monkeypatch.setattr(
        main_module,
        "procurement_service",
        ProcurementService(procurement_enabled=False),
    )
    response = client.get("/api/v2/procurement/plans/not-found")
    assert response.status_code == 503
    assert "disabled" in response.json()["detail"]
