from __future__ import annotations

from datetime import UTC, datetime

import httpx
import pytest
from gridsynapse_adapters import LiveMarketScenarioService, NesoCarbonAdapter, ScenarioStore
from gridsynapse_adapters.live_market import CarbonForecast, CatalogOffer, SkyPilotCatalogAdapter


def test_skypilot_catalog_selects_preferred_region_and_per_gpu_price():
    csv_body = """InstanceType,AcceleratorName,AcceleratorCount,Region,AvailabilityZone,Price
fallback-8x,A100-80GB,8,europe-west4,,16.00
preferred-8x,A100-80GB,8,us-central1,,20.00
preferred-1x,A100-80GB,1,us-central1,,3.00
other-gpu,H100,8,us-central1,,10.00
"""

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, text=csv_body, request=request)

    adapter = SkyPilotCatalogAdapter(httpx.Client(transport=httpx.MockTransport(handler)))
    offer = adapter.fetch_offer("gcp", "A100-80GB", ("us-central1",))

    assert offer.instance_type == "preferred-8x"
    assert offer.region == "us-central1"
    assert offer.price_usd_per_gpu_hour == 2.5


def test_neso_carbon_forecast_reads_and_pads_half_hour_values():
    start = datetime(2026, 7, 18, 4, 0, tzinfo=UTC)
    payload = {
        "data": [
            {
                "from": "2026-07-18T04:00Z",
                "to": "2026-07-18T04:30Z",
                "intensity": {"forecast": 91},
            },
            {
                "from": "2026-07-18T04:30Z",
                "to": "2026-07-18T05:00Z",
                "intensity": {"forecast": 87},
            },
        ]
    }

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=payload, request=request)

    adapter = NesoCarbonAdapter(httpx.Client(transport=httpx.MockTransport(handler)))
    forecast = adapter.fetch_forecast(start, slots=4, slot_minutes=30)

    assert forecast.values == [91, 87, 87, 87]
    with pytest.raises(ValueError, match="30-minute slots"):
        adapter.fetch_forecast(start, slots=4, slot_minutes=60)


class StubCatalog:
    prices = {"runpod": 1.39, "gcp": 1.85, "aws": 3.43, "azure": 3.67, "oci": 4.0}

    def fetch_offer(
        self,
        provider: str,
        gpu_type: str,
        preferred_regions: tuple[str, ...],
    ) -> CatalogOffer:
        return CatalogOffer(
            provider=provider,
            instance_type=f"{provider}-a100-80gb",
            accelerator_name=gpu_type,
            accelerator_count=1,
            region=preferred_regions[0],
            availability_zone=None,
            price_usd_per_gpu_hour=self.prices[provider],
            source_url=f"https://example.com/{provider}/vms.csv",
        )


class StubCarbon:
    def __init__(self, now: datetime) -> None:
        self.now = now

    def fetch_forecast(self, start: datetime, slots: int, slot_minutes: int) -> CarbonForecast:
        assert slot_minutes == 30
        return CarbonForecast(
            values=[82 + index for index in range(slots)],
            retrieved_at=self.now,
            source_url="https://api.carbonintensity.org.uk/intensity/test/fw24h",
        )


def test_live_market_scenario_is_current_source_aware_and_cached():
    now = datetime(2026, 7, 18, 4, 12, tzinfo=UTC)
    service = LiveMarketScenarioService(
        ScenarioStore(),
        catalog=StubCatalog(),  # type: ignore[arg-type]
        carbon=StubCarbon(now),  # type: ignore[arg-type]
        now=lambda: now,
    )

    first = service.snapshot()
    second = service.snapshot()
    scenario = first["scenario"]

    assert first is second
    assert first["marketMode"] == "hybrid-live"
    assert first["health"]["sourceCount"] == len(scenario["resourcePools"]) * 5
    assert scenario["horizon"]["start"] == "2026-07-18T04:00:00Z"
    assert {pool["provider"] for pool in scenario["resourcePools"]} == {
        "AWS",
        "Azure",
        "Google Cloud",
        "Oracle Cloud",
        "RunPod",
    }
    oracle = next(pool for pool in scenario["resourcePools"] if pool["provider"] == "Oracle Cloud")
    aws = next(pool for pool in scenario["resourcePools"] if pool["provider"] == "AWS")
    assert oracle["metricSources"]["carbon"]["sourceType"] == "forecast"
    assert aws["metricSources"]["carbon"]["sourceType"] == "estimated"
    assert aws["metricSources"]["capacity"]["unit"] == "modeled GPUs, not provider inventory"
    assert all(pool["capacityBySlot"] == [16] * 16 for pool in scenario["resourcePools"])


class FailingCarbon:
    def fetch_forecast(self, start: datetime, slots: int, slot_minutes: int) -> CarbonForecast:
        raise RuntimeError("forecast unavailable")


def test_live_market_falls_back_to_labeled_carbon_estimate():
    now = datetime(2026, 7, 18, 4, 0, tzinfo=UTC)
    service = LiveMarketScenarioService(
        ScenarioStore(),
        catalog=StubCatalog(),  # type: ignore[arg-type]
        carbon=FailingCarbon(),  # type: ignore[arg-type]
        now=lambda: now,
    )

    snapshot = service.snapshot()
    oracle = next(
        pool for pool in snapshot["scenario"]["resourcePools"] if pool["provider"] == "Oracle Cloud"
    )

    assert "NESO forecast unavailable" in snapshot["warnings"][0]
    assert oracle["metricSources"]["carbon"]["sourceType"] == "estimated"
