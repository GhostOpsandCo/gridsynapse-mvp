export type ObjectiveProfile = "cost" | "balanced" | "carbon" | "sla";

export interface SourceRef {
  sourceId: string;
  sourceType:
    | "synthetic"
    | "observed"
    | "forecast"
    | "contract"
    | "public_snapshot"
    | "estimated";
  sourceUrl: string | null;
  observedAt: string;
  unit: string;
  freshnessSeconds: number;
  confidence: "low" | "medium" | "high";
}

export interface Horizon {
  start: string;
  end: string;
  slotMinutes: number;
}

export interface Workload {
  id: string;
  name: string;
  workloadType: "training" | "fine_tuning" | "embeddings" | "batch_inference";
  gpuType: string;
  gpuCount: number;
  durationMinutes: number;
  earliestStart: string;
  deadline: string;
  priority: number;
  interruptible: boolean;
  checkpointable: boolean;
  allowedRegions: string[];
  maxLatencyMs: number | null;
  maxBudgetUsd: number | null;
  baselinePoolId: string | null;
}

export interface ResourcePool {
  id: string;
  provider: string;
  cluster: string;
  region: string;
  gpuType: string;
  capacityBySlot: number[];
  priceUsdPerGpuHour: number;
  gpuPowerKw: number;
  pue: number;
  carbonGramsPerKwhBySlot: number[];
  latencyMs: number;
  availabilityBps: number;
  egressUsdPerGb: number;
  source: SourceRef;
  metricSources: {
    price: SourceRef;
    carbon: SourceRef;
    capacity: SourceRef;
    latency: SourceRef;
    availability: SourceRef;
  } | null;
}

export interface OptimizationRequest {
  schemaVersion: string;
  scenarioId: string;
  horizon: Horizon;
  policy: {
    profile: ObjectiveProfile;
    weights: { costBps: number; carbonBps: number; delayBps: number; riskBps: number };
    maxSolverSeconds: number;
  };
  workloads: Workload[];
  resourcePools: ResourcePool[];
}

export interface Placement {
  workloadId: string;
  poolId: string;
  start: string;
  end: string;
  gpuCount: number;
  costUsd: number;
  energyKwh: number;
  emissionsKgCo2e: number;
  delayMinutes: number;
  reasons: string[];
}

export interface Plan {
  status: "feasible" | "infeasible";
  placements: Placement[];
  totalCostUsd: number;
  totalEnergyKwh: number;
  totalEmissionsKgCo2e: number;
  totalDelayMinutes: number;
  capacityRiskScore: number;
}

export interface OptimizationResult {
  schemaVersion: string;
  recommendationId: string;
  scenarioId: string;
  status: "feasible" | "partial" | "infeasible" | "error";
  inputHash: string;
  solver: {
    backend: string;
    version: string;
    durationMs: number;
    objectiveProfile: ObjectiveProfile;
  };
  baseline: Plan;
  optimized: Plan;
  deltas: {
    costUsd: number;
    costPercent: number;
    emissionsKgCo2e: number;
    emissionsPercent: number;
    delayMinutes: number;
  };
  infeasibleReasons: string[];
  validation: { valid: boolean; checks: string[] };
  approval: {
    status: "not_reviewed" | "approved" | "revision_required" | "invalidated";
    approvedBy: string | null;
    approvedAt: string | null;
  };
}

export interface Explanation {
  recommendationId: string;
  headline: string;
  summary: string;
  decisionFactors: string[];
  tradeoffs: string[];
  warnings: string[];
  operatorAction: string;
  generatedBy: string;
}

export interface DataHealth {
  scenarioId: string;
  status: "healthy" | "stale" | "warning" | "blocked";
  sourceCount: number;
  staleSourceCount: number;
  sources: Array<{
    poolId: string;
    metric: string;
    sourceId: string;
    sourceType: string;
    sourceUrl: string | null;
    unit: string;
    observedAt: string;
    ageSeconds: number;
    freshnessSeconds: number;
    confidence: string;
    stale: boolean;
  }>;
}

export interface LiveMarketSnapshot {
  scenario: OptimizationRequest;
  health: DataHealth;
  generatedAt: string;
  marketMode: "hybrid-live";
  warnings: string[];
  sources: {
    pricing: string;
    carbon: string;
    capacity: string;
  };
}

