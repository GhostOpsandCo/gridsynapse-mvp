from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

from gridsynapse_adapters import ScenarioStore
from gridsynapse_contracts import ResourceMetricSources


def test_scenario_store_loads_explicit_directory(reference_request, tmp_path: Path):
    scenario_path = tmp_path / "scenario.json"
    scenario_path.write_text(reference_request.model_dump_json(by_alias=True))

    store = ScenarioStore(tmp_path)

    assert store.list()[0]["scenarioId"] == reference_request.scenario_id
    assert store.get(reference_request.scenario_id) == reference_request


def test_scenario_store_reports_stale_sources(reference_request, tmp_path: Path):
    scenario_path = tmp_path / "scenario.json"
    scenario_path.write_text(reference_request.model_dump_json(by_alias=True))
    store = ScenarioStore(tmp_path)

    health = store.data_health(
        reference_request.scenario_id,
        now=datetime(2030, 1, 1, tzinfo=UTC),
    )

    assert health["status"] == "stale"
    assert health["staleSourceCount"] == health["sourceCount"]


def test_data_health_reports_metric_level_sources(reference_request):
    request = reference_request.model_copy(deep=True)
    pool = request.resource_pools[0]
    pool.metric_sources = ResourceMetricSources(
        price=pool.source,
        carbon=pool.source,
        capacity=pool.source,
        latency=pool.source,
        availability=pool.source,
    )

    health = ScenarioStore.data_health_for(request, now=pool.source.observed_at)
    pool_sources = [source for source in health["sources"] if source["poolId"] == pool.id]

    assert {source["metric"] for source in pool_sources} == {
        "availability",
        "capacity",
        "carbon",
        "latency",
        "price",
    }
