from __future__ import annotations

import csv
import io
import os
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

import httpx
from gridsynapse_contracts import (
    DataSourceRef,
    Horizon,
    OptimizationRequest,
    ResourceMetricSources,
    ResourcePool,
)

from .scenario_store import ScenarioStore

SKYPILOT_RAW_ROOT = (
    "https://raw.githubusercontent.com/skypilot-org/skypilot-catalog/master/catalogs/v8"
)
NESO_INTENSITY_ROOT = "https://api.carbonintensity.org.uk/intensity"


@dataclass(frozen=True)
class CatalogOffer:
    provider: str
    instance_type: str
    accelerator_name: str
    accelerator_count: int
    region: str
    availability_zone: str | None
    price_usd_per_gpu_hour: float
    source_url: str


@dataclass(frozen=True)
class CarbonForecast:
    values: list[int]
    retrieved_at: datetime
    source_url: str


@dataclass(frozen=True)
class ProviderSpec:
    catalog_id: str
    display_name: str
    preferred_regions: tuple[str, ...]
    latency_ms: int
    availability_bps: int
    pue: float
    estimated_carbon: int
    use_neso_carbon: bool = False


PROVIDER_SPECS = (
    ProviderSpec("runpod", "RunPod", ("US",), 28, 9850, 1.18, 290),
    ProviderSpec("gcp", "Google Cloud", ("us-central1",), 32, 9970, 1.10, 447),
    ProviderSpec("aws", "AWS", ("us-east-1",), 22, 9980, 1.12, 386),
    ProviderSpec("azure", "Azure", ("eastus",), 30, 9970, 1.15, 365),
    ProviderSpec("oci", "Oracle Cloud", ("uk-london-1",), 72, 9960, 1.14, 120, True),
)


class SkyPilotCatalogAdapter:
    """Read no-key catalog pricing published by the SkyPilot project."""

    def __init__(self, client: httpx.Client | None = None) -> None:
        self.client = client

    def fetch_offer(
        self,
        provider: str,
        gpu_type: str,
        preferred_regions: tuple[str, ...],
    ) -> CatalogOffer:
        source_url = f"{SKYPILOT_RAW_ROOT}/{provider}/vms.csv"
        response = self._get(source_url)
        candidates: list[tuple[int, float, CatalogOffer]] = []
        for row in csv.DictReader(io.StringIO(response.text)):
            if row.get("AcceleratorName") != gpu_type:
                continue
            try:
                accelerator_count = int(float(row.get("AcceleratorCount") or 0))
                total_price = float(row.get("Price") or 0)
            except ValueError:
                continue
            if accelerator_count <= 0 or total_price <= 0:
                continue
            region = row.get("Region") or "unknown"
            rank = (
                preferred_regions.index(region)
                if region in preferred_regions
                else len(preferred_regions) + 1
            )
            price_per_gpu = total_price / accelerator_count
            offer = CatalogOffer(
                provider=provider,
                instance_type=row.get("InstanceType") or f"{gpu_type}-{region}",
                accelerator_name=gpu_type,
                accelerator_count=accelerator_count,
                region=region,
                availability_zone=row.get("AvailabilityZone") or None,
                price_usd_per_gpu_hour=round(price_per_gpu, 6),
                source_url=source_url,
            )
            candidates.append((rank, price_per_gpu, offer))
        if not candidates:
            raise RuntimeError(f"No {gpu_type} catalog offer found for {provider}")
        return min(candidates, key=lambda item: (item[0], item[1], item[2].region))[2]

    def _get(self, url: str) -> httpx.Response:
        if self.client is not None:
            response = self.client.get(url)
        else:
            with httpx.Client(
                timeout=15,
                follow_redirects=True,
                headers={"User-Agent": "GridSynapse/2.0 live-market-adapter"},
            ) as client:
                response = client.get(url)
        response.raise_for_status()
        return response


