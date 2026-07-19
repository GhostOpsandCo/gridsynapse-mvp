from __future__ import annotations

from gridsynapse_contracts import Explanation, OptimizationRequest, OptimizationResult


def _percent(value: float | None) -> str:
    return "not available" if value is None else f"{abs(value):.1f}%"


def explain_result(
    request: OptimizationRequest,
    result: OptimizationResult,
) -> Explanation:
    if result.status == "infeasible":
        reasons = result.infeasible_reasons or [
            "No feasible placement satisfied every hard constraint."
        ]
        return Explanation(
            recommendation_id=result.recommendation_id,
            headline="No feasible schedule passed every operating constraint",
            summary=(
                "GridSynapse did not relax residency, GPU, latency, capacity, "
                "deadline, or budget rules."
            ),
            decision_factors=reasons[:4],
            tradeoffs=["Adjust a hard constraint or add compatible capacity before rerunning."],
            warnings=["No approval is available for an infeasible recommendation."],
            operator_action=(
                "Review the blocking reasons, update the scenario, and run a new optimization."
            ),
        )

    cost_percent = result.deltas.cost_percent
    emissions_percent = result.deltas.emissions_percent
    cost_direction = "reduces" if cost_percent is not None and cost_percent < 0 else "increases"
    emissions_direction = (
        "reduces" if emissions_percent is not None and emissions_percent < 0 else "increases"
    )
    pool_map = {pool.id: pool for pool in request.resource_pools}
    selected_regions = sorted(
        {pool_map[item.pool_id].region for item in result.optimized.placements}
    )

    warnings = []
    if cost_percent is not None and cost_percent > 0:
        warnings.append(
            f"The selected profile adds {_percent(cost_percent)} cost versus baseline "
            "to improve another objective."
        )
    if emissions_percent is not None and emissions_percent > 0:
        warnings.append(
            f"The selected profile adds {_percent(emissions_percent)} emissions versus baseline."
        )
    if not warnings:
        warnings.append(
            "All savings are scenario-relative and depend on the supplied price "
            "and carbon snapshots."
        )

    selected_pools = ", ".join(sorted({item.pool_id for item in result.optimized.placements}))
    return Explanation(
        recommendation_id=result.recommendation_id,
        headline=(
            f"{request.policy.profile.title()} routing moves work across "
            f"{', '.join(selected_regions)}"
        ),
        summary=(
            f"Compared with the named baseline, the validated schedule {cost_direction} cost by "
            f"{_percent(cost_percent)} and {emissions_direction} emissions by "
            f"{_percent(emissions_percent)} while meeting every hard constraint."
        ),
        decision_factors=[
            f"{len(result.optimized.placements)} workloads were placed exactly once.",
            f"The {request.policy.profile} profile applied explicit cost, carbon, "
            "delay, and capacity-risk weights.",
            f"Selected pools: {selected_pools}.",
            f"Independent validation completed {len(result.validation.checks)} result checks.",
        ],
        tradeoffs=[
            f"Cost delta: ${result.deltas.cost_usd:+,.2f}."
            if result.deltas.cost_usd is not None
            else "Cost delta is unavailable because the baseline is infeasible.",
            f"Emissions delta: {result.deltas.emissions_kg_co2e:+,.2f} kg CO2e."
            if result.deltas.emissions_kg_co2e is not None
            else "Emissions delta is unavailable because the baseline is infeasible.",
            f"Delay delta: {result.deltas.delay_minutes:+d} minutes."
            if result.deltas.delay_minutes is not None
            else "Delay delta is unavailable.",
        ],
        warnings=warnings,
        operator_action=(
            "Review the placements and source freshness, then approve or request a revision."
        ),
    )
