import type {
  DataHealth,
  DecisionHistoryItem,
  Explanation,
  HealthResponse,
  LiveMarketSnapshot,
  OptimizationRequest,
  OptimizationResult,
  ProcurementAction,
  ProcurementPlan,
  ExecutableWorkloadSpec,
} from "./types";

export const API_URL = "/api/proxy";

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(`${API_URL}${path}`, {
    ...init,
    headers: { "Content-Type": "application/json", ...init?.headers },
  });
  if (!response.ok) {
    const body = await response.json().catch(() => ({ detail: "Request failed" }));
    throw new Error(body.detail ?? `Request failed with ${response.status}`);
  }
  return response.json() as Promise<T>;
}

export const api = {
  health: () => request<HealthResponse>("/health"),
  decisionHistory: (limit = 12) =>
    request<DecisionHistoryItem[]>(`/api/v2/decision-history?limit=${limit}`),
  liveMarket: (refresh = false) =>
    request<LiveMarketSnapshot>(`/api/v2/live-market/scenario?refresh=${refresh}`),
  scenario: (id: string) => request<OptimizationRequest>(`/api/v2/scenarios/${id}`),
  dataHealth: (id: string) => request<DataHealth>(`/api/v2/scenarios/${id}/data-health`),
  validate: (body: OptimizationRequest) =>
    request<{ valid: boolean; scenarioId: string; workloadCount: number; resourcePoolCount: number; slotCount: number }>(
      "/api/v2/scenarios/validate",
      { method: "POST", body: JSON.stringify(body) },
    ),
  optimize: (body: OptimizationRequest) =>
    request<OptimizationResult>("/api/v2/optimizations", {
      method: "POST",
      body: JSON.stringify(body),
    }),
  explanation: (id: string) =>
    request<Explanation>(`/api/v2/optimizations/${id}/explanation`),
  optimization: (id: string) =>
    request<OptimizationResult>(`/api/v2/optimizations/${id}`),
  approve: (id: string, status: "approved" | "revision_required") =>
    request<OptimizationResult>(`/api/v2/optimizations/${id}/approval`, {
      method: "POST",
      body: JSON.stringify({ status, actor: "operator@gridsynapse.io" }),
    }),
  createProcurementPlan: (body: {
    recommendationId: string;
    expectedInputHash: string;
    requestedBy: string;
    maxSpendUsd: number;
    workloadSpecs: ExecutableWorkloadSpec[];
  }) =>
    request<ProcurementPlan>("/api/v2/procurement/plans", {
      method: "POST",
      body: JSON.stringify(body),
    }),
  procurementPlan: (id: string) =>
    request<ProcurementPlan>(`/api/v2/procurement/plans/${id}`),
  verifyProcurementPlan: (id: string) =>
    request<ProcurementPlan>(`/api/v2/procurement/plans/${id}/verify`, {
      method: "POST",
    }),
  transitionProcurementPlan: (
    id: string,
    action: ProcurementAction,
    simulatedActualCostUsd?: number,
  ) =>
    request<ProcurementPlan>(`/api/v2/procurement/plans/${id}/transitions`, {
      method: "POST",
      body: JSON.stringify({
        action,
        actor: "portfolio-operator@gridsynapse.io",
        simulation: true,
        simulatedActualCostUsd,
      }),
    }),
  exportUrl: (id: string, format: "json" | "csv") =>
    `${API_URL}/api/v2/optimizations/${id}/export?format=${format}`,
};
