from __future__ import annotations

import hashlib
import json
import os
import re
import shlex
from collections.abc import Callable
from copy import deepcopy
from datetime import UTC, datetime, timedelta
from typing import Literal

from gridsynapse_contracts import (
    DataSourceRef,
    ExecutableWorkloadSpec,
    OfferSnapshot,
    OptimizationRequest,
    OptimizationResult,
    ProcurementAction,
    ProcurementCreateRequest,
    ProcurementPlacement,
    ProcurementPlan,
    ProcurementStatus,
    ProcurementTransitionRequest,
    ReconciliationReport,
    VerificationCheck,
    VerificationRecord,
)

EXECUTION_BOUNDARY = (
    "Portfolio mode generates inspectable SkyPilot planning artifacts and simulated state "
    "transitions only. GridSynapse does not contact providers, reserve inventory, launch "
    "compute, or create billable resources."
)


class ProcurementDisabledError(RuntimeError):
    pass


class ProcurementNotFoundError(KeyError):
    pass


class InvalidProcurementPlanError(ValueError):
    pass


class ProcurementTransitionError(ValueError):
    pass


def _flag(name: str, default: bool) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


def _stable_hash(payload: object) -> str:
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str).encode()
    return hashlib.sha256(encoded).hexdigest()


def _canonical_request_hash(request: OptimizationRequest) -> str:
    return _stable_hash(request.model_dump(mode="json", by_alias=True, exclude_none=False))


