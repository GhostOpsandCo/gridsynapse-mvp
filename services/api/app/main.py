from __future__ import annotations

import csv
import io
import os
import secrets
import time
from collections import defaultdict, deque
from datetime import UTC, datetime
from threading import Lock

from fastapi import FastAPI, HTTPException, Query, Request, Response
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

from .procurement_repository import procurement_plan_store
from .repository import repository

PREVIEW_SAFE_MODE = os.getenv("GRIDSYNAPSE_PREVIEW_SAFE_MODE", "false").strip().lower() in {
    "1",
    "true",
    "yes",
    "on",
}
API_WRITE_KEY = os.getenv("GRIDSYNAPSE_API_WRITE_KEY", "").strip()
WRITE_AUTH_REQUIRED = os.getenv("VERCEL_ENV", "").strip().lower() == "production" or bool(
    API_WRITE_KEY
)
WRITE_RATE_LIMIT_PER_MINUTE = max(
    1,
    int(os.getenv("GRIDSYNAPSE_WRITE_RATE_LIMIT_PER_MINUTE", "120")),
)
_write_request_times: dict[str, deque[float]] = defaultdict(deque)
_write_rate_lock = Lock()

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
procurement_service = ProcurementService(
    execution_enabled=False if PREVIEW_SAFE_MODE else None,
    store=procurement_plan_store,
)


@app.middleware("http")
async def protect_write_routes(request: Request, call_next):
    is_write = request.method in {"POST", "PUT", "PATCH", "DELETE"}
    if not is_write or not request.url.path.startswith("/api/v2/"):
        return await call_next(request)

    if WRITE_AUTH_REQUIRED:
        supplied_key = request.headers.get("x-gridsynapse-api-key", "")
        if not API_WRITE_KEY:
            return JSONResponse(
                status_code=503,
                content={"detail": "Production write access is not configured"},
            )
        if not secrets.compare_digest(supplied_key, API_WRITE_KEY):
            return JSONResponse(status_code=401, content={"detail": "Write authorization required"})

    now = time.monotonic()
    forwarded_for = request.headers.get("x-forwarded-for", "local-session").split(",", 1)[0]
    bucket_key = f"{request.headers.get('x-gridsynapse-api-key', 'local-session')}:{forwarded_for}"
    with _write_rate_lock:
        bucket = _write_request_times[bucket_key]
        while bucket and now - bucket[0] >= 60:
            bucket.popleft()
        if len(bucket) >= WRITE_RATE_LIMIT_PER_MINUTE:
            return JSONResponse(
                status_code=429,
                content={"detail": "Write rate limit exceeded; retry in one minute"},
                headers={"Retry-After": "60"},
            )
        bucket.append(now)
    return await call_next(request)


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
            "planPersistence": procurement_service.store.status(),
            "writeAuthRequired": WRITE_AUTH_REQUIRED,
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
