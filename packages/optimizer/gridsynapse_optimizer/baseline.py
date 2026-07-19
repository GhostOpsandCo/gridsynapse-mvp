from __future__ import annotations

from gridsynapse_contracts import OptimizationRequest, Plan

from .calculations import build_placement, build_plan
from .candidates import Candidate, enumerate_candidates


def _candidate_order(candidate: Candidate, baseline_pool_id: str | None) -> tuple:
    preferred = 0 if baseline_pool_id and candidate.pool.id == baseline_pool_id else 1
    return (preferred, candidate.start_slot, candidate.pool.id)


def build_baseline(request: OptimizationRequest) -> tuple[Plan, list[str]]:
    occupancy = {pool.id: [0] * request.horizon.slot_count for pool in request.resource_pools}
    placements = []
    reasons: list[str] = []

    for workload in sorted(request.workloads, key=lambda item: (-item.priority, item.id)):
        candidates, candidate_reasons = enumerate_candidates(request, workload)
        selected = None
        for candidate in sorted(
            candidates,
            key=lambda item: _candidate_order(item, workload.baseline_pool_id),
        ):
            if all(
                occupancy[candidate.pool.id][slot] + workload.gpu_count
                <= candidate.pool.capacity_by_slot[slot]
                for slot in candidate.occupied_slots
            ):
                selected = candidate
                break

        if selected is None:
            detail = "; ".join(candidate_reasons[:3]) or "capacity conflict"
            reasons.append(f"Baseline could not place {workload.id}: {detail}")
            continue

        for slot in selected.occupied_slots:
            occupancy[selected.pool.id][slot] += workload.gpu_count
        pool_note = (
            "named baseline pool"
            if selected.pool.id == workload.baseline_pool_id
            else "first feasible compatible pool"
        )
        placements.append(
            build_placement(
                request,
                workload,
                selected.pool,
                selected.start_slot,
                [f"Baseline policy used the {pool_note} at the earliest feasible slot."],
            )
        )

    if len(placements) == len(request.workloads):
        status = "feasible"
    elif placements:
        status = "partial"
    else:
        status = "infeasible"
    return build_plan(request, placements, status), reasons
