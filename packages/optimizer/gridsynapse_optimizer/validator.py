from __future__ import annotations

from math import isclose

from gridsynapse_contracts import (
    OptimizationRequest,
    OptimizationResult,
    Plan,
    ValidationSummary,
)

from .calculations import (
    canonical_request_hash,
    duration_slots,
    placement_metrics,
    slot_index,
)


def validate_plan(
    request: OptimizationRequest,
    plan: Plan,
    *,
    require_all: bool,
) -> ValidationSummary:
    failures: list[str] = []
    successes: list[str] = []
    workload_map = {workload.id: workload for workload in request.workloads}
    pool_map = {pool.id: pool for pool in request.resource_pools}
    occupancy = {pool.id: [0] * request.horizon.slot_count for pool in request.resource_pools}
    seen: set[str] = set()
    calculated_cost = 0.0
    calculated_energy = 0.0
    calculated_emissions = 0.0
    calculated_delay = 0

    for placement in plan.placements:
        workload = workload_map.get(placement.workload_id)
        pool = pool_map.get(placement.pool_id)
        if workload is None:
            failures.append(f"Unknown workload {placement.workload_id}")
            continue
        if pool is None:
            failures.append(f"Unknown pool {placement.pool_id}")
            continue
        if placement.workload_id in seen:
            failures.append(f"Workload {placement.workload_id} is placed more than once")
        seen.add(placement.workload_id)

        if pool.gpu_type != workload.gpu_type:
            failures.append(f"{workload.id} GPU type is incompatible with {pool.id}")
        if pool.region not in workload.allowed_regions:
            failures.append(f"{workload.id} region is incompatible with {pool.id}")
        if workload.max_latency_ms is not None and pool.latency_ms > workload.max_latency_ms:
            failures.append(f"{workload.id} latency limit is violated")
        if placement.start < workload.earliest_start or placement.end > workload.deadline:
            failures.append(f"{workload.id} time window is violated")

        start = slot_index(request, placement.start)
        slots = duration_slots(workload, request.horizon.slot_minutes)
        if start < 0 or start + slots > request.horizon.slot_count:
            failures.append(f"{workload.id} is outside the scenario horizon")
            continue
        for slot in range(start, start + slots):
            occupancy[pool.id][slot] += workload.gpu_count

        metrics = placement_metrics(request, workload, pool, start)
        cost = metrics.cost_micro_usd / 1_000_000
        energy = metrics.energy_wh / 1000
        emissions = metrics.emissions_grams / 1000
        if workload.max_budget_usd is not None and cost > workload.max_budget_usd + 1e-6:
            failures.append(f"{workload.id} budget is violated")
        if not isclose(placement.cost_usd, cost, abs_tol=1e-6):
            failures.append(f"{workload.id} placement cost does not recalculate")
        if not isclose(placement.energy_kwh, energy, abs_tol=1e-6):
            failures.append(f"{workload.id} placement energy does not recalculate")
        if not isclose(placement.emissions_kg_co2e, emissions, abs_tol=1e-6):
            failures.append(f"{workload.id} placement emissions do not recalculate")
        if placement.delay_minutes != metrics.delay_minutes:
            failures.append(f"{workload.id} placement delay does not recalculate")
        calculated_cost += cost
        calculated_energy += energy
        calculated_emissions += emissions
        calculated_delay += metrics.delay_minutes

    for pool in request.resource_pools:
        for slot, used in enumerate(occupancy[pool.id]):
            if used > pool.capacity_by_slot[slot]:
                capacity = pool.capacity_by_slot[slot]
                failures.append(f"{pool.id} slot {slot} uses {used} GPUs with capacity {capacity}")

    if require_all and seen != set(workload_map):
        missing = sorted(set(workload_map) - seen)
        failures.append(f"Missing placements for: {', '.join(missing)}")

    if plan.placements:
        totals = [
            ("cost", plan.total_cost_usd, calculated_cost),
            ("energy", plan.total_energy_kwh, calculated_energy),
            ("emissions", plan.total_emissions_kg_co2e, calculated_emissions),
        ]
        for name, actual, expected in totals:
            if actual is None or not isclose(actual, expected, abs_tol=1e-6):
                failures.append(f"Plan {name} total does not recalculate")
        if plan.total_delay_minutes != calculated_delay:
            failures.append("Plan delay total does not recalculate")

    if not failures:
        successes.extend(
            [
                "Placement cardinality is valid",
                "Capacity is valid in every occupied slot",
                "GPU, region, latency, budget, and time constraints are valid",
                "Cost, energy, emissions, and delay totals independently recalculate",
            ]
        )
    return ValidationSummary(valid=not failures, checks=failures or successes)


def validate_result(
    request: OptimizationRequest,
    result: OptimizationResult,
) -> ValidationSummary:
    failures: list[str] = []
    if result.input_hash != canonical_request_hash(request):
        failures.append("Result input hash does not match the request")

    baseline_validation = validate_plan(
        request,
        result.baseline,
        require_all=result.baseline.status == "feasible",
    )
    optimized_validation = validate_plan(
        request,
        result.optimized,
        require_all=result.status == "feasible",
    )
    if not baseline_validation.valid:
        failures.extend(f"Baseline: {item}" for item in baseline_validation.checks)
    if not optimized_validation.valid:
        failures.extend(f"Optimized: {item}" for item in optimized_validation.checks)

    if not failures:
        checks = [
            "Input hash matches the canonical request",
            "Baseline independently validates",
            "Optimized schedule independently validates",
        ]
    else:
        checks = failures
    return ValidationSummary(valid=not failures, checks=checks)