def _slug(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", value.lower()).strip("-") or "provider"


def _skypilot_cloud(provider: str) -> str:
    canonical = {
        "amazon web services": "aws",
        "aws": "aws",
        "azure": "azure",
        "gcp": "gcp",
        "google cloud": "gcp",
        "google cloud platform": "gcp",
        "oci": "oci",
        "oracle cloud": "oci",
        "runpod": "runpod",
    }
    normalized = provider.strip().lower()
    return canonical.get(normalized, _slug(provider))


def _yaml_string(value: str) -> str:
    return json.dumps(value)


def _source_is_fresh(source: DataSourceRef, now: datetime) -> bool:
    return now <= source.observed_at + timedelta(seconds=source.freshness_seconds)


def _source_age_seconds(source: DataSourceRef, now: datetime) -> int:
    return max(0, round((now - source.observed_at).total_seconds()))


class ProcurementService:
    """Build and simulate procurement plans without contacting a compute provider."""

    def __init__(
        self,
        *,
        procurement_enabled: bool | None = None,
        execution_enabled: bool | None = None,
        now: Callable[[], datetime] | None = None,
    ) -> None:
        self.procurement_enabled = (
            _flag("GRIDSYNAPSE_PROCUREMENT_ENABLED", True)
            if procurement_enabled is None
            else procurement_enabled
        )
        self.execution_enabled = (
            _flag("GRIDSYNAPSE_EXECUTION_ENABLED", False)
            if execution_enabled is None
            else execution_enabled
        )
        self._now = now or (lambda: datetime.now(UTC))
        self._plans: dict[str, ProcurementPlan] = {}
        self._contexts: dict[
            str,
            tuple[OptimizationRequest, OptimizationResult, ProcurementCreateRequest],
        ] = {}

    def create_plan(
        self,
        request: OptimizationRequest,
        result: OptimizationResult,
        create: ProcurementCreateRequest,
    ) -> ProcurementPlan:
        self._require_enabled()
        self._validate_recommendation(request, result, create)

        specs = {spec.workload_id: spec for spec in create.workload_specs}
        if len(specs) != len(create.workload_specs):
            raise InvalidProcurementPlanError("Executable workload IDs must be unique")
        placement_workload_ids = {item.workload_id for item in result.optimized.placements}
        missing = sorted(placement_workload_ids - set(specs))
        extras = sorted(set(specs) - placement_workload_ids)
        if missing:
            raise InvalidProcurementPlanError(
                f"Executable workload specs are missing for: {', '.join(missing)}"
            )
        if extras:
            raise InvalidProcurementPlanError(
                "Executable workload specs are not part of the approved placement set: "
                + ", ".join(extras)
            )

        identity_payload = {
            "recommendationId": result.recommendation_id,
            "inputHash": result.input_hash,
            "maxSpendUsd": create.max_spend_usd,
            "workloadSpecs": [
                item.model_dump(mode="json", by_alias=True)
                for item in sorted(create.workload_specs, key=lambda item: item.workload_id)
            ],
        }
        identity_hash = _stable_hash(identity_payload)
        plan_id = f"proc-{identity_hash[:16]}"
        if plan_id in self._plans:
            return deepcopy(self._plans[plan_id])

        now = self._now()
        pool_map = {pool.id: pool for pool in request.resource_pools}
        placements: list[ProcurementPlacement] = []
        task_documents: list[str] = []
        for index, placement in enumerate(result.optimized.placements, start=1):
            pool = pool_map[placement.pool_id]
            offer = self._offer_snapshot(pool, now)
            placement_id = f"{plan_id}-placement-{index:03d}"
            task_yaml = self._skypilot_task_yaml(
                placement_id,
                placement,
                pool.provider,
                pool.region,
                pool.gpu_type,
                specs[placement.workload_id],
            )
            task_documents.append(task_yaml)
            placements.append(
                ProcurementPlacement(
                    placement_id=placement_id,
                    workload_id=placement.workload_id,
                    pool_id=placement.pool_id,
                    provider=pool.provider,
                    region=pool.region,
                    gpu_type=pool.gpu_type,
                    gpu_count=placement.gpu_count,
                    start=placement.start,
                    end=placement.end,
                    estimated_cost_usd=placement.cost_usd,
                    workload_spec=specs[placement.workload_id],
                    offer=offer,
                    skypilot_task_yaml=task_yaml,
                )
            )

        manifest = (
            "# GridSynapse SkyPilot portfolio dry-run manifest\n"
            "# Planning artifact only. No provider inventory is reserved and no compute is "
            "launched.\n" + "\n---\n".join(task_documents)
        )
        estimated_cost = float(result.optimized.total_cost_usd or 0)
        plan = ProcurementPlan(
            schema_version="gridsynapse-procurement-plan-v1",
            procurement_plan_id=plan_id,
            recommendation_id=result.recommendation_id,
            scenario_id=request.scenario_id,
            input_hash=result.input_hash,
            idempotency_key=f"gridsynapse-{identity_hash}",
            status=ProcurementStatus.CREATED,
            requested_by=create.requested_by,
            max_spend_usd=create.max_spend_usd,
            estimated_total_cost_usd=estimated_cost,
            placements=placements,
            skypilot_manifest_yaml=manifest,
            execution_boundary=EXECUTION_BOUNDARY,
            created_at=now,
            updated_at=now,
        )
        self._plans[plan_id] = deepcopy(plan)
        self._contexts[plan_id] = (deepcopy(request), deepcopy(result), deepcopy(create))
        return deepcopy(plan)

    def get_plan(self, procurement_plan_id: str) -> ProcurementPlan:
        self._require_enabled()
        try:
            return deepcopy(self._plans[procurement_plan_id])
        except KeyError as error:
            raise ProcurementNotFoundError(procurement_plan_id) from error

    def verify_plan(self, procurement_plan_id: str) -> ProcurementPlan:
        self._require_enabled()
        plan = self.get_plan(procurement_plan_id)
        request, result, create = self._contexts[procurement_plan_id]
        now = self._now()
        checks: list[VerificationCheck] = []

        def add(
            check_id: str,
            passed: bool,
            severity: Literal["blocking", "warning", "information"],
            message: str,
        ) -> None:
            checks.append(
                VerificationCheck(
                    check_id=check_id,
                    passed=passed,
                    severity=severity,
                    message=message,
                )
            )

        add(
            "approved_recommendation",
            result.approval.status == "approved",
            "blocking",
            "The exact validated recommendation is advisor-approved."
            if result.approval.status == "approved"
            else "The recommendation is not approved.",
        )
        canonical_hash = _canonical_request_hash(request)
        hash_valid = (
            result.input_hash == canonical_hash
            and create.expected_input_hash == result.input_hash
            and plan.input_hash == result.input_hash
        )
        add(
            "input_hash_match",
            hash_valid,
            "blocking",
            "Request, recommendation, caller expectation, and procurement plan hashes match."
            if hash_valid
            else "The procurement plan no longer matches the optimization inputs.",
        )
        result_valid = result.status == "feasible" and result.validation.valid
        add(
            "validated_feasible_result",
            result_valid,
            "blocking",
            "The optimization is feasible and independently validated."
            if result_valid
            else "Only an independently validated feasible optimization can be procured.",
        )
        executable_fields_valid = all(
            placement.workload_spec.container_image
            and placement.workload_spec.command
            and all(part.strip() for part in placement.workload_spec.command)
            for placement in plan.placements
        )
        add(
            "executable_workload_fields",
            executable_fields_valid,
            "blocking",
            "Every placement has an image and command for manifest inspection."
            if executable_fields_valid
            else "Every placement requires a non-empty image and command.",
        )
        within_spend = plan.estimated_total_cost_usd <= plan.max_spend_usd
        add(
            "max_spend",
            within_spend,
            "blocking",
            f"Estimated compute cost ${plan.estimated_total_cost_usd:,.2f} is within the "
            f"${plan.max_spend_usd:,.2f} portfolio limit."
            if within_spend
            else f"Estimated compute cost ${plan.estimated_total_cost_usd:,.2f} exceeds the "
            f"${plan.max_spend_usd:,.2f} portfolio limit.",
        )

        for placement in plan.placements:
            for evidence_kind, source in (
                ("price", placement.offer.price_evidence),
                ("capacity", placement.offer.capacity_evidence),
            ):
                fresh = _source_is_fresh(source, now)
                age = _source_age_seconds(source, now)
                add(
                    f"{placement.placement_id}_{evidence_kind}_freshness",
                    fresh,
                    "blocking",
                    f"{evidence_kind.title()} evidence {source.source_id} is {age}s old and fresh."
                    if fresh
                    else f"{evidence_kind.title()} evidence {source.source_id} is stale at "
                    f"{age}s old (limit {source.freshness_seconds}s).",
                )
            add(
                f"{placement.placement_id}_planning_price",
                placement.offer.price_classification != "planning_only",
                "warning",
                "Price is an account-specific quote."
                if placement.offer.price_classification != "planning_only"
                else "Public catalog price is planning-only and must be refreshed before a "
                "future billable launch.",
            )
            add(
                f"{placement.placement_id}_inventory_evidence",
                placement.offer.executable_inventory,
                "warning",
                "Inventory evidence is executable."
                if placement.offer.executable_inventory
                else "Modeled capacity is not executable inventory and reserves no GPUs.",
            )

        add(
            "provider_credentials_absent",
            not plan.provider_credentials_present,
            "blocking",
            "No provider credentials are accepted, stored, or transmitted in portfolio mode.",
        )
        launch_disabled = not self.execution_enabled and not plan.live_execution_permitted
        add(
            "live_launch_disabled",
            launch_disabled,
            "blocking",
            "Live launch is disabled; verification can produce only a dry-run-ready plan."
            if launch_disabled
            else "Execution was enabled, but this portfolio module has no authorized live "
            "provider path.",
        )

        blocking_reasons = [
            check.message for check in checks if check.severity == "blocking" and not check.passed
        ]
        warnings = [
            check.message for check in checks if check.severity == "warning" and not check.passed
        ]
        valid = not blocking_reasons
        evidence_hash = _stable_hash(
            {
                "planId": plan.procurement_plan_id,
                "checks": [check.model_dump(mode="json", by_alias=True) for check in checks],
            }
        )
        verification = VerificationRecord(
            verification_id=f"verify-{evidence_hash[:16]}",
            procurement_plan_id=plan.procurement_plan_id,
            verified_at=now,
            valid_for_dry_run=valid,
            live_launch_allowed=False,
            checks=checks,
            blocking_reasons=blocking_reasons,
            warnings=warnings,
            evidence_hash=evidence_hash,
        )
        plan.verification = verification
        plan.status = (
            ProcurementStatus.DRY_RUN_READY if valid else ProcurementStatus.VERIFICATION_FAILED
        )
        plan.updated_at = now
        self._plans[procurement_plan_id] = deepcopy(plan)
        return deepcopy(plan)

    def transition_plan(
        self,
        procurement_plan_id: str,
        transition: ProcurementTransitionRequest,
    ) -> ProcurementPlan:
        self._require_enabled()
        plan = self.get_plan(procurement_plan_id)
        if plan.verification is None or not plan.verification.valid_for_dry_run:
            raise ProcurementTransitionError(
                "A valid dry-run verification is required before lifecycle simulation"
            )
        if not transition.simulation:
            raise ProcurementTransitionError(
                "Portfolio mode permits simulated transitions only; no provider call was made"
            )

        expected = {
            ProcurementAction.APPROVE_FOR_LAUNCH: ProcurementStatus.DRY_RUN_READY,
            ProcurementAction.START_PROVISIONING: ProcurementStatus.APPROVED_FOR_LAUNCH,
            ProcurementAction.MARK_RUNNING: ProcurementStatus.PROVISIONING,
            ProcurementAction.MARK_COMPLETED: ProcurementStatus.RUNNING,
            ProcurementAction.RECONCILE: ProcurementStatus.COMPLETED,
        }
        target = {
            ProcurementAction.APPROVE_FOR_LAUNCH: ProcurementStatus.APPROVED_FOR_LAUNCH,
            ProcurementAction.START_PROVISIONING: ProcurementStatus.PROVISIONING,
            ProcurementAction.MARK_RUNNING: ProcurementStatus.RUNNING,
            ProcurementAction.MARK_COMPLETED: ProcurementStatus.COMPLETED,
            ProcurementAction.RECONCILE: ProcurementStatus.RECONCILED,
        }
        if plan.status != expected[transition.action]:
            raise ProcurementTransitionError(
                f"Action {transition.action.value} requires status "
                f"{expected[transition.action].value}; current status is {plan.status.value}"
            )

        now = self._now()
        plan.status = target[transition.action]
        if transition.action == ProcurementAction.RECONCILE:
            simulated_actual = (
                transition.simulated_actual_cost_usd
                if transition.simulated_actual_cost_usd is not None
                else round(plan.estimated_total_cost_usd * 1.03, 2)
            )
            variance = round(simulated_actual - plan.estimated_total_cost_usd, 2)
            variance_percent = (
                round(variance / plan.estimated_total_cost_usd * 100, 2)
                if plan.estimated_total_cost_usd
                else None
            )
            reconciliation_hash = _stable_hash(
                {
                    "planId": plan.procurement_plan_id,
                    "estimated": plan.estimated_total_cost_usd,
                    "simulatedActual": simulated_actual,
                }
            )
            plan.reconciliation = ReconciliationReport(
                reconciliation_id=f"recon-{reconciliation_hash[:16]}",
                procurement_plan_id=plan.procurement_plan_id,
                estimated_total_cost_usd=plan.estimated_total_cost_usd,
                simulated_actual_cost_usd=simulated_actual,
                variance_usd=variance,
                variance_percent=variance_percent,
                workload_count=len(plan.placements),
                completed_workload_count=len(plan.placements),
                methodology=(
                    "Portfolio simulation compares the optimizer estimate with an explicitly "
                    "simulated actual cost. No provider invoice or usage record was queried."
                ),
                reconciled_at=now,
            )
        plan.updated_at = now
        self._plans[procurement_plan_id] = deepcopy(plan)
        return deepcopy(plan)

    def _require_enabled(self) -> None:
        if not self.procurement_enabled:
            raise ProcurementDisabledError("Procurement manifest and dry-run APIs are disabled")

    @staticmethod
    def _validate_recommendation(
        request: OptimizationRequest,
        result: OptimizationResult,
        create: ProcurementCreateRequest,
    ) -> None:
        if create.recommendation_id != result.recommendation_id:
            raise InvalidProcurementPlanError("Recommendation ID does not match the result")
        if result.status != "feasible" or not result.validation.valid:
            raise InvalidProcurementPlanError(
                "Only a validated feasible recommendation can create a procurement plan"
            )
        if result.approval.status != "approved":
            raise InvalidProcurementPlanError(
                "The exact recommendation must be approved before procurement planning"
            )
        canonical_hash = _canonical_request_hash(request)
        if result.input_hash != canonical_hash or create.expected_input_hash != result.input_hash:
            raise InvalidProcurementPlanError(
                "Recommendation, request, and expected input hashes must match"
            )

    @staticmethod
    def _offer_snapshot(pool, captured_at: datetime) -> OfferSnapshot:
        price_source = pool.metric_sources.price if pool.metric_sources else pool.source
        capacity_source = pool.metric_sources.capacity if pool.metric_sources else pool.source
        price_classification = (
            "account_specific_quote" if price_source.source_type == "contract" else "planning_only"
        )
        inventory_executable = (
            capacity_source.source_type in {"observed", "contract"}
            and "modeled" not in capacity_source.unit.lower()
        )
        offer_hash = _stable_hash(
            {
                "poolId": pool.id,
                "price": pool.price_usd_per_gpu_hour,
                "priceSource": price_source.model_dump(mode="json", by_alias=True),
                "capacitySource": capacity_source.model_dump(mode="json", by_alias=True),
            }
        )
        notes = []
        if price_classification == "planning_only":
            notes.append("Catalog price is for planning and is not an executable quote.")
        if not inventory_executable:
            notes.append("Capacity is modeled and does not represent reservable inventory.")
        return OfferSnapshot(
            offer_id=f"offer-{offer_hash[:16]}",
            provider=pool.provider,
            pool_id=pool.id,
            region=pool.region,
            gpu_type=pool.gpu_type,
            price_usd_per_gpu_hour=pool.price_usd_per_gpu_hour,
            price_classification=price_classification,
            inventory_classification=(
                "verified_executable" if inventory_executable else "modeled_not_executable"
            ),
            price_evidence=price_source,
            capacity_evidence=capacity_source,
            captured_at=captured_at,
            executable_inventory=inventory_executable,
            evidence_notes=notes,
        )

    @staticmethod
    def _skypilot_task_yaml(
        placement_id: str,
        placement,
        provider: str,
        region: str,
        gpu_type: str,
        spec: ExecutableWorkloadSpec,
    ) -> str:
        cloud = _skypilot_cloud(provider)
        lines = [
            f"name: {_slug(placement_id)}",
            "resources:",
            f"  cloud: {_yaml_string(cloud)}",
            f"  region: {_yaml_string(region)}",
            f"  accelerators: {_yaml_string(f'{gpu_type}:{placement.gpu_count}')}",
            f"  image_id: {_yaml_string(f'docker:{spec.container_image}')}",
            "  use_spot: false",
        ]
        if spec.working_directory:
            lines.append(f"workdir: {_yaml_string(spec.working_directory)}")
        if spec.environment:
            lines.append("envs:")
            for key, value in sorted(spec.environment.items()):
                lines.append(f"  {key}: {_yaml_string(value)}")
        if spec.storage_mounts:
            lines.append("file_mounts:")
            for remote_path, source in sorted(spec.storage_mounts.items()):
                lines.append(f"  {_yaml_string(remote_path)}: {_yaml_string(source)}")
        lines.extend(
            [
                "run: |",
                f"  {shlex.join(spec.command)}",
            ]
        )
        if spec.secret_refs:
            lines.append(
                "# Secret references are intentionally omitted from this planning artifact "
                f"({len(spec.secret_refs)} configured)."
            )
        return "\n".join(lines) + "\n"