class NesoCarbonAdapter:
    """Read the official, unauthenticated GB carbon-intensity forecast."""

    def __init__(self, client: httpx.Client | None = None) -> None:
        self.client = client

    def fetch_forecast(
        self,
        start: datetime,
        slots: int,
        slot_minutes: int,
    ) -> CarbonForecast:
        if slot_minutes != 30:
            raise ValueError("NESO forecast adapter currently requires 30-minute slots")
        request_start = start.astimezone(UTC).strftime("%Y-%m-%dT%H:%MZ")
        source_url = f"{NESO_INTENSITY_ROOT}/{request_start}/fw24h"
        response = self._get(source_url)
        values: list[int] = []
        for item in response.json().get("data", []):
            interval_start = datetime.fromisoformat(item["from"].replace("Z", "+00:00"))
            if interval_start < start:
                continue
            forecast = item.get("intensity", {}).get("forecast")
            if forecast is not None:
                values.append(int(forecast))
            if len(values) == slots:
                break
        if not values:
            raise RuntimeError("NESO returned no carbon forecast values")
        values.extend([values[-1]] * (slots - len(values)))
        return CarbonForecast(
            values=values,
            retrieved_at=datetime.now(UTC),
            source_url=source_url,
        )

    def _get(self, url: str) -> httpx.Response:
        if self.client is not None:
            response = self.client.get(url, headers={"Accept": "application/json"})
        else:
            with httpx.Client(timeout=10, follow_redirects=True) as client:
                response = client.get(url, headers={"Accept": "application/json"})
        response.raise_for_status()
        return response


