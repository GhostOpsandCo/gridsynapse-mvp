# GridSynapse v2 Architecture and Implementation Scaffold

## 1. Architecture goals

The architecture must make three boundaries obvious:

1. **Data adapters observe conditions.** They do not decide placement.
2. **The deterministic optimizer decides the feasible schedule.** It does not write narrative.
3. **The AI explanation layer describes the result.** It cannot change allocations, constraints, or approvals.

This separation is the core credibility of GridSynapse.

## 2. Target system

```text
Next.js Operator Console
        |
        v
FastAPI Application API
        |
        +--> Scenario and provenance store (Postgres / local JSON in demo)
        +--> Data adapter layer
        |      +--> Workloads / Kueue adapter
        |      +--> Capacity / DCGM + scheduler adapter
        |      +--> Cost / OpenCost + FOCUS adapter
        |      +--> Carbon / snapshot + Carbon Aware adapter
        |
        +--> OR-Tools CP-SAT optimizer
        |      +--> baseline scheduler
        |      +--> optimized scheduler
        |      +--> independent result validator
        |
        +--> Explanation service (feature flagged)
        |      +--> deterministic template fallback
        |
        +--> Approval and export service
        |
        +--> Prometheus metrics / structured logs
```

## 3. Repository scaffold

The v2 implementation should converge on this structure. Existing files can be moved incrementally; the legacy dashboard stays available as visual reference until the new console replaces it.

```text
gridsynapse-mvp/
  apps/
    web/                         # Next.js operator console
      app/
      components/
      lib/api/
      tests/
  services/
    api/                         # FastAPI composition layer
      app/
        routers/
        services/
        repositories/
        telemetry/
      tests/
  packages/
    contracts/                   # Pydantic + generated TypeScript contracts
    optimizer/                   # CP-SAT model, baseline, validator, benchmarks
    adapters/                    # workload/capacity/cost/carbon implementations
    explanations/                # schemas, deterministic fallback, optional LLM
  data/
    scenarios/
    snapshots/
      carbon/
      prices/
  docs/v2/
  infra/
    docker/
    prometheus/
  scripts/
    validate_scenario.py
    run_benchmark.py
    export_contracts.py
```

### Migration rule

Do not create every service at once. Build a vertical slice in this order:

`contracts -> optimizer -> result validator -> API -> console -> explanation -> adapters`

## 4. Canonical domain objects

### Workload

```python
class Workload(BaseModel):
    id: str
    name: str
    workload_type: Literal["training", "fine_tuning", "embeddings", "batch_inference"]
    gpu_type: str
    gpu_count: int
    duration_minutes: int
    earliest_start: datetime
    deadline: datetime
    priority: int
    interruptible: bool
    checkpointable: bool
    allowed_regions: list[str]
    max_latency_ms: int | None
    max_budget_usd: Decimal | None
    baseline_pool_id: str | None
```

### ResourcePoolSnapshot

```python
class ResourcePoolSnapshot(BaseModel):
    id: str
    provider: str
    cluster: str
    region: str
    gpu_type: str
    capacity_by_slot: list[int]
    price_microusd_per_gpu_hour: int
    gpu_power_milliwatts: int
    pue_milli: int
    carbon_grams_per_kwh_by_slot: list[int]
    latency_ms: int
    availability_basis_points: int
    source: DataSourceRef
```

### OptimizationPolicy

```python
class OptimizationPolicy(BaseModel):
    profile: Literal["cost", "balanced", "carbon", "sla"]
    cost_weight_bps: int
    carbon_weight_bps: int
    delay_weight_bps: int
    risk_weight_bps: int
    slot_minutes: int
    max_solver_seconds: int
```

### OptimizationResult

The result must include:

- request and recommendation IDs;
- solver version and input hash;
- baseline and optimized placements;
- aggregate cost, emissions, delay, and risk;
- normalized objective components;
- per-workload reasons and binding constraints;
- infeasible workloads and reasons;
- provenance and freshness summary;
- approval state.

The JSON schemas in `docs/v2/contracts` are the initial language-neutral contract. Pydantic models become the executable source of truth during implementation.

## 5. Units and integer safety

CP-SAT operates on integers. V2 uses explicit integer units:

| Quantity | Internal unit |
| --- | --- |
| Time | integer slot index |
| Money | micro-USD |
| Energy | watt-hours |
| Carbon | grams CO2e |
| PUE | thousandths (`1200` = 1.2) |
| Availability | basis points |
| Objective weights | basis points |

Conversions happen at contract boundaries, never implicitly inside objective expressions.

## 6. Solver model

### Backend

Use OR-Tools **CP-SAT**, not GLOP. GLOP is a continuous linear solver and does not provide the integer scheduling semantics required here.

### Time model

