from __future__ import annotations

from gridsynapse_contracts import ObjectiveWeights
from gridsynapse_optimizer import optimize, validate_plan
from gridsynapse_optimizer.calculations import duration_slots

PROFILES = {
    "cost": ObjectiveWeights(cost_bps=6500, carbon_bps=1000, delay_bps=1500, risk_bps=1000),
    "balanced": ObjectiveWeights(cost_bps=4000, carbon_bps=2500, delay_bps=2000, risk_bps=1500),
    "carbon": ObjectiveWeights(cost_bps=1500, carbon_bps=6000, delay_bps=1500, risk_bps=1000),
    "sla": ObjectiveWeights(cost_bps=2000, carbon_bps=500, delay_bps=5500, risk_bps=2000),
}


def with_profile(request, profile):
    updated = request.model_copy(deep=True)
    updated.policy.profile = profile
    updated.policy.weights = PROFILES[profile]
    return updated


def test_reference_result_is_independently_valid(reference_request):
    result = optimize(reference_request)
    assert result.status == "feasible"
    assert result.validation.valid is True
    assert len(result.optimized.placements) == len(reference_request.workloads)
    assert result.baseline.total_cost_usd == 130.2
    assert result.baseline.total_emissions_kg_co2e == 8.128


def test_objective_profiles_change_placement(reference_request):
    cost_result = optimize(with_profile(reference_request, "cost"))
    carbon_result = optimize(with_profile(reference_request, "carbon"))
    assert "pool-us-central-a100" in {item.pool_id for item in cost_result.optimized.placements}
    assert {item.pool_id for item in carbon_result.optimized.placements} == {"pool-us-east-a100"}
    assert cost_result.optimized.total_cost_usd < carbon_result.optimized.total_cost_usd
    assert (
        carbon_result.optimized.total_emissions_kg_co2e
        < cost_result.optimized.total_emissions_kg_co2e
    )


def test_identical_input_produces_identical_placements(reference_request):
    first = optimize(reference_request)
    second = optimize(reference_request)
    assert first.input_hash == second.input_hash
    assert first.recommendation_id == second.recommendation_id
    assert first.optimized.placements == second.optimized.placements


def test_latency_constraint_excludes_slow_pools(reference_request):
    updated = reference_request.model_copy(deep=True)
    for workload in updated.workloads:
        workload.max_latency_ms = 20
    result = optimize(updated)
    assert result.status == "feasible"
    assert {item.pool_id for item in result.optimized.placements} == {"pool-us-west-a100"}


def test_budget_can_make_workload_infeasible(reference_request):
    updated = reference_request.model_copy(deep=True)
    updated.workloads[0].max_budget_usd = 1
    result = optimize(updated)
    assert result.status == "infeasible"
    assert any("budget" in reason.lower() for reason in result.infeasible_reasons)


def test_duration_uses_ceiling_slots(reference_request):
    updated = reference_request.model_copy(deep=True)
    updated.workloads[2].duration_minutes = 61
    assert duration_slots(updated.workloads[2], updated.horizon.slot_minutes) == 3
    result = optimize(updated)
    assert result.validation.valid is True


def test_capacity_is_never_exceeded(reference_request):
    updated = reference_request.model_copy(deep=True)
    for pool in updated.resource_pools:
        pool.capacity_by_slot = [8] * updated.horizon.slot_count
    result = optimize(updated)
    assert result.status == "feasible"
    validation = validate_plan(updated, result.optimized, require_all=True)
    assert validation.valid is True


def test_validator_rejects_tampered_total(reference_request):
    result = optimize(reference_request)
    result.optimized.total_cost_usd += 1
    validation = validate_plan(reference_request, result.optimized, require_all=True)
    assert validation.valid is False
    assert "Plan cost total does not recalculate" in validation.checks
