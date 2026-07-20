from __future__ import annotations

import os
from copy import deepcopy
from datetime import UTC, datetime
from typing import Protocol

import httpx
from gridsynapse_contracts import OptimizationRequest, OptimizationResult


def _utc_now() -> str:
    return datetime.now(UTC).isoformat()


class Repository(Protocol):
    def save(
        self,
        request: OptimizationRequest,
        result: OptimizationResult,
        *,
        event_type: str = "recommendation_saved",
        actor: str = "gridsynapse-api",
    ) -> None: ...

    def get(self, recommendation_id: str) -> tuple[OptimizationRequest, OptimizationResult]: ...

    def list(self) -> list[OptimizationResult]: ...

    def history(self, limit: int = 20) -> list[dict]: ...

    def status(self) -> dict: ...


class InMemoryOptimizationRepository:
    def __init__(self) -> None:
        self._requests: dict[str, OptimizationRequest] = {}
        self._results: dict[str, OptimizationResult] = {}
        self._metadata: dict[str, dict] = {}

    def save(
        self,
        request: OptimizationRequest,
        result: OptimizationResult,
        *,
        event_type: str = "recommendation_saved",
        actor: str = "gridsynapse-api",
    ) -> None:
        recommendation_id = result.recommendation_id
        now = _utc_now()
        created_at = self._metadata.get(recommendation_id, {}).get("createdAt", now)
        self._requests[recommendation_id] = deepcopy(request)
        self._results[recommendation_id] = deepcopy(result)
        self._metadata[recommendation_id] = {
            "createdAt": created_at,
            "updatedAt": now,
            "lastEvent": event_type,
            "lastActor": actor,
        }

    def get(self, recommendation_id: str) -> tuple[OptimizationRequest, OptimizationResult]:
        if recommendation_id not in self._results:
            raise KeyError(recommendation_id)
        return deepcopy(self._requests[recommendation_id]), deepcopy(
            self._results[recommendation_id]
        )

    def list(self) -> list[OptimizationResult]:
        return [
            deepcopy(item)
            for item in sorted(
                self._results.values(),
                key=lambda item: self._metadata[item.recommendation_id]["updatedAt"],
                reverse=True,
            )
        ]

    def history(self, limit: int = 20) -> list[dict]:
        records = []
        for result in self.list()[:limit]:
            request = self._requests[result.recommendation_id]
            records.append(
                _history_record(request, result, self._metadata[result.recommendation_id])
            )
        return records

    def status(self) -> dict:
        return {
            "backend": "memory",
            "durable": False,
            "detail": "Decisions last only for the current API process.",
        }


class PreviewSafeOptimizationRepository(InMemoryOptimizationRepository):
    """Session-only repository that cannot reach durable persistence."""

    def status(self) -> dict:
        return {
            "backend": "preview_session",
            "durable": False,
            "previewSafeMode": True,
            "durableWritesEnabled": False,
            "writePolicy": "session_only",
            "detail": (
                "Preview Safe Mode keeps recommendations and reviews in this API session. "
                "Supabase writes and provider execution are disabled."
            ),
        }


