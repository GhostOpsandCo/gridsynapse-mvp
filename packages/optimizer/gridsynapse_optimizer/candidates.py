from __future__ import annotations

from dataclasses import dataclass

from gridsynapse_contracts import OptimizationRequest, ResourcePool, Workload

from .calculations import PlacementMetrics, duration_slots, placement_metrics, slot_index


@dataclass(frozen=True)
class Candidate:
    workload: Workload
    pool: ResourcePool
    start_slot: int
    occupied_slots: tuple[int, ...]
    metrics: PlacementMetrics


def pool_rejection_reasons(workload: Workload, pool: ResourcePool) -> list[str]:
    reasons: list[str] = []
    if pool.gpu_type != workload.gpu_type:
        reasons.append("GPU type mismatch")
    if pool.region not in workload.allowed_regions:
        reasons.append("Region is outside the workload allowlist")
    if workload.max_latency_ms is not None and pool.latency_ms > workload.max_latency_ms:
        reasons.append(
            f"Pool latency {pool.latency_ms}ms exceeds limit {workload.max_latency_ms}ms"
        )
    return reasons


def enumerate_candidates(
    request: OptimizationRequest,
    workload: Workload,
) -> tuple[list[Candidate], list[str]]:
    candidates: list[Candidate] = []
    rejection_reasons: set[str] = set()
    slots_required = duration_slots(workload, request.horizon.slot_minutes)
    earliest_slot = slot_index(request, workload.earliest_start)
    deadline_slot = int(
        (workload.deadline - request.horizon.start).total_seconds()
        // 60
        // request.horizon.slot_minutes
    )

    for pool in sorted(request.resource_pools, key=lambda item: item.id):
        pool_reasons = pool_rejection_reasons(workload, pool)
        if pool_reasons:
            rejection_reasons.update(f"{pool.id}: {reason}" for reason in pool_reasons)
            continue

        latest_start = min(deadline_slot, request.horizon.slot_count) - slots_required
        if latest_start < earliest_slot:
            rejection_reasons.add(f"{pool.id}: no start can finish before the deadline")
            continue

        for start_slot in range(earliest_slot, latest_start + 1):
            occupied = tuple(range(start_slot, start_slot + slots_required))
            if any(pool.capacity_by_slot[slot] < workload.gpu_count for slot in occupied):
                continue
            metrics = placement_metrics(request, workload, pool, start_slot)
            if workload.max_budget_usd is not None and metrics.cost_micro_usd > round(
                workload.max_budget_usd * 1_000_000
            ):
                rejection_reasons.add(f"{pool.id}: placement cost exceeds workload budget")
                continue
            candidates.append(
                Candidate(
                    workload=workload,
                    pool=pool,
                    start_slot=start_slot,
                    occupied_slots=occupied,
                    metrics=metrics,
                )
            )

    if not candidates and not rejection_reasons:
        rejection_reasons.add("No pool has sufficient capacity inside the workload window")
    return candidates, sorted(rejection_reasons)
