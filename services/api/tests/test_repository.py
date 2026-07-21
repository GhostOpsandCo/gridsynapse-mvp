from __future__ import annotations

import json
from urllib.parse import parse_qs

import httpx
from app.repository import (
    PreviewSafeOptimizationRepository,
    SupabaseOptimizationRepository,
    build_repository,
)
from gridsynapse_adapters import ScenarioStore
from gridsynapse_optimizer import optimize


def test_supabase_repository_round_trip_and_history():
    rows: dict[str, dict] = {}
    events: list[dict] = []
    authorized_requests = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal authorized_requests
        assert request.headers["authorization"] == "Bearer secret-key"
        assert request.headers["apikey"] == "secret-key"
        authorized_requests += 1
        path = request.url.path
        query = parse_qs(request.url.query.decode())

        if request.method == "POST" and path.endswith("/gridsynapse_optimization_runs"):
            payload = json.loads(request.content)
            recommendation_id = payload["recommendation_id"]
            existing = rows.get(recommendation_id, {})
            rows[recommendation_id] = {
                "created_at": existing.get("created_at", "2026-07-18T12:00:00+00:00"),
                **existing,
                **payload,
            }
            return httpx.Response(201)

        if request.method == "POST" and path.endswith("/gridsynapse_decision_events"):
            events.append(json.loads(request.content))
            return httpx.Response(201)

        if request.method == "GET" and path.endswith("/gridsynapse_optimization_runs"):
            if "recommendation_id" in query:
                recommendation_id = query["recommendation_id"][0].removeprefix("eq.")
                row = rows.get(recommendation_id)
                return httpx.Response(
                    200,
                    json=(
                        [
                            {
                                "request_payload": row["request_payload"],
                                "result_payload": row["result_payload"],
                            }
                        ]
                        if row
                        else []
                    ),
                )
            return httpx.Response(200, json=list(rows.values()))

        raise AssertionError(f"Unhandled request: {request.method} {request.url}")

    repository = SupabaseOptimizationRepository("https://example.supabase.co", "secret-key")
    repository.client.close()
    repository.client = httpx.Client(
        transport=httpx.MockTransport(handler),
        headers={
            "apikey": "secret-key",
            "Authorization": "Bearer secret-key",
            "Content-Type": "application/json",
        },
    )

    request = ScenarioStore().get("reference-cost-carbon-tradeoff-v1")
    result = optimize(request)
    repository.save(request, result, event_type="recommendation_created")

    stored_request, stored_result = repository.get(result.recommendation_id)
    assert stored_request.scenario_id == request.scenario_id
    assert stored_result.recommendation_id == result.recommendation_id
    assert repository.list()[0].recommendation_id == result.recommendation_id
    assert repository.history()[0]["approvalStatus"] == "not_reviewed"
    assert events[0]["event_type"] == "recommendation_created"
    assert authorized_requests == 5

    repository.client.close()


def test_preview_safe_mode_ignores_supabase_credentials(monkeypatch):
    monkeypatch.setenv("GRIDSYNAPSE_PREVIEW_SAFE_MODE", "true")
    monkeypatch.setenv("SUPABASE_URL", "https://production-project.supabase.co")
    monkeypatch.setenv("SUPABASE_SECRET_KEY", "must-not-be-used")

    repository = build_repository()

    assert isinstance(repository, PreviewSafeOptimizationRepository)
    assert repository.status() == {
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


def test_preview_safe_mode_supports_session_workflow_without_durable_writes(monkeypatch):
    monkeypatch.setenv("GRIDSYNAPSE_PREVIEW_SAFE_MODE", "true")
    monkeypatch.setenv("SUPABASE_URL", "https://production-project.supabase.co")
    monkeypatch.setenv("SUPABASE_SECRET_KEY", "must-not-be-used")
    repository = build_repository()
    request = ScenarioStore().get("reference-cost-carbon-tradeoff-v1")
    result = optimize(request)

    repository.save(request, result, event_type="preview_recommendation_created")
    stored_request, stored_result = repository.get(result.recommendation_id)

    assert stored_request.scenario_id == request.scenario_id
    assert stored_result.recommendation_id == result.recommendation_id
    assert repository.status()["durableWritesEnabled"] is False
