from __future__ import annotations

import csv
import io
import os
import time
from datetime import UTC, datetime

from fastapi import FastAPI, HTTPException, Query, Response
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, PlainTextResponse
from gridsynapse_adapters import LiveMarketScenarioService, ScenarioStore
from gridsynapse_contracts import (
    ApprovalUpdate,
    Explanation,
    OptimizationRequest,
    OptimizationResult,
    ProcurementCreateRequest,
    ProcurementPlan,
    ProcurementTransitionRequest,
)
from gridsynapse_explanations import explain_result
from gridsynapse_optimizer import optimize
from gridsynapse_procurement import (
    InvalidProcurementPlanError,
    ProcurementDisabledError,
    ProcurementNotFoundError,
    ProcurementService,
    ProcurementTransitionError,
)
from prometheus_client import CONTENT_TYPE_LATEST, Counter, Histogram, generate_latest

from .repository import repository

PREVIEW_SAFE_MODE = os.getenv("GRIDSYNAPSE_PREVIEW_SAFE_MODE", "false").strip().lower() in {
    "1",
    "true",
    "yes",
    "on",
}

OPTIMIZATION_REQUESTS = Counter(
    "gridsynapse_optimization_requests_total",
    "Optimization requests by final status",
    ["status", "profile"],
)
OPTIMIZATION_DURATION = Histogram(
    "gridsynapse_optimization_duration_seconds",
    "End-to-end optimization duration",
    buckets=(0.01, 0.05, 0.1, 0.25, 0.5, 1, 2, 5, 10),
)

app = FastAPI(
    title="GridSynapse Optimization API",
    version="2.0.0",
    description="Deterministic baseline and CP-SAT optimization for AI compute workloads.",
)
cors_origins = [
    origin.strip()
    for origin in os.getenv(
        "GRIDSYNAPSE_CORS_ORIGINS",
        "http://127.0.0.1:3020,http://localhost:3020,https://gridsynapse.io,https://www.gridsynapse.io",
    ).split(",")
    if origin.strip()
]

app.add_middleware(
    CORSMiddleware,
    allow_origins=cors_origins,
    allow_origin_regex=os.getenv(
        "GRIDSYNAPSE_CORS_ORIGIN_REGEX",
        r"https://gridsynapse(?:-[a-z0-9-]+)?\.vercel\.app",
    ),
    allow_credentials=False,
    allow_methods=["GET", "POST"],
    allow_headers=["*"],
)

scenario_store = ScenarioStore()
live_market_service = LiveMarketScenarioService(scenario_store)
procurement_service = ProcurementService(execution_enabled=False if PREVIEW_SAFE_MODE else None)


def _get_recommendation(recommendation_id: str):
    try:
        return repository.get(recommendation_id)
    except KeyError as error:
        raise HTTPException(status_code=404, detail="Recommendation not found") from error


@app.get("/health")
def health() -> dict:
    return {
        "status": "healthy",
        "service": "gridsynapse-api",
        "version": "2.0.0",
        "previewSafeMode": PREVIEW_SAFE_MODE,
        "persistence": repository.status(),
        "procurement": {
            "enabled": procurement_service.procurement_enabled,
            "mode": "portfolio_dry_run",
            "executionEnabled": procurement_service.execution_enabled,
            "liveProviderCallsAvailable": False,
            "durableWritesEnabled": repository.status().get("durable", False),
        },
    }


@app.get("/metrics")
def metrics() -> Response:
    return Response(generate_latest(), media_type=CONTENT_TYPE_LATEST)


@app.get("/api/v2/scenarios")
def list_scenarios() -> list[dict]:
    return scenario_store.list()


@app.get("/api/v2/live-market/scenario")
def get_live_market_scenario(refresh: bool = Query(default=False)) -> dict:
    if os.getenv("GRIDSYNAPSE_LIVE_MARKET_ENABLED", "true").lower() != "true":
        raise HTTPException(status_code=503, detail="Live market adapters are disabled")
    try:
        return live_market_service.snapshot(force=refresh)
    except (RuntimeError, ValueError) as error:
        raise HTTPException(
            status_code=503,
            detail=f"Live market inputs are temporarily unavailable: {error}",
        ) from error


@app.get("/api/v2/scenarios/{scenario_id}", response_model=OptimizationRequest)
def get_scenario(scenario_id: str) -> OptimizationRequest:
    try:
        return scenario_store.get(scenario_id)
    except KeyError as error:
        raise HTTPException(status_code=404, detail="Scenario not found") from error


@app.get("/api/v2/scenarios/{scenario_id}/data-health")
def get_data_health(scenario_id: str) -> dict:
    try:
        return scenario_store.data_health(scenario_id)
    except KeyError as error:
        raise HTTPException(status_code=404, detail="Scenario not found") from error


@app.post("/api/v2/scenarios/validate")
def validate_scenario(request: OptimizationRequest) -> dict:
    return {
        "valid": True,
        "scenarioId": request.scenario_id,
        "workloadCount": len(request.workloads),
        "resourcePoolCount": len(request.resource_pools),
        "slotCount": request.horizon.slot_count,
    }


