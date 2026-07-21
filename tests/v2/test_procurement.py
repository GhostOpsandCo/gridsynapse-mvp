from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from gridsynapse_contracts import (
    ExecutableWorkloadSpec,
    ProcurementAction,
    ProcurementCreateRequest,
    ProcurementStatus,
    ProcurementTransitionRequest,
)
from gridsynapse_optimizer import optimize
from gridsynapse_procurement import (
    InMemoryProcurementPlanStore,
    InvalidProcurementPlanError,
    ProcurementService,
    ProcurementTransitionError,
)

NOW = datetime(2026, 7, 20, 12, tzinfo=UTC)


def _specs(request):
    return [
        ExecutableWorkloadSpec(
            workload_id=workload.id,
            container_image=f"ghcr.io/gridsynapse/{workload.id}:portfolio",
            command=["python", "run.py", "--workload", workload.id],
            checkpoint_uri=f"s3://portfolio-checkpoints/{workload.id}",
            retry_limit=1,
            secret_refs=[f"portfolio/{workload.id}/provider-token"],
        )
        for workload in request.workloads
    ]


def _approved_result(request):
    result = optimize(request)
    assert result.status == "feasible"
    assert result.validation.valid
    result.approval.status = "approved"
    result.approval.approved_by = "portfolio-reviewer"
    result.approval.approved_at = NOW
    return result


def _create_request(result, request, max_spend_usd=1_000):
    return ProcurementCreateRequest(
        recommendation_id=result.recommendation_id,
        expected_input_hash=result.input_hash,
        requested_by="portfolio-operator",
        max_spend_usd=max_spend_usd,
        workload_specs=_specs(request),
    )


def test_builds_stable_inspectable_planning_manifest(reference_request):
    result = _approved_result(reference_request)
    service = ProcurementService(now=lambda: NOW)
    create = _create_request(result, reference_request)

    first = service.create_plan(reference_request, result, create)
    second = service.create_plan(reference_request, result, create)

    assert first.procurement_plan_id == second.procurement_plan_id
    assert first.idempotency_key == second.idempotency_key
    assert first.status == ProcurementStatus.CREATED
    assert first.simulation_only is True
    assert first.live_execution_permitted is False
    assert first.provider_credentials_present is False
    assert "SkyPilot portfolio dry-run manifest" in first.skypilot_manifest_yaml
    assert "No provider inventory is reserved" in first.skypilot_manifest_yaml
    assert "resources:" in first.skypilot_manifest_yaml
    assert "accelerators:" in first.skypilot_manifest_yaml
    assert "image_id:" in first.skypilot_manifest_yaml
    assert "run: |" in first.skypilot_manifest_yaml
    assert "provider-token" not in first.skypilot_manifest_yaml
    assert "Secret references are intentionally omitted" in first.skypilot_manifest_yaml
    assert len(first.placements) == len(reference_request.workloads)
    assert all(item.offer.price_classification == "planning_only" for item in first.placements)
    assert all(
        item.offer.inventory_classification == "modeled_not_executable" for item in first.placements
    )


def test_requires_approved_validated_feasible_recommendation(reference_request):
    result = optimize(reference_request)
    service = ProcurementService(now=lambda: NOW)
    create = _create_request(result, reference_request)

    with pytest.raises(InvalidProcurementPlanError, match="must be approved"):
        service.create_plan(reference_request, result, create)


def test_verification_surfaces_planning_only_inventory_and_blocks_overspend(
    reference_request,
):
    result = _approved_result(reference_request)
    service = ProcurementService(now=lambda: NOW)
    create = _create_request(result, reference_request, max_spend_usd=1)
    plan = service.create_plan(reference_request, result, create)

    verified = service.verify_plan(plan.procurement_plan_id)

    assert verified.status == ProcurementStatus.VERIFICATION_FAILED
    assert verified.verification is not None
    assert verified.verification.valid_for_dry_run is False
    assert any("exceeds" in item for item in verified.verification.blocking_reasons)
    assert any("planning-only" in item for item in verified.verification.warnings)
    assert any("not executable inventory" in item for item in verified.verification.warnings)
    with pytest.raises(ProcurementTransitionError, match="valid dry-run verification"):
        service.transition_plan(
            plan.procurement_plan_id,
            ProcurementTransitionRequest(
                action=ProcurementAction.APPROVE_FOR_LAUNCH,
                actor="portfolio-reviewer",
                simulation=True,
            ),
        )