- Initial slot size: 30 minutes.
- `duration_slots = ceil(duration_minutes / slot_minutes)`.
- A placement variable represents one workload, one compatible pool, and one valid start slot.
- Variables are created only for starts where the workload can finish before its deadline and inside the scenario horizon.

### Decision variable

```text
x[workload, pool, start_slot] in {0, 1}
```

### Hard constraints

1. Each accepted workload is scheduled exactly once.
2. Per-pool GPU capacity is not exceeded in any slot.
3. Pool GPU type matches workload GPU type.
4. Start is at or after earliest start.
5. End is at or before deadline.
6. Pool region is in workload allowlist.
7. Pool latency is within workload maximum when provided.
8. Placement cost does not exceed workload budget when provided.
9. Non-checkpointable jobs cannot be split.
10. Missing required source data blocks the affected placement.

### Cost calculation

```text
gpu_hours = gpu_count * duration_minutes / 60
placement_cost_usd = gpu_hours * price_usd_per_gpu_hour + egress_cost_usd
```

The CP-SAT implementation uses integer micro-USD values calculated from slot duration.

### Emissions calculation

```text
energy_kwh = gpu_count * gpu_power_kw * duration_hours * PUE
emissions_kg_co2e = energy_kwh * carbon_g_co2e_per_kwh / 1000
```

Carbon intensity can vary by slot. A multi-slot workload sums slot-level energy and carbon.

### Delay calculation

```text
delay_minutes = scheduled_start - earliest_start
```

### Capacity-risk calculation

V2 uses a transparent heuristic based on availability confidence and post-placement headroom. It must not be labeled a failure probability.

### Objective normalization

Raw dollars, grams, minutes, and risk scores cannot be summed directly. For each feasible placement component:

```text
normalized_component = component / max(reference_component, epsilon)
```

The reference is the named baseline total for the same workload set. If the baseline is infeasible, the result must disclose the alternate normalization method.

```text
score =
  cost_weight * normalized_cost
  + carbon_weight * normalized_carbon
  + delay_weight * normalized_delay
  + risk_weight * normalized_capacity_risk
```

The response returns every component so the score is auditable.

## 7. Baseline scheduler

Savings claims are meaningless without a baseline. V2 baseline policy:

1. Use the workload's `baselinePoolId` when supplied.
2. Otherwise choose the first compatible preferred/default pool.
3. Start at the earliest feasible slot.
4. Apply the same hard constraints and calculation functions used by the optimizer.

If the baseline cannot schedule a workload, return `baselineStatus: infeasible` and do not publish percentage savings for that workload.

## 8. Independent result validator

Do not trust the solver response alone. A separate pure function must recalculate:

- exactly-once placement;
- capacity by slot;
- time-window and deadline compliance;
- GPU, region, latency, and budget compatibility;
- cost, energy, and carbon totals;
- input/result hash consistency.

The API refuses to mark a result valid if this validator fails.

## 9. API surface

### Scenario and data

```text
GET  /api/v2/scenarios
GET  /api/v2/scenarios/{scenario_id}
POST /api/v2/scenarios/validate
GET  /api/v2/workloads
GET  /api/v2/resource-pools
GET  /api/v2/data-health
```

### Optimization

```text
POST /api/v2/optimizations
GET  /api/v2/optimizations/{recommendation_id}
POST /api/v2/optimizations/{recommendation_id}/explain
POST /api/v2/optimizations/{recommendation_id}/approve
POST /api/v2/optimizations/{recommendation_id}/export
```

### Operations

```text
GET /api/v2/health
GET /metrics
```

`POST /api/v2/optimizations` can run synchronously for the initial benchmark-sized demo. Introduce a queue only when measured solve time or concurrency requires it.

## 10. Adapter interfaces

```python
class WorkloadProvider(Protocol):
    def list_workloads(self, at: datetime) -> list[Workload]: ...

class CapacityProvider(Protocol):
    def get_capacity(self, horizon: TimeHorizon) -> list[CapacitySnapshot]: ...

class CostProvider(Protocol):
    def get_prices(self, horizon: TimeHorizon) -> list[PriceSnapshot]: ...

class CarbonProvider(Protocol):
    def get_carbon(self, horizon: TimeHorizon) -> list[CarbonSnapshot]: ...

class TelemetryProvider(Protocol):
    def get_utilization(self, horizon: TimeHorizon) -> list[TelemetrySnapshot]: ...

class ScheduleProvider(Protocol):
    def export_plan(self, result: OptimizationResult) -> ExportReceipt: ...
```

### V2 demo adapters

- `ScenarioJsonWorkloadProvider`
- `ScenarioJsonCapacityProvider`
- `StaticPricingProvider`
- `CarbonSnapshotProvider`
- `ReadOnlyJsonScheduleProvider`

### Production-path adapters

