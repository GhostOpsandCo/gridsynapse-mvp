from __future__ import annotations

import os
from datetime import UTC, datetime
from pathlib import Path

from gridsynapse_contracts import OptimizationRequest


class ScenarioStore:
    def __init__(self, scenario_directory: Path | None = None) -> None:
        configured_directory = os.getenv("GRIDSYNAPSE_SCENARIO_DIRECTORY")
        source_repo_root = Path(__file__).resolve().parents[3]
        self.scenario_directory = (
            scenario_directory
            or (Path(configured_directory) if configured_directory else None)
            or Path.cwd() / "data" / "scenarios"
        )
        if not self.scenario_directory.exists():
            self.scenario_directory = source_repo_root / "data" / "scenarios"

    def list(self) -> list[dict]:
        summaries = []
        for path in sorted(self.scenario_directory.glob("*.json")):
            request = OptimizationRequest.model_validate_json(path.read_text())
            summaries.append(
                {
                    "scenarioId": request.scenario_id,
                    "workloadCount": len(request.workloads),
                    "resourcePoolCount": len(request.resource_pools),
                    "objectiveProfile": request.policy.profile,
                    "horizonStart": request.horizon.start.isoformat(),
                    "horizonEnd": request.horizon.end.isoformat(),
                    "sourceTypes": sorted(
                        {pool.source.source_type for pool in request.resource_pools}
                    ),
                }
            )
        return summaries

    def get(self, scenario_id: str) -> OptimizationRequest:
        for path in self.scenario_directory.glob("*.json"):
            request = OptimizationRequest.model_validate_json(path.read_text())
            if request.scenario_id == scenario_id:
                return request
        raise KeyError(scenario_id)

    def data_health(self, scenario_id: str, now: datetime | None = None) -> dict:
        return self.data_health_for(self.get(scenario_id), now=now)

    @staticmethod
    def data_health_for(request: OptimizationRequest, now: datetime | None = None) -> dict:
        current_time = now or datetime.now(UTC)
        sources = []
        stale_count = 0
        for pool in request.resource_pools:
            metric_sources = (
                [
                    ("price", pool.metric_sources.price),
                    ("carbon", pool.metric_sources.carbon),
                    ("capacity", pool.metric_sources.capacity),
                    ("latency", pool.metric_sources.latency),
                    ("availability", pool.metric_sources.availability),
                ]
                if pool.metric_sources
                else [("mixed", pool.source)]
            )
            for metric, source in metric_sources:
                age_seconds = max(0, int((current_time - source.observed_at).total_seconds()))
                stale = age_seconds > source.freshness_seconds
                stale_count += int(stale)
                sources.append(
                    {
                        "poolId": pool.id,
                        "metric": metric,
                        "sourceId": source.source_id,
                        "sourceType": source.source_type,
                        "sourceUrl": str(source.source_url) if source.source_url else None,
                        "unit": source.unit,
                        "observedAt": source.observed_at.isoformat(),
                        "ageSeconds": age_seconds,
                        "freshnessSeconds": source.freshness_seconds,
                        "confidence": source.confidence,
                        "stale": stale,
                    }
                )
        return {
            "scenarioId": request.scenario_id,
            "status": "stale" if stale_count else "healthy",
            "sourceCount": len(sources),
            "staleSourceCount": stale_count,
            "sources": sources,
        }
