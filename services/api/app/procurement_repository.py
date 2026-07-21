from __future__ import annotations

import os

import httpx
from gridsynapse_contracts import (
    OptimizationRequest,
    OptimizationResult,
    ProcurementCreateRequest,
    ProcurementPlan,
)
from gridsynapse_procurement import InMemoryProcurementPlanStore, ProcurementNotFoundError


class SupabaseProcurementPlanStore:
    table = "gridsynapse_procurement_plans"

    def __init__(
        self,
        url: str,
        api_key: str,
        *,
        database_api_key: str,
        timeout_seconds: float = 10.0,
    ) -> None:
        self.url = url.rstrip("/")
        self.client = httpx.Client(
            timeout=timeout_seconds,
            headers={
                "apikey": api_key,
                "Authorization": f"Bearer {api_key}",
                "Content-Type": "application/json",
                "x-gridsynapse-database-key": database_api_key,
            },
        )

    def _request(self, method: str, path: str, **kwargs) -> httpx.Response:
        response = self.client.request(method, f"{self.url}/rest/v1/{path}", **kwargs)
        response.raise_for_status()
        return response

    def save(
        self,
        plan: ProcurementPlan,
        request: OptimizationRequest,
        result: OptimizationResult,
        create: ProcurementCreateRequest,
    ) -> None:
        self._request(
            "POST",
            self.table,
            params={"on_conflict": "procurement_plan_id"},
            headers={"Prefer": "resolution=merge-duplicates,return=minimal"},
            json={
                "procurement_plan_id": plan.procurement_plan_id,
                "recommendation_id": plan.recommendation_id,
                "status": plan.status.value,
                "plan_payload": plan.model_dump(mode="json", by_alias=True),
                "request_payload": request.model_dump(mode="json", by_alias=True),
                "result_payload": result.model_dump(mode="json", by_alias=True),
                "create_payload": create.model_dump(mode="json", by_alias=True),
                "updated_at": plan.updated_at.isoformat(),
            },
        )

    def get(
        self,
        procurement_plan_id: str,
    ) -> tuple[
        ProcurementPlan,
        OptimizationRequest,
        OptimizationResult,
        ProcurementCreateRequest,
    ]:
        response = self._request(
            "GET",
            self.table,
            params={
                "procurement_plan_id": f"eq.{procurement_plan_id}",
                "select": "plan_payload,request_payload,result_payload,create_payload",
                "limit": "1",
            },
        )
        rows = response.json()
        if not rows:
            raise ProcurementNotFoundError(procurement_plan_id)
        row = rows[0]
        return (
            ProcurementPlan.model_validate(row["plan_payload"]),
            OptimizationRequest.model_validate(row["request_payload"]),
            OptimizationResult.model_validate(row["result_payload"]),
            ProcurementCreateRequest.model_validate(row["create_payload"]),
        )

    def status(self) -> dict:
        return {
            "backend": "supabase",
            "durable": True,
            "detail": "Procurement plans and lifecycle state are stored durably.",
        }


def build_procurement_plan_store():
    if os.getenv("GRIDSYNAPSE_PREVIEW_SAFE_MODE", "false").strip().lower() in {
        "1",
        "true",
        "yes",
        "on",
    }:
        return InMemoryProcurementPlanStore()

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
            "GridSynapse procurement persistence requires SUPABASE_URL plus either a "
            "Supabase secret key or SUPABASE_PUBLISHABLE_KEY with "
            "GRIDSYNAPSE_DATABASE_API_KEY"
        )
    if url and api_key:
        return SupabaseProcurementPlanStore(
            url,
            api_key,
            database_api_key=database_api_key,
        )
    return InMemoryProcurementPlanStore()


procurement_plan_store = build_procurement_plan_store()