- Kubernetes Kueue for workload and queue state.
- NVIDIA DCGM Exporter for GPU telemetry.
- OpenCost/FOCUS for cost allocation and normalized billing data.
- Carbon Aware SDK or timestamped EIA-derived feeds for carbon signals.

Adapter names must identify whether data is observed, contract-priced, estimated, or synthetic.

## 11. AI explanation contract

### Input

The model receives a structured, read-only packet:

- workloads and hard constraints;
- baseline and optimized placements;
- objective profile and components;
- binding constraints;
- alternative feasible placements;
- provenance and freshness warnings.

### Output

```json
{
  "summary": "string",
  "placementReasons": [
    {"workloadId": "string", "reason": "string", "evidence": ["string"]}
  ],
  "tradeoffs": ["string"],
  "risks": ["string"],
  "operatorActions": ["string"],
  "sourceRefs": ["string"]
}
```

### Guardrails

- The explanation cannot introduce a pool or value absent from the result.
- Every numerical sentence must be derivable from structured fields.
- Missing or invalid AI output falls back to deterministic templates.
- Prompt/model/version and response validation status are logged.
- No fine-tuning or customer-data training in v2.

## 12. Operator console structure

Use the legacy dashboard's strongest qualities: quiet dark/light contrast, meters, compact status, and real-time feel. Replace decorative/random telemetry with task-oriented modules:

- persistent navigation: Brief, Workloads, Resources, Optimize, Results, Evidence;
- top status: scenario, data freshness, solver version;
- queue with one obvious next action;
- resource matrix with aligned units;
- segmented objective control;
- stable timeline dimensions;
- baseline and optimized result comparison;
- explanation and approval below the result, not beside every input.

No marketing hero belongs inside the console.

## 13. Data provenance

```python
class DataSourceRef(BaseModel):
    source_id: str
    source_type: Literal["observed", "contract", "public_snapshot", "estimated", "synthetic"]
    source_url: str | None
    observed_at: datetime
    imported_at: datetime
    unit: str
    freshness_seconds: int
    confidence: Literal["high", "medium", "low"]
```

The UI shows stale status when `now - observed_at > freshness_seconds`.

## 14. Persistence and state

### Demo

- Versioned scenario files in Git.
- In-memory or SQLite result storage for local development.
- Optional Postgres for deployed recommendation history.

### Later

- Postgres for scenarios, recommendation metadata, approvals, and audit events.
- Object storage for imported snapshots and exports.
- Redis only for measured caching/queue needs, not as a mandatory startup dependency.

## 15. Observability

Prometheus metrics:

- `gridsynapse_optimization_requests_total`
- `gridsynapse_optimization_duration_seconds`
- `gridsynapse_optimization_feasible_total`
- `gridsynapse_optimization_infeasible_total`
- `gridsynapse_adapter_freshness_seconds`
- `gridsynapse_explanation_validation_failures_total`
- `gridsynapse_result_validation_failures_total`

Structured logs include request ID, scenario ID, recommendation ID, input hash, solver version, duration, and status. They exclude secrets and raw customer payloads.

## 16. Security and execution boundary

- Public portfolio deployment uses synthetic scenario data only.
- No cloud credentials, scheduler credentials, or customer job payloads in the browser.
- Rate-limit optimization endpoints.
- Validate file imports and cap scenario size.
- No arbitrary code or solver expression from user input.
- Exports are recommendations, not autonomous scheduler commands.
- Production adapters later require OIDC, RBAC, tenant isolation, secrets management, and audit retention.

## 17. Deployment shape

- `gridsynapse.io`: Next.js web console on Vercel.
- `api.gridsynapse.io`: FastAPI + OR-Tools container on a long-running container platform.
- Scenario data and static snapshots: versioned with the API or object storage.
- Preview environment for each pull request.
- Production deploy only after contracts, solver invariants, browser QA, and benchmark gate pass.

GitHub Pages is not appropriate for the v2 product because the optimization API and future adapters require a server runtime.

## 18. Current official integration references

- Kubernetes Kueue: job admission, queues, resource flavors, fair sharing, and integrations: <https://kueue.sigs.k8s.io/>
- NVIDIA DCGM Exporter: Prometheus GPU telemetry: <https://docs.nvidia.com/datacenter/cloud-native/gpu-telemetry/dcgm-exporter.html>
- OpenCost: Kubernetes/GPU allocation and AI inference cost tracking: <https://www.opencost.io/>
- FinOps FOCUS: vendor-neutral cost and usage schema: <https://focus.finops.org/>
- Carbon Aware SDK: time/location shifting using carbon-intensity data: <https://github.com/Green-Software-Foundation/carbon-aware-sdk>
- EIA Open Data: official energy datasets and API: <https://www.eia.gov/opendata/>
- OR-Tools CP-SAT: integer constraint solver: <https://developers.google.com/optimization/cp/cp_solver>