@app.post("/api/v2/optimizations", response_model=OptimizationResult)
def create_optimization(request: OptimizationRequest) -> OptimizationResult:
    started = time.perf_counter()
    result = optimize(request)
    event_type = "recommendation_created"
    try:
        _, stored_result = repository.get(result.recommendation_id)
        if stored_result.input_hash == result.input_hash:
            result.approval = stored_result.approval
            event_type = "recommendation_refreshed"
    except KeyError:
        pass
    repository.save(request, result, event_type=event_type)
    OPTIMIZATION_REQUESTS.labels(status=result.status, profile=request.policy.profile).inc()
    OPTIMIZATION_DURATION.observe(time.perf_counter() - started)
    return result


@app.get("/api/v2/optimizations", response_model=list[OptimizationResult])
def list_optimizations() -> list[OptimizationResult]:
    return repository.list()


@app.get("/api/v2/decision-history")
def decision_history(limit: int = Query(default=20, ge=1, le=100)) -> list[dict]:
    return repository.history(limit=limit)


@app.get("/api/v2/optimizations/{recommendation_id}", response_model=OptimizationResult)
def get_optimization(recommendation_id: str) -> OptimizationResult:
    _, result = _get_recommendation(recommendation_id)
    return result


@app.get(
    "/api/v2/optimizations/{recommendation_id}/explanation",
    response_model=Explanation,
)
def get_explanation(recommendation_id: str) -> Explanation:
    request, result = _get_recommendation(recommendation_id)
    return explain_result(request, result)


@app.post(
    "/api/v2/optimizations/{recommendation_id}/approval",
    response_model=OptimizationResult,
)
def update_approval(
    recommendation_id: str,
    update: ApprovalUpdate,
) -> OptimizationResult:
    request, result = _get_recommendation(recommendation_id)
    if not result.validation.valid or result.status != "feasible":
        raise HTTPException(
            status_code=409,
            detail="Only a validated feasible result can be reviewed",
        )
    result.approval.status = update.status
    result.approval.approved_by = update.actor if update.status == "approved" else None
    result.approval.approved_at = datetime.now(UTC) if update.status == "approved" else None
    repository.save(
        request,
        result,
        event_type="approval_updated",
        actor=update.actor,
    )
    return result


@app.post("/api/v2/procurement/plans", response_model=ProcurementPlan)
def create_procurement_plan(create: ProcurementCreateRequest) -> ProcurementPlan:
    request, result = _get_recommendation(create.recommendation_id)
    try:
        return procurement_service.create_plan(request, result, create)
    except ProcurementDisabledError as error:
        raise HTTPException(status_code=503, detail=str(error)) from error
    except InvalidProcurementPlanError as error:
        raise HTTPException(status_code=409, detail=str(error)) from error


@app.get(
    "/api/v2/procurement/plans/{procurement_plan_id}",
    response_model=ProcurementPlan,
)
def get_procurement_plan(procurement_plan_id: str) -> ProcurementPlan:
    try:
        return procurement_service.get_plan(procurement_plan_id)
    except ProcurementDisabledError as error:
        raise HTTPException(status_code=503, detail=str(error)) from error
    except ProcurementNotFoundError as error:
        raise HTTPException(status_code=404, detail="Procurement plan not found") from error


@app.post(
    "/api/v2/procurement/plans/{procurement_plan_id}/verify",
    response_model=ProcurementPlan,
)
def verify_procurement_plan(procurement_plan_id: str) -> ProcurementPlan:
    try:
        return procurement_service.verify_plan(procurement_plan_id)
    except ProcurementDisabledError as error:
        raise HTTPException(status_code=503, detail=str(error)) from error
    except ProcurementNotFoundError as error:
        raise HTTPException(status_code=404, detail="Procurement plan not found") from error


@app.post(
    "/api/v2/procurement/plans/{procurement_plan_id}/transitions",
    response_model=ProcurementPlan,
)
def transition_procurement_plan(
    procurement_plan_id: str,
    transition: ProcurementTransitionRequest,
) -> ProcurementPlan:
    try:
        return procurement_service.transition_plan(procurement_plan_id, transition)
    except ProcurementDisabledError as error:
        raise HTTPException(status_code=503, detail=str(error)) from error
    except ProcurementNotFoundError as error:
        raise HTTPException(status_code=404, detail="Procurement plan not found") from error
    except ProcurementTransitionError as error:
        raise HTTPException(status_code=409, detail=str(error)) from error


@app.get("/api/v2/optimizations/{recommendation_id}/export")
def export_optimization(
    recommendation_id: str,
    format: str = Query(default="json", pattern="^(json|csv)$"),
):
    _, result = _get_recommendation(recommendation_id)
    filename = f"{result.recommendation_id}.{format}"
    if format == "json":
        return JSONResponse(
            result.model_dump(mode="json", by_alias=True),
            headers={"Content-Disposition": f'attachment; filename="{filename}"'},
        )

    buffer = io.StringIO()
    writer = csv.DictWriter(
        buffer,
        fieldnames=[
            "plan",
            "workloadId",
            "poolId",
            "start",
            "end",
            "gpuCount",
            "costUsd",
            "energyKwh",
            "emissionsKgCo2e",
            "delayMinutes",
        ],
    )
    writer.writeheader()
    for plan_name, plan in (("baseline", result.baseline), ("optimized", result.optimized)):
        for placement in plan.placements:
            row = placement.model_dump(mode="json", by_alias=True)
            row["plan"] = plan_name
            row.pop("reasons", None)
            writer.writerow(row)
    return PlainTextResponse(
        buffer.getvalue(),
        media_type="text/csv",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )
