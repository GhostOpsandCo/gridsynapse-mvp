#!/usr/bin/env python3
"""Generate committed, reproducible reference-scenario evidence."""

from __future__ import annotations

import json
import sys
from datetime import UTC, datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
for package_path in (
    "packages/contracts",
    "packages/optimizer",
):
    sys.path.insert(0, str(ROOT / package_path))

from gridsynapse_contracts import (  # noqa: E402
    ObjectiveWeights,
    OptimizationPolicy,
    OptimizationRequest,
)
from gridsynapse_optimizer import optimize  # noqa: E402

PROFILES = {
    "cost": ObjectiveWeights(cost_bps=7000, carbon_bps=1000, delay_bps=1000, risk_bps=1000),
    "balanced": ObjectiveWeights(
        cost_bps=3500,
        carbon_bps=3000,
        delay_bps=1500,
        risk_bps=2000,
    ),
    "carbon": ObjectiveWeights(
        cost_bps=1500,
        carbon_bps=6500,
        delay_bps=1000,
        risk_bps=1000,
    ),
    "sla": ObjectiveWeights(cost_bps=1500, carbon_bps=1000, delay_bps=6000, risk_bps=1500),
}


def plan_values(plan) -> dict:
    return {
        "status": plan.status,
        "costUsd": plan.total_cost_usd,
        "energyKwh": plan.total_energy_kwh,
        "emissionsKgCo2e": plan.total_emissions_kg_co2e,
        "delayMinutes": plan.total_delay_minutes,
        "capacityRiskScore": plan.capacity_risk_score,
        "placements": [
            {
                "workloadId": placement.workload_id,
                "poolId": placement.pool_id,
                "start": placement.start.isoformat(),
                "end": placement.end.isoformat(),
            }
            for placement in plan.placements
        ],
    }


def main() -> int:
    scenario_path = ROOT / "data" / "scenarios" / "reference-scenario.json"
    base_request = OptimizationRequest.model_validate_json(scenario_path.read_text())
    results = []
    for profile, weights in PROFILES.items():
        request = base_request.model_copy(
            update={
                "policy": OptimizationPolicy(
                    profile=profile,
                    weights=weights,
                    max_solver_seconds=5,
                )
            }
        )
        result = optimize(request)
        results.append(
            {
                "profile": profile,
                "recommendationId": result.recommendation_id,
                "status": result.status,
                "validation": result.validation.model_dump(mode="json", by_alias=True),
                "solverDurationMs": result.solver.duration_ms,
                "baseline": plan_values(result.baseline),
                "optimized": plan_values(result.optimized),
                "deltas": result.deltas.model_dump(mode="json", by_alias=True),
            }
        )

    payload = {
        "evidenceVersion": "gridsynapse-reference-evidence-v1",
        "generatedAt": datetime.now(UTC).isoformat(),
        "scenarioId": base_request.scenario_id,
        "sourceTypes": sorted({pool.source.source_type for pool in base_request.resource_pools}),
        "note": (
            "Values are deterministic outputs from the checked-in reference scenario; "
            "they are not production savings claims."
        ),
        "profiles": results,
    }
    output = ROOT / "evidence" / "reference-profile-results.json"
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(payload, indent=2) + "\n")
    print(output)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
