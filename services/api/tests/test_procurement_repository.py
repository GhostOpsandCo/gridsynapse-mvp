from __future__ import annotations

import json
from urllib.parse import parse_qs

import httpx
from app.procurement_repository import SupabaseProcurementPlanStore
from gridsynapse_adapters import ScenarioStore
from gridsynapse_contracts import ExecutableWorkloadSpec, ProcurementCreateRequest
from gridsynapse_optimizer import optimize
from gridsynapse_procurement import ProcurementNotFoundError, ProcurementService


def test_supabase_procurement_store_round_trip():
    rows: dict[str, dict] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.headers["x-gridsynapse-database-key"] == "database-key"
        path = request.url.path
        query = parse_qs(request.url.query.decode())
        if request.method == "POST" and path.endswith("/gridsynapse_procurement_plans"):
            payload = json.loads(request.content)
            rows[payload["procurement_plan_id"]] = payload
            return httpx.Response(201)
        if request.method == "GET" and path.endswith("/gridsynapse_procurement_plans"):
            plan_id = query["procurement_plan_id"][0].removeprefix("eq.")
            row = rows.get(plan_id)
            return httpx.Response(200, json=[row] if row else [])
        raise AssertionError(f"Unhandled request: {request.method} {request.url}")

    store = SupabaseProcurementPlanStore(
        "https://example.supabase.co",
        "publishable-key",
        database_api_key="database-key",
    )
    store.client.close()
    store.client = httpx.Client(
        transport=httpx.MockTransport(handler),
        headers={
            "apikey": "publishable-key",
            "Authorization": "Bearer publishable-key",
            "Content-Type": "application/json",
            "x-gridsynapse-database-key": "database-key",
        },
    )

    request = ScenarioStore().get("reference-cost-carbon-tradeoff-v1")
    result = optimize(request)
    result.approval.status = "approved"
    create = ProcurementCreateRequest(
        recommendation_id=result.recommendation_id,
        expected_input_hash=result.input_hash,
        requested_by="portfolio-operator",
        max_spend_usd=1000,
        workload_specs=[
            ExecutableWorkloadSpec(
                workload_id=workload.id,
                container_image=f"ghcr.io/gridsynapse/{workload.id}:portfolio",
                command=["python", "run.py"],
            )
            for workload in request.workloads
        ],
    )
    service = ProcurementService(store=store)
    plan = service.create_plan(request, result, create)

    restarted = ProcurementService(store=store)
    restored = restarted.get_plan(plan.procurement_plan_id)

    assert restored == plan
    assert store.status()["durable"] is True
    try:
        restarted.get_plan("not-found")
    except ProcurementNotFoundError:
        pass
    else:
        raise AssertionError("Missing durable plan should raise ProcurementNotFoundError")
    store.client.close()