export interface PersistenceStatus {
  backend: "memory" | "supabase" | "unavailable";
  durable: boolean;
  detail: string;
}

export interface HealthResponse {
  status: "healthy";
  service: string;
  version: string;
  persistence: PersistenceStatus;
  procurement?: {
    enabled: boolean;
    mode: "portfolio_dry_run";
    executionEnabled: boolean;
    liveProviderCallsAvailable: false;
  };
}

export interface ExecutableWorkloadSpec {
  workloadId: string;
  containerImage: string;
  command: string[];
  workingDirectory: string | null;
  environment: Record<string, string>;
  secretRefs: string[];
  storageMounts: Record<string, string>;
  checkpointUri: string | null;
  retryLimit: number;
  cleanupPolicy: "delete_compute" | "retain_storage";
}

export interface OfferSnapshot {
  offerId: string;
  provider: string;
  poolId: string;
  region: string;
  gpuType: string;
  priceUsdPerGpuHour: number;
  currency: "USD";
  priceClassification: "planning_only" | "account_specific_quote";
  inventoryClassification: "modeled_not_executable" | "verified_executable";
  priceEvidence: SourceRef;
  capacityEvidence: SourceRef;
  capturedAt: string;
  executableInventory: boolean;
  evidenceNotes: string[];
}

export interface VerificationCheck {
  checkId: string;
  passed: boolean;
  severity: "blocking" | "warning" | "information";
  message: string;
}

export interface VerificationRecord {
  verificationId: string;
  procurementPlanId: string;
  verifiedAt: string;
  validForDryRun: boolean;
  liveLaunchAllowed: false;
  mode: "portfolio_dry_run";
  checks: VerificationCheck[];
  blockingReasons: string[];
  warnings: string[];
  evidenceHash: string;
}

export type ProcurementStatus =
  | "created"
  | "verification_failed"
  | "dry_run_ready"
  | "approved_for_launch"
  | "provisioning"
  | "running"
  | "completed"
  | "reconciled";

export type ProcurementAction =
  | "approve_for_launch"
  | "start_provisioning"
  | "mark_running"
  | "mark_completed"
  | "reconcile";

export interface ProcurementPlacement {
  placementId: string;
  workloadId: string;
  poolId: string;
  provider: string;
  region: string;
  gpuType: string;
  gpuCount: number;
  start: string;
  end: string;
  estimatedCostUsd: number;
  workloadSpec: ExecutableWorkloadSpec;
  offer: OfferSnapshot;
  skypilotTaskYaml: string;
}

export interface ReconciliationReport {
  reconciliationId: string;
  procurementPlanId: string;
  estimatedTotalCostUsd: number;
  simulatedActualCostUsd: number;
  varianceUsd: number;
  variancePercent: number | null;
  workloadCount: number;
  completedWorkloadCount: number;
  provenance: "deterministic_portfolio_simulation";
  methodology: string;
  reconciledAt: string;
}

export interface ProcurementPlan {
  schemaVersion: "gridsynapse-procurement-plan-v1";
  procurementPlanId: string;
  recommendationId: string;
  scenarioId: string;
  inputHash: string;
  idempotencyKey: string;
  mode: "portfolio_dry_run";
  status: ProcurementStatus;
  requestedBy: string;
  maxSpendUsd: number;
  estimatedTotalCostUsd: number;
  currency: "USD";
  placements: ProcurementPlacement[];
  skypilotManifestYaml: string;
  verification: VerificationRecord | null;
  reconciliation: ReconciliationReport | null;
  simulationOnly: true;
  liveExecutionPermitted: false;
  providerCredentialsPresent: false;
  executionBoundary: string;
  createdAt: string;
  updatedAt: string;
}

export interface DecisionHistoryItem {
  recommendationId: string;
  scenarioId: string;
  objectiveProfile: ObjectiveProfile;
  workloadCount: number;
  totalCostUsd: number;
  costDeltaUsd: number;
  approvalStatus: OptimizationResult["approval"]["status"];
  approvedBy: string | null;
  approvedAt: string | null;
  createdAt: string;
  updatedAt: string;
}