class SupabaseOptimizationRepository:
    table = "gridsynapse_optimization_runs"
    event_table = "gridsynapse_decision_events"

    def __init__(
        self,
        url: str,
        secret_key: str,
        timeout_seconds: float = 10.0,
        database_api_key: str = "",
    ) -> None:
        self.url = url.rstrip("/")
        headers = {
            "apikey": secret_key,
            "Authorization": f"Bearer {secret_key}",
            "Content-Type": "application/json",
        }
        if database_api_key:
            headers["x-gridsynapse-database-key"] = database_api_key
        self.client = httpx.Client(
            timeout=timeout_seconds,
            headers=headers,
        )

    def _request(self, method: str, path: str, **kwargs) -> httpx.Response:
        response = self.client.request(method, f"{self.url}/rest/v1/{path}", **kwargs)
        response.raise_for_status()
        return response

    def save(
        self,
        request: OptimizationRequest,
        result: OptimizationResult,
        *,
        event_type: str = "recommendation_saved",
        actor: str = "gridsynapse-api",
    ) -> None:
        now = _utc_now()
        payload = {
            "recommendation_id": result.recommendation_id,
            "scenario_id": result.scenario_id,
            "request_payload": request.model_dump(mode="json", by_alias=True),
            "result_payload": result.model_dump(mode="json", by_alias=True),
            "approval_status": result.approval.status,
            "approved_by": result.approval.approved_by,
            "approved_at": (
                result.approval.approved_at.isoformat() if result.approval.approved_at else None
            ),
            "updated_at": now,
        }
        self._request(
            "POST",
            self.table,
            params={"on_conflict": "recommendation_id"},
            headers={"Prefer": "resolution=merge-duplicates,return=minimal"},
            json=payload,
        )
        self._request(
            "POST",
            self.event_table,
            headers={"Prefer": "return=minimal"},
            json={
                "recommendation_id": result.recommendation_id,
                "event_type": event_type,
                "actor": actor,
                "details": {
                    "approvalStatus": result.approval.status,
                    "inputHash": result.input_hash,
                    "objectiveProfile": result.solver.objective_profile,
                },
            },
        )

    def get(self, recommendation_id: str) -> tuple[OptimizationRequest, OptimizationResult]:
        response = self._request(
            "GET",
            self.table,
            params={
                "recommendation_id": f"eq.{recommendation_id}",
                "select": "request_payload,result_payload",
                "limit": "1",
            },
        )
        rows = response.json()
        if not rows:
            raise KeyError(recommendation_id)
        row = rows[0]
        return (
            OptimizationRequest.model_validate(row["request_payload"]),
            OptimizationResult.model_validate(row["result_payload"]),
        )

    def list(self) -> list[OptimizationResult]:
        response = self._request(
            "GET",
            self.table,
            params={"select": "result_payload", "order": "updated_at.desc", "limit": "100"},
        )
        return [OptimizationResult.model_validate(row["result_payload"]) for row in response.json()]

    def history(self, limit: int = 20) -> list[dict]:
        response = self._request(
            "GET",
            self.table,
            params={
                "select": (
                    "recommendation_id,scenario_id,request_payload,result_payload,"
                    "created_at,updated_at"
                ),
                "order": "updated_at.desc",
                "limit": str(limit),
            },
        )
        return [
            _history_record(
                OptimizationRequest.model_validate(row["request_payload"]),
                OptimizationResult.model_validate(row["result_payload"]),
                {"createdAt": row["created_at"], "updatedAt": row["updated_at"]},
            )
            for row in response.json()
        ]

    def status(self) -> dict:
        return {
            "backend": "supabase",
            "durable": True,
            "detail": "Recommendations, reviews, and decision events are stored durably.",
        }


def _history_record(
    request: OptimizationRequest,
    result: OptimizationResult,
    metadata: dict,
) -> dict:
    return {
        "recommendationId": result.recommendation_id,
        "scenarioId": result.scenario_id,
        "objectiveProfile": result.solver.objective_profile,
        "workloadCount": len(request.workloads),
        "totalCostUsd": result.optimized.total_cost_usd,
        "costDeltaUsd": result.deltas.cost_usd,
        "approvalStatus": result.approval.status,
        "approvedBy": result.approval.approved_by,
        "approvedAt": (
            result.approval.approved_at.isoformat() if result.approval.approved_at else None
        ),
        "createdAt": metadata["createdAt"],
        "updatedAt": metadata["updatedAt"],
    }


def build_repository() -> Repository:
    if os.getenv("GRIDSYNAPSE_PREVIEW_SAFE_MODE", "false").strip().lower() in {
        "1",
        "true",
        "yes",
        "on",
    }:
        return PreviewSafeOptimizationRepository()

    url = os.getenv("SUPABASE_URL", "").strip()
    secret_key = (
        os.getenv("SUPABASE_SECRET_KEY", "").strip()
        or os.getenv("SUPABASE_SERVICE_ROLE_KEY", "").strip()
    )
    publishable_key = os.getenv("SUPABASE_PUBLISHABLE_KEY", "").strip()
    database_api_key = os.getenv("GRIDSYNAPSE_DATABASE_API_KEY", "").strip()
    api_key = secret_key or publishable_key
    has_server_access = bool(secret_key) or bool(publishable_key and database_api_key)
    if bool(url) != bool(api_key) or (url and not has_server_access):
        raise RuntimeError(
            "GridSynapse persistence requires SUPABASE_URL plus either a Supabase "
            "secret key or SUPABASE_PUBLISHABLE_KEY with GRIDSYNAPSE_DATABASE_API_KEY"
        )
    if url and api_key:
        return SupabaseOptimizationRepository(
            url,
            api_key,
            database_api_key=database_api_key,
        )
    return InMemoryOptimizationRepository()


repository = build_repository()
