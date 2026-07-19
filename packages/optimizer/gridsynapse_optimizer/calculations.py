from __future__ import annotations

import hashlib
import json
import math
from dataclasses import dataclass
from datetime import timedelta

from gridsynapse_contracts import OptimizationRequest, Placement, Plan, ResourcePool, Workload

MICRO_USD_PER_USD = 1_000_000


@dataclass(frozen=True)
class PlacementMetrics:
    cost_micro_usd: int
    energy_wh: int
    emissions_grams: int
    delay_minutes: int
    risk_units: int


def canonical_request_hash(request: OptimizationRequest) -> str:
    payload = request.model_dump(mode="json", by_alias=True, exclude_none=False)
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
    return hashlib.sha256(encoded).hexdigest()


def duration_slots(workload: Workload, slot_minutes: int) -> int:
    return math.ceil(workload.duration_minutes / slot_minutes)


def slot_index(request: OptimizationRequest, timestamp) -> int:
    minutes = int((timestamp - request.horizon.start).total_seconds() // 60)
    return minutes // request.horizon.slot_minutes


def placement_metrics(
    request: OptimizationRequest,
    workload: Workload,
    pool: ResourcePool,
    start_slot: int,
) -> PlacementMetrics:
    slot_minutes = request.horizon.slot_minutes
    remaining = workload.duration_minutes
    energy_wh = 0.0
    emissions_grams = 0.0
    current_slot = start_slot

    while remaining > 0:
        active_minutes = min(slot_minutes, remaining)
        slot_energy_kwh = workload.gpu_count * pool.gpu_power_kw * pool.pue * (active_minutes / 60)
        energy_wh += slot_energy_kwh * 1000
        emissions_grams += slot_energy_kwh * pool.carbon_grams_per_kwh_by_slot[current_slot]
        remaining -= active_minutes
        current_slot += 1

    cost_micro_usd = round(
        workload.gpu_count
        * workload.duration_minutes
        * pool.price_usd_per_gpu_hour
        * MICRO_USD_PER_USD
        / 60
    )
    earliest_slot = slot_index(request, workload.earliest_start)
    delay_minutes = max(0, (start_slot - earliest_slot) * slot_minutes)
    occupied_capacity = pool.capacity_by_slot[
        start_slot : start_slot + duration_slots(workload, slot_minutes)
    ]
    maximum_capacity = max(occupied_capacity)
    utilization_bps = round(workload.gpu_count / max(maximum_capacity, 1) * 10_000)
    availability_penalty_bps = 10_000 - pool.availability_bps

    return PlacementMetrics(
        cost_micro_usd=cost_micro_usd,
        energy_wh=round(energy_wh),
        emissions_grams=round(emissions_grams),
        delay_minutes=delay_minutes,
        # Availability is amplified because basis-point differences would otherwise
        # disappear beside utilization in the integer objective. This remains a
        # transparent scheduling heuristic, not a failure probability.
        risk_units=availability_penalty_bps * 20 + utilization_bps,
    )


def build_placement(
    request: OptimizationRequest,
    workload: Workload,
    pool: ResourcePool,
    start_slot: int,
    reasons: list[str],
) -> Placement:
    metrics = placement_metrics(request, workload, pool, start_slot)
    start = request.horizon.start + timedelta(minutes=start_slot * request.horizon.slot_minutes)
    end = start + timedelta(minutes=workload.duration_minutes)
    return Placement(
        workload_id=workload.id,
        pool_id=pool.id,
        start=start,
        end=end,
        gpu_count=workload.gpu_count,
        cost_usd=round(metrics.cost_micro_usd / MICRO_USD_PER_USD, 6),
        energy_kwh=round(metrics.energy_wh / 1000, 6),
        emissions_kg_co2e=round(metrics.emissions_grams / 1000, 6),
        delay_minutes=metrics.delay_minutes,
        reasons=reasons,
    )


def capacity_risk_score(request: OptimizationRequest, placements: list[Placement]) -> float:
    if not placements:
        return 0.0

    pool_map = {pool.id: pool for pool in request.resource_pools}
    workload_map = {workload.id: workload for workload in request.workloads}
    occupancy = {pool.id: [0] * request.horizon.slot_count for pool in request.resource_pools}
    availability_penalties: list[float] = []

    for placement in placements:
        workload = workload_map[placement.workload_id]
        pool = pool_map[placement.pool_id]
        start = slot_index(request, placement.start)
        for slot in range(start, start + duration_slots(workload, request.horizon.slot_minutes)):
            occupancy[pool.id][slot] += workload.gpu_count
        availability_penalties.append((10_000 - pool.availability_bps) / 100)

    peak_utilization = 0.0
    for pool in request.resource_pools:
        for slot, used in enumerate(occupancy[pool.id]):
            capacity = pool.capacity_by_slot[slot]
            if capacity:
                peak_utilization = max(peak_utilization, used / capacity * 100)

    average_availability_penalty = sum(availability_penalties) / len(availability_penalties)
    return round(peak_utilization * 0.8 + average_availability_penalty * 0.2, 2)


def build_plan(
    request: OptimizationRequest,
    placements: list[Placement],
    status: str,
) -> Plan:
    if not placements:
        return Plan(
            status=status,
            placements=[],
            total_cost_usd=None,
            total_energy_kwh=None,
            total_emissions_kg_co2e=None,
            total_delay_minutes=None,
            capacity_risk_score=None,
        )

    ordered = sorted(placements, key=lambda item: (item.start, item.workload_id))
    return Plan(
        status=status,
        placements=ordered,
        total_cost_usd=round(sum(item.cost_usd for item in ordered), 6),
        total_energy_kwh=round(sum(item.energy_kwh for item in ordered), 6),
        total_emissions_kg_co2e=round(sum(item.emissions_kg_co2e for item in ordered), 6),
        total_delay_minutes=sum(item.delay_minutes for item in ordered),
        capacity_risk_score=capacity_risk_score(request, ordered),
    )
