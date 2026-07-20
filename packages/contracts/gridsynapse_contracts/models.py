from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, HttpUrl, model_validator


def to_camel(value: str) -> str:
    first, *rest = value.split("_")
    return first + "".join(part.capitalize() for part in rest)


class ContractModel(BaseModel):
    model_config = ConfigDict(
        alias_generator=to_camel,
        populate_by_name=True,
        extra="forbid",
        str_strip_whitespace=True,
    )


class DataSourceRef(ContractModel):
    source_id: str
    source_type: Literal[
        "observed",
        "forecast",
        "contract",
        "public_snapshot",
        "estimated",
        "synthetic",
    ]
    source_url: HttpUrl | None = None
    observed_at: datetime
    unit: str
    freshness_seconds: Annotated[int, Field(ge=0)]
    confidence: Literal["high", "medium", "low"]


class ResourceMetricSources(ContractModel):
    price: DataSourceRef
    carbon: DataSourceRef
    capacity: DataSourceRef
    latency: DataSourceRef
    availability: DataSourceRef


class Horizon(ContractModel):
    start: datetime
    end: datetime
    slot_minutes: Literal[15, 30, 60]

    @model_validator(mode="after")
    def validate_window(self) -> Horizon:
        if self.end <= self.start:
            raise ValueError("horizon end must be after start")
        total_minutes = int((self.end - self.start).total_seconds() // 60)
        if total_minutes % self.slot_minutes:
            raise ValueError("horizon must contain a whole number of slots")
        return self

    @property
    def slot_count(self) -> int:
        return int((self.end - self.start).total_seconds() // 60) // self.slot_minutes


class ObjectiveWeights(ContractModel):
    cost_bps: Annotated[int, Field(ge=0, le=10_000)]
    carbon_bps: Annotated[int, Field(ge=0, le=10_000)]
    delay_bps: Annotated[int, Field(ge=0, le=10_000)]
    risk_bps: Annotated[int, Field(ge=0, le=10_000)]

    @model_validator(mode="after")
    def validate_total(self) -> ObjectiveWeights:
        total = self.cost_bps + self.carbon_bps + self.delay_bps + self.risk_bps
        if total != 10_000:
            raise ValueError(f"objective weights must sum to 10000 bps, got {total}")
        return self


class OptimizationPolicy(ContractModel):
    profile: Literal["cost", "balanced", "carbon", "sla"]
    weights: ObjectiveWeights
    max_solver_seconds: Annotated[int, Field(ge=1, le=60)] = 5


class Workload(ContractModel):
    id: str
    name: str
    workload_type: Literal["training", "fine_tuning", "embeddings", "batch_inference"]
    gpu_type: str
    gpu_count: Annotated[int, Field(ge=1)]
    duration_minutes: Annotated[int, Field(ge=1)]
    earliest_start: datetime
    deadline: datetime
    priority: Annotated[int, Field(ge=1, le=100)]
    interruptible: bool
    checkpointable: bool
    allowed_regions: Annotated[list[str], Field(min_length=1)]
    max_latency_ms: Annotated[int, Field(ge=0)] | None = None
    max_budget_usd: Annotated[float, Field(ge=0)] | None = None
    baseline_pool_id: str | None = None

    @model_validator(mode="after")
    def validate_window(self) -> Workload:
        if self.deadline <= self.earliest_start:
            raise ValueError(f"workload {self.id} deadline must be after earliest start")
        return self


class ResourcePool(ContractModel):
    id: str
    provider: str
    cluster: str
    region: str
    gpu_type: str
    capacity_by_slot: Annotated[list[int], Field(min_length=1)]
    price_usd_per_gpu_hour: Annotated[float, Field(ge=0)]
    gpu_power_kw: Annotated[float, Field(gt=0)]
    pue: Annotated[float, Field(ge=1)]
    carbon_grams_per_kwh_by_slot: Annotated[list[int], Field(min_length=1)]
    latency_ms: Annotated[int, Field(ge=0)]
    availability_bps: Annotated[int, Field(ge=0, le=10_000)]
    egress_usd_per_gb: Annotated[float, Field(ge=0)] = 0
    source: DataSourceRef
    metric_sources: ResourceMetricSources | None = None

    @model_validator(mode="after")
    def validate_slots(self) -> ResourcePool:
        if len(self.capacity_by_slot) != len(self.carbon_grams_per_kwh_by_slot):
            raise ValueError(f"pool {self.id} capacity and carbon arrays must have equal length")
        if any(value < 0 for value in self.capacity_by_slot):
            raise ValueError(f"pool {self.id} capacity cannot be negative")
        if any(value < 0 for value in self.carbon_grams_per_kwh_by_slot):
            raise ValueError(f"pool {self.id} carbon intensity cannot be negative")
        return self


class OptimizationRequest(ContractModel):
    schema_version: Literal["gridsynapse-optimization-request-v2"]
    scenario_id: str
    horizon: Horizon
    policy: OptimizationPolicy
    workloads: Annotated[list[Workload], Field(min_length=1)]
    resource_pools: Annotated[list[ResourcePool], Field(min_length=1)]

    @model_validator(mode="after")
    def validate_request(self) -> OptimizationRequest:
        workload_ids = [workload.id for workload in self.workloads]
        pool_ids = [pool.id for pool in self.resource_pools]
        if len(workload_ids) != len(set(workload_ids)):
            raise ValueError("workload IDs must be unique")
        if len(pool_ids) != len(set(pool_ids)):
            raise ValueError("resource pool IDs must be unique")
        for pool in self.resource_pools:
            if len(pool.capacity_by_slot) != self.horizon.slot_count:
                raise ValueError(
                    f"pool {pool.id} has {len(pool.capacity_by_slot)} slots; "
                    f"horizon requires {self.horizon.slot_count}"
                )
        for workload in self.workloads:
            if workload.earliest_start < self.horizon.start or workload.deadline > self.horizon.end:
                raise ValueError(f"workload {workload.id} must fit inside the horizon")
        return self


class Placement(ContractModel):
    workload_id: str
    pool_id: str
    start: datetime
    end: datetime
    gpu_count: Annotated[int, Field(ge=1)]
    cost_usd: Annotated[float, Field(ge=0)]
    energy_kwh: Annotated[float, Field(ge=0)]
    emissions_kg_co2e: Annotated[float, Field(ge=0)]
    delay_minutes: Annotated[int, Field(ge=0)]
    reasons: list[str]


class Plan(ContractModel):
    status: Literal["feasible", "partial", "infeasible"]
    placements: list[Placement]
    total_cost_usd: Annotated[float, Field(ge=0)] | None
    total_energy_kwh: Annotated[float, Field(ge=0)] | None
    total_emissions_kg_co2e: Annotated[float, Field(ge=0)] | None
    total_delay_minutes: Annotated[int, Field(ge=0)] | None
    capacity_risk_score: Annotated[float, Field(ge=0)] | None


class Deltas(ContractModel):
    cost_usd: float | None
    cost_percent: float | None
    emissions_kg_co2e: float | None
    emissions_percent: float | None
    delay_minutes: int | None


class ValidationSummary(ContractModel):
    valid: bool
    checks: list[str]


class ApprovalState(ContractModel):
    status: Literal["not_reviewed", "approved", "revision_required", "invalidated"]
    approved_by: str | None = None
    approved_at: datetime | None = None


class ApprovalUpdate(ContractModel):
    status: Literal["approved", "revision_required"]
    actor: str


class SolverMetadata(ContractModel):
    backend: Literal["ortools-cp-sat"] = "ortools-cp-sat"
    version: str
    duration_ms: Annotated[int, Field(ge=0)]
    objective_profile: Literal["cost", "balanced", "carbon", "sla"]


class OptimizationResult(ContractModel):
    schema_version: Literal["gridsynapse-optimization-result-v2"]
    recommendation_id: str
    scenario_id: str
    status: Literal["feasible", "partial", "infeasible", "error"]
    input_hash: str
    solver: SolverMetadata
    baseline: Plan
    optimized: Plan
    deltas: Deltas
    infeasible_reasons: list[str] = Field(default_factory=list)
    validation: ValidationSummary
    approval: ApprovalState


class OfferSnapshot(ContractModel):
    offer_id: str
    provider: str
    pool_id: str
    region: str
    gpu_type: str
    price_usd_per_gpu_hour: Annotated[float, Field(ge=0)]
    currency: Literal["USD"] = "USD"
    price_classification: Literal["planning_only", "account_specific_quote"]
    inventory_classification: Literal[
        "modeled_not_executable",
        "verified_executable",
    ]
    price_evidence: DataSourceRef
    capacity_evidence: DataSourceRef
    captured_at: datetime
    executable_inventory: bool = False
    evidence_notes: list[str] = Field(default_factory=list)


class ExecutableWorkloadSpec(ContractModel):
    workload_id: str
    container_image: Annotated[str, Field(min_length=1)]
    command: Annotated[list[str], Field(min_length=1)]
    working_directory: str | None = None
    environment: dict[str, str] = Field(default_factory=dict)
    secret_refs: list[str] = Field(default_factory=list)
    storage_mounts: dict[str, str] = Field(default_factory=dict)
    checkpoint_uri: str | None = None
    retry_limit: Annotated[int, Field(ge=0, le=10)] = 0
    cleanup_policy: Literal["delete_compute", "retain_storage"] = "delete_compute"


class ProcurementPlacement(ContractModel):
    placement_id: str
    workload_id: str
    pool_id: str
    provider: str
    region: str
    gpu_type: str
    gpu_count: Annotated[int, Field(ge=1)]
    start: datetime
    end: datetime
    estimated_cost_usd: Annotated[float, Field(ge=0)]
    workload_spec: ExecutableWorkloadSpec
    offer: OfferSnapshot
    skypilot_task_yaml: str


class VerificationCheck(ContractModel):
    check_id: str
    passed: bool
    severity: Literal["blocking", "warning", "information"]
    message: str


class VerificationRecord(ContractModel):
    verification_id: str
    procurement_plan_id: str
    verified_at: datetime
    valid_for_dry_run: bool
    live_launch_allowed: bool = False
    mode: Literal["portfolio_dry_run"] = "portfolio_dry_run"
    checks: list[VerificationCheck]
    blocking_reasons: list[str] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    evidence_hash: str


class ProcurementStatus(StrEnum):
    CREATED = "created"
    VERIFICATION_FAILED = "verification_failed"
    DRY_RUN_READY = "dry_run_ready"
    APPROVED_FOR_LAUNCH = "approved_for_launch"
    PROVISIONING = "provisioning"
    RUNNING = "running"
    COMPLETED = "completed"
    RECONCILED = "reconciled"


class ReconciliationReport(ContractModel):
    reconciliation_id: str
    procurement_plan_id: str
    estimated_total_cost_usd: Annotated[float, Field(ge=0)]
    simulated_actual_cost_usd: Annotated[float, Field(ge=0)]
    variance_usd: float
    variance_percent: float | None
    workload_count: Annotated[int, Field(ge=0)]
    completed_workload_count: Annotated[int, Field(ge=0)]
    provenance: Literal["deterministic_portfolio_simulation"] = "deterministic_portfolio_simulation"
    methodology: str
    reconciled_at: datetime


class ProcurementPlan(ContractModel):
    schema_version: Literal["gridsynapse-procurement-plan-v1"]
    procurement_plan_id: str
    recommendation_id: str
    scenario_id: str
    input_hash: str
    idempotency_key: str
    mode: Literal["portfolio_dry_run"] = "portfolio_dry_run"
    status: ProcurementStatus
    requested_by: str
    max_spend_usd: Annotated[float, Field(gt=0)]
    estimated_total_cost_usd: Annotated[float, Field(ge=0)]
    currency: Literal["USD"] = "USD"
    placements: Annotated[list[ProcurementPlacement], Field(min_length=1)]
    skypilot_manifest_yaml: str
    verification: VerificationRecord | None = None
    reconciliation: ReconciliationReport | None = None
    simulation_only: Literal[True] = True
    live_execution_permitted: Literal[False] = False
    provider_credentials_present: Literal[False] = False
    execution_boundary: str
    created_at: datetime
    updated_at: datetime


class ProcurementCreateRequest(ContractModel):
    recommendation_id: str
    expected_input_hash: str
    requested_by: str
    max_spend_usd: Annotated[float, Field(gt=0)]
    workload_specs: Annotated[list[ExecutableWorkloadSpec], Field(min_length=1)]


class ProcurementAction(StrEnum):
    APPROVE_FOR_LAUNCH = "approve_for_launch"
    START_PROVISIONING = "start_provisioning"
    MARK_RUNNING = "mark_running"
    MARK_COMPLETED = "mark_completed"
    RECONCILE = "reconcile"


class ProcurementTransitionRequest(ContractModel):
    action: ProcurementAction
    actor: str
    simulation: bool = False
    simulated_actual_cost_usd: Annotated[float, Field(ge=0)] | None = None


class Explanation(ContractModel):
    recommendation_id: str
    headline: str
    summary: str
    decision_factors: list[str]
    tradeoffs: list[str]
    warnings: list[str]
    operator_action: str
    generated_by: Literal["deterministic-template"] = "deterministic-template"