def test_stale_evidence_is_a_blocking_verification_failure(reference_request):
    stale_pools = []
    for pool in reference_request.resource_pools:
        stale_source = pool.source.model_copy(
            update={
                "observed_at": NOW - timedelta(hours=2),
                "freshness_seconds": 60,
            }
        )
        stale_pools.append(pool.model_copy(update={"source": stale_source}))
    stale_request = reference_request.model_copy(update={"resource_pools": stale_pools})
    result = _approved_result(stale_request)
    service = ProcurementService(now=lambda: NOW)
    plan = service.create_plan(stale_request, result, _create_request(result, stale_request))

    verified = service.verify_plan(plan.procurement_plan_id)

    assert verified.status == ProcurementStatus.VERIFICATION_FAILED
    assert verified.verification is not None
    assert any("stale" in item.lower() for item in verified.verification.blocking_reasons)


def test_portfolio_simulation_lifecycle_never_allows_live_execution(reference_request):
    result = _approved_result(reference_request)
    service = ProcurementService(now=lambda: NOW)
    plan = service.create_plan(
        reference_request,
        result,
        _create_request(result, reference_request),
    )
    plan = service.verify_plan(plan.procurement_plan_id)
    assert plan.status == ProcurementStatus.DRY_RUN_READY
    assert plan.verification is not None
    assert plan.verification.live_launch_allowed is False

    with pytest.raises(ProcurementTransitionError, match="simulated transitions only"):
        service.transition_plan(
            plan.procurement_plan_id,
            ProcurementTransitionRequest(
                action=ProcurementAction.APPROVE_FOR_LAUNCH,
                actor="portfolio-reviewer",
            ),
        )

    actions = [
        ProcurementAction.APPROVE_FOR_LAUNCH,
        ProcurementAction.START_PROVISIONING,
        ProcurementAction.MARK_RUNNING,
        ProcurementAction.MARK_COMPLETED,
        ProcurementAction.RECONCILE,
    ]
    for action in actions:
        plan = service.transition_plan(
            plan.procurement_plan_id,
            ProcurementTransitionRequest(
                action=action,
                actor="portfolio-reviewer",
                simulation=True,
                simulated_actual_cost_usd=(
                    round(plan.estimated_total_cost_usd * 1.05, 2)
                    if action == ProcurementAction.RECONCILE
                    else None
                ),
            ),
        )

    assert plan.status == ProcurementStatus.RECONCILED
    assert plan.live_execution_permitted is False
    assert plan.reconciliation is not None
    assert plan.reconciliation.provenance == "deterministic_portfolio_simulation"
    assert "No provider invoice" in plan.reconciliation.methodology


def test_execution_flag_does_not_create_a_live_provider_path(reference_request):
    result = _approved_result(reference_request)
    service = ProcurementService(execution_enabled=True, now=lambda: NOW)
    plan = service.create_plan(
        reference_request,
        result,
        _create_request(result, reference_request),
    )

    verified = service.verify_plan(plan.procurement_plan_id)

    assert verified.status == ProcurementStatus.VERIFICATION_FAILED
    assert verified.live_execution_permitted is False
    assert verified.verification is not None
    assert any(
        "no authorized live provider path" in item
        for item in verified.verification.blocking_reasons
    )


def test_environment_defaults_enable_dry_run_and_disable_execution(monkeypatch):
    monkeypatch.delenv("GRIDSYNAPSE_PROCUREMENT_ENABLED", raising=False)
    monkeypatch.delenv("GRIDSYNAPSE_EXECUTION_ENABLED", raising=False)

    service = ProcurementService()

    assert service.procurement_enabled is True
    assert service.execution_enabled is False


def test_shared_store_preserves_plan_across_service_instances(reference_request):
    result = _approved_result(reference_request)
    store = InMemoryProcurementPlanStore()
    first_service = ProcurementService(now=lambda: NOW, store=store)
    plan = first_service.create_plan(
        reference_request,
        result,
        _create_request(result, reference_request),
    )

    restarted_service = ProcurementService(now=lambda: NOW, store=store)
    restored = restarted_service.get_plan(plan.procurement_plan_id)
    verified = restarted_service.verify_plan(plan.procurement_plan_id)

    assert restored == plan
    assert verified.status == ProcurementStatus.DRY_RUN_READY
