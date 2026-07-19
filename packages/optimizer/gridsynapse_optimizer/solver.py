from __future__ import annotations

import time
from collections import defaultdict

import ortools
from gridsynapse_contracts import (
    ApprovalState,
    Deltas,
    OptimizationRequest,
    OptimizationResult,
    SolverMetadata,
    ValidationSummary,
)
from ortools.sat.python import cp_model

from .baseline import build_baseline
from .calculations import build_placement, build_plan, canonical_request_hash
from .candidates import Candidate, enumerate_candidates
from .validator import validate_result

NORMALIZATION_SCALE = 100_000


def _reference_components(baseline, request: OptimizationRequest) -> dict[str, int]:
    horizon_minutes = int((request.horizon.end - request.horizon.start).total_seconds() // 60)
    return {
        "cost": max(1, round((baseline.total_cost_usd or 0) * 1_000_000)),
        "carbon": max(1, round((baseline.total_emissions_kg_co2e or 0) * 1000)),
        "delay": max(1, baseline.total_delay_minutes or horizon_minutes),
        "risk": max(1, round((baseline.capacity_risk_score or 1) * 100)),
    }


def _objective_coefficient(
    candidate: Candidate,
    request: OptimizationRequest,
    references: dict[str, int],
) -> int:
    weights = request.policy.weights
    components = (
        (weights.cost_bps, candidate.metrics.cost_micro_usd, references["cost"]),
        (weights.carbon_bps, candidate.metrics.emissions_grams, references["carbon"]),
        (weights.delay_bps, candidate.metrics.delay_minutes, references["delay"]),
        (weights.risk_bps, candidate.metrics.risk_units, references["risk"]),
    )
    score = sum(
        weight * value * NORMALIZATION_SCALE // reference for weight, value, reference in components
    )
    # Stable tie-breaker: earlier starts, then lexical pool order from candidate creation.
    return score * 1000 + candidate.start_slot


def _deltas(baseline, optimized) -> Deltas:
    if not baseline.placements or not optimized.placements:
        return Deltas(
            cost_usd=None,
            cost_percent=None,
            emissions_kg_co2e=None,
            emissions_percent=None,
            delay_minutes=None,
        )
    cost_delta = round((optimized.total_cost_usd or 0) - (baseline.total_cost_usd or 0), 6)
    emissions_delta = round(
        (optimized.total_emissions_kg_co2e or 0) - (baseline.total_emissions_kg_co2e or 0),
        6,
    )
    return Deltas(
        cost_usd=cost_delta,
        cost_percent=round(cost_delta / baseline.total_cost_usd * 100, 2)
        if baseline.total_cost_usd
        else None,
        emissions_kg_co2e=emissions_delta,
        emissions_percent=round(
            emissions_delta / baseline.total_emissions_kg_co2e * 100,
            2,
        )
        if baseline.total_emissions_kg_co2e
        else None,
        delay_minutes=(optimized.total_delay_minutes or 0) - (baseline.total_delay_minutes or 0),
    )


def optimize(request: OptimizationRequest) -> OptimizationResult:
    started = time.perf_counter()
    input_hash = canonical_request_hash(request)
    baseline, baseline_reasons = build_baseline(request)
    references = _reference_components(baseline, request)
    model = cp_model.CpModel()
    variables: dict[tuple[str, str, int], cp_model.IntVar] = {}
    candidates_by_workload: dict[str, list[Candidate]] = {}
    rejection_reasons: list[str] = list(baseline_reasons)

    for workload in sorted(request.workloads, key=lambda item: item.id):
        candidates, reasons = enumerate_candidates(request, workload)
        candidates_by_workload[workload.id] = candidates
        if not candidates:
            rejection_reasons.append(
                f"{workload.id}: " + ("; ".join(reasons) or "no feasible placement")
            )
            continue
        workload_variables = []
        for candidate in candidates:
            key = (workload.id, candidate.pool.id, candidate.start_slot)
            variable = model.new_bool_var("place__" + "__".join(map(str, key)))
            variables[key] = variable
            workload_variables.append(variable)
        model.add_exactly_one(workload_variables)

    if rejection_reasons and any(not value for value in candidates_by_workload.values()):
        optimized = build_plan(request, [], "infeasible")
        result = OptimizationResult(
            schema_version="gridsynapse-optimization-result-v2",
            recommendation_id=f"rec-{input_hash[:12]}-{request.policy.profile}",
            scenario_id=request.scenario_id,
            status="infeasible",
            input_hash=input_hash,
            solver=SolverMetadata(
                version=ortools.__version__,
                duration_ms=round((time.perf_counter() - started) * 1000),
                objective_profile=request.policy.profile,
            ),
            baseline=baseline,
            optimized=optimized,
            deltas=_deltas(baseline, optimized),
            infeasible_reasons=rejection_reasons,
            validation=ValidationSummary(
                valid=True,
                checks=["Infeasibility was detected before solve"],
            ),
            approval=ApprovalState(status="not_reviewed"),
        )
        return result

    capacity_terms: dict[tuple[str, int], list[tuple[cp_model.IntVar, int]]] = defaultdict(list)
    objective_terms = []
    candidate_lookup: dict[tuple[str, str, int], Candidate] = {}
    for workload_id, candidates in candidates_by_workload.items():
        for candidate in candidates:
            key = (workload_id, candidate.pool.id, candidate.start_slot)
            variable = variables[key]
            candidate_lookup[key] = candidate
            for slot in candidate.occupied_slots:
                capacity_terms[(candidate.pool.id, slot)].append(
                    (variable, candidate.workload.gpu_count)
                )
            objective_terms.append(
                _objective_coefficient(candidate, request, references) * variable
            )

    pool_map = {pool.id: pool for pool in request.resource_pools}
    for (pool_id, slot), terms in capacity_terms.items():
        model.add(
            sum(variable * gpu_count for variable, gpu_count in terms)
            <= pool_map[pool_id].capacity_by_slot[slot]
        )

    model.minimize(sum(objective_terms))
    solver = cp_model.CpSolver()
    solver.parameters.max_time_in_seconds = request.policy.max_solver_seconds
    solver.parameters.num_search_workers = 1
    solver.parameters.random_seed = 0
    status = solver.solve(model)

    if status not in (cp_model.OPTIMAL, cp_model.FEASIBLE):
        optimized = build_plan(request, [], "infeasible")
        result_status = "infeasible"
        rejection_reasons.append(f"CP-SAT returned {solver.status_name(status)}")
    else:
        placements = []
        for key in sorted(variables):
            if solver.value(variables[key]):
                candidate = candidate_lookup[key]
                placements.append(
                    build_placement(
                        request,
                        candidate.workload,
                        candidate.pool,
                        candidate.start_slot,
                        [
                            f"Selected by the {request.policy.profile} objective profile.",
                            f"{candidate.pool.region} passed GPU, residency, latency, "
                            "budget, and capacity constraints.",
                        ],
                    )
                )
        optimized = build_plan(request, placements, "feasible")
        result_status = "feasible"

    result = OptimizationResult(
        schema_version="gridsynapse-optimization-result-v2",
        recommendation_id=f"rec-{input_hash[:12]}-{request.policy.profile}",
        scenario_id=request.scenario_id,
        status=result_status,
        input_hash=input_hash,
        solver=SolverMetadata(
            version=ortools.__version__,
            duration_ms=round((time.perf_counter() - started) * 1000),
            objective_profile=request.policy.profile,
        ),
        baseline=baseline,
        optimized=optimized,
        deltas=_deltas(baseline, optimized),
        infeasible_reasons=rejection_reasons,
        validation=ValidationSummary(valid=False, checks=["Validation pending"]),
        approval=ApprovalState(status="not_reviewed"),
    )
    result.validation = validate_result(request, result)
    if not result.validation.valid:
        result.status = "error"
    return result