class LiveMarketScenarioService:
    def __init__(
        self,
        scenario_store: ScenarioStore,
        catalog: SkyPilotCatalogAdapter | None = None,
        carbon: NesoCarbonAdapter | None = None,
        now: Callable[[], datetime] | None = None,
    ) -> None:
        self.scenario_store = scenario_store
        self.catalog = catalog or SkyPilotCatalogAdapter()
        self.carbon = carbon or NesoCarbonAdapter()
        self.now = now or (lambda: datetime.now(UTC))
        self.cache_seconds = int(os.getenv("GRIDSYNAPSE_LIVE_MARKET_CACHE_SECONDS", "1800"))
        self._cached_at: datetime | None = None
        self._cached_snapshot: dict | None = None

    def snapshot(self, force: bool = False) -> dict:
        now = self.now().astimezone(UTC)
        if (
            not force
            and self._cached_at
            and self._cached_snapshot
            and (now - self._cached_at).total_seconds() < self.cache_seconds
        ):
            return self._cached_snapshot

        scenario, warnings = self._build_scenario(now)
        snapshot = {
            "scenario": scenario.model_dump(mode="json", by_alias=True),
            "health": ScenarioStore.data_health_for(scenario, now=now),
            "generatedAt": now.isoformat(),
            "marketMode": "hybrid-live",
            "warnings": warnings,
            "sources": {
                "pricing": "SkyPilot public cloud catalog",
                "carbon": "NESO live forecast for GB; labeled estimates elsewhere",
                "capacity": "Modeled planning capacity",
            },
        }
        self._cached_at = now
        self._cached_snapshot = snapshot
        return snapshot

    def _build_scenario(self, now: datetime) -> tuple[OptimizationRequest, list[str]]:
        base = self.scenario_store.get("reference-cost-carbon-tradeoff-v1")
        horizon_start = now.replace(second=0, microsecond=0)
        horizon_start -= timedelta(minutes=horizon_start.minute % 30)
        horizon = Horizon(
            start=horizon_start,
            end=horizon_start + timedelta(hours=8),
            slot_minutes=30,
        )
        warnings: list[str] = []
        offers: list[tuple[ProviderSpec, CatalogOffer]] = []
        for spec in PROVIDER_SPECS:
            try:
                offers.append(
                    (
                        spec,
                        self.catalog.fetch_offer(
                            spec.catalog_id,
                            "A100-80GB",
                            spec.preferred_regions,
                        ),
                    )
                )
            except (httpx.HTTPError, RuntimeError) as error:
                warnings.append(f"{spec.display_name} catalog unavailable: {error}")
        if len(offers) < 2:
            raise RuntimeError("Live market requires at least two current catalog offers")

        neso_forecast: CarbonForecast | None = None
        try:
            neso_forecast = self.carbon.fetch_forecast(
                horizon.start,
                horizon.slot_count,
                horizon.slot_minutes,
            )
        except (httpx.HTTPError, RuntimeError, ValueError) as error:
            warnings.append(f"NESO forecast unavailable; GB estimate used: {error}")

        retrieved_at = now
        pools = [
            self._build_pool(spec, offer, horizon, retrieved_at, neso_forecast)
            for spec, offer in offers
        ]
        allowed_regions = [pool.region for pool in pools]
        baseline_pool = next(
            (pool.id for pool in pools if pool.provider == "AWS"),
            pools[0].id,
        )
        old_start = base.horizon.start
        workloads = []
        for workload in base.workloads:
            earliest_offset = workload.earliest_start - old_start
            deadline_offset = workload.deadline - old_start
            workloads.append(
                workload.model_copy(
                    update={
                        "earliest_start": horizon.start + earliest_offset,
                        "deadline": horizon.start + deadline_offset,
                        "allowed_regions": allowed_regions,
                        "baseline_pool_id": baseline_pool,
                    }
                )
            )
        scenario = base.model_copy(
            update={
                "scenario_id": f"live-a100-market-{horizon.start:%Y%m%dT%H%MZ}",
                "horizon": horizon,
                "workloads": workloads,
                "resource_pools": pools,
            }
        )
        return OptimizationRequest.model_validate(scenario.model_dump()), warnings

    @staticmethod
    def _build_pool(
        spec: ProviderSpec,
        offer: CatalogOffer,
        horizon: Horizon,
        retrieved_at: datetime,
        neso_forecast: CarbonForecast | None,
    ) -> ResourcePool:
        price_source = DataSourceRef(
            source_id=f"skypilot-catalog-{spec.catalog_id}",
            source_type="public_snapshot",
            source_url=offer.source_url,
            observed_at=retrieved_at,
            unit="USD per GPU-hour catalog price",
            freshness_seconds=8 * 60 * 60,
            confidence="high",
        )
        if spec.use_neso_carbon and neso_forecast:
            carbon_values = neso_forecast.values
            carbon_source = DataSourceRef(
                source_id="neso-gb-carbon-forecast",
                source_type="forecast",
                source_url=neso_forecast.source_url,
                observed_at=neso_forecast.retrieved_at,
                unit="gCO2e per kWh 30-minute forecast",
                freshness_seconds=60 * 60,
                confidence="high",
            )
        else:
            pattern = (0, 12, 24, 18, 6, -8, -15, -4)
            carbon_values = [
                max(1, spec.estimated_carbon + pattern[index % len(pattern)])
                for index in range(horizon.slot_count)
            ]
            carbon_source = DataSourceRef(
                source_id=f"regional-carbon-planning-estimate-{spec.catalog_id}",
                source_type="estimated",
                observed_at=retrieved_at,
                unit="gCO2e per kWh planning estimate",
                freshness_seconds=24 * 60 * 60,
                confidence="low",
            )
        capacity_source = DataSourceRef(
            source_id=f"modeled-capacity-{spec.catalog_id}",
            source_type="estimated",
            observed_at=retrieved_at,
            unit="modeled GPUs, not provider inventory",
            freshness_seconds=24 * 60 * 60,
            confidence="low",
        )
        latency_source = DataSourceRef(
            source_id=f"planning-latency-{spec.catalog_id}",
            source_type="estimated",
            observed_at=retrieved_at,
            unit="milliseconds planning estimate",
            freshness_seconds=24 * 60 * 60,
            confidence="low",
        )
        availability_source = DataSourceRef(
            source_id=f"planning-availability-{spec.catalog_id}",
            source_type="estimated",
            observed_at=retrieved_at,
            unit="basis-point planning estimate",
            freshness_seconds=24 * 60 * 60,
            confidence="low",
        )
        zone = offer.availability_zone or offer.region
        pool_id = f"pool-{spec.catalog_id}-{offer.region}-a100-80gb".lower()
        return ResourcePool(
            id=pool_id,
            provider=spec.display_name,
            cluster=f"{offer.instance_type} · {zone}",
            region=offer.region,
            gpu_type="A100-80GB",
            capacity_by_slot=[16] * horizon.slot_count,
            price_usd_per_gpu_hour=offer.price_usd_per_gpu_hour,
            gpu_power_kw=0.4,
            pue=spec.pue,
            carbon_grams_per_kwh_by_slot=carbon_values,
            latency_ms=spec.latency_ms,
            availability_bps=spec.availability_bps,
            egress_usd_per_gb=0,
            source=price_source,
            metric_sources=ResourceMetricSources(
                price=price_source,
                carbon=carbon_source,
                capacity=capacity_source,
                latency=latency_source,
                availability=availability_source,
            ),
        )
