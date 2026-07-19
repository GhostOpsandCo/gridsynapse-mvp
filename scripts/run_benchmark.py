#!/usr/bin/env python3
"""Run the reproducible GridSynapse v2 solver latency benchmark."""

from __future__ import annotations

import argparse
import json
import math
import platform
import statistics
import sys
import time
from datetime import UTC, datetime, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
for package_path in (
    "packages/contracts",
    "packages/optimizer",
):
    sys.path.insert(0, str(ROOT / package_path))

import ortools  # noqa: E402
from gridsynapse_contracts import (  # noqa: E402
    DataSourceRef,
    Horizon,
    ObjectiveWeights,
    OptimizationPolicy,
    OptimizationRequest,
    ResourcePool,
    Workload,
)
from gridsynapse_optimizer import optimize  # noqa: E402


def percentile(values: list[float], quantile: float) -> float:
    """Return a linearly interpolated percentile for a non-empty sample."""
    ordered = sorted(values)
    index = (len(ordered) - 1) * quantile
    lower = math.floor(index)
    upper = math.ceil(index)
    if lower == upper:
        return ordered[lower]
    return ordered[lower] + (ordered[upper] - ordered[lower]) * (index - lower)


def build_benchmark_request() -> OptimizationRequest:
    """Build the fixed 100-job, 6-pool, 96-slot engineering gate scenario."""
    start = datetime(2026, 7, 1, tzinfo=UTC)
    slot_minutes = 30
    slot_count = 96
    end = start + timedelta(minutes=slot_minutes * slot_count)
    regions = [
        "us-west-2",
        "us-east-1",
        "us-central-1",
        "eu-west-1",
        "eu-central-1",
        "ca-central-1",
    ]
    pools: list[ResourcePool] = []
    for index, region in enumerate(regions):
        carbon_base = (160, 280, 210, 95, 125, 70)[index]
        pools.append(
            ResourcePool(
                id=f"pool-{index + 1}",
                provider=("AWS", "GCP", "Azure")[index % 3],
                cluster=f"benchmark-h100-{index + 1}",
                region=region,
                gpu_type="H100",
                capacity_by_slot=[128 - (8 if slot % 24 in {7, 8, 9} else 0) for slot in range(96)],
                price_usd_per_gpu_hour=round(2.15 + index * 0.31, 2),
                gpu_power_kw=0.7,
                pue=round(1.12 + index * 0.025, 3),
                carbon_grams_per_kwh_by_slot=[
                    carbon_base + ((slot * 13 + index * 7) % 45) for slot in range(96)
                ],
                latency_ms=18 + index * 8,
                availability_bps=9990 - index * 5,
                source=DataSourceRef(
                    source_id=f"benchmark-source-{index + 1}",
                    source_type="synthetic",
                    observed_at=start,
                    unit="USD/GPU-hour and gCO2e/kWh",
                    freshness_seconds=86_400,
                    confidence="high",
                ),
            )
        )

    workloads: list[Workload] = []
    durations = (30, 60, 90, 120)
    gpu_counts = (1, 2, 4, 8)
    workload_types = ("batch_inference", "embeddings", "fine_tuning", "training")
    for index in range(100):
        earliest_slot = (index * 7) % 74
        duration = durations[index % len(durations)]
        required_slots = math.ceil(duration / slot_minutes)
        window_slots = 10 + (index % 5)
        deadline_slot = min(96, earliest_slot + required_slots + window_slots)
        workloads.append(
            Workload(
                id=f"job-{index + 1:03d}",
                name=f"AI workload {index + 1:03d}",
                workload_type=workload_types[index % len(workload_types)],
                gpu_type="H100",
                gpu_count=gpu_counts[index % len(gpu_counts)],
                duration_minutes=duration,
                earliest_start=start + timedelta(minutes=earliest_slot * slot_minutes),
                deadline=start + timedelta(minutes=deadline_slot * slot_minutes),
                priority=100 - index % 50,
                interruptible=index % 3 != 0,
                checkpointable=index % 4 != 0,
                allowed_regions=regions,
                max_latency_ms=80,
                baseline_pool_id="pool-1",
            )
        )

    return OptimizationRequest(
        schema_version="gridsynapse-optimization-request-v2",
        scenario_id="benchmark-100-jobs-6-pools-96-slots",
        horizon=Horizon(start=start, end=end, slot_minutes=slot_minutes),
        policy=OptimizationPolicy(
            profile="balanced",
            weights=ObjectiveWeights(
                cost_bps=3500,
                carbon_bps=3000,
                delay_bps=1500,
                risk_bps=2000,
            ),
            max_solver_seconds=2,
        ),
        workloads=workloads,
        resource_pools=pools,
    )


def run_benchmark(iterations: int, warmups: int) -> dict:
    request = build_benchmark_request()
    for _ in range(warmups):
        optimize(request)

    wall_times: list[float] = []
    solver_times: list[int] = []
    result = None
    for _ in range(iterations):
        started = time.perf_counter()
        result = optimize(request)
        wall_times.append((time.perf_counter() - started) * 1000)
        solver_times.append(result.solver.duration_ms)

    assert result is not None
    p95_wall = percentile(wall_times, 0.95)
    payload = {
        "benchmarkVersion": "gridsynapse-solver-benchmark-v1",
        "generatedAt": datetime.now(UTC).isoformat(),
        "engineeringGate": {
            "metric": "p95 end-to-end optimize(request) latency",
            "thresholdMs": 2000,
            "passed": p95_wall < 2000,
        },
        "scenario": {
            "scenarioId": request.scenario_id,
            "workloads": len(request.workloads),
            "resourcePools": len(request.resource_pools),
            "slots": request.horizon.slot_count,
            "candidateWindowSlots": "10-14 plus workload duration",
            "sourceType": "deterministic synthetic benchmark",
        },
        "runtime": {
            "python": platform.python_version(),
            "platform": platform.platform(),
            "processor": platform.processor() or "not reported",
            "ortools": ortools.__version__,
            "iterations": iterations,
            "warmups": warmups,
            "solverWorkers": 1,
            "solverSeed": 0,
        },
        "latencyMs": {
            "wall": {
                "min": round(min(wall_times), 2),
                "p50": round(statistics.median(wall_times), 2),
                "p95": round(p95_wall, 2),
                "max": round(max(wall_times), 2),
            },
            "reportedSolver": {
                "min": min(solver_times),
                "p50": round(statistics.median(solver_times), 2),
                "p95": round(percentile([float(value) for value in solver_times], 0.95), 2),
                "max": max(solver_times),
            },
        },
        "result": {
            "status": result.status,
            "validationPassed": result.validation.valid,
            "placements": len(result.optimized.placements),
            "recommendationId": result.recommendation_id,
        },
    }
    return payload


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--iterations", type=int, default=8)
    parser.add_argument("--warmups", type=int, default=1)
    parser.add_argument(
        "--output",
        type=Path,
        default=ROOT / "evidence" / "benchmarks" / "100-jobs-6-pools-96-slots.json",
    )
    args = parser.parse_args()
    payload = run_benchmark(args.iterations, args.warmups)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(payload, indent=2) + "\n")
    print(json.dumps(payload, indent=2))
    return 0 if payload["engineeringGate"]["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
